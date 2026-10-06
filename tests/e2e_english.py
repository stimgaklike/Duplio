"""Английский интерфейс: ни одной строки с русскими буквами нигде в окне, диалогах и подсказках.

Запуск: python tests/e2e_english.py [папка_для_снимков]
"""

import atexit
import os
import re
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import i18n  # noqa: E402
import settings  # noqa: E402

i18n.set_lang("en")
tmp_cfg = tempfile.mkdtemp(prefix="dup_cfg_")
atexit.register(shutil.rmtree, tmp_cfg, True)          # убрать и при обрыве прогона
settings.DIR, settings.PATH = tmp_cfg, os.path.join(tmp_cfg, "settings.json")

from PySide6.QtWidgets import (QAbstractButton, QApplication, QComboBox, QLabel, QLineEdit, QMenu,  # noqa: E402
                               QTabBar, QTreeWidget, QWidget)

import app  # noqa: E402
import dups_page  # noqa: E402
import ui_util  # noqa: E402
import updater  # noqa: E402

CYR = re.compile("[А-Яа-яЁё]")
ALLOWED = {"Русский"}       # название языка пишут на нём самом — чтобы найти свой язык в чужом интерфейсе
shots = sys.argv[1] if len(sys.argv) > 1 else tempfile.gettempdir()
root = tempfile.mkdtemp(prefix="dup_en_")
atexit.register(shutil.rmtree, root, True)          # убрать и при обрыве прогона
said = []
ui_util.ask_yes_no = lambda parent, text, **k: said.append(text) or True
ui_util.info = lambda parent, text: said.append(text)
ui_util.warn = lambda parent, text: said.append(text)
ui_util.reveal = lambda path: None                        # не открывать настоящий Проводник
ui_util.open_file = lambda path: None


def put(rel, data):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)
    return p


data = os.urandom(300_000)
put("a/photo.jpg", data)
put("b/photo copy.jpg", data)
put("c/clip.mp4", data[:200_000])
put("d/clip2.mp4", data[:200_000])

qapp = QApplication(sys.argv)
cfg = settings.load()
cfg["lang"] = "en"
w = app.MainWindow(cfg)
w.show()
p = w.dups
found = {}


def pump(sec=0.3):
    t = time.time()
    while time.time() - t < sec:
        qapp.processEvents()
        time.sleep(0.01)


def scan_widgets(where):
    for wd in [w] + w.findChildren(QWidget) + [x for x in QApplication.topLevelWidgets() if x is not w]:
        texts = [wd.toolTip(), wd.windowTitle() if wd.isWindow() else ""]
        if isinstance(wd, (QLabel, QAbstractButton)):
            texts.append(wd.text())
        if isinstance(wd, QAbstractButton) and re.search(r"&(?!&)", wd.text()):
            found.setdefault(wd.text() + "  ← одиночный & на кнопке Qt съест", where)
        if isinstance(wd, QLineEdit):
            texts.append(wd.placeholderText())
        if isinstance(wd, QComboBox):
            texts += [wd.itemText(i) for i in range(wd.count())]
        if isinstance(wd, QMenu):
            texts += [a.text() for a in wd.actions()]
        if isinstance(wd, QTabBar):
            texts += [wd.tabText(i) for i in range(wd.count())]
        if isinstance(wd, QTreeWidget):
            texts += [wd.headerItem().text(i) for i in range(wd.columnCount())]
            for i in range(wd.topLevelItemCount()):
                top = wd.topLevelItem(i)
                texts += [top.text(c) for c in range(wd.columnCount())] + \
                    [top.toolTip(c) for c in range(wd.columnCount())]
                for j in range(top.childCount()):
                    ch = top.child(j)
                    texts += [ch.text(c) for c in range(wd.columnCount())] + [ch.toolTip(0)]
        for t in texts:
            if t and CYR.search(t) and t not in ALLOWED:
                found.setdefault(t, where)


pump(0.5)
scan_widgets("старт")
p.chips["other"].setChecked(True)          # подсказка про «остальные файлы»
pump()
scan_widgets("подсказка «остальные»")
p.chips["other"].setChecked(False)
p.folder.setText(root)
p.start_scan()
t0 = time.time()
while p.busy and time.time() - t0 < 30:
    pump(0.05)
