"""Конвертация в другой формат: логика без окна.

Как «Сжатие»: копии готовятся в своей рабочей папке и проверяются, оригиналы не трогаются до «Заменить»;
при замене оригинал уходит в Корзину, а рядом встаёт новый файл с тем же именем, новым расширением
(занято — «(2)») и датами оригинала (compcore.replace по Job.target).

Куда — `Target`: контейнер, кодек видео, качество, размер кадра, частота кадров, звук, видеокарта или
процессор; готовые наборы — `PRESETS`. Что можно не пересжимать, копируется как есть (кодек тот же —
поток копируется байт в байт и сверяется по хешу). Пересжатие с качеством «само» — лестница `LADDERS`
с проверкой VMAF, как в «Сжатии».

Метаданные MP4/MOV переносятся блоками оригинала байт в байт (`carry_meta`): ffmpeg пересобирает их
по-своему и кладёт ключи Apple в moov/udta/meta — там их не видит Проводник (геометка пропадала), а
в moov/meta, как у iPhone, видит. Служебные дорожки MOV (у iPhone — лица в кадре и т. п.) MP4 не
хранит — о них сказано в Job.note.
"""

import os
import shutil
import struct
import subprocess
import threading
from dataclasses import asdict, dataclass, field, fields

import compcore
import dupcore
import metacore
from compcore import Skip
from dupcore import Cancelled
from i18n import decimal, tr

WORK = os.path.join(os.path.dirname(compcore.WORK), "convert")

# Ключи про сам контейнер, а не про съёмку: в новом файле их пишет заново ffmpeg.
CONTAINER_KEYS = {"major_brand", "minor_version", "compatible_brands", "encoder", "handler_name"}
LIVE_KEY = compcore.LIVE_KEY
ISO = {".mp4", ".m4v", ".mov", ".qt", ".3gp", ".3g2"}     # MP4 и родня: метаданные — блоками (carry_meta)

# ---------------------------------------------------------------- куда конвертировать

# ключ: (название, расширение, видеокодеки, звуковые кодеки (None — любые), звук по умолчанию)
CONTAINERS = {
    "mp4": ("MP4", ".mp4", ("h264", "hevc", "av1"), ("aac", "mp3", "opus", "flac", "alac", "ac3", "eac3"), "aac"),
    "mov": ("MOV", ".mov", ("h264", "hevc"), ("aac", "alac", "mp3", "ac3", "pcm_s16le", "pcm_s24le"), "aac"),
    "mkv": ("MKV", ".mkv", ("h264", "hevc", "av1", "vp9"), None, "aac"),
    "webm": ("WebM", ".webm", ("vp9", "av1"), ("opus", "vorbis"), "opus"),
    "m4a": ("M4A (звук)", ".m4a", (), ("aac", "alac"), "aac"),
    "mp3": ("MP3 (звук)", ".mp3", (), ("mp3",), "mp3"),
    "opus": ("Opus (звук)", ".opus", (), ("opus",), "opus"),
    "flac": ("FLAC (звук)", ".flac", (), ("flac",), "flac"),
}
VIDEO_CODECS = {"copy": "Без пересжатия", "h264": "H.264", "hevc": "HEVC (H.265)", "av1": "AV1",
                "vp9": "VP9"}
AUDIO_CODECS = {"auto": "Как есть", "aac": "AAC", "opus": "Opus", "mp3": "MP3",
                "flac": "FLAC", "none": "Без звука"}
QUALITIES = {"auto": "Само", "high": "Высокое", "medium": "Среднее", "small": "Маленький файл"}
SIZES = {0: "Как есть", 2160: "4K (2160p)", 1440: "1440p", 1080: "1080p", 720: "720p", 480: "480p"}
FPSES = {0: "Как есть", 60: "60 кадров/с", 30: "30 кадров/с", 25: "25 кадров/с"}
DEVICES = {"gpu": "Видеокарта", "cpu": "Процессор"}
# Видео «fit» (только в наборах): кодек, который контейнер хранит, копируется, иначе — вот этот. Для Apple
# H.264 так же хорош, как HEVC: пересжимать его в HEVC — потеря без пользы (MOV 720p стал бы 1,5× больше).
FIT = {"mp4": "h264", "mov": "hevc", "mkv": "hevc", "webm": "vp9"}


@dataclass
class Target:
    container: str = "mp4"
    video: str = "copy"
    quality: str = "auto"
    size: int = 0                  # меньшая сторона кадра; 0 — как есть
    fps: int = 0                   # 0 — как есть
    audio: str = "auto"
    device: str = "gpu"
    shrink: bool = False           # файл должен стать меньше хотя бы на MIN_GAIN, иначе — как есть («Меньше места»)

    @property
    def audio_only(self):
        return not CONTAINERS[self.container][2]

    @property
    def ext(self):
        return CONTAINERS[self.container][1]

    @classmethod
    def from_dict(cls, d):
        """Из настроек; неизвестное и несовместимое — по умолчанию (настройки мог править человек)."""
        t = cls()
        tables = {"container": CONTAINERS, "video": {**VIDEO_CODECS, "fit": ""}, "quality": QUALITIES,
                  "size": SIZES, "fps": FPSES, "audio": AUDIO_CODECS, "device": DEVICES, "shrink": {True: 1, False: 0}}
        for f in fields(cls):
            v = (d or {}).get(f.name)
            if v in tables[f.name]:
                setattr(t, f.name, v)
        return t.fixed()

    def fixed(self):
        """Привести выбор к тому, что контейнер умеет: WebM — только VP9/AV1 и Opus, MOV — без AV1 и т. п."""
        _name, _ext, vids, auds, default = CONTAINERS[self.container]
        if vids and self.video not in ("copy", "fit") and self.video not in vids:
            self.video = vids[0]
        if self.audio_only and self.audio in ("auto", "none"):
            self.audio = default
        if self.audio not in ("auto", "none") and auds is not None and self.audio not in auds:
            self.audio = default
        return self

    def as_dict(self):
        return asdict(self)


