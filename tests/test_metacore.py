"""Метаданные: что находится, что убирается, что остаётся байт в байт.

Проверяем чужими глазами: Pillow (EXIF, превью, MPO), ffprobe (видео), сверка пикселей compcore.same_pixels.
Нужны программы из third_party: python tools/fetch_tools.py.
"""

import io
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from PIL import ExifTags, Image, ImageCms, PngImagePlugin  # noqa: E402
from PIL.TiffImagePlugin import IFDRational as R  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import compcore as C  # noqa: E402
import metacore as M  # noqa: E402

APP = QApplication.instance() or QApplication([])
ALL = tuple(M.GROUPS)
ICC = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
XMP = ('<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>'
       '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
       '<rdf:Description rdf:about="" xmlns:exif="http://ns.adobe.com/exif/1.0/" '
       'xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/" '
       'exif:GPSLatitude="55,45.07N" exif:GPSLongitude="37,37.10E" xmp:CreateDate="2024-11-16T22:59:42" '
       'xmp:CreatorTool="Gallery" xmp:Rating="5" photoshop:City="Moscow"/>'
       '</rdf:RDF></x:xmpmeta>' + " " * 400 + '<?xpacket end="w"?>').encode("utf-8")
HDR_XMP = ('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
           '<rdf:Description rdf:about="" xmlns:hdrgm="http://ns.adobe.com/hdr-gain-map/1.0/" '
           'xmlns:xmp="http://ns.adobe.com/xap/1.0/" hdrgm:Version="1.0" xmp:CreateDate="2024-11-16T22:59:42"/>'
           '</rdf:RDF></x:xmpmeta>').encode("utf-8")
IPTC = (b"\x1c\x02\x00\x00\x02\x00\x04" + b"\x1c\x02\x5a\x00\x06Moscow" + b"\x1c\x02\x50\x00\x04Ivan" +
        b"\x1c\x02\x19\x00\x03sea")


def setUpModule():
    missing = [n for n in ("ffmpeg", "ffprobe") if not C.tool(n)]
    if missing:
        raise RuntimeError(f"нет программ {missing}: запусти python tools/fetch_tools.py")


