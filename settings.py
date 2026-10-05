"""Настройки программы — один маленький файл %APPDATA%\\Duplio\\settings.json. Других файлов программа не пишет."""

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
    "close_to_tray": True,       # крестик сворачивает в трей (значок у часов), а не закрывает программу
    "tray_hint_shown": False,    # подсказку «я в трее» показываем один раз
    "lang": "auto",              # auto / ru / en
    "check_updates": True,       # проверять обновления при запуске (не чаще раза в сутки)
    "last_update_check": 0,
}


def load():
    data = dict(DEFAULTS)
    path = PATH if os.path.exists(PATH) or not os.path.exists(OLD_PATH) else OLD_PATH
    try:
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        data.update({k: v for k, v in saved.items() if k in DEFAULTS})
    except (OSError, ValueError, AttributeError):
        pass
    return sanitize(data)


ALLOWED = {
    "load": {"gentle", "normal", "fast"},
    "theme": {"system", "light", "dark"},
    "keep_rule": {"oldest", "newest", "shortest"},
    "lang": {"auto", "ru", "en"},
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
    for key in ("close_to_tray", "tray_hint_shown", "check_updates"):
        if not isinstance(data.get(key), bool):
            data[key] = DEFAULTS[key]
    if not isinstance(data.get("last_folder"), str):
        data["last_folder"] = ""
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
