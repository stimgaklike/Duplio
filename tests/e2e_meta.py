"""Вкладка «Метаданные» целиком: наборы и галочки, проверка папки, «было → стало», копии в папку, замена.

Запуск: python tests/e2e_meta.py [папка_для_снимков] [light|dark]
Окно появится на экране. Диалоги подменены автоответом «да». Корзина подменена временной папкой —
настоящую тест не трогает. Настройки — во временной папке.
"""

import atexit
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import settings  # noqa: E402

tmp_cfg = tempfile.mkdtemp(prefix="dup_cfg_")
atexit.register(shutil.rmtree, tmp_cfg, True)          # убрать и при обрыве прогона
settings.DIR, settings.PATH = tmp_cfg, os.path.join(tmp_cfg, "settings.json")

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

qapp = QApplication(sys.argv)

import app  # noqa: E402
import dupcore  # noqa: E402
import metacore  # noqa: E402
import ui_util  # noqa: E402
from PIL import Image, PngImagePlugin  # noqa: E402
from test_metacore import make_video, motion_jpeg, phone_jpeg, picture  # noqa: E402

shots = sys.argv[1] if len(sys.argv) > 1 else tempfile.gettempdir()
mode = sys.argv[2] if len(sys.argv) > 2 else "system"
base = tempfile.mkdtemp(prefix="dup_meta_e2e_")
atexit.register(shutil.rmtree, base, True)
root = os.path.join(base, "Поездка")
work = tempfile.mkdtemp(prefix="dup_meta_work_")
atexit.register(shutil.rmtree, work, True)
metacore.WORK = work
fake_bin = tempfile.mkdtemp(prefix="dup_meta_bin_")
atexit.register(shutil.rmtree, fake_bin, True)


def to_bin(paths, hwnd=None, **kw):
    for path in paths:
        shutil.move(path, os.path.join(fake_bin, f"{len(os.listdir(fake_bin))}_{os.path.basename(path)}"))
    return list(paths), []


dupcore.to_recycle_bin = to_bin


def p(rel):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


photos = [phone_jpeg(p(rf"Телефон\IMG_000{i}.jpg"), picture(color=(40 * i, 120, 200))) for i in (1, 2, 3)]
plain = p(r"Разное\без метаданных.jpg")
picture().save(plain, "JPEG")
info = PngImagePlugin.PngInfo()
info.add_text("Author", "Ivan")
shot_png = p(r"Скриншоты\экран.png")
picture().save(shot_png, "PNG", pnginfo=info)
clip = make_video(p(r"Видео\отпуск.mp4"), "-movflags", "use_metadata_tags")
old = time.time() - 86400 * 200
for f in photos + [plain, shot_png, clip]:
    os.utime(f, (old, old))
orig = {f: open(f, "rb").read() for f in photos + [plain, shot_png, clip]}

answers = []
ui_util.ask_yes_no = lambda parent, text, **k: answers.append(("yesno", text)) or True
ui_util.info = lambda parent, text: answers.append(("info", text))
ui_util.warn = lambda parent, text: answers.append(("warn", text))
opened = []
ui_util.open_file = lambda path: opened.append(path)
revealed = []
ui_util.reveal = lambda path: revealed.append(path)          # не открывать настоящий Проводник

slot_errors = []
_hook = sys.excepthook
sys.excepthook = lambda *exc: (slot_errors.append(exc), _hook(*exc))
cfg = settings.load()
cfg["theme"] = mode
cfg["load"] = "fast"
w = app.MainWindow(cfg)
w.show()
m = w.meta
w.tabs.setCurrentWidget(m)
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


def face(btn):
    """Самый частый цвет кнопки (её заливка) на снимке."""
    from collections import Counter
    img = btn.grab().toImage()
    pts = [(x, y) for y in range(4, img.height() - 4) for x in range(6, img.width() - 6)]
    return Counter(img.pixelColor(x, y).name() for x, y in pts).most_common(1)[0][0]


def ink_share(widget):
    img = widget.grab().toImage()
    bg = QColor(w.colors["surface2"])
    pts = [(x, y) for y in range(0, img.height(), 3) for x in range(0, img.width(), 3)]
    return sum(img.pixelColor(x, y) != bg for x, y in pts) / len(pts)


