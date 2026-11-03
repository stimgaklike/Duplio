"""Скачивание по ссылке без окна: yt-dlp подменён поддельным (fake_ytdlp.py) — сети не нужно."""

import hashlib
import http.server
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import dlcore  # noqa: E402

FAKE = [sys.executable, os.path.join(os.path.dirname(__file__), "fake_ytdlp.py")]


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="dl_test_")
        self.saved = dlcore.COMMAND, dlcore.WORK, dlcore.TOOLS
        dlcore.COMMAND = FAKE
        dlcore.WORK = os.path.join(self.dir, "work")
        dlcore.TOOLS = os.path.join(self.dir, "tools")
        self.out = os.path.join(self.dir, "Загрузки")

    def tearDown(self):
        dlcore.COMMAND, dlcore.WORK, dlcore.TOOLS = self.saved
        shutil.rmtree(self.dir, ignore_errors=True)

    def get(self, key, **kw):
        it = dlcore.Item("https://example.com/v/" + key, **kw)
        self.steps = []
        dlcore.download(it, self.out, lambda i: self.steps.append((i.state, i.stage, round(i.percent))))
        return it


class Links(unittest.TestCase):
    def test_links_from_pasted_text(self):
        text = ("Глянь https://youtu.be/abc, и ещё https://vk.com/video1_2.\n"
                "https://youtu.be/abc\nне ссылка\n(https://rutube.ru/x)")
        self.assertEqual(dlcore.links(text), ["https://youtu.be/abc", "https://vk.com/video1_2",
                                              "https://rutube.ru/x"])


class Releases(Base):
    SHA = "a" * 64

    def release(self, digest=True, sums=False, exe=True):
        assets = []
        if exe:
            assets.append({"name": "yt-dlp.exe", "browser_download_url": "https://x/yt-dlp.exe", "size": 10,
                           **({"digest": "sha256:" + self.SHA.upper()} if digest else {})})
        if sums:
            assets.append({"name": "SHA2-256SUMS", "browser_download_url": "https://x/SUMS"})
        return {"tag_name": "2026.10.26", "assets": assets}

    def test_checksum_from_github(self):
        r = dlcore.from_release(self.release())
        self.assertEqual((r.version, r.sha256, r.size), ("2026.10.26", self.SHA, 10))

    def test_checksum_from_sums_file(self):
        sums = lambda url: f"{'b' * 64}  yt-dlp\n{'c' * 64}  yt-dlp.exe\n"     # noqa: E731
        self.assertEqual(dlcore.from_release(self.release(digest=False, sums=True), sums).sha256, "c" * 64)

    def test_no_checksum_no_install(self):
        with self.assertRaises(dlcore.Failed):
            dlcore.from_release(self.release(digest=False))
        with self.assertRaises(dlcore.Failed):
            dlcore.from_release(self.release(exe=False))

    def test_update_due(self):
        now = 1_000_000
        self.assertTrue(dlcore.update_due(0, now))
        self.assertFalse(dlcore.update_due(now - dlcore.CHECK_EVERY + 60, now))
        self.assertTrue(dlcore.update_due(now - dlcore.CHECK_EVERY, now))


class Fetch(Base):
    def setUp(self):
        super().setUp()
        self.body = b"MZ not really a program " * 100
        body = self.body

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/yt-dlp.exe"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def test_wrong_checksum_leaves_nothing(self):
        dest = os.path.join(self.dir, "x.exe")
        with self.assertRaises(dlcore.Failed):
            dlcore.fetch(self.url, dest, len(self.body), "0" * 64)
        self.assertEqual(os.listdir(self.dir), [])

    def test_right_checksum(self):
        dest = os.path.join(self.dir, "x.exe")
        dlcore.fetch(self.url, dest, len(self.body), hashlib.sha256(self.body).hexdigest())
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), self.body)

    def test_install_keeps_old_when_new_does_not_run(self):
        os.makedirs(dlcore.TOOLS)
        with open(dlcore.exe(), "wb") as f:
            f.write(b"old")
        rel = dlcore.Release("2099.01.01", self.url, len(self.body), hashlib.sha256(self.body).hexdigest())
        with self.assertRaises(dlcore.Failed):
            dlcore.install(rel)
        with open(dlcore.exe(), "rb") as f:
            self.assertEqual(f.read(), b"old")
        self.assertEqual(os.listdir(dlcore.TOOLS), ["yt-dlp.exe"])


