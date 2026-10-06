"""Сжатие фото и видео: логика без окна, чтобы её можно было проверять тестами.

Два шага. «Подготовить» — сжатые копии складываются в рабочую папку, оригиналы не трогаются;
каждая копия проверена: в строгом режиме пиксели совпадают байт в байт, в режиме «без видимых
потерь» — числом SSIM. «Заменить» — оригинал уходит в Корзину, на его место встаёт сжатый файл
с теми же датами. Тип файла (расширение) не меняется никогда.
"""

import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from dataclasses import dataclass, field

import dupcore
from dupcore import Cancelled, _check
from i18n import tr

JPEG_EXT = {".jpg", ".jpeg", ".jfif"}
PNG_EXT = {".png"}
PHOTO_EXT = JPEG_EXT | PNG_EXT
# Только контейнеры, в которые AV1 кладётся без смены расширения, а звук копируется как есть.
VIDEO_EXT = {".mp4", ".m4v", ".mov", ".mkv", ".webm"}

MODES = {"lossless": "Строго без потерь", "visual": "Без видимых потерь"}
KINDS = {"photo": "Фото", "video": "Видео"}
MODE_KINDS = {"lossless": {"photo"}, "visual": {"photo", "video"}}

# Меньше этого не заменяем: менять файл ради пары процентов — не стоит того.
MIN_GAIN = {"lossless": 0.02, "visual": 0.10}

# «Без видимых потерь» для фото: качество JPEG по очереди, берётся первое, что прошло проверку.
PHOTO_QUALITIES = (85, 90)
# Проверка фото — SSIM яркости блоками 8×8 на кадре, уменьшенном вдвое (так фото смотрят: целиком на экране):
# среднее и худший 1 % блоков (испорченное место — видно здесь). Плюс «пол» на полном размере против сильной
# местной порчи. На полном размере SSIM считает потерей пропажу шумового зерна сенсора: 107 снимков
# Galaxy S24 Ultra (качество 96–97) при качестве 85 — медиана 0,959, хотя при 150 % разница еле заметна;
# вдвое — минимум 0,986 / 0,964, при 100 % худший 1 % — минимум 0,833 (калибровка 6.10.2026).
PHOTO_SSIM_MEAN = 0.985
PHOTO_SSIM_LOW = 0.96
PHOTO_SSIM_FLOOR = 0.80
# Видео: AV1 (SVT-AV1). CRF — качество (меньше — лучше), preset — скорость (больше — быстрее).
VIDEO_CRF = 28
VIDEO_PRESET = 8
VIDEO_SSIM = 0.97

WORK = os.path.join(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(), "Duplio", "work")
RESERVE = 2 * 1024 ** 3          # столько места оставляем свободным на диске рабочей папки

CREATE_NO_WINDOW = 0x08000000
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
IDLE_PRIORITY_CLASS = 0x00000040


class Skip(Exception):
    """Файл не сжимаем — с понятной причиной (русский шаблон для tr)."""


# ---------------------------------------------------------------- программы-помощники

def _base():
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def tool(name):
    """Путь к jpegtran / oxipng / ffmpeg / ffprobe из third_party или None, если их нет."""
    folder = "ffmpeg" if name in ("ffmpeg", "ffprobe") else name
    path = os.path.join(_base(), "third_party", folder, name + ".exe")
    return path if os.path.exists(path) else None


def _env():
    # jpegtran и oxipng нужна VCRUNTIME140.dll — в собранной программе она лежит в _internal.
    env = dict(os.environ)
    env["PATH"] = _base() + os.pathsep + env.get("PATH", "")
    return env