def picture(w=640, h=480, color=(90, 120, 200)):
    im = Image.new("RGB", (w, h), color)
    for x in range(0, w, 16):
        im.paste((x % 255, 200, 40), (x, 0, x + 8, h // 2))
    return im


def phone_exif():
    e = Image.Exif()
    e[0x010F], e[0x0110], e[0x0112] = "samsung", "SM-S928B", 6
    e[0x0131], e[0x0132], e[0x013B] = "S928BXXU1AXA1", "2024:11:16 22:59:42", "Ivan"
    ex = e.get_ifd(ExifTags.IFD.Exif)
    ex[0x9003], ex[0x829A], ex[0x829D], ex[0x8827] = "2024:11:16 22:59:42", R(1, 120), R(17, 10), 50
    ex[0x927C] = b"TESTMN\0\0" + bytes(4) + b"SERIAL123\0\0\0" + bytes(40)    # смещение внутрь себя — допишем ниже
    ex[0xA431], ex[0xA001] = "R5CX1234567", 1
    gps = e.get_ifd(ExifTags.IFD.GPSInfo)
    gps[0], gps[1], gps[3] = b"\2\2\0\0", "N", "E"
    gps[2], gps[4] = (R(55, 1), R(45, 1), R(432, 100)), (R(37, 1), R(37, 1), R(624, 100))
    return e


def with_thumb_and_makernote(tiff):
    """Дописать к EXIF от Pillow превью (IFD1) и смещение внутри MakerNote — как у камер."""
    t = bytearray(tiff)
    e = "<" if t[:2] == b"II" else ">"
    mn = t.index(b"TESTMN\0\0")
    struct.pack_into(e + "I", t, mn + 8, mn + 12)                # указывает на «SERIAL123» от начала TIFF
    ifd0 = struct.unpack_from(e + "I", t, 4)[0]
    n = struct.unpack_from(e + "H", t, ifd0)[0]
    next_at = ifd0 + 2 + 12 * n
    thumb = io.BytesIO()
    picture(160, 120).save(thumb, "JPEG", quality=70)
    thumb = thumb.getvalue()
    if len(t) % 2:
        t.append(0)
    ifd1 = len(t)
    struct.pack_into(e + "I", t, next_at, ifd1)
    t += struct.pack(e + "H", 2)
    t += struct.pack(e + "HHII", 0x0201, 4, 1, ifd1 + 2 + 24 + 4)
    t += struct.pack(e + "HHII", 0x0202, 4, 1, len(thumb))
    t += bytes(4) + thumb
    return bytes(t)


def segment(marker, body):
    return bytes((0xFF, marker)) + struct.pack(">H", len(body) + 2) + body


def insert_before_tables(data, segs):
    """Вставить блоки перед первой таблицей (DQT) — туда, где их пишут камеры."""
    i = data.index(b"\xff\xdb")
    return data[:i] + b"".join(segs) + data[i:]


def phone_jpeg(path, im=None):
    """Снимок как с телефона: EXIF (GPS, камера, время, автор, MakerNote, превью), XMP, IPTC, ICC, комментарий."""
    b = io.BytesIO()
    (im or picture()).save(b, "JPEG", quality=90, icc_profile=ICC)
    tiff = with_thumb_and_makernote(phone_exif().tobytes()[6:])
    data = insert_before_tables(b.getvalue(), [segment(0xE1, b"Exif\0\0" + tiff),
                                               segment(0xE1, M.XMP_SIG + XMP),
                                               segment(0xED, M.PS_SIG + ps_block(IPTC)),
                                               segment(0xFE, b"Shot on Galaxy")])
    with open(path, "wb") as f:
        f.write(data)
    return path


def ps_block(iptc):
    pad = b"\0" if len(iptc) % 2 else b""
    return b"8BIM\x04\x04\0\0" + struct.pack(">I", len(iptc)) + iptc + pad


def tiff_of(path):
    """TIFF из первого блока EXIF файла."""
    with open(path, "rb") as f:
        data = f.read()
    i = data.index(b"Exif\0\0")
    n = struct.unpack_from(">H", data, i - 2)[0]
    return data[i + 6:i - 2 + n]


def opened(path):
    """Картинка целиком в памяти: файл сразу закрыт (на Windows открытый файл не даёт убрать папку теста)."""
    with open(path, "rb") as f:
        return Image.open(io.BytesIO(f.read()))


def names(path):
    return {(f.group, f.name) for f in M.read(path).fields}


def sef(*entries):
    """Запись Samsung: блоки (тип, имя, данные), за ними каталог SEFH и подпись SEFT."""
    blocks, pos = b"", []
    for typ, name, data in entries:
        pos.append((typ, len(blocks)))
        blocks += struct.pack("<HHI", 0, typ, len(name)) + name + data
    head = b"SEFH" + struct.pack("<II", 107, len(entries))
    for (typ, p), (_t, name, data) in zip(pos, entries):
        head += struct.pack("<HHII", 0, typ, len(blocks) - p, 8 + len(name) + len(data))
    return blocks + head + struct.pack("<I", len(head)) + b"SEFT"


SEF = sef((0x0A01, b"Image_UTC_Data", b"1731797982101"), (0x0AA1, b"MCC_Data", b"250"),
          (0x0BA1, b"Original_Path_Hash_Key", b"6b2f0e6f"))


def make_video(path, *extra, rotate=None):
    ff = C.tool("ffmpeg")
    tmp = path + ".src.mp4"
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=15:duration=2",
                    "-f", "lavfi", "-i", "sine=duration=2", "-c:v", "libopenh264", "-c:a", "aac", tmp],
                   check=True, creationflags=C.CREATE_NO_WINDOW)
    rot = ["-display_rotation", str(rotate)] if rotate is not None else []
    subprocess.run([ff, "-v", "error", "-y", *rot, "-i", tmp, "-c", "copy",
                    "-metadata", "location=+55.7512+037.6184/", "-metadata", "creation_time=2024-05-01T10:00:00Z",
                    "-metadata", "com.android.version=14", "-metadata", "com.android.capture.fps=30", *extra, path],
                   check=True, creationflags=C.CREATE_NO_WINDOW)
    os.remove(tmp)
    return path


def motion_jpeg(path):
    """«Живое фото»: снимок, за ним видео (с геометкой) и запись Samsung. Само видео остаётся рядом: path + ".mp4"."""
    video = make_video(path + ".mp4", "-movflags", "use_metadata_tags")
    with open(video, "rb") as f:
        mp4 = f.read()
    b = io.BytesIO()
    picture().save(b, "JPEG", exif=phone_exif())
    with open(path, "wb") as f:
        f.write(b.getvalue() + mp4 + SEF)
    return path


