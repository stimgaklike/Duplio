"""Сжатие: строго без потерь (пиксели совпадают), без видимых потерь (SSIM), видео, замена оригинала.

Нужны программы из third_party: python tools/fetch_tools.py (в GitHub Actions это делает сборка).
"""

import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np  # noqa: E402
from PIL import Image, ImageCms, ImageDraw, PngImagePlugin  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import compcore as C  # noqa: E402

APP = QApplication.instance() or QApplication([])

XMP = (b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
       b'<rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/" dc:title="Duplio"/></rdf:RDF></x:xmpmeta>')
ICC = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def setUpModule():
    missing = [n for n in ("jpegtran", "oxipng", "ffmpeg", "ffprobe") if not C.tool(n)]
    if missing:
        raise RuntimeError(f"нет программ {missing}: запусти python tools/fetch_tools.py")


def photo(w=1600, h=1200, noise=2.0, seed=1):
    """Своё «фото»: плавные градиенты, фигуры и немного шума, как у снимка с телефона."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.stack([x / w * 200 + 30, y / h * 180 + 40, (x + y) / (w + h) * 160 + 50], -1)
    im = Image.fromarray(np.clip(img + rng.normal(0, noise, img.shape), 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im)
    d.ellipse((w * 0.2, h * 0.2, w * 0.5, h * 0.6), fill=(230, 190, 150))
    d.rectangle((w * 0.6, h * 0.3, w * 0.9, h * 0.8), fill=(40, 70, 120))
    d.text((w * 0.1, h * 0.85), "Duplio 2026", fill=(255, 255, 255))
    return im


def exif_bytes():
    e = Image.Exif()
    e[0x010F] = "TestCam"
    e[0x0112] = 6                        # повёрнут — пиксели при сжатии не поворачиваются
    e[0x9003] = "2024:05:01 10:00:00"
    return e.tobytes()


IPTC = b"\xff\xed\x00\x1cPhotoshop 3.0\x008BIM\x04\x04\x00\x00\x00\x00\x00\x00"   # APP13, как пишет Photoshop


def save_jpeg(im, path, quality=95):
    im.save(path, "JPEG", quality=quality, exif=exif_bytes(), icc_profile=ICC, xmp=XMP, comment=b"from camera")
    with open(path, "rb") as f:
        data = f.read()
    with open(path, "wb") as f:                                        # вставить IPTC сразу после SOI
        f.write(data[:2] + IPTC + data[2:])
    return path


def meta_of(path):
    with open(path, "rb") as f:
        segs, _ = C.jpeg_segments(f.read())
    return [s for m, s in segs if m in C.META and m != 0xE0]          # APP0 (JFIF) — от кодировщика


def make_video(path, seconds=3, codec="libopenh264", extra=()):
    subprocess.run([C.tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi",
                    "-i", f"testsrc2=size=640x360:rate=30:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                    "-c:v", codec, *extra, "-c:a", "aac", "-shortest",
                    "-metadata", "creation_time=2024-05-01T10:00:00Z", path],
                   check=True, creationflags=C.CREATE_NO_WINDOW)
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="cmp_")
        self.work = tempfile.mkdtemp(prefix="cmp_work_")
        self._work, C.WORK = C.WORK, self.work

    def tearDown(self):
        C.WORK = self._work
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.work, ignore_errors=True)

    def p(self, name):
        return os.path.join(self.root, name)

    def job(self, path):
        st = os.stat(path)
        return C.Job(path, st.st_size, st.st_mtime)


class SamePixels(Base):
    def test_one_changed_pixel_is_found(self):
        a = np.full((50, 60, 3), 120, np.uint8)
        Image.fromarray(a).save(self.p("a.png"))
        a[49, 59, 2] = 121
        Image.fromarray(a).save(self.p("b.png"))
        self.assertTrue(C.same_pixels(self.p("a.png"), self.p("a.png")))
        self.assertFalse(C.same_pixels(self.p("a.png"), self.p("b.png")))

    def test_color_under_transparent_pixel_counts(self):
        a = np.zeros((20, 20, 4), np.uint8)
        a[..., :3] = 77
        Image.fromarray(a, "RGBA").save(self.p("a.png"))
        a[5, 5, 0] = 78                                       # точка невидима, но данные изменились
        Image.fromarray(a, "RGBA").save(self.p("b.png"))
        self.assertFalse(C.same_pixels(self.p("a.png"), self.p("b.png")))

    def test_16_bit_difference_is_not_rounded_away(self):
        a = np.full((20, 20), 30000, np.uint16)
        Image.fromarray(a, "I;16").save(self.p("a.png"))
        a[3, 3] = 30001                                       # в 8 битах это то же значение
        Image.fromarray(a, "I;16").save(self.p("b.png"))
        self.assertFalse(C.same_pixels(self.p("a.png"), self.p("b.png")))

    def test_broken_file_is_never_the_same(self):
        with open(self.p("bad.jpg"), "wb") as f:
            f.write(b"not an image")
        self.assertFalse(C.same_pixels(self.p("bad.jpg"), self.p("bad.jpg")))


class Lossless(Base):
    def test_jpeg_smaller_same_pixels_all_metadata_kept(self):
        src = save_jpeg(photo(noise=6), self.p("IMG_1.jpg"))
        before = meta_of(src)
        job = C.prepare_one(self.job(src), "lossless")
        self.assertEqual(job.skip, "")
        self.assertLess(job.new_size, job.size)
        self.assertEqual(job.check, "pixels")
        self.assertTrue(C.same_pixels(src, job.out))
        self.assertEqual(meta_of(job.out), before)            # EXIF, ICC, XMP, IPTC, комментарий — байт в байт

    def test_png_smaller_same_pixels_text_and_profile_kept(self):
        a = np.zeros((400, 500, 4), np.uint8)
        a[..., 0], a[..., 1], a[..., 3] = 200, np.arange(500) % 256, 255
        a[50:150, 50:250, 3] = 0
        a[50:150, 50:250, :3] = np.random.default_rng(3).integers(0, 255, (100, 200, 3))
        info = PngImagePlugin.PngInfo()
        info.add_text("Author", "Duplio test")
        Image.fromarray(a, "RGBA").save(self.p("shot.png"), pnginfo=info, icc_profile=ICC, compress_level=1)
        job = C.prepare_one(self.job(self.p("shot.png")), "lossless")
        self.assertEqual(job.skip, "")
        self.assertLess(job.new_size, job.size)
        self.assertTrue(C.same_pixels(self.p("shot.png"), job.out))
        with Image.open(job.out) as im:
            self.assertEqual(im.text.get("Author"), "Duplio test")
            self.assertEqual(im.info.get("icc_profile"), ICC)

    def test_already_optimized_file_is_skipped(self):
        src = save_jpeg(photo(), self.p("a.jpg"))
        first = C.prepare_one(self.job(src), "lossless")
        shutil.copyfile(first.out, self.p("b.jpg"))
        again = C.prepare_one(self.job(self.p("b.jpg")), "lossless")
        self.assertEqual(again.skip, "почти не уменьшился")
        self.assertEqual(again.out, "")
        self.assertEqual(os.listdir(self.work), [first.out and os.path.basename(first.out)])

    def test_pixels_check_guards_the_result(self):
        # Если бы перепаковка испортила хоть один пиксель, файл не должен попасть в замену.
        src = save_jpeg(photo(), self.p("a.jpg"))
        real = C.same_pixels
        C.same_pixels = lambda a, b: False
        try:
            job = C.prepare_one(self.job(src), "lossless")
        finally:
            C.same_pixels = real
        self.assertEqual(job.out, "")
        self.assertIn("пиксели не совпали", job.skip)
        self.assertEqual(os.listdir(self.work), [])

    def test_changed_file_and_read_only_file_are_skipped(self):
        src = save_jpeg(photo(), self.p("a.jpg"))
        job = self.job(src)
        os.utime(src, (time.time(), time.time() + 5))
        self.assertEqual(C.prepare_one(job, "lossless").skip, "файл изменился")
        os.chmod(src, 0o444)
        try:
            self.assertEqual(C.prepare_one(self.job(src), "lossless").skip, "файл только для чтения")
        finally:
            os.chmod(src, 0o666)


class VisualPhoto(Base):
    def test_phone_photo_gets_much_smaller_metadata_kept(self):
        src = save_jpeg(photo(noise=0), self.p("IMG_2.jpg"), quality=97)
        before = meta_of(src)
        job = C.prepare_one(self.job(src), "visual")
        self.assertEqual(job.skip, "")
        self.assertEqual(job.check, "ssim")
        self.assertGreaterEqual(job.score, C.PHOTO_SSIM_MEAN)
        self.assertLess(job.new_size, job.size * 0.7)
        self.assertEqual(meta_of(job.out), before)
        with Image.open(job.out) as im:
            self.assertEqual(im.getexif().get(0x0112), 6)

    def test_camera_grain_is_accepted(self):
        # Зерно, как у снимка с телефона: JPEG 85 его слегка сглаживает. На полном размере SSIM считает это
        # потерей (≈ 0,90), при обычном просмотре разницы нет — такой файл сжимается.
        src = save_jpeg(photo(noise=6), self.p("grain.jpg"), quality=98)
        job = C.prepare_one(self.job(src), "visual")
        self.assertEqual((job.skip, job.how), ("", "JPEG, качество 85"))
        a, b = C._luma(src), C._luma(job.out)
        self.assertLess(C.ssim(a, b)[0], 0.95)                 # на полном размере — «потеря»
        self.assertGreaterEqual(job.score, C.PHOTO_SSIM_MEAN)  # а вдвое — нет

    def refused_with(self, **limits):
        src = save_jpeg(photo(noise=6), self.p("grain.jpg"), quality=98)
        old = {k: getattr(C, k) for k in limits}
        for k, v in limits.items():
            setattr(C, k, v)
        try:
            job = C.prepare_one(self.job(src), "visual")
        finally:
            for k, v in old.items():
                setattr(C, k, v)
        self.assertEqual((job.skip, job.out), ("без видимых потерь не сжимается", ""))
        self.assertEqual(os.listdir(self.work), [])

    def test_below_threshold_is_refused(self):
        self.refused_with(PHOTO_SSIM_MEAN=0.99999)             # недостижимо: порог вообще соблюдается

    def test_worst_blocks_threshold_is_refused(self):
        self.refused_with(PHOTO_SSIM_LOW=0.99999)

    def test_full_size_floor_is_refused(self):
        self.refused_with(PHOTO_SSIM_FLOOR=0.95)               # у зерна на полном размере худший 1 % ≈ 0,8

    def test_low_quality_original_is_left_alone(self):
        src = save_jpeg(photo(), self.p("small.jpg"), quality=80)
        self.assertEqual(C.prepare_one(self.job(src), "visual").skip,
                         "уже сжат сильно — дальше будут видны потери")

    def test_quality_estimate(self):
        for q in (40, 60, 75, 85, 92):
            photo(400, 300).save(self.p(f"q{q}.jpg"), quality=q)
            with Image.open(self.p(f"q{q}.jpg")) as im:
                self.assertLessEqual(abs(C.jpeg_quality(im) - q), 2, q)

    def test_multi_picture_file_is_skipped(self):
        im = photo(400, 300)
        im.save(self.p("mpo.jpg"), "MPO", save_all=True, append_images=[photo(400, 300, seed=2)], quality=97)
        for mode in ("visual", "lossless"):
            self.assertEqual(C.prepare_one(self.job(self.p("mpo.jpg")), mode).skip, C.ATTACHED, mode)

    def test_ssim_sees_a_damaged_block(self):
        a = np.asarray(photo(320, 240).convert("L"), np.float32)
        b = a.copy()
        b[100:140, 100:140] = 128                              # заплатка 40×40 из 320×240 — 2 % кадра
        mean, low = C.ssim(a, b)
        self.assertGreater(mean, 0.9)                         # в среднем почти не видно…
        self.assertLess(low, C.PHOTO_SSIM_LOW)                # …а худшие блоки — видно


class Names(Base):
    """Имена вне кодировки Windows (ANSI): старые программы на C открывают файлы по ANSI-имени и не находят их.

    На сервере GitHub (cp1252) так не открывалось даже «корзина-тест.jpg»; у владельца (cp1251) кириллица
    работает, но иероглифы и эмодзи — нет.
    """

    NAME = "照片 фото 😀"

    def test_every_tool_opens_unicode_names(self):
        jpg = save_jpeg(photo(noise=6), self.p(self.NAME + ".jpg"), quality=97)
        Image.fromarray(np.full((200, 300, 3), 90, np.uint8)).save(self.p(self.NAME + ".png"), compress_level=0)
        vid = make_video(self.p(self.NAME + ".mp4"), seconds=1, extra=("-b:v", "6M"))
        for path, mode in ((jpg, "lossless"), (jpg, "visual"), (self.p(self.NAME + ".png"), "lossless"), (vid, "visual")):
            job = C.prepare_one(self.job(path), mode)
            self.assertEqual(job.skip, "", f"{os.path.basename(path)} {mode}")


class Tail(Base):
    """Данные после конца основной картинки: служебная запись Samsung переносится, картинка и видео — нет."""

    SEF = (b"\x00\x00\x01\n\x0e\x00\x00\x00Image_UTC_Data1731797982101\x00\x00\xa1\n\x08\x00\x00\x00MCC_Data250"
           b"SEFH\x6b\x00\x00\x00\x03\x00\x00\x00" + bytes(20) + b"SEFT")

    def with_tail(self, name, tail, **kw):
        src = save_jpeg(photo(noise=6), self.p(name), **kw)
        with open(src, "ab") as f:
            f.write(tail)
        return src

    def test_samsung_record_is_carried_over_in_both_modes(self):
        for mode, q in (("lossless", 95), ("visual", 97)):
            src = self.with_tail(f"sef_{mode}.jpg", self.SEF, quality=q)
            job = C.prepare_one(self.job(src), mode)
            self.assertEqual(job.skip, "", mode)
            with open(job.out, "rb") as f:
                out = f.read()
            self.assertTrue(out.endswith(self.SEF), mode)
            self.assertEqual(C.jpeg_tail(out), self.SEF, mode)

    def test_attached_image_or_video_is_left_alone_in_both_modes(self):
        gain_map = io.BytesIO()
        Image.new("L", (100, 60), 128).save(gain_map, "JPEG")
        for name, tail in (("hdr.jpg", gain_map.getvalue() + self.SEF),
                           ("motion.jpg", b"\x00\x00\x00\x18ftypmp42" + os.urandom(2000) + self.SEF)):
            src = self.with_tail(name, tail, quality=97)
            for mode in ("lossless", "visual"):
                job = C.prepare_one(self.job(src), mode)
                self.assertEqual((job.skip, job.out), (C.ATTACHED, ""), f"{name} {mode}")

    def test_tail_is_found_only_after_the_picture(self):
        for kw in ({}, {"progressive": True}, {"restart_marker_blocks": 4}, {"restart_marker_rows": 1, "progressive": True}):
            b = io.BytesIO()
            photo(400, 300).save(b, "JPEG", quality=90, **kw)
            data = b.getvalue()
            self.assertEqual(C.jpeg_tail(data), b"", kw)
            self.assertEqual(C.jpeg_tail(data + bytes(64)), b"", kw)         # нули выравнивания — не хвост
            self.assertEqual(C.jpeg_tail(data + self.SEF), self.SEF, kw)


class Video(Base):
    def test_h264_becomes_av1_sound_and_dates_kept(self):
        src = make_video(self.p("clip.mp4"), extra=("-b:v", "6M"))
        job = C.prepare_one(self.job(src), "visual")
        self.assertEqual(job.skip, "")
        self.assertLess(job.new_size, job.size * 0.5)
        self.assertGreaterEqual(job.score, C.VIDEO_SSIM)
        info = C.probe(job.out)
        kinds = sorted(s["codec_type"] + ":" + s["codec_name"] for s in info["streams"])
        self.assertEqual(kinds, ["audio:aac", "video:av1"])
        self.assertEqual(info["format"]["tags"].get("creation_time"), "2024-05-01T10:00:00.000000Z")
        self.assertAlmostEqual(float(info["format"]["duration"]), float(C.probe(src)["format"]["duration"]),
                               delta=0.1)

    def test_below_threshold_is_refused(self):
        src = make_video(self.p("clip.mp4"), seconds=1, extra=("-b:v", "6M"))
        old = C.VIDEO_SSIM
        C.VIDEO_SSIM = 0.99999                      # недостижимо: проверяем, что порог вообще соблюдается
        try:
            job = C.prepare_one(self.job(src), "visual")
        finally:
            C.VIDEO_SSIM = old
        self.assertEqual((job.skip, job.out), ("без видимых потерь не сжимается", ""))
        self.assertEqual(os.listdir(self.work), [])

    def test_av1_is_left_alone(self):
        src = make_video(self.p("av1.mp4"), seconds=1, codec="libsvtav1")
        self.assertEqual(C.prepare_one(self.job(src), "visual").skip, "уже в AV1")

    def test_cancel_stops_encoder(self):
        src = make_video(self.p("long.mp4"), seconds=20, extra=("-b:v", "6M"))
        cancel = threading.Event()
        threading.Timer(0.5, cancel.set).start()
        t = time.monotonic()
        with self.assertRaises(C.Cancelled):
            C.prepare_one(self.job(src), "visual", cancel, threads=1)
        self.assertLess(time.monotonic() - t, 3)
        self.assertEqual(os.listdir(self.work), [])


class PrepareFolder(Base):
    def test_lossless_mode_does_not_touch_video(self):
        save_jpeg(photo(), self.p("a.jpg"))
        make_video(self.p("v.mp4"), seconds=1)
        res = C.prepare(self.root, {"photo", "video"}, "lossless")
        self.assertEqual([os.path.basename(j.path) for j in res.jobs], ["a.jpg"])

    def test_photos_first_then_videos_biggest_first(self):
        # Имена против правила: по алфавиту маленькое видео шло бы первым, а фото — между видео.
        make_video(self.p("a_small.mp4"), seconds=1)
        make_video(self.p("z_big.mp4"), seconds=2, extra=("-b:v", "4M"))
        save_jpeg(photo(400, 300), self.p("y.jpg"))
        save_jpeg(photo(400, 300, seed=2), self.p("x.jpg"))
        order = []
        res = C.prepare(self.root, {"photo", "video"}, "visual", on_job=lambda j: order.append(j.path))
        names = [os.path.basename(p) for p in order]
        self.assertEqual(sorted(names[:2]), ["x.jpg", "y.jpg"])     # фото сжимаются в несколько потоков
        self.assertEqual(names[2:], ["z_big.mp4", "a_small.mp4"])
        self.assertFalse(res.cancelled)

    def test_dropped_files_only_those(self):
        a = save_jpeg(photo(400, 300), self.p("a.jpg"))
        save_jpeg(photo(400, 300, seed=2), self.p("b.jpg"))                 # лежит рядом, но не брошен
        Image.fromarray(np.full((80, 90, 3), 90, np.uint8)).save(self.p("c.png"), compress_level=0)
        with open(self.p("notes.txt"), "w") as f:
            f.write("не фото")
        res = C.prepare([a, self.p("c.png"), self.p("notes.txt")], {"photo"}, "lossless")
        self.assertEqual(sorted(os.path.basename(j.path) for j in res.jobs), ["a.jpg", "c.png"])
        self.assertEqual(res.unsupported, 1)

    def test_dropped_folder_and_its_file_counted_once(self):
        sub = os.path.join(self.root, "sub")
        os.makedirs(sub)
        a = save_jpeg(photo(400, 300), os.path.join(sub, "a.jpg"))
        save_jpeg(photo(400, 300, seed=2), os.path.join(sub, "b.jpg"))
        res = C.prepare([sub, a, a.upper()], {"photo"}, "lossless")
        self.assertEqual(sorted(os.path.basename(j.path).lower() for j in res.jobs), ["a.jpg", "b.jpg"])

    def test_stops_when_disk_is_full(self):
        save_jpeg(photo(400, 300), self.p("a.jpg"))
        old = C.RESERVE
        C.RESERVE = 1 << 62
        try:
            res = C.prepare(self.root, {"photo"}, "lossless")
        finally:
            C.RESERVE = old
        self.assertTrue(res.no_space)
        self.assertEqual(res.jobs[0].out, "")


class Replace(Base):
    def setUp(self):
        super().setUp()
        self.bin = tempfile.mkdtemp(prefix="cmp_bin_")

    def tearDown(self):
        shutil.rmtree(self.bin, ignore_errors=True)
        super().tearDown()

    def fake_bin(self, paths):
        """Корзина для теста: файл переезжает в отдельную папку."""
        for p in paths:
            shutil.move(p, os.path.join(self.bin, os.path.basename(p)))
        return paths, []

    def prepared(self, name="IMG_3.jpg"):
        src = save_jpeg(photo(noise=6), self.p(name))
        old = time.time() - 86400 * 300
        os.utime(src, (old, old))
        C.set_times(src, int((old - 86400 * 30) * 1e9), int(old * 1e9), int(old * 1e9))
        job = C.prepare_one(self.job(src), "lossless")
        self.assertEqual(job.skip, "")
        return job

    def test_original_to_bin_compressed_in_place_with_old_dates(self):
        job = self.prepared()
        st0 = os.stat(job.path)
        with open(job.out, "rb") as f:
            new_data = f.read()
        with open(job.path, "rb") as f:
            old_data = f.read()
        done, problems = C.replace([job], recycle=self.fake_bin)
        self.assertEqual((len(done), problems), (1, []))
        with open(job.path, "rb") as f:
            self.assertEqual(f.read(), new_data)
        with open(os.path.join(self.bin, "IMG_3.jpg"), "rb") as f:
            self.assertEqual(f.read(), old_data)              # оригинал целиком в «Корзине»
        st1 = os.stat(job.path)
        self.assertEqual(st1.st_mtime_ns, st0.st_mtime_ns)
        self.assertEqual(st1.st_birthtime_ns, st0.st_birthtime_ns)
        self.assertEqual(os.listdir(self.root), ["IMG_3.jpg"])  # временных файлов не осталось
        self.assertFalse(os.path.exists(job.out))

    def test_original_stays_when_bin_refuses(self):
        job = self.prepared()
        with open(job.path, "rb") as f:
            old_data = f.read()
        done, problems = C.replace([job], recycle=lambda paths: ([], paths))
        self.assertEqual(done, [])
        self.assertIn("оставлен как был", problems[0][1])
        with open(job.path, "rb") as f:
            self.assertEqual(f.read(), old_data)
        self.assertEqual(os.listdir(self.root), ["IMG_3.jpg"])

    def test_file_changed_after_prepare_is_not_replaced(self):
        job = self.prepared()
        with open(job.path, "ab") as f:
            f.write(b"edited")
        done, problems = C.replace([job], recycle=self.fake_bin)
        self.assertEqual((done, problems), ([], [(job.path, "файл изменился после подготовки")]))
        self.assertEqual(os.listdir(self.bin), [])

    def test_real_recycle_bin(self):
        job = self.prepared("корзина-тест.jpg")
        done, problems = C.replace([job])
        self.assertEqual((len(done), problems), (1, []))
        self.assertTrue(C.same_pixels(job.path, job.path))
        self.assertEqual(os.path.getsize(job.path), job.new_size)


if __name__ == "__main__":
    unittest.main()