def _run(args, cancel=None, gentle=False, on_line=None, ok_codes=(0,), src=None, dst=None):
    """Запустить программу без окна; cancel — остановить её. Возвращает stderr; ошибка — Skip.

    src / dst — файлы, которые программа читает со входа и пишет на выход: так ей не нужно знать их
    имена (старые программы на C открывают файлы по ANSI-имени и не видят иероглифы, эмодзи, а на
    английской Windows — и кириллицу).
    """
    flags = CREATE_NO_WINDOW | (IDLE_PRIORITY_CLASS if gentle else BELOW_NORMAL_PRIORITY_CLASS)
    err_file = tempfile.TemporaryFile()
    fin = open(src, "rb") if src else None
    fout = open(dst, "wb") if dst else None
    try:
        p = subprocess.Popen(args, stdin=fin or subprocess.DEVNULL,
                             stdout=fout or (subprocess.PIPE if on_line else subprocess.DEVNULL),
                             stderr=err_file, creationflags=flags, env=_env())
        reader = None
        if on_line:
            def pump():
                for raw in p.stdout:
                    on_line(raw.decode("utf-8", "replace").strip())
            reader = threading.Thread(target=pump, daemon=True)
            reader.start()
        while True:
            try:
                p.wait(0.2)
                break
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel.is_set():
                    p.kill()
                    p.wait()
                    raise Cancelled
        if reader:
            reader.join(5)
        err_file.seek(0)
        err = err_file.read().decode("utf-8", "replace")
    finally:
        err_file.close()
        for f in (fin, fout):
            if f:
                f.close()
    if p.returncode not in ok_codes:
        last = err.strip().splitlines()[-1] if err.strip() else tr("код {n}", n=p.returncode)
        raise Skip(f"{os.path.basename(args[0])}: {last[:200]}")
    return err


# ---------------------------------------------------------------- файлы и задания

@dataclass(slots=True)
class Job:
    path: str
    size: int
    mtime: float
    out: str = ""             # готовый уменьшенный файл в рабочей папке
    new_size: int = 0
    how: str = ""             # что сделано: «перепаковка», «качество 85», «AV1»
    check: str = ""           # чем проверено: "pixels" — пиксели совпали; "ssim" — по числу score
    score: float = 0.0
    skip: str = ""            # почему не сжали

    @property
    def kind(self):
        ext = os.path.splitext(self.path)[1].lower()
        return "video" if ext in VIDEO_EXT else "png" if ext in PNG_EXT else "jpeg"

    @property
    def is_video(self):
        return self.kind == "video"

    @property
    def is_image(self):
        return not self.is_video

    @property
    def saved(self):
        return self.size - self.new_size if self.out else 0


@dataclass
class PrepResult:
    jobs: list = field(default_factory=list)       # все найденные файлы
    files_seen: int = 0
    bytes_seen: int = 0
    cloud_skipped: int = 0
    errors: list = field(default_factory=list)     # (путь, текст) — папки и файлы, которые не прочитались
    cancelled: bool = False
    no_space: bool = False


def wanted_ext(kinds):
    exts = set()
    if "photo" in kinds:
        exts |= PHOTO_EXT
    if "video" in kinds:
        exts |= VIDEO_EXT
    return exts


def missing_tools(kinds, mode):
    """Каких программ не хватает для выбранного (в сборке есть все; из исходников — после fetch_tools)."""
    need = []
    if "photo" in kinds:
        need += ["jpegtran", "oxipng"] if mode == "lossless" else ["oxipng"]
    if "video" in kinds and mode == "visual":
        need += ["ffmpeg", "ffprobe"]
    return [n for n in need if not tool(n)]


def _work_name(path):
    h = hashlib.blake2b(os.path.normcase(os.path.abspath(path)).encode("utf-8"), digest_size=6).hexdigest()
    return os.path.join(WORK, f"{h}_{os.path.basename(path)}")


def clean_work():
    shutil.rmtree(WORK, ignore_errors=True)


def free_space(path):
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


# ---------------------------------------------------------------- проверка: пиксели и SSIM

def _decode(path):
    from PySide6.QtGui import QImage, QImageReader
    r = QImageReader(path)
    r.setAutoTransform(False)            # сравниваем данные файла, а не то, как его повернёт просмотрщик
    img = r.read()
    return img if not img.isNull() else QImage()


def _wide_formats():
    from PySide6.QtGui import QImage
    names = ("Format_Grayscale16", "Format_RGBX64", "Format_RGBA64", "Format_RGBA64_Premultiplied",
             "Format_BGR30", "Format_A2BGR30_Premultiplied", "Format_RGB30", "Format_A2RGB30_Premultiplied",
             "Format_RGBX16FPx4", "Format_RGBA16FPx4", "Format_RGBA16FPx4_Premultiplied",
             "Format_RGBX32FPx4", "Format_RGBA32FPx4", "Format_RGBA32FPx4_Premultiplied")
    return {getattr(QImage, n) for n in names if hasattr(QImage, n)}


