"""Метаданные фото и видео: что файл рассказывает о человеке, и как это убрать без пересжатия.

read(path) — поля файла (Field) по группам GROUPS. clean_one(item, groups) — копия в рабочей папке без
выбранных групп; всё остальное в ней — байт в байт как было:

- JPEG: меняются только служебные блоки до картинки; сжатые данные картинки не трогаются вовсе.
- EXIF правится «на месте»: поле вынимается из таблицы, его данные затираются нулями, остальное не
  сдвигается — так не ломаются запись производителя (MakerNote) и превью, у которых внутри смещения.
  Если таких частей в EXIF не осталось — он собирается заново, компактно.
- Приложенное к снимку (карта яркости Ultra HDR, второй снимок MPO, видео «живого фото») остаётся
  на месте: смещения в MPF пересчитываются, EXIF приложенных картинок чистится без сдвигов.
- PNG: текстовые блоки, eXIf, tIME; блоки картинки — те же байт в байт.
- MP4 / MOV: размер файла не меняется: ненужные блоки становятся «free» и затираются нулями, время в
  заголовках — нули; потоки (видео, звук) не трогаются.

Поворот и цвет (Orientation, ICC, ColorSpace) — не метаданные о человеке, они остаются всегда.
Каждый файл после очистки читается заново: выбранного нет, остальное на месте, картинка та же.
"""

import hashlib
import os
import re
import shutil
import struct
import threading
import xml.etree.ElementTree as ET
from collections import Counter, namedtuple
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import compcore
import dupcore
from compcore import Skip
from dupcore import Cancelled, _check
from i18n import tr

GROUPS = {
    "place": "Место (GPS)",
    "camera": "Камера и серийный номер",
    "time": "Время съёмки",
    "author": "Автор и программа",
    "thumb": "Превью внутри файла",
    "other": "Прочее (XMP, IPTC, Samsung)",
}
PRESETS = {"all": tuple(GROUPS), "place": ("place",)}       # третий вариант — «свой набор» галочками

JPEG_EXT = compcore.JPEG_EXT
PNG_EXT = compcore.PNG_EXT
VIDEO_EXT = {".mp4", ".m4v", ".mov", ".3gp", ".3g2"}        # MP4 и его родня; MKV и WebM — пока нет
EXTS = JPEG_EXT | PNG_EXT | VIDEO_EXT

WORK = os.path.join(os.path.dirname(compcore.WORK), "meta")
MAX_PHOTO = 512 * 1024 ** 2          # фото читается в память целиком — больше этого не берём


@dataclass(frozen=True)
class Field:
    group: str
    name: str
    value: str = ""
    where: str = ""        # "" — сам файл; иначе — приложенная картинка, видео «живого фото» и т. п.
    locked: str = ""       # почему это поле не убрать (оно останется при любом выборе)


@dataclass(slots=True)
class Item:
    path: str
    size: int
    mtime: float
    fields: list = field(default_factory=list)
    skip: str = ""
    out: str = ""           # очищенная копия в рабочей папке
    new_size: int = 0
    saved_to: str = ""      # куда легла копия (режим «копии в папку»)

    @property
    def kind(self):
        return kind_of(self.path)

    @property
    def is_video(self):
        return self.kind == "video"

    def groups(self, removable=True):
        return {f.group for f in self.fields if not (removable and f.locked)}

    def to_remove(self, groups):
        return [f for f in self.fields if f.group in groups and not f.locked]


def kind_of(path):
    ext = os.path.splitext(path)[1].lower()
    return "jpeg" if ext in JPEG_EXT else "png" if ext in PNG_EXT else "video"


def _size(n):
    return dupcore.human_size(n)


def _short(text, n=80):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n - 1] + "…"


def _app(marker, body):
    if len(body) + 2 > 0xFFFF:
        raise Skip("служебный блок не помещается в JPEG")
    return bytes((0xFF, marker)) + struct.pack(">H", len(body) + 2) + body


# ---------------------------------------------------------------- EXIF (TIFF)

TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4}
Entry = namedtuple("Entry", "tag type count pos vpos vlen")    # pos — запись в таблице; vpos/vlen — значение
SUBIFD = {"ifd0": {0x8769: "exif", 0x8825: "gps"}, "exif": {0xA005: "interop"}}
POINTERS = {0x8769, 0x8825, 0xA005}
# Поля, внутри которых смещения: после пересборки EXIF они указывали бы мимо — тогда правим только на месте.
OFFSET_TAGS = {0x927C, 0x0111, 0x0201, 0x0144, 0x014A, 0xC634}

# Что о человеке: (группа, название). Остальное известное — технические поля картинки (их не трогаем),
# неизвестное — «прочее».
EXIF_TAGS = {
    0x010E: ("author", "Описание"),
    0x010F: ("camera", "Производитель камеры"),
    0x0110: ("camera", "Модель камеры"),
    0x0131: ("author", "Программа"),
    0x0132: ("time", "Дата изменения"),
    0x013B: ("author", "Автор"),
    0x013C: ("author", "Компьютер"),
    0x8298: ("author", "Авторские права"),
    0x9C9B: ("author", "Название"),
    0x9C9C: ("author", "Комментарий"),
    0x9C9D: ("author", "Автор"),
    0x9C9E: ("author", "Ключевые слова"),
    0x9C9F: ("author", "Тема"),
    0x9003: ("time", "Дата съёмки"),
    0x9004: ("time", "Дата оцифровки"),
    0x9010: ("time", "Часовой пояс"),
    0x9011: ("time", "Часовой пояс съёмки"),
    0x9012: ("time", "Часовой пояс оцифровки"),
    0x9290: ("time", "Доли секунды"),
    0x9291: ("time", "Доли секунды съёмки"),
    0x9292: ("time", "Доли секунды оцифровки"),
    0x927C: ("camera", "Служебная запись производителя"),
    0x9286: ("author", "Комментарий"),
    0xA420: ("camera", "Номер снимка"),
    0xA430: ("author", "Владелец камеры"),
    0xA431: ("camera", "Серийный номер камеры"),
    0xA432: ("camera", "Объектив"),
    0xA433: ("camera", "Производитель объектива"),
    0xA434: ("camera", "Модель объектива"),
    0xA435: ("camera", "Серийный номер объектива"),
    0x8825: ("place", "Геометка"),
}
# Настройки съёмки — тоже про камеру; показываются одной строкой.
SHOOTING = {0x829A, 0x829D, 0x8822, 0x8824, 0x8827, 0x8828, 0x8830, 0x8831, 0x8832, 0x9201, 0x9202, 0x9203,
            0x9204, 0x9205, 0x9206, 0x9207, 0x9208, 0x9209, 0x920A, 0x9214, 0x9400, 0x9401, 0x9402, 0x9403,
            0x9404, 0x9405, 0xA20B, 0xA20C, 0xA20E, 0xA20F, 0xA210, 0xA214, 0xA215, 0xA217, 0xA300, 0xA301,
            0xA302, 0xA401, 0xA402, 0xA403, 0xA404, 0xA405, 0xA406, 0xA407, 0xA408, 0xA409, 0xA40A, 0xA40B,
            0xA40C, 0xA460, 0xA461, 0xA462}
# Как показывать картинку: размеры, поворот, цвет, разрешение, версия формата. Не о человеке — не трогаем.
TECH = {0x0100, 0x0101, 0x0102, 0x0103, 0x0106, 0x0112, 0x0115, 0x011A, 0x011B, 0x011C, 0x0128, 0x012D,
        0x013E, 0x013F, 0x0211, 0x0212, 0x0213, 0x0214, 0x8769, 0xA005, 0x9000, 0x9101, 0x9102, 0xA000,
        0xA001, 0xA002, 0xA003, 0xA500}


def _tag_group(tag):
    if tag in EXIF_TAGS:
        return EXIF_TAGS[tag][0]
    if tag in SHOOTING:
        return "camera"
    if tag in TECH:
        return None
    return "other"


def _tag_name(tag):
    if tag in EXIF_TAGS:
        return tr(EXIF_TAGS[tag][1])
    from PIL import ExifTags
    return ExifTags.TAGS.get(tag) or f"EXIF 0x{tag:04X}"


