"""Конвертация MOV → MP4 без пересжатия: потоки байт в байт, метаданные Apple на своих местах, новое имя.

Ролик «как с iPhone» собирается сам: MOV от ffmpeg, а ключи Apple (геометка, дата, модель) и объектив
у видеодорожки дописываются блоками meta туда же, куда их кладёт iPhone (moov/meta, trak/meta).
Нужны программы из third_party: python tools/fetch_tools.py.
"""

import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dataclasses import replace  # noqa: E402

import compcore as C  # noqa: E402
import convcore as V  # noqa: E402

LOCATION = "+55.7505+037.7167+140.070/"
APPLE = [("com.apple.quicktime.location.ISO6709", LOCATION), ("com.apple.quicktime.make", "Apple"),
         ("com.apple.quicktime.model", "iPhone 13 Pro"),
         ("com.apple.quicktime.creationdate", "2025-11-15T21:22:48+0300")]
LENS = [("com.apple.quicktime.camera.lens_model", "iPhone 13 Pro back camera 5.7mm f/1.5")]


def setUpModule():
    if V.missing_tools():
        raise RuntimeError("нет ffmpeg: запусти python tools/fetch_tools.py")


def box(typ, body):
    return struct.pack(">I4s", 8 + len(body), typ) + body


def mdta(pairs):
    """Блок meta с ключами mdta, как у iPhone: без версии, внутри hdlr, keys, ilst."""
    hdlr = box(b"hdlr", b"\0" * 8 + b"mdta" + b"\0" * 13)
    keys = box(b"keys", struct.pack(">II", 0, len(pairs)) +
               b"".join(struct.pack(">I4s", 8 + len(k.encode()), b"mdta") + k.encode() for k, _ in pairs))
    items = b"".join(box(struct.pack(">I", i + 1), box(b"data", struct.pack(">II", 1, 0) + v.encode()))
                     for i, (_, v) in enumerate(pairs))
    return box(b"meta", hdlr + keys + box(b"ilst", items))


def ff(*args):
    subprocess.run([C.tool("ffmpeg"), "-v", "error", "-y", *args], check=True, creationflags=C.CREATE_NO_WINDOW)


def iphone_mov(path, seconds=2, video=("-c:v", "libopenh264"), audio=("-c:a", "aac"), keys=APPLE, lens=LENS,
               extra=()):
    """MOV «как с iPhone»: H.264 + AAC, время съёмки в заголовках, ключи Apple — в moov/meta и trak/meta."""
    ff("-f", "lavfi", "-i", f"testsrc2=size=320x240:rate=30:duration={seconds}",
       "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", *video, *audio, "-shortest", *extra,
       "-metadata", "creation_time=2025-11-15T18:22:48Z", "-f", "mov", path)
    moov, at, n = V.read_moov(path)
    assert at + n == os.path.getsize(path)
    kids = V._kids(moov)
    parts = []
    for k in kids:
        piece = moov[k[1]:k[3]]
        if k[0] == b"udta":
            continue                                   # свой udta ffmpeg (кодировщик) — у iPhone его нет
        if k[0] == b"trak" and V._handler(moov, k) == b"vide" and lens:
            piece = box(b"trak", piece[8:] + mdta(lens))
        parts.append(piece)
    if keys:
        parts.append(mdta(keys))
    with open(path, "r+b") as f:
        f.seek(at)
        f.write(box(b"moov", b"".join(parts)))
        f.truncate()
    return path


def tags(path):
    return V._tags(C.probe(path))


def video_trak_meta(path):
    moov = V.read_moov(path)[0]
    trak = next(k for k in V._kids(moov) if k[0] == b"trak" and V._handler(moov, k) == b"vide")
    return [bytes(moov[k[1]:k[3]]) for k in V._kids(moov, trak) if k[0] == b"meta"]