def same_pixels(a, b):
    """Пиксели двух картинок совпадают байт в байт (после приведения к одному формату).

    Формат — без предумножения альфы: иначе цвет под полностью прозрачными точками не сравнивался бы.
    Больше 8 бит на канал — сравниваем в 16 битах, чтобы не потерять разницу при приведении.
    """
    import numpy as np
    from PySide6.QtGui import QImage
    ia, ib = _decode(a), _decode(b)
    if ia.isNull() or ib.isNull() or ia.size() != ib.size():
        return False
    wide = _wide_formats()
    fmt = QImage.Format_RGBA64 if ia.format() in wide or ib.format() in wide else QImage.Format_ARGB32
    ia, ib = ia.convertToFormat(fmt), ib.convertToFormat(fmt)
    row = ia.width() * (8 if fmt == QImage.Format_RGBA64 else 4)
    va = np.frombuffer(ia.constBits(), np.uint8).reshape(ia.height(), ia.bytesPerLine())[:, :row]
    vb = np.frombuffer(ib.constBits(), np.uint8).reshape(ib.height(), ib.bytesPerLine())[:, :row]
    return bool(np.array_equal(va, vb))


def _luma(path):
    import numpy as np
    from PIL import Image
    with Image.open(path) as im:
        return np.asarray(im.convert("L"), dtype=np.float32)