PRESETS = {
    # ключ: (название, пояснение, настройка)
    "keep": ("Как есть", "MP4 без пересжатия: картинка — та же байт в байт, звук — тоже, если MP4 его хранит "
             "(иначе — AAC). Быстро.", Target("mp4", "copy")),
    # 4K60 в H.264 старые телевизоры и телефоны не тянут, а кодировать его долго и выходит больше оригинала
    # (Galaxy ночью — 1,35×) — набор уменьшает кадр до 1080p; об этом сказано в строке и в окне замены.
    "everywhere": ("Откроется везде", "MP4, H.264 и AAC — откроет любой телефон, телевизор и старый компьютер. "
                   "Видео больше 1080p уменьшается до 1080p.", Target("mp4", "h264", size=1080, audio="aac")),
    # AV1 на процессоре (SVT) на треть меньше AV1 видеокарты при том же VMAF, а медленнее всего в 1,7 раза
    # (4K HEVC всё равно распаковывает процессор) — для «места» процессор.
    "small": ("Меньше места", "MP4, AV1 — меньше всего места при том же качестве. Открывают Windows 10/11, "
              "Android 10+, iPhone 15 Pro и новее, браузеры, новые телевизоры. Если меньше не выходит — файл "
              "остаётся как есть.", Target("mp4", "av1", device="cpu", shrink=True)),
    "apple": ("Для Apple", "MOV и AAC, как снимает iPhone: Фото, iMovie, QuickTime. H.264 и HEVC перекладываются "
              "без пересжатия, остальное — в HEVC.", Target("mov", "fit", audio="aac")),
    "audio": ("Только звук", "Звук из видео — в MP3, его откроет что угодно.", Target("mp3", audio="mp3")),
    "custom": ("Свой", "Всё выбираешь сам.", None),
}

# ---------------------------------------------------------------- кодировщики

# -maxrate обязателен: без него видеокарта молча режет битрейт по уровню профиля, и у 4K60 высокие ступени
# лестницы не лучше низких (HEVC: CQ 24 и 27 — один размер, VMAF 95,5; с потолком 500M — файл вдвое больше).
NVENC = ["-preset", "p6", "-tune", "hq", "-rc", "vbr", "-b:v", "0", "-maxrate", "500M", "-bufsize", "1000M",
         "-spatial_aq", "1", "-rc-lookahead", "32"]
# (кодек, видеокарта?) → (кодировщик ffmpeg, аргументы для значения качества q, параметр потоков)
ENCODERS = {
    ("h264", True): ("h264_nvenc", lambda q, n: [*NVENC, "-cq", str(q)]),
    ("hevc", True): ("hevc_nvenc", lambda q, n: [*NVENC, "-cq", str(q)]),
    ("av1", True): ("av1_nvenc", lambda q, n: [*NVENC, "-cq", str(q)]),
    ("h264", False): ("libopenh264", lambda q, n: ["-b:v", str(q), "-maxrate", str(q * 2), "-threads", str(n)]),
    ("hevc", False): ("libkvazaar", lambda q, n: ["-kvazaar-params", f"qp={q},preset=medium,threads={n}"]),
    ("av1", False): ("libsvtav1", lambda q, n: ["-crf", str(q), "-preset", str(compcore.VIDEO_PRESET),
                                                "-svtav1-params", f"lp={n}"]),
    ("vp9", False): ("libvpx-vp9", lambda q, n: ["-crf", str(q), "-b:v", "0", "-row-mt", "1", "-cpu-used", "4",
                                                 "-deadline", "good", "-threads", str(n)]),
}
# Лестница «само»: от меньшего файла к лучшему качеству, берётся первое, что прошло VMAF.
# У OpenH264 нет CRF — значения в битах на пиксель кадра (умножаются на ширину × высоту × частоту).
# Калибровка 17.10.2026 на роликах владельца (куски по 8 с; Galaxy S24 Ultra 4K60 день и ночь, H.264 4K, телефон
# 720p, запись экрана 1080p60, WhatsApp 478×850), проверка — как ниже (VMAF ≥ 93, худший 1 % ≥ 88), в скобках —
# где проходит и доля размера оригинала:
#   h264_nvenc  день CQ 27 (0,82), ночь 30 (0,40), H.264 4K 30, 720p 27 (1,48), WhatsApp 27, экран 33 (0,06)
#   hevc_nvenc  день 30 (0,45), ночь 33 (0,17), H.264 4K 33, 720p 27, WhatsApp 27, экран 36
#   av1_nvenc   день 36 (0,36), ночь 40 (0,13), H.264 4K 40, 720p 36 (0,91), WhatsApp 36, экран 44 (0,01)
#   libsvtav1   день CRF 32 (0,25 — на треть меньше видеокарты), 720p 32, WhatsApp 36
#   libvpx-vp9  день 37 (0,21), 720p 32, WhatsApp 32;  libkvazaar день и 720p — QP 25 (8 с 4K — 160 с)
#   libopenh264 день 0,16 бит/пиксель (1,28), 720p 0,16 (2,5!), WhatsApp 0,16; ниже 0,11 не проходит ничто
LADDERS = {
    "h264_nvenc": (33, 30, 27, 24, 21),   # 21 — ночной 4K → 1080p: худший 1 % кадров проходит только тут
    "hevc_nvenc": (36, 33, 30, 27),
    "av1_nvenc": (44, 40, 36, 32),
    "libopenh264": (0.11, 0.16, 0.24),
    "libkvazaar": (28, 25, 22),
    "libsvtav1": compcore.VIDEO_CRFS,
    "libvpx-vp9": (42, 37, 32, 27),
}
# Ручное качество: «высокое» — с запасом над порогом, «среднее» — около порога на трудном ролике, «маленький
# файл» — заметно на крупных планах (VMAF 85–90 на 4K днём).
MANUAL = {
    "h264_nvenc": {"high": 22, "medium": 27, "small": 32},
    "hevc_nvenc": {"high": 24, "medium": 29, "small": 35},
    "av1_nvenc": {"high": 30, "medium": 36, "small": 43},
    "libopenh264": {"high": 0.24, "medium": 0.16, "small": 0.09},
    "libkvazaar": {"high": 22, "medium": 25, "small": 30},
    "libsvtav1": {"high": 24, "medium": 32, "small": 40},
    "libvpx-vp9": {"high": 27, "medium": 34, "small": 41},
}
Q_NAMES = {"h264_nvenc": "CQ", "hevc_nvenc": "CQ", "av1_nvenc": "CQ", "libkvazaar": "QP"}   # остальные — CRF
AUDIO_ARGS = {"aac": ["-c:a", "aac", "-b:a", "256k"], "mp3": ["-c:a", "libmp3lame", "-q:a", "0"],
              "opus": ["-c:a", "libopus", "-b:a", "160k"], "flac": ["-c:a", "flac"],
              "vorbis": ["-c:a", "libvorbis", "-q:a", "6"], "alac": ["-c:a", "alac"]}