def top_meta(path):
    moov = V.read_moov(path)[0]
    return [bytes(moov[k[1]:k[3]]) for k in V._kids(moov) if k[0] == b"meta"]


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="conv_")
        self.work = tempfile.mkdtemp(prefix="conv_work_")
        self._work, V.WORK = V.WORK, self.work

    def tearDown(self):
        V.WORK = self._work
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.work, ignore_errors=True)

    def p(self, name):
        return os.path.join(self.root, name)

    def job(self, path):
        st = os.stat(path)
        return C.Job(path, st.st_size, st.st_mtime)

    def convert(self, path, target=None, **kw):
        return V.convert_one(self.job(path), target, **kw)


class Remux(Base):
    def test_iphone_mov_becomes_mp4_same_streams_and_apple_metadata(self):
        src = iphone_mov(self.p("IMG_0001.MOV"))
        job = self.convert(src)
        self.assertEqual(job.skip, "")
        self.assertEqual((job.how, job.check, job.note), ("без пересжатия", "streams", ""))
        self.assertEqual(os.path.basename(job.target), "IMG_0001.MP4")          # регистр — как у оригинала
        with open(job.out, "rb") as f:
            head = f.read(12)
        self.assertEqual(head[4:12], b"ftypisom")                               # настоящий MP4, не MOV
        self.assertEqual(V.stream_hashes(src), V.stream_hashes(job.out))         # байт в байт
        self.assertEqual(tags(job.out), tags(src))
        self.assertEqual(tags(job.out)["com.apple.quicktime.location.ISO6709"], LOCATION)
        self.assertEqual(tags(job.out)["creation_time"], "2025-11-15T18:22:48.000000Z")
        # там же, где у iPhone, и теми же байтами: в moov/udta/meta Проводник геометку не видит
        self.assertEqual(top_meta(job.out), top_meta(src))
        self.assertEqual(video_trak_meta(job.out), [mdta(LENS)])
        self.assertTrue(os.path.exists(src))                                    # оригинал не тронут

    def test_lowercase_name_unicode_and_rotation(self):
        plain = iphone_mov(self.p("tmp.mov"))
        src = self.p("видео 😀.mov")
        ff("-display_rotation:v:0", "90", "-i", plain, "-map", "0", "-c", "copy", "-map_metadata", "0",
           "-movflags", "+use_metadata_tags", "-f", "mov", src)
        job = self.convert(src)
        self.assertEqual(job.skip, "")
        self.assertEqual(os.path.basename(job.target), "видео 😀.mp4")
        side = V._side(C._video_stream(C.probe(job.out)), "Display Matrix")
        self.assertEqual(abs(side["rotation"]), 90)

    def test_name_taken_on_disk_or_by_another_file_gets_number(self):
        a = iphone_mov(self.p("clip.mov"))
        b = shutil.copyfile(a, self.p("clip.qt"))
        open(self.p("clip.mp4"), "wb").close()
        res = V.prepare(self.root)
        names = sorted(os.path.basename(j.target) for j in res.jobs)
        self.assertEqual(names, ["clip (2).mp4", "clip (3).mp4"])
        self.assertTrue(all(j.out and os.path.exists(j.out) for j in res.jobs))
        self.assertEqual({j.path for j in res.jobs}, {a, b})

    def test_timecode_is_kept(self):
        src = iphone_mov(self.p("tc.mov"), extra=("-timecode", "01:02:03:04"))
        job = self.convert(src)
        self.assertEqual((job.skip, job.note), ("", ""))
        new = C.probe(job.out)["streams"]
        self.assertEqual([s["codec_tag_string"] for s in new], ["avc1", "mp4a", "tmcd"])
        self.assertEqual(new[0]["tags"]["timecode"], "01:02:03:04")

    def test_service_tracks_are_named_in_note(self):
        src = iphone_mov(self.p("faces.mov"))
        probe = C.probe

        def with_mebx(path):                    # дорожку mebx (лица в кадре у iPhone) ffmpeg не пишет —
            info = probe(path)                  # у оригинала она «появляется» в описании потоков
            if path == src:
                info["streams"].append({"index": 9, "codec_type": "data", "codec_tag_string": "mebx"})
            return info
        C.probe = with_mebx
        try:
            job = self.convert(src)
        finally:
            C.probe = probe
        self.assertEqual(job.skip, "")
        self.assertEqual(job.note, "служебных дорожек не перенесено: 1 (в MP4 их не положить)")

    def test_live_photo_video_is_left_alone(self):
        src = iphone_mov(self.p("IMG_0002.MOV"), keys=APPLE + [(V.LIVE_KEY, "8D5F0A3B-1C2D-4E5F-9A8B-7C6D5E4F3A2B")])
        job = self.convert(src)
        self.assertIn("живого фото", job.skip)
        self.assertEqual(job.out, "")
        self.assertEqual(os.listdir(self.work), [])

    def test_video_mp4_cannot_take_as_is_asks_for_a_codec(self):
        mj = self.convert(iphone_mov(self.p("mj.mov"), video=("-c:v", "mjpeg")))
        self.assertEqual(mj.skip, "видео в формате mjpeg — без пересжатия в MP4 не переложить: выбери кодек")
        self.assertEqual(os.listdir(self.work), [])

    def test_sound_mp4_cannot_take_becomes_aac_video_stays_byte_for_byte(self):
        src = iphone_mov(self.p("pcm.mov"), audio=("-c:a", "pcm_s16le"))     # так пишут фотоаппараты
        job = self.convert(src)
        self.assertEqual(job.skip, "")
        self.assertEqual((job.how, job.detail, job.check), ("звук → AAC", "видео без пересжатия, звук → AAC", ""))
        info = C.probe(job.out)
        self.assertEqual([s["codec_name"] for s in info["streams"]], ["h264", "aac"])
        self.assertEqual(V.stream_hashes(src, [0]), V.stream_hashes(job.out, [0]))
        self.assertEqual(tags(job.out), tags(src))

    def test_already_in_that_form_is_left_alone(self):
        src = self.p("clip.mp4")
        ff("-i", iphone_mov(self.p("a.mov")), "-map", "0", "-c", "copy", src)
        self.assertEqual(self.convert(src).skip, "уже MP4 в нужном виде")