def box(typ, payload):
    return struct.pack(">I", 8 + len(payload)) + typ + payload


def add_udta(path, *boxes):
    """Дописать блоки в конец udta. У ролика от ffmpeg moov — последний в файле, udta — последний в moov,
    так что потоки не сдвигаются; размеры udta и moov увеличиваются на столько же."""
    with open(path, "rb") as f:
        data = bytearray(f.read())
    moov = data.rindex(b"moov") - 4
    udta = data.rindex(b"udta") - 4
    assert moov + struct.unpack_from(">I", data, moov)[0] == len(data)
    assert udta + struct.unpack_from(">I", data, udta)[0] == len(data)
    extra = b"".join(boxes)
    for at in (moov, udta):
        struct.pack_into(">I", data, at, struct.unpack_from(">I", data, at)[0] + len(extra))
    with open(path, "wb") as f:
        f.write(bytes(data) + extra)
    return path


def samsung_video(path):
    """Ролик, устроенный как у Galaxy S24 Ultra: auth (3GPP), smta с превью-JPEG, cami, SDLN."""
    thumb = io.BytesIO()
    picture(320, 180).save(thumb, "JPEG", quality=80)
    smta = bytes(4) + box(b"saut", bytes(4)) + box(b"sthm", bytes(4) + box(b"stjp", thumb.getvalue()))
    return add_udta(make_video(path), box(b"auth", bytes(4) + b"\x15\xc7Galaxy S24 Ultra\0"), box(b"smta", smta),
                    box(b"cami", bytes(4) + b"3, 2, 3592, -1197, 1.0"), box(b"SDLN", b"SEQ_PLAY"))


def probe_tags(path):
    info = C.probe(path)
    tags = dict(info.get("format", {}).get("tags", {}))
    for s in info.get("streams", []):
        tags.update({f"s:{k}": v for k, v in s.get("tags", {}).items()})
    return tags


def rotation(path):
    for s in C.probe(path).get("streams", []):
        for d in s.get("side_data_list", []):
            if "rotation" in d:
                return d["rotation"]
    return None


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="meta_")
        self.work = tempfile.mkdtemp(prefix="meta_work_")
        self._work, M.WORK = M.WORK, self.work

    def tearDown(self):
        M.WORK = self._work
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.work, ignore_errors=True)

    def p(self, name):
        return os.path.join(self.root, name)

    def cleaned(self, path, groups):
        item = M.clean_one(M.read(path), groups)
        self.assertEqual(item.skip, "", path)
        return item.out


