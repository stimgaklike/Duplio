"""Окно-тесты (e2e) не трогают рабочие папки установленного Duplio.

Окно при выходе чистит рабочие папки всех вкладок; e2e, подменивший только свою, стирал настоящие — и копии,
которые владелец в это время готовил в установленном Duplio. Здесь сверяется, что каждый e2e подключает
e2e_isolate раньше, чем создаёт окно, и что после него все рабочие папки — временные.
"""

import glob
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


class E2EIsolation(unittest.TestCase):
    def test_every_e2e_isolates_work_folders_before_the_window(self):
        bad = []
        for path in sorted(glob.glob(os.path.join(HERE, "e2e_*.py"))):
            if os.path.basename(path) == "e2e_isolate.py":
                continue
            with open(path, encoding="utf-8") as f:
                src = f.read()
            at, window = src.find("\nimport e2e_isolate"), src.find("MainWindow(")
            if at < 0 or (window >= 0 and at > window):
                bad.append(os.path.basename(path))
        self.assertEqual(bad, [])

    def test_isolation_points_every_work_folder_to_temp(self):
        # Отдельный процесс: подмена — при импорте, а здесь модули уже могли быть загружены другими тестами.
        code = ("import sys; sys.path[:0] = [%r, %r]\n"
                "import e2e_isolate, compcore, convcore, metacore\n"
                "for m in (compcore, convcore, metacore): print(m.WORK, '|', e2e_isolate.REAL[m])") % (
                    HERE, os.path.dirname(HERE))
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8",
                             check=True).stdout.strip().splitlines()
        self.assertEqual(len(out), 3)
        temp = os.path.normcase(os.path.realpath(tempfile.gettempdir()))
        for line in out:
            now, real = (os.path.normcase(os.path.realpath(x.strip())) for x in line.split("|"))
            self.assertNotEqual(now, real)
            self.assertTrue(now.startswith(temp), now)
            self.assertNotIn(os.path.join("duplio", ""), now[len(temp):])     # не внутри настоящей …\Duplio\


if __name__ == "__main__":
    unittest.main()