def ink_in_cell(tree, row, col):
    """Цвета букв в ячейке: точки, заметно отличные от фона ячейки, — по снимку самого списка."""
    from collections import Counter
    tree.scrollToItem(row)
    pump(0.1)
    img = tree.viewport().grab().toImage()
    dpr = img.devicePixelRatio()
    r = tree.visualItemRect(row)
    x0 = tree.header().sectionViewportPosition(col)
    x1 = x0 + tree.header().sectionSize(col)
    bg = img.pixelColor(int((x1 - 3) * dpr), int((r.top() + 2) * dpr))
    out = Counter()
    for y in range(int(r.top() * dpr) + 2, int(r.bottom() * dpr) - 1):
        for x in range(int(x0 * dpr) + 2, int(x1 * dpr) - 2):
            px = img.pixelColor(x, y)
            if abs(px.red() - bg.red()) + abs(px.green() - bg.green()) + abs(px.blue() - bg.blue()) > 120:
                out[px.name()] += 1
    return out


def main_ink(counter):
    """Самый частый цвет букв: края сглажены в оттенки, а середина штрихов — ровно цвет текста."""
    return counter.most_common(1)[0][0] if counter else ""


def close(a, b, tol=24):
    a, b = QColor(a), QColor(b)
    return abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue()) <= tol


def picture_ink(pic):
    """Доля закрашенных точек внутри прямоугольника, куда Picture вписывает картинку (как в его paintEvent)."""
    from PySide6.QtCore import QSize
    img = pic.grab().toImage()
    dpr = img.devicePixelRatio()
    s = pic.img.size().scaled(pic.size() - QSize(8, 8), Qt.KeepAspectRatio)
    x0, y0 = (pic.width() - s.width()) / 2, (pic.height() - s.height()) / 2
    bg = QColor(w.colors["surface2"])
    pts = [(x, y) for y in range(int(y0) + 2, int(y0 + s.height()) - 2, 2)
           for x in range(int(x0) + 2, int(x0 + s.width()) - 2, 2)]
    return sum(img.pixelColor(int(x * dpr), int(y * dpr)) != bg for x, y in pts) / max(1, len(pts)), s


def layout_problems():
    from PySide6.QtWidgets import QCheckBox, QLabel, QLineEdit, QPushButton
    bad = []
    for wd in m.findChildren(QLabel):
        if wd.isVisible() and wd.wordWrap() and wd.text() and wd.height() + 1 < wd.heightForWidth(wd.width()):
            bad.append(f"перенос «{wd.text()[:25]}» {wd.height()} из {wd.heightForWidth(wd.width())}")
        if wd.isVisible() and not wd.wordWrap() and wd.text() and wd.objectName() == "muted" \
                and wd.width() + 1 < wd.sizeHint().width():
            bad.append(f"надпись «{wd.text()[:25]}» {wd.width()} из {wd.sizeHint().width()}")
    for wd in m.findChildren(QPushButton) + m.findChildren(QLineEdit) + m.findChildren(QCheckBox):
        if not wd.isVisible():
            continue
        hint = wd.minimumSizeHint() if isinstance(wd, QLineEdit) else wd.sizeHint()
        name = wd.text()[:25] if hasattr(wd, "text") else type(wd).__name__
        if not isinstance(wd, QLineEdit) and wd.text() and wd.width() + 1 < hint.width():
            bad.append(f"{type(wd).__name__} «{name}» {wd.width()} из {hint.width()}")
        if wd.height() + 1 < hint.height():
            bad.append(f"{type(wd).__name__} «{name}» сплющен: {wd.height()} из {hint.height()}")
    for i in range(m.tree.topLevelItemCount()):
        it = m.tree.topLevelItem(i)
        need = m.tree.fontMetrics().horizontalAdvance(it.text(2)) + 12
        if need > m.tree.columnWidth(2):
            bad.append(f"ячейка «{it.text(2)}» {m.tree.columnWidth(2)} из {need}")
    return sorted(set(bad))


pump(0.6)

# ---------- начальное состояние
check(m.preset() == "all" and all(c.isChecked() for c in m.checks.values()), "по умолчанию «Всё» — все галочки")
check(face(m.preset_btns["all"]) == w.colors["accent"] and face(m.preset_btns["place"]) != w.colors["accent"],
      f"выбранный набор выделен ({face(m.preset_btns['all'])})")
check(m.output() == "replace" and not m.copies.isVisible() and m.output_note.isVisible(),
      "по умолчанию — замена оригиналов, поле папки копий скрыто")
