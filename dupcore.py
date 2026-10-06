"""Поиск точных копий файлов: логика без окна, чтобы её можно было проверять тестами."""

import ctypes
import hashlib
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from ctypes import wintypes
from dataclasses import dataclass, field

from i18n import decimal, tr

IMAGE_EXT = {
    ".jpg", ".jpeg", ".jfif", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff",
    ".heic", ".heif", ".avif", ".dng", ".cr2", ".cr3", ".nef", ".arw", ".orf", ".rw2", ".raf",
}
VIDEO_EXT = {
    ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".wmv", ".webm", ".3gp", ".3g2",
    ".mts", ".m2ts", ".ts", ".flv", ".mpg", ".mpeg", ".vob",
}
AUDIO_EXT = {
    ".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".aiff", ".aif", ".ape", ".alac", ".mka",
}
DOC_EXT = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp", ".rtf", ".txt",
    ".epub", ".fb2", ".mobi", ".azw3", ".djvu", ".csv", ".psd", ".ai", ".indd",
}
ARCHIVE_EXT = {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".iso", ".img", ".dmg", ".cab"}
MEDIA_EXT = IMAGE_EXT | VIDEO_EXT
KNOWN_EXT = IMAGE_EXT | VIDEO_EXT | AUDIO_EXT | DOC_EXT | ARCHIVE_EXT

# Типы файлов, которые можно выбрать в окне. "other" — всё, что не попало в остальные.
KINDS = {
    "photo": ("Фото", IMAGE_EXT),
    "video": ("Видео", VIDEO_EXT),
    "audio": ("Музыка", AUDIO_EXT),
    "docs": ("Документы и книги", DOC_EXT),
    "archives": ("Архивы и образы", ARCHIVE_EXT),
    "other": ("Остальные файлы", None),
}
DEFAULT_KINDS = {"photo", "video"}
KIND_WORD = {"photo": "фото", "video": "видео", "audio": "аудиофайлов", "docs": "документов",
             "archives": "архивов", "other": "файлов"}

FILE_ATTRIBUTE_SYSTEM = 0x4
FILE_ATTRIBUTE_REPARSE_POINT = 0x400     # junction, точка монтирования, символическая ссылка
# Файл есть только «в облаке»: OneDrive, телефон через «Связь с телефоном» (папка CrossDevice) и т. п.
# Чтение такого файла заставляет Windows скачать его — с интернета или с телефона по Wi-Fi.
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
CLOUD_ONLY = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS


def is_cloud_only(st):
    return bool(getattr(st, "st_file_attributes", 0) & CLOUD_ONLY)

# Служебные папки Windows: там чужие файлы, трогать их нельзя.
SKIP_DIRS = {"$recycle.bin", "system volume information", "$windows.~bt", "$windows.~ws"}

EDGE = 64 * 1024        # сколько байт с начала и с конца читать для быстрого отсева
CHUNK = 1024 * 1024


def kind_of(path):
    ext = os.path.splitext(path)[1].lower()
    for key, (_, exts) in KINDS.items():
        if exts is not None and ext in exts:
            return key
    return "other"


def ext_filter(kinds):
    """Функция «брать ли файл с таким расширением» для выбранных типов."""
    kinds = set(kinds)
    wanted = set()
    for k in kinds:
        exts = KINDS[k][1]
        if exts is not None:
            wanted |= exts
    take_other = "other" in kinds
    return lambda ext: ext in wanted or (take_other and ext not in KNOWN_EXT)


@dataclass(slots=True)          # slots: на миллионе файлов экономит сотни мегабайт памяти
class MediaFile:
    path: str
    size: int
    mtime: float

    @property
    def is_video(self):
        return os.path.splitext(self.path)[1].lower() in VIDEO_EXT

    @property
    def is_image(self):
        return os.path.splitext(self.path)[1].lower() in IMAGE_EXT


@dataclass
class ScanResult:
    groups: list = field(default_factory=list)   # список групп, в каждой >= 2 MediaFile
    files_seen: int = 0
    bytes_seen: int = 0
    cloud_skipped: int = 0                       # файлы только в облаке/на телефоне — не читали
    errors: list = field(default_factory=list)   # (путь, текст ошибки)
    cancelled: bool = False