pump(1.5)
scan_widgets("после поиска")
w.grab().save(os.path.join(shots, "en_dups.png"))
p.tree.setCurrentItem(p.items[p.groups[0][0].path])
pump(1)
scan_widgets("сравнение")
ql = dups_page.QuickLook(p, p.groups[0], 0)
ql.show()
pump(0.4)
scan_widgets("быстрый просмотр")
ql.close()
first = p.groups[0]
p.toggle_file(first[1])
p.toggle_file(first[0])
p.toggle_file(first[1])                    # последняя копия — предупреждение
p._show_progress(1, "Ищу файлы", 10, 0, "files")
p.busy = True
p._show_progress(3, "Сверяю содержимое целиком", 5, 10, "bytes")
p.busy = False
scan_widgets("ход поиска")
p.delete_marked()
pump()
scan_widgets("после удаления")
# ---- «Сжатие»: оба режима, сравнение крупно, несжатые, замена, трей, выход
import compcore  # noqa: E402
import compress_page  # noqa: E402
from test_compcore import make_video, photo, save_jpeg  # noqa: E402

compcore.WORK = tempfile.mkdtemp(prefix="dup_en_work_")

atexit.register(shutil.rmtree, compcore.WORK, True)          # убрать и при обрыве прогона
croot = tempfile.mkdtemp(prefix="dup_en_cmp_")
atexit.register(shutil.rmtree, croot, True)          # убрать и при обрыве прогона
save_jpeg(photo(noise=0), os.path.join(croot, "a.jpg"), quality=97)
save_jpeg(photo(400, 300, seed=3), os.path.join(croot, "low.jpg"), quality=80)
make_video(os.path.join(croot, "v.mp4"), seconds=1, extra=("-b:v", "6M"))
c = w.compress
w.tabs.setCurrentWidget(c)
tray_said = []
w.tray.showMessage = lambda title, text, *a: tray_said.extend([title, text])
for mode in ("lossless", "visual"):
    c.mode_btns[mode].click()
    pump(0.2)
    scan_widgets(f"сжатие: режим {mode}")
    c.folder.setText(croot)
    c.start()
    c.busy = True
    c._show_progress(0, 0, 0, 3, "")
    scan_widgets("сжатие: обход папок")
    t0 = time.time()
    while c.busy and time.time() - t0 < 60:
        pump(0.05)
    pump(1.5)
    scan_widgets(f"сжатие: готово ({mode})")
    if c.ready:
        c.tree.setCurrentItem(c.items[c.ready[-1].path])
        pump(1)
        scan_widgets("сжатие: было → стало")
        dlg = compress_page.CompareDialog(c, c.ready, len(c.ready) - 1)
        dlg.show()
        pump(0.4)
        scan_widgets("сжатие: сравнение крупно")
        dlg.close()
    if c.skipped:
        c.show_skipped()
    c.busy = True
    c._show_progress(50, 100, 1, 3, "v.mp4")
    c._update_summary()
    scan_widgets("сжатие: ход")
    c.busy = False
    for note in filter(None, [w.busy_note()]):
        said.extend(x for x in note if isinstance(x, str))
# Перетаскивание: подсказки поверх окна и «Перетащено: …» во «Сжатии».
for tab, items in ((c, [os.path.join(croot, "a.jpg"), os.path.join(croot, "v.mp4")]), (c, [croot]),
                   (w.dups, [os.path.join(croot, "a.jpg")]), (w.settings, [croot, os.path.join(croot, "a.jpg")])):
    w.tabs.setCurrentWidget(tab)
    page, title, sub = w.drop_plan(items)
    said.extend([title, sub])
c.use_files([os.path.join(croot, "a.jpg"), croot])
w.tabs.setCurrentWidget(c)
pump(0.2)
scan_widgets("сжатие: перетащенные файлы")
c.busy = True
said.extend(w.drop_plan([croot])[1:])
c.busy = False
c.use_files(None)
w.hide()                                   # уведомление в трее — только когда окна не видно
w._compress_finished(2, 1000)
w._compress_finished(0, 0)
w.show()
check_tray = len(tray_said) == 4
c.replace_marked()
pump()
scan_widgets("сжатие: после замены")
if not check_tray:
    found.setdefault(f"уведомления трея не пришли: {tray_said}", "трей")
for t in tray_said:
    if CYR.search(t):
        found.setdefault(t, "трей")
# ---- «Метаданные»: проверка, наборы, «было → стало», копии, замена, ход, перетаскивание
import dupcore  # noqa: E402
import metacore  # noqa: E402
from test_metacore import make_video as meta_video, phone_jpeg  # noqa: E402