class Tiff:
    """Таблицы EXIF (TIFF) внутри buf[start:end]: где лежат поля и их значения. Правка — strip()."""

    def __init__(self, buf, start, end, follow=True):
        self.buf, self.start, self.end = buf, start, end
        self.e = {b"II": "<", b"MM": ">"}.get(bytes(buf[start:start + 2]))
        if self.e is None or end - start < 8 or self.u16(start + 2) != 42:
            raise Skip("испорченный EXIF")
        self.ifds = {}                  # имя → (позиция таблицы, [Entry], позиция «следующей таблицы»)
        self.bad_next = False
        seen = set()
        self._read("ifd0", self.u32(start + 4), seen, follow)
        if follow:
            nxt = self.u32(self.ifds["ifd0"][2])
            if nxt:
                try:
                    self._read("ifd1", nxt, seen, False)
                except Skip:
                    self.bad_next = True        # указатель в никуда — не трогаем его и EXIF не пересобираем

    def u16(self, p):
        return struct.unpack_from(self.e + "H", self.buf, p)[0]

    def u32(self, p):
        return struct.unpack_from(self.e + "I", self.buf, p)[0]

    def _read(self, name, off, seen, follow):
        p = self.start + off
        if off < 8 or off in seen or p + 2 > self.end:
            raise Skip("испорченный EXIF")
        seen.add(off)
        n = self.u16(p)
        if p + 2 + 12 * n + 4 > self.end:
            raise Skip("испорченный EXIF")
        ents = []
        for k in range(n):
            q = p + 2 + 12 * k
            tag, typ, cnt = self.u16(q), self.u16(q + 2), self.u32(q + 4)
            size = TYPE_SIZE.get(typ)
            vlen = size * cnt if size else None
            vpos = None
            if vlen is not None and vlen <= 4:
                vpos = q + 8
            elif vlen is not None:
                v = self.start + self.u32(q + 8)
                if self.start + 8 <= v and v + vlen <= self.end:
                    vpos = v
            ents.append(Entry(tag, typ, cnt, q, vpos, vlen))
        self.ifds[name] = (p, ents, p + 2 + 12 * n)
        if follow:
            for tag, sub in SUBIFD.get(name, {}).items():
                e = self.find(name, tag)
                if e is not None and e.vpos is not None and e.type in (4, 13) and e.count == 1:
                    self._read(sub, self.u32(e.vpos), seen, True)

    def find(self, name, tag):
        return next((e for e in self.ifds.get(name, (0, []))[1] if e.tag == tag), None)

    def entries(self, name):
        return self.ifds.get(name, (0, []))[1]

    # ---------- значения

    def raw(self, e):
        return bytes(self.buf[e.vpos:e.vpos + e.vlen]) if e.vpos is not None else b""

    def value(self, e):
        raw = self.raw(e)
        if not raw:
            return None
        t, n = e.type, e.count
        if t == 2:
            return raw.split(b"\0", 1)[0].decode("utf-8", "replace").strip()
        fmt = {3: "H", 8: "h", 4: "I", 9: "i", 11: "f", 12: "d"}.get(t)
        if fmt:
            return list(struct.unpack(self.e + fmt * n, raw))
        if t in (5, 10):
            v = struct.unpack(self.e + ("I" if t == 5 else "i") * (2 * n), raw)
            return [(v[i], v[i + 1]) for i in range(0, len(v), 2)]
        return raw

    def text(self, e):
        v = self.value(e)
        if v is None:
            return ""
        if e.tag == 0x927C:
            return _size(e.vlen)
        if e.tag in (0x9C9B, 0x9C9C, 0x9C9D, 0x9C9E, 0x9C9F) and isinstance(v, (bytes, list)):
            raw = self.raw(e)
            return _short(raw.decode("utf-16-le", "replace").rstrip("\0"))
        if e.tag == 0x9286 and isinstance(v, bytes):
            code, body = v[:8], v[8:]
            text = body.decode("utf-16-le" if code.startswith(b"UNICODE") else "utf-8", "replace")
            return _short(text.strip("\0 "))
        if isinstance(v, bytes):
            s = v.rstrip(b"\0")
            if s and all(32 <= c < 127 for c in s):
                return _short(s.decode("ascii"))
            return _size(len(v))
        if isinstance(v, list):
            parts = [_rational(*x) if isinstance(x, tuple) else str(x) for x in v[:8]]
            return _short(" ".join(parts))
        return _short(v)

    def shooting(self, ents):
        by = {e.tag: self.value(e) for e in ents}
        parts = []
        if by.get(0x829D):
            parts.append("f/" + _rational(*by[0x829D][0]))
        if by.get(0x829A):
            n, d = by[0x829A][0]
            parts.append(f"1/{round(d / n)}" if n and d and n < d else _rational(n, d))
        if by.get(0x8827):
            parts.append(f"ISO {by[0x8827][0]}")
        if by.get(0x920A):
            parts.append(tr("{v} мм", v=_rational(*by[0x920A][0])))
        rest = len(ents) - sum(1 for t in (0x829D, 0x829A, 0x8827, 0x920A) if by.get(t))
        if rest:
            parts.append(tr("ещё полей: {n}", n=rest))
        return " · ".join(parts)

    def coords(self):
        g = {e.tag: self.value(e) for e in self.entries("gps")}
        try:
            lat = _dms(g[2]) * (-1 if str(g.get(1, "N")).upper().startswith("S") else 1)
            lon = _dms(g[4]) * (-1 if str(g.get(3, "E")).upper().startswith("W") else 1)
            return f"{lat:.5f}, {lon:.5f}"
        except (KeyError, TypeError, ZeroDivisionError, IndexError):
            return tr("без координат")

    def fields(self, where=""):
        out, shoot = [], []
        for name in ("ifd0", "exif"):
            for e in self.entries(name):
                g = _tag_group(e.tag)
                if g is None or e.tag in POINTERS:
                    continue
                if e.tag in SHOOTING:
                    shoot.append(e)
                    continue
                out.append(Field(g, _tag_name(e.tag), self.text(e), where))
        if shoot:
            out.append(Field("camera", tr("Параметры съёмки"), self.shooting(shoot), where))
        if any(e.tag != 0 for e in self.entries("gps")):           # одна версия GPS без данных — не геометка
            out.append(Field("place", tr("Геометка"), self.coords(), where))
        if "ifd1" in self.ifds:
            n = self.find("ifd1", 0x0202)
            size = self.value(n)[0] if n is not None and self.value(n) else 0
            out.append(Field("thumb", tr("Превью в EXIF"), _size(size) if size else "", where))
        return out

    # ---------- правка

    def _ranges(self, name, ents):
        """Где лежат значения полей (вне самой таблицы) и, для превью, его данные."""
        r = [(e.vpos, e.vpos + e.vlen) for e in ents if e.vpos is not None and e.vlen > 4]
        if name == "ifd1":
            for off_tag, len_tag in ((0x0201, 0x0202), (0x0111, 0x0117)):
                o, n = self.find("ifd1", off_tag), self.find("ifd1", len_tag)
                if o is not None and n is not None and self.value(o) and self.value(n):
                    for a, b in zip(self.value(o), self.value(n)):
                        if self.start + a + b <= self.end:
                            r.append((self.start + a, self.start + a + b))
        return r

    def strip(self, groups, compact):
        """Убрать поля выбранных групп. None — убирать нечего; иначе — новый TIFF (b"" — EXIF больше не нужен).

        compact=False — только «на месте»: размер и положение всего, что остаётся, не меняются.
        """
        remove = {name: set() for name in self.ifds}
        drop = set()
        for name in ("ifd0", "exif"):
            for e in self.entries(name):
                if _tag_group(e.tag) in groups:
                    remove[name].add(e.tag)
        if "place" in groups and "gps" in self.ifds:
            remove["ifd0"].add(0x8825)
            drop.add("gps")
        if "thumb" in groups and "ifd1" in self.ifds:
            drop.add("ifd1")
        if not any(remove.values()) and not drop:
            return None
        kept = {name: [e for e in ents if e.tag not in remove[name]]
                for name, (_p, ents, _n) in self.ifds.items() if name not in drop}
        can_compact = (compact and not self.bad_next and "ifd1" not in kept
                       and all(e.tag not in OFFSET_TAGS and e.vpos is not None
                               for ents in kept.values() for e in ents))
        if can_compact:
            return self._compact(kept)
        return self._in_place(remove, drop, kept)

    def _compact(self, kept):
        def raw_entries(name):
            return [(e.tag, e.type, e.count, self.raw(e)) for e in kept.get(name, []) if e.tag not in POINTERS]
        interop = raw_entries("interop")
        exif = raw_entries("exif")
        gps = raw_entries("gps")
        ifd0 = raw_entries("ifd0")
        subs0 = {}
        if exif or interop:
            subs0[0x8769] = (exif, {0xA005: (interop, {})} if interop else {})
        if gps:
            subs0[0x8825] = (gps, {})
        if not (ifd0 or exif or gps or interop):
            return b""                                      # ничего не осталось — EXIF больше не нужен
        out = bytearray(b"II*\x00" if self.e == "<" else b"MM\x00*")
        out += struct.pack(self.e + "I", 8)

        def put(entries, subs):
            items = sorted([(t, ty, c, r) for t, ty, c, r in entries] + [(t, 4, 1, None) for t in subs])
            pos = len(out)
            out.extend(struct.pack(self.e + "H", len(items)) + bytes(12 * len(items) + 4))
            later = []
            for k, (tag, typ, cnt, raw) in enumerate(items):
                ep = pos + 2 + 12 * k
                struct.pack_into(self.e + "HHI", out, ep, tag, typ, cnt)
                if raw is None:
                    later.append((ep, tag))
                elif len(raw) <= 4:
                    out[ep + 8:ep + 8 + len(raw)] = raw
                else:
                    if len(out) % 2:
                        out.append(0)
                    struct.pack_into(self.e + "I", out, ep + 8, len(out))
                    out.extend(raw)
            for ep, tag in later:
                if len(out) % 2:
                    out.append(0)
                struct.pack_into(self.e + "I", out, ep + 8, put(*subs[tag]))
            return pos

        put(ifd0, subs0)
        return bytes(out)

    def _in_place(self, remove, drop, kept):
        wipe, keep = [], []
        for name, (p, ents, nxt) in self.ifds.items():
            if name in drop:
                wipe.append((p, nxt + 4))
                wipe += self._ranges(name, ents)
                continue
            rows = [bytes(self.buf[e.pos:e.pos + 12]) for e in kept[name]]
            next_ptr = bytes(self.buf[nxt:nxt + 4])
            if name == "ifd0" and "ifd1" in drop:
                next_ptr = bytes(4)
            table = struct.pack(self.e + "H", len(rows)) + b"".join(rows) + next_ptr
            self.buf[p:nxt + 4] = table + bytes(nxt + 4 - p - len(table))
            keep.append((p, p + len(table)))
            keep += self._ranges(name, kept[name])
            gone = [e for e in ents if e.tag in remove.get(name, ())]
            wipe += self._ranges(name, gone)
        mask = bytearray(self.end - self.start)
        for a, b in wipe:
            mask[a - self.start:b - self.start] = b"\x01" * (b - a)
        for a, b in keep:
            mask[a - self.start:b - self.start] = bytes(b - a)
        for i, m in enumerate(mask):
            if m:
                self.buf[self.start + i] = 0
        return bytes(self.buf[self.start:self.end])