class Cancelled(Exception):
    pass


def _check(cancel):
    if cancel is not None and cancel.is_set():
        raise Cancelled


def _is_link(path):
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT) or os.path.islink(path)


def collect(root, cancel=None, errors=None, kinds=DEFAULT_KINDS, on_file=None, cloud=None, take=None):
    """Нужные файлы во вложенных папках. Один и тот же файл (жёсткая ссылка) — один раз.

    cloud — список, куда складываются пропущенные облачные файлы (их не читаем вовсе).
    take(расширение) — свой отбор вместо типов kinds (так берёт файлы «Сжатие»).
    """
    seen_ids = set()
    out = []
    take = take or ext_filter(kinds)
    skip_system = "other" in kinds

    def onerror(exc):
        if errors is not None:
            errors.append((exc.filename or root, exc.strerror or str(exc)))

    for dirpath, dirnames, filenames in os.walk(root, onerror=onerror):
        _check(cancel)
        # Связки (junction) и точки монтирования ведут за пределы выбранной папки: по ним не идём,
        # иначе копия «где-то ещё» выглядела бы обычной подпапкой и попадала под удаление.
        dirnames[:] = [d for d in dirnames
                       if d.lower() not in SKIP_DIRS and not _is_link(os.path.join(dirpath, d))]
        for name in filenames:
            if not take(os.path.splitext(name)[1].lower()):
                continue
            path = os.path.join(dirpath, name)
            if _is_link(path):                   # ссылка на файл — не сам файл
                continue
            try:
                st = os.stat(path)
            except OSError as e:
                onerror(e)
                continue
            # Жёсткая ссылка — это не копия, а тот же файл под вторым именем:
            # «удалить копию» стёрло бы единственные данные.
            fid = (st.st_dev, st.st_ino) if st.st_ino else os.path.normcase(os.path.realpath(path))
            if fid in seen_ids:
                continue
            if is_cloud_only(st):
                if cloud is not None:
                    cloud.append(path)
                continue
            # Среди «остальных» попадаются системные файлы Windows — их не трогаем вовсе.
            if skip_system and getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_SYSTEM:
                continue
            seen_ids.add(fid)
            out.append(MediaFile(path, st.st_size, st.st_mtime))
            if on_file:
                on_file(len(out))
    return out


def _hash(path, edges_only, cancel, on_bytes):
    h = hashlib.blake2b(digest_size=32)
    with open(path, "rb") as f:
        if edges_only:
            h.update(f.read(EDGE))
            f.seek(-EDGE, os.SEEK_END)
            h.update(f.read(EDGE))
            on_bytes(2 * EDGE)
            return h.digest()
        while True:
            _check(cancel)
            block = f.read(CHUNK)
            if not block:
                break
            h.update(block)
            on_bytes(len(block))
    return h.digest()


def _regroup(groups, key_fn, errors, workers=1, init=None):
    """Разбить каждую группу по ключу, оставить только подгруппы из 2+ файлов.

    Файлы читаются в порядке путей: на жёстком диске соседние по пути файлы обычно лежат
    рядом, и головка меньше прыгает. workers > 1 — несколько потоков сразу (выигрыш на SSD).
    """
    items = sorted(((gi, mf) for gi, g in enumerate(groups) for mf in g), key=lambda t: t[1].path.lower())

    def safe(item):
        try:
            return key_fn(item[1]), None
        except OSError as e:
            return None, e

    if workers > 1:
        with ThreadPoolExecutor(workers, initializer=init) as ex:
            results = list(ex.map(safe, items))      # Cancelled из потока поднимется здесь
    else:
        results = [safe(it) for it in items]

    buckets = {}
    for (gi, mf), (key, err) in zip(items, results):
        if err is not None:
            errors.append((mf.path, err.strerror or str(err)))
            continue
        # gi — чтобы файлы разного размера с одинаковыми краями не попали на шаг 3 вместе.
        # На итог это не влияет (шаг 3 их всё равно разведёт), только экономит лишнее чтение.
        buckets.setdefault((gi, key), []).append(mf)
    return [b for b in buckets.values() if len(b) > 1]


STEPS = 3


LOAD_LEVELS = {
    # уровень: (фоновый приоритет, потоков чтения)
    "gentle": (True, 1),
    "normal": (False, 1),
    "fast": (False, 4),
}