class Checks(Base):
    """Проверка после перекладки ловит каждую порчу сама — поддельный «результат» подсовывается ей напрямую."""

    def setUp(self):
        super().setUp()
        self.src = iphone_mov(self.p("IMG_0003.MOV"))
        self.info = C.probe(self.src)
        self.keep = [s for s in self.info["streams"] if s["codec_type"] in ("video", "audio")]
        self.dur = float(self.info["format"]["duration"])

    def check(self, dst):
        t = V.Target()
        V._check(C.Job(self.src, 0, 0), self.info, V.plan(self.info, ".mov", t), t, dst, None, False)

    def remux(self, *args, carry=True):
        dst = self.p("out.mp4")
        ff("-i", self.src, "-map", "0:v", "-map", "0:a", *args, "-map_metadata", "0", "-f", "mp4", dst)
        if carry:
            V.carry_meta(self.src, dst)
        return dst

    def test_good_remux_passes(self):
        self.check(self.remux("-c", "copy"))

    def test_lost_metadata_is_caught(self):
        with self.assertRaisesRegex(C.Skip, "не перенеслись метаданные: com.apple"):
            self.check(self.remux("-c", "copy", carry=False))

    def test_extra_metadata_is_caught(self):
        dst = self.remux("-c", "copy", "-metadata", "comment=added", "-movflags", "+use_metadata_tags", carry=False)
        with self.assertRaisesRegex(C.Skip, "не перенеслись метаданные"):
            self.check(dst)

    def test_reencoded_sound_is_caught(self):
        with self.assertRaisesRegex(C.Skip, "не совпали с оригиналом байт в байт"):
            self.check(self.remux("-c:v", "copy", "-c:a", "aac", "-b:a", "96k"))

    def test_rotation_change_is_caught(self):
        dst = self.p("rot.mp4")
        ff("-display_rotation:v:0", "180", "-i", self.src, "-map", "0:v", "-map", "0:a", "-c", "copy",
           "-map_metadata", "0", "-f", "mp4", dst)
        V.carry_meta(self.src, dst)
        with self.assertRaisesRegex(C.Skip, "повернулся бы иначе"):
            self.check(dst)

    def test_shifted_frames_are_caught(self):
        dst = self.p("shift.mp4")
        ff("-i", self.src, "-map", "0:v", "-map", "0:a", "-c", "copy", "-bsf:v", r"setts=pts=PTS+eq(N\,10)*1000",
           "-map_metadata", "0", "-f", "mp4", dst)
        V.carry_meta(self.src, dst)
        with self.assertRaisesRegex(C.Skip, "сдвинулись по времени"):
            self.check(dst)

    def test_timecode_change_is_caught(self):
        dst = self.remux("-c", "copy", "-timecode", "01:00:00:00")
        with self.assertRaisesRegex(C.Skip, "тайм-код"):
            self.check(dst)

    def test_moov_not_at_end_is_refused(self):
        dst = self.p("fast.mp4")
        ff("-i", self.src, "-map", "0:v", "-map", "0:a", "-c", "copy", "-movflags", "+faststart", "-f", "mp4", dst)
        with self.assertRaisesRegex(C.Skip, "не в конце файла"):
            V.carry_meta(self.src, dst)