check(m.btn_go.text() == "Убрать из отмеченных файлов" and not m.btn_go.isEnabled(), "главная кнопка неактивна")
check(m.stack.currentIndex() == 0, "до проверки — заглушка")
shot("qt_meta_start.png")

m.preset_btns["place"].click()
pump(0.1)
check(m.groups() == {"place"}, f"«Только место» — одна галочка ({m.groups()})")
m.checks["time"].click()
pump(0.1)
check(m.preset() == "custom" and m.groups() == {"place", "time"}, "галочка руками — набор стал «Свой»")
m.checks["time"].click()
pump(0.1)
check(m.preset() == "place", "сняли — снова «Только место»")
m.preset_btns["all"].click()
pump(0.1)

# ---------- проверка папки
m.folder.setText(root)
m.start()
check(m.busy and not m.btn_start.isEnabled() and m.btn_stop.isEnabled(), "во время проверки «Остановить» активна")
check(w.busy_note() is not None and "метаданными" in w.busy_note()[1], "при выходе во время работы — предупреждение")
wait(lambda: not m.busy)
pump(0.5)
names = sorted(os.path.basename(i.path) for i in m.shown)
check(names == ["IMG_0001.jpg", "IMG_0002.jpg", "IMG_0003.jpg", "отпуск.mp4", "экран.png"],
      f"в списке — файлы, где есть что убрать: {names}")
check(m.tree.topLevelItemCount() == 5 and m.stack.currentIndex() == 1, "в списке 5 строк")
check(m.checks["place"].text() == "Место (GPS) · 4", f"у галочки — сколько файлов: {m.checks['place'].text()}")
check(m.btn_go.text() == "Убрать из 5 файлов" and m.btn_go.isEnabled(), f"кнопка: «{m.btn_go.text()}»")
check(face(m.btn_go) == w.colors["danger_bg"], f"в режиме замены главная кнопка — красная ({face(m.btn_go)})")
check(w.windowTitle() == "Duplio", "после проверки заголовок обычный: " + w.windowTitle())
first = next(i for i in m.shown if i.path == photos[0])
m.tree.setCurrentItem(m.tree_items[first.path])
wait(lambda: m.pic.img is not None, 10)
pump(0.3)
share, size = picture_ink(m.pic)
check(share > 0.95 and size.height() >= 100, f"превью файла видно: закрашено {share:.2f}, {size.width()}x{size.height()}")
rows = [m.fields.topLevelItem(i) for i in range(m.fields.topLevelItemCount())]
heads = [r.text(0) for r in rows if r.isFirstColumnSpanned()]
check(heads == list(metacore.GROUPS.values()), f"поля по группам, все шесть: {heads}")
gps = next(r for r in rows if r.text(0) == "Геометка")
check((gps.text(1), gps.text(2)) == ("55.75120, 37.61840", "уберётся"), f"геометка видна и уберётся: {gps.text(1)}")
ink = main_ink(ink_in_cell(m.fields, gps, 2))
check(close(ink, w.colors["danger"]), f"«уберётся» — красным на экране ({ink}, ждали {w.colors['danger']})")
shot("qt_meta_all.png")
check(not layout_problems(), f"ничего не обрезано и не сплющено: {layout_problems()}")

m.preset_btns["place"].click()
pump(0.3)
names = sorted(os.path.basename(i.path) for i in m.shown)
check(names == ["IMG_0001.jpg", "IMG_0002.jpg", "IMG_0003.jpg", "отпуск.mp4"],
      f"«Только место»: PNG без геометки ушёл из списка: {names}")
rows = [m.fields.topLevelItem(i) for i in range(m.fields.topLevelItemCount())]
model = next(r for r in rows if r.text(0) == "Модель камеры")
gps = next(r for r in rows if r.text(0) == "Геометка")
check((model.text(2), gps.text(2)) == ("останется", "уберётся"), "камера останется, геометка уберётся")
ink_keep, ink_gone = main_ink(ink_in_cell(m.fields, model, 1)), main_ink(ink_in_cell(m.fields, gps, 1))
check(close(ink_gone, w.colors["muted"]) and close(ink_keep, w.colors["text"]),
      f"убираемое значение — серым ({ink_gone}), остающееся — обычным цветом ({ink_keep})")
shot("qt_meta_place.png")