_gpu = {}


def gpu_ok(encoder):
    """Работает ли кодировщик видеокарты на этом компьютере (проба на десятой доле секунды; запоминается)."""
    if encoder not in _gpu:
        try:
            r = subprocess.run([compcore.tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i",
                                "color=size=256x256:duration=0.1", "-c:v", encoder, "-f", "null", "-"],
                               capture_output=True, timeout=30, creationflags=compcore.CREATE_NO_WINDOW,
                               env=compcore._env())
            _gpu[encoder] = r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _gpu[encoder] = False
    return _gpu[encoder]


def encoder_for(codec, device):
    """(кодировщик, аргументы, на видеокарте ли): видеокарта — если выбрана и работает, иначе процессор."""
    if device == "gpu" and (codec, True) in ENCODERS and gpu_ok(ENCODERS[codec, True][0]):
        return (*ENCODERS[codec, True], True)
    return (*ENCODERS[codec, False], False)


def clean_work():
    shutil.rmtree(WORK, ignore_errors=True)


def _tags(info):
    return {k: v for k, v in (info.get("format", {}).get("tags") or {}).items() if k not in CONTAINER_KEYS}


def _side(stream, kind):
    for sd in stream.get("side_data_list") or []:
        if kind in str(sd.get("side_data_type", "")):
            return sd
    return None


def stream_hashes(path, indexes=None, cancel=None, gentle=False):
    """SHA-256 содержимого каждого потока (пакеты подряд, без распаковки): ["v,SHA256=…", …].

    indexes — какие потоки (по номерам в файле); None — все. Совпали хеши — значит, видео и звук
    скопированы байт в байт.
    """
    maps = [a for i in indexes for a in ("-map", f"0:{i}")] if indexes is not None else ["-map", "0"]
    lines = []
    compcore._run([compcore.tool("ffmpeg"), "-hide_banner", "-nostdin", "-v", "error", "-i", path, *maps,
                   "-c", "copy", "-f", "streamhash", "-hash", "sha256", "-"], cancel, gentle,
                  on_line=lambda s: s and lines.append(s.split(",", 1)[1]))
    return lines


# ---------------------------------------------------------------- метаданные блоками оригинала

def _top_boxes(f):
    """Блоки верхнего уровня файла: (тип, начало, размер) — читаются только заголовки."""
    f.seek(0, 2)
    end, i = f.tell(), 0
    while i + 8 <= end:
        f.seek(i)
        h = f.read(16)
        size, typ, hdr = struct.unpack(">I", h[:4])[0], h[4:8], 8
        if size == 1:
            size, hdr = struct.unpack(">Q", h[8:16])[0], 16
        elif size == 0:
            size = end - i
        if size < hdr or i + size > end:
            raise Skip("испорченный MP4")
        yield typ, i, size
        i += size


def read_moov(path):
    """Заголовок moov целиком (байты), его начало и размер."""
    with open(path, "rb") as f:
        for typ, i, n in _top_boxes(f):
            if typ == b"moov":
                f.seek(i)
                return f.read(n), i, n
    raise Skip("в видео нет заголовка moov")


def _kids(buf, box=None):
    """Дети блока box = (тип, начало, начало содержимого, конец); None — весь buf — это сам блок."""
    if box is None:
        box = next(metacore._boxes(buf, 0, len(buf)))
    return list(metacore._boxes(buf, box[2], box[3]))


def _box(typ, body):
    return struct.pack(">I4s", 8 + len(body), typ) + body


def _handler(buf, trak):
    for k in _kids(buf, trak):
        if k[0] == b"mdia":
            for h in _kids(buf, k):
                if h[0] == b"hdlr":
                    return bytes(buf[h[2] + 8:h[2] + 12])
    return b""


CARRIED = (b"udta", b"meta")          # где MOV и MP4 хранят метаданные: у ролика и у дорожки


