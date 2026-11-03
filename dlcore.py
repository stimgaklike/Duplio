"""Скачивание видео и звука по ссылке без окна — через yt-dlp.

yt-dlp в программу не вшит: сайты меняются, и он обновляется раз в одну-две недели — вшитый устарел бы за
месяц. Официальный yt-dlp.exe скачивается с его выпусков на GitHub (только с разрешения человека),
сверяется по SHA-256 и потом обновляется сам; лежит в %LOCALAPPDATA%\\Duplio\\tools. Защищённое от
копирования (DRM) не скачивается — yt-dlp его не берёт, а программа объясняет причину.

Ссылка → probe (что за ней: одно видео или плейлист) → Item на каждое видео → download (по одному, с ходом).
"""

import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from ctypes import wintypes
from dataclasses import dataclass

import compcore
from version import VERSION

TOOLS = os.path.join(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(), "Duplio", "tools")
WORK = os.path.join(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(), "Duplio", "download")
EXE_NAME = "yt-dlp.exe"
API = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
SUMS = "SHA2-256SUMS"
CHECK_EVERY = 3 * 86400          # новая версия yt-dlp — не чаще раза в три дня
TIMEOUT = 20
COMMAND = None                   # тесты подменяют: [python, поддельный yt-dlp]

KINDS = {"video": "Видео", "audio": "Только звук"}
QUALITIES = {"best": "Лучшее", "1080": "До 1080p", "720": "До 720p", "480": "До 480p"}
AUDIO_FORMATS = {"mp3": "MP3", "m4a": "M4A"}

MARK = "@@duplio "               # строка хода: «@@duplio статус|скачано|всего|оценка|скорость|осталось|название»
DONE = "@@done "                 # строка с готовым файлом (после всех переделок)
PROGRESS = ("%(progress.status)s|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
            "%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s|%(info.title)s")
OUT_NAME = "%(title).150B [%(id)s].%(ext)s"      # id в имени: два разных ролика с одним названием не спутаются


class Failed(Exception):
    """Не скачалось — с понятной причиной (русский шаблон для tr)."""


class Cancelled(Exception):
    pass


# ---------------------------------------------------------------- сам yt-dlp: где лежит, скачать, обновить

def exe():
    return os.path.join(TOOLS, EXE_NAME)


def command():
    """Чем запускать yt-dlp, или None — его ещё нет (нужно скачать)."""
    if COMMAND:
        return list(COMMAND)
    return [exe()] if os.path.exists(exe()) else None


@dataclass
class Release:
    version: str
    url: str
    size: int
    sha256: str


def _get(url, accept="application/vnd.github+json"):
    req = urllib.request.Request(url, headers={"User-Agent": f"Duplio/{VERSION}", "Accept": accept})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def from_release(data, sums=None):
    """Разобрать ответ GitHub о выпуске yt-dlp. Без контрольной суммы — отказ: непроверенный exe не запускаем.

    sums(url) → текст SHA2-256SUMS — запасной путь, если GitHub не сообщил сумму у самого файла.
    """
    assets = data.get("assets") or []
    asset = next((a for a in assets if a.get("name") == EXE_NAME), None)
    if not asset:
        raise Failed("В выпуске yt-dlp нет файла для Windows.")
    digest = asset.get("digest") or ""
    sha = digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else ""
    if not sha and sums:
        listed = next((a for a in assets if a.get("name") == SUMS), None)
        if listed:
            for line in sums(listed["browser_download_url"]).splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1].lstrip("*") == EXE_NAME:
                    sha = parts[0].lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise Failed("У yt-dlp нет контрольной суммы — такой файл не запускаю.")
    return Release(data.get("tag_name", ""), asset["browser_download_url"], int(asset.get("size") or 0), sha)


def latest():
    return from_release(json.loads(_get(API)), sums=lambda url: _get(url, "*/*").decode("utf-8", "replace"))


