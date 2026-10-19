"""Журнал работы: что программа делала и какие ошибки случились — чтобы разобраться, если что-то пошло не так.

Лежит в %LOCALAPPDATA%\\Duplio\\logs, никуда не отправляется. Размер ограничен: duplio.log до 1 МБ
и два предыдущих куска, всего до ~3 МБ — старые записи вытесняются новыми. Вылет внутри библиотеки на C
(нарушение доступа к памяти) Python не перехватывает — его стеки пишет faulthandler в crash.log, а при следующем
запуске они переносятся в журнал.
"""

import faulthandler
import logging
import logging.handlers
import os
import platform
import sys
import threading

DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Duplio", "logs")
FILE = "duplio.log"
MAX_BYTES = 1_000_000
BACKUPS = 2
CRASH_FILE = "crash.log"
# признаки настоящего вылета; исключения Windows, которые программа пережила (COM и т. п.), faulthandler тоже пишет
FATAL = ("access violation", "stack overflow", "Fatal Python error", "Segmentation fault")

log = logging.getLogger("duplio")
_on_crash = []           # окно подписывается, чтобы показать «что-то пошло не так»
_crash_file = None       # открыт всё время работы: faulthandler пишет в него при вылете сам, без Python


def path():
    return os.path.join(DIR, FILE)


def setup(version="", folder=None):
    """Включить запись в файл и перехват необработанных ошибок (в главном потоке, в потоках, в Qt)."""
    global DIR
    if folder:
        DIR = folder
    for h in list(log.handlers):
        log.removeHandler(h)
        h.close()
    try:
        os.makedirs(DIR, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(path(), maxBytes=MAX_BYTES, backupCount=BACKUPS,
                                                       encoding="utf-8")
    except OSError:
        return False
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(threadName)s: %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    log.info("—— запуск Duplio %s · Python %s · Windows %s", version, platform.python_version(),
             platform.version())
    _crash_trap()

    def excepthook(kind, value, tb):
        log.error("Необработанная ошибка", exc_info=(kind, value, tb))
        for fn in list(_on_crash):
            try:
                fn(value)
            except Exception:
                pass
        sys.__excepthook__(kind, value, tb)

    def thread_hook(args):
        log.error("Необработанная ошибка в потоке %s", args.thread.name if args.thread else "?",
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = excepthook
    threading.excepthook = thread_hook
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler

        def qt_messages(kind, _ctx, msg):
            if kind in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
                log.warning("Qt: %s", msg)
        qInstallMessageHandler(qt_messages)
    except Exception:
        pass
    return True


def _crash_trap():
    """Перенести в журнал стеки прошлого вылета (если был) и ловить следующий.

    Нарушение доступа к памяти внутри python314.dll или библиотеки на C убивает процесс сразу: ни excepthook,
    ни запись в журнал уже не срабатывают — журнал просто обрывается. faulthandler пишет стеки всех потоков
    в отдельный открытый файл средствами ОС.
    """
    global _crash_file
    stop_crash_trap()
    where = os.path.join(DIR, CRASH_FILE)
    try:
        with open(where, encoding="utf-8", errors="replace") as f:
            old = f.read().strip()
    except OSError:
        old = ""
    if old:
        fatal = any(k in old for k in FATAL)
        log.log(logging.ERROR if fatal else logging.WARNING, "%s\n%s",
                "Прошлый запуск упал внутри библиотеки (не в Python) — где были потоки:" if fatal else
                "Сведения faulthandler с прошлого запуска:", old)
    try:
        _crash_file = open(where, "w", encoding="utf-8")
        faulthandler.enable(_crash_file, all_threads=True)
    except (OSError, RuntimeError):
        _crash_file = None


def stop_crash_trap():
    global _crash_file
    if _crash_file is not None:
        faulthandler.disable()
        _crash_file.close()
        _crash_file = None


def on_crash(fn):
    _on_crash.append(fn)


def total_size():
    try:
        return sum(os.path.getsize(os.path.join(DIR, f)) for f in os.listdir(DIR))
    except OSError:
        return 0
