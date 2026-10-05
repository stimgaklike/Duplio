"""Обновления: узнать последнюю версию на GitHub, скачать установщик, проверить его и запустить.

Обращение одно — к открытому адресу выпусков репозитория; ничего о пользователе и его файлах не отправляется.
"""

import glob
import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass

from version import REPO, VERSION

API = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET = re.compile(r"^Duplio-Setup-.*\.exe$", re.I)
TIMEOUT = 15


@dataclass
class Update:
    version: str
    notes: str
    url: str
    size: int
    sha256: str          # пусто, если GitHub не сообщил контрольную сумму
    page: str


class Cancelled(Exception):
    pass


def parse_version(v):
    """'v1.10.2' → (1, 10, 2). Нечисловые хвосты (-beta) отбрасываются."""
    nums = [int(x) for x in re.findall(r"\d+", v)[:3]]
    return tuple(nums + [0] * (3 - len(nums)))


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": f"Duplio/{VERSION}",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def from_release(data, current=VERSION):
    """Разобрать ответ GitHub о выпуске. None — если он не новее текущей версии или в нём нет установщика."""
    tag = data.get("tag_name", "")
    if data.get("draft") or data.get("prerelease") or parse_version(tag) <= parse_version(current):
        return None
    asset = next((a for a in data.get("assets", []) if ASSET.match(a.get("name", ""))), None)
    if not asset:
        return None
    digest = asset.get("digest") or ""
    return Update(version=tag.lstrip("vV"), notes=(data.get("body") or "").strip(),
                  url=asset["browser_download_url"], size=int(asset.get("size") or 0),
                  sha256=digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else "",
                  page=data.get("html_url", ""))


def check(current=VERSION):
    try:
        return from_release(_get_json(API), current)
    except urllib.error.HTTPError as e:
        if e.code == 404:           # выпусков ещё нет (или репозиторий закрыт) — значит, обновляться не на что
            return None
        raise


def download(upd, progress=None, cancel=None, folder=None):
    """Скачать установщик во временную папку; проверить размер и SHA-256. Возвращает путь к файлу."""
    folder = folder or tempfile.gettempdir()
    dest = os.path.join(folder, f"Duplio-Setup-{upd.version}.exe")
    part = dest + ".part"
    h = hashlib.sha256()
    done = 0
    req = urllib.request.Request(upd.url, headers={"User-Agent": f"Duplio/{VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r, open(part, "wb") as f:
            total = upd.size or int(r.headers.get("Content-Length") or 0)
            while True:
                if cancel is not None and cancel.is_set():
                    raise Cancelled
                block = r.read(256 * 1024)
                if not block:
                    break
                f.write(block)
                h.update(block)
                done += len(block)
                if progress:
                    progress(done, total)
        if upd.size and done != upd.size:
            raise IOError(f"size {done} != {upd.size}")
        if upd.sha256 and h.hexdigest() != upd.sha256:
            raise ValueError("checksum")
        os.replace(part, dest)
        return dest
    finally:
        if os.path.exists(part):
            os.remove(part)


def install(path):
    """Запустить установщик тихо; он дождётся закрытия программы, обновит её и откроет снова."""
    subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/UPDATE=1"], close_fds=True)


def cleanup(folder=None):
    """Удалить скачанные раньше установщики — после обновления они больше не нужны."""
    for p in glob.glob(os.path.join(folder or tempfile.gettempdir(), "Duplio-Setup-*.exe*")):
        try:
            os.remove(p)
        except OSError:
            pass
