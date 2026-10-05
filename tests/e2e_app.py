"""Прогон окна целиком на тестовой папке: поиск → отметки → сравнение → удаление в Корзину.

Запуск: python tests/e2e_app.py [папка_для_снимков] [light|dark]
Окно появится на экране на несколько секунд. Диалоги подменены автоответом «да».
Настройки пишутся во временную папку, а не в настоящие настройки программы.
"""

import glob
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import settings  # noqa: E402

tmp_cfg = tempfile.mkdtemp(prefix="dup_cfg_")
settings.DIR, settings.PATH = tmp_cfg, os.path.join(tmp_cfg, "settings.json")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import app  # noqa: E402
import dupcore  # noqa: E402
import dups_page  # noqa: E402
import ui_util  # noqa: E402

shots = sys.argv[1] if len(sys.argv) > 1 else tempfile.gettempdir()
mode = sys.argv[2] if len(sys.argv) > 2 else "system"
root = tempfile.mkdtemp(prefix="dup_e2e_")


def put(rel, data):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)
    return p


qapp = QApplication(sys.argv)


def jpeg(text, c1, c2, w_=900, h_=1400):
    """Своя картинка для теста: градиент и надпись, сохранённые в JPEG."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter
    img = QImage(w_, h_, QImage.Format_RGB32)
    pnt = QPainter(img)
    g = QLinearGradient(0, 0, w_, h_)
    g.setColorAt(0, QColor(c1))
    g.setColorAt(1, QColor(c2))
    pnt.fillRect(img.rect(), g)
    f = QFont("Segoe UI")
    f.setPixelSize(120)
    f.setBold(True)
    pnt.setFont(f)
    pnt.setPen(QColor("white"))
    pnt.drawText(img.rect(), Qt.AlignCenter, text)
    pnt.end()
    buf = QByteArray()
    dev = QBuffer(buf)
    dev.open(QIODevice.WriteOnly)
    img.save(dev, "JPG", 90)
    return bytes(buf)


photo1 = jpeg("IMG 1", "#0066ff", "#08bf78")
photo2 = jpeg("IMG 2", "#ff7a00", "#ffd000")
video = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "sample.mp4"), "rb").read()

now = time.time()
old = put(r"Телефон\2024\IMG_0001.jpg", photo1)
os.utime(old, (now - 86400 * 400, now - 86400 * 400))
put(r"Бэкап\Фото\IMG_0001.jpg", photo1)
put(r"Скачанное\photo (1).jpg", photo1)
put(r"Телефон\2024\IMG_0002.jpg", photo2)
put(r"Бэкап\Фото\IMG_0002 копия.jpg", photo2)
put(r"Видео\отпуск.mp4", video)
put(r"Бэкап\Видео\VID_2024.mp4", video)
put(r"Разное\уникальное.jpg", os.urandom(90_000))
put(r"Разное\заметки.txt", photo2)

answers = []
ui_util.ask_yes_no = lambda parent, text, **k: answers.append(("yesno", text)) or True
ui_util.info = lambda parent, text: answers.append(("info", text))
ui_util.warn = lambda parent, text: answers.append(("warn", text))

slot_errors = []
_hook = sys.excepthook
sys.excepthook = lambda *exc: (slot_errors.append(exc), _hook(*exc))
cfg = settings.load()
cfg["theme"] = mode
w = app.MainWindow(cfg)
w.show()
p = w.dups
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


def shot(name):
    pump(0.4)
    w.grab().save(os.path.join(shots, name))


pump(0.5)
check([w.tabs.tabText(i) for i in range(w.tabs.count())] == ["Дубликаты", "Сжатие", "Настройки"], "три вкладки")
shot("qt_start.png")

# Шапка: кроме знака, надписи и вкладок — ровный фон, без рамок и полос; знак на одной линии с вкладками.
hdr = w.tabs.header
himg = hdr.grab().toImage()
brand = hdr.layout().itemAt(0).widget()
# Пустые места шапки: левый край до знака и правая часть после вкладок.
empty_x = (2, brand.geometry().left() + 4, himg.width() - 4, w.tabs.tabBar().geometry().right() + 20)
odd = {himg.pixelColor(x, y).name() for x in empty_x for y in range(0, himg.height() - 2)}
check(odd == {w.colors["bg"]}, f"в шапке нет лишних рамок и полос (цвета: {sorted(odd)})")
bar = w.tabs.tabBar()
mid_brand = brand.mapTo(w, brand.rect().center()).y()
mid_tab = bar.mapTo(w, bar.tabRect(0).center()).y()
check(abs(mid_brand - mid_tab) <= 3, f"знак на одной линии с вкладками ({mid_brand} и {mid_tab})")


def text_width(img):
    """Ширина надписи на снимке кнопки.

    Фон — самый частый цвет средней полосы (заливка кнопки); надпись — пиксели, заметно отличные
    от него по яркости. Края кнопки (рамка, скругления) не учитываем.
    """
    from collections import Counter
    h, w_ = img.height(), img.width()
    band = [(x, y) for y in range(h // 3, 2 * h // 3) for x in range(6, w_ - 6)]
    fill = Counter(img.pixelColor(x, y).name() for x, y in band).most_common(1)[0][0]
    from PySide6.QtGui import QColor
    fl = QColor(fill).lightness()
    cols = [x for x, y in band if abs(img.pixelColor(x, y).lightness() - fl) > 60]
    return (max(cols) - min(cols)) if cols else 0


def chips_fit():
    """Надпись чипа на экране такой же ширины, как в заведомо широком чипе, — значит, не обрезана."""
    bad = []
    for b in p.chips.values():
        now_w = text_width(b.grab().toImage())
        b.setFixedWidth(b.width() + 80)
        pump(0.05)
        wide_w = text_width(b.grab().toImage())
        b.setMinimumWidth(0)
        b.setMaximumWidth(16777215)
        pump(0.05)
        if now_w + 1 < wide_w:
            bad.append(f"{b.text()}: {now_w} из {wide_w} px")
    return bad


before_state = {k: b.isChecked() for k, b in p.chips.items()}
for state in (True, False):
    for b in p.chips.values():
        b.setChecked(state)
    pump(0.2)
    check(not chips_fit(), f"текст чипов влезает, когда они {'выбраны' if state else 'не выбраны'}: {chips_fit()}")
for k, b in p.chips.items():
    b.setChecked(before_state[k])
pump(0.2)

import dups_page as _dp
_dp.QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: root)
p.choose()
pump(0.3)
check(p.folder.text() == os.path.normpath(root) and not p.busy, "выбор папки подставляет её, но поиск сам не начинается")
check(p.btn_scan.text() == "Начать поиск", "кнопка «Начать поиск»")
p.start_scan()
t0 = time.time()
while p.busy and time.time() - t0 < 30:
    pump(0.05)
pump(1.5)                       # дать прийти превью

check(w.windowTitle() == "Duplio", "после поиска заголовок обычный: " + w.windowTitle())
check(len(p.groups) == 3, f"групп 3 (найдено {len(p.groups)})")
check(sorted(len(g) for g in p.groups) == [2, 2, 3], "размеры групп 2, 2, 3")
check(len(p.marked) == 4, f"отмечено по умолчанию 4 лишних (отмечено {len(p.marked)})")
check(old not in p.marked, "самый старый IMG_0001 не отмечен")
freed = [g[0].size * (len(g) - 1) for g in p.groups]
check(freed == sorted(freed, reverse=True), "группы по убыванию освобождаемого места")
vgroup = next(g for g in p.groups if g[0].is_video)
check(p.stack.currentIndex() == 1, "список виден вместо заглушки")
size4 = sum(m.size for g in p.groups for m in g if m.path in p.marked)
check(p.btn_delete.text() == f"Удалить 4 файла в Корзину  ·  освободится {dupcore.human_size(size4)}"
      and p.btn_delete.isEnabled(), "на кнопке удаления — сколько файлов и сколько места: " + p.btn_delete.text())
some_marked = next(path for path in p.marked)
some_kept = old
pump(0.3)


def pixel_of(item):
    """Цвет пикселя на экране в строке элемента — в колонке «Изменён», правее текста."""
    rect = p.tree.visualItemRect(item)
    x = p.tree.header().sectionViewportPosition(3) + p.tree.header().sectionSize(3) - 6
    img = p.tree.viewport().grab().toImage()
    return img.pixelColor(x, rect.center().y()).name()


p.tree.setCurrentItem(None)
pump(0.2)
tint, plain = pixel_of(p.items[some_marked]), pixel_of(p.items[some_kept])
check(tint == w.colors["row_del"] and plain != w.colors["row_del"],
      f"на экране отмеченная строка подкрашена ({tint}), оставляемая — нет ({plain})")
head_px = pixel_of(p.items[old].parent())
check(head_px == w.colors["group"], f"заголовок группы на экране со своим фоном ({head_px})")

# Шрифты: выделенные надписи — настоящим жирным начертанием, а не дорисованным и не «полужирным»,
# которое на деле рисуется обычным. Меряем «чернила»: та же надпись тем же шрифтом, но обычным весом.
from PySide6.QtGui import QFont, QFontInfo, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QAbstractButton, QLabel  # noqa: E402


def widget_ink(wd):
    """«Чернила» надписи на снимке самого элемента: сколько пикселей отличаются от фона и насколько."""
    from collections import Counter
    img = wd.grab().toImage()
    pts = [(x, y) for y in range(0, img.height(), 1) for x in range(0, img.width(), 1)]
    bg = Counter(img.pixelColor(x, y).lightness() for x, y in pts).most_common(1)[0][0]
    return sum(abs(img.pixelColor(x, y).lightness() - bg) for x, y in pts)


bad_fonts = []
for wd in w.findChildren(QLabel):
    text = wd.text()
    f = wd.font()
    if not text or not wd.isVisible() or f.weight() <= 400:
        continue
    fi = QFontInfo(f)
    twin = QLabel(text)                      # та же надпись тем же стилем, но обычным весом
    twin.setObjectName(wd.objectName())
    twin.setStyleSheet("font-weight: 400;")
    twin.resize(wd.size())
    twin.ensurePolished()
    gain = widget_ink(wd) / max(1, widget_ink(twin))
    if fi.weight() != f.weight() or fi.family() != "Segoe UI" or gain < 1.12:
        bad_fonts.append(f"{text[:30]!r}: {fi.family()} {fi.styleName()} {fi.weight()} (просили {f.weight()}), "
                         f"чернил ×{gain:.2f}")
check(not bad_fonts, f"выделенный текст — настоящим жирным, без подмены шрифта: {bad_fonts[:4]}")

tr_choose = "Выбрать…"

# Курсор и отклик: «пальчик» на всём нажимаемом; наведение и нажатие заметно меняют цвет.
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QComboBox, QPushButton, QTabBar  # noqa: E402

no_hand = [getattr(x, "text", lambda: x.__class__.__name__)() or x.__class__.__name__
           for x in w.findChildren(QAbstractButton) + w.findChildren(QComboBox) + w.findChildren(QTabBar)
           if x.isVisible() and x.isEnabled() and x.cursor().shape() != Qt.PointingHandCursor]
check(not no_hand, f"курсор-«пальчик» на всех активных кнопках и списках (без него: {no_hand[:5]})")
disabled_hand = [x.text() for x in w.findChildren(QPushButton)
                 if x.isVisible() and not x.isEnabled() and x.cursor().shape() == Qt.PointingHandCursor]
check(not disabled_hand, f"на неактивных кнопках обычная стрелка (с «пальчиком»: {disabled_hand[:5]})")


def face(btn):
    """Средний цвет заливки кнопки (без текста): самый частый цвет во внутренней полосе."""
    from collections import Counter
    btn.style().unpolish(btn)
    btn.style().polish(btn)
    img = btn.grab().toImage()
    pts = [(x, img.height() // 2 + dy) for x in range(6, img.width() - 6) for dy in (-6, 6)]
    return Counter(img.pixelColor(x, y).name() for x, y in pts).most_common(1)[0][0]


def lightness_gap(a, b):
    from PySide6.QtGui import QColor
    return abs(QColor(a).lightness() - QColor(b).lightness())


# Нажатие — по пикселям (setDown даёт то же состояние, что и нажатая мышь).
# Наведение в снимке элемента Qt не рисует (underMouse=True, а grab() — обычный цвет), поэтому его
# заметность проверяем по цветам темы: наведённое отличается от обычного на ≥ 12 по яркости.
weak = []
for name, btn in (("обычная", next(b for b in w.findChildren(QPushButton) if b.text() == tr_choose)),
                  ("главная", p.btn_scan), ("чип", p.chips["audio"])):
    normal = face(btn)
    btn.setDown(True)
    pressed = face(btn)
    btn.setDown(False)
    face(btn)
    if lightness_gap(normal, pressed) < 12:
        weak.append(f"нажатие {name}: {normal} → {pressed}")
c = w.colors
for name, a_, b_ in (("кнопка", "surface2", "btn_hover"), ("главная", "accent", "accent_hover"),
                     ("удаление", "danger_bg", "danger_bg_hover"), ("рамка", "border", "border_hover")):
    if lightness_gap(c[a_], c[b_]) < 12:
        weak.append(f"наведение {name}: {c[a_]} → {c[b_]}")
check(not weak, f"наведение и нажатие заметны (разница яркости ≥ 12): {weak}")

# Отметки галочками в списке — тот же путь, что щелчок мышью по флажку.
vid_items = [p.items[m.path] for m in vgroup]
vid_items[1].setCheckState(0, Qt.Unchecked)           # снять отметку с лишней копии
vid_items[0].setCheckState(0, Qt.Checked)             # отметить ту, что оставлялась
vid_items[1].setCheckState(0, Qt.Checked)             # отметить и вторую — должно не дать
pump()
check(sum(m.path in p.marked for m in vgroup) == 1, "вторая копия видео не отмечается")
check(any("последняя" in a[1] for a in answers), "показано предупреждение про последнюю копию")
shown = {path: it.checkState(0) == Qt.Checked for path, it in p.items.items()}
check(all(shown[path] == (path in p.marked) for path in shown), "галочки на экране совпадают с тем, что удалится")
check(p.items[vgroup[0].path].text(4) in ("Видео", r"Бэкап\Видео"), "папка показана относительно выбранной")

# Сравнение: выбрать фото — справа карточки всей группы, с превью и состояниями.
p.tree.setCurrentItem(p.items[old])
pump(1.5)
group = p.group_of(old)
check(set(p.cards) == {m.path for m in group}, f"в сравнении все {len(group)} копии группы")
check(all(c.thumb.pixmap() is not None and not c.thumb.pixmap().isNull() for c in p.cards.values()),
      "у всех карточек есть превью")
check(p.cards[old].property("current") == "true", "выбранная копия подсвечена")
check(p.cards[old].pill.text() == "Оставить" and
      all(p.cards[m.path].pill.text() == "Удалить" for m in group if m.path != old), "подписи «Оставить/Удалить»")
other = next(m for m in group if m.path != old)
p.cards[other.path].btn.click()
pump()
check(other.path not in p.marked and p.items[other.path].checkState(0) == Qt.Unchecked,
      "кнопка на карточке снимает отметку и в списке")
p.cards[other.path].btn.click()
pump()
shot("qt_compare.png")

# Быстрый просмотр: большая картинка, листание стрелками, переключение отметки.
ql = dups_page.QuickLook(p, group, 0)
ql.show()
pump(0.6)
check(ql.view.pixmap() is not None and not ql.view.pixmap().isNull() and max(ql.view.pixmap().width(), ql.view.pixmap().height()) > 500,
      "быстрый просмотр показывает большую картинку")
ql.go(1)
pump(0.2)
check(ql.counter.text() == f"копия 2 из {len(group)}", "листание: " + ql.counter.text())
before = group[1].path in p.marked
ql._toggle()
check((group[1].path in p.marked) != before and ql.toggle_btn.text() in ("Оставить эту копию", "Удалить эту копию"),
      "кнопка в просмотре меняет отметку")
ql._toggle()
pump(0.3)
ql.grab().save(os.path.join(shots, "qt_quicklook.png"))
ql.close()
pump(0.2)

# Видео: превью-кадр тоже есть.
p.tree.setCurrentItem(p.items[vgroup[0].path])
pump(2.5)
check(all(c.thumb.pixmap() is not None and not c.thumb.pixmap().isNull() for c in p.cards.values()),
      "у видео в сравнении есть кадр")
shot("qt_compare_video.png")


def inside(widget):
    tl = widget.mapTo(w, widget.rect().topLeft())
    return widget.isVisible() and tl.x() >= 0 and tl.y() >= 0 and \
        tl.x() + widget.width() <= w.width() and tl.y() + widget.height() <= w.height()


w.resize(w.minimumSize())
pump(0.5)
check(w.height() <= w.minimumHeight() + 2, f"окно сжато до минимума ({w.width()}x{w.height()})")
for name, wdg in [("Удалить отмеченные", p.btn_delete), ("Найти дубликаты", p.btn_scan), ("Остановить", p.btn_stop)]:
    check(inside(wdg), f"кнопка «{name}» видна в окне минимального размера")
check(p.tree.width() > 300, f"список не сжался ({p.tree.width()} px)")
check(p.summary.width() >= p.summary.sizeHint().width(),
      f"строка итогов влезает целиком ({p.summary.width()} из {p.summary.sizeHint().width()} px)")
shot("qt_min.png")
w.resize(1320, 880)
pump(0.3)

# Зазор между списком и сравнением; полоса прокрутки на длинном списке видна и заметна.
gap = p.split.widget(1).geometry().left() - p.split.widget(0).geometry().right()
check(gap >= 12, f"между списком и сравнением есть зазор ({gap} px)")
saved = (p.groups, set(p.marked))
p.groups = [[dupcore.MediaFile(os.path.join(root, f"g{g}", f"f{i}.jpg"), 1000 + g, now - i) for i in range(2)]
            for g in range(300)]
p.apply_rule()
pump(0.4)
sb = p.tree.verticalScrollBar()
check(sb.isVisible() and sb.maximum() > 0, "на длинном списке есть полоса прокрутки")
img = sb.grab().toImage()
track = img.pixelColor(img.width() // 2, img.height() - 3)
handle = img.pixelColor(img.width() // 2, 30)
check(abs(handle.lightness() - track.lightness()) > 40,
      f"ползунок заметен на дорожке (яркость {handle.lightness()} против {track.lightness()})")
p.groups, p.marked = saved
p.refresh()
pump(0.2)

marked_before = set(p.marked)
p.delete_marked()
pump()
left = [f for f in glob.glob(os.path.join(root, "**", "*"), recursive=True) if os.path.isfile(f)]
check(all(not os.path.exists(x) for x in marked_before), "все отмеченные ушли с диска")
check(len(left) == 9 - len(marked_before), f"на диске осталось {len(left)}")
check(os.path.exists(old), "оставленный IMG_0001 на месте")
check(p.groups == [] and p.stack.currentIndex() == 0, "после удаления групп нет, показана заглушка")
check(any(a[0] == "yesno" and "Корзину" in a[1] for a in answers), "было подтверждение перед удалением")

# Ход поиска на большой папке: шаг 3, 40 из 100 ГБ за 400 секунд.
GB = 1024 ** 3
p.busy = True
p.clock = dups_page.StepClock()
p._show_progress(3, "Сверяю содержимое целиком", 0, 100 * GB, "bytes")
p.clock.start -= 400
p._show_progress(3, "Сверяю содержимое целиком", 40 * GB, 100 * GB, "bytes")
p.elapsed.setText("прошло 7 мин")
check(p.step_text.text() == "Шаг 3 из 3 · Сверяю содержимое целиком", "номер шага: " + p.step_text.text())
check("осталось ≈ 10 мин" in p.status.text() and "102,4 МБ/с" in p.status.text(),
      "время и скорость: " + p.status.text())
check(w.windowTitle() == "Duplio — шаг 3 из 3, 40%", "ход в заголовке: " + w.windowTitle())
shot("qt_progress.png")
p.busy = False

# Находки во время поиска: группа появляется сразу, её можно удалить, не дожидаясь конца.
sx = put("Поток/a.jpg", os.urandom(50_000))
sy = put("Поток/b.jpg", open(sx, "rb").read())
os.utime(sx, (now - 999, now - 999))
p._set_busy(True)
stream_group = [dupcore.MediaFile(x, os.path.getsize(x), os.path.getmtime(x)) for x in (sx, sy)]
p.bridge.group.emit(stream_group)
pump(0.6)                                   # таймер добавления раз в 0,4 с
check(any(m.path == sy for g in p.groups for m in g) and sy in p.items, "группа, найденная во время поиска, сразу в списке")
check(sy in p.marked and p.btn_delete.isEnabled(), "её можно удалить во время поиска")
check("поиск продолжается" in p.summary.text(), "в итоге видно, что поиск ещё идёт: " + p.summary.text())
p.delete_marked()
pump()
check(not os.path.exists(sy) and os.path.exists(sx), "удаление во время поиска: копия в Корзине, оригинал на месте")
p._set_busy(False)

# Дата до 1970 года (камеры со сбитыми часами): строка показывает «—», список и отметки не расходятся.
dx = put("Старьё/a.jpg", os.urandom(30_000))
dy = put("Старьё/b.jpg", open(dx, "rb").read())
p._set_busy(True)
p.bridge.group.emit([dupcore.MediaFile(dx, os.path.getsize(dx), -100.0),
                     dupcore.MediaFile(dy, os.path.getsize(dy), -50.0)])
pump(0.6)
check(dx in p.items and dy in p.items and p.items[dy].text(3) == "—", "файл с датой до 1970 года виден, дата «—»")
consistent = all((path in p.marked) == (it.checkState(0) == Qt.Checked) for path, it in p.items.items())
orphans = [x for x in p.marked if x not in p.items]
check(consistent and not orphans, f"отметки совпадают со списком, невидимых отмеченных нет ({orphans[:2]})")

# «Снять все отметки» во время поиска: новые находки тоже не помечаются сами.
p.unmark_all()
ex = put("Новое/a.jpg", os.urandom(20_000))
ey = put("Новое/b.jpg", open(ex, "rb").read())
os.utime(ex, (now - 50, now - 50))             # настоящие даты: старший ex — оставляемый


def real(path):
    return dupcore.MediaFile(path, os.path.getsize(path), os.path.getmtime(path))


p.bridge.group.emit([real(ex), real(ey)])
pump(0.6)
check(ey in p.items and not p.marked, "после «Снять все отметки» новые группы не помечаются без тебя")
p._set_busy(False)

# Смена правила после ручных отметок — с вопросом; «Нет» оставляет всё как было.
p.toggle_file(next(m for g in p.groups for m in g if m.path == ey))
before_marks, before_rule = set(p.marked), p.rule.currentIndex()
answers.clear()
ui_util.ask_yes_no = lambda parent, text, **k: answers.append(("yesno", text)) or False
p.rule.setCurrentIndex((before_rule + 1) % p.rule.count())
pump()
check(any("сбросятся" in a[1] for a in answers) and p.rule.currentIndex() == before_rule
      and p.marked == before_marks, "смена правила спрашивает и при «Нет» ничего не трогает")

# Повторная проверка после подтверждения: пока окно было открыто, оставляемая копия пропала — удалять нельзя.
def confirm_and_remove_kept(parent, text, **k):
    answers.append(("yesno", text))
    os.remove(ex)                      # «другая программа» удалила оставляемую копию
    return True


ui_util.ask_yes_no = confirm_and_remove_kept
p.delete_marked()
pump()
check(os.path.exists(ey), "если оставляемая копия пропала во время подтверждения — вторая не удаляется")

# Диск без Корзины: честное предупреждение «навсегда».
fx = put("Флешка/a.jpg", os.urandom(20_000))
fy = put("Флешка/b.jpg", open(fx, "rb").read())
os.utime(fx, (now - 50, now - 50))
p._set_busy(True)
p.automark = True
p.bridge.group.emit([real(fx), real(fy)])
pump(0.6)
p._set_busy(False)
answers.clear()
asked = {}
ui_util.ask_yes_no = lambda parent, text, **k: asked.update(text=text, yes=k.get("yes")) or False
saved_bin = dupcore.has_recycle_bin
dupcore.has_recycle_bin = lambda d: False
p.delete_marked()
dupcore.has_recycle_bin = saved_bin
check("НАВСЕГДА" in asked.get("text", "") and asked.get("yes") == "Удалить навсегда",
      "на диске без Корзины предупреждение «удалятся навсегда» и кнопка «Удалить навсегда»")
ui_util.ask_yes_no = lambda parent, text, **k: answers.append(("yesno", text)) or True

w.tabs.setCurrentWidget(w.settings)
shot("qt_settings.png")
w.settings.load_cards["fast"].radio.setChecked(True)
pump()
check(cfg["load"] == "fast" and "быстрая" in p.load_text.text(), "выбор нагрузки доходит до вкладки поиска")
check(os.path.exists(settings.PATH), "настройки сохранены (во временную папку теста)")
w.tabs.setCurrentWidget(w.compress)
shot("qt_compress.png")

# Трей: крестик прячет окно, программа работает; «Выход» — закрывает.
cfg["close_to_tray"] = True
quit_called = []
qapp.quit = lambda: quit_called.append(True)
w.close()
pump(0.3)
check(not w.isVisible() and w.tray.isVisible() and not quit_called, "крестик сворачивает в трей, программа работает")
check(cfg["tray_hint_shown"], "подсказка про трей показана один раз")
w.bring_back()
pump(0.3)
check(w.isVisible(), "щелчок по значку возвращает окно")
w.quit_app()
pump(0.3)
check(quit_called and not w.tray.isVisible(), "«Выход» закрывает программу и убирает значок")
check(not slot_errors, f"ни одной ошибки в обработчиках окна (было {len(slot_errors)})")
shutil.rmtree(root, ignore_errors=True)
shutil.rmtree(tmp_cfg, ignore_errors=True)
print("\nИТОГ:", "всё прошло" if not fails else f"провалов {len(fails)}")
sys.exit(1 if fails else 0)