class Replace(Base):
    def setUp(self):
        super().setUp()
        self.bin = tempfile.mkdtemp(prefix="conv_bin_")

    def tearDown(self):
        shutil.rmtree(self.bin, ignore_errors=True)
        super().tearDown()

    def fake_bin(self, paths):
        for p in paths:
            shutil.move(p, os.path.join(self.bin, os.path.basename(p)))
        return paths, []

    def prepared(self):
        src = iphone_mov(self.p("IMG_0004.MOV"))
        old = time.time() - 86400 * 300
        os.utime(src, (old, old))
        C.set_times(src, int((old - 86400 * 30) * 1e9), int(old * 1e9), int(old * 1e9))
        job = self.convert(src)
        self.assertEqual(job.skip, "")
        return job

    def test_original_to_bin_new_name_old_dates(self):
        job = self.prepared()
        st0 = os.stat(job.path)
        with open(job.out, "rb") as f:
            new_data = f.read()
        done, problems = C.replace([job], recycle=self.fake_bin)
        self.assertEqual((len(done), problems), (1, []))
        self.assertEqual(os.listdir(self.root), ["IMG_0004.MP4"])            # оригинала и временных нет
        self.assertEqual(os.listdir(self.bin), ["IMG_0004.MOV"])
        with open(job.target, "rb") as f:
            self.assertEqual(f.read(), new_data)
        st1 = os.stat(job.target)
        self.assertEqual(st1.st_mtime_ns, st0.st_mtime_ns)
        self.assertEqual(st1.st_birthtime_ns, st0.st_birthtime_ns)

    def test_name_taken_after_prepare_is_named_before_asking(self):
        job = self.prepared()
        open(job.target, "wb").close()
        ok, problems = C.check_before_replace([job])          # по нему окно пишет «Пропущу: …» до вопроса
        self.assertEqual((ok, problems), ([], [(job.path, "файл IMG_0004.MP4 уже есть рядом — подготовь заново")]))

    def test_name_taken_after_prepare_is_not_replaced(self):
        job = self.prepared()
        with open(job.target, "wb") as f:
            f.write(b"someone else's file")
        done, problems = C.replace([job], recycle=self.fake_bin)
        self.assertEqual(done, [])
        self.assertEqual(problems, [(job.path, "файл IMG_0004.MP4 уже есть рядом — подготовь заново")])
        self.assertEqual(os.listdir(self.bin), [])
        with open(job.target, "rb") as f:
            self.assertEqual(f.read(), b"someone else's file")


def old_avi(path, seconds=2, size="640x480", extra=()):
    """Старое видео: MPEG-4 Part 2 и звук PCM в AVI, 25 кадров/с — MP4 их «как есть» не берёт (MPEG-4 берёт,
    но так снимали камеры лет 15 назад; для теста важно, что пересжатие нужно)."""
    ff("-f", "lavfi", "-i", f"testsrc2=size={size}:rate=25:duration={seconds}", "-f", "lavfi",
       "-i", f"sine=frequency=440:duration={seconds}", "-c:v", "mpeg4", "-q:v", "3", "-c:a", "pcm_s16le",
       *extra, path)
    return path