def half(a):
    """Яркость, уменьшенная вдвое усреднением 2×2."""
    h, w = a.shape[0] // 2 * 2, a.shape[1] // 2 * 2
    return a[:h, :w].reshape(h // 2, 2, w // 2, 2).mean((1, 3))


def photo_check(ref, cur):
    """(прошло ли, SSIM вдвое — среднее) для яркости оригинала ref и сжатого cur."""
    mean, low = ssim(half(ref), half(cur))
    _, floor = ssim(ref, cur)
    return mean >= PHOTO_SSIM_MEAN and low >= PHOTO_SSIM_LOW and floor >= PHOTO_SSIM_FLOOR, mean


def ssim(a, b, block=8):
    """SSIM по яркости блоками block×block: (среднее, худший 1 % блоков). a, b — массивы одного размера."""
    import numpy as np
    if a.shape != b.shape:
        return 0.0, 0.0
    h, w = (a.shape[0] // block) * block, (a.shape[1] // block) * block
    if not h or not w:
        return (1.0, 1.0) if np.array_equal(a, b) else (0.0, 0.0)
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    parts = []
    step = block * 64                         # полосами: на 50 Мп не съедаем гигабайты памяти
    for y in range(0, h, step):
        x = a[y:min(y + step, h), :w].reshape(-1, block, w // block, block).astype(np.float64)
        z = b[y:min(y + step, h), :w].reshape(-1, block, w // block, block).astype(np.float64)
        mx, mz = x.mean((1, 3)), z.mean((1, 3))
        vx = (x * x).mean((1, 3)) - mx * mx
        vz = (z * z).mean((1, 3)) - mz * mz
        cov = (x * z).mean((1, 3)) - mx * mz
        parts.append(((2 * mx * mz + c1) * (2 * cov + c2) / ((mx * mx + mz * mz + c1) * (vx + vz + c2))).ravel())
    s = np.concatenate(parts)
    return float(s.mean()), float(np.percentile(s, 1))


# ---------------------------------------------------------------- JPEG: служебные блоки

def jpeg_segments(data):
    """Блоки JPEG до начала сжатых данных: [(маркер, байты блока целиком)], и смещение SOS."""
    if data[:2] != b"\xff\xd8":
        raise Skip("файл не похож на JPEG")
    out, i = [], 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            raise Skip("испорченный JPEG")
        marker = data[i + 1]
        if marker == 0xFF:                    # заполнитель
            i += 1
            continue
        if marker == 0xDA:                    # SOS — дальше сжатые данные
            return out, i
        n = int.from_bytes(data[i + 2:i + 4], "big")
        out.append((marker, data[i:i + 2 + n]))
        i += 2 + n
    raise Skip("испорченный JPEG")


def jpeg_tail(data):
    """Байты после конца основной картинки JPEG (после её EOI); b"", если там пусто или одни нули.

    Там телефоны хранят карту яркости Ultra HDR, второй снимок (MPO), видео «живого фото», служебную
    запись Samsung (SEF: время съёмки в UTC и т. п.). jpegtran и пересжатие хвост выбрасывают — а пиксели
    основного кадра при этом совпадают, и проверка этого не видит. Не разобрался в файле — b"": дальше
    решит проверка пикселей.
    """
    try:
        _, i = jpeg_segments(data)
    except Skip:
        return b""
    n = len(data)
    while i + 4 <= n:                         # i — на маркере после заголовков
        marker = data[i + 1]
        if marker == 0xD9:                    # EOI — конец основной картинки
            tail = data[i + 2:]
            return tail if tail.strip(b"\x00") else b""
        if 0xD0 <= marker <= 0xD7 or marker in (0x01, 0xFF):
            i += 2 if marker != 0xFF else 1
        else:
            i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
        if marker == 0xDA or 0xD0 <= marker <= 0xD7:
            # сжатые данные: идём до следующего маркера (FF00 — байт данных, FFD0–FFD7 — перезапуск)
            while i + 1 < n and not (data[i] == 0xFF and data[i + 1] not in (0x00, 0xFF)):
                i += 1
        while i + 1 < n and data[i] == 0xFF and data[i + 1] == 0xFF:    # заполнители
            i += 1
    return b""


# Вторая картинка (Ultra HDR, MPO) или видео («живое фото») в хвосте: их положение записано смещениями
# от начала файла — после пересжатия основного кадра они указывали бы мимо. Такие файлы не трогаем.
FOREIGN_TAIL = (b"\xff\xd8\xff", b"ftyp")
ATTACHED = "к снимку приложены HDR-карта, второй снимок или видео «живого фото» — их бы потерять"


META = set(range(0xE0, 0xEE)) | {0xEF, 0xFE}    # APP0–APP13, APP15, COM; APP14 (Adobe) — от кодировщика


def with_meta(new, orig):
    """Новый JPEG со всеми служебными блоками оригинала (EXIF, ICC, XMP, IPTC, комментарии) — байт в байт."""
    o_segs, _ = jpeg_segments(orig)
    n_segs, sos = jpeg_segments(new)
    keep = [s for m, s in o_segs if m in META]
    rest = [s for m, s in n_segs if m not in META]
    return b"\xff\xd8" + b"".join(keep) + b"".join(rest) + new[sos:]


_STD_LUMA = [16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56,
             14, 17, 22, 29, 51, 87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92,
             49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99]


def jpeg_quality(im):
    """Примерное качество, с которым снят JPEG (по таблице яркости), или None."""
    try:
        table = list(im.quantization[0])
    except (AttributeError, KeyError, IndexError, TypeError):
        return None
    if len(table) != 64:
        return None
    # Порядок значений в таблице и эталоне может различаться (зигзаг), но среднее отношение от него не зависит.
    scale = 100.0 * sum(table) / sum(_STD_LUMA)
    q = (200 - scale) / 2 if scale <= 100 else 5000 / scale
    return max(1, min(100, round(q)))


# ---------------------------------------------------------------- сжатие одного файла

def _jpeg_lossless(job, dst, cancel, gentle):
    best = None
    for i, extra in enumerate((["-optimize"], ["-optimize", "-progressive"])):
        out = f"{dst}.{i}"
        # Код 2 — предупреждение («лишние байты» и т. п., частое у камер): файл всё равно собран,
        # а совпадение пикселей проверяется после.
        _run([tool("jpegtran"), "-copy", "all", *extra], cancel, gentle, ok_codes=(0, 2), src=job.path, dst=out)
        if not os.path.exists(out) or not os.path.getsize(out):
            raise Skip("jpegtran не собрал файл")
        if best is None or os.path.getsize(out) < os.path.getsize(best[0]):
            if best:
                os.remove(best[0])
            best = (out, tr("перепаковка (progressive)") if i else tr("перепаковка"))
        else:
            os.remove(out)
    os.replace(best[0], dst)
    job.how = best[1]


def _png(job, dst, cancel, gentle, threads):
    # --strip none: все служебные блоки (цветовой профиль, тексты, EXIF) остаются; -a не ставим —
    # цвет под прозрачными точками не меняется, и проверка пикселей это подтверждает.
    _run([tool("oxipng"), "-o", "2", "--strip", "none", "-t", str(threads), "-q", "--out", dst, job.path],
         cancel, gentle)
    job.how = tr("перепаковка PNG")


def _jpeg_visual(job, dst):
    from PIL import Image, JpegImagePlugin
    with open(job.path, "rb") as f:
        orig = f.read()
    with Image.open(job.path) as im:
        if im.mode not in ("RGB", "L"):                 # CMYK и прочее — редкость, а цвета легко исказить
            raise Skip("необычный JPEG — не трогаю")
        src_q = jpeg_quality(im)
        sampling = JpegImagePlugin.get_sampling(im)
        im.load()
        ref = __import__("numpy").asarray(im.convert("L"), dtype="float32")
        tried = False
        for q in PHOTO_QUALITIES:
            if src_q is not None and q >= src_q:       # снят с тем же качеством или хуже — выигрыша не будет
                continue
            tried = True
            tmp = dst + ".enc"
            im.save(tmp, "JPEG", quality=q, optimize=True, progressive=True,
                    subsampling=sampling if sampling in (0, 1, 2) else 2)
            with open(tmp, "rb") as f:
                data = with_meta(f.read(), orig)
            os.remove(tmp)
            with open(dst, "wb") as f:
                f.write(data)
            ok, mean = photo_check(ref, _luma(dst))
            if ok:
                job.how, job.check, job.score = tr("JPEG, качество {q}", q=q), "ssim", mean
                return
            job.score = mean
        if not tried:
            raise Skip("уже сжат сильно — дальше будут видны потери")
        os.remove(dst)
        raise Skip("без видимых потерь не сжимается")


def probe(path):
    out = subprocess.run([tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_streams", "-show_format",
                          path], capture_output=True, creationflags=CREATE_NO_WINDOW, env=_env())
    if out.returncode != 0:
        raise Skip("видео не открывается")
    return json.loads(out.stdout.decode("utf-8", "replace") or "{}")


def _video_stream(info):
    for s in info.get("streams", []):
        if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic"):
            return s
    return None


def _video(job, dst, cancel, gentle, threads, on_part):
    info = probe(job.path)
    v = _video_stream(info)
    if not v:
        raise Skip("в файле нет видео")
    if v.get("codec_name") == "av1":
        raise Skip("уже в AV1")
    if v.get("color_transfer") in ("smpte2084", "arib-std-b67") or any(
            "DOVI" in str(sd.get("side_data_type", "")).upper() for sd in v.get("side_data_list", [])):
        raise Skip("HDR-видео — не трогаю, чтобы не испортить цвета")
    try:
        duration = float(info.get("format", {}).get("duration") or v.get("duration") or 0)
    except ValueError:
        duration = 0
    deep = "10" in v.get("pix_fmt", "") or "12" in v.get("pix_fmt", "") or int(v.get("bits_per_raw_sample") or 8) > 8
    ext = os.path.splitext(job.path)[1].lower()
    args = [tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-i", job.path,
            "-map", "0:V:0", "-map", "0:a?", "-map_metadata", "0", "-map_chapters", "0",
            "-c:v", "libsvtav1", "-crf", str(VIDEO_CRF), "-preset", str(VIDEO_PRESET),
            "-svtav1-params", f"lp={threads}",
            "-pix_fmt", "yuv420p10le" if deep else "yuv420p", "-c:a", "copy"]
    if ext in (".mp4", ".m4v", ".mov"):
        args += ["-movflags", "+faststart+use_metadata_tags"]
    args += ["-progress", "pipe:1", "-nostats", dst]

    def line(s):
        if s.startswith("out_time_us=") and duration > 0:
            try:
                on_part(min(1.0, int(s.split("=", 1)[1]) / 1e6 / duration) * 0.85)
            except ValueError:
                pass
    _run(args, cancel, gentle, on_line=line)
    new = probe(dst)
    nv = _video_stream(new)
    try:
        new_dur = float(new.get("format", {}).get("duration") or 0)
    except ValueError:
        new_dur = 0
    n_audio = sum(s.get("codec_type") == "audio" for s in info.get("streams", []))
    n_audio_new = sum(s.get("codec_type") == "audio" for s in new.get("streams", []))
    if not nv or n_audio != n_audio_new or (duration and abs(new_dur - duration) > max(0.5, duration * 0.01)):
        raise Skip("после сжатия видео не сходится с оригиналом (длина или звук)")
    job.score = video_ssim(job.path, dst, cancel, gentle, threads)
    on_part(1.0)
    job.how, job.check = tr("AV1, качество CRF {crf}", crf=VIDEO_CRF), "ssim"
    if job.score < VIDEO_SSIM:
        raise Skip("без видимых потерь не сжимается")


def video_ssim(a, b, cancel=None, gentle=False, threads=4):
    """Средний SSIM всех кадров двух видео (ffmpeg, фильтр ssim)."""
    err = _run([tool("ffmpeg"), "-hide_banner", "-nostdin", "-threads", str(threads), "-i", b, "-i", a,
                "-lavfi", "[0:V:0]setpts=PTS-STARTPTS[x];[1:V:0]setpts=PTS-STARTPTS[y];[x][y]ssim",
                "-f", "null", "-"], cancel, gentle)
    m = re.findall(r"All:([0-9.]+)", err)
    if not m:
        raise Skip("не удалось сравнить видео с оригиналом")
    return float(m[-1])


def prepare_one(job, mode, cancel=None, gentle=False, threads=1, on_part=lambda f: None):
    """Сжать один файл в рабочую папку и проверить. Успех — job.out; нет — job.skip с причиной."""
    os.makedirs(WORK, exist_ok=True)
    dst = _work_name(job.path)
    try:
        st = os.stat(job.path)
        if st.st_size != job.size or st.st_mtime != job.mtime:
            raise Skip("файл изменился")
        if st.st_file_attributes & 0x1:                   # «только чтение» — значит, кто-то его бережёт
            raise Skip("файл только для чтения")
        kind = job.kind
        tail = b""
        if kind == "jpeg":
            with open(job.path, "rb") as f:
                data = f.read()
            tail = jpeg_tail(data)
            # MPO и Ultra HDR тоже здесь: их вторая картинка всегда лежит в хвосте.
            if any(sig in tail for sig in FOREIGN_TAIL):
                raise Skip(ATTACHED)
        if kind == "png":
            _png(job, dst, cancel, gentle, threads)
        elif kind == "jpeg" and mode == "lossless":
            _jpeg_lossless(job, dst, cancel, gentle)
        elif kind == "jpeg":
            _jpeg_visual(job, dst)
        else:
            _video(job, dst, cancel, gentle, threads, on_part)
        if tail:
            # Служебная запись Samsung (SEF) отсчитывает свои смещения от конца файла — переносим как есть.
            with open(dst, "ab") as f:
                f.write(tail)
            with open(dst, "rb") as f:
                if jpeg_tail(f.read()) != tail:
                    raise Skip("служебные данные в конце снимка не перенеслись — файл не трогаю")
        if kind == "png" or (kind == "jpeg" and mode == "lossless"):
            if not same_pixels(job.path, dst):
                raise Skip("после пересборки пиксели не совпали — файл не трогаю")
            job.check = "pixels"
        new_size = os.path.getsize(dst)
        if new_size > job.size * (1 - MIN_GAIN[mode]):
            raise Skip("почти не уменьшился")
        job.out, job.new_size = dst, new_size
    except Cancelled:
        _drop(dst)
        raise
    except Skip as e:
        _drop(dst)
        job.skip = str(e)
    except OSError as e:
        _drop(dst)
        job.skip = e.strerror or str(e)
    except Exception as e:                                # чужой файл не должен ронять всю подготовку
        _drop(dst)
        job.skip = f"{type(e).__name__}: {e}"
    return job


def _drop(path):
    for p in (path, path + ".enc", path + ".0", path + ".1"):
        try:
            os.remove(p)
        except OSError:
            pass


# ---------------------------------------------------------------- подготовка целой папки

LOAD = {
    # уровень: (фоновый приоритет, потоков для фото, потоков кодировщика видео)
    "gentle": (True, 1, 2),
    "normal": (False, 2, max(2, (os.cpu_count() or 4) // 2)),
    "fast": (False, max(2, (os.cpu_count() or 4) // 2), os.cpu_count() or 4),
}


def prepare(root, kinds, mode, progress=None, cancel=None, load="normal", on_job=None):
    """Найти файлы и подготовить сжатые копии.

    progress(сделано_байт, всего_байт, сделано_файлов, всего_файлов, имя_текущего) — из потока подготовки.
    on_job(job) — сразу, как файл готов (сжат или пропущен).
    Фото идут первыми (они быстрые), видео — от больших к маленьким.
    """
    progress = progress or (lambda *a: None)
    gentle, photo_workers, enc_threads = LOAD[load]
    if gentle:
        dupcore.background_mode()
    res = PrepResult()
    kinds = set(kinds) & MODE_KINDS[mode]
    clean_work()
    try:
        exts = wanted_ext(kinds)
        cloud = []
        files = dupcore.collect(root, cancel, res.errors, take=lambda e: e in exts, cloud=cloud,
                                on_file=lambda n: progress(0, 0, 0, n, ""))
        res.cloud_skipped = len(cloud)
        jobs = [Job(m.path, m.size, m.mtime) for m in files if m.size > 0]
        jobs.sort(key=lambda j: (j.is_video, -j.size if j.is_video else j.path.lower()))
        res.jobs = jobs
        res.files_seen, res.bytes_seen = len(jobs), sum(j.size for j in jobs)
        total = res.bytes_seen
        lock = threading.Lock()
        state = {"bytes": 0, "files": 0}

        def finished(job):
            with lock:
                state["bytes"] += job.size
                state["files"] += 1
                progress(state["bytes"], total, state["files"], len(jobs), "")
            if on_job:
                on_job(job)

        def room(job):
            free = free_space(os.path.dirname(WORK) if os.path.isdir(os.path.dirname(WORK)) else WORK)
            return free is None or free > RESERVE + job.size

        photos = [j for j in jobs if not j.is_video]
        videos = [j for j in jobs if j.is_video]
        progress(0, total, 0, len(jobs), "")

        def one_photo(job):
            _check(cancel)
            if not room(job):
                res.no_space = True
                raise Cancelled
            prepare_one(job, mode, cancel, gentle, 1 if photo_workers > 1 else 2)
            finished(job)

        if photo_workers > 1:
            init = dupcore.background_mode if gentle else None
            with ThreadPoolExecutor(photo_workers, initializer=init) as ex:
                futures = [ex.submit(one_photo, j) for j in photos]
                try:
                    for f in futures:
                        f.result()                    # Cancelled из потока поднимется здесь
                except Cancelled:
                    for f in futures:
                        f.cancel()
                    raise
        else:
            for j in photos:
                one_photo(j)

        for job in videos:
            _check(cancel)
            if not room(job):
                res.no_space = True
                raise Cancelled
            base = state["bytes"]

            def part(f, base=base, job=job):
                progress(base + int(job.size * f), total, state["files"], len(jobs), os.path.basename(job.path))
            part(0)
            prepare_one(job, mode, cancel, gentle, enc_threads, part)
            finished(job)
    except Cancelled:
        res.cancelled = True
    return res


# ---------------------------------------------------------------- замена

def _filetime(ns):
    v = ns // 100 + 116444736000000000
    return wintypes.FILETIME(v & 0xFFFFFFFF, v >> 32)


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.restype = wintypes.HANDLE
_k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                             wintypes.DWORD, wintypes.HANDLE]
_k32.SetFileTime.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 3
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
INVALID_HANDLE = wintypes.HANDLE(-1).value


def set_times(path, birth_ns, atime_ns, mtime_ns):
    """Даты создания, доступа и изменения файла — как были у оригинала."""
    # FILE_WRITE_ATTRIBUTES, общий доступ на всё, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS
    h = _k32.CreateFileW(path, 0x100, 7, None, 3, 0x02000000, None)
    if h is None or h == INVALID_HANDLE:
        raise OSError(ctypes.get_last_error(), "не удалось открыть файл, чтобы поставить даты", path)
    try:
        if not _k32.SetFileTime(h, ctypes.byref(_filetime(birth_ns)), ctypes.byref(_filetime(atime_ns)),
                                ctypes.byref(_filetime(mtime_ns))):
            raise OSError(ctypes.get_last_error(), "не удалось поставить даты", path)
    finally:
        _k32.CloseHandle(h)


def _blake(path):
    h = hashlib.blake2b(digest_size=32)
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.digest()


def check_before_replace(jobs):
    """Что можно заменять прямо сейчас: оригинал не менялся, сжатая копия на месте. (можно, проблемы)."""
    ok, problems = [], []
    for j in jobs:
        try:
            st = os.stat(j.path)
        except OSError:
            problems.append((j.path, "файл пропал после подготовки"))
            continue
        if st.st_size != j.size or st.st_mtime != j.mtime:
            problems.append((j.path, "файл изменился после подготовки"))
        elif not j.out or not os.path.exists(j.out) or os.path.getsize(j.out) != j.new_size:
            problems.append((j.path, "сжатая копия пропала — подготовь заново"))
        else:
            ok.append(j)
    return ok, problems


def replace(jobs, hwnd=None, progress=None, recycle=None, batch=None):
    """Заменить оригиналы сжатыми копиями. Возвращает (заменённые, проблемы [(путь, причина)]).

    Для каждого файла: копия кладётся рядом под временным именем и сверяется по содержимому →
    оригинал уходит в Корзину → копия получает имя оригинала и его даты. Не ушёл оригинал
    в Корзину — временный файл удаляется, оригинал остаётся как был. В Корзину — пачками:
    одна операция на много файлов в разы быстрее.
    """
    recycle = recycle or (lambda paths: dupcore.to_recycle_bin(paths, hwnd=hwnd))
    ok, problems = check_before_replace(jobs)
    done = []
    batch = batch or min(50, dupcore.step_for(len(ok)))
    for i in range(0, len(ok), batch):
        if progress:
            progress(i)
        staged = []                                    # (задание, временный файл, даты оригинала)
        for j in ok[i:i + batch]:
            folder, name = os.path.split(os.path.abspath(j.path))
            tmp = os.path.join(folder, f"~{name}.duplio")
            try:
                st = os.stat(j.path)
                shutil.copyfile(j.out, tmp)
                if os.path.getsize(tmp) != j.new_size or _blake(tmp) != _blake(j.out):
                    raise OSError(0, "копия легла с ошибкой")
            except OSError as e:
                _drop(tmp)
                problems.append((j.path, e.strerror or str(e)))
                continue
            staged.append((j, tmp, st))
        if not staged:
            continue
        removed, _left = recycle([j.path for j, _, _ in staged])
        gone = {os.path.abspath(p) for p in removed}
        for j, tmp, st in staged:
            if os.path.abspath(j.path) not in gone:
                _drop(tmp)
                problems.append((j.path, "оригинал не удалось убрать в Корзину — оставлен как был"))
                continue
            try:
                os.rename(tmp, j.path)
            except OSError as e:
                problems.append((j.path, tr("оригинал в Корзине, а сжатый файл остался под именем {name}: {err}",
                                            name=os.path.basename(tmp), err=e.strerror or e)))
                continue
            try:
                set_times(j.path, getattr(st, "st_birthtime_ns", st.st_ctime_ns), st.st_atime_ns, st.st_mtime_ns)
            except OSError as e:
                problems.append((j.path, tr("заменён, но даты не перенеслись: {err}", err=e.strerror or e)))
            _drop(j.out)
            done.append(j)
    if progress:
        progress(len(ok))
    return done, problems
