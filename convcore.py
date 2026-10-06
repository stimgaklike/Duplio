"""Конвертация в другой формат: логика без окна. Сейчас — MOV → MP4; дальше AVI, WMV, MTS → MP4, HEIC → JPEG.

Как «Сжатие»: копии готовятся в своей рабочей папке и проверяются, оригиналы не трогаются до «Заменить»;
при замене оригинал уходит в Корзину, а рядом встаёт новый файл с тем же именем, новым расширением
(занято — «(2)») и датами оригинала (compcore.replace по Job.target).

MOV с H.264 / HEVC / AV1 перекладывается в MP4 без пересжатия: потоки копируются байт в байт (сверяется
по хешу каждого потока), время кадров, поворот и Dolby Vision — те же. Метаданные съёмки переносятся блоками
оригинала байт в байт (`carry_meta`): ffmpeg пересобирает их по-своему и кладёт ключи Apple в moov/udta/meta —
там их не видит Проводник (геометка пропадала), а в moov/meta, как у iPhone, видит. Служебные дорожки MOV
(у iPhone — лица в кадре и т. п.) MP4 не хранит — о них сказано в Job.note.
"""

import os
import shutil
import struct
import threading

import compcore
import metacore
from compcore import Skip
from dupcore import Cancelled
from i18n import tr

WORK = os.path.join(os.path.dirname(compcore.WORK), "convert")

