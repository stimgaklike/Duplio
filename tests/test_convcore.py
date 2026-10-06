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

    def convert(self, path):
        return V.convert_one(self.job(path))


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
        self.assertEqual(job.note, "служебных дорожек не перенесено: 1 (MP4 их не хранит)")

    def test_live_photo_video_is_left_alone(self):
        src = iphone_mov(self.p("IMG_0002.MOV"), keys=APPLE + [(V.LIVE_KEY, "8D5F0A3B-1C2D-4E5F-9A8B-7C6D5E4F3A2B")])
        job = self.convert(src)
        self.assertIn("живого фото", job.skip)
        self.assertEqual(job.out, "")
        self.assertEqual(os.listdir(self.work), [])

    def test_codecs_mp4_cannot_take_as_is_are_left_for_now(self):
        mj = self.convert(iphone_mov(self.p("mj.mov"), video=("-c:v", "mjpeg")))
        self.assertEqual(mj.skip, "видео в формате mjpeg — без пересжатия в MP4 не переложить")
        pcm = self.convert(iphone_mov(self.p("pcm.mov"), audio=("-c:a", "pcm_s16le")))
        self.assertEqual(pcm.skip, "звук в формате pcm_s16le — без пересжатия в MP4 не переложить")
        self.assertEqual(os.listdir(self.work), [])


class Checks(Base):
    """Проверка после перекладки ловит каждую порчу сама — поддельный «результат» подсовывается ей напрямую."""

    def setUp(self):
        super().setUp()
        self.src = iphone_mov(self.p("IMG_0003.MOV"))
        self.info = C.probe(self.src)
        self.keep = [s for s in self.info["streams"] if s["codec_type"] in ("video", "audio")]
        self.dur = float(self.info["format"]["duration"])

    def check(self, dst):
        V._check_remux(self.src, self.info, self.keep, dst, self.dur, None, False)

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
            V._check_remux(self.src, self.info, self.keep, dst, self.dur, None, False)

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


if __name__ == "__main__":
    unittest.main()