def _rational(n, d):
    if not d:
        return str(n)
    v = n / d
    return str(int(v)) if v == int(v) else f"{v:.2f}".rstrip("0")


def _dms(v):
    d, m, s = (n / den if den else 0 for n, den in v[:3])
    return d + m / 60 + s / 3600


# ---------------------------------------------------------------- XMP

XMP_SIG = b"http://ns.adobe.com/xap/1.0/\x00"
XMP_EXT_SIG = b"http://ns.adobe.com/xmp/extension/\x00"
RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
NS = {
    "exif": "http://ns.adobe.com/exif/1.0/",
    "exifEX": "http://cipa.jp/exif/1.0/",
    "tiff": "http://ns.adobe.com/tiff/1.0/",
    "xmp": "http://ns.adobe.com/xap/1.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "photoshop": "http://ns.adobe.com/photoshop/1.0/",
    "iptc": "http://iptc.org/std/Iptc4xmpCore/1.0/xmlns/",
    "iptcExt": "http://iptc.org/std/Iptc4xmpExt/2008-02-29/",
    "xmpRights": "http://ns.adobe.com/xap/1.0/rights/",
    "aux": "http://ns.adobe.com/exif/1.0/aux/",
}
# Без этого снимок покажется не так: карта яркости HDR, «живое фото», панорама 360°. Не трогаем никогда.
XMP_NEEDED = {"http://ns.adobe.com/hdr-gain-map/1.0/", "http://ns.google.com/photos/1.0/container/",
              "http://ns.google.com/photos/1.0/container/item/", "http://ns.google.com/photos/1.0/camera/",
              "http://ns.google.com/photos/1.0/panorama/", "http://ns.adobe.com/xmp/note/", "adobe:ns:meta/",
              RDF_NS}
TIFF_TECH = {"Orientation", "XResolution", "YResolution", "ResolutionUnit", "ImageWidth", "ImageLength",
             "BitsPerSample", "Compression", "PhotometricInterpretation", "SamplesPerPixel",
             "YCbCrPositioning", "YCbCrSubSampling", "PlanarConfiguration"}


def _xmp_group(uri, local):
    if uri in XMP_NEEDED:
        return None
    if uri == NS["exif"]:
        if local.startswith("GPS"):
            return "place"
        if local.startswith("DateTime"):
            return "time"
        if local in ("PixelXDimension", "PixelYDimension", "ColorSpace", "ExifVersion"):
            return None
        return "camera"
    if uri == NS["exifEX"]:
        return "author" if local == "CameraOwnerName" else "camera"
    if uri == NS["tiff"]:
        if local in TIFF_TECH:
            return None
        if local in ("Make", "Model"):
            return "camera"
        return "time" if local == "DateTime" else "author"
    if uri == NS["xmp"]:
        if local.endswith("Date"):
            return "time"
        return "author" if local == "CreatorTool" else "thumb" if local == "Thumbnails" else "other"
    if uri == NS["dc"]:
        return None if local == "format" else "author"
    if uri == NS["photoshop"]:
        if local in ("City", "State", "Country"):
            return "place"
        if local == "DateCreated":
            return "time"
        return "author" if local in ("Credit", "Source", "AuthorsPosition", "CaptionWriter") else "other"
    if uri == NS["iptc"]:
        if local in ("Location", "CountryCode"):
            return "place"
        return "author" if local == "CreatorContactInfo" else "other"
    if uri == NS["iptcExt"]:
        return "place" if local.startswith("Location") else "other"
    if uri == NS["xmpRights"]:
        return "author"
    if uri == NS["aux"]:
        return "author" if local == "OwnerName" else "camera"
    return "other"


_ET_LOCK = threading.Lock()


def _qname(key):
    if key.startswith("{"):
        uri, local = key[1:].split("}", 1)
        return uri, local
    return "", key


def _xmp_bounds(raw):
    m = re.search(rb"<(?:[\w.-]+:)?xmpmeta\b", raw)
    tag = b"xmpmeta"
    if not m:
        m = re.search(rb"<(?:[\w.-]+:)?RDF\b", raw)
        tag = b"RDF"
    if not m:
        return None
    close = list(re.finditer(rb"</(?:[\w.-]+:)?" + tag + rb"\s*>", raw))
    if not close:
        return None
    return m.start(), close[-1].end()


def _xmp_props(root):
    rdf = root if root.tag == f"{{{RDF_NS}}}RDF" else root.find(f"{{{RDF_NS}}}RDF")
    if rdf is None:
        return []
    out = []
    for desc in rdf.findall(f"{{{RDF_NS}}}Description"):
        for k, v in desc.attrib.items():
            uri, local = _qname(k)
            out.append((desc, "attr", k, uri, local, v))
        for child in list(desc):
            uri, local = _qname(child.tag)
            text = " ".join(t.strip() for t in child.itertext() if t.strip())
            out.append((desc, "elem", child, uri, local, text))
    return out


def _xmp(raw, groups=frozenset(), where="", size=None, fixed_reason=""):
    """XMP-пакет raw: (поля, новый пакет). Новый — None, если не менялся; b"" — больше не нужен.

    size — новый пакет должен быть ровно такого размера (место в файле не двигается): разница уходит
    в пробелы-заполнитель, который XMP для этого и держит. fixed_reason — менять нельзя вовсе.
    """
    bounds = _xmp_bounds(raw)
    root = None
    if bounds:
        try:
            root = ET.fromstring(raw[bounds[0]:bounds[1]])
        except ET.ParseError:
            root = None
    if root is None:
        return [Field("other", "XMP", tr("не разобрать"), where, tr("XMP не разобрать — не трогаю"))], None
    fields, gone = [], []
    for desc, how, key, uri, local, value in _xmp_props(root):
        g = _xmp_group(uri, local)
        if g is None:
            continue
        shown = _size(len(value)) if g == "thumb" else _short(value)
        fields.append(Field(g, f"XMP {local}", shown, where, fixed_reason))
        if g in groups and not fixed_reason:
            gone.append((desc, how, key))
    if not gone:
        return fields, None
    for desc, how, key in gone:
        if how == "attr":
            del desc.attrib[key]
        else:
            desc.remove(key)
    left = [p for p in _xmp_props(root) if p[3] not in (RDF_NS, "adobe:ns:meta/") and
            not (p[1] == "attr" and p[3] == RDF_NS)]
    if not left and size is None:
        return fields, b""
    with _ET_LOCK:
        for prefix, uri in re.findall(rb'xmlns:([\w.-]+)\s*=\s*["\']([^"\']+)["\']', raw):
            try:
                ET.register_namespace(prefix.decode(), uri.decode("utf-8", "replace"))
            except ValueError:
                pass
        xml = ET.tostring(root, encoding="unicode").encode("utf-8")
    new = raw[:bounds[0]] + xml + raw[bounds[1]:]
    if size is not None:
        new = _fit(new, size, len(raw[:bounds[0]]) + len(xml))
    return fields, new


def _fit(data, size, after):
    """Подогнать пакет XMP под размер size за счёт пробелов-заполнителя после XML (с позиции after)."""
    diff = size - len(data)
    if diff == 0:
        return data
    end = data.rfind(b"<?xpacket end")
    if end < after:
        end = len(data)
    pad_from = end
    while pad_from > after and data[pad_from - 1] in b" \t\r\n":
        pad_from -= 1
    if diff > 0:
        return data[:end] + b" " * diff + data[end:]
    if end - pad_from < -diff:
        raise Skip("XMP не помещается на старое место")
    return data[:end + diff] + data[end:]


# ---------------------------------------------------------------- IPTC (блок Photoshop)

PS_SIG = b"Photoshop 3.0\x00"
IPTC = {
    (2, 5): ("other", "Название"), (2, 25): ("other", "Ключевые слова"), (2, 105): ("other", "Заголовок"),
    (2, 80): ("author", "Автор"), (2, 85): ("author", "Должность автора"), (2, 110): ("author", "Источник"),
    (2, 115): ("author", "Источник"), (2, 116): ("author", "Авторские права"), (2, 120): ("author", "Описание"),
    (2, 122): ("author", "Автор описания"), (2, 65): ("author", "Программа"), (2, 70): ("author", "Программа"),
    (2, 90): ("place", "Город"), (2, 92): ("place", "Район"), (2, 95): ("place", "Регион"),
    (2, 100): ("place", "Код страны"), (2, 101): ("place", "Страна"), (2, 26): ("place", "Место"),
    (2, 55): ("time", "Дата создания"), (2, 60): ("time", "Время создания"), (2, 62): ("time", "Дата оцифровки"),
    (2, 63): ("time", "Время оцифровки"), (2, 30): ("time", "Дата публикации"), (2, 35): ("time", "Время публикации"),
    (1, 90): (None, ""), (2, 0): (None, ""),
}