CPU = dict(device="cpu")            # в GitHub Actions видеокарты нет — тесты лестницы идут на процессоре


class Reencode(Base):
    def test_old_avi_everywhere_h264_aac_checked_by_vmaf(self):
        job = self.convert(old_avi(self.p("old.avi")), V.Target("mp4", "h264", audio="aac", **CPU))
        self.assertEqual(job.skip, "")
        self.assertEqual(os.path.basename(job.target), "old.mp4")
        self.assertEqual(job.check, "vmaf")
        self.assertGreaterEqual(job.score, C.VIDEO_VMAF_MEAN)
        info = C.probe(job.out)
        self.assertEqual([s["codec_name"] for s in info["streams"]], ["h264", "aac"])
        self.assertRegex(job.how, r"^H\.264 · \d,\d Мбит/с$")
        self.assertRegex(job.detail, r"^H\.264, процессор, \d,\d Мбит/с, звук → AAC$")

    def test_each_cpu_codec_and_container(self):
        src = old_avi(self.p("old.avi"), seconds=1, size="320x240")
        for t, codecs, ext in ((V.Target("mp4", "av1", **CPU), ["av1", "aac"], "mp4"),
                               (V.Target("mkv", "hevc", **CPU), ["hevc", "pcm_s16le"], "mkv"),
                               (V.Target("webm", "vp9", **CPU), ["vp9", "opus"], "webm")):
            job = self.convert(src, t)
            self.assertEqual(job.skip, "", t)
            self.assertEqual(([s["codec_name"] for s in C.probe(job.out)["streams"]], job.target[-len(ext):]),
                             (codecs, ext))

    def test_same_codec_is_copied_not_reencoded(self):
        src = iphone_mov(self.p("IMG_0005.MOV"))                    # уже H.264
        job = self.convert(src, V.Target("mp4", "h264", audio="aac", **CPU))
        self.assertEqual((job.how, job.check), ("без пересжатия", "streams"))
        self.assertEqual(V.stream_hashes(src), V.stream_hashes(job.out))

    def test_smaller_frame_and_fewer_frames(self):
        src = self.p("big.mp4")
        ff("-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=60:duration=2", "-c:v", "libopenh264", "-b:v", "8M", src)
        job = self.convert(src, V.Target("mkv", "av1", size=480, fps=30, **CPU))
        self.assertEqual(job.skip, "")
        v = C._video_stream(C.probe(job.out))
        self.assertEqual((int(v["width"]), int(v["height"])), (854, 480))
        self.assertEqual(len(C.frame_times(job.out)), 60)                     # 2 с по 30 кадров
        self.assertGreaterEqual(job.score, C.VIDEO_VMAF_MEAN)                  # сравнение — с уменьшенным оригиналом

    def test_portrait_frame_is_shrunk_by_its_short_side(self):
        src = self.p("tall.mp4")
        ff("-f", "lavfi", "-i", "testsrc2=size=720x1280:rate=30:duration=1", "-c:v", "libopenh264", "-b:v", "6M", src)
        job = self.convert(src, V.Target("mp4", "av1", "small", size=480, **CPU))
        v = C._video_stream(C.probe(job.out))
        self.assertEqual((int(v["width"]), int(v["height"])), (480, 854))

    def test_interlaced_camera_video_is_deinterlaced(self):
        src = self.p("00001.MTS")
        ff("-f", "lavfi", "-i", "testsrc2=size=1440x1080:rate=25:duration=1", "-c:v", "mpeg2video", "-b:v", "15M",
           "-flags", "+ilme+ildct", "-top", "1", "-f", "mpegts", src)
        self.assertEqual(C._video_stream(C.probe(src))["field_order"], "tt")
        job = self.convert(src, V.Target("mp4", "av1", "medium", **CPU))
        self.assertEqual(job.skip, "")
        self.assertEqual(C._video_stream(C.probe(job.out)).get("field_order", "progressive"), "progressive")

    def test_hdr_to_h264_is_refused_hevc_keeps_hdr_colors(self):
        src = self.p("hlg.mkv")
        ff("-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=1", "-c:v", "ffv1", "-pix_fmt", "yuv420p10le",
           "-vf", "setparams=color_trc=arib-std-b67:color_primaries=bt2020:colorspace=bt2020nc", src)
        self.assertEqual(C._video_stream(C.probe(src))["color_transfer"], "arib-std-b67")
        self.assertEqual(self.convert(src, V.Target("mp4", "h264", **CPU)).skip,
                         "HDR-видео в H.264 не перевести без потери цветов — выбери HEVC или AV1")
        job = self.convert(src, V.Target("mkv", "av1", **CPU))
        self.assertEqual(job.skip, "")
        v = C._video_stream(C.probe(job.out))
        self.assertEqual((v["color_transfer"], v["pix_fmt"]), ("arib-std-b67", "yuv420p10le"))

    def test_video_already_reencoded_by_a_program_is_flagged(self):
        src = old_avi(self.p("old.avi"), seconds=1, size="320x240")
        first = self.convert(src, V.Target("mp4", "av1", "small", **CPU))      # ffmpeg пишет подпись Lavc
        os.replace(first.out, self.p("once.mp4"))
        again = self.convert(self.p("once.mp4"), V.Target("mp4", "h264", "high", **CPU))
        self.assertTrue(again.warn)
        notes = again.note.split("; ")                           # AV1 → H.264 высокого качества — и больше
        self.assertEqual(len(notes), 2, notes)
        self.assertEqual(notes[0], "уже пересжимался программой (libsvtav1) — каждое пересжатие чуть ухудшает качество")
        self.assertRegex(notes[1], r"^файл стал больше оригинала на \d+%$")
        cam = self.p("camera.mp4")                                               # подпись как у видеокамеры
        ff("-i", src, "-c:v", "libopenh264", "-b:v", "4M", "-metadata:s:v:0", "encoder=AVC Coding", cam)
        self.assertFalse(self.convert(cam, V.Target("mp4", "av1", "small", **CPU)).warn)
        copied = self.convert(self.p("once.mp4"), V.Target("mkv", "copy"))       # без пересжатия — не потеря
        self.assertEqual((copied.skip, copied.warn), ("", False))

    def test_cpu_hevc_refuses_frames_not_divisible_by_8(self):
        # kvazaar на таком кадре молча не выдаёт ни одного (у владельца — ролик WhatsApp 478×850)
        src = self.p("wa.mp4")
        ff("-f", "lavfi", "-i", "testsrc2=size=478x850:rate=30:duration=1", "-c:v", "libopenh264", "-b:v", "3M", src)
        self.assertEqual(self.convert(src, V.Target("mkv", "hevc", **CPU)).skip,
                         "HEVC на процессоре не кодирует кадр 478×850 (стороны должны делиться на 8) — выбери другой "
                         "кодек или видеокарту")
        ok = self.convert(src, V.Target("mkv", "hevc", "small", size=360, **CPU))      # уменьшенный — 360×640
        self.assertEqual(ok.skip, "")
        v = C._video_stream(C.probe(ok.out))
        self.assertEqual((int(v["width"]), int(v["height"])), (360, 640))
        self.assertEqual(V._out_size({"width": 1920, "height": 1080}, V.Target(size=720)), (1280, 720))

    def test_less_space_never_makes_a_file_bigger(self):
        # телефон 720p уже сжат экономно — AV1 «без видимых потерь» вышел бы в 1,5 раза больше (прогон 17.10.2026)
        src = self.p("low.mp4")
        ff("-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=2", "-c:v", "libopenh264", "-b:v", "120k", src)
        job = self.convert(src, V.PRESETS["small"][2])
        self.assertRegex(job.skip, r"^AV1 не уменьшает этот файл \(\d+% оригинала\) — оставлен как есть$")
        self.assertEqual(os.listdir(self.work), [])
        big = old_avi(self.p("old.avi"), seconds=1, size="320x240")             # а несжатое — уменьшает
        self.assertEqual(self.convert(big, V.PRESETS["small"][2]).skip, "")

    def test_everywhere_shrinks_big_frames_to_1080p_and_says_so(self):
        src = self.p("big.mp4")
        ff("-f", "lavfi", "-i", "testsrc2=size=2560x1440:rate=30:duration=1", "-c:v", "libopenh264", "-b:v", "20M", src)
        job = self.convert(src, replace(V.PRESETS["everywhere"][2], device="cpu"))
        self.assertEqual(job.skip, "")
        v = C._video_stream(C.probe(job.out))
        self.assertEqual((int(v["width"]), int(v["height"])), (1920, 1080))
        self.assertTrue(job.warn and job.resized)
        self.assertIn("кадр уменьшен: 2560×1440 → 1920×1080", job.note)
        small = self.convert(old_avi(self.p("old.avi"), seconds=1), replace(V.PRESETS["everywhere"][2], device="cpu"))
        self.assertEqual((small.skip, small.resized), ("", False))               # 640×480 не трогается

    def test_for_apple_keeps_h264_and_hevc_as_they_are(self):
        apple = replace(V.PRESETS["apple"][2], device="cpu")
        mov = iphone_mov(self.p("IMG_0008.MOV"))                                 # H.264 в MOV
        self.assertEqual(self.convert(mov, apple).skip, "уже MOV в нужном виде")
        mp4 = self.p("clip.mp4")
        ff("-i", mov, "-map", "0", "-c", "copy", mp4)
        job = self.convert(mp4, apple)
        self.assertEqual((job.skip, job.how, job.target[-4:]), ("", "без пересжатия", ".mov"))
        avi = self.convert(old_avi(self.p("old.avi"), seconds=1), apple)          # MPEG-4 Part 2 — в HEVC
        self.assertEqual((avi.skip, C._video_stream(C.probe(avi.out))["codec_name"]), ("", "hevc"))

    def test_service_tracks_alone_are_no_reason_to_rewrite(self):
        src = iphone_mov(self.p("faces2.mov"))
        probe = C.probe

        def with_mebx(path):
            info = probe(path)
            if path == src:
                info["streams"].append({"index": 9, "codec_type": "data", "codec_tag_string": "mebx"})
            return info
        C.probe = with_mebx
        try:
            job = self.convert(src, replace(V.PRESETS["apple"][2], device="cpu"))
        finally:
            C.probe = probe
        self.assertEqual(job.skip, "уже MOV в нужном виде")

    def test_manual_quality_skips_the_ladder(self):
        src = old_avi(self.p("old.avi"), seconds=1, size="320x240")
        small = self.convert(src, V.Target("mp4", "av1", "small", **CPU))
        high = self.convert(src, V.Target("mp4", "av1", "high", **CPU))
        self.assertEqual((small.check, small.how, small.detail),
                         ("", "AV1 · Маленький файл", "AV1, процессор, Маленький файл, звук → AAC"))
        self.assertLess(small.new_size, high.new_size)

    @unittest.skipUnless(V.gpu_ok("hevc_nvenc"), "нет видеокарты NVIDIA")
    def test_video_card_is_used_when_there(self):
        job = self.convert(old_avi(self.p("old.avi")), V.Target("mov", "hevc", audio="aac"))
        self.assertEqual(job.skip, "")
        self.assertRegex(job.how, r"^HEVC · CQ \d+$")
        self.assertIn("HEVC (H.265), видеокарта, CQ ", job.detail)
        v = C._video_stream(C.probe(job.out))
        self.assertEqual((v["codec_tag_string"], job.target[-4:]), ("hvc1", ".mov"))

    def test_without_video_card_falls_back_to_cpu(self):
        saved = dict(V._gpu)
        V._gpu.update({"h264_nvenc": False})
        try:
            self.assertEqual(V.encoder_for("h264", "gpu")[0], "libopenh264")
            self.assertEqual(V.encoder_for("vp9", "gpu")[0], "libvpx-vp9")          # у VP9 видеокарты нет
        finally:
            V._gpu.clear()
            V._gpu.update(saved)

    @unittest.skipUnless(C.hwdec(), "нет видеокарты NVIDIA")
    def test_video_card_decoding_does_not_change_the_score(self):
        src = old_avi(self.p("old.avi"), seconds=1)
        dst = self.p("enc.mp4")
        ff("-i", src, "-map", "0:v", "-c:v", "libsvtav1", "-crf", "40", dst)
        with_card = C.video_vmaf(src, dst, by_order=True)
        saved, C._hwdec[:] = list(C._hwdec), [[]]
        try:
            on_cpu = C.video_vmaf(src, dst, by_order=True)
        finally:
            C._hwdec[:] = saved
        # MPEG-4 Part 2 (AVI) распаковка не обязана совпадать бит в бит — 0,006 VMAF; у H.264/HEVC совпадает до знака
        self.assertAlmostEqual(with_card[0], on_cpu[0], delta=0.05)

    def test_vmaf_by_frame_order_with_different_time_bases(self):
        # AVI считает время в 1/25 с, MP4 — в своих долях: пары по номеру кадра, а не по числу из файла
        src = old_avi(self.p("old.avi"), seconds=1)
        dst = self.p("same.mp4")
        ff("-i", src, "-map", "0:v", "-c:v", "libsvtav1", "-crf", "10", dst)
        mean, low = C.video_vmaf(src, dst, by_order=True)
        self.assertGreater(low, 90)