def carry_meta(src, dst):
    """Метаданные из оригинала src в новый dst — блоками udta и meta как есть, байт в байт.

    У ролика целиком (moov) и у видеодорожки (у iPhone там модель объектива и фокусное расстояние).
    Свои блоки ffmpeg выбрасываются. Заголовок moov в dst должен быть последним блоком файла:
    тогда он меняет размер, не сдвигая видео (смещения кадров в нём не меняются).
    """
    old = read_moov(src)[0]
    new, at, n = read_moov(dst)
    if at + n != os.path.getsize(dst):
        raise Skip("заголовок moov не в конце файла — метаданные не перенести")
    old_kids, new_kids = _kids(old), _kids(new)
    vid = lambda buf, kids: next((k for k in kids if k[0] == b"trak" and _handler(buf, k) == b"vide"), None)
    old_v, new_v = vid(old, old_kids), vid(new, new_kids)
    parts = []
    for k in new_kids:
        if k[0] in CARRIED:
            continue
        piece = bytes(new[k[1]:k[3]])
        if k is new_v and old_v is not None:
            body = b"".join(bytes(new[t[1]:t[3]]) for t in _kids(new, k) if t[0] not in CARRIED)
            body += b"".join(bytes(old[t[1]:t[3]]) for t in _kids(old, old_v) if t[0] in CARRIED)
            piece = _box(b"trak", body)
        parts.append(piece)
    parts += [bytes(old[k[1]:k[3]]) for k in old_kids if k[0] in CARRIED]
    moov = _box(b"moov", b"".join(parts))
    with open(dst, "r+b") as f:
        f.seek(at)
        f.write(moov)
        f.truncate()


# ---------------------------------------------------------------- план: что с каждой дорожкой

def _fps(v):
    try:
        a, b = (v.get("avg_frame_rate") or "0/1").split("/")
        return float(a) / float(b) if float(b) else 0.0
    except ValueError:
        return 0.0


def _hdr(v):
    return v.get("color_transfer") in ("smpte2084", "arib-std-b67")


def plan(info, src_ext, t):
    """Что делать с файлом: словарь {"video": "copy" | кодек | None, "audio": [(поток, "copy" | кодек)],
    "subs": [поток], "dropped": n, "filters": [...], "fps_change": bool}. Нельзя — Skip с причиной."""
    name, ext, vids, auds, default = CONTAINERS[t.container]
    streams = info.get("streams", [])
    v = compcore._video_stream(info)
    p = {"video": None, "vstream": v, "audio": [], "subs": [], "dropped": 0, "filters": [], "fps_change": False,
         "resize": None}
    for s in streams:
        kind = s.get("codec_type")
        if kind == "video" and s.get("disposition", {}).get("attached_pic"):
            p["dropped"] += 1                      # обложка внутри ролика
        elif kind == "video":
            if s is not v or t.audio_only:
                p["dropped"] += 0 if t.audio_only else 1
        elif kind == "audio":
            if t.audio == "none":
                continue
            if t.audio_only and p["audio"]:
                continue                           # в файл «только звук» — одна дорожка, первая
            codec = s.get("codec_name")
            want = t.audio if t.audio != "auto" else (codec if auds is None or codec in auds else default)
            if want == codec and (auds is None or codec in auds):
                p["audio"].append((s, "copy"))
            else:
                p["audio"].append((s, want))
        elif kind == "subtitle":
            if t.container == "mkv" or (ext in (".mp4", ".mov") and s.get("codec_name") == "mov_text"):
                p["subs"].append(s)
            elif not t.audio_only:
                p["dropped"] += 1
        elif s.get("codec_tag_string") == "tmcd":
            pass                                   # тайм-код: ffmpeg пишет его в MP4 заново по метке видео
        elif not t.audio_only:
            p["dropped"] += 1                      # служебные дорожки: у iPhone — лица, ориентация (mebx)
    if t.audio_only:
        if not p["audio"]:
            raise Skip("в файле нет звука")
        return p
    if v is None:
        raise Skip("в файле нет видео")
    codec = v.get("codec_name")
    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    resize = bool(t.size and min(w, h) > t.size)
    fps_change = bool(t.fps and _fps(v) > t.fps + 0.5)
    interlaced = v.get("field_order") in ("tt", "bb", "tb", "bt")
    video = t.video
    if video == "fit":
        video = "copy" if codec in vids and not resize and not fps_change else FIT[t.container]
    if video == "copy":
        if codec not in vids:
            raise Skip(tr("видео в формате {codec} — без пересжатия в {fmt} не переложить: выбери кодек",
                          codec=codec or "?", fmt=name))
        p["video"] = "copy"
    elif codec == video and not resize and not fps_change and not interlaced:
        p["video"] = "copy"                        # кодек уже тот — пересжимать незачем, поток копируется
    else:
        if _hdr(v) and video == "h264":
            raise Skip("HDR-видео в H.264 не перевести без потери цветов — выбери HEVC или AV1")
        p["video"] = video
        if interlaced:
            p["filters"].append("bwdif=mode=send_frame:deint=interlaced")
        if resize:
            p["resize"] = (w, h)
            s_ = t.size
            p["filters"].append(f"scale='if(gte(iw,ih),-2,{s_})':'if(gte(iw,ih),{s_},-2)':flags=lanczos")
        if fps_change:
            p["filters"].append(f"fps={t.fps}")
            p["fps_change"] = True
    all_copy = p["video"] == "copy" and all(a == "copy" for _s, a in p["audio"])
    if all_copy and src_ext == ext:
        # служебные дорожки не в счёт: выкинуть их — не причина переписывать файл (MOV iPhone с Dolby Vision
        # набор «Для Apple» иначе перекладывал бы в MOV и спотыкался о Dolby Vision)
        raise Skip(tr("уже {fmt} в нужном виде", fmt=name))
    return p


# ---------------------------------------------------------------- один файл