def _irb(body):
    """Блоки Photoshop: [(id, сырые байты блока, данные)]."""
    out, i = [], 0
    while i < len(body):
        if body[i:i + 4] != b"8BIM" or i + 8 > len(body):
            if body[i:].strip(b"\0"):
                raise Skip("испорченный блок Photoshop")
            break
        rid = struct.unpack_from(">H", body, i + 4)[0]
        nl = body[i + 6]
        j = i + 6 + 1 + nl
        j += j - i & 1                      # имя дополнено до чётной длины
        if j + 4 > len(body):
            raise Skip("испорченный блок Photoshop")
        size = struct.unpack_from(">I", body, j)[0]
        end = j + 4 + size + (size & 1)
        if j + 4 + size > len(body):
            raise Skip("испорченный блок Photoshop")
        out.append((rid, body[i:min(end, len(body))], body[j + 4:j + 4 + size], body[i:j + 4]))
        i = end
    return out


def _iptc_sets(data):
    out, i = [], 0
    while i + 5 <= len(data) and data[i] == 0x1C:
        rec, ds, n = data[i + 1], data[i + 2], struct.unpack_from(">H", data, i + 3)[0]
        if n & 0x8000:
            raise Skip("необычный IPTC")
        out.append((rec, ds, data[i:i + 5 + n], data[i + 5:i + 5 + n]))
        i += 5 + n
    return out


def _ps(body, groups=frozenset(), where=""):
    """Блок Photoshop (APP13): поля и новый блок (None — не менялся, b"" — не нужен)."""
    try:
        blocks = _irb(body)
    except Skip:
        f = Field("other", "Photoshop / IPTC", _size(len(body)), where)
        return [f], (b"" if "other" in groups else None)
    fields, out, changed, digest_at = [], [], False, None
    iptc_new = None
    for rid, raw, data, head in blocks:
        if rid == 0x0404:
            kept = []
            for rec, ds, whole, val in _iptc_sets(data):
                g, name = IPTC.get((rec, ds), ("other", f"{rec}:{ds}"))
                if g is None:
                    kept.append(whole)
                    continue
                fields.append(Field(g, f"IPTC {tr(name) if name else ''}".strip(), _short(val.decode("utf-8", "replace")),
                                    where))
                if g in groups:
                    changed = True
                else:
                    kept.append(whole)
            new_data = b"".join(kept)
            if new_data == data:
                out.append(raw)
                continue
            iptc_new = new_data
            if not any(not (w[1] == 2 and w[2] == 0) and not (w[1] == 1 and w[2] == 90) for w in kept):
                iptc_new = b""
                continue                                     # остались одни служебные — блок не нужен
            out.append(head[:-4] + struct.pack(">I", len(new_data)) + new_data + b"\0" * (len(new_data) & 1))
        elif rid in (0x0409, 0x040C):
            fields.append(Field("thumb", tr("Превью Photoshop"), _size(len(data)), where))
            if "thumb" in groups:
                changed = True
            else:
                out.append(raw)
        elif rid == 0x0425:                                  # контрольная сумма IPTC — пересчитаем ниже
            digest_at = len(out)
            out.append(raw)
        else:
            fields.append(Field("other", f"Photoshop 0x{rid:04X}", _size(len(data)), where))
            if "other" in groups:
                changed = True
            else:
                out.append(raw)
    if not changed:
        return fields, None
    if digest_at is not None and iptc_new is not None:
        rid, raw, data, head = next(b for b in blocks if b[0] == 0x0425)
        out[digest_at] = (head + hashlib.md5(iptc_new).digest()) if iptc_new else b""
    out = [b for b in out if b]
    if not out:
        return fields, b""
    return fields, PS_SIG + b"".join(out)


# ---------------------------------------------------------------- JPEG

def _jpeg_parts(data):
    """Служебные блоки до сжатых данных [(маркер, начало, конец)] и смещение SOS."""
    if data[:3] != b"\xff\xd8\xff":
        raise Skip("файл не похож на JPEG")
    out, i = [], 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            raise Skip("испорченный JPEG")
        m = data[i + 1]
        if m == 0xFF:
            i += 1
            continue
        if m == 0xDA:
            return out, i
        n = struct.unpack_from(">H", data, i + 2)[0]
        if n < 2 or i + 2 + n > len(data):
            raise Skip("испорченный JPEG")
        out.append((m, i, i + 2 + n))
        i += 2 + n
    raise Skip("испорченный JPEG")


# Маркер внутри сжатых данных: FF, за которым не 00 (байт данных), не FF (заполнитель) и не RST0–7.
_MARKER = re.compile(rb"\xff[^\x00\xff\xd0-\xd7]")


def _main_end(data, sos):
    """Позиция сразу после EOI основной картинки (сжатые данные пролистываются поиском, а не по байту)."""
    n, i = len(data), sos
    while i + 1 < n:
        while i + 1 < n and data[i] == 0xFF and data[i + 1] == 0xFF:     # заполнители перед маркером
            i += 1
        if data[i] != 0xFF or i + 1 >= n:
            break
        marker = data[i + 1]
        if marker == 0xD9:
            return i + 2
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            i += 2
            continue
        if i + 4 > n:
            break
        i += 2 + struct.unpack_from(">H", data, i + 2)[0]
        if marker == 0xDA:
            m = _MARKER.search(data, i)
            if not m:
                break
            i = m.start()
    raise Skip("испорченный JPEG: нет конца картинки")


def _seg_kind(m, seg):
    body = seg[4:]
    if m == 0xE0:
        return ("thumb", tr("Превью JFXX")) if body.startswith(b"JFXX\0") else ("keep", "")
    if m == 0xE1:
        if body.startswith(b"Exif\0"):
            return "exif", ""
        if body.startswith(XMP_SIG):
            return "xmp", ""
        if body.startswith(XMP_EXT_SIG):
            return "other", tr("XMP (дополнительный)")
    if m == 0xE2:
        if body.startswith(b"ICC_PROFILE\0"):
            return "keep", ""
        if body.startswith(b"urn:iso:std:iso:ts:21496"):
            return "keep", ""                   # описание HDR-карты по ISO 21496 — без него HDR не покажется
        if body.startswith(b"MPF\0"):
            return "mpf", ""
        if body.startswith(b"FPXR\0"):
            return "thumb", tr("Превью FlashPix")
    if m == 0xED and body.startswith(PS_SIG):
        return "ps", ""
    if m == 0xEE:
        return "keep", ""                       # Adobe: как раскладывать цвета
    if m == 0xFE:
        return "com", ""
    if 0xE0 <= m <= 0xEF:
        if m == 0xEB and (b"jumb" in body[:64] or b"c2pa" in body[:256]):
            return "other", tr("Подпись C2PA (история снимка)")
        sig = body[:24].split(b"\0", 1)[0]
        label = sig.decode("ascii") if sig and all(32 <= c < 127 for c in sig) else ""
        return "other", tr("Служебный блок {name}", name=f"APP{m - 0xE0}" + (f" {label}" if label else ""))
    return "keep", ""