class Jpeg(Base):
    def test_phone_photo_shows_every_group(self):
        it = M.read(phone_jpeg(self.p("IMG_1.jpg")))
        self.assertEqual(it.skip, "")
        self.assertEqual(it.groups(), set(M.GROUPS))
        f = {(x.group, x.name): x.value for x in it.fields}
        self.assertEqual(f[("place", "Геометка")], "55.75120, 37.61840")
        self.assertEqual(f[("camera", "Модель камеры")], "SM-S928B")
        self.assertEqual(f[("camera", "Параметры съёмки")], "f/1.7 · 1/120 · ISO 50")
        self.assertEqual(f[("place", "IPTC Город")], "Moscow")
        self.assertEqual(f[("author", "Комментарий")], "Shot on Galaxy")
        self.assertIn(("thumb", "Превью в EXIF"), f)

    def test_place_only_everywhere_rest_untouched_in_place(self):
        src = phone_jpeg(self.p("IMG_2.jpg"))
        out = self.cleaned(src, ["place"])
        before, after = names(src), names(out)
        self.assertEqual(after, {n for n in before if n[0] != "place"})
        self.assertFalse(any(g == "place" for g, _n in after))
        ex = opened(out).getexif()
        self.assertEqual(dict(ex.get_ifd(ExifTags.IFD.GPSInfo)), {})       # Pillow тоже геометки не видит
        self.assertEqual((ex[0x010F], ex[0x0112]), ("samsung", 6))
        with open(out, "rb") as f:
            data = f.read()
        self.assertNotIn(b"GPSLatitude", data)                              # и в XMP её нет
        self.assertNotIn(b"Moscow", data)                                   # и в IPTC
        # EXIF правился на месте: запись производителя не сдвинулась, её смещение указывает куда надо
        old, new = tiff_of(src), tiff_of(out)
        self.assertEqual(len(old), len(new))
        mn = new.index(b"TESTMN\0\0")
        self.assertEqual(mn, old.index(b"TESTMN\0\0"))
        ptr = struct.unpack_from("<I" if new[:2] == b"II" else ">I", new, mn + 8)[0]
        self.assertEqual(new[ptr:ptr + 9], b"SERIAL123")
        thumb = ex.get_ifd(ExifTags.IFD.IFD1)                               # превью на месте и открывается
        a, n = thumb[0x0201], thumb[0x0202]
        self.assertEqual(Image.open(io.BytesIO(new[a:a + n])).size, (160, 120))
        self.assertTrue(C.same_pixels(src, out))
        # Без превью EXIF можно было бы собрать заново — но запись производителя держит его на месте.
        out = self.cleaned(src, ["place", "thumb"])
        new = tiff_of(out)
        mn = new.index(b"TESTMN\0\0")
        ptr = struct.unpack_from("<I" if new[:2] == b"II" else ">I", new, mn + 8)[0]
        self.assertEqual(new[ptr:ptr + 9], b"SERIAL123")
        self.assertEqual(dict(opened(out).getexif().get_ifd(ExifTags.IFD.IFD1)), {})

    def test_everything_leaves_only_rotation_and_color(self):
        src = phone_jpeg(self.p("IMG_3.jpg"))
        out = self.cleaned(src, ALL)
        self.assertEqual(M.read(out).fields, [])
        im = opened(out)
        ex = im.getexif()
        self.assertEqual(ex[0x0112], 6)                                     # поворот
        self.assertEqual(ex.get_ifd(ExifTags.IFD.Exif)[0xA001], 1)          # цветовое пространство
        self.assertEqual(im.info.get("icc_profile"), ICC)                   # цветовой профиль байт в байт
        self.assertNotIn(0x010F, ex)
        self.assertEqual(dict(ex.get_ifd(ExifTags.IFD.IFD1)), {})
        with open(out, "rb") as f:
            data = f.read()
        for gone in (b"samsung", b"TESTMN", b"Ivan", b"2024:11:16", b"xmpmeta", b"Photoshop", b"Galaxy"):
            self.assertNotIn(gone, data, gone)
        self.assertLess(os.path.getsize(out), os.path.getsize(src) - 3000)
        self.assertTrue(C.same_pixels(src, out))

    def test_each_group_alone_takes_only_itself(self):
        src = phone_jpeg(self.p("IMG_4.jpg"))
        before = M.read(src).fields
        for g in M.GROUPS:
            out = self.cleaned(src, [g])
            self.assertEqual(sorted(M.read(out).fields, key=repr),
                             sorted([f for f in before if f.group != g], key=repr), g)
            self.assertTrue(C.same_pixels(src, out), g)

    def test_end_of_picture_found_in_every_layout(self):
        for kw in ({}, {"progressive": True}, {"restart_marker_blocks": 4},
                   {"restart_marker_rows": 1, "progressive": True}):
            b = io.BytesIO()
            picture().save(b, "JPEG", quality=90, **kw)
            data = b.getvalue()
            parts, sos = M._jpeg_parts(data)
            self.assertEqual(M._main_end(data, sos), len(data), kw)
            self.assertEqual(M._main_end(data + SEF, sos), len(data), kw)

    def test_hdr_description_iso_21496_is_not_metadata(self):
        """Ultra HDR пишет описание карты яркости блоком APP2 по ISO 21496 — это не о человеке, его не трогаем."""
        iso = segment(0xE2, b"urn:iso:std:iso:ts:21496:-1\0" + bytes([0, 0, 1, 2, 3, 4]))
        src = self.p("iso.jpg")
        with open(phone_jpeg(self.p("base.jpg")), "rb") as f:
            data = f.read()
        with open(src, "wb") as f:
            f.write(data[:2] + iso + data[2:])                            # сразу за SOI (в EXIF есть свой FFDB)
        self.assertFalse([f for f in M.read(src).fields if "21496" in f.name])
        out = self.cleaned(src, ALL)
        self.assertEqual(M.read(out).fields, [])
        with open(out, "rb") as f:
            self.assertIn(iso, f.read())                                  # блок на месте байт в байт

    def test_nothing_to_remove(self):
        src = self.p("plain.jpg")
        picture().save(src, "JPEG")
        item = M.clean_one(M.read(src), ALL)
        self.assertEqual((item.skip, item.out), ("убирать нечего", ""))


