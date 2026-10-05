"""Журнал работы: что программа делала и какие ошибки случились — чтобы разобраться, если что-то пошло не так.

Лежит в %LOCALAPPDATA%\\Duplio\\logs, никуда не отправляется. Размер ограничен: duplio.log до 1 МБ
и два предыдущих куска, всего до ~3 МБ — старые записи вытесняются новыми.
"""

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

log = logging.getLogger("duplio")
_on_crash = []           # окно подписывается, чтобы показать «что-то пошло не так»


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


def on_crash(fn):
    _on_crash.append(fn)


def total_size():
    try:
        return sum(os.path.getsize(os.path.join(DIR, f)) for f in os.listdir(DIR))
    except OSError:
        return 0
