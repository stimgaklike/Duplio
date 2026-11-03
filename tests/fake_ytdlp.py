"""Поддельный yt-dlp для test_dlcore: что делать — по ссылке. Ход, готовый файл и ошибки — в том же виде,
что у настоящего с ключами dlcore (строки MARK / DONE, «ERROR: …»).

Как настоящий, вынимая звук (-x), берёт за исходник уже лежащий в папке ролик с тем же именем и потом
удаляет его — эту беду dlcore.download обходит рабочей папкой для звука.
"""

import json
import os
import subprocess
import sys
import time

MARK, DONE = "@@duplio ", "@@done "
args = sys.argv[1:]
if "--version" in args:
    print("2099.01.01")
    sys.exit(0)
url = args[-1]
key = url.rstrip("/").rsplit("/", 1)[-1]


def opt(name, default=None):
    vals = [args[i + 1] for i, a in enumerate(args[:-1]) if a == name]
    return vals or ([default] if default is not None else [])


if "-J" in args:
    if key == "drm":
        print("ERROR: [fake] drm: This video is DRM protected")
        sys.exit(1)
    if key == "playlist":
        print(json.dumps({"_type": "playlist", "title": "Плейлист", "entries": [
            {"url": "https://example.com/v/ok", "title": "Первое"}, {"url": "abc123", "title": "Второе"}]}))
    else:
        print(json.dumps({"_type": "video", "title": "Клип " + key, "webpage_url": url}, ensure_ascii=False))
    sys.exit(0)

if key == "js":
    print("WARNING: [youtube] No supported JavaScript runtime could be found. YouTube extraction without a JS "
          "runtime has been deprecated")
    print("ERROR: [youtube] js: Requested format is not available")
    sys.exit(1)
if key == "forbid_always" or (key == "forbid" and "--impersonate" not in args):
    print("ERROR: [generic] forbid: Unable to download webpage: HTTP Error 403: Forbidden")
    sys.exit(1)
if key == "unsupported":
    print("ERROR: Unsupported URL: " + url)
    sys.exit(1)

home = next(p for p in opt("-P") if not p.startswith("temp:"))
audio = "-x" in args
title = "Клип " + key
base = os.path.join(home, f"{title} [{key}]")
video = base + ".mp4"
final = base + "." + opt("--audio-format", "mp3")[0] if audio else video
if key == "slow":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    with open(os.environ["FAKE_CHILD_PID"], "w") as f:
        f.write(str(child.pid))
    print(f"{MARK}downloading|100|1000|NA|50.5|18|{title}", flush=True)
    time.sleep(60)
had = os.path.exists(video if audio else final)
if not had:
    for done in (0, 400, 1000):
        print(f"{MARK}downloading|{done}|1000|NA|200.0|{(1000 - done) // 200}|{title}", flush=True)
    with open(video, "wb") as f:
        f.write(b"v" * 1000)
print(f"{MARK}finished|1000|1000|NA|NA|NA|{title}", flush=True)
if audio:
    with open(final, "wb") as f:
        f.write(b"a" * 300)
    os.remove(video)                    # как настоящий yt-dlp без -k: исходник после -x удаляется
print(DONE + final, flush=True)