class Attached(Base):
    """Ultra HDR / MPO: карта яркости в хвосте находится по смещению из MPF; запись Samsung в конце."""

    def hdr_photo(self, path, gain_exif=True, tail_extra=b""):
        b = io.BytesIO()
        e = Image.Exif()
        e[0x0112] = 1
        e.get_ifd(ExifTags.IFD.GPSInfo).update({1: "N", 2: (R(55, 1), R(45, 1), R(0, 1))})
        gain = io.BytesIO()
        Image.new("L", (160, 120), 128).save(gain, "JPEG", exif=e if gain_exif else Image.Exif(), quality=80)
        gain = gain.getvalue()
        picture().save(b, "JPEG", quality=90, exif=phone_exif())
        mpf_tiff = (b"II*\0" + struct.pack("<I", 8) + struct.pack("<H", 3) +
                    struct.pack("<HHI4s", 0xB000, 7, 4, b"0100") + struct.pack("<HHII", 0xB001, 4, 1, 2) +
                    struct.pack("<HHII", 0xB002, 7, 32, 8 + 2 + 36 + 4) + bytes(4) + bytes(32))
        data = insert_before_tables(b.getvalue(), [segment(0xE1, M.XMP_SIG + HDR_XMP),
                                                   segment(0xE2, b"MPF\0" + mpf_tiff),
                                                   segment(0xFE, b"comment after MPF")])
        base = data.index(b"MPF\0") + 4
        entries = base + 8 + 2 + 36 + 4
        data = bytearray(data)
        struct.pack_into("<IIII", data, entries, 0x030000, len(data), 0, 0)
        struct.pack_into("<IIII", data, entries + 16, 0, len(gain), len(data) - base, 0)
        with open(path, "wb") as f:
            f.write(bytes(data) + gain + tail_extra)
        return path

    def gain_map(self, path):
        """Вторая картинка там, куда указывает MPF, — по разбору Pillow (Ultra HDR как MPO он не открывает)."""
        im = opened(path)
        entry = im._getmp()[0xB002][1]
        with open(path, "rb") as f:
            data = f.read()
        pos = im.info["mpoffset"] + entry["DataOffset"]
        return Image.open(io.BytesIO(data[pos:pos + entry["Size"]]))

    def assert_gain_map_intact(self, path):
        g = self.gain_map(path)
        g.load()
        self.assertEqual((g.size, g.getpixel((5, 5))), ((160, 120), 128))

    def test_hdr_map_found_after_blocks_change_size(self):
        src = self.hdr_photo(self.p("hdr.jpg"), tail_extra=SEF)
        self.assert_gain_map_intact(src)
        it = M.read(src)
        f = {(x.group, x.name, x.where) for x in it.fields}
        self.assertIn(("place", "Геометка", "приложенная картинка 1"), f)
        self.assertIn(("time", "Samsung Image_UTC_Data", ""), f)
        out = self.cleaned(src, ALL)
        self.assert_gain_map_intact(out)
        self.assertLess(os.path.getsize(out), os.path.getsize(src))       # блоки до карты стали меньше
        with open(out, "rb") as f:
            data = f.read()
        self.assertIn(b"hdrgm:Version", data)                              # описание HDR осталось
        self.assertNotIn(b"CreateDate", data)
        self.assertFalse(data.endswith(b"SEFT"))                           # всё из записи Samsung убрано
        self.assertTrue(C.same_pixels(src, out))
        self.assertEqual(M.read(out).fields, [])

    def test_samsung_record_keeps_the_rest(self):
        src = self.hdr_photo(self.p("sef.jpg"), tail_extra=SEF)
        out = self.cleaned(src, ["time"])
        with open(out, "rb") as f:
            tail = f.read()[-200:]
        self.assertNotIn(b"1731797982101", tail)
        self.assertIn(b"MCC_Data250", tail)
        self.assertIn(b"Original_Path_Hash_Key6b2f0e6f", tail)
        sef_new = M._sef(tail[tail.index(b"\0\0\xa1\x0a"):])               # каталог снова сходится
        self.assertEqual([e[2] for e in sef_new[1]], ["MCC_Data", "Original_Path_Hash_Key"])
        self.assert_gain_map_intact(out)

    def test_attached_picture_cleaned_without_moving(self):
        src = self.hdr_photo(self.p("mpo.jpg"))
        out = self.cleaned(src, ["place"])
        self.assert_gain_map_intact(out)
        self.assertNotEqual(dict(self.gain_map(src).getexif().get_ifd(ExifTags.IFD.GPSInfo)), {})
        self.assertEqual(dict(self.gain_map(out).getexif().get_ifd(ExifTags.IFD.GPSInfo)), {})

    def test_motion_photo_video_cleaned_in_place_record_kept(self):
        src = motion_jpeg(self.p("motion.jpg"))
        video = src + ".mp4"
        with open(video, "rb") as f:
            mp4 = f.read()
        it = M.read(src)
        f = {(x.group, x.name, x.where): x.locked for x in it.fields}
        self.assertEqual(f[("place", "Геометка", "видео «живого фото»")], "")
        self.assertTrue(f[("time", "Samsung Image_UTC_Data", "")])        # запись рядом с видео — не трогаем
        out = self.cleaned(src, ALL)
        with open(out, "rb") as f:
            data = f.read()
        v = data.index(b"ftyp") - 4
        self.assertEqual(len(data) - v, len(mp4) + len(SEF))                # видео и запись — того же размера
        self.assertTrue(data.endswith(SEF))
        cut = self.p("cut.mp4")
        with open(cut, "wb") as f:
            f.write(data[v:v + len(mp4)])
        self.assertNotIn("location", probe_tags(cut))
        self.assertEqual(M._streams(cut), M._streams(video))


