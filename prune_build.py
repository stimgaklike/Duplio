"""Убрать из собранной программы части Qt, которые ей не нужны (запускается из build.bat после сборки)."""

import glob
import os
import shutil
import sys

base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist", "Duplio", "_internal", "PySide6")
REMOVE = [
    "opengl32sw.dll",          # программный OpenGL для компьютеров без видеодрайвера — окну на виджетах не нужен
    "translations",            # переводы Qt: диалоги программы и так на русском, выбор папки — системный
    "Qt6Pdf.dll",
    "plugins/imageformats/qpdf.dll",
]
freed = 0
for rel in REMOVE:
    for path in glob.glob(os.path.join(base, rel)):
        if os.path.isdir(path):
            freed += sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(path) for f in fs)
            shutil.rmtree(path)
        else:
            freed += os.path.getsize(path)
            os.remove(path)
print(f"Убрано лишнего: {freed / 2**20:.0f} МБ")
sys.exit(0)