def find_duplicates(root, progress=None, cancel=None, kinds=DEFAULT_KINDS, load="normal", on_group=None):
    """progress(шаг, название, сделано, всего, единица) — единица "files" или "bytes".

    Шаг 1 — обход папок (всего неизвестно, 0), шаг 2 — сравнение краёв файлов,
    шаг 3 — полное сравнение. Шагу, которому нечего делать, приходит 0 из 0.
    load — уровень нагрузки из LOAD_LEVELS.
    on_group(группа) — вызывается сразу, как только группа копий подтверждена (из потока поиска).
    """
    progress = progress or (lambda *a: None)
    gentle, workers = LOAD_LEVELS[load]
    init = background_mode if gentle else None
    if gentle:
        background_mode()
    lock = threading.Lock()
    res = ScanResult()
    try:
        progress(1, "Ищу файлы", 0, 0, "files")
        cloud = []
        files = collect(root, cancel, res.errors, kinds,
                        on_file=lambda n: progress(1, "Ищу файлы", n, 0, "files"), cloud=cloud)
        res.cloud_skipped = len(cloud)
        res.files_seen = len(files)
        res.bytes_seen = sum(m.size for m in files)

        by_size = {}
        for mf in files:
            if mf.size > 0:
                by_size.setdefault(mf.size, []).append(mf)
        groups = [g for g in by_size.values() if len(g) > 1]

        # Быстрый отсев: начало и конец файла. Маленькие файлы этот шаг не экономит.
        big = [g for g in groups if g[0].size > 2 * EDGE]
        small = [g for g in groups if g[0].size <= 2 * EDGE]
        total = sum(len(g) for g in big)
        done = [0]
        progress(2, "Сравниваю начала и концы файлов", 0, total, "files")

        def edge_key(mf):
            _check(cancel)
            k = _hash(mf.path, True, cancel, lambda n: None)
            with lock:
                done[0] += 1
                progress(2, "Сравниваю начала и концы файлов", done[0], total, "files")
            return k

        groups = small + _regroup(big, edge_key, res.errors, workers, init)

        # Полное сравнение содержимого — только тем, кто совпал по размеру и краям.
        # Группа за группой, самые выгодные (больше всего места) — первыми: каждая подтверждённая
        # группа сразу уходит в on_group, и её можно смотреть и удалять, не дожидаясь конца поиска.
        total = sum(mf.size for g in groups for mf in g)
        done = [0]
        progress(3, "Сверяю содержимое целиком", 0, total, "bytes")

        def on_bytes(n):
            with lock:
                done[0] += n
                progress(3, "Сверяю содержимое целиком", done[0], total, "bytes")

        def confirm(group):
            if workers > 1:
                background_mode() if gentle else None
            buckets = {}
            for mf in sorted(group, key=lambda m: m.path.lower()):
                try:
                    key = _hash(mf.path, False, cancel, on_bytes)
                except OSError as e:
                    res.errors.append((mf.path, e.strerror or str(e)))
                    continue
                buckets.setdefault(key, []).append(mf)
            return [b for b in buckets.values() if len(b) > 1]

        def found(sub):
            sort_keep_first(sub, "oldest")
            res.groups.append(sub)
            if on_group:
                on_group(sub)

        groups.sort(key=lambda g: -g[0].size * (len(g) - 1))
        if workers > 1:
            ex = ThreadPoolExecutor(workers)
            try:
                for fut in as_completed([ex.submit(confirm, g) for g in groups]):
                    for sub in fut.result():          # Cancelled из потока поднимется здесь
                        found(sub)
            finally:
                ex.shutdown(wait=True, cancel_futures=True)
        else:
            for g in groups:
                for sub in confirm(g):
                    found(sub)
    except Cancelled:
        res.cancelled = True
        return res

    res.groups.sort(key=lambda g: -g[0].size * (len(g) - 1))   # сначала то, что освободит больше места
    return res


KEEP_RULES = {
    "oldest": "самый старый файл",
    "newest": "самый новый файл",
    "shortest": "файл с самым коротким путём",
}


