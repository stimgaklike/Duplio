"""Вкладка «Скачать» целиком: разрешение скачать yt-dlp, очередь, плейлист, ход, «уже есть», причины,
«Только звук», передача скачанного в «Сжатие», окно минимального размера.

Запуск: python tests/e2e_download.py [папка_для_снимков] [light|dark]
Окно появится на экране. yt-dlp подменён поддельным (fake_ytdlp.py) — сеть не нужна. Диалоги подменены
автоответом «да». Настройки, рабочие папки и папка загрузок — временные.
"""

import atexit
import os
import shutil
import sys
import tempfile
import time
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import settings  # noqa: E402

tmp_cfg = tempfile.mkdtemp(prefix="dup_cfg_")
atexit.register(shutil.rmtree, tmp_cfg, True)          # убрать и при обрыве прогона
settings.DIR, settings.PATH = tmp_cfg, os.path.join(tmp_cfg, "settings.json")

from PySide6.QtGui import QColor, QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton  # noqa: E402

qapp = QApplication(sys.argv)

import app  # noqa: E402
import e2e_isolate  # noqa: E402,F401  — рабочие папки всех вкладок временные
import dlcore  # noqa: E402
import download_page  # noqa: E402
import ui_util  # noqa: E402

shots = sys.argv[1] if len(sys.argv) > 1 else tempfile.gettempdir()
mode = sys.argv[2] if len(sys.argv) > 2 else "system"
root = tempfile.mkdtemp(prefix="dup_dl_e2e_")
atexit.register(shutil.rmtree, root, True)
dlcore.TOOLS = os.path.join(root, "tools")             # yt-dlp «ещё не скачан»
FAKE = [sys.executable, os.path.join(os.path.dirname(__file__), "fake_ytdlp.py")]
installed = []


def fake_refresh(progress=None, cancel=None):
    progress and progress(10, 20)
    dlcore.COMMAND = FAKE
    installed.append(True)
    return "2099.01.01"


dlcore.refresh = fake_refresh
answers = []
ui_util.ask_yes_no = lambda parent, text, **k: answers.append(("yesno", text)) or True
ui_util.info = lambda parent, text: answers.append(("info", text))
ui_util.warn = lambda parent, text: answers.append(("warn", text))
slot_errors = []
_hook = sys.excepthook
sys.excepthook = lambda *exc: (slot_errors.append(exc), _hook(*exc))

cfg = settings.load()
cfg["theme"] = mode
cfg["dl_folder"] = os.path.join(root, "Загрузки")
w = app.MainWindow(cfg)
w.show()
d = w.download
w.tabs.setCurrentWidget(d)
fails = []