def _out_size(v, t):
    """Размер кадра после уменьшения (как его сделает scale с -2: чётная сторона)."""
    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    if not (t.size and min(w, h) > t.size):
        return w, h
    k = t.size / min(w, h)
    long_side = int(round(max(w, h) * k / 2)) * 2
    return (long_side, t.size) if w >= h else (t.size, long_side)


def _duration(info):
    try:
        return float(info.get("format", {}).get("duration") or 0)
    except ValueError:
        return 0.0


def _encode(job, info, p, t, dst, q, enc, enc_args, threads, cancel, gentle, on_line):
    """Один проход ffmpeg с качеством q (None — видео копируется или его нет)."""
    v = p["vstream"]
    src_iso = os.path.splitext(job.path)[1].lower() in ISO
    out_iso = t.ext in (".mp4", ".mov", ".m4a")
    args = [compcore.tool("ffmpeg"), "-hide_banner", "-nostdin", "-y"]
    if p["video"] not in (None, "copy"):
        args += compcore.hwdec()               # распаковка на видеокарте — в разы быстрее (compcore.hwdec)
    args += ["-i", job.path]
    if p["video"]:
        args += ["-map", f"0:{v['index']}"]
    for s, _a in p["audio"]:
        args += ["-map", f"0:{s['index']}"]
    for s in p["subs"]:
        args += ["-map", f"0:{s['index']}"]
    if p["video"] == "copy":
        args += ["-c:v", "copy"]
    elif p["video"]:
        deep = any(x in (v.get("pix_fmt") or "") for x in ("10", "12")) or int(v.get("bits_per_raw_sample") or 8) > 8
        ten = deep and p["video"] in ("hevc", "av1", "vp9") and enc != "libkvazaar"
        args += ["-c:v", enc, *enc_args(q, threads)]
        if enc.endswith("nvenc"):
            args += ["-pix_fmt", "p010le" if ten else "nv12"]
        else:
            args += ["-pix_fmt", "yuv420p10le" if ten else "yuv420p"]
        if p["filters"]:
            args += ["-vf", ",".join(p["filters"])]
        # цвета HDR (HLG, PQ, BT.2020) ffmpeg берёт из кадров сам — проверено тестом; Dolby Vision не сохранится
        if p["video"] == "hevc" and t.ext in (".mp4", ".mov"):
            args += ["-tag:v", "hvc1"]         # так HEVC открывают Apple и Windows
    for i, (s, a) in enumerate(p["audio"]):
        args += [f"-c:a:{i}", "copy"] if a == "copy" else [x.replace("-c:a", f"-c:a:{i}").replace(
            "-b:a", f"-b:a:{i}").replace("-q:a", f"-q:a:{i}") for x in AUDIO_ARGS[a]]
    if p["subs"]:
        args += ["-c:s", "copy"]
    if not p["video"] or not p["audio"]:
        args += ["-vn"] if not p["video"] else ["-an"]
    args += ["-map_metadata", "0", "-map_chapters", "0"]
    if p["video"] and not p["fps_change"]:
        args += ["-fps_mode", "passthrough"]
        if p["video"] != "copy":
            args += ["-enc_time_base", "demux"]
    if out_iso:
        args += ["-strict", "unofficial"]      # Dolby Vision при копировании; без него — HLG без DV
        if not (src_iso and p["video"]):
            args += ["-movflags", "+faststart+use_metadata_tags"]
        # из MP4/MOV — без +faststart: moov в конце, carry_meta кладёт туда метаданные оригинала
    args += ["-progress", "pipe:1", "-nostats", dst]
    compcore._run(args, cancel, gentle, on_line=on_line)
    if out_iso and src_iso and p["video"]:
        carry_meta(job.path, dst)


def _check(job, info, p, t, dst, cancel, gentle):
    """После прохода: дорожки, длина, время кадров, поворот, метаданные; скопированное — байт в байт."""
    new = compcore.probe(dst)
    streams = [s for s in new.get("streams", []) if s.get("codec_tag_string") != "tmcd"]
    want = (1 if p["video"] else 0) + len(p["audio"]) + len(p["subs"])
    if len(streams) != want:
        raise Skip("после конвертации дорожки не сходятся с оригиналом")
    dur, new_dur = _duration(info), _duration(new)
    if p["video"] == "copy" and all(a == "copy" for _s, a in p["audio"]):
        if dur and abs(new_dur - dur) > 0.1:
            raise Skip("после перекладки не сходится длина ролика")
    elif dur and abs(new_dur - dur) > max(0.5, dur * 0.01):
        raise Skip("после конвертации не сходится длина")
    v = p["vstream"]
    if p["video"]:
        nv = streams[0]
        if (v.get("tags") or {}).get("timecode") != (nv.get("tags") or {}).get("timecode"):
            raise Skip("после перекладки не сходится тайм-код")
        if p["video"] == "copy":
            ra, rb = _side(v, "Display Matrix"), _side(nv, "Display Matrix")
            if (ra or {}).get("rotation", 0) != (rb or {}).get("rotation", 0):
                raise Skip("после перекладки ролик повернулся бы иначе")
            if bool(_side(v, "DOVI")) != bool(_side(nv, "DOVI")):
                raise Skip("после перекладки пропал бы Dolby Vision")
        if not p["fps_change"] and not compcore.same_timing(job.path, dst):
            raise Skip("после перекладки кадры сдвинулись по времени")
    if t.ext in (".mp4", ".mov") and os.path.splitext(job.path)[1].lower() in ISO and p["video"]:
        old_tags, new_tags = _tags(info), _tags(new)
        lost = sorted(k for k in old_tags.keys() | new_tags.keys() if new_tags.get(k) != old_tags.get(k))
        if lost:
            raise Skip(tr("не перенеслись метаданные: {keys}", keys=", ".join(lost[:4])))
    copied_src = ([v["index"]] if p["video"] == "copy" else []) + [s["index"] for s, a in p["audio"] if a == "copy"]
    copied_new = ([streams[0]["index"]] if p["video"] == "copy" else []) + \
        [streams[(1 if p["video"] else 0) + i]["index"] for i, (_s, a) in enumerate(p["audio"]) if a == "copy"]
    if copied_src and stream_hashes(job.path, copied_src, cancel, gentle) != stream_hashes(dst, copied_new,
                                                                                           cancel, gentle):
        raise Skip("после перекладки видео или звук не совпали с оригиналом байт в байт")