VIDEO_IN = {".mov", ".qt"}
# Что кладётся в MP4 как есть: видео и звук, которые MP4 хранит и которые открывают обычные плееры.
COPY_VIDEO = {"h264", "hevc", "av1", "vp9", "mpeg4"}
COPY_AUDIO = {"aac", "mp3", "alac", "ac3", "eac3", "opus", "flac"}
# Ключи про сам контейнер MOV, а не про съёмку: в MP4 их пишет заново ffmpeg.
CONTAINER_KEYS = {"major_brand", "minor_version", "compatible_brands", "encoder"}
LIVE_KEY = compcore.LIVE_KEY


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
    """SHA-256 содержимого каждого потока (пакеты подряд, без распаковки): ["0,v,SHA256=…", …].

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


# ---------------------------------------------------------------- MOV → MP4

def _remux(job, info, dst, cancel, gentle, on_part):
    """MOV → MP4 без пересжатия и проверка, что перенеслось всё, что MP4 может хранить."""
    keep, dropped = [], 0
    for s in info.get("streams", []):
        t, codec = s.get("codec_type"), s.get("codec_name")
        if t == "video" and s.get("disposition", {}).get("attached_pic"):
            dropped += 1                               # обложка внутри ролика — у видео с камер её не бывает
        elif t == "video":
            if codec not in COPY_VIDEO:
                raise Skip(tr("видео в формате {codec} — без пересжатия в MP4 не переложить", codec=codec or "?"))
            keep.append(s)
        elif t == "audio":
            if codec not in COPY_AUDIO:
                raise Skip(tr("звук в формате {codec} — без пересжатия в MP4 не переложить", codec=codec or "?"))
            keep.append(s)
        elif t == "subtitle" and codec == "mov_text":
            keep.append(s)
        elif s.get("codec_tag_string") == "tmcd":
            pass                                       # тайм-код: ffmpeg пишет его в MP4 заново по метке видео
        else:
            dropped += 1                               # служебные дорожки: у iPhone — лица, ориентация (mebx)
    if not any(s.get("codec_type") == "video" for s in keep):
        raise Skip("в файле нет видео")
    try:
        duration = float(info.get("format", {}).get("duration") or 0)
    except ValueError:
        duration = 0

    def line(s):
        if s.startswith("out_time_us=") and duration > 0:
            try:
                on_part(min(1.0, int(s.split("=", 1)[1]) / 1e6 / duration) * 0.4)
            except ValueError:
                pass
    maps = []
    for s in keep:
        maps += ["-map", f"0:{s['index']}"]
    compcore._run([compcore.tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-i", job.path, *maps, "-c", "copy",
                   # время съёмки — в заголовки (mvhd, tkhd, mdhd); остальное переносит carry_meta
                   "-map_metadata", "0", "-map_chapters", "0",
                   # Dolby Vision (блок dvvC) ffmpeg пишет в MP4 только так; без него — HLG без Dolby Vision
                   "-strict", "unofficial",
                   # без +faststart: заголовок moov — в конце файла (как у iPhone), carry_meta меняет его,
                   # не сдвигая видео
                   "-progress", "pipe:1", "-nostats", dst], cancel, gentle, on_line=line)
    carry_meta(job.path, dst)
    on_part(0.45)
    _check_remux(job.path, info, keep, dst, duration, cancel, gentle)
    on_part(1.0)
    job.how, job.check = tr("без пересжатия"), "streams"
    if dropped:
        job.note = tr("служебных дорожек не перенесено: {n} (MP4 их не хранит)", n=dropped)


def _check_remux(src, info, keep, dst, duration, cancel, gentle):
    new = compcore.probe(dst)
    streams = [s for s in new.get("streams", []) if s.get("codec_tag_string") != "tmcd"]
    if [s.get("codec_name") for s in streams] != [s.get("codec_name") for s in keep]:
        raise Skip("после перекладки дорожки не сходятся с оригиналом")
    try:
        new_dur = float(new.get("format", {}).get("duration") or 0)
    except ValueError:
        new_dur = 0
    if duration and abs(new_dur - duration) > 0.1:
        raise Skip("после перекладки не сходится длина ролика")
    for a, b in zip(keep, streams):
        if a.get("codec_type") != "video":
            continue
        if (a.get("tags") or {}).get("timecode") != (b.get("tags") or {}).get("timecode"):
            raise Skip("после перекладки не сходится тайм-код")
        ra, rb = _side(a, "Display Matrix"), _side(b, "Display Matrix")
        if (ra or {}).get("rotation", 0) != (rb or {}).get("rotation", 0):
            raise Skip("после перекладки ролик повернулся бы иначе")
        if bool(_side(a, "DOVI")) != bool(_side(b, "DOVI")):
            raise Skip("после перекладки пропал бы Dolby Vision")
    old_tags, new_tags = _tags(info), _tags(new)
    lost = sorted(k for k in old_tags.keys() | new_tags.keys() if new_tags.get(k) != old_tags.get(k))
    if lost:
        raise Skip(tr("не перенеслись метаданные: {keys}", keys=", ".join(lost[:4])))
    if not compcore.same_timing(src, dst):
        raise Skip("после перекладки кадры сдвинулись по времени")
    if (stream_hashes(src, [s["index"] for s in keep], cancel, gentle) !=
            stream_hashes(dst, [s["index"] for s in streams], cancel, gentle)):
        raise Skip("после перекладки видео или звук не совпали с оригиналом байт в байт")


def convert_one(job, cancel=None, gentle=False, threads=1, on_part=lambda f: None, taken=None, lock=None):
    """Сделать новый файл в рабочей папке и проверить. Успех — job.out и job.target; нет — job.skip."""
    os.makedirs(WORK, exist_ok=True)
    dst = target = ""
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
        with lock:                                  # два «IMG_1.MOV» и «IMG_1.mov» не получат одно имя
            target = compcore.target_for(job.path, ".mp4", taken)
            taken.add(os.path.normcase(target))
        dst = compcore._work_name(job.path, WORK, os.path.basename(target))
        _remux(job, info, dst, cancel, gentle, on_part)
        job.out, job.new_size, job.target = dst, os.path.getsize(dst), target
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
    if job.skip and target:
        with lock:
            taken.discard(os.path.normcase(target))
    return job


def missing_tools():
    return [n for n in ("ffmpeg", "ffprobe") if not compcore.tool(n)]


def prepare(root, progress=None, cancel=None, load="normal", on_job=None):
    """Найти MOV в root (папка или перетащенное) и подготовить MP4 рядом с ними — в рабочей папке."""
    clean_work()
    taken, lock = set(), threading.Lock()

    def one(job, cancel, gentle, threads, on_part):
        convert_one(job, cancel, gentle, threads, on_part, taken, lock)
    return compcore.run_jobs(root, VIDEO_IN, one, WORK, progress, cancel, load, on_job)