metacore.WORK = tempfile.mkdtemp(prefix="dup_en_meta_work_")
atexit.register(shutil.rmtree, metacore.WORK, True)
mroot = tempfile.mkdtemp(prefix="dup_en_meta_")
atexit.register(shutil.rmtree, mroot, True)
os.makedirs(os.path.join(mroot, "trip"))
phone_jpeg(os.path.join(mroot, "trip", "a.jpg"))
phone_jpeg(os.path.join(mroot, "b.jpg"))
meta_video(os.path.join(mroot, "trip", "v.mp4"), "-movflags", "use_metadata_tags")
with open(os.path.join(mroot, "broken.jpg"), "wb") as f:
    f.write(b"\xff\xd8\xff\xe0 not a picture")
mbin = tempfile.mkdtemp(prefix="dup_en_meta_bin_")
atexit.register(shutil.rmtree, mbin, True)
dupcore.to_recycle_bin = lambda paths, hwnd=None, **k: ([shutil.move(x, mbin) and x for x in paths], [])
mp = w.meta
w.tabs.setCurrentWidget(mp)
pump(0.2)
scan_widgets("метаданные: старт")
for key in ("place", "custom", "all"):
    mp.preset_btns[key].click()
    pump(0.1)
    scan_widgets(f"метаданные: набор {key}")
mp.folder.setText(mroot)
mp.start()
mp._show_progress("scan", 0, 3, "")
scan_widgets("метаданные: обход папок")
t0 = time.time()
while mp.busy and time.time() - t0 < 60:
    pump(0.05)
pump(0.5)
scan_widgets("метаданные: прочитано")
for it in mp.shown:
    mp.tree.setCurrentItem(mp.tree_items[it.path])
    pump(0.3)
    scan_widgets("метаданные: было → стало")
mp.show_skipped()
mp.busy = True
for step in ("scan", "clean", "replace", "copies"):
    mp._show_progress(step, 1, 3, "a.jpg")
    scan_widgets(f"метаданные: ход {step}")
for note in filter(None, [w.busy_note()]):
    said.extend(x for x in note if isinstance(x, str))
said.extend(w.drop_plan([mroot])[1:])
mp.busy = False
for items in ([mroot], [os.path.join(mroot, "b.jpg"), mroot]):
    page, title, sub = w.drop_plan(items)
    said.extend([title, sub])
mp.preset_btns["place"].click()
mp.output_btns["copies"].click()
pump(0.2)
scan_widgets("метаданные: копии")
mp.run_marked()
t0 = time.time()
while mp.busy and time.time() - t0 < 60:
    pump(0.05)
pump(0.3)
mp.output_btns["replace"].click()
mp.preset_btns["all"].click()
mp.run_marked()
t0 = time.time()
while mp.busy and time.time() - t0 < 60:
    pump(0.05)
pump(0.3)
scan_widgets("метаданные: после замены")
mp.copies.setText("")
mp.output_btns["copies"].click()
mp.copies.setText("")
mp.run_marked()                              # без папки — предупреждение
w.grab().save(os.path.join(shots, "en_meta.png"))
for page in (w.compress, w.meta, w.settings):
    w.tabs.setCurrentWidget(page)
    pump(0.3)
    scan_widgets(page.__class__.__name__)
w.settings._lang_picked("ru")
w.settings.set_update_status(i18n.tr("Установлена последняя версия."))
pump()
scan_widgets("настройки: язык и обновления")
w.grab().save(os.path.join(shots, "en_settings.png"))
fake = updater.Update("9.9.9", "- Faster scan", "file:///nonexistent", 1, "", "")
w._update_found(fake)
dlg = app.UpdateDialog(w, fake)
dlg.show()
dlg._progress(5, 10)
dlg._downloaded("x")
pump(0.3)
scan_widgets("обновление")
dlg.close()
w._scan_finished(3, 1000)
for t in said:
    if CYR.search(t):
        found.setdefault(t, "диалог")

w.quit_app()
shutil.rmtree(root, ignore_errors=True)
shutil.rmtree(croot, ignore_errors=True)
shutil.rmtree(tmp_cfg, ignore_errors=True)
if found:
    print(f"FAIL русские строки в английском интерфейсе: {len(found)}")
    for t, where in found.items():
        print(f"   [{where}] {t!r}")
else:
    print("OK   в английском интерфейсе нет ни одной русской строки")
print("ИТОГ:", "всё прошло" if not found else "провалов 1")
sys.exit(1 if found else 0)
