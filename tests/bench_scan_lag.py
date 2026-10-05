"""Замер отзывчивости окна во время поиска: как сильно запаздывает таймер окна (16 мс).

python tests/bench_scan_lag.py <папка> [нагрузка]
Окно «лагает», если таймер срабатывает с опозданием: 100+ мс уже заметно на глаз, 16 мс — плавно.
Файлы только читаются.
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

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import app  # noqa: E402

folder = sys.argv[1]
load = sys.argv[2] if len(sys.argv) > 2 else "gentle"
qapp = QApplication(sys.argv)
cfg = settings.load()
cfg["load"] = load
cfg["kinds"] = ["photo"]
w = app.MainWindow(cfg)
w.show()
p = w.dups
for k, b in p.chips.items():
    b.setChecked(k == "photo")
gaps = []
last = [time.perf_counter()]


def tick():
    now = time.perf_counter()
    gaps.append((now - last[0]) * 1000 - 16)
    last[0] = now


timer = QTimer(interval=16)
timer.timeout.connect(tick)
p.folder.setText(folder)
t0 = time.perf_counter()
timer.start()
p.start_scan()
while p.busy:
    qapp.processEvents()
    time.sleep(0.002)
took = time.perf_counter() - t0
timer.stop()
gaps.sort()
print(f"поиск {took:.1f} с, групп {len(p.groups)}; запаздывание окна: медиана {statistics.median(gaps):.0f} мс, "
      f"95% {gaps[int(len(gaps) * .95)]:.0f} мс, худшее {gaps[-1]:.0f} мс, "
      f"заметных (>100 мс): {sum(g > 100 for g in gaps)}")
w.close()
