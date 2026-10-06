import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import dupcore  # noqa: E402


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def paths(group):
    return sorted(os.path.relpath(m.path, ROOT[0]) for m in group)


ROOT = [None]


class FindDuplicates(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="dup_")
        ROOT[0] = self.root

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def p(self, *parts):
        return os.path.join(self.root, *parts)

    def groups(self):
        return sorted(paths(g) for g in dupcore.find_duplicates(self.root).groups)

    def test_copies_in_nested_folders_under_other_names(self):
        photo = os.urandom(300_000)
        write(self.p("a", "IMG_1.jpg"), photo)
        write(self.p("b", "c", "копия.JPG"), photo)
        write(self.p("other.jpg"), os.urandom(300_000))
        self.assertEqual(self.groups(), [[os.path.join("a", "IMG_1.jpg"), os.path.join("b", "c", "копия.JPG")]])

    def test_same_size_same_edges_different_middle_is_not_a_copy(self):
        # Ловушка для быстрого отсева: начало и конец совпадают, середина — нет.
        head, tail = os.urandom(dupcore.EDGE), os.urandom(dupcore.EDGE)
        write(self.p("1.mp4"), head + b"A" * 500_000 + tail)
        write(self.p("2.mp4"), head + b"B" * 500_000 + tail)
        self.assertEqual(self.groups(), [])

    def test_small_files_same_size_different_content(self):
        write(self.p("1.png"), b"x" * 1000)
        write(self.p("2.png"), b"y" * 1000)
        write(self.p("3.png"), b"x" * 1000)
        self.assertEqual(self.groups(), [["1.png", "3.png"]])

    def test_not_media_and_empty_files_are_ignored(self):
        data = os.urandom(5000)
        write(self.p("1.txt"), data)
        write(self.p("2.txt"), data)
        write(self.p("e1.jpg"), b"")
        write(self.p("e2.jpg"), b"")
        self.assertEqual(self.groups(), [])

    def test_hardlink_is_not_a_duplicate(self):
        write(self.p("1.jpg"), os.urandom(4000))
        os.link(self.p("1.jpg"), self.p("link.jpg"))
        self.assertEqual(self.groups(), [])

    def test_junction_to_another_folder_is_not_followed(self):
        import _winapi
        outside = tempfile.mkdtemp(prefix="dup_out_")
        try:
            data = os.urandom(4000)
            write(self.p("a", "p1.jpg"), data)
            write(os.path.join(outside, "p2.jpg"), data)           # копия ЗА пределами выбранной папки
            _winapi.CreateJunction(outside, self.p("link"))
            self.assertEqual(self.groups(), [])
        finally:
            os.rmdir(self.p("link"))                                # убрать саму связку, не то, куда она ведёт
            shutil.rmtree(outside, ignore_errors=True)

    def test_recycle_bin_folder_is_skipped(self):
        data = os.urandom(4000)
        write(self.p("1.jpg"), data)
        write(self.p("$RECYCLE.BIN", "S-1", "$R1.jpg"), data)
        self.assertEqual(self.groups(), [])

    def test_cancel(self):
        data = os.urandom(4000)
        write(self.p("1.jpg"), data)
        write(self.p("2.jpg"), data)
        ev = threading.Event()
        ev.set()
        res = dupcore.find_duplicates(self.root, cancel=ev)
        self.assertTrue(res.cancelled)
        self.assertEqual(res.groups, [])


