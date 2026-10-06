"""Установщик и программа договариваются через канал второго запуска — сверяем, что говорят одно и то же.

Установщик пишет в именованный канал Windows, который слушает QLocalServer программы. Ошибку в одной
обратной косой (`\\.\\pipe\\` → `\\.\\pipe`) не видно ни при сборке, ни в тестах программы: просьба просто
никуда не уходит, и установщик просит закрыть Duplio вручную (так и было 6.10.2026).
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import app  # noqa: E402

ISS = os.path.join(os.path.dirname(__file__), "..", "installer.iss")


class InstallerTalksToApp(unittest.TestCase):
    def setUp(self):
        with open(ISS, "rb") as f:
            self.raw = f.read()
        self.text = self.raw.decode("utf-8-sig")

    def test_pipe_is_the_one_the_app_listens_to(self):
        m = re.search(r"CreateFileW\('([^']*)' \+ GetUserNameString\(\)", self.text)
        self.assertIsNotNone(m, "в installer.iss нет вызова CreateFileW с именем канала")
        prefix = app.INSTANCE_KEY[: -len(app.getpass.getuser())]
        # QLocalServer на Windows слушает \\.\pipe\<имя>; имя — "Duplio-" + пользователь.
        self.assertEqual(m.group(1), "\\\\.\\pipe\\" + prefix)

    def test_quit_request_is_the_same_text(self):
        m = re.search(r"msg := '([^']*)';", self.text)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), app.QUIT_REQUEST)

    def test_mutex_is_the_same(self):
        m = re.search(r"AppMutex = '([^']*)';", self.text)
        self.assertEqual(m.group(1), app.APP_MUTEX)

    def test_file_keeps_bom(self):
        # Без BOM Windows PowerShell 5 и старые инструменты читают русский текст как ANSI.
        self.assertTrue(self.raw.startswith(b"\xef\xbb\xbf"))


if __name__ == "__main__":
    unittest.main()