def _mpf_entries(seg):
    """Записи MPF: [(позиция поля «смещение» в seg, размер, смещение)] и порядок байт. Базой служит seg[8]."""
    try:
        t = Tiff(bytearray(seg), 8, len(seg), follow=False)
    except Skip:
        return [], None
    e = t.find("ifd0", 0xB002)
    if e is None or e.vpos is None:
        return [], None
    out = []
    for k in range(e.vlen // 16):
        p = e.vpos + 16 * k
        out.append((p + 8, t.u32(p + 4), t.u32(p + 8)))
    return out, t.e


ATTACHED_PART = "внутри приложенной картинки — не трогаю"


def _jpeg(data, groups=frozenset(), where="", fixed=False):
    """JPEG: (поля, новые байты или None). fixed — размер и расположение не меняются (приложенная картинка)."""
    parts, sos = _jpeg_parts(data)
    end = _main_end(data, sos)
    fields, out = [], bytearray(data[:2])
    others = {}                                   # прочие блоки одного вида — одной строкой с общим размером
    mpf = None
    lock = tr(ATTACHED_PART) if fixed else ""
    for m, s, e in parts:
        seg = data[s:e]
        kind, label = _seg_kind(m, seg)
        new = seg
        if kind == "exif":
            try:
                buf = bytearray(seg)
                t = Tiff(buf, 10, len(buf))
                fields += t.fields(where)
                res = t.strip(groups, compact=not fixed) if groups else None
                if res is not None:
                    new = bytes(buf) if fixed else (_app(0xE1, b"Exif\0\0" + res) if res else b"")
            except Skip:
                fields.append(Field("other", "EXIF", tr("не разобрать"), where, tr("EXIF не разобрать — не трогаю")))
        elif kind == "xmp":
            fs, body = _xmp(seg[4 + len(XMP_SIG):], groups, where, fixed_reason=lock)
            fields += fs
            if body is not None:
                new = _app(0xE1, XMP_SIG + body) if body else b""
        elif kind == "ps":
            fs, body = _ps(seg[4 + len(PS_SIG):], groups if not fixed else frozenset(), where)
            fields += [f if not fixed else Field(f.group, f.name, f.value, f.where, lock) for f in fs]
            if body is not None:
                new = _app(0xED, body) if body else b""
        elif kind == "com":
            fields.append(Field("author", tr("Комментарий"), _short(seg[4:].decode("utf-8", "replace").strip("\0 ")),
                                where, lock))
            if "author" in groups and not fixed:
                new = b""
        elif kind in ("thumb", "other"):
            others[(kind, label)] = others.get((kind, label), 0) + len(seg)
            if kind in groups and not fixed:
                new = b""
        elif kind == "mpf":
            mpf = (s, len(out))
        out += new
    for (kind, label), n in others.items():
        fields.append(Field(kind, label, _size(n), where, lock))
    out += data[sos:end]
    if fixed:
        if len(out) != end:
            raise Skip("приложенная картинка изменила бы размер")
        new = bytes(out) + data[end:]
        return fields, (new if new != data else None)
    tf, tail = _jpeg_tail(data, end, groups, mpf)
    fields += tf
    new = bytes(out) + bytes(tail)
    if mpf:
        new = _patch_mpf(new, data, mpf, end, len(out))
    return fields, (new if new != data else None)


def _patch_mpf(new, old, mpf, old_end, new_end):
    """Смещения приложенных картинок в MPF отсчитываются от самого MPF: если блоки между ним и концом
    основной картинки поменяли размер, смещения сдвигаются на ту же разницу."""
    old_s, new_s = mpf
    seg_len = struct.unpack_from(">H", old, old_s + 2)[0] + 2
    seg = old[old_s:old_s + seg_len]
    entries, e = _mpf_entries(seg)
    d = (new_end - (new_s + 8)) - (old_end - (old_s + 8))
    if not d or not entries:
        return new
    buf = bytearray(new)
    for p, _size_, off in entries:
        if off:
            struct.pack_into(e + "I", buf, new_s + p, off + d)
    return bytes(buf)


# ---------------------------------------------------------------- хвост JPEG: приложенное и запись Samsung

SEF_GROUPS = {"Image_UTC_Data": "time", "MCC_Data": "place", "Camera_Capture_Mode_Info": "camera",
              "Color_Display_P3": None}
CONTENT = (b"\xff\xd8\xff", b"ftyp")


def _sef(tail):
    """Запись Samsung в конце файла: (начало, [(тип, имя, начало блока, длина, сырая запись)], версия) или None."""
    if len(tail) < 20 or tail[-4:] != b"SEFT":
        return None
    n = struct.unpack_from("<I", tail, len(tail) - 8)[0]
    d = len(tail) - 8 - n
    if d < 0 or tail[d:d + 4] != b"SEFH":
        return None
    ver, count = struct.unpack_from("<II", tail, d + 4)
    if n != 12 + 12 * count:
        return None
    entries = []
    for k in range(count):
        p = d + 12 + 12 * k
        pad, typ, off, size = struct.unpack_from("<HHII", tail, p)
        start = d - off
        if start < 0 or start + size > d:
            return None
        nl = struct.unpack_from("<I", tail, start + 4)[0] if size >= 8 else 0
        name = tail[start + 8:start + 8 + nl].decode("latin-1", "replace") if 8 + nl <= size else ""
        entries.append((pad, typ, name, start, size))
    if not entries:
        return None
    first = min(e[3] for e in entries)
    if sum(e[4] for e in entries) != d - first:          # между блоками что-то ещё — не разбираемся
        return None
    return first, entries, ver


def _sef_value(tail, start, size, nl):
    data = tail[start + 8 + nl:start + size]
    s = data.rstrip(b"\0")
    if s and all(32 <= c < 127 for c in s):
        return _short(s.decode("ascii"))
    return _size(size)


def _jpeg_tail(data, end, groups, mpf):
    """Поля и новые байты хвоста (всё после основной картинки)."""
    tail = bytearray(data[end:])
    fields = []
    if not tail.strip(b"\0"):
        return fields, tail
    sef = _sef(tail)
    sef_start = sef[0] if sef else len(tail)
    spans = []                                     # приложенные картинки: (начало, конец) в tail
    if mpf:
        old_s = mpf[0]
        seg = data[old_s:old_s + struct.unpack_from(">H", data, old_s + 2)[0] + 2]
        entries, _e = _mpf_entries(seg)
        for _p, size, off in entries:
            a = old_s + 8 + off - end
            if off and 0 <= a and a + size <= len(tail) and tail[a:a + 3] == b"\xff\xd8\xff":
                spans.append((a, a + size))
    else:
        a = len(tail) - len(tail.lstrip(b"\0"))
        if tail[a:a + 3] == b"\xff\xd8\xff":
            try:
                parts, sos = _jpeg_parts(bytes(tail[a:]))
                spans.append((a, a + _main_end(bytes(tail[a:]), sos)))
            except Skip:
                pass
    for n, (a, b) in enumerate(spans, 1):
        try:
            fs, new = _jpeg(bytes(tail[a:b]), groups, tr("приложенная картинка {n}", n=n), fixed=True)
        except Skip:
            continue
        fields += fs
        if new is not None:
            tail[a:b] = new
    # Видео «живого фото»: отдельно в конце или внутри записи Samsung.
    videos = []
    for m in re.finditer(rb"ftyp", tail):
        a = m.start() - 4
        if a < 0 or any(s <= a < e for s, e in spans) or any(s <= a < e for s, e in videos):
            continue
        b = len(tail)
        if sef:
            inside = [(st, st + sz) for _pd, _t, _nm, st, sz in sef[1] if st <= a < st + sz]
            b = inside[0][1] if inside else (sef_start if a < sef_start else b)
        videos.append((a, b))
    for a, b in videos:
        was, n = bytes(tail[a:b]), len(tail)
        try:
            fs = _mp4_walk(tail, a, b, groups, tr("видео «живого фото»"))
            if len(tail) != n:
                raise Skip("необычный MP4")
        except Skip:                                     # не разобрались — видео остаётся как было, целиком
            del tail[a:a + (len(tail) - n) + (b - a)]
            tail[a:a] = was
            fs = [Field("other", tr("Видео «живого фото»"), _size(b - a), "", tr("видео не разобрать — не трогаю"))]
        fields += fs
    if sef:
        content = any(any(sig in bytes(tail[st:st + sz]) for sig in CONTENT) for _p, _t, _n, st, sz in sef[1])
        lock = ""
        if content or videos:
            lock = tr("в записи Samsung лежат карта глубины или видео — не трогаю, чтобы они не потерялись")
        elif any(b > sef_start for _a, b in spans):
            lock = tr("запись Samsung не разобрать — не трогаю")
        kept, changed = [], False
        for pad, typ, name, st, sz in sorted(sef[1], key=lambda x: x[3]):
            g = SEF_GROUPS.get(name, "other")
            nl = struct.unpack_from("<I", tail, st + 4)[0] if sz >= 8 else 0
            is_content = any(sig in bytes(tail[st:st + sz]) for sig in CONTENT)
            if g is None or is_content:
                kept.append((pad, typ, st, sz))
                continue
            fields.append(Field(g, f"Samsung {name}", _sef_value(tail, st, sz, nl), "", lock))
            if g in groups and not lock:
                changed = True
            else:
                kept.append((pad, typ, st, sz))
        if changed:
            blocks = b"".join(bytes(tail[st:st + sz]) for _p, _t, st, sz in kept)
            new = bytearray(tail[:sef_start])
            if kept:
                pos = []
                acc = 0
                for _p, _t, _st, sz in kept:
                    pos.append(acc)
                    acc += sz
                d = len(blocks)
                head = b"SEFH" + struct.pack("<II", sef[2], len(kept))
                for (pad, typ, _st, sz), p in zip(kept, pos):
                    head += struct.pack("<HHII", pad, typ, d - p, sz)
                new += blocks + head + struct.pack("<I", len(head)) + b"SEFT"
            tail = new
    return fields, tail


def _image_parts(data):
    """Всё, что описывает саму картинку JPEG: таблицы, кадр, сжатые данные — без служебных блоков."""
    parts, sos = _jpeg_parts(data)
    end = _main_end(data, sos)
    # «keep» — таблицы, кадр, JFIF, Adobe, цветовой профиль ICC; их программа не меняет никогда.
    return b"".join(data[s:e] for m, s, e in parts if _seg_kind(m, data[s:e])[0] == "keep") + data[sos:end]


def _same_jpeg(old, new):
    """Картинка (и всё приложенное) та же байт в байт; приложенное по-прежнему находится по MPF."""
    if _image_parts(old) != _image_parts(new):
        raise Skip("картинка изменилась бы — файл не трогаю")

    def attached(data):
        parts, sos = _jpeg_parts(data)
        end = _main_end(data, sos)
        out = []
        for m, s, e in parts:
            if _seg_kind(m, data[s:e])[0] == "mpf":
                entries, _e = _mpf_entries(data[s:e])
                for _p, size, off in entries:
                    if off:
                        a = s + 8 + off
                        if data[a:a + 3] != b"\xff\xd8\xff":
                            raise Skip("приложенная картинка потерялась бы — файл не трогаю")
                        out.append(_image_parts(data[a:a + size]))
        return out, data[end:].count(b"ftyp")
    if attached(old) != attached(new):
        raise Skip("приложенная картинка изменилась бы — файл не трогаю")


# ---------------------------------------------------------------- PNG

PNG_SIG = b"\x89PNG\r\n\x1a\n"
PNG_KEEP = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"cHRM", b"gAMA", b"iCCP", b"sBIT", b"sRGB", b"cICP",
            b"mDCV", b"mDCv", b"cLLI", b"cLLi", b"bKGD", b"hIST", b"pHYs", b"sPLT", b"acTL", b"fcTL", b"fdAT",
            b"iDOT", b"oFFs", b"pCAL", b"sCAL", b"sTER"}
PNG_TEXT = {"author": "author", "copyright": "author", "software": "author", "comment": "author",
            "description": "author", "title": "author", "disclaimer": "author", "creation time": "time",
            "source": "camera", "warning": "other"}


def _png_text_group(key):
    k = key.lower()
    if k in PNG_TEXT:
        return PNG_TEXT[k]
    if k.startswith("date:"):
        return "time"
    if k.startswith("exif:"):
        name = k[5:]
        return ("place" if name.startswith("gps") else "time" if name.startswith("datetime")
                else "camera" if name in ("make", "model") else "other")
    return "other"


