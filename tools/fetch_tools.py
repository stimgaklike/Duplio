"""Скачивает программы для сжатия в third_party\\ (в git не попадают): jpegtran, oxipng, ffmpeg.

Версии закреплены, у каждого файла — размер и SHA-256: чужой или подменённый файл не ляжет.
Запуск: python tools/fetch_tools.py   (повторный запуск ничего не качает, если всё на месте)
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

# В GitHub Actions вывод идёт в кодировке cp1252 — русский текст ронял бы скрипт (UnicodeEncodeError).
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "third_party")
CACHE = os.path.join(OUT, "_downloads")

GH = "https://github.com"
TOOLS = [
    dict(name="jpegtran", kind="nsis",
         url=f"{GH}/libjpeg-turbo/libjpeg-turbo/releases/download/3.2.0/libjpeg-turbo-3.2.0-vc-x64.exe",
         size=2361008, sha256="662761d8ba8dae04aec74023ebaeceb856c2b56b9b59cfd180759d26300dda42",
         take=["bin/jpegtran.exe", "bin/jpeg62.dll", "doc/LICENSE.md", "doc/README.ijg"]),
    dict(name="oxipng", kind="zip",
         url=f"{GH}/oxipng/oxipng/releases/download/v10.2.1/oxipng-10.2.1-x86_64-pc-windows-msvc.zip",
         size=497302, sha256="7e940f83ee46874b73f53031f96a15834cb70b220af27391fb06fe7b4dd798e1",
         take=["oxipng.exe", "LICENSE.txt"]),
    dict(name="ffmpeg", kind="zip",
         url=f"{GH}/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-10-05-13-07/"
             "ffmpeg-n8.1.3-14-g330caae0c1-win64-lgpl-shared-8.1.zip",
         size=80993040, sha256="534653068a3ac64ed5d02361e1ad59e4cb99a713f425444b470514999e437473",
         take=["bin/ffmpeg.exe", "bin/ffprobe.exe", "bin/*.dll", "LICENSE.txt"]),
]


# Свой релиз «deps» с теми же файлами — первым: сборки FFmpeg на исходном сервере живут около месяца.
# Не скачалось оттуда — берём у авторов; в любом случае размер и SHA-256 сверяются.
MIRROR = f"{GH}/stimgaklike/Duplio/releases/download/deps"


def urls(t):
    return [f"{MIRROR}/{t['url'].rsplit('/', 1)[1]}", t["url"]]


def _download(t):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, t["url"].rsplit("/", 1)[1])
    if os.path.exists(path) and os.path.getsize(path) == t["size"] and _sha(path) == t["sha256"]:
        return path
    tmp = path + ".part"
    for url in urls(t):
        print(f"  скачиваю {url} ({t['size'] / 1e6:.1f} МБ)")
        try:
            with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
        except OSError as e:                      # нет сети, 404 — пробуем следующий адрес
            print(f"  не скачалось: {e}")
            continue
        size, sha = os.path.getsize(tmp), _sha(tmp)
        if size == t["size"] and sha == t["sha256"]:
            os.replace(tmp, path)
            return path
        print(f"  НЕ СОВПАЛО: размер {size}, sha256 {sha} — файл отброшен")
    if os.path.exists(tmp):
        os.remove(tmp)
    sys.exit(f"  {t['name']}: ни один адрес не дал нужный файл")


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _seven_zip():
    for p in (shutil.which("7z"), r"C:\Program Files\7-Zip\7z.exe"):
        if p and os.path.exists(p):
            return p
    sys.exit("  нужен 7-Zip (7z), чтобы достать jpegtran из установщика libjpeg-turbo")


def _unpack(t, archive, into):
    if t["kind"] == "zip":
        with zipfile.ZipFile(archive) as z:
            z.extractall(into)
    else:
        subprocess.run([_seven_zip(), "x", "-y", f"-o{into}", archive], check=True, stdout=subprocess.DEVNULL)
    # в zip всё лежит во вложенной папке — берём её как корень
    items = os.listdir(into)
    return os.path.join(into, items[0]) if len(items) == 1 and os.path.isdir(os.path.join(into, items[0])) else into


def _take(src, pattern, dest):
    import glob
    found = glob.glob(os.path.join(src, pattern))
    if not found:
        sys.exit(f"  в архиве нет {pattern}")
    for f in found:
        shutil.copy2(f, dest)


def main():
    for t in TOOLS:
        dest = os.path.join(OUT, t["name"])
        stamp = os.path.join(dest, ".sha256")
        if os.path.exists(stamp) and open(stamp).read() == t["sha256"]:
            print(f"{t['name']}: на месте")
            continue
        print(f"{t['name']}:")
        archive = _download(t)
        shutil.rmtree(dest, ignore_errors=True)
        os.makedirs(dest)
        with tempfile.TemporaryDirectory() as tmp:
            src = _unpack(t, archive, tmp)
            for pattern in t["take"]:
                _take(src, pattern, dest)
        with open(stamp, "w") as f:
            f.write(t["sha256"])
        print(f"  готово: {', '.join(sorted(os.listdir(dest)))}")


if __name__ == "__main__":
    main()