def check(cond, what):
    print(("OK   " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


def pump(sec=0.3):
    t = time.time()
    while time.time() - t < sec:
        qapp.processEvents()
        time.sleep(0.01)


def wait(cond, sec=60):
    t = time.time()
    while not cond() and time.time() - t < sec:
        pump(0.05)
    return cond()


def shot(name):
    pump(0.4)
    w.grab().save(os.path.join(shots, name))


def cell_ink(row, col):
    """Самый частый цвет точек букв в ячейке (края букв сглажены — берём частый, а не любой)."""
    rect = d.tree.visualItemRect(row)
    x0 = d.tree.header().sectionViewportPosition(col)
    img = d.tree.viewport().grab().toImage()
    dpr = img.devicePixelRatio()
    bg = img.pixelColor(int((x0 + 2) * dpr), int((rect.top() + 2) * dpr))
    inks = Counter()
    for y in range(int(rect.top() * dpr), int(rect.bottom() * dpr)):
        for x in range(int((x0 + 4) * dpr), int((x0 + d.tree.columnWidth(col) - 4) * dpr)):
            px = img.pixelColor(x, y)
            if abs(px.lightness() - bg.lightness()) > 60:
                inks[px.name()] += 1
    return inks.most_common(1)[0][0] if inks else None


def near(a, b, tol=40):
    qa, qb = QColor(a), QColor(b)
    return max(abs(qa.red() - qb.red()), abs(qa.green() - qb.green()), abs(qa.blue() - qb.blue())) <= tol


def rows():
    return [d.tree.topLevelItem(i) for i in range(d.tree.topLevelItemCount())]


def layout_problems():
    bad = []
    for wd in d.findChildren(QLabel):
        if wd.isVisible() and wd.wordWrap() and wd.text() and wd.height() + 1 < wd.heightForWidth(wd.width()):
            bad.append(f"перенос «{wd.text()[:25]}» {wd.height()} из {wd.heightForWidth(wd.width())}")
    for wd in d.findChildren(QPushButton) + d.findChildren(QLineEdit):
        if not wd.isVisible():
            continue
        hint = wd.sizeHint() if isinstance(wd, QPushButton) else wd.minimumSizeHint()
        name = wd.text()[:25] if hasattr(wd, "text") else type(wd).__name__
        if isinstance(wd, QPushButton) and wd.text() and wd.width() + 1 < hint.width():
            bad.append(f"кнопка «{name}» {wd.width()} из {hint.width()}")
        if wd.height() + 1 < hint.height():
            bad.append(f"{type(wd).__name__} «{name}» сплющен: {wd.height()} из {hint.height()}")
    return sorted(set(bad))


pump(0.5)
tabs = [w.tabs.tabText(i) for i in range(w.tabs.count())]
check(tabs[-2:] == ["Скачать", "Настройки"], f"вкладка «Скачать» перед «Настройками» ({tabs})")
check(d.stack.currentIndex() == 0 and "появятся" in d.empty.text(), "пустой список — подсказка, что тут будет")
check(not d.btn_start.isEnabled() and d.btn_start.property(ui_util.WHY), "«Скачать» без ссылки недоступна и "
      "объясняет почему")
check(not d.btn_stop.isEnabled() and d.btn_stop.property(ui_util.WHY), "«Остановить» без загрузок объясняет почему")
check(d.quality.isVisible() and not d.audio.isVisible(), "у видео — качество, формата звука не видно")
img = d.links.viewport().grab().toImage()
field = Counter(img.pixelColor(x, y).name() for y in range(2, img.height() - 2, 3)
                for x in range(img.width() - 40, img.width() - 4, 3)).most_common(1)[0][0]
check(near(field, w.colors["surface2"], 6), f"поле ссылок — цвета полей темы ({field}, а не белое; "
      f"тема {w.colors['surface2']})")
shot("qt_dl_empty.png")


def ink_rows(widget):
    """Строки точек с буквами (по экрану, в пикселях окна): (первая, последняя) или None."""
    img = widget.grab().toImage()
    dpr = img.devicePixelRatio()
    bg = Counter(img.pixelColor(x, img.height() // 2).name() for x in range(0, img.width(), 2)).most_common(1)[0][0]
    rows_ = [y for y in range(img.height())
             if any(abs(img.pixelColor(x, y).lightness() - QColor(bg).lightness()) > 50
                    for x in range(8, int(min(img.width(), 400 * dpr)), 2))]
    top = widget.mapTo(w, widget.rect().topLeft()).y()
    return (top + rows_[0] / dpr, top + rows_[-1] / dpr) if rows_ else None


# поле ссылок: одна строка, растёт до четырёх, дальше — прокрутка
ls = d.links.fontMetrics().lineSpacing()
h1 = d.links.height()
check(d.links.lines() == 1 and not d.links.verticalScrollBar().isVisible(), f"пустое поле — одна строка ({h1} px)")
check(abs(h1 - d.folder.height()) <= 1, f"в одну строку поле ссылок как поле папки ({h1} и {d.folder.height()})")
label_ink, field_ink = ink_rows(d.links_label), ink_rows(d.links.viewport())
check(label_ink and field_ink and abs(label_ink[0] - field_ink[0]) <= 2,
      f"«Ссылки» на одной линии с текстом поля (верх букв {label_ink}, {field_ink})")
heights = {}
for n in (2, 3, 4, 6):
    d.links.setPlainText("\n".join(f"https://example.com/v/{i}" for i in range(n)))
    d.links.moveCursor(d.links.textCursor().MoveOperation.End)     # курсор в конце — как после вставки
    pump(0.15)
    heights[n] = d.links.height()
    if n <= 4:
        first = d.links.firstVisibleBlock().blockNumber()
        check(first == 0 and not d.links.verticalScrollBar().isVisible(),
              f"{n} строки видны целиком, первая не уехала (первая видимая — {first})")
check([heights[n] - h1 for n in (2, 3, 4)] == [ls, 2 * ls, 3 * ls],
      f"растёт ровно на строку: {[heights[n] - h1 for n in (2, 3, 4)]} при строке {ls}")
check(heights[6] == heights[4] and d.links.verticalScrollBar().isVisible(),
      f"после четырёх строк — не растёт, а прокручивается ({heights[6]} = {heights[4]})")
d.links.setPlainText("https://example.com/" + "очень-длинная-ссылка-" * 12)
pump(0.15)
check(d.links.lines() >= 2 and d.links.height() == h1 + (min(d.links.lines(), 4) - 1) * ls,
      f"длинная ссылка переносится — поле растёт под неё ({d.links.lines()} строк)")
shot("qt_dl_links_long.png")
d.links.clear()
pump(0.15)
check(d.links.height() == h1, "очистили — снова одна строка")

# папка: выбранная остаётся и после перезапуска
other = os.path.join(root, "Видео с сайтов")
d.folder.setText(other)
d.folder.editingFinished.emit()
settings.save(cfg)
again = download_page.DownloadPage(settings.load(), w.colors)
check(again.folder.text() == other, f"папка после «перезапуска» та же ({again.folder.text()})")
again.deleteLater()
d.folder.setText(cfg["dl_folder"] if False else os.path.join(root, "Загрузки"))
d.folder.editingFinished.emit()

# «Вставить»: в буфере текст со ссылками вперемешку
QGuiApplication.clipboard().setText("Смотри https://example.com/v/ok и https://example.com/v/playlist")
d.paste()
check(d.links.toPlainText() == "https://example.com/v/ok\nhttps://example.com/v/playlist",
      f"«Вставить» берёт из буфера только ссылки ({d.links.toPlainText()!r})")
check(d.btn_start.isEnabled(), "со ссылкой «Скачать» доступна")
d.links.appendPlainText("https://example.com/v/forbid_always\nhttps://example.com/v/drm")
d.start()
check(any("yt-dlp" in t and "github.com/yt-dlp" in t for k, t in answers), "перед первым скачиванием спрошено "
      "разрешение скачать yt-dlp, и сказано откуда")
check(cfg.get("dl_allowed") is True, "разрешение запомнено")
check(d.busy and d.btn_start.text() == "Добавить в очередь", "во время загрузки кнопка добавляет в очередь")
check(wait(lambda: not d.busy, 60), "очередь закончилась")
check(installed == [True], "yt-dlp «скачан» один раз")
texts = [(r.text(0), r.text(3)) for r in rows()]
print("   строки:", texts)
check(len(texts) == 5, f"плейлист раскрылся в две строки — всего 5 ({len(texts)})")
check(texts[0] == ("Клип ok", "Готово"), "обычное видео — «Готово», название с сайта")
check([t[0] for t in texts[1:3]] == ["Клип ok", "Клип playlist"] and texts[1][1] == "Уже есть в папке",
      f"видео из плейлиста: первое уже скачано («Уже есть в папке»), второе скачалось ({texts[1:3]})")
check(texts[3][1] == "Сайт не отдал видео. Проверь, что оно открывается в браузере.", "403 — понятная причина")
check(texts[4][1].startswith("Видео защищено от копирования"), "DRM — не качаем и говорим почему")
check(near(cell_ink(rows()[0], 3), w.colors["keep"]), f"«Готово» — зелёным ({cell_ink(rows()[0], 3)})")
check(near(cell_ink(rows()[3], 3), w.colors["danger"]), f"причина — красным ({cell_ink(rows()[3], 3)})")
check("Скачано: 2" in d.step_text.text() and "не получилось: 2" in d.step_text.text(),
      f"итог: сколько скачано и сколько нет ({d.step_text.text()})")
files = sorted(os.listdir(cfg["dl_folder"]))
check(files == ["Клип ok [ok].mp4", "Клип playlist [playlist].mp4"], f"в папке ровно скачанное ({files})")
shot("qt_dl_done.png")

# без выбора кнопки «Сжать» и т. п. недоступны и объясняют; с выбором — отдают файл во вкладку
check(not d.btn_to["compress"].isEnabled() and d.btn_to["compress"].property(ui_util.WHY),
      "«Сжать» без выбранного файла недоступна и объясняет почему")
rows()[0].setSelected(True)
rows()[3].setSelected(True)                     # не скачанное — не уходит
pump(0.1)
check(d.btn_to["compress"].isEnabled(), "выбран скачанный файл — «Сжать» доступна")
d.btn_to["compress"].click()
pump(0.3)
check(w.tabs.currentWidget() is w.compress, "«Сжать» открывает вкладку «Сжатие»")
check(list(w.compress.drop_files or []) == [os.path.join(cfg["dl_folder"], "Клип ok [ok].mp4")],
      f"туда ушёл только скачанный файл ({w.compress.drop_files})")
w.tabs.setCurrentWidget(d)

# «Только звук»: качество кадра прячется, видео рядом не пропадает
d.kind_btns["audio"].click()
pump(0.1)
check(not d.quality.isVisible() and d.audio.isVisible(), "у звука — формат, качества кадра не видно")
d.links.setPlainText("https://example.com/v/ok")
d.start()
check(wait(lambda: not d.busy, 60), "звук скачался")
check(rows()[-1].text(1) == "MP3" and rows()[-1].text(3) == "Готово", f"строка звука ({rows()[-1].text(1)}, "
      f"{rows()[-1].text(3)})")
files = sorted(os.listdir(cfg["dl_folder"]))
check("Клип ok [ok].mp4" in files and "Клип ok [ok].mp3" in files, f"видео осталось рядом со звуком ({files})")
d.kind_btns["video"].click()

# остановка: строка «Остановлено», процесс не висит
os.environ["FAKE_CHILD_PID"] = os.path.join(root, "child.pid")
d.links.setPlainText("https://example.com/v/slow\nhttps://example.com/v/ok")
d.start()
check(wait(lambda: any(r.text(3).startswith("10 %") for r in rows()), 30), "ход видно в строке («10 % · …»)")
slow = next(r for r in rows() if r.text(3).startswith("10 %"))
check("осталось" in slow.text(3) and "/с" in slow.text(3), f"в ходе — скорость и сколько осталось ({slow.text(3)})")
d.stop()
check(wait(lambda: not d.busy, 30), "«Остановить» останавливает")
check(rows()[-2].text(3) == "Остановлено" and rows()[-1].text(3) == "Остановлено",
      f"и текущее, и ждавшее — «Остановлено» ({rows()[-2].text(3)}, {rows()[-1].text(3)})")
d.retry([rows()[-1].data(0, download_page.ITEM_ROLE)])
check(wait(lambda: not d.busy and rows()[-1].text(3) == "Уже есть в папке", 30), "«Скачать ещё раз» — снова в работу")

# «Очистить список» — уходит всё, файлы остаются
d.clear_list()
check(d.tree.topLevelItemCount() == 0 and d.stack.currentIndex() == 0, "список очищен, снова подсказка")
check(len(os.listdir(cfg["dl_folder"])) == 3, "файлы в папке остались")

# путь вписали руками и сразу «Скачать» (поле не теряло фокус) — папка тоже запоминается
typed = os.path.join(root, "Вписано руками")
d.folder.setText(typed)
d.links.setPlainText("https://example.com/v/ok")
d.start()
check(wait(lambda: not d.busy, 30) and cfg.get("dl_folder") == typed and settings.load()["dl_folder"] == typed,
      f"вписанная папка запомнена и записана в настройки ({cfg.get('dl_folder')})")
d.clear_list()

# окно минимального размера
w.resize(w.minimumWidth(), w.minimumHeight())
pump(0.6)
check(d.minimumSizeHint().height() <= d.height(), f"вкладка влезает в окно минимального размера "
      f"({d.minimumSizeHint().height()} ≤ {d.height()})")
probs = layout_problems()
check(not probs, f"в окне минимального размера ничего не сплющено и не обрезано {probs}")
shot("qt_dl_min.png")

check(not slot_errors, f"ошибок в обработчиках нет ({len(slot_errors)})")
print("\nИТОГ:", "всё хорошо" if not fails else f"проблем: {len(fails)}")
for f in fails:
    print("  -", f)
w.quitting = True
w.close()
sys.exit(1 if fails else 0)