class Png(Base):
    def png(self, path):
        info = PngImagePlugin.PngInfo()
        info.add_text("Author", "Ivan")
        info.add_text("Software", "Snipping Tool")
        info.add_itxt("XML:com.adobe.xmp", XMP.decode("utf-8"))
        info.add_text("Comment", "zipped note", zip=True)
        e = Image.Exif()
        e[0x010F] = "PNGCam"
        e[0x0112] = 1
        e.get_ifd(ExifTags.IFD.GPSInfo).update({1: "N", 2: (R(10, 1), R(0, 1), R(0, 1))})
        picture().save(path, "PNG", pnginfo=info, exif=e, icc_profile=ICC)
        with open(path, "rb") as f:
            data = f.read()
        i = data.index(b"IDAT") - 4
        data = data[:i] + M._chunk(b"tIME", struct.pack(">HBBBBB", 2024, 11, 16, 22, 59, 42)) + data[i:]
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_place_only(self):
        src = self.png(self.p("screen.png"))
        self.assertEqual(M.read(src).groups(), {"place", "camera", "time", "author", "other"})
        out = self.cleaned(src, ["place"])
        self.assertEqual(names(out), {n for n in names(src) if n[0] != "place"})
        im = opened(out)
        self.assertEqual(dict(im.getexif().get_ifd(ExifTags.IFD.GPSInfo)), {})
        self.assertEqual(im.getexif()[0x010F], "PNGCam")
        self.assertEqual(im.info["Author"], "Ivan")
        self.assertTrue(C.same_pixels(src, out))

    def test_everything(self):
        src = self.png(self.p("screen2.png"))
        out = self.cleaned(src, ALL)
        self.assertEqual(M.read(out).fields, [])
        im = opened(out)
        self.assertEqual(im.info.get("icc_profile"), ICC)
        for key in ("Author", "Software", "Comment", "XML:com.adobe.xmp"):
            self.assertNotIn(key, im.info)
        with open(out, "rb") as f:
            data = f.read()
        self.assertNotIn(b"tIME", data)
        self.assertTrue(C.same_pixels(src, out))