SHORT = {"h264": "H.264", "hevc": "HEVC", "av1": "AV1", "vp9": "VP9", "aac": "AAC", "mp3": "MP3", "opus": "Opus",
         "flac": "FLAC", "vorbis": "Vorbis", "alac": "ALAC"}


def _how(p, t, enc, gpu, q):
    """(коротко — для столбца списка, подробно — под превью)."""
    audio = sorted({a for _s, a in p["audio"]} - {"copy"})
    sound = ", ".join(SHORT.get(a, a) for a in audio)
    if p["video"] in ("copy", None) and not audio:
        return tr("без пересжатия"), tr("без пересжатия")
    if p["video"] in ("copy", None):
        short = tr("звук → {codec}", codec=sound) if p["video"] else sound
        return short, (tr("видео без пересжатия, звук → {codec}", codec=sound) if p["video"] else
                       tr("звук → {codec}", codec=sound))
    if t.quality != "auto":
        q_text = tr(QUALITIES[t.quality])
    elif enc == "libopenh264":
        q_text = tr("{n} Мбит/с", n=decimal(q))
    else:
        q_text = f"{Q_NAMES.get(enc, 'CRF')} {q}"
    detail = f"{VIDEO_CODECS[p['video']]}, {tr('видеокарта') if gpu else tr('процессор')}, {q_text}, " + (
        tr("звук → {codec}", codec=sound) if audio else tr("звук без пересжатия") if p["audio"] else tr("без звука"))
    return f"{SHORT[p['video']]} · {q_text}", detail


def convert_one(job, target=None, cancel=None, gentle=False, threads=1, on_part=lambda f: None, taken=None,
                lock=None, beside=False):
    """Сделать новый файл в рабочей папке и проверить. Успех — job.out (и job.target); нет — job.skip.

    beside — новый файл ляжет рядом с оригиналом (оригинал остаётся): имя нужно всегда другое.
    """
    t = target or Target()
    os.makedirs(WORK, exist_ok=True)
    dst = new_name = ""
    lock = lock or threading.Lock()
    taken = taken if taken is not None else set()
    try:
        st = os.stat(job.path)
        if st.st_size != job.size or st.st_mtime != job.mtime:
            raise Skip("файл изменился")
        if st.st_file_attributes & 0x1:
            raise Skip("файл только для чтения")
        info = compcore.probe(job.path)
        if LIVE_KEY in (info.get("format", {}).get("tags") or {}):
            raise Skip(compcore.LIVE)
        src_ext = os.path.splitext(job.path)[1].lower()
        p = plan(info, src_ext, t)
        if src_ext != t.ext or beside:
            with lock:                              # два «IMG_1.MOV» и «IMG_1.qt» не получат одно имя
                new_name = compcore.target_for(job.path, t.ext, taken)
                taken.add(os.path.normcase(new_name))
        dst = compcore._work_name(job.path, WORK, os.path.basename(new_name or job.path))
        duration = _duration(info)
        enc, enc_args, gpu = (None, None, False)
        if p["video"] not in (None, "copy"):
            enc, enc_args, gpu = encoder_for(p["video"], t.device)
        v = p["vstream"]
        if enc == "libkvazaar":
            w, h = _out_size(v, t)
            if w % 8 or h % 8:                     # kvazaar молча не выдаёт ни кадра (WhatsApp 478×850)
                raise Skip(tr("HEVC на процессоре не кодирует кадр {w}×{h} (стороны должны делиться на 8) — "
                              "выбери другой кодек или видеокарту", w=w, h=h))
        if t.quality == "auto" and enc:
            steps = list(LADDERS[enc])
        elif enc:
            steps = [MANUAL[enc][t.quality]]
        else:
            steps = [None]
        if enc == "libopenh264":                   # биты на пиксель → битрейт
            px = int(v.get("width") or 0) * int(v.get("height") or 0) * (t.fps or _fps(v) or 30)
            if t.size and min(int(v.get("width") or 0), int(v.get("height") or 0)) > t.size:
                px *= (t.size / min(int(v["width"]), int(v["height"]))) ** 2
            steps = [max(100_000, int(b * px)) for b in steps]
        four_k = bool(v) and int(v.get("width") or 0) * int(v.get("height") or 0) >= 0.9 * 3840 * 2160 and \
            not (t.size and t.size < 2160)
        for n, q in enumerate(steps):
            share = 0.6 if t.quality == "auto" and enc else 0.9

            def line(s, n=n):
                if s.startswith("out_time_us=") and duration > 0:
                    try:
                        f = min(1.0, int(s.split("=", 1)[1]) / 1e6 / duration)
                        on_part((n + f * share) / len(steps))
                    except ValueError:
                        pass
            _encode(job, info, p, t, dst, q, enc, enc_args, threads, cancel, gentle, line)
            _check(job, info, p, t, dst, cancel, gentle)
            if t.shrink and p["video"] not in (None, "copy") and os.path.getsize(dst) > job.size * (1 - compcore.MIN_GAIN["visual"]):
                raise Skip(tr("{codec} не уменьшает этот файл ({pct} оригинала) — оставлен как есть",
                              codec=SHORT.get(p["video"], ""), pct=f"{os.path.getsize(dst) / job.size:.0%}"))
            if t.quality == "auto" and enc:
                mean, low = compcore.video_vmaf(job.path, dst, four_k, cancel, gentle, threads,
                                                ref_filter=",".join(p["filters"]), by_order=True)
                job.score = mean
                on_part((n + 1) / len(steps))
                if mean >= compcore.VIDEO_VMAF_MEAN and low >= compcore.VIDEO_VMAF_LOW:
                    job.check = "vmaf"
                    break
                if n == len(steps) - 1:
                    raise Skip("без видимых потерь не получается — выбери качество «Высокое»")
            else:
                job.check = "streams" if p["video"] in ("copy", None) and \
                    all(a == "copy" for _s, a in p["audio"]) else ""
        on_part(1.0)
        if enc == "libopenh264":
            q = round(q / 1e6, 1)
        job.how, job.detail = _how(p, t, enc, gpu, q)
        notes, new_size = [], os.path.getsize(dst)
        made_by = reencoded_by(v)
        reencoded = p["video"] not in (None, "copy")
        if made_by and reencoded:
            job.warn = True
            notes.append(tr("уже пересжимался программой ({enc}) — каждое пересжатие чуть ухудшает качество",
                            enc=made_by))
        if p["resize"]:
            job.warn = job.resized = True
            nw, nh = _out_size(v, t)
            notes.append(tr("кадр уменьшен: {old} → {new}", old=f"{p['resize'][0]}×{p['resize'][1]}",
                            new=f"{nw}×{nh}"))
        if reencoded and new_size > job.size * 1.05:
            job.warn = True
            notes.append(tr("файл стал больше оригинала на {pct}", pct=f"{new_size / job.size - 1:.0%}"))
        if _side(v or {}, "DOVI") and reencoded:
            notes.append(tr("Dolby Vision не сохранится — останется обычный HDR"))
        if p["dropped"]:
            notes.append(tr("служебных дорожек не перенесено: {n} (в {fmt} их не положить)", n=p["dropped"],
                            fmt=CONTAINERS[t.container][0]))
        job.note = "; ".join(notes)
        job.out, job.new_size, job.target = dst, new_size, new_name
    except Cancelled:
        dst and compcore._drop(dst)
        raise
    except Skip as e:
        dst and compcore._drop(dst)
        job.skip = str(e)
    except OSError as e:
        dst and compcore._drop(dst)
        job.skip = e.strerror or str(e)
    except Exception as e:                                # чужой файл не должен ронять всю подготовку
        dst and compcore._drop(dst)
        job.skip = f"{type(e).__name__}: {e}"
    if job.skip and new_name:
        with lock:
            taken.discard(os.path.normcase(new_name))
    return job


