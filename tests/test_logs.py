import logging
import os
import shutil
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import logs  # noqa: E402


class Journal(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="logs_")
        self.saved = (sys.excepthook, threading.excepthook, sys.__excepthook__)
        sys.__excepthook__ = lambda *a: None          # не печатать в вывод теста
        self.assertTrue(logs.setup("9.9.9", folder=self.dir))

    def tearDown(self):
        for h in list(logs.log.handlers):
            logs.log.removeHandler(h)
            h.close()
        sys.excepthook, threading.excepthook, sys.__excepthook__ = self.saved
        shutil.rmtree(self.dir, ignore_errors=True)

    def text(self):
        for h in logs.log.handlers:
            h.flush()
        with open(logs.path(), encoding="utf-8") as f:
            return f.read()

    def test_start_line(self):
        self.assertIn("запуск Duplio 9.9.9", self.text())

    def test_unhandled_error_goes_to_journal_with_traceback(self):
        crashed = []
        logs.on_crash(crashed.append)
        try:
            raise ZeroDivisionError("проверка")
        except ZeroDivisionError:
            sys.excepthook(*sys.exc_info())
        t = self.text()
        self.assertIn("Необработанная ошибка", t)
        self.assertIn("Traceback", t)
        self.assertIn("ZeroDivisionError: проверка", t)
        self.assertEqual(len(crashed), 1)
        logs._on_crash.clear()

    def test_error_in_thread(self):
        th = threading.Thread(target=lambda: 1 / 0, name="поиск")
        th.start()
        th.join()
        self.assertIn("Необработанная ошибка в потоке поиск", self.text())

    def test_size_is_capped(self):
        for i in range(30_000):
            logs.log.info("строка %d %s", i, "x" * 100)
        files = os.listdir(self.dir)
        self.assertLessEqual(len(files), logs.BACKUPS + 1)
        self.assertLessEqual(logs.total_size(), (logs.BACKUPS + 1) * logs.MAX_BYTES + 10_000)


if __name__ == "__main__":
    unittest.main()