class Video(Base):
    def test_place_only_size_streams_rotation_same(self):
        src = make_video(self.p("clip.mp4"), "-movflags", "use_metadata_tags", rotate=90)
        self.assertEqual(rotation(src), 90)
        self.assertIn("location", probe_tags(src))
        place = sorted(f.value for f in M.read(src).fields if f.group == "place")
        self.assertEqual(place, ["+55.7512+037.6184/", "55.75119, 37.61839"])     # ключ mdta и блок 3GPP loci
        out = self.cleaned(src, ["place"])
        tags = probe_tags(out)
        self.assertNotIn("location", tags)
        self.assertIn("creation_time", tags)                   # время не выбрано — осталось
        self.assertEqual(tags["com.android.capture.fps"], "30")
        self.assertEqual(os.path.getsize(out), os.path.getsize(src))
        self.assertEqual(rotation(out), 90)
        self.assertEqual(M._streams(out), M._streams(src))
        with open(out, "rb") as f:
            self.assertNotIn(b"+55.7512", f.read())

    def test_everything_keeps_what_playback_needs(self):
        cam = ("-metadata", "make=TestCam", "-metadata", "model=X1")
        for name, extra in (("clip.mov", cam), ("clip.mp4", cam + ("-movflags", "use_metadata_tags"))):
            src = make_video(self.p(name), *extra)
            self.assertEqual(M.read(src).groups(), {"place", "camera", "time", "author"}, name)
            out = self.cleaned(src, ALL)
            self.assertEqual(M.read(out).fields, [], name)
            tags = probe_tags(out)
            for key in ("location", "creation_time", "make", "model", "encoder", "com.android.version"):
                self.assertNotIn(key, tags, name)
            if name.endswith(".mp4"):
                self.assertEqual(tags["com.android.capture.fps"], "30")     # без него замедленное видео — обычное
            self.assertEqual(M._streams(out), M._streams(src), name)
            self.assertEqual(os.path.getsize(out), os.path.getsize(src), name)

    def test_samsung_blocks_named_and_grouped(self):
        src = samsung_video(self.p("20251115_172307.mp4"))
        self.assertEqual(M._streams(src), M._streams(make_video(self.p("plain.mp4"))))   # ролик цел
        f = {(x.group, x.name): x.value for x in M.read(src).fields}
        self.assertEqual(f[("author", "Автор")], "Galaxy S24 Ultra")                 # 3GPP: не «23 Б»
        self.assertEqual(f[("camera", "Параметры камеры Samsung")], "3, 2, 3592, -1197, 1.0")
        self.assertIn(("thumb", "Превью и служебная запись Samsung"), f)
        self.assertIn(("other", "SDLN"), f)
        out = self.cleaned(src, ["thumb"])
        after = {(x.group, x.name) for x in M.read(out).fields}
        self.assertNotIn(("thumb", "Превью и служебная запись Samsung"), after)
        self.assertIn(("author", "Автор"), after)
        with open(out, "rb") as fh:
            data = fh.read()
        self.assertNotIn(b"stjp", data)                                             # превью затёрто
        self.assertEqual(len(data), os.path.getsize(src))
        self.assertEqual(M._streams(out), M._streams(src))

    def test_change_outside_metadata_is_caught(self):
        a = make_video(self.p("a.mp4"))
        b = self.p("b.mp4")
        shutil.copyfile(a, b)
        with open(b, "r+b") as f:
            f.seek(100)
            x = f.read(1)
            f.seek(100)
            f.write(bytes([x[0] ^ 1]))
        M._same_outside(a, b, [(90, 110)])                     # байт внутри изменённого места — так и надо
        with self.assertRaises(C.Skip):
            M._same_outside(a, b, [(90, 100), (101, 200)])     # а рядом с ним — уже порча


class Guard(Base):
    """Проверка после очистки ловит и недоубранное, и лишнее, и изменённую картинку."""

    def test_leftover_field_is_caught(self):
        src = phone_jpeg(self.p("g1.jpg"))
        real = M.Tiff.strip
        try:
            M.Tiff.strip = lambda self, groups, compact: real(self, set(groups) - {"place"}, compact)
            item = M.clean_one(M.read(src), ["place", "author"])
        finally:
            M.Tiff.strip = real
        self.assertEqual((item.skip, item.out), ("после очистки поля не сошлись — файл не трогаю", ""))

    def test_changed_picture_is_caught(self):
        src = phone_jpeg(self.p("g2.jpg"))
        real = M._jpeg

        def broken(data, groups=frozenset(), where="", fixed=False):
            fields, new = real(data, groups, where, fixed)
            if new is not None and not where:
                new = new[:-10] + bytes([new[-10] ^ 1]) + new[-9:]
            return fields, new
        try:
            M._jpeg = broken
            item = M.clean_one(M.read(src), ["place"])
        finally:
            M._jpeg = real
        self.assertEqual((item.skip, item.out), ("картинка изменилась бы — файл не трогаю", ""))

    def test_changed_or_read_only_file(self):
        src = phone_jpeg(self.p("g3.jpg"))
        item = M.read(src)
        with open(src, "ab") as f:
            f.write(b"x")
        self.assertEqual(M.clean_one(item, ALL).skip, "файл изменился")
        item = M.read(src)
        os.chmod(src, 0o444)
        try:
            self.assertEqual(M.clean_one(item, ALL).skip, "файл только для чтения")
            self.assertEqual(M.clean_one(item, ALL, need_writable=False).skip, "")   # копии рядом — можно
        finally:
            os.chmod(src, 0o666)

    def test_unicode_names(self):
        src = phone_jpeg(self.p("照片 фото 😀.jpg"))
        self.assertTrue(self.cleaned(src, ["place"]))
        v = make_video(self.p("видео 😀.mp4"))
        self.assertTrue(self.cleaned(v, ["place"]))


