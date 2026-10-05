"""Замер плавности: время перерисовки окна на каждый шаг изменения размера.

python tests/bench_resize.py [групп]
Плавно — это меньше ~16 мс на шаг (60 кадров в секунду). Старое окно на tkinter давало ~190 мс.
"""

import os
import statistics
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import settings  # noqa: E402

tmp_cfg = tempfile.mkdtemp(prefix="dup_cfg_")
settings.DIR, settings.PATH = tmp_cfg, os.path.join(tmp_cfg, "settings.json")

from PySide6.QtWidgets import QApplication  # noqa: E402

import app  # noqa: E402
import dupcore  # noqa: E402

n_groups = int(sys.argv[1]) if len(sys.argv) > 1 else 300
qapp = QApplication(sys.argv)
w = app.MainWindow(settings.load())
w.show()
root = tempfile.gettempdir()
now = time.time()
p = w.dups
p.scan_root = root
p.groups = [[dupcore.MediaFile(os.path.join(root, f"папка{g % 7}", f"IMG_{g:04d}_{i}.jpg"), 1_000_000 + g,
                               now - i * 1000) for i in range(2 + g % 3)] for g in range(n_groups)]
p.apply_rule()
if p.groups:
    p.tree.setCurrentItem(p.items[p.groups[0][0].path])
for _ in range(30):
    qapp.processEvents()
    time.sleep(0.01)

W, H = w.width(), w.height()
times = []
for step in range(60):
    k = step if step < 30 else 60 - step
    t = time.perf_counter()
    w.resize(W - k * 10, H - k * 5)
    qapp.processEvents()
    w.repaint()
    times.append((time.perf_counter() - t) * 1000)
w.close()
times.sort()
print(f"групп {n_groups}: медиана {statistics.median(times):.1f} мс, 90% {times[int(len(times) * .9)]:.1f} мс, "
      f"худший {times[-1]:.1f} мс на шаг")