# Подпись кодировщика в видео: её оставляют ffmpeg (Lavc — и Duplio), HandBrake и программы на их основе.
# Камеры и телефоны пишут своё («AVC Coding», «HEVC») или ничего. Перекладка без пересжатия подпись не меняет.
REENCODERS = ("Lavc", "HandBrake")


def reencoded_by(v):
    """Чем видео уже пересжимали («libsvtav1», «HandBrake …») или "" — по подписи в самом файле, без памяти."""
    tags = {k.lower(): str(val) for k, val in ((v or {}).get("tags") or {}).items()}
    enc = tags.get("encoder", "")
    if any(sig in enc for sig in REENCODERS):
        return enc.split(" ", 1)[1] if enc.startswith("Lavc") and " " in enc else enc
    return ""


def missing_tools():
    return [n for n in ("ffmpeg", "ffprobe") if not compcore.tool(n)]


def inputs(t):
    """Какие файлы берёт подготовка: видео; для «только звук» — ещё и музыка."""
    return set(dupcore.VIDEO_EXT) | {".qt"} | (set(dupcore.AUDIO_EXT) if t.audio_only else set())


# ---------------------------------------------------------------- «Подобрать для каждого»: группы

# Что можно сделать с группой: (кнопка в списке, что будет — одной строкой). Слова — как сказал бы человек.
ACTIONS = {
    "nothing": ("Не трогать", "Эти файлы останутся как есть."),
    "mp4": ("Сделать MP4, картинка та же", "Файлы станут MP4. Картинка и звук не изменятся. Это быстро."),
    "small": ("Сжать, чтобы занимали меньше места",
              "Видео станут меньше. На глаз разницы не будет — программа проверит каждое. Если меньше не "
              "выйдет, файл останется как был."),
    "everywhere": ("Сделать, чтобы открывались везде",
                   "Видео станут MP4, их откроет любой телефон и телевизор. Видео больше Full HD станут Full HD."),
    "apple": ("Сделать для iPhone и Mac", "Видео станут MOV, как у iPhone. Если можно, картинка не меняется."),
    "audio": ("Сохранить только звук (MP3)", "Рядом с каждым видео появится MP3 со звуком. Само видео останется."),
}
ACTION_TARGETS = {"mp4": Target("mp4", "copy"), "small": PRESETS["small"][2], "everywhere": PRESETS["everywhere"][2],
                  "apple": PRESETS["apple"][2], "audio": PRESETS["audio"][2]}