class Folder(Base):
    def test_scan_finds_media_and_skips_copies_folder(self):
        phone_jpeg(self.p("a.jpg"))
        os.makedirs(self.p("sub"))
        phone_jpeg(self.p(r"sub\b.jpg"))
        os.makedirs(self.p("copies"))
        phone_jpeg(self.p(r"copies\c.jpg"))
        with open(self.p("notes.txt"), "w") as f:
            f.write("x")
        res = M.scan(self.root, exclude=self.p("copies"))
        self.assertEqual(sorted(os.path.relpath(i.path, self.root) for i in res.items), ["a.jpg", r"sub\b.jpg"])
        res = M.scan([self.p("a.jpg"), self.p("notes.txt")])
        self.assertEqual((len(res.items), res.unsupported), (1, 1))

    def test_replace_original_to_bin_dates_kept(self):
        src = phone_jpeg(self.p("IMG_9.jpg"))
        old = time.time() - 86400 * 300
        os.utime(src, (old, old))
        st0 = os.stat(src)
        items = M.clean([M.read(src)], ["place"])
        binned = []

        def fake_bin(paths):
            for p in paths:
                dst = os.path.join(self.work, "bin_" + os.path.basename(p))
                shutil.move(p, dst)
                binned.append(dst)
            return paths, []
        done, problems = C.replace(items, recycle=fake_bin)
        self.assertEqual((len(done), problems), (1, []))
        self.assertNotIn(("place", "Геометка"), names(src))
        self.assertEqual(os.stat(src).st_mtime_ns, st0.st_mtime_ns)
        self.assertIn(("place", "Геометка"), names(binned[0]))             # оригинал в «Корзине» целиком
        self.assertEqual(os.listdir(self.root), ["IMG_9.jpg"])

    def test_copies_to_folder_original_untouched(self):
        os.makedirs(self.p("trip"))
        a = phone_jpeg(self.p(r"trip\a.jpg"))
        old = time.time() - 86400 * 100
        os.utime(a, (old, old))
        with open(a, "rb") as f:
            orig = f.read()
        target = self.p("out")
        os.makedirs(os.path.join(target, "trip"))
        with open(os.path.join(target, "trip", "a.jpg"), "wb") as f:
            f.write(b"someone else's file")
        for groups, keep in ((["place"], True), (["time"], False)):
            items = M.clean([M.read(a)], groups, need_writable=False)
            done, problems = M.save_copies(items, target, self.root, keep_dates=keep)
            self.assertEqual((len(done), problems), (1, []))
            with open(a, "rb") as f:
                self.assertEqual(f.read(), orig)                            # оригинал не тронут
            got = done[0].saved_to
            self.assertEqual(os.path.dirname(got), os.path.join(target, "trip"))
            self.assertNotEqual(os.path.basename(got), "a.jpg")             # чужой файл не перезаписан
            self.assertEqual(abs(os.path.getmtime(got) - old) < 2, keep)
        self.assertEqual(sorted(os.listdir(os.path.join(target, "trip"))), ["a (2).jpg", "a (3).jpg", "a.jpg"])
        self.assertEqual(M.default_copies_folder(r"D:\Фото\Поездка"), r"D:\Фото\Поездка — без метаданных")
        self.assertEqual(M.default_copies_folder("E:\\"), "E:\\Без метаданных")


if __name__ == "__main__":
    unittest.main()
