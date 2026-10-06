"""После сборки (запускается из build.bat): убрать лишние части Qt и Pillow, положить программы для сжатия."""

import glob
import os
import shutil
import sys

# В GitHub Actions вывод идёт в кодировке cp1252 — русский текст ронял бы скрипт (UnicodeEncodeError).
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

here = os.path.dirname(os.path.abspath(__file__))
internal = os.path.join(here, "dist", "Duplio", "_internal")
base = os.path.join(internal, "PySide6")
REMOVE = [
    "opengl32sw.dll",          # программный OpenGL для компьютеров без видеодрайвера — окну на виджетах не нужен
    "translations",            # переводы Qt: диалоги программы и так на русском, выбор папки — системный
    "Qt6Pdf.dll",
    "plugins/imageformats/qpdf.dll",
    "../PIL/_avif*.pyd",       # AVIF Pillow не нужен: фото сжимаются в JPEG (Pillow сам переживает его отсутствие)
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

# Программы для сжатия — копией после сборки, а не через --add-data: PyInstaller разбирает ffmpeg.exe
# и кладёт все его DLL ещё раз в корень _internal (+160 МБ одних и тех же файлов).
for name in ("jpegtran", "oxipng", "ffmpeg"):
    src = os.path.join(here, "third_party", name)
    if not os.path.isdir(src):
        sys.exit(f"Нет third_party\\{name}: сначала python tools/fetch_tools.py")
    shutil.copytree(src, os.path.join(internal, "third_party", name), dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(".sha256"))
print("Программы для сжатия положены в _internal\\third_party")
sys.exit(0)