class LoadLevels(unittest.TestCase):
    """Все уровни нагрузки находят одно и то же; группы одного размера с разным содержимым не смешиваются."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="dup_")
        ROOT[0] = self.root
        a, b = os.urandom(300_000), os.urandom(300_000)      # одинаковый размер, разное содержимое
        for i in range(3):
            write(os.path.join(self.root, f"a{i}.mp4"), a)
            write(os.path.join(self.root, f"b{i}.mp4"), b)
        write(os.path.join(self.root, "single.mp4"), os.urandom(300_000))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_same_result_on_every_level(self):
        expected = [["a0.mp4", "a1.mp4", "a2.mp4"], ["b0.mp4", "b1.mp4", "b2.mp4"]]
        for load in dupcore.LOAD_LEVELS:
            with self.subTest(load=load):
                got = sorted(paths(g) for g in dupcore.find_duplicates(self.root, load=load).groups)
                self.assertEqual(got, expected)

    def test_groups_arrive_one_by_one_biggest_first(self):
        for load in dupcore.LOAD_LEVELS:
            with self.subTest(load=load):
                got = []
                res = dupcore.find_duplicates(self.root, load=load, on_group=got.append)
                self.assertEqual(sorted(paths(g) for g in got), sorted(paths(g) for g in res.groups))
                self.assertEqual(len(got), 2)

    def test_biggest_group_is_announced_first(self):
        big = os.urandom(900_000)
        for i in range(2):
            write(os.path.join(self.root, f"big{i}.mp4"), big)
        got = []
        dupcore.find_duplicates(self.root, load="normal", on_group=got.append)
        self.assertEqual(paths(got[0]), ["big0.mp4", "big1.mp4"])

    def test_cancel_in_fast_mode(self):
        ev = threading.Event()
        ev.set()
        self.assertTrue(dupcore.find_duplicates(self.root, cancel=ev, load="fast").cancelled)


class KeepAndDelete(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="dup_")
        data = os.urandom(4000)
        self.old = write(os.path.join(self.root, "deep", "folder", "old.jpg"), data)
        self.new = write(os.path.join(self.root, "new.jpg"), data)
        now = time.time()
        os.utime(self.old, (now - 1000, now - 1000))
        self.group = dupcore.find_duplicates(self.root).groups[0]

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_default_keeps_oldest(self):
        self.assertEqual(self.group[0].path, self.old)

    def test_rules(self):
        self.assertEqual(dupcore.sort_keep_first(self.group, "newest")[0].path, self.new)
        self.assertEqual(dupcore.sort_keep_first(self.group, "shortest")[0].path, self.new)
        self.assertEqual(dupcore.sort_keep_first(self.group, "oldest")[0].path, self.old)

    def test_refuses_to_delete_every_copy(self):
        ok, problems = dupcore.check_before_delete([self.group], {self.old, self.new})
        self.assertEqual(ok, [])
        self.assertEqual(len(problems), 1)

    def test_deletes_marked_when_one_copy_stays(self):
        ok, problems = dupcore.check_before_delete([self.group], {self.new})
        self.assertEqual([m.path for m in ok], [self.new])
        self.assertEqual(problems, [])

    def test_skips_file_changed_after_scan(self):
        with open(self.new, "ab") as f:
            f.write(b"more")
        ok, problems = dupcore.check_before_delete([self.group], {self.new})
        self.assertEqual(ok, [])
        self.assertEqual(len(problems), 1)

    def test_skips_group_when_kept_copy_is_gone(self):
        os.remove(self.old)
        ok, problems = dupcore.check_before_delete([self.group], {self.new})
        self.assertEqual(ok, [])
        self.assertEqual(len(problems), 1)

    def test_recycle_bin_removes_only_given_files(self):
        removed, left = dupcore.to_recycle_bin([self.new])
        self.assertEqual(removed, [os.path.abspath(self.new)])
        self.assertEqual(left, [])
        self.assertFalse(os.path.exists(self.new))
        self.assertTrue(os.path.exists(self.old))


class Kinds(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="dup_")
        ROOT[0] = self.root
        for ext in (".jpg", ".mp3", ".pdf", ".blend"):
            data = os.urandom(3000)
            write(os.path.join(self.root, "a" + ext), data)
            write(os.path.join(self.root, "b" + ext), data)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def found(self, kinds):
        return sorted(os.path.splitext(g[0].path)[1]
                      for g in dupcore.find_duplicates(self.root, kinds=kinds).groups)

    def test_default_is_photo_and_video_only(self):
        self.assertEqual(self.found(dupcore.DEFAULT_KINDS), [".jpg"])

    def test_music_only(self):
        self.assertEqual(self.found({"audio"}), [".mp3"])

    def test_other_means_unknown_extensions_only(self):
        self.assertEqual(self.found({"other"}), [".blend"])

    def test_everything(self):
        self.assertEqual(self.found(set(dupcore.KINDS)), [".blend", ".jpg", ".mp3", ".pdf"])

    def test_system_files_skipped_in_other_mode(self):
        import subprocess
        for n in ("a.blend", "b.blend"):
            subprocess.run(["attrib", "+s", os.path.join(self.root, n)], check=True)
        try:
            self.assertEqual(self.found({"other"}), [])
        finally:
            for n in ("a.blend", "b.blend"):
                subprocess.run(["attrib", "-s", os.path.join(self.root, n)], check=True)


class CloudOnly(unittest.TestCase):
    """Файлы «только в облаке» (OneDrive, телефон в CrossDevice) нельзя читать: Windows начнёт их скачивать."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="dup_")
        data = os.urandom(300_000)
        for n in ("cloud_a.jpg", "cloud_b.jpg", "local.jpg"):
            write(os.path.join(self.root, n), data)
        real_stat = os.stat

        class FakeStat:
            def __init__(self, st, extra):
                self._st, self.st_file_attributes = st, st.st_file_attributes | extra

            def __getattr__(self, name):
                return getattr(self._st, name)

        def fake_stat(path, *a, **k):
            st = real_stat(path, *a, **k)
            if os.path.basename(str(path)).startswith("cloud_"):
                return FakeStat(st, dupcore.FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS)
            return st
        self.real_stat = real_stat
        dupcore.os.stat = fake_stat
        self.opened = []
        self.real_hash = dupcore._hash
        dupcore._hash = lambda path, *a: self.opened.append(path) or self.real_hash(path, *a)

    def tearDown(self):
        dupcore.os.stat = self.real_stat
        dupcore._hash = self.real_hash
        shutil.rmtree(self.root, ignore_errors=True)

    def test_cloud_files_are_never_opened(self):
        res = dupcore.find_duplicates(self.root)
        self.assertEqual(res.groups, [])
        self.assertEqual(res.cloud_skipped, 2)
        self.assertFalse([p for p in self.opened if "cloud_" in p])


