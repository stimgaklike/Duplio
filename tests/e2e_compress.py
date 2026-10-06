"""Вкладка «Сжатие» целиком: строго без потерь → замена, без видимых потерь с видео, сравнение крупно.

Запуск: python tests/e2e_compress.py [папка_для_снимков] [light|dark]
Окно появится на экране. Диалоги подменены автоответом «да». Оригиналы уходят в настоящую Корзину
(это свои тестовые файлы во временной папке). Настройки — во временной папке.
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

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

qapp = QApplication(sys.argv)

import app  # noqa: E402
import compcore  # noqa: E402
import compress_page  # noqa: E402
import dupcore  # noqa: E402
import ui_util  # noqa: E402
from test_compcore import make_video, photo, save_jpeg  # noqa: E402

shots = sys.argv[1] if len(sys.argv) > 1 else tempfile.gettempdir()
mode = sys.argv[2] if len(sys.argv) > 2 else "system"
root = tempfile.mkdtemp(prefix="dup_cmp_e2e_")
atexit.register(shutil.rmtree, root, True)          # убрать и при обрыве прогона
work = tempfile.mkdtemp(prefix="dup_cmp_work_")
atexit.register(shutil.rmtree, work, True)          # убрать и при обрыве прогона
compcore.WORK = work


def p(rel):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


img1 = save_jpeg(photo(noise=6), p(r"Телефон\IMG_0001.jpg"), quality=95)      # «без видимых» не пройдёт
img2 = save_jpeg(photo(noise=0, seed=2), p(r"Телефон\IMG_0002.jpg"), quality=97)
low = save_jpeg(photo(800, 600, seed=3), p(r"Разное\маленькое.jpg"), quality=80)
from PIL import Image  # noqa: E402
import numpy as np  # noqa: E402

a = np.zeros((500, 700, 3), np.uint8)
a[..., 0], a[..., 1] = 230, np.arange(700) % 256
Image.fromarray(a).save(p(r"Скриншоты\экран.png"), compress_level=1)
clip = make_video(p(r"Видео\отпуск.mp4"), seconds=2, extra=("-b:v", "6M"))
sizes0 = {x: os.path.getsize(x) for x in (img1, img2, low, p(r"Скриншоты\экран.png"), clip)}

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
c = w.compress
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


def face(btn):
    """Самый частый цвет кнопки (её заливка) на снимке."""
    from collections import Counter
    img = btn.grab().toImage()
    pts = [(x, y) for y in range(4, img.height() - 4) for x in range(6, img.width() - 6)]
    return Counter(img.pixelColor(x, y).name() for x, y in pts).most_common(1)[0][0]


def ink_share(widget):
    """Доля точек, отличных от фона виджета: есть ли на нём картинка, а не пустая подложка."""
    img = widget.grab().toImage()
    bg = QColor(w.colors["surface2"])
    pts = [(x, y) for y in range(0, img.height(), 3) for x in range(0, img.width(), 3)]
    return sum(img.pixelColor(x, y) != bg for x, y in pts) / len(pts)


def layout_problems():
    """Что на вкладке обрезано или сплющено: перенос не влез по высоте, надпись кнопки не влезла по ширине,
    поле или кнопка ниже своей минимальной высоты, текст в ячейке списка обрезан."""
    from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton
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
        for col in (2, 3, 4, 5):
            need = c.tree.fontMetrics().horizontalAdvance(it.text(col)) + 12
            if need > c.tree.columnWidth(col):
                bad.append(f"ячейка «{it.text(col)}» {c.tree.columnWidth(col)} из {need}")
    return sorted(set(bad))


pump(0.6)

# ---------- начальное состояние
check(c.mode() == "lossless" and c.mode_btns["lossless"].isChecked() and not c.mode_btns["visual"].isChecked(),
      "по умолчанию «Строго без потерь»")
check(face(c.mode_btns["lossless"]) == w.colors["accent"] and face(c.mode_btns["visual"]) != w.colors["accent"],
      f"выбранный режим на экране выделен ({face(c.mode_btns['lossless'])}, {face(c.mode_btns['visual'])})")
check("байт в байт" in c.mode_text.text(), "под режимом — его пояснение")
check(not c.chips["video"].isEnabled() and c.chips["photo"].isEnabled(), "видео в строгом режиме недоступно")
check(face(c.chips["video"]) != face(c.chips["photo"]),
      f"недоступное «Видео» выглядит иначе, чем «Фото» ({face(c.chips['video'])} и {face(c.chips['photo'])})")
check(c.kinds() == {"photo"}, f"сжимать — только фото ({c.kinds()})")
check(c.btn_replace.text() == "Заменить оригиналы" and not c.btn_replace.isEnabled(), "кнопка замены неактивна")
check(c.stack.currentIndex() == 0, "до подготовки — заглушка")
shot("qt_compress_start.png")

# ---------- строго без потерь
c.folder.setText(root)
c.start()
check(c.busy and not c.btn_start.isEnabled() and c.btn_stop.isEnabled(), "во время подготовки «Остановить» активна")
check(w.busy_note() is not None and "сжатие" in w.busy_note()[1], "при выходе во время сжатия — предупреждение")
wait(lambda: not c.busy)
pump(0.5)
names = sorted(os.path.basename(j.path) for j in c.ready)
check(names == ["IMG_0001.jpg", "IMG_0002.jpg", "маленькое.jpg", "экран.png"], f"готовы четыре фото: {names}")
check(all(j.check == "pixels" for j in c.ready), "все проверены по пикселям")
check(c.tree.topLevelItemCount() == 4 and c.stack.currentIndex() == 1, "в списке 4 строки")
check(all(c.items[j.path].text(5) == "байт в байт" for j in c.ready), "в столбце «Проверка» — «байт в байт»")
check(all(c.items[j.path].checkState(0) == Qt.Checked for j in c.ready), "все отмечены к замене")
saved = sum(j.saved for j in c.ready)
want = f"Заменить 4 файла  ·  освободится {dupcore.human_size(saved)}"
check(c.btn_replace.text() == want and c.btn_replace.isEnabled(), f"кнопка: «{c.btn_replace.text()}» (ждали «{want}»)")
check(c.step_text.text().startswith("Готово за"), "итог: " + c.step_text.text())
check(w.windowTitle() == "Duplio", "после подготовки заголовок обычный: " + w.windowTitle())

# Сравнение справа: обе картинки загружены и видны.
first = c.ready[0]
c.tree.setCurrentItem(c.items[first.path])
wait(lambda: c.pic_old.img is not None and c.pic_new.img is not None, 10)
pump(0.3)
check(c.pic_old.img is not None and c.pic_new.img is not None, "превью «было» и «стало» загружены")
check(ink_share(c.pic_old) > 0.3 and ink_share(c.pic_new) > 0.3,
      f"на превью есть изображение ({ink_share(c.pic_old):.2f}, {ink_share(c.pic_new):.2f})")
check("пиксели совпадают байт в байт" in c.cmp_how.text(), "под превью сказано, чем проверено")
shot("qt_compress_lossless.png")
check(not layout_problems(), f"ничего не обрезано и не сплющено: {layout_problems()}")

# Сравнение крупно: при 100 % в центре каждой половины — тот самый пиксель картинки.
big_i = next(i for i, j in enumerate(c.ready) if j.path == img1)
dlg = compress_page.CompareDialog(c, c.ready, big_i)
dlg.show()
pump(0.4)
v = dlg.view
check(v.a is not None and not v.a.isNull() and v.a.size() == v.b.size(), "крупно: обе картинки, одного размера")
v.set_zoom(1.0)
pump(0.2)
check(dlg.zoom_btns[1].isChecked(), "кнопка «100 %» нажата")


def centers():
    img = v.grab().toImage()
    dpr = img.devicePixelRatio()
    left, right = v.halves()
    out = []
    for r, src in ((left, v.a), (right, v.b)):
        px = img.pixelColor(int(r.center().x() * dpr), int(r.center().y() * dpr))
        # центр половины показывает точку center картинки (с округлением в пределах пикселя)
        cx, cy = int(v.center.x()), int(v.center.y())
        near = [src.pixelColor(x, y) for x in (cx - 1, cx, cx + 1) for y in (cy - 1, cy, cy + 1)]
        out.append(min(max(abs(px.red() - q.red()), abs(px.green() - q.green()), abs(px.blue() - q.blue()))
                       for q in near))
    return out


check(max(centers()) <= 2, f"100 %: центр половин = центр картинки (расхождение {centers()})")
c0 = QPointF(v.center)
press = QMouseEvent(QMouseEvent.MouseButtonPress, QPointF(300, 200), QPointF(300, 200), Qt.LeftButton,
                    Qt.LeftButton, Qt.NoModifier)
move = QMouseEvent(QMouseEvent.MouseMove, QPointF(240, 170), QPointF(240, 170), Qt.LeftButton, Qt.LeftButton,
                   Qt.NoModifier)
v.mousePressEvent(press)
v.mouseMoveEvent(move)
v.mouseReleaseEvent(press)
pump(0.2)
d = v.center - c0
s = v.scale()
check(abs(d.x() - 60 / s) < 0.01 and abs(d.y() - 30 / s) < 0.01, f"перетаскивание сдвинуло обе половины ({d.x():.1f}, {d.y():.1f})")
check(max(centers()) <= 2, f"после сдвига центры половин снова совпадают с картинкой ({centers()})")
dlg.grab().save(os.path.join(shots, "qt_compress_compare.png"))
for _ in range(5):                                         # утащить далеко за край
    v.mousePressEvent(press)
    v.mouseMoveEvent(QMouseEvent(QMouseEvent.MouseMove, QPointF(900, 700), QPointF(900, 700), Qt.LeftButton,
                                 Qt.LeftButton, Qt.NoModifier))
    v.mouseReleaseEvent(press)
pump(0.2)
img = v.grab().toImage()
dpr = img.devicePixelRatio()
bg = QColor(w.colors["surface2"])
lr = v.halves()[0]
corners = [img.pixelColor(int(x * dpr), int(y * dpr)) for x, y in
           ((lr.left() + 3, lr.top() + 40), (lr.right() - 3, lr.top() + 40),
            (lr.left() + 3, lr.bottom() - 3), (lr.right() - 3, lr.bottom() - 3))]
check(all(px != bg for px in corners),
      f"за край картинку не утащить: в углах половины — картинка, не подложка ({[q.name() for q in corners]}, "
      f"подложка {bg.name()}, центр {v.center.x():.0f},{v.center.y():.0f}, картинка {v.a.width()}x{v.a.height()}, "
      f"масштаб {v.scale():.3f}, половина {lr.width():.0f}x{lr.height():.0f})")
check(max(centers()) <= 2, f"и у края центры половин совпадают с картинкой ({centers()})")
dlg.go(1)
check(dlg.counter.text() == f"{(big_i + 1) % 4 + 1} из 4",
      f"листание в сравнении: {dlg.counter.text()} (был {big_i + 1} из 4)")
dlg.close()

# Снять отметку с одного файла: число и сумма на кнопке меняются ровно на него.
keep = next(j for j in c.ready if j.path == low)
c.items[keep.path].setCheckState(0, Qt.Unchecked)
pump(0.1)
want = f"Заменить 3 файла  ·  освободится {dupcore.human_size(saved - keep.saved)}"
check(c.btn_replace.text() == want, f"после снятия отметки: «{c.btn_replace.text()}»")
check(w.busy_note() is not None and "не заменили" in w.busy_note()[1], "при выходе с незаменёнными копиями — предупреждение")
# Обновление тоже закрывает программу: с незаменёнными копиями — сначала вопрос; «Позже» — установщик не запускается.
import updater  # noqa: E402
installed = []
updater.install = lambda path: installed.append(path)
ui_util.ask_yes_no = lambda parent, text, **k: answers.append(("yesno", text)) and False
upd = app.UpdateDialog(w, updater.Update("9.9.9", "", "file:///x", 1, "", ""))
upd.path = "x.exe"
answers.clear()
upd._go()
check(installed == [] and any("копии не заменили" in a[1] for a in answers),
      f"обновление с незаменёнными копиями спрашивает, «Позже» — не ставит ({installed}, {answers[-1:]})")
upd.close()
ui_util.ask_yes_no = lambda parent, text, **k: answers.append(("yesno", text)) or True
expect = {j.path: (j.new_size, j.mtime) for j in c.ready if j.path in c.marked}
c.replace_marked()
pump(0.5)
check(all(os.path.getsize(path) == size for path, (size, _) in expect.items()), "заменённые файлы стали сжатыми")
check(all(abs(os.path.getmtime(path) - mt) < 1e-6 for path, (_, mt) in expect.items()), "даты изменения прежние")
check(os.path.getsize(low) == sizes0[low], "файл без отметки не тронут")
check([j.path for j in c.ready] == [low] and c.tree.topLevelItemCount() == 1, "в списке остался только неотмеченный")
check(any(a[0] == "yesno" and "Корзину" in a[1] for a in answers), "было подтверждение перед заменой")
check(any(a[0] == "info" and a[1].startswith("Заменено файлов: 3.") for a in answers), "итог замены показан")
check(not [x for x in os.listdir(os.path.dirname(img1)) if x.startswith("~")], "временных файлов рядом не осталось")

# ---------- без видимых потерь, с видео
c.mode_btns["visual"].click()
pump(0.2)
check(c.mode() == "visual" and c.chips["video"].isEnabled(), "«Без видимых потерь»: видео доступно")
check("AV1" in c.kinds_note.text() and "AV1 Video Extension" in c.kinds_note.toolTip(),
      "рядом с типами сказано про AV1, в подсказке — про расширение для Windows 10")
check("SSIM" not in c.mode_text.text() and "AV1" in c.mode_text.text(), "пояснение сменилось на режим «без видимых»")
answers.clear()
c._mark_all(True)                         # оставшаяся копия снова отмечена — её потеря требует вопроса
c.start()
check([x[1] for x in answers if x[0] == "yesno"] ==
      ["Подготовленные копии ещё не заменили оригиналы. Начать заново? Они пропадут."],
      "перед новой подготовкой спросили про незаменённые копии")
wait(lambda: not c.busy, 120)
pump(0.5)
names = sorted(os.path.basename(j.path) for j in c.ready)
skipped = {os.path.basename(j.path): j.skip for j in c.skipped}
check("отпуск.mp4" in names, f"видео сжато: {names}")
check(skipped.get("маленькое.jpg") == "уже сжат сильно — дальше будут видны потери",
      f"слабый JPEG не тронут: {skipped.get('маленькое.jpg')}")
check(c.btn_skipped.isVisible() and c.btn_skipped.text() == f"Не сжаты: {len(c.skipped)}", c.btn_skipped.text())
vid = next(j for j in c.ready if j.is_video)
check(c.items[vid.path].text(5).startswith("SSIM "), "у видео проверка — SSIM: " + c.items[vid.path].text(5))
c.tree.setCurrentItem(c.items[vid.path])
wait(lambda: c.pic_old.img is not None and c.pic_new.img is not None, 20)
pump(0.3)
check(c.pic_old.img is not None and c.pic_new.img is not None and c.pic_old.img.size() == c.pic_new.img.size(),
      "у видео — кадры «было» и «стало» одного размера")
check(ink_share(c.pic_new) > 0.3, f"кадр сжатого видео виден ({ink_share(c.pic_new):.2f})")
shot("qt_compress_visual.png")
c.show_skipped()
check(any(a[0] == "info" and "уже сжат сильно" in a[1] for a in answers), "список несжатых с причинами")

# ---------- установщик просит закрыться (тот же канал, что у второго запуска)
from PySide6.QtCore import QByteArray  # noqa: E402
from PySide6.QtNetwork import QLocalSocket  # noqa: E402

app.INSTANCE_KEY = f"Duplio-e2e-{os.getpid()}"            # не настоящий канал: там может слушать открытый Duplio
server = app.listen(w)
quits, opened = [], []
real_quit, real_open = w.quit_app, w.open_folder
w.quit_app = lambda *a, **k: quits.append(1)
w.open_folder = lambda f: opened.append(f)


def send(data):
    sock = QLocalSocket()
    sock.connectToServer(app.INSTANCE_KEY)
    sock.waitForConnected(1000)
    sock.write(QByteArray(data))
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    pump(0.5)


send(app.QUIT_REQUEST.encode())
check((quits, opened) == ([1], []), f"просьба установщика закрывает программу ({quits}, {opened})")
send(root.encode("utf-8"))
check((quits, opened) == ([1], [root]), f"а папка от второго запуска — подставляется, не закрывает ({quits}, {opened})")
w.quit_app, w.open_folder = real_quit, real_open
server.close()

# ---------- окно минимального размера: ничего не вылезает
w.resize(w.minimumWidth(), w.minimumHeight())
pump(0.5)


def inside(widget):
    r = widget.rect()
    tl, br = widget.mapTo(w, r.topLeft()), widget.mapTo(w, r.bottomRight())
    return widget.isVisible() and tl.x() >= 0 and tl.y() >= 0 and br.x() < w.width() and br.y() < w.height()


for name, wd in (("Подготовить", c.btn_start), ("Остановить", c.btn_stop), ("Заменить", c.btn_replace)):
    check(inside(wd), f"кнопка «{name}» видна в окне минимального размера")
check(c.btn_replace.width() >= c.btn_replace.sizeHint().width(),
      f"надпись кнопки замены не обрезана ({c.btn_replace.width()} из {c.btn_replace.sizeHint().width()})")
fm = c.kinds_note.fontMetrics()
check(c.kinds_note.width() >= fm.horizontalAdvance(c.kinds_note.text()),
      f"пояснение к типам не обрезано ({c.kinds_note.width()} из {fm.horizontalAdvance(c.kinds_note.text())})")
check(c.tree.width() > 300, f"список не сжался ({c.tree.width()} px)")
check(c.minimumSizeHint().height() <= c.height(),
      f"вкладке хватает высоты: минимум {c.minimumSizeHint().height()} при {c.height()} — Qt ничего не сминает")
check(not layout_problems(), f"в окне минимального размера ничего не обрезано и не сплющено: {layout_problems()}")
check(c.tree.height() >= 150, f"список в окне минимального размера не ниже 150 px ({c.tree.height()})")
check(c.pic_old.width() >= 140 and c.pic_old.height() >= 110, f"превью не меньше {c.pic_old.width()}x{c.pic_old.height()}")
shot("qt_compress_min.png")

check(not slot_errors, f"ошибок в обработчиках нет ({len(slot_errors)})")
w.quit_app()
check(not os.path.exists(work) or not os.listdir(work), "при выходе рабочая папка очищена")
shutil.rmtree(root, ignore_errors=True)
shutil.rmtree(work, ignore_errors=True)
shutil.rmtree(tmp_cfg, ignore_errors=True)
print("ИТОГ:", "всё прошло" if not fails else f"провалов {len(fails)}")
sys.exit(1 if fails else 0)
