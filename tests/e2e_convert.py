"""Вкладка «Конвертация» целиком: MOV → MP4, список «было → станет», превью, сравнение крупно, замена,
перетаскивание, окно минимального размера.

Запуск: python tests/e2e_convert.py [папка_для_снимков] [light|dark]
Окно появится на экране. Диалоги подменены автоответом «да». Корзина подменена папкой во временной папке —
тестовые оригиналы в настоящую Корзину не попадают. Настройки — во временной папке.
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

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton  # noqa: E402

qapp = QApplication(sys.argv)

import app  # noqa: E402
import compress_page  # noqa: E402
import convcore  # noqa: E402
import dupcore  # noqa: E402
import ui_util  # noqa: E402
from test_compcore import photo, save_jpeg  # noqa: E402
from test_convcore import iphone_mov  # noqa: E402

shots = sys.argv[1] if len(sys.argv) > 1 else tempfile.gettempdir()
mode = sys.argv[2] if len(sys.argv) > 2 else "system"
root = tempfile.mkdtemp(prefix="dup_conv_e2e_")
atexit.register(shutil.rmtree, root, True)
work = tempfile.mkdtemp(prefix="dup_conv_work_")
atexit.register(shutil.rmtree, work, True)
convcore.WORK = work
trash = tempfile.mkdtemp(prefix="dup_conv_bin_")
atexit.register(shutil.rmtree, trash, True)
dupcore.to_recycle_bin = lambda paths, hwnd=None, **k: ([shutil.move(x, trash) and x for x in paths], [])


def p(rel):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


mov1 = iphone_mov(p(r"iPhone\IMG_0001.MOV"), seconds=3)
live = iphone_mov(p(r"iPhone\IMG_0002.MOV"), keys=[(convcore.LIVE_KEY, "8D5F0A3B-1C2D-4E5F-9A8B-7C6D5E4F3A2B")])
mjpeg = iphone_mov(p(r"Камера\MVI_0003.MOV"), video=("-c:v", "mjpeg"))
clip = iphone_mov(p(r"Камера\прогулка.mov"), seconds=2)
open(p(r"Камера\прогулка.mp4"), "wb").close()                     # имя занято — новый файл получит «(2)»
jpg = save_jpeg(photo(400, 300), p(r"iPhone\IMG_0003.jpg"))         # не MOV — вкладка его не берёт
old = time.time() - 86400 * 400
for f in (mov1, clip):
    os.utime(f, (old, old))

answers = []
ui_util.ask_yes_no = lambda parent, text, **k: answers.append(("yesno", text)) or True
ui_util.info = lambda parent, text: answers.append(("info", text))
ui_util.warn = lambda parent, text: answers.append(("warn", text))

slot_errors = []
_hook = sys.excepthook
sys.excepthook = lambda *exc: (slot_errors.append(exc), _hook(*exc))
cfg = settings.load()
cfg["theme"] = mode
cfg["load"] = "fast"
w = app.MainWindow(cfg)
w.show()
c = w.convert
w.tabs.setCurrentWidget(c)
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


def ink_share(widget):
    img = widget.grab().toImage()
    bg = QColor(w.colors["surface2"])
    pts = [(x, y) for y in range(0, img.height(), 3) for x in range(0, img.width(), 3)]
    return sum(img.pixelColor(x, y) != bg for x, y in pts) / len(pts)


def cell_ink(item, col):
    """Самый частый цвет точек букв в ячейке списка (края букв сглажены — берём частый, а не любой)."""
    rect = c.tree.visualItemRect(item)
    x0 = c.tree.header().sectionViewportPosition(col)
    img = c.tree.viewport().grab().toImage()
    dpr = img.devicePixelRatio()
    bg = img.pixelColor(int((x0 + 2) * dpr), int((rect.top() + 2) * dpr))
    inks = Counter()
    for y in range(int(rect.top() * dpr), int(rect.bottom() * dpr)):
        for x in range(int((x0 + 4) * dpr), int((x0 + c.tree.columnWidth(col) - 4) * dpr)):
            px = img.pixelColor(x, y)
            if abs(px.lightness() - bg.lightness()) > 60:
                inks[px.name()] += 1
    return inks.most_common(1)[0][0] if inks else None


def near(a, b, tol=40):
    qa, qb = QColor(a), QColor(b)
    return max(abs(qa.red() - qb.red()), abs(qa.green() - qb.green()), abs(qa.blue() - qb.blue())) <= tol


def layout_problems():
    bad = []
    for wd in c.findChildren(QLabel):
        if wd.isVisible() and wd.wordWrap() and wd.text() and wd.height() + 1 < wd.heightForWidth(wd.width()):
            bad.append(f"перенос «{wd.text()[:25]}» {wd.height()} из {wd.heightForWidth(wd.width())}")
    for wd in c.findChildren(QPushButton) + c.findChildren(QLineEdit):
        if not wd.isVisible():
            continue
        hint = wd.sizeHint() if isinstance(wd, QPushButton) else wd.minimumSizeHint()
        name = wd.text()[:25] if hasattr(wd, "text") else type(wd).__name__
        if isinstance(wd, QPushButton) and wd.text() and wd.width() + 1 < hint.width():
            bad.append(f"кнопка «{name}» {wd.width()} из {hint.width()}")
        if wd.height() + 1 < hint.height():
            bad.append(f"{type(wd).__name__} «{name}» сплющен: {wd.height()} из {hint.height()}")
    for i in range(c.tree.topLevelItemCount()):
        it = c.tree.topLevelItem(i)
        for col in (1, 2, 3, 4, 5):
            need = c.tree.fontMetrics().horizontalAdvance(it.text(col)) + 12
            if need > c.tree.columnWidth(col):
                bad.append(f"ячейка «{it.text(col)}» {c.tree.columnWidth(col)} из {need}")
    return sorted(set(bad))


pump(0.6)

# ---------- начальное состояние
tabs = [w.tabs.tabText(i) for i in range(w.tabs.count())]
check(tabs == ["Дубликаты", "Сжатие", "Конвертация", "Метаданные", "Настройки"], f"вкладки: {tabs}")
check(c.btn_start.text() == "Подготовить MP4" and c.btn_replace.text() == "Заменить оригиналы"
      and not c.btn_replace.isEnabled(), "кнопки до подготовки")
check(c.stack.currentIndex() == 0 and "было → станет" in c.empty.text(), "до подготовки — заглушка")
check(c.what.isVisible() and "без пересжатия" in c.what.text() and not c.hint.isVisible(), "что делает вкладка")
check(not hasattr(c, "chips") and c.mode_btns == {}, "режимов и типов у «Конвертации» нет")
shot("qt_convert_start.png")

# ---------- подготовка
c.folder.setText(root)
c.start()
check(c.busy and c.btn_stop.isEnabled() and not c.btn_start.isEnabled(), "во время подготовки «Остановить» активна")
check(w.busy_note() is not None and "конвертация" in w.busy_note()[1], "при выходе во время конвертации — предупреждение")
wait(lambda: not c.busy, 120)
pump(0.5)
names = sorted((os.path.basename(j.path), os.path.basename(j.target)) for j in c.ready)
check(names == [("IMG_0001.MOV", "IMG_0001.MP4"), ("прогулка.mov", "прогулка (2).mp4")], f"готовы два MOV: {names}")
skipped = {os.path.basename(j.path): j.skip for j in c.skipped}
check(set(skipped) == {"IMG_0002.MOV", "MVI_0003.MOV"} and "живого фото" in skipped["IMG_0002.MOV"]
      and "mjpeg" in skipped["MVI_0003.MOV"], f"пропущены «живое фото» и MJPEG: {skipped}")
check(c.btn_skipped.isVisible() and c.btn_skipped.text() == "Не конвертированы: 2", c.btn_skipped.text())
check(c.result.files_seen == 4, f"JPEG не взят — только MOV ({c.result.files_seen})")
it = c.items[mov1]
cols = [it.text(i) for i in range(1, 7)]
check(cols[0] == "IMG_0001.MOV" and cols[1] == "IMG_0001.MP4" and cols[4] == "без пересжатия"
      and cols[5] == "iPhone", f"строка списка: {cols}")
header = [c.tree.headerItem().text(i) for i in range(c.tree.columnCount())]
check(header == ["Заменить", "Файл", "Станет", "Было", "Стало", "Как", "Где лежит"], f"столбцы: {header}")
check(c.btn_replace.text() == "Заменить 2 файла" and c.btn_replace.isEnabled(),
      f"на кнопке без «освободится»: «{c.btn_replace.text()}»")
check("освободится" not in c.status.text() and c.step_text.text().startswith("Готово за"), c.step_text.text())
check(w.windowTitle() == "Duplio", "после подготовки заголовок обычный: " + w.windowTitle())

# Сравнение справа: кадры обоих файлов, под ними — чем проверено.
targets_now = {j.path: j.target for j in c.ready}
c.tree.setCurrentItem(it)
wait(lambda: c.pic_old.img is not None and c.pic_new.img is not None, 20)
pump(0.3)
check(c.pic_old.img is not None and c.pic_new.img is not None and c.pic_old.img.size() == c.pic_new.img.size(),
      "кадры «было» и «стало» загружены, одного размера")
check(ink_share(c.pic_old) > 0.3 and ink_share(c.pic_new) > 0.3,
      f"на превью есть изображение ({ink_share(c.pic_old):.2f}, {ink_share(c.pic_new):.2f})")
same = c.pic_old.img.convertToFormat(c.pic_new.img.format()) == c.pic_new.img
check(same, "кадр нового файла совпадает с кадром оригинала точка в точку")
check(c.cmp_sizes.text().startswith("MOV ") and " → MP4 " in c.cmp_sizes.text(), "размеры: " + c.cmp_sizes.text())
check("те же байт в байт" in c.cmp_how.text(), "под превью: " + c.cmp_how.text())
other = c.items[clip]                                   # выделенная строка рисуется цветом выделения
ink = cell_ink(other, 5)
check(ink is not None and near(ink, w.colors["keep"]), f"«без пересжатия» — зелёным ({ink}, ждали {w.colors['keep']})")
ink1 = cell_ink(other, 2)
check(ink1 is not None and near(ink1, w.colors["text"]), f"новое имя — обычным цветом ({ink1})")
check(it.toolTip(2) == targets_now[mov1], "у нового имени — подсказка с полным путём")
shot("qt_convert_ready.png")
check(not layout_problems(), f"ничего не обрезано и не сплющено: {layout_problems()}")
last = c.tree.columnCount() - 1
need = c.tree.header().fontMetrics().horizontalAdvance(header[last]) + 16
right = c.tree.header().sectionViewportPosition(last) + c.tree.columnWidth(last)
check(c.tree.columnWidth(last) >= need and right <= c.tree.viewport().width(),
      f"«{header[last]}» виден целиком без прокрутки: {c.tree.columnWidth(last)} из {need}, "
      f"правый край {right} при {c.tree.viewport().width()}")
# Длинный список: появится полоса прокрутки и отнимет ширину — «(в самой папке)» всё равно влезает.
bar = 0 if c.tree.verticalScrollBar().isVisible() else c.tree.verticalScrollBar().sizeHint().width()
room = c.tree.viewport().width() - bar - sum(c.tree.columnWidth(i) for i in range(last))
need = c.tree.fontMetrics().horizontalAdvance("(в самой папке)") + 12
check(room >= need, f"«(в самой папке)» влезает и при полосе прокрутки: {room} из {need}")

dlg = compress_page.CompareDialog(c, c.ready, c.ready.index(c.current))
dlg.show()
pump(0.6)
check(dlg.title.text() == "IMG_0001.MOV" and "IMG_0001.MOV → IMG_0001.MP4" in dlg.info.text(),
      f"крупно: {dlg.title.text()} · {dlg.info.text()[:60]}")
check("целиком — «Открыть новый»" in dlg.info.text(), "подсказка про кадр называет свою кнопку: " + dlg.info.text()[-50:])
check(dlg.view.a is not None and not dlg.view.a.isNull() and dlg.view.a.size() == dlg.view.b.size(),
      "крупно: оба кадра, одного размера")
open_btns = [b.text() for b in dlg.findChildren(QPushButton)]
check("Открыть новый" in open_btns and "Открыть сжатый" not in open_btns, f"кнопки крупно: {open_btns}")
dlg.grab().save(os.path.join(shots, "qt_convert_compare.png"))
dlg.close()

# ---------- замена
st0 = {j.path: os.stat(j.path) for j in c.ready}
targets = {j.path: j.target for j in c.ready}
check(w.busy_note() is not None and "Новые файлы ещё не заменили" in w.busy_note()[1], "выход с незаменёнными — вопрос")
answers.clear()
c.replace_marked()
pump(0.5)
ask = next((a[1] for a in answers if a[0] == "yesno"), "")
check("(.mp4)" in ask and "Корзину" in ask, "подтверждение: " + ask[:70])
check(all(not os.path.exists(x) for x in targets) and all(os.path.exists(t) for t in targets.values()),
      "оригиналы ушли, рядом — MP4")
check(sorted(os.listdir(trash)) == ["IMG_0001.MOV", "прогулка.mov"], f"в «Корзине»: {sorted(os.listdir(trash))}")
check(all(os.stat(t).st_mtime_ns == st0[x].st_mtime_ns and os.stat(t).st_birthtime_ns == st0[x].st_birthtime_ns
          for x, t in targets.items()), "даты файлов прежние")
check(os.path.getsize(p(r"Камера\прогулка.mp4")) == 0, "чужой «прогулка.mp4» не тронут")
check(any(a[0] == "info" and a[1].startswith("Заменено файлов: 2.") for a in answers), "итог замены показан")
check(c.tree.topLevelItemCount() == 0 and c.empty.text() == "Все отмеченные файлы заменены новыми.",
      "список пуст: " + c.empty.text())
check(not [x for x in os.listdir(p("iPhone")) if x.startswith("~")], "временных файлов рядом не осталось")

# ---------- перетаскивание
def drag(paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(x) for x in paths])
    pos = QPoint(w.width() // 2, w.height() // 2)
    QApplication.sendEvent(w, QDragEnterEvent(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
    pump(0.1)
    text = w.drop_hint_text
    QApplication.sendEvent(w, QDropEvent(QPointF(pos), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
    pump(0.2)
    return text


w.tabs.setCurrentWidget(c)
said = drag([live, mjpeg])
check(said == "Отпусти — переведу в MP4 только 2 файла" and c.drop_files == [live, mjpeg]
      and c.files_note.text() == "Перетащено: 2 файла", f"файлы на «Конвертацию»: {said!r}")
said = drag([p("Камера")])
check(said == "Отпусти — подставлю папку «Камера» в «Конвертацию»" and c.folder.text() == p("Камера")
      and c.drop_files is None, f"папка на «Конвертацию»: {said!r}")
c.busy = True
answers.clear()
drag([live])
c.busy = False
check(any(a[0] == "warn" and "идёт конвертация" in a[1] for a in answers), "во время конвертации бросок не принят")

# ---------- окно минимального размера
w.resize(w.minimumWidth(), w.minimumHeight())
iphone_mov(p(r"iPhone\IMG_0005.MOV"))                              # чтобы в списке была строка
c.folder.setText(root)
c.start()
wait(lambda: not c.busy, 60)
pump(0.5)


def inside(widget):
    r = widget.rect()
    tl, br = widget.mapTo(w, r.topLeft()), widget.mapTo(w, r.bottomRight())
    return widget.isVisible() and tl.x() >= 0 and tl.y() >= 0 and br.x() < w.width() and br.y() < w.height()


for name, wd in (("Подготовить", c.btn_start), ("Остановить", c.btn_stop), ("Заменить", c.btn_replace)):
    check(inside(wd), f"кнопка «{name}» видна в окне минимального размера")
check(c.minimumSizeHint().height() <= c.height(),
      f"вкладке хватает высоты: минимум {c.minimumSizeHint().height()} при {c.height()}")
check(not layout_problems(), f"в окне минимального размера ничего не обрезано: {layout_problems()}")
check(c.tree.height() >= 150, f"список не ниже 150 px ({c.tree.height()})")
shot("qt_convert_min.png")

check(not slot_errors, f"ошибок в обработчиках нет ({len(slot_errors)})")
w.quit_app()
check(not os.path.exists(work) or not os.listdir(work), "при выходе рабочая папка очищена")
print("ИТОГ:", "всё прошло" if not fails else f"провалов {len(fails)}")
sys.exit(1 if fails else 0)