def _png_text(typ, body):
    import zlib
    key, _, rest = body.partition(b"\0")
    key = key.decode("latin-1")
    if typ == b"tEXt":
        return key, rest.decode("latin-1"), None
    if typ == b"zTXt":
        return key, zlib.decompress(rest[1:]).decode("latin-1", "replace"), None
    flag, method = rest[0], rest[1]
    lang, _, rest = rest[2:].partition(b"\0")
    tkey, _, text = rest.partition(b"\0")
    raw = zlib.decompress(text) if flag else text
    return key, raw.decode("utf-8", "replace"), (flag, method, lang, tkey, raw)


def _chunk(typ, body):
    import zlib
    return struct.pack(">I", len(body)) + typ + body + struct.pack(">I", zlib.crc32(typ + body) & 0xFFFFFFFF)


def _png_chunks(data):
    if not data.startswith(PNG_SIG):
        raise Skip("файл не похож на PNG")
    out, i = [], 8
    while i + 12 <= len(data):
        n = struct.unpack_from(">I", data, i)[0]
        if i + 12 + n > len(data):
            raise Skip("испорченный PNG")
        typ = data[i + 4:i + 8]
        out.append((typ, i, i + 12 + n))
        i += 12 + n
        if typ == b"IEND":
            break
    return out, i


def _png(data, groups=frozenset()):
    import zlib
    chunks, end = _png_chunks(data)
    fields, out = [], bytearray(PNG_SIG)
    for typ, s, e in chunks:
        whole, body = data[s:e], data[s + 8:e - 4]
        new = whole
        if typ in (b"tEXt", b"zTXt", b"iTXt"):
            try:
                key, text, itxt = _png_text(typ, body)
            except (zlib.error, IndexError, ValueError):
                key, text, itxt = typ.decode(), _size(len(body)), None
            if key == "XML:com.adobe.xmp" and itxt:
                fs, xmp = _xmp(itxt[4], groups)
                fields += fs
                if xmp is not None:
                    flag, method, lang, tkey, _raw = itxt
                    payload = zlib.compress(xmp) if flag else xmp
                    new = _chunk(b"iTXt", key.encode("latin-1") + b"\0" + bytes((flag, method)) + lang + b"\0" +
                                 tkey + b"\0" + payload) if xmp else b""
            elif key.lower().startswith("raw profile type"):
                fields.append(Field("other", key, _size(len(body))))
                if "other" in groups:
                    new = b""
            else:
                g = _png_text_group(key)
                fields.append(Field(g, key, _short(text)))
                if g in groups:
                    new = b""
        elif typ == b"eXIf":
            try:
                buf = bytearray(body)
                t = Tiff(buf, 0, len(buf))
                fields += t.fields()
                res = t.strip(groups, compact=True) if groups else None
                if res is not None:
                    new = _chunk(b"eXIf", res) if res else b""
            except Skip:
                fields.append(Field("other", "EXIF", tr("не разобрать"), "", tr("EXIF не разобрать — не трогаю")))
        elif typ == b"tIME":
            if len(body) == 7:
                y, mo, d, h, mi, sec = struct.unpack(">HBBBBB", body)
                value = f"{y:04}-{mo:02}-{d:02} {h:02}:{mi:02}:{sec:02}"
            else:
                value = ""
            fields.append(Field("time", tr("Дата изменения"), value))
            if "time" in groups:
                new = b""
        elif typ not in PNG_KEEP and typ[0] & 0x20:      # необязательный блок неизвестного вида
            fields.append(Field("other", typ.decode("latin-1"), _size(len(body))))
            if "other" in groups:
                new = b""
        out += new
    out += data[end:]
    new = bytes(out)
    return fields, (new if new != data else None)


def _same_png(old, new):
    def image(data):
        chunks, _end = _png_chunks(data)
        return [data[s:e] for typ, s, e in chunks if typ in PNG_KEEP or not typ[0] & 0x20]
    if image(old) != image(new):
        raise Skip("картинка изменилась бы — файл не трогаю")


# ---------------------------------------------------------------- MP4 / MOV

XMP_UUID = bytes.fromhex("BE7ACFCB97A942E89C71999491E3AFAC")
UDTA = {
    b"\xa9xyz": ("place", "Геометка"), b"loci": ("place", "Геометка"),
    b"\xa9day": ("time", "Дата записи"),
    b"\xa9mak": ("camera", "Производитель камеры"), b"\xa9mod": ("camera", "Модель камеры"),
    b"\xa9swr": ("author", "Программа"), b"\xa9too": ("author", "Программа"), b"\xa9enc": ("author", "Программа"),
    b"\xa9ART": ("author", "Автор"), b"\xa9aut": ("author", "Автор"), b"auth": ("author", "Автор"),
    b"perf": ("author", "Автор"), b"\xa9cpy": ("author", "Авторские права"), b"cprt": ("author", "Авторские права"),
    b"\xa9cmt": ("author", "Комментарий"), b"\xa9des": ("author", "Описание"), b"dscp": ("author", "Описание"),
    b"\xa9nam": ("author", "Название"), b"titl": ("author", "Название"), b"\xa9inf": ("author", "Описание"),
    b"desc": ("author", "Описание"), b"ldes": ("author", "Описание"),
    b"covr": ("thumb", "Обложка"), b"thmb": ("thumb", "Превью"),
    # Samsung: smta — превью ролика (JPEG ~250 КБ) и служебные записи; cami — параметры камеры.
    b"smta": ("thumb", "Превью и служебная запись Samsung"), b"cami": ("camera", "Параметры камеры Samsung"),
    b"free": (None, ""), b"skip": (None, ""), b"wide": (None, ""), b"hnti": (None, ""), b"hinf": (None, ""),
    b"name": (None, ""),
}
MDTA_NEEDED = ("com.apple.quicktime.content.identifier", "com.apple.quicktime.live-photo",
               "com.apple.quicktime.still-image-time", "com.android.capture.fps",
               "com.apple.quicktime.full-frame-rate-playback-intent")
EPOCH_1904 = datetime(1904, 1, 1, tzinfo=timezone.utc)


def _boxes(buf, start, end):
    i = start
    while i + 8 <= end:
        size = struct.unpack_from(">I", buf, i)[0]
        typ = bytes(buf[i + 4:i + 8])
        hdr = 8
        if size == 1:
            if i + 16 > end:
                raise Skip("испорченный MP4")
            size, hdr = struct.unpack_from(">Q", buf, i + 8)[0], 16
        elif size == 0:
            size = end - i
        if size < hdr or i + size > end:
            if size == 0 or typ == b"\0\0\0\0":
                return                                          # QuickTime: udta кончается нулём
            raise Skip("испорченный MP4")
        yield typ, i, i + hdr, i + size
        i += size


def _free(buf, s, c, e):
    """Блок становится «free» (его пропускают все программы), содержимое — нули. Размер тот же."""
    buf[s + 4:s + 8] = b"free"
    buf[c:e] = bytes(e - c)


THREEGPP = {b"auth", b"titl", b"dscp", b"perf", b"cprt", b"gnre", b"albm"}


def _3gpp_text(buf, c, e):
    """Текстовый блок 3GPP (Samsung пишет так auth = «Galaxy S24 Ultra»): версия, язык, строка до нуля."""
    body = bytes(buf[c + 6:e])
    if body[:2] in (b"\xfe\xff", b"\xff\xfe"):
        return _short(body.decode("utf-16", "replace").split("\0", 1)[0])
    return _short(body.split(b"\0", 1)[0].decode("utf-8", "replace"))


def _atom_text(buf, c, e):
    """Значение текстового блока: в стиле QuickTime (длина, язык, текст) или iTunes (вложенный data)."""
    body = bytes(buf[c:e])
    if body[4:8] == b"data" and len(body) >= 16:
        payload = body[16:struct.unpack_from(">I", body, 0)[0]]
        kind = struct.unpack_from(">I", body, 8)[0] & 0xFFFFFF
        if kind == 1:
            return _short(payload.decode("utf-8", "replace"))
        return _size(len(payload))
    if len(body) >= 4:
        n = struct.unpack_from(">H", body, 0)[0]
        if 0 < n <= len(body) - 4:
            return _short(body[4:4 + n].decode("utf-8", "replace").strip("\0"))
        rest = body[4:].rstrip(b"\0")                    # «полный» блок: 4 байта версии, потом текст (Samsung cami)
        if body[:4] == bytes(4) and rest and all(32 <= ch < 127 for ch in rest):
            return _short(rest.decode("ascii"))
    return _size(len(body))


def _loci_text(buf, c, e):
    """Геометка 3GPP (loci): версия, язык, название места до нуля, роль, долгота, широта (16.16)."""
    body = bytes(buf[c:e])
    z = body.find(b"\0", 6)
    if z < 0 or z + 10 > len(body):
        return _size(len(body))
    lon, lat = struct.unpack_from(">ii", body, z + 2)
    return f"{lat / 65536:.5f}, {lon / 65536:.5f}"


def _mdta_group(key):
    k = key.lower()
    if k.startswith(MDTA_NEEDED) or k in ("major_brand", "minor_version", "compatible_brands"):
        return None, ""
    if "location" in k or "gps" in k:
        return "place", tr("Геометка")
    if "creation" in k or "utc_offset" in k or k.endswith((".date", "date")):
        return "time", tr("Дата записи")
    if k == "encoder" or k.endswith((".encoder", ".software")) or k == "com.android.version":
        return "author", tr("Программа")
    if k in ("make", "manufacturer") or k.endswith((".make", ".manufacturer")):
        return "camera", tr("Производитель камеры")
    if k == "model" or k.endswith(".model"):
        return "camera", tr("Модель камеры")
    if "camera" in k or "lens" in k:
        return "camera", key
    if any(w in k for w in ("author", "artist", "copyright", "comment", "description", "title", "displayname",
                            "keywords", "publisher", "information")):
        return "author", key
    return "other", key