class Progress(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="dup_")
        big = os.urandom(400_000)
        write(os.path.join(self.root, "1.mp4"), big)
        write(os.path.join(self.root, "2.mp4"), big)
        write(os.path.join(self.root, "3.jpg"), os.urandom(5000))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_steps_go_in_order_and_finish_at_total(self):
        calls = []
        dupcore.find_duplicates(self.root, progress=lambda *a: calls.append(a))
        steps = [c[0] for c in calls]
        self.assertEqual(steps, sorted(steps))
        self.assertEqual(set(steps), {1, 2, 3})
        last = {c[0]: c for c in calls}
        self.assertEqual(last[1][2], 3)                     # найдено 3 файла
        self.assertEqual(last[2][2:4], (2, 2))              # оба больших файла проверены по краям
        self.assertEqual(last[3][2:5], (800_000, 800_000, "bytes"))


class SettingsFile(unittest.TestCase):
    def test_bad_values_fall_back_to_defaults(self):
        import json
        import settings
        d = tempfile.mkdtemp(prefix="cfg_")
        saved = settings.PATH
        settings.PATH = os.path.join(d, "settings.json")
        try:
            with open(settings.PATH, "w", encoding="utf-8") as f:
                json.dump({"load": "turbo", "theme": 5, "kinds": ["photo", "x"], "close_action": "взорвать",
                           "keep_rule": "newest", "last_update_check": "вчера"}, f)
            cfg = settings.load()
            self.assertEqual(cfg["load"], "gentle")
            self.assertEqual(cfg["theme"], "system")
            self.assertEqual(cfg["kinds"], ["photo", "video"])
            self.assertEqual(cfg["close_action"], "ask")
            self.assertEqual(cfg["keep_rule"], "newest")          # правильное значение сохраняется
            self.assertEqual(cfg["last_update_check"], 0)
            with open(settings.PATH, "w", encoding="utf-8") as f:
                f.write("{не json")
            self.assertEqual(settings.load()["load"], "gentle")
        finally:
            settings.PATH = saved
            shutil.rmtree(d, ignore_errors=True)

    def test_bad_compress_values_fall_back_to_defaults(self):
        import settings
        cfg = settings.sanitize(dict(settings.DEFAULTS, compress_mode="сжать всё", compress_kinds=["photo", "audio"],
                                     compress_folder=42))
        self.assertEqual((cfg["compress_mode"], cfg["compress_kinds"], cfg["compress_folder"]),
                         ("lossless", ["photo", "video"], ""))
        good = settings.sanitize(dict(settings.DEFAULTS, compress_mode="visual", compress_kinds=["video"],
                                      compress_folder=r"E:\Фото"))
        self.assertEqual((good["compress_mode"], good["compress_kinds"], good["compress_folder"]),
                         ("visual", ["video"], r"E:\Фото"))

    def test_old_setting_close_to_tray_false_means_quit(self):
        import json
        import settings
        d = tempfile.mkdtemp(prefix="cfg_")
        saved = settings.PATH
        settings.PATH = os.path.join(d, "settings.json")
        try:
            with open(settings.PATH, "w", encoding="utf-8") as f:
                json.dump({"close_to_tray": False}, f)                 # как сохраняла версия 1.0.0
            self.assertEqual(settings.load()["close_action"], "quit")
        finally:
            settings.PATH = saved
            shutil.rmtree(d, ignore_errors=True)

    def test_fixed_drive_has_recycle_bin(self):
        self.assertTrue(dupcore.has_recycle_bin("C:"))


class HumanSize(unittest.TestCase):
    def test_format(self):
        self.assertEqual(dupcore.human_size(512), "512 Б")
        self.assertEqual(dupcore.human_size(4_404_019), "4,2 МБ")
        self.assertEqual(dupcore.human_size(3 * 1024 ** 3), "3,0 ГБ")
        self.assertEqual(dupcore.human_size(4140 * 1024 ** 3), "4,0 ТБ")

    def test_time(self):
        self.assertEqual(dupcore.human_time(42), "42 с")
        self.assertEqual(dupcore.human_time(185), "3 мин 05 с")
        self.assertEqual(dupcore.human_time(1500), "25 мин")
        self.assertEqual(dupcore.human_time(3 * 3600 + 120), "3 ч 02 мин")


if __name__ == "__main__":
    unittest.main()