# ---------- копии в папку: оригиналы не трогаются
m.output_btns["copies"].click()
pump(0.2)
want = os.path.join(base, "Поездка — без метаданных")
check(m.copies.isVisible() and m.copies.text() == want, f"папка копий предложена рядом: {m.copies.text()}")
check(m.btn_go.text() == "Сохранить 4 очищенные копии", f"кнопка: «{m.btn_go.text()}»")
check(face(m.btn_go) == w.colors["accent"], f"для копий главная кнопка — синяя ({face(m.btn_go)})")
shot("qt_meta_copies.png")
check(not layout_problems(), f"с полем копий ничего не обрезано: {layout_problems()}")
answers.clear()
m.run_marked()
wait(lambda: not m.busy, 60)
pump(0.5)
got = sorted(os.path.relpath(os.path.join(d, f), want) for d, _s, fs in os.walk(want) for f in fs)
check(got == [r"Видео\отпуск.mp4", r"Телефон\IMG_0001.jpg", r"Телефон\IMG_0002.jpg", r"Телефон\IMG_0003.jpg"],
      f"копии легли с теми же подпапками: {got}")
check(all(open(f, "rb").read() == data for f, data in orig.items()), "оригиналы не тронуты ни на байт")
check(all(not any(f.group == "place" for f in metacore.read(os.path.join(want, g)).fields) for g in got),
      "в копиях геометки нет")
check(any(a[0] == "yesno" and a[1].startswith("Сохранено очищенных копий: 4.") for a in answers)
      and opened == [want], f"итог показан, «Открыть папку» открыла её ({opened})")
check(not os.path.exists(work) or not os.listdir(work), "рабочая папка пуста")

# ---------- замена: оригинал — в Корзину, даты прежние
m.output_btns["replace"].click()
m.preset_btns["all"].click()
pump(0.2)
m.start()                                          # копии лежат рядом, а не внутри — проверка их не видит
wait(lambda: not m.busy)
pump(0.3)
check(len(m.shown) == 5, f"снова 5 файлов ({len(m.shown)})")
m.tree_items[clip].setCheckState(0, Qt.Unchecked)
pump(0.1)
check(m.btn_go.text() == "Убрать из 4 файлов", f"сняли отметку с видео: «{m.btn_go.text()}»")
answers.clear()
revealed.clear()
done_paths = [i.path for i in m._marked_items()]
m.run_marked()
wait(lambda: not m.busy, 60)
pump(0.5)
check(any(a[0] == "yesno" and "Корзину" in a[1] and "(место, камера, время, автор, превью, прочее)" in a[1]
          for a in answers), "перед заменой спросили и перечислили, что уберётся")
final = [a[1] for a in answers if a[1].startswith("Готово: метаданные убраны из 4 файлов.")]
check(len(final) == 1 and "остались на своих местах с теми же именами" in final[0] and "Корзине" in final[0],
      f"итог замены говорит, где файлы и где старые версии: {final[:1]}")
check(len(revealed) == 1 and revealed[0] in done_paths and os.path.exists(revealed[0]),
      f"«Показать в папке» выделяет готовый файл, и он на месте: {revealed}")
check(all(metacore.read(f).fields == [] for f in photos + [shot_png]), "в заменённых файлах ничего не осталось")
check(all(abs(os.path.getmtime(f) - old) < 1 for f in photos + [shot_png]), "даты изменения прежние")
check(open(clip, "rb").read() == orig[clip], "неотмеченное видео не тронуто")
check(len(os.listdir(fake_bin)) == 4, f"оригиналы — в «Корзине» ({len(os.listdir(fake_bin))})")
check([os.path.basename(i.path) for i in m.shown] == ["отпуск.mp4"], "в списке осталось только видео")
check(not [x for x in os.listdir(os.path.dirname(photos[0])) if x.startswith("~")], "временных файлов не осталось")
m._mark_all(True)
m.run_marked()
wait(lambda: not m.busy, 60)
pump(0.5)
check(m.stack.currentIndex() == 0 and m.empty.text() == "Готово: в проверенных файлах больше нечего убирать.",
      f"всё очищено — в пустом списке так и сказано: {m.empty.text()[:40]!r}")