class _Mp4:
    def __init__(self, buf, groups, where):
        self.buf, self.groups, self.where = buf, groups, where
        self.fields, self.times = [], []

    def add(self, g, name, value, locked=""):
        self.fields.append(Field(g, name, value, self.where, locked))
        return g in self.groups and not locked

    def walk(self, start, end):
        for typ, s, c, e in _boxes(self.buf, start, end):
            if typ in (b"moov", b"trak", b"mdia", b"minf", b"stbl"):
                self.walk(c, e)
            elif typ in (b"mvhd", b"tkhd", b"mdhd"):
                self.times.append(c)
            elif typ == b"udta":
                self.udta(c, e)
            elif typ == b"meta":
                self.meta(s, c, e)
            elif typ == b"uuid" and bytes(self.buf[c:c + 16]) == XMP_UUID:
                self.xmp(c + 16, e, s)
            elif typ == b"stsd" and e - c >= 16 and bytes(self.buf[c + 12:c + 16]) in (b"gpmd", b"camm"):
                self.add("place", tr("Дорожка с GPS"), bytes(self.buf[c + 12:c + 16]).decode(),
                         tr("это отдельный поток внутри видео — без перепаковки не убрать"))

    def xmp(self, c, e, s):
        fs, new = _xmp(bytes(self.buf[c:e]), self.groups, self.where, size=e - c)
        self.fields += fs
        if new is not None:
            self.buf[c:e] = new

    def udta(self, start, end):
        for typ, s, c, e in _boxes(self.buf, start, end):
            if typ == b"meta":
                self.meta(s, c, e)
                continue
            if typ == b"XMP_":
                self.xmp(c, e, s)
                continue
            g, name = UDTA.get(typ, ("other", typ.decode("latin-1")))
            if g is None:
                continue
            value = (_loci_text(self.buf, c, e) if typ == b"loci" else
                     _3gpp_text(self.buf, c, e) if typ in THREEGPP else
                     _size(e - c) if g == "thumb" else _atom_text(self.buf, c, e))
            if self.add(g, tr(name) if name in _NAMES else name, value):
                _free(self.buf, s, c, e)

    def meta(self, s, c, e):
        buf = self.buf
        cs = c if bytes(buf[c + 4:c + 8]) == b"hdlr" else c + 4 if bytes(buf[c + 8:c + 12]) == b"hdlr" else None
        if cs is None:
            if self.add("other", "meta", _size(e - s)):
                _free(buf, s, c, e)
            return
        kids = list(_boxes(buf, cs, e))
        hdlr = next(k for k in kids if k[0] == b"hdlr")
        handler = bytes(buf[hdlr[2] + 8:hdlr[2] + 12])
        ilst = next((k for k in kids if k[0] == b"ilst"), None)
        if handler == b"mdir" and ilst:
            for typ, s2, c2, e2 in _boxes(buf, ilst[2], ilst[3]):
                g, name = UDTA.get(typ, ("other", typ.decode("latin-1")))
                if g is None:
                    continue
                value = _atom_text(buf, c2, e2) if g != "thumb" else _size(e2 - c2)
                if self.add(g, tr(name) if name in _NAMES else name, value):
                    _free(buf, s2, c2, e2)
            return
        if handler == b"mdta":
            self.mdta(s, c, e, cs, kids)
            return
        if self.add("other", f"meta {handler.decode('latin-1')}", _size(e - s)):
            _free(buf, s, c, e)

    def mdta(self, s, c, e, cs, kids):
        buf = self.buf
        keys = next((k for k in kids if k[0] == b"keys"), None)
        ilst = next((k for k in kids if k[0] == b"ilst"), None)
        if not keys or not ilst:
            return
        names, p = [], keys[2] + 8
        for _ in range(struct.unpack_from(">I", buf, keys[2] + 4)[0]):
            n = struct.unpack_from(">I", buf, p)[0]
            if n < 8 or p + n > keys[3]:
                raise Skip("испорченный MP4")
            names.append((bytes(buf[p:p + n]), bytes(buf[p + 8:p + n]).decode("utf-8", "replace")))
            p += n
        items, gone = [], set()
        for typ, s2, c2, e2 in _boxes(buf, ilst[2], ilst[3]):
            idx = struct.unpack(">I", typ)[0]
            key = names[idx - 1][1] if 0 < idx <= len(names) else ""
            items.append((idx, bytes(buf[s2:e2])))
            g, label = _mdta_group(key)
            if g is None:
                continue
            if self.add(g, label, _atom_text(buf, c2, e2)):
                gone.add(idx)
        if not gone:
            return
        new_index = {}
        kept_keys = []
        for i, (raw, _name) in enumerate(names, 1):
            if i not in gone:
                new_index[i] = len(kept_keys) + 1
                kept_keys.append(raw)
        new_keys = bytes(buf[keys[2]:keys[2] + 4]) + struct.pack(">I", len(kept_keys)) + b"".join(kept_keys)
        new_items = b"".join(raw[:4] + struct.pack(">I", new_index[idx]) + raw[8:]
                             for idx, raw in items if idx not in gone and idx in new_index)
        content = bytearray(buf[c:cs])
        for typ, s2, c2, e2 in kids:
            if typ == b"keys":
                content += struct.pack(">I", 8 + len(new_keys)) + b"keys" + new_keys
            elif typ == b"ilst":
                content += struct.pack(">I", 8 + len(new_items)) + b"ilst" + new_items
            else:
                content += buf[s2:e2]
        if c - s != 8:
            raise Skip("необычный MP4")
        new = struct.pack(">I", 8 + len(content)) + b"meta" + bytes(content)
        room = (e - s) - len(new)
        if room < 8:
            raise Skip("необычный MP4")
        buf[s:e] = new + struct.pack(">I", room) + b"free" + bytes(room - 8)

    def finish(self):
        stamps = []
        for c in self.times:
            v = self.buf[c]
            fmt = ">QQ" if v == 1 else ">II"
            stamps.append(struct.unpack_from(fmt, self.buf, c + 4))
        nonzero = [t for pair in stamps for t in pair if t]
        if nonzero:
            when = EPOCH_1904 + timedelta(seconds=nonzero[0])
            if self.add("time", tr("Дата записи"), when.strftime("%Y-%m-%d %H:%M:%S UTC")):
                for c in self.times:
                    n = 16 if self.buf[c] == 1 else 8
                    self.buf[c + 4:c + 4 + n] = bytes(n)
        return self.fields


_NAMES = {v[1] for v in UDTA.values()}


def _mp4_walk(buf, start, end, groups, where=""):
    m = _Mp4(buf, groups, where)
    m.walk(start, end)
    return m.finish()


def _top_boxes(f, size):
    out, i = [], 0
    while i + 8 <= size:
        f.seek(i)
        head = f.read(16)
        n, typ = struct.unpack_from(">I", head)[0], head[4:8]
        hdr = 8
        if n == 1:
            n, hdr = struct.unpack_from(">Q", head, 8)[0], 16
        elif n == 0:
            n = size - i
        if n < hdr or i + n > size:
            raise Skip("испорченный MP4")
        out.append((typ, i, i + n))
        i += n
    return out