def fetch(url, dest, size, sha256, progress=None, cancel=None):
    """Скачать файл с проверкой размера и SHA-256; при любой ошибке недокачанное удаляется."""
    part = dest + ".part"
    h = hashlib.sha256()
    done = 0
    req = urllib.request.Request(url, headers={"User-Agent": f"Duplio/{VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r, open(part, "wb") as f:
            total = size or int(r.headers.get("Content-Length") or 0)
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
        if size and done != size:
            raise Failed("yt-dlp скачался не целиком. Попробуй ещё раз.")
        if h.hexdigest() != sha256.lower():
            raise Failed("Скачанный yt-dlp повреждён (не совпала контрольная сумма). Попробуй ещё раз.")
        os.replace(part, dest)
    finally:
        if os.path.exists(part):
            os.remove(part)


def version(cmd=None):
    """Версия yt-dlp (как в названии выпуска: 2026.10.26) или None, если он не запускается."""
    cmd = cmd or command()
    if not cmd:
        return None
    try:
        out = subprocess.run(cmd + ["--version"], capture_output=True, timeout=120,
                             creationflags=compcore.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = out.stdout.decode("utf-8", "replace").strip()
    return text if out.returncode == 0 and text else None


def install(rel, progress=None, cancel=None):
    """Поставить выпуск rel: скачать рядом, проверить, что запускается, и только потом заменить старый."""
    os.makedirs(TOOLS, exist_ok=True)
    new = os.path.join(TOOLS, "yt-dlp.new.exe")
    fetch(rel.url, new, rel.size, rel.sha256, progress, cancel)
    try:
        if not version([new]):
            raise Failed("Скачанный yt-dlp не запускается.")
        os.replace(new, exe())
    finally:
        if os.path.exists(new):
            os.remove(new)
    return rel.version


def update_due(last_check, now=None):
    return (now or time.time()) - (last_check or 0) >= CHECK_EVERY


def refresh(progress=None, cancel=None):
    """Есть новее — поставить. Возвращает версию, которая стоит теперь."""
    rel = latest()
    if version() == rel.version:
        return rel.version
    return install(rel, progress, cancel)


def js_runtime():
    """Чем yt-dlp решает проверки YouTube: Deno или Node.js, если они есть на компьютере, иначе None."""
    for name in ("deno", "node"):
        path = shutil.which(name)
        if path:
            return name, path
    return None


# ---------------------------------------------------------------- куда класть

def _known_folder(guid):
    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]
    g = GUID()
    ctypes.oledll.ole32.CLSIDFromString(guid, ctypes.byref(g))
    ptr = ctypes.c_wchar_p()
    ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(ptr))
    try:
        return ptr.value
    finally:
        ctypes.windll.ole32.CoTaskMemFree(ptr)


def default_folder():
    """Загрузки\\Duplio — папка «Загрузки» там, куда её перенёс человек (может быть и на другом диске)."""
    try:
        downloads = _known_folder("{374DE290-123F-4565-9164-39C4925E467B}")
    except OSError:
        downloads = None
    return os.path.join(downloads or os.path.join(os.path.expanduser("~"), "Downloads"), "Duplio")


# ---------------------------------------------------------------- ссылка → что за ней

URL = re.compile(r"https?://[^\s<>\"']+", re.I)


def links(text):
    """Ссылки из вставленного текста: по одной на строку или вперемешку с другим текстом; без повторов."""
    seen, out = set(), []
    for m in URL.findall(text or ""):
        u = m.rstrip(".,;)»”")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


@dataclass
class Item:
    url: str
    kind: str = "video"
    quality: str = "best"
    audio: str = "mp3"
    title: str = ""
    index: int = 0               # номер в плейлисте, если у видео нет своей ссылки
    looked: bool = False         # уже знаем, что за ссылкой (probe): одно видео, а не плейлист
    state: str = "wait"          # wait / look / work / done / had (уже было в папке) / failed / stopped
    percent: float = 0.0
    done_bytes: int = 0
    total: int = 0
    speed: float = 0.0
    eta: int = -1
    stage: str = ""              # download / process
    path: str = ""
    error: str = ""              # понятная причина (шаблон для tr)
    tech: str = ""               # что ответил yt-dlp — для журнала


# Что ответил сайт или yt-dlp → понятная причина. Порядок важен: сначала самое определённое.
REASONS = [
    (re.compile(r"\bDRM\b", re.I), "Видео защищено от копирования (DRM) — такое не скачиваем."),
    (re.compile(r"JavaScript runtime|js[- ]runtime", re.I),
     "Для YouTube нужна программа Deno или Node.js — на компьютере их нет."),
    (re.compile(r"sign in|log ?in|login required|members[- ]only|private video|confirm your age|"
                r"cookies", re.I),
     "Сайт показывает это видео только после входа — пока так не умеем."),
    (re.compile(r"not available in your country|geo.?restrict", re.I), "Видео недоступно в твоей стране."),
    (re.compile(r"Unsupported URL", re.I), "Этот сайт не поддерживается или по ссылке нет видео."),
    (re.compile(r"HTTP Error (403|410)|403: Forbidden|410: Gone", re.I),
     "Сайт не отдал видео. Проверь, что оно открывается в браузере."),
    (re.compile(r"HTTP Error 404|Video unavailable|has been removed|does not exist", re.I),
     "Видео нет: удалено, скрыто или ссылка с ошибкой."),
    (re.compile(r"getaddrinfo|Unable to download webpage|timed out|Connection (refused|reset|aborted)|"
                r"Network is unreachable|No route to host|CERTIFICATE_VERIFY_FAILED", re.I),
     "Нет связи с сайтом. Проверь интернет."),
    (re.compile(r"Requested format is not available", re.I), "Такого качества у видео нет — выбери «Лучшее»."),
]
BLOCKED = re.compile(r"HTTP Error (403|410)|403: Forbidden|410: Gone", re.I)


def reason(lines):
    """Понятная причина по выводу yt-dlp: (шаблон для tr, техническая строка для журнала)."""
    errors = [ln for ln in lines if ln.startswith("ERROR:")]
    tech = (errors[-1] if errors else (lines[-1] if lines else "")).removeprefix("ERROR:").strip()
    text = "\n".join(errors) or "\n".join(lines[-5:])
    drm, js = REASONS[0], REASONS[1]
    if drm[0].search(text):
        return drm[1], tech
    if js[0].search("\n".join(lines)):            # «нет Deno» — предупреждение, а ошибка после него о другом
        return js[1], tech
    for rx, why in REASONS[2:]:
        if rx.search(text):
            return why, tech
    return "Не получилось скачать.", tech


def _env():
    env = compcore._env()
    env["PYTHONIOENCODING"] = "utf-8"           # для запуска через python (тесты); yt-dlp.exe — по --encoding
    return env


def _kill(p):
    """yt-dlp.exe — распаковщик, внутри — ещё процесс и ffmpeg: останавливать всё дерево."""
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True,
                   creationflags=compcore.CREATE_NO_WINDOW)
    try:
        p.wait(10)
    except subprocess.TimeoutExpired:
        p.kill()


