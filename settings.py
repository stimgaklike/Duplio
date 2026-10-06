"""Настройки программы — один маленький файл %APPDATA%\\Duplio\\settings.json.

Ещё программа пишет журнал (%LOCALAPPDATA%\\Duplio\\logs) и, пока готовит сжатие, — сжатые копии
в %LOCALAPPDATA%\\Duplio\\work (папка очищается при каждой подготовке и при выходе).
"""

import json
import os

DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Duplio")
PATH = os.path.join(DIR, "settings.json")
# До названия Duplio программа звалась DupFinder — её настройки подхватываем один раз.
OLD_PATH = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "DupFinder", "settings.json")

DEFAULTS = {
    "load": "gentle",            # gentle / normal / fast — см. dupcore.LOAD_LEVELS
    "theme": "system",           # system / light / dark
    "kinds": ["photo", "video"],
    "keep_rule": "oldest",
    "last_folder": "",
    "close_action": "ask",       # крестик: ask — спросить, tray — свернуть в трей, quit — закрыть программу
    "tray_hint_shown": False,    # подсказку «я в трее» показываем один раз
    "lang": "auto",              # auto / ru / en
    "check_updates": True,       # проверять обновления при запуске (не чаще раза в сутки)
    "last_update_check": 0,
    "compress_mode": "lossless",  # lossless — строго без потерь, visual — без видимых потерь
    "compress_kinds": ["photo", "video"],
    "compress_folder": "",
    "meta_folder": "",
    "meta_preset": "all",        # all — всё, place — только место, custom — свой набор галочками
    "meta_groups": ["place", "camera", "time", "author", "thumb", "other"],
    "meta_output": "replace",    # replace — заменить оригиналы, copies — очищенные копии в папку
    "meta_copies": "",
}
META_GROUPS = {"place", "camera", "time", "author", "thumb", "other"}


def load():
    data = dict(DEFAULTS)
    path = PATH if os.path.exists(PATH) or not os.path.exists(OLD_PATH) else OLD_PATH
    try:
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        data.update({k: v for k, v in saved.items() if k in DEFAULTS})
        if "close_action" not in saved and saved.get("close_to_tray") is False:   # настройка версии 1.0.0
            data["close_action"] = "quit"
    except (OSError, ValueError, AttributeError):
        pass
    return sanitize(data)


ALLOWED = {
    "load": {"gentle", "normal", "fast"},
    "theme": {"system", "light", "dark"},
    "keep_rule": {"oldest", "newest", "shortest"},
    "lang": {"auto", "ru", "en"},
    "close_action": {"ask", "tray", "quit"},
    "compress_mode": {"lossless", "visual"},
    "meta_preset": {"all", "place", "custom"},
    "meta_output": {"replace", "copies"},
}
KINDS = {"photo", "video", "audio", "docs", "archives", "other"}


def sanitize(data):
    """Испорченный или чужой файл настроек не должен ронять программу: всё неизвестное — по умолчанию."""
    for key, ok in ALLOWED.items():
        if data.get(key) not in ok:
            data[key] = DEFAULTS[key]
    kinds = data.get("kinds")
    if not isinstance(kinds, list) or not set(kinds) <= KINDS:
        data["kinds"] = list(DEFAULTS["kinds"])
    for key in ("tray_hint_shown", "check_updates"):
        if not isinstance(data.get(key), bool):
            data[key] = DEFAULTS[key]
    ck = data.get("compress_kinds")
    if not isinstance(ck, list) or not set(ck) <= {"photo", "video"}:
        data["compress_kinds"] = list(DEFAULTS["compress_kinds"])
    mg = data.get("meta_groups")
    if not isinstance(mg, list) or not set(mg) <= META_GROUPS:
        data["meta_groups"] = list(DEFAULTS["meta_groups"])
    for key in ("last_folder", "compress_folder", "meta_folder", "meta_copies"):
        if not isinstance(data.get(key), str):
            data[key] = ""
    if not isinstance(data.get("last_update_check"), (int, float)):
        data["last_update_check"] = 0
    return data


def save(data):
    """Пишем через временный файл: если компьютер выключится посреди записи, старые настройки уцелеют."""
    try:
        os.makedirs(DIR, exist_ok=True)
        tmp = PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({k: data[k] for k in DEFAULTS if k in data}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, PATH)
    except OSError:
        pass