def first_ink_row(widget):
    """Верхняя строка точек, где на снимке виджета есть буквы (отличие от фона в его верхнем левом углу)."""
    img = widget.grab().toImage()
    bg = img.pixelColor(1, 1)
    for y in range(img.height()):
        for x in range(0, img.width(), 2):
            px = img.pixelColor(x, y)
            if abs(px.red() - bg.red()) + abs(px.green() - bg.green()) + abs(px.blue() - bg.blue()) > 120:
                return y / img.devicePixelRatio()
    return None


ink_top = first_ink_row(m.side_hint)
check(m.side_hint.isVisible() and ink_top is not None and ink_top < 12 and m.side_hint.height() > 200,
      f"без выбранного файла текст подсказки — наверху панели (буквы с {ink_top} px, высота {m.side_hint.height()})")
shot("qt_meta_done.png")

# ---------- перетаскивание на «Метаданные»


def drag(paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(x) for x in paths])
    pos = QPoint(w.width() // 2, w.height() // 2)
    QApplication.sendEvent(w, QDragEnterEvent(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
    pump(0.1)
    seen = w.drop_hint_text
    QApplication.sendEvent(w, QDropEvent(QPointF(pos), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
    pump(0.2)
    return seen


seen = drag([photos[0], clip])
check(seen == "Отпусти — проверю только 2 файла" and m.drop_files == [photos[0], clip]
      and m.files_note.text() == "Перетащено: 2 файла", f"брошенные файлы — в «Метаданные»: {seen}")
m.files_reset.click()
seen = drag([os.path.dirname(clip)])
check(seen == "Отпусти — подставлю папку «Видео» в «Метаданные»" and m.folder.text() == os.path.dirname(clip),
      f"брошенная папка — в поле: {seen}")

# ---------- окно минимального размера
w.resize(w.minimumWidth(), w.minimumHeight())
fresh = phone_jpeg(p(r"Ещё\IMG_0009.jpg"))                # всё прежнее уже очищено — нужен файл с метаданными
motion = motion_jpeg(p(r"Ещё\живое.jpg"))                 # к нему приложено видео — запись Samsung не трогается
os.remove(motion + ".mp4")
m.use_folder(os.path.dirname(fresh))
m.start()
wait(lambda: not m.busy)
pump(0.5)
m.tree.setCurrentItem(m.tree_items[fresh])
pump(0.3)
check(m.current is not None and m.side_body.isVisible(), "в окне минимального размера выбран файл, поля видны")
row = m.tree_items[motion]
check(row.text(2).endswith("не всё") and "убрать нельзя" in row.toolTip(2),
      f"файл, где часть полей не убрать, помечен в списке: {row.text(2)!r}")
ink = main_ink(ink_in_cell(m.tree, row, 2))
check(close(ink, w.colors["warn"]), f"и пометка — цветом предупреждения ({ink}, ждали {w.colors['warn']})")
check(m.tree_items[fresh].text(2) == "место, камера, время +3", "у обычного файла пометки нет")
first_row = m.fields.topLevelItem(0)
check(first_row.text(0) == "Место (GPS)" and m.fields.visualItemRect(first_row).top() >= 0
      and m.fields.verticalScrollBar().value() == 0, "таблица полей нового файла — с первой группы, не прокручена")


def inside(widget):
    r = widget.rect()
    tl, br = widget.mapTo(w, r.topLeft()), widget.mapTo(w, r.bottomRight())
    return widget.isVisible() and tl.x() >= 0 and tl.y() >= 0 and br.x() < w.width() and br.y() < w.height()


for name, wd in (("Проверить", m.btn_start), ("Остановить", m.btn_stop), ("Убрать", m.btn_go)):
    check(inside(wd), f"кнопка «{name}» видна в окне минимального размера")
check(m.minimumSizeHint().height() <= m.height(),
      f"вкладке хватает высоты: минимум {m.minimumSizeHint().height()} при {m.height()}")
check(not layout_problems(), f"в окне минимального размера ничего не обрезано: {layout_problems()}")
check(m.tree.height() >= 150, f"список не ниже 150 px ({m.tree.height()})")
check(m.fields.height() >= 100, f"таблица полей не ниже 100 px ({m.fields.height()})")
shot("qt_meta_min.png")

check(not slot_errors, f"ошибок в обработчиках нет ({len(slot_errors)})")
w.quit_app()
print("ИТОГ:", "всё прошло" if not fails else f"провалов {len(fails)}")
sys.exit(1 if fails else 0)