def _run(args, on_line, cancel=None):
    """Запустить yt-dlp без окна, отдавать строки вывода; cancel — остановить. Возвращает код выхода."""
    cmd = command()
    if not cmd:
        raise Failed("yt-dlp ещё не скачан.")
    p = subprocess.Popen(cmd + args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         creationflags=compcore.CREATE_NO_WINDOW | compcore.BELOW_NORMAL_PRIORITY_CLASS,
                         env=_env())

    def pump():
        for raw in p.stdout:
            on_line(raw.decode("utf-8", "replace").rstrip("\r\n"))
    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        while True:
            try:
                p.wait(0.2)
                break
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel.is_set():
                    _kill(p)
                    reader.join(5)
                    raise Cancelled
        reader.join(5)
    finally:
        p.stdout.close()
    return p.returncode


BASE = ["--ignore-config", "--no-colors", "--encoding", "utf-8"]


def probe(url, cancel=None):
    """Что за ссылкой: [(ссылка, название, номер в плейлисте)] — одно видео или все из плейлиста."""
    lines = []
    code = _run(BASE + ["-J", "--flat-playlist", "--", url], lines.append, cancel)
    data = None
    for ln in lines:
        if ln.startswith("{"):
            try:
                data = json.loads(ln)
            except ValueError:
                pass
    if code != 0 or not data:
        raise Failed(reason(lines)[0])
    if data.get("_type") in ("playlist", "multi_video"):
        out = []
        for i, e in enumerate(data.get("entries") or [], 1):
            if not e:
                continue
            link = e.get("webpage_url") or e.get("url") or ""
            own = link.lower().startswith(("http://", "https://"))
            out.append((link if own else url, e.get("title") or "", 0 if own else i))
        if not out:
            raise Failed("В плейлисте нет видео.")
        return out
    return [(data.get("webpage_url") or url, data.get("title") or "", 0)]