def sort_keep_first(group, rule):
    """Переставить группу так, чтобы первым шёл файл, который правило оставляет."""
    if rule == "oldest":
        group.sort(key=lambda m: (m.mtime, len(m.path), m.path.lower()))
    elif rule == "newest":
        group.sort(key=lambda m: (-m.mtime, len(m.path), m.path.lower()))
    elif rule == "shortest":
        group.sort(key=lambda m: (len(m.path), m.mtime, m.path.lower()))
    else:
        raise ValueError(rule)
    return group


def check_before_delete(groups, marked):
    """Что можно удалять прямо сейчас.

    marked — множество путей. Возвращает (можно_удалить, проблемы).
    Правила: в каждой группе остаётся хотя бы один файл, и он на месте;
    отмеченный файл не менялся с момента поиска.
    """
    ok, problems = [], []
    for group in groups:
        to_del = [m for m in group if m.path in marked]
        if not to_del:
            continue
        keep = [m for m in group if m.path not in marked]
        if not keep:
            problems.append((group[0].path, "в группе отмечены все копии — хоть одну надо оставить"))
            continue
        if not any(_unchanged(m) for m in keep):
            problems.append((keep[0].path, "оставляемый файл пропал или изменился — группу пропускаю"))
            continue
        for m in to_del:
            if _unchanged(m):
                ok.append(m)
            else:
                problems.append((m.path, "файл пропал или изменился после поиска"))
    return ok, problems


def _unchanged(mf):
    try:
        st = os.stat(mf.path)
    except OSError:
        return False
    return st.st_size == mf.size and st.st_mtime == mf.mtime


# --- Удаление в Корзину через SHFileOperationW (без сторонних библиотек) ---

FO_DELETE = 0x0003
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400
FOF_WANTNUKEWARNING = 0x4000   # спросит, если Корзины нет (флешка, сеть) и удаление было бы насовсем


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def drive_of(path):
    return os.path.splitdrive(os.path.abspath(path))[0] or os.path.abspath(path)[:3]


def has_recycle_bin(drive):
    """Есть ли Корзина на диске: у съёмных (флешка, карта) и сетевых дисков её нет — удаление там навсегда."""
    try:
        kind = ctypes.windll.kernel32.GetDriveTypeW(drive.rstrip("\\") + "\\")
    except Exception:
        return True
    return kind not in (2, 4)        # DRIVE_REMOVABLE, DRIVE_REMOTE


def to_recycle_bin(paths, batch=100, hwnd=None, progress=None):
    """Отправить файлы в Корзину. Возвращает (удалённые, оставшиеся) — точные абсолютные пути."""
    removed, left = [], []
    for i in range(0, len(paths), batch):
        part = [os.path.abspath(p) for p in paths[i:i + batch]]
        op = _SHFILEOPSTRUCTW()
        op.hwnd = hwnd
        op.wFunc = FO_DELETE
        op.pFrom = "\0".join(part) + "\0\0"
        op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI | FOF_WANTNUKEWARNING
        ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        # Итог проверяем по диску, а не по коду возврата: так видно каждый файл.
        for p in part:
            (left if os.path.exists(p) else removed).append(p)
        if progress:
            progress(len(removed) + len(left))
    return removed, left


THREAD_MODE_BACKGROUND_BEGIN = 0x00010000


def background_mode():
    """Понизить приоритет текущего потока по процессору и диску, чтобы поиск не мешал другим программам.

    Когда диск свободен, скорость почти не меняется; когда занят — поиск уступает.
    """
    try:
        k = ctypes.windll.kernel32
        return bool(k.SetThreadPriority(k.GetCurrentThread(), THREAD_MODE_BACKGROUND_BEGIN))
    except Exception:
        return False


def human_time(sec):
    sec = int(round(sec))
    if sec < 60:
        return tr("{s} с", s=sec)
    m, s = divmod(sec, 60)
    if m < 60:
        return tr("{m} мин {s} с", m=m, s=f"{s:02d}") if m < 10 else tr("{m} мин", m=m)
    h, m = divmod(m, 60)
    return tr("{h} ч {m} мин", h=h, m=f"{m:02d}")


def human_size(n):
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if n < 1024 or unit == "ТБ":
            s = decimal(n) if unit != "Б" else str(int(n))
            return s + " " + tr(unit)
        n /= 1024
