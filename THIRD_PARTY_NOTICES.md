# Сторонние программы в Duplio

Duplio распространяется по лицензии MIT (см. `LICENSE`). Для вкладки «Сжатие» вместе с ним ставятся
отдельные программы — без изменений, как их выпустили авторы. Их лицензии лежат рядом с ними
в папке `third_party` установленной программы. Версии и контрольные суммы — в `tools/fetch_tools.py`.

| Программа | Версия | Зачем | Лицензия | Откуда |
|---|---|---|---|---|
| jpegtran (libjpeg-turbo) | 3.2.0 | JPEG строго без потерь | IJG, BSD-3-Clause, zlib | https://github.com/libjpeg-turbo/libjpeg-turbo/releases/tag/3.2.0 |
| oxipng | 10.2.1 | PNG без потерь | MIT | https://github.com/oxipng/oxipng/releases/tag/v10.2.1 |
| FFmpeg (сборка BtbN, LGPL) | n8.1.3-14-g330caae0c1 | видео в AV1, проверка SSIM, кадры для сравнения | LGPL 2.1 или новее | https://github.com/BtbN/FFmpeg-Builds/releases/tag/autobuild-2026-10-05-13-07 |

**FFmpeg.** Сборка без GPL-частей (вариант `lgpl-shared`): программы `ffmpeg.exe` и `ffprobe.exe` и их
библиотеки `av*.dll`, `sw*.dll`. Duplio запускает `ffmpeg.exe` как отдельную программу и с её кодом не
связан. Исходный код этой версии FFmpeg — https://github.com/FFmpeg/FFmpeg/tree/330caae0c1, сценарии
сборки — https://github.com/BtbN/FFmpeg-Builds. Библиотеки можно заменить своей сборкой той же версии,
положив их в `third_party\ffmpeg`.

В программу также входят Python, Qt for Python (PySide6, LGPL), Pillow (MIT-CMU) и NumPy (BSD) — их
лицензии собраны в папке `_internal` установленной программы.

---

# Third-party software in Duplio

Duplio is MIT-licensed (see `LICENSE`). For the Compression tab it ships the separate, unmodified programs
listed above — jpegtran (libjpeg-turbo 3.2.0: IJG, BSD-3-Clause, zlib), oxipng 10.2.1 (MIT) and an LGPL build
of FFmpeg n8.1.3 by BtbN (LGPL 2.1 or later). Their licenses are in the `third_party` folder of the installed
app. Duplio runs `ffmpeg.exe` as a separate process and does not link to it. FFmpeg source for this version:
https://github.com/FFmpeg/FFmpeg/tree/330caae0c1; build scripts: https://github.com/BtbN/FFmpeg-Builds.