# Вид группы: (порядок, название, пояснение, действие по умолчанию, подходящие действия)
KINDS = {
    "big": (1, "Большие видео", "Занимают много места — их можно сжать.",
            "small", ("small", "everywhere", "audio", "nothing")),
    "mov": (2, "Видео MOV (iPhone, фотоаппарат)", "Не все телефоны и телевизоры открывают MOV.",
            "mp4", ("mp4", "small", "everywhere", "audio", "nothing")),
    "old": (3, "Старые видео", "AVI, WMV и похожие могут не открыться на телефоне.",
            "everywhere", ("everywhere", "small", "audio", "nothing")),
    "hdr": (4, "Яркие HDR-видео", "Если их пересжать, яркость может потеряться — лучше не трогать.",
            "nothing", ("nothing", "small", "audio")),
    "fine": (5, "Обычные видео", "Уже сжаты и открываются почти везде.",
             "nothing", ("nothing", "small", "everywhere", "apple", "audio")),
    "av1": (6, "Уже сжатые видео", "Меньше их сделать не получится.",
            "nothing", ("nothing", "everywhere", "audio")),
    "live": (7, "Видео от «живых фото»", "Это вторая половинка снимка — трогать нельзя, иначе снимок сломается.",
             "nothing", ("nothing",)),
}
OLD_CODECS = {"h264", "hevc", "av1", "vp9"}           # всё прочее (MPEG-4 Part 2, WMV, MPEG-2, MJPEG…) — старое
OLD_EXT = {".avi", ".wmv", ".mpg", ".mpeg", ".vob", ".flv", ".3gp", ".3g2", ".mts", ".m2ts", ".ts"}
BIG_RATE = 15_000_000       # бит/с: съёмка камеры (Galaxy 4K — 61 Мбит/с, 1080p — 17) сжимается в разы;
                            # телефон 720p (3,4 Мбит/с) и WhatsApp — уже экономные, AV1 их не уменьшает


def kind_of(info, path):
    """К какой группе относится видео (ключ KINDS) — по заголовку файла."""
    ext = os.path.splitext(path)[1].lower()
    v = compcore._video_stream(info)
    if LIVE_KEY in (info.get("format", {}).get("tags") or {}):
        return "live"
    if v is None:
        return None
    codec = v.get("codec_name")
    if codec not in OLD_CODECS or ext in OLD_EXT:
        return "old"
    if _hdr(v) or _side(v, "DOVI"):
        return "hdr"
    if codec == "av1":
        return "av1"
    if ext in (".mov", ".qt"):
        return "mov"
    try:
        rate = float(info.get("format", {}).get("bit_rate") or 0)
    except ValueError:
        rate = 0
    return "big" if rate >= BIG_RATE else "fine"


@dataclass
class Group:
    kind: str
    files: list = field(default_factory=list)      # MediaFile
    action: str = ""

    @property
    def size(self):
        return sum(f.size for f in self.files)

    @property
    def actions(self):
        return KINDS[self.kind][4]


@dataclass
class Survey:
    groups: list = field(default_factory=list)
    unreadable: list = field(default_factory=list)   # (путь, причина)
    cloud_skipped: int = 0
    unsupported: int = 0
    cancelled: bool = False


def survey(root, progress=None, cancel=None):
    """Посмотреть файлы и разложить по группам (только заголовки — быстро). progress(сделано, всего)."""
    progress = progress or (lambda *a: None)
    res, cloud, errors = Survey(), [], []
    exts = set(dupcore.VIDEO_EXT) | {".qt"}
    try:
        if isinstance(root, (list, tuple)):
            files, res.unsupported = compcore.gather(root, exts, cancel, errors, cloud)
        else:
            files = dupcore.collect(root, cancel, errors, take=lambda e: e in exts, cloud=cloud)
        files = [f for f in files if f.size > 0]
        res.cloud_skipped = len(cloud)
        by = {}
        for i, f in enumerate(files):
            dupcore._check(cancel)
            progress(i, len(files))
            try:
                kind = kind_of(compcore.probe(f.path), f.path)
            except Skip as e:
                res.unreadable.append((f.path, str(e)))
                continue
            if kind is None:
                res.unreadable.append((f.path, "в файле нет видео"))
                continue
            by.setdefault(kind, Group(kind, action=KINDS[kind][3])).files.append(f)
        progress(len(files), len(files))
        res.groups = sorted(by.values(), key=lambda g: KINDS[g.kind][0])
        res.unreadable += errors
    except Cancelled:
        res.cancelled = True
    return res


def prepare_groups(groups, beside=False, progress=None, cancel=None, load="normal", on_job=None):
    """Подготовить новые файлы по группам: у каждой — своё действие («Не трогать» — пропуск).
    «Только звук» — всегда рядом с видео (само видео не выбрасываем)."""
    plan_by = {}
    for g in groups:
        if g.action in ACTION_TARGETS:
            for f in g.files:
                plan_by[os.path.normcase(os.path.abspath(f.path))] = (ACTION_TARGETS[g.action],
                                                                      beside or g.action == "audio")
    clean_work()
    taken, lock = set(), threading.Lock()

    def one(job, cancel, gentle, threads, on_part):
        t, near = plan_by[os.path.normcase(os.path.abspath(job.path))]
        convert_one(job, t, cancel, gentle, threads, on_part, taken, lock, near)
        job.keep = near
    paths = [f.path for g in groups if g.action in ACTION_TARGETS for f in g.files]
    exts = set(dupcore.VIDEO_EXT) | {".qt"}
    return compcore.run_jobs(paths, exts, one, WORK, progress, cancel, load, on_job)


def prepare(root, target=None, progress=None, cancel=None, load="normal", on_job=None, beside=False):
    """Найти видео в root (папка или перетащенное) и подготовить новые файлы рядом с ними — в рабочей папке."""
    t = target or Target()
    clean_work()
    taken, lock = set(), threading.Lock()

    def one(job, cancel, gentle, threads, on_part):
        convert_one(job, t, cancel, gentle, threads, on_part, taken, lock, beside)
        job.keep = beside
    return compcore.run_jobs(root, inputs(t), one, WORK, progress, cancel, load, on_job)
