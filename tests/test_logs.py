import logging
import os
import shutil
import subprocess
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
        logs.stop_crash_trap()                         # иначе crash.log открыт и папку не удалить
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
        files = [f for f in os.listdir(self.dir) if f != logs.CRASH_FILE]
        self.assertLessEqual(len(files), logs.BACKUPS + 1)
        self.assertLessEqual(logs.total_size(), (logs.BACKUPS + 1) * logs.MAX_BYTES + 10_000)

    def test_crash_inside_library_reaches_journal_next_start(self):
        # Вылет в python314.dll (у владельца — при сжатии 14 663 фото) убивает процесс мимо excepthook:
        # журнал просто обрывался. Настоящее нарушение доступа к памяти — в отдельном процессе.
        logs.stop_crash_trap()
        # чтение по адресу 0 в C — то же «access violation», что у владельца (ctypes.string_at(0) не годится:
        # ctypes ловит его сам и превращает в OSError); окно отчёта Windows _read_null не показывает
        code = ("import sys, faulthandler; sys.path.insert(0, sys.argv[1]); import logs; "
                "logs.setup('9.9.9', folder=sys.argv[2]); faulthandler._read_null()")
        run = subprocess.run([sys.executable, "-c", code, os.path.join(os.path.dirname(__file__), ".."), self.dir],
                             capture_output=True, timeout=60)
        self.assertEqual(run.returncode & 0xFFFFFFFF, 0xC0000005)       # процесс убит нарушением доступа
        logs.setup("9.9.9", folder=self.dir)
        t = self.text()
        self.assertIn("Прошлый запуск упал внутри библиотеки", t)
        self.assertIn("access violation", t)
        self.assertIn('File "<string>", line 1', t)               # где был поток — видно
        self.assertEqual(t.count("Прошлый запуск упал"), 1)
        with open(os.path.join(self.dir, logs.CRASH_FILE), encoding="utf-8") as f:
            self.assertEqual(f.read(), "")                       # перенесено — второй раз не повторится

    def test_survived_windows_exception_is_not_a_crash(self):
        logs.stop_crash_trap()
        with open(os.path.join(self.dir, logs.CRASH_FILE), "w", encoding="utf-8") as f:
            f.write("Windows fatal exception: code 0x8001010d\n\nThread 0x0001 (most recent call first):\n")
        logs.setup("9.9.9", folder=self.dir)
        t = self.text()
        self.assertIn("Сведения faulthandler с прошлого запуска", t)
        self.assertNotIn("Прошлый запуск упал", t)


if __name__ == "__main__":
    unittest.main()