def _mp4_file(path, groups=frozenset(), dst=None):
    """Поля видео; с dst — копия без выбранного. Возвращает (поля, изменённые места [(начало, конец)])."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        tops = _top_boxes(f, size)
        if not any(t == b"moov" for t, _s, _e in tops):
            raise Skip("в файле нет описания видео (moov)")
        regions = []
        for typ, s, e in tops:
            if typ in (b"moov", b"meta", b"udta", b"uuid"):
                if e - s > 256 * 1024 ** 2:
                    raise Skip("необычный MP4")
                f.seek(s)
                regions.append((s, bytearray(f.read(e - s))))
    fields, changed = [], []
    for s, buf in regions:
        before = bytes(buf)
        m = _Mp4(buf, groups, "")
        m.walk(0, len(buf))
        fields += m.finish()
        if len(buf) != len(before):                     # всё правится на месте — иначе сдвинулись бы потоки
            raise Skip("необычный MP4")
        if bytes(buf) != before:
            changed.append((s, buf))
    if dst is not None and changed:
        shutil.copyfile(path, dst)
        with open(dst, "r+b") as f:
            for s, buf in changed:
                f.seek(s)
                f.write(buf)
    return fields, [(s, s + len(buf)) for s, buf in changed]


def _same_outside(a, b, ranges, cancel=None):
    """Файлы одного размера совпадают байт в байт везде, кроме ranges."""
    if os.path.getsize(a) != os.path.getsize(b):
        raise Skip("размер видео изменился бы — файл не трогаю")
    step = 4 << 20
    ranges = sorted(ranges)
    with open(a, "rb") as fa, open(b, "rb") as fb:
        pos = 0
        while True:
            _check(cancel)
            x, y = fa.read(step), fb.read(step)
            if not x:
                break
            if x != y:
                i = 0                                           # сравниваем куски между изменёнными местами
                for s, e in ranges + [(pos + len(x), pos + len(x))]:
                    s0, e0 = min(max(s - pos, 0), len(x)), min(max(e - pos, 0), len(x))
                    if s0 > i and x[i:s0] != y[i:s0]:
                        raise Skip("видео изменилось бы — файл не трогаю")
                    i = max(i, e0)
            pos += len(x)


def _streams(path):
    info = compcore.probe(path)
    keys = ("codec_type", "codec_name", "width", "height", "pix_fmt", "sample_rate", "channels", "duration_ts",
            "nb_frames", "r_frame_rate")
    out = []
    for s in info.get("streams", []):
        row = {k: s.get(k) for k in keys}
        row["side"] = [{k: v for k, v in d.items()} for d in s.get("side_data_list", [])]
        out.append(row)
    return out


# ---------------------------------------------------------------- файл целиком

def _load(path):
    if os.path.getsize(path) > MAX_PHOTO:
        raise Skip("слишком большой файл")
    with open(path, "rb") as f:
        return f.read()


def _parse(kind, path, data=None, groups=frozenset()):
    if kind == "jpeg":
        return _jpeg(data if data is not None else _load(path), groups)
    if kind == "png":
        return _png(data if data is not None else _load(path), groups)
    raise ValueError(kind)


def read(path, st=None):
    """Что лежит в файле: Item с полями; не прочиталось — item.skip с причиной."""
    st = st or os.stat(path)
    item = Item(path, st.st_size, st.st_mtime)
    try:
        if item.kind == "video":
            item.fields = _mp4_file(path)[0]
        else:
            item.fields = _parse(item.kind, path)[0]
    except Skip as e:
        item.skip = str(e)
    except OSError as e:
        item.skip = e.strerror or str(e)
    except Exception as e:                           # чужой файл не должен ронять всю проверку
        item.skip = f"{type(e).__name__}: {e}"
    return item


def _work_name(path):
    h = hashlib.blake2b(os.path.normcase(os.path.abspath(path)).encode("utf-8"), digest_size=6).hexdigest()
    return os.path.join(WORK, f"{h}_{os.path.basename(path)}")


def clean_work():
    shutil.rmtree(WORK, ignore_errors=True)


def _drop(path):
    try:
        os.remove(path)
    except OSError:
        pass


def clean_one(item, groups, cancel=None, need_writable=True):
    """Очищенная копия файла в рабочей папке. Успех — item.out; нет — item.skip с причиной.

    После очистки копия читается заново: полей выбранных групп нет, все остальные — те же, картинка
    (у видео — всё, кроме служебных блоков) та же байт в байт.
    """
    os.makedirs(WORK, exist_ok=True)
    dst = _work_name(item.path)
    groups = frozenset(groups)
    item.out, item.skip = "", ""
    try:
        st = os.stat(item.path)
        if st.st_size != item.size or st.st_mtime != item.mtime:
            raise Skip("файл изменился")
        if need_writable and st.st_file_attributes & 0x1:
            raise Skip("файл только для чтения")
        if item.is_video:
            if not compcore.tool("ffprobe"):
                raise Skip("нет программы ffprobe")
            before, ranges = _mp4_file(item.path, groups, dst)
            if not ranges:
                raise Skip("убирать нечего")
            after = _mp4_file(dst)[0]
            _same_outside(item.path, dst, ranges, cancel)
            if _streams(item.path) != _streams(dst):
                raise Skip("видео изменилось бы — файл не трогаю")
        else:
            data = _load(item.path)
            before, new = _parse(item.kind, item.path, data, groups)
            if new is None:
                raise Skip("убирать нечего")
            after = _parse(item.kind, dst, new)[0]
            (_same_jpeg if item.kind == "jpeg" else _same_png)(data, new)
            with open(dst, "wb") as f:
                f.write(new)
        expect = [f for f in before if f.group not in groups or f.locked]
        if Counter(after) != Counter(expect):
            raise Skip("после очистки поля не сошлись — файл не трогаю")
        item.fields = before
        item.out, item.new_size = dst, os.path.getsize(dst)
    except Cancelled:
        _drop(dst)
        raise
    except Skip as e:
        _drop(dst)
        item.skip = str(e)
    except OSError as e:
        _drop(dst)
        item.skip = e.strerror or str(e)
    except Exception as e:
        _drop(dst)
        item.skip = f"{type(e).__name__}: {e}"
    return item


# ---------------------------------------------------------------- папка целиком

@dataclass
class ScanResult:
    items: list = field(default_factory=list)
    files_seen: int = 0
    errors: list = field(default_factory=list)
    cloud_skipped: int = 0
    unsupported: int = 0
    cancelled: bool = False


def _inside(path, folder):
    if not folder:
        return False
    try:
        return os.path.commonpath([os.path.normcase(os.path.abspath(path)),
                                   os.path.normcase(os.path.abspath(folder))]) == \
            os.path.normcase(os.path.abspath(folder))
    except ValueError:
        return False


def scan(root, progress=None, cancel=None, load="normal", on_item=None, exclude=None):
    """Найти фото и видео и прочитать, что в них лежит. root — папка или список перетащенного.

    progress(прочитано, всего); on_item(item) — сразу, как файл прочитан. exclude — папка, которую
    пропустить (туда кладутся очищенные копии).
    """
    progress = progress or (lambda *a: None)
    gentle, workers, _ = compcore.LOAD[load]
    if gentle:
        dupcore.background_mode()
    res = ScanResult()
    try:
        cloud = []
        if isinstance(root, (list, tuple)):
            files, res.unsupported = compcore.gather(root, EXTS, cancel, res.errors, cloud,
                                                     on_file=lambda n: progress(0, n))
        else:
            files = dupcore.collect(root, cancel, res.errors, take=lambda e: e in EXTS, cloud=cloud,
                                    on_file=lambda n: progress(0, n))
        res.cloud_skipped = len(cloud)
        files = [m for m in files if m.size > 0 and not _inside(m.path, exclude)]
        files.sort(key=lambda m: m.path.lower())
        res.files_seen = len(files)
        lock = threading.Lock()
        state = {"n": 0}
        progress(0, len(files))

        def one(m):
            _check(cancel)
            item = read(m.path)
            with lock:
                res.items.append(item)
                state["n"] += 1
                progress(state["n"], len(files))
            if on_item:
                on_item(item)

        if workers > 1:
            init = dupcore.background_mode if gentle else None
            with ThreadPoolExecutor(workers, initializer=init) as ex:
                futures = [ex.submit(one, m) for m in files]
                try:
                    for f in futures:
                        f.result()
                except Cancelled:
                    for f in futures:
                        f.cancel()
                    raise
        else:
            for m in files:
                one(m)
    except Cancelled:
        res.cancelled = True
    res.items.sort(key=lambda it: it.path.lower())
    return res


def clean(items, groups, progress=None, cancel=None, load="normal", need_writable=True):
    """Очищенные копии для items. progress(сделано, всего, имя). Остановка — Cancelled."""
    progress = progress or (lambda *a: None)
    gentle, workers, _ = compcore.LOAD[load]
    if gentle:
        dupcore.background_mode()
    clean_work()
    lock = threading.Lock()
    state = {"n": 0}
    progress(0, len(items), "")

    def one(item):
        _check(cancel)
        clean_one(item, groups, cancel, need_writable)
        with lock:
            state["n"] += 1
            progress(state["n"], len(items), os.path.basename(item.path))

    photos = [i for i in items if not i.is_video]
    videos = [i for i in items if i.is_video]
    if workers > 1 and len(photos) > 1:
        init = dupcore.background_mode if gentle else None
        with ThreadPoolExecutor(workers, initializer=init) as ex:
            futures = [ex.submit(one, i) for i in photos]
            try:
                for f in futures:
                    f.result()
            except Cancelled:
                for f in futures:
                    f.cancel()
                raise
    else:
        for i in photos:
            one(i)
    for i in videos:
        one(i)
    return items


def default_copies_folder(base):
    """Куда класть очищенные копии, если не выбрано: рядом с папкой, «<имя> — без метаданных»."""
    base = os.path.abspath(base)
    parent, name = os.path.split(base.rstrip("\\/"))
    if not name:                                            # корень диска
        return os.path.join(base, tr("Без метаданных"))
    return os.path.join(parent, tr("{name} — без метаданных", name=name))


def _free_name(folder, name):
    stem, ext = os.path.splitext(name)
    path, n = os.path.join(folder, name), 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{stem} ({n}){ext}")
        n += 1
    return path


def save_copies(items, folder, base, keep_dates, progress=None):
    """Положить очищенные копии в folder, повторяя путь от base. Оригиналы не трогаются.

    Имя занято — «имя (2).jpg». keep_dates — дата изменения как у оригинала (если время не убирали).
    Возвращает (сделанные, проблемы [(путь, причина)]).
    """
    done, problems = [], []
    for k, it in enumerate(items):
        if progress:
            progress(k)
        rel = ""
        if base:
            try:
                rel = os.path.relpath(os.path.dirname(os.path.abspath(it.path)), base)
            except ValueError:
                rel = ""
            if rel == "." or rel.startswith(".."):
                rel = ""
        target_dir = os.path.join(folder, rel)
        tmp = ""
        try:
            if not it.out or not os.path.exists(it.out) or os.path.getsize(it.out) != it.new_size:
                raise OSError(0, tr("готовая копия пропала — подготовь заново"))
            os.makedirs(target_dir, exist_ok=True)
            target = _free_name(target_dir, os.path.basename(it.path))
            tmp = target + ".duplio-part"
            shutil.copyfile(it.out, tmp)
            if compcore._blake(tmp) != compcore._blake(it.out):
                raise OSError(0, tr("копия легла с ошибкой"))
            os.replace(tmp, target)
            if keep_dates:
                st = os.stat(it.path)
                os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns))
        except OSError as e:
            if tmp:
                _drop(tmp)
            problems.append((it.path, e.strerror or str(e)))
            continue
        _drop(it.out)
        it.saved_to = target
        done.append(it)
    if progress:
        progress(len(items))
    return done, problems
