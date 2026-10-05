import hashlib
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import updater  # noqa: E402


def release(tag, assets=None, **kw):
    data = dict(tag_name=tag, body="Что нового", html_url="https://example/r", draft=False, prerelease=False,
                assets=assets if assets is not None else [
                    {"name": f"Duplio-Setup-{tag.lstrip('v')}.exe", "browser_download_url": "https://example/x.exe",
                     "size": 10, "digest": "sha256:ABC"}])
    data.update(kw)
    return data


class Versions(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(updater.parse_version("v1.10.2"), (1, 10, 2))
        self.assertEqual(updater.parse_version("2.0"), (2, 0, 0))
        self.assertGreater(updater.parse_version("v1.10.0"), updater.parse_version("1.9.9"))   # не строками

    def test_newer_release_is_offered(self):
        u = updater.from_release(release("v1.2.0"), current="1.0.0")
        self.assertEqual((u.version, u.size, u.sha256), ("1.2.0", 10, "abc"))

    def test_same_or_older_is_not_offered(self):
        self.assertIsNone(updater.from_release(release("v1.0.0"), current="1.0.0"))
        self.assertIsNone(updater.from_release(release("v0.9.0"), current="1.0.0"))

    def test_drafts_prereleases_and_no_installer_are_skipped(self):
        self.assertIsNone(updater.from_release(release("v2.0.0", prerelease=True), current="1.0.0"))
        self.assertIsNone(updater.from_release(release("v2.0.0", assets=[{"name": "notes.txt"}]), current="1.0.0"))


class Check(unittest.TestCase):
    def test_no_releases_yet_means_no_update(self):
        import urllib.error

        def boom(url):
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
        saved = updater._get_json
        updater._get_json = boom
        try:
            self.assertIsNone(updater.check())
        finally:
            updater._get_json = saved

    def test_other_errors_are_reported(self):
        import urllib.error

        def boom(url):
            raise urllib.error.HTTPError(url, 500, "Server Error", None, None)
        saved = updater._get_json
        updater._get_json = boom
        try:
            with self.assertRaises(urllib.error.HTTPError):
                updater.check()
        finally:
            updater._get_json = saved


class Download(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="upd_")
        self.src = os.path.join(self.dir, "src.exe")
        self.data = os.urandom(700_000)
        with open(self.src, "wb") as f:
            f.write(self.data)
        self.out = os.path.join(self.dir, "out")
        os.makedirs(self.out)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def upd(self, sha=None, size=None):
        return updater.Update("9.9.9", "", Path(self.src).as_uri(), size if size is not None else len(self.data),
                              sha if sha is not None else hashlib.sha256(self.data).hexdigest(), "")

    def test_good_download(self):
        seen = []
        p = updater.download(self.upd(), progress=lambda d, t: seen.append((d, t)), folder=self.out)
        self.assertEqual(open(p, "rb").read(), self.data)
        self.assertEqual(seen[-1], (len(self.data), len(self.data)))
        self.assertEqual(os.listdir(self.out), ["Duplio-Setup-9.9.9.exe"])

    def test_wrong_checksum_leaves_nothing(self):
        with self.assertRaises(ValueError):
            updater.download(self.upd(sha="0" * 64), folder=self.out)
        self.assertEqual(os.listdir(self.out), [])          # ни готового файла, ни .part

    def test_wrong_size_leaves_nothing(self):
        with self.assertRaises(IOError):
            updater.download(self.upd(size=123), folder=self.out)
        self.assertEqual(os.listdir(self.out), [])

    def test_cancel(self):
        ev = threading.Event()
        ev.set()
        with self.assertRaises(updater.Cancelled):
            updater.download(self.upd(), cancel=ev, folder=self.out)
        self.assertEqual(os.listdir(self.out), [])

    def test_cleanup_removes_old_installers_only(self):
        for n in ("Duplio-Setup-1.0.0.exe", "Duplio-Setup-1.1.0.exe.part", "other.exe"):
            open(os.path.join(self.out, n), "wb").close()
        updater.cleanup(self.out)
        self.assertEqual(os.listdir(self.out), ["other.exe"])


if __name__ == "__main__":
    unittest.main()