def args_for(item, home, impersonate=False):
    """Ключи yt-dlp для одного видео. home — куда ляжет готовый файл; куски по ходу — в рабочей папке."""
    a = BASE + ["--newline", "--progress", "--progress-template", "download:" + MARK + PROGRESS,
                "--print", "after_move:" + DONE + "%(filepath)s", "--no-simulate",
                "-P", home, "-P", "temp:" + WORK, "-o", OUT_NAME, "--windows-filenames", "--no-overwrites",
                "--continue",
                "--retries", "8", "--fragment-retries", "8", "--concurrent-fragments", "4", "--embed-metadata"]
    a += ["--yes-playlist", "--playlist-items", str(item.index)] if item.index else ["--no-playlist"]
    ff = compcore.tool("ffmpeg")
    if ff:
        a += ["--ffmpeg-location", os.path.dirname(ff)]
    js = js_runtime()
    if js:
        a += ["--js-runtimes", f"{js[0]}:{js[1]}"]
    if item.kind == "audio":
        a += ["-f", "ba/b", "-x", "--audio-format", item.audio, "--audio-quality", "0",
              "--embed-thumbnail", "--convert-thumbnails", "jpg"]
    else:
        h = item.quality
        a += ["-f", "bv*+ba/b" if h == "best" else f"bv*[height<={h}]+ba/b[height<={h}]",
              "--merge-output-format", "mp4/mkv"]
    if impersonate:
        a += ["--impersonate", "chrome"]
    return a + ["--", item.url]


def _num(s, kind=float):
    try:
        return kind(float(s))
    except (TypeError, ValueError):
        return None


def parse_progress(item, line):
    """Строка хода → поля item. True — строка была про ход."""
    if not line.startswith(MARK):
        return False
    status, done, total, estimate, speed, eta, title = (line[len(MARK):].split("|", 6) + [""] * 7)[:7]
    if title and title != "NA":
        item.title = title
    if status == "downloading":
        item.stage = "download"
        item.done_bytes = _num(done, int) or 0
        item.total = _num(total, int) or _num(estimate, int) or item.total
        item.percent = min(100.0, 100.0 * item.done_bytes / item.total) if item.total else 0.0
        item.speed = _num(speed) or 0.0
        e = _num(eta, int)
        item.eta = e if e is not None else -1
    elif status == "finished":
        item.stage = "process"                  # дальше — склейка дорожек, звук, обложка
        item.percent = 100.0
        item.speed, item.eta = 0.0, -1
    return True


def download(item, folder, on_change=None, cancel=None):
    """Скачать одно видео в folder; item заполняется по ходу (on_change(item) — после каждого шага).

    Сайт ответил 403/410 — одна повторная попытка с маскировкой под Chrome (так проверяют «живой ли браузер»).
    Файл с тем же именем уже лежит в папке — не качается заново (state "had").

    Звук готовится в своей рабочей папке и только потом переносится в folder: иначе yt-dlp принимал уже
    скачанный ролик с тем же именем за исходник, вынимал из него звук — и удалял само видео.
    """
    os.makedirs(folder, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)
    on_change = on_change or (lambda it: None)
    home = tempfile.mkdtemp(prefix="audio_", dir=WORK) if item.kind == "audio" else folder
    try:
        for impersonate in (False, True):
            lines, seen = [], {"downloading": False}
            item.state, item.error, item.path, item.stage = "work", "", "", "download"
            on_change(item)

            def line(ln):
                if parse_progress(item, ln):
                    seen["downloading"] |= item.stage == "download"
                    on_change(item)
                elif ln.startswith(DONE):
                    item.path = ln[len(DONE):].strip()
                elif ln.strip():
                    lines.append(ln)
            try:
                code = _run(args_for(item, home, impersonate), line, cancel)
            except Cancelled:
                item.state, item.stage = "stopped", ""
                on_change(item)
                raise
            if code == 0 and item.path and os.path.exists(item.path):
                item.state = "done" if seen["downloading"] else "had"
                if home != folder:
                    _move_in(item, folder)
                item.stage, item.percent = "", 100.0
                item.total = os.path.getsize(item.path)
                if not item.title:
                    item.title = os.path.splitext(os.path.basename(item.path))[0]
                on_change(item)
                return item
            if impersonate or not any(BLOCKED.search(ln) for ln in lines):
                break
        item.error, item.tech = reason(lines)
        item.state, item.stage = "failed", ""
        on_change(item)
        return item
    finally:
        if home != folder:
            shutil.rmtree(home, ignore_errors=True)


def _move_in(item, folder):
    """Готовый звук — из рабочей папки к человеку. Такой файл уже лежит — его не трогаем (state "had")."""
    dest = os.path.join(folder, os.path.basename(item.path))
    if os.path.exists(dest):
        item.state = "had"
    else:
        shutil.move(item.path, dest)
    item.path = dest


def clean_work():
    """Недокачанные куски и звук по ходу — при выходе и перед первой загрузкой не нужны."""
    shutil.rmtree(WORK, ignore_errors=True)