class Settings(Base):
    def test_presets_are_valid_targets(self):
        for key, (_name, _text, t) in V.PRESETS.items():
            if t is not None:
                self.assertEqual(V.Target.from_dict(t.as_dict()), t, key)

    def test_choice_is_fitted_to_the_container(self):
        t = V.Target.from_dict({"container": "webm", "video": "h264", "audio": "aac", "size": 1080, "fps": 7})
        self.assertEqual((t.video, t.audio, t.size, t.fps), ("vp9", "opus", 1080, 0))
        t = V.Target.from_dict({"container": "mp3", "audio": "none"})
        self.assertEqual((t.audio_only, t.audio), (True, "mp3"))
        self.assertEqual(V.Target.from_dict({"container": "avi", "device": "tpu"}), V.Target())
        # «Меньше места» — на процессоре: AV1 там на треть меньше при том же VMAF (калибровка 17.10.2026)
        self.assertEqual(V.PRESETS["small"][2].device, "cpu")


class AudioOnly(Base):
    def test_sound_from_video_beside_the_original(self):
        src = iphone_mov(self.p("IMG_0006.MOV"))
        job = self.convert(src, V.Target("mp3", audio="mp3"), beside=True)
        self.assertEqual(job.skip, "")
        info = C.probe(job.out)
        self.assertEqual([s["codec_type"] + ":" + s["codec_name"] for s in info["streams"]], ["audio:mp3"])
        self.assertEqual(os.path.basename(job.target), "IMG_0006.MP3")
        self.assertAlmostEqual(float(info["format"]["duration"]), 2.0, delta=0.15)
        to_bin = []                                   # Корзину звать нельзя: оригинал остаётся
        done, problems = C.replace([job], keep=True, recycle=lambda paths: (to_bin.append(paths), (paths, []))[1])
        self.assertEqual((len(done), problems, to_bin), (1, [], []))
        self.assertEqual(sorted(os.listdir(self.root)), ["IMG_0006.MOV", "IMG_0006.MP3"])   # видео на месте

    def test_same_extension_beside_gets_a_number(self):
        src = old_avi(self.p("clip.avi"), seconds=1, size="320x240")
        mp4 = self.convert(src, V.Target("mp4", "av1", "small", **CPU))
        os.replace(mp4.out, self.p("clip.mp4"))
        again = self.convert(self.p("clip.mp4"), V.Target("mp4", "h264", "medium", **CPU), beside=True)
        self.assertEqual(os.path.basename(again.target), "clip (2).mp4")

    def test_replace_beside_never_takes_the_original_place(self):
        job = self.convert(iphone_mov(self.p("IMG_0007.MOV")))
        job.target = ""
        done, problems = C.replace([job], keep=True)
        self.assertEqual((done, problems), ([], [(job.path, "новый файл встал бы на место оригинала")]))


if __name__ == "__main__":
    unittest.main()