class Probe(Base):
    def test_video(self):
        self.assertEqual(dlcore.probe("https://example.com/v/ok"),
                         [("https://example.com/v/ok", "Клип ok", 0)])

    def test_playlist_entries(self):
        url = "https://example.com/v/playlist"
        self.assertEqual(dlcore.probe(url), [("https://example.com/v/ok", "Первое", 0), (url, "Второе", 2)])

    def test_drm_is_refused_with_reason(self):
        with self.assertRaises(dlcore.Failed) as e:
            dlcore.probe("https://example.com/v/drm")
        self.assertIn("DRM", str(e.exception))


class Download(Base):
    def test_progress_and_file(self):
        it = self.get("ok")
        self.assertEqual(it.state, "done")
        self.assertEqual(it.path, os.path.join(self.out, "Клип ok [ok].mp4"))
        self.assertTrue(os.path.exists(it.path))
        self.assertEqual((it.title, it.total), ("Клип ok", 1000))
        self.assertIn(("work", "download", 40), self.steps)       # ход виден по дороге
        self.assertIn(("work", "process", 100), self.steps)
        self.assertEqual(self.steps[-1], ("done", "", 100))

    def test_second_time_is_not_downloaded(self):
        first = self.get("ok")
        again = self.get("ok")
        self.assertEqual((again.state, again.path), ("had", first.path))

    def test_sound_does_not_eat_the_video(self):
        # Настоящий yt-dlp, вынимая звук, взял бы уже скачанный ролик с тем же именем и удалил его.
        video = self.get("ok").path
        sound = self.get("ok", kind="audio", audio="mp3")
        self.assertEqual(sound.state, "done")
        self.assertEqual(sound.path, os.path.join(self.out, "Клип ok [ok].mp3"))
        self.assertTrue(os.path.exists(video), "видео пропало после «Только звук»")
        self.assertEqual(sorted(os.listdir(self.out)), ["Клип ok [ok].mp3", "Клип ok [ok].mp4"])
        self.assertEqual(os.listdir(dlcore.WORK), [])              # рабочая папка звука убрана

    def test_sound_already_there(self):
        self.get("ok", kind="audio")
        again = self.get("ok", kind="audio")
        self.assertEqual(again.state, "had")
        self.assertEqual(os.listdir(self.out), ["Клип ok [ok].mp3"])

    def test_blocked_site_retried_as_chrome(self):
        self.assertEqual(self.get("forbid").state, "done")
        it = self.get("forbid_always")
        self.assertEqual(it.state, "failed")
        self.assertEqual(it.error, "Сайт не отдал видео. Проверь, что оно открывается в браузере.")
        self.assertIn("403", it.tech)

    def test_reasons(self):
        self.assertEqual(self.get("js").error, "Для YouTube нужна программа Deno или Node.js — на компьютере их нет.")
        self.assertEqual(self.get("unsupported").error, "Этот сайт не поддерживается или по ссылке нет видео.")

    def test_stop_kills_whole_tree(self):
        pid_file = os.path.join(self.dir, "child.pid")
        os.environ["FAKE_CHILD_PID"] = pid_file
        cancel = threading.Event()
        it = dlcore.Item("https://example.com/v/slow")
        th = threading.Thread(target=lambda: self.assertRaises(dlcore.Cancelled, dlcore.download, it, self.out,
                                                               None, cancel))
        th.start()
        end = time.time() + 30
        while it.percent < 10 and time.time() < end:
            time.sleep(0.05)
        self.assertEqual(it.stage, "download")
        cancel.set()
        th.join(30)
        self.assertEqual(it.state, "stopped")
        with open(pid_file) as f:
            child = int(f.read())
        alive = subprocess.run(["tasklist", "/FI", f"PID eq {child}", "/NH"], capture_output=True, text=True,
                               encoding="cp866", errors="replace").stdout
        self.assertNotIn(str(child), alive, "ffmpeg и прочие помощники yt-dlp должны остановиться вместе с ним")


class Reasons(unittest.TestCase):
    def test_drm_first(self):
        self.assertIn("DRM", dlcore.reason(["ERROR: This video is DRM protected"])[0])

    def test_sign_in(self):
        why, tech = dlcore.reason(["ERROR: [youtube] x: Sign in to confirm you're not a bot. Use --cookies"])
        self.assertEqual(why, "Сайт показывает это видео только после входа — пока так не умеем.")
        self.assertTrue(tech.startswith("[youtube] x: Sign in"))

    def test_unknown(self):
        self.assertEqual(dlcore.reason(["ERROR: что-то странное"])[0], "Не получилось скачать.")


if __name__ == "__main__":
    unittest.main()
