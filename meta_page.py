"""Вкладка «Метаданные»: что фото и видео рассказывают о человеке, и как это убрать без пересжатия."""

import os
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLineEdit, QMenu, QProgressBar, QPushButton, QSplitter,
                               QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import compcore
import dupcore
import metacore
import ui_util as U
from compress_page import Picture, Previews, WrapLabel
from dups_page import LOAD_NAMES, RowTint, StepClock, _problems_text
from i18n import num, plural, tr
from logs import log

FILE_ROLE = Qt.UserRole
PRESETS = {"all": "Всё", "place": "Только место", "custom": "Свой набор"}
SHORT = {"place": "место", "camera": "камера", "time": "время", "author": "автор", "thumb": "превью",
         "other": "прочее"}
OUTPUTS = {"replace": "Заменить оригиналы", "copies": "Сохранить копии в папку"}


def EMPTY_TEXT():
    return tr("Здесь появятся фото и видео, в которых есть что убрать: геометка, камера, время, автор.\n\n"
              "Программа ничего не пересжимает — меняются только служебные записи файла. Сначала проверь "
              "список и «было → стало», потом нажми кнопку внизу.")


def what_text(item, groups):
    """Что уберётся из файла: (короткая строка для списка — до трёх групп и «+N», полная — для подсказки)."""
    names = [tr(SHORT[g]) for g in metacore.GROUPS
             if g in groups and any(f.group == g for f in item.to_remove(groups))]
    short = ", ".join(names[:3]) + (f" +{len(names) - 3}" if len(names) > 3 else "")
    return short, ", ".join(names)


class Bridge(QObject):
    """Сигналы из рабочего потока в окно. object — чтобы большие числа не обрезались."""
    progress = Signal(str, object, object, str)       # шаг, сделано, всего, имя
    item = Signal(object)
    scanned = Signal(object)
    cleaned = Signal(object)
    failed = Signal(str)


class MetaPage(QWidget):
    title_changed = Signal(str)
    go_settings = Signal()
    settings_changed = Signal()

    def __init__(self, cfg, colors):
        super().__init__(objectName="page")
        self.cfg, self.colors = cfg, colors
        self.busy = False
        self.cancel = None
        self.result = None
        self.items = []             # прочитанные файлы
        self.shown = []             # в списке: те, в которых есть что убрать
        self.marked = set()
        self.tree_items = {}
        self.current = None
        self.scan_root = ""
        self.drop_files = None
        self._updating = False
        self._times = {}
        self.previews = Previews(360)
        self.previews.ready.connect(self._preview_ready)
        self.bridge = Bridge()
        self.bridge.progress.connect(self._show_progress)
        self.bridge.item.connect(lambda it: self.pending.append(it))
        self.bridge.scanned.connect(self._scan_done)
        self.bridge.cleaned.connect(self._clean_done)
        self.bridge.failed.connect(self._failed)
        self.pending = []
        self.ticker = QTimer(self, interval=1000)
        self.ticker.timeout.connect(self._tick)
        self._build()
        self.set_load_text()
        self._set_busy(False)

    # ---------- раскладка

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(16)
        root.addWidget(U.label(tr("Метаданные фото и видео"), "title"))

        card, cl = U.card()
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnMinimumWidth(0, 96)
        grid.addWidget(U.label(tr("Папка"), "strong"), 0, 0)
        self.folder = QLineEdit(self.cfg.get("meta_folder") or self.cfg.get("last_folder", ""))
        self.folder.setPlaceholderText(tr("Например, E:\\ или C:\\Users\\Имя\\Pictures"))
        self.folder.returnPressed.connect(self.start)
        self.folder.setAcceptDrops(False)        # файлы бросают на окно целиком — поле их не перехватывает
        self.folder.textEdited.connect(lambda _t: self.use_files(None))
        frow = QHBoxLayout()
        frow.setSpacing(8)
        frow.addWidget(self.folder, 1)
        self.files_note = U.label("", "strong")
        frow.addWidget(self.files_note, 1)
        self.files_reset = QPushButton(tr("Сбросить"), objectName="link")
        self.files_reset.setToolTip(tr("Снова проверять папку из поля"))
        self.files_reset.clicked.connect(lambda: self.use_files(None))
        frow.addWidget(self.files_reset)
        choose = QPushButton(tr("Выбрать…"))
        choose.clicked.connect(self.choose)
        frow.addWidget(choose)
        grid.addLayout(frow, 0, 1)

        grid.addWidget(U.label(tr("Убрать"), "strong"), 1, 0)
        prow = QHBoxLayout()
        prow.setSpacing(8)
        self.preset_group = QButtonGroup(self)
        self.preset_btns = {}
        for key, title in PRESETS.items():
            b = QPushButton(tr(title), objectName="chip", checkable=True)
            self.preset_group.addButton(b)
            b.toggled.connect(lambda on, k=key: on and self._preset_picked(k))
            prow.addWidget(b)
            self.preset_btns[key] = b
        prow.addSpacing(8)
        prow.addWidget(U.label(tr("Поворот и цвет остаются всегда. Без пересжатия."),
                               "muted"), 1)
        grid.addLayout(prow, 1, 1)
        checks = QGridLayout()
        checks.setHorizontalSpacing(24)
        checks.setVerticalSpacing(6)
        self.checks = {}
        saved = set(self.cfg.get("meta_groups") or metacore.GROUPS)
        for i, key in enumerate(metacore.GROUPS):
            c = QCheckBox(tr(metacore.GROUPS[key]))
            c.setChecked(key in saved)
            c.toggled.connect(self._checks_changed)
            checks.addWidget(c, i // 3, i % 3)
            self.checks[key] = c
        checks.setColumnStretch(3, 1)
        grid.addLayout(checks, 2, 1)

        grid.addWidget(U.label(tr("Результат"), "strong"), 3, 0)
        orow = QHBoxLayout()
        orow.setSpacing(8)
        self.output_group = QButtonGroup(self)
        self.output_btns = {}
        for key, title in OUTPUTS.items():
            b = QPushButton(tr(title), objectName="chip", checkable=True)
            self.output_group.addButton(b)
            b.toggled.connect(lambda on, k=key: on and self._output_picked(k))
            orow.addWidget(b)
            self.output_btns[key] = b
        orow.addSpacing(8)
        self.copies = QLineEdit(self.cfg.get("meta_copies", ""))
        self.copies.setAcceptDrops(False)
        self.copies.textEdited.connect(self._copies_edited)
        orow.addWidget(self.copies, 1)
        self.copies_choose = QPushButton(tr("Выбрать…"))
        self.copies_choose.clicked.connect(self.choose_copies)
        orow.addWidget(self.copies_choose)
        self.output_note = U.label("", "muted")
        orow.addWidget(self.output_note, 1)
        grid.addLayout(orow, 3, 1)
        cl.addLayout(grid)

        act = QHBoxLayout()
        act.setSpacing(8)
        self.load_text = U.label("", "muted")
        act.addWidget(self.load_text)
        change = QPushButton(tr("Изменить"), objectName="link")
        change.clicked.connect(self.go_settings.emit)
        act.addWidget(change)
        act.addStretch()
        self.btn_stop = QPushButton(tr("Остановить"))
        self.btn_stop.clicked.connect(self.stop)
        act.addWidget(self.btn_stop)
        self.btn_start = QPushButton(tr("Проверить файлы"), objectName="accent")
        self.btn_start.clicked.connect(self.start)
        act.addWidget(self.btn_start)
        cl.addLayout(act)
        root.addWidget(card)

        prog = QVBoxLayout()
        prog.setSpacing(6)
        top = QHBoxLayout()
        self.step_text = U.label(tr("Выбери папку и что убрать, и нажми «Проверить файлы»."), "strong")
        top.addWidget(self.step_text)
        top.addStretch()
        self.elapsed = U.label("", "muted")
        top.addWidget(self.elapsed)
        prog.addLayout(top)
        self.bar = QProgressBar(textVisible=False, maximum=1000)
        prog.addWidget(self.bar)
        self.status = WrapLabel("", "muted")
        self.status.hide()
        prog.addWidget(self.status)
        self.summary = U.label("", "strong")
        prog.addWidget(self.summary)
        root.addLayout(prog)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(16)
        self.stack = QStackedWidget()
        self.empty = U.label(EMPTY_TEXT(), "empty")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        empty_box, eb = U.card()
        eb.addWidget(self.empty)
        self.stack.addWidget(empty_box)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels([tr("Убрать"), tr("Файл"), tr("Что уберётся"), tr("Где лежит")])
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setItemDelegate(RowTint(self.tree))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        hdr = self.tree.header()
        hdr.setStretchLastSection(True)
        hdr.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        for col, w in enumerate((84, 180, 260)):
            self.tree.setColumnWidth(col, w)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.currentItemChanged.connect(lambda cur, _p: self.show_item(cur.data(1, FILE_ROLE) if cur else None))
        self.tree.itemDoubleClicked.connect(lambda it, col: col and U.open_file(it.data(1, FILE_ROLE).path))
        self.stack.addWidget(self.tree)
        split.addWidget(self.stack)

        side, sl = U.card(margins=(16, 14, 16, 14), spacing=10)
        stop = QHBoxLayout()
        stop.addWidget(U.label(tr("Было → стало"), "h2"))
        stop.addStretch()
        self.side_name = U.label("", "muted")
        stop.addWidget(self.side_name)
        sl.addLayout(stop)
        self.side_hint = WrapLabel(tr("Выбери файл в списке — здесь будет всё, что в нём записано, и что из этого "
                                      "уберётся."), "muted")
        self.side_hint.setAlignment(Qt.AlignLeft | Qt.AlignTop)   # растянута на свободное место — текст наверху
        sl.addWidget(self.side_hint, 1)
        self.side_layout = sl
        self.side_body = QWidget()
        body = QVBoxLayout(self.side_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)
        self.pic = Picture("", self.colors)
        self.pic.setMinimumWidth(140)
        self.pic.setFixedHeight(130)                 # главное справа — поля; превью только напоминает, что за файл
        body.addWidget(self.pic)
        self.fields = QTreeWidget()
        self.fields.setColumnCount(3)
        self.fields.setHeaderLabels([tr("Поле"), tr("Значение"), tr("После")])
        self.fields.setRootIsDecorated(False)
        self.fields.setIndentation(0)
        self.fields.setSelectionMode(QAbstractItemView.NoSelection)
        self.fields.setFocusPolicy(Qt.NoFocus)
        self.fields.setItemDelegate(RowTint(self.fields))
        fh = self.fields.header()
        fh.setStretchLastSection(False)
        fh.setSectionResizeMode(1, QHeaderView.Stretch)
        fh.setSectionResizeMode(0, QHeaderView.Interactive)
        fh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.fields.setColumnWidth(0, 170)
        body.addWidget(self.fields, 1)
        sl.addWidget(self.side_body, 1)
        side.setMinimumWidth(360)
        side.installEventFilter(self)
        self.side = side
        split.addWidget(side)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([640, 560])
        self.split = split
        root.addWidget(split, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        mark_all = QPushButton(tr("Отметить все"))
        mark_all.clicked.connect(lambda: self._mark_all(True))
        bottom.addWidget(mark_all)
        unmark = QPushButton(tr("Снять все отметки"))
        unmark.clicked.connect(lambda: self._mark_all(False))
        bottom.addWidget(unmark)
        self.btn_skipped = QPushButton()
        self.btn_skipped.clicked.connect(self.show_skipped)
        self.btn_skipped.hide()
        bottom.addWidget(self.btn_skipped)
        self.btn_errors = QPushButton()
        self.btn_errors.clicked.connect(self.show_errors)
        self.btn_errors.hide()
        bottom.addWidget(self.btn_errors)
        bottom.addStretch()
        self.btn_go = QPushButton(objectName="danger")
        self.btn_go.clicked.connect(self.run_marked)
        bottom.addWidget(self.btn_go)
        root.addLayout(bottom)

        preset = self.cfg.get("meta_preset", "all")
        self.preset_btns[preset if preset in PRESETS else "all"].setChecked(True)
        out = self.cfg.get("meta_output", "replace")
        self.output_btns[out if out in OUTPUTS else "replace"].setChecked(True)
        self.show_item(None)
        self.use_files(None)

    PIC_ROOM = 320          # ниже этого правой панели превью не показываем: место — таблице полей

    def eventFilter(self, obj, ev):
        if obj is getattr(self, "side", None) and ev.type() == ev.Type.Resize:
            self.pic.setVisible(obj.height() >= self.PIC_ROOM)
        return False

    def set_load_text(self):
        self.load_text.setText(tr("Нагрузка на компьютер: {name}",
                                  name=tr(LOAD_NAMES[self.cfg.get("load", "gentle")])))

    # ---------- что убрать и куда

    def groups(self):
        return {k for k, c in self.checks.items() if c.isChecked()}

    def preset(self):
        return next((k for k, b in self.preset_btns.items() if b.isChecked()), "all")

    def output(self):
        return next((k for k, b in self.output_btns.items() if b.isChecked()), "replace")

    def _preset_picked(self, key):
        if key in metacore.PRESETS:
            want = set(metacore.PRESETS[key])
            self._updating_checks = True
            try:
                for k, c in self.checks.items():
                    c.setChecked(k in want)
            finally:
                self._updating_checks = False
        self.cfg["meta_preset"] = key
        self._selection_changed()

    def _checks_changed(self, *_):
        if getattr(self, "_updating_checks", False):
            return
        groups = self.groups()
        match = next((k for k, v in metacore.PRESETS.items() if set(v) == groups), "custom")
        if not self.preset_btns[match].isChecked():
            self.preset_btns[match].blockSignals(True)
            self.preset_btns[match].setChecked(True)
            self.preset_btns[match].blockSignals(False)
            self.cfg["meta_preset"] = match
        self._selection_changed()

    def _selection_changed(self):
        self.cfg["meta_groups"] = sorted(self.groups())
        self.settings_changed.emit()
        self._update_counts()
        if self.items:
            self.refresh()

    def _output_picked(self, key):
        copies = key == "copies"
        self.copies.setVisible(copies)
        self.copies_choose.setVisible(copies)
        self.output_note.setVisible(not copies)
        self.output_note.setText(tr("Оригиналы — в Корзину; имена и даты те же."))
        if copies and not self.copies.text().strip():
            self._suggest_copies()
        self.copies.setPlaceholderText(tr("Папка для очищенных копий"))
        self.cfg["meta_output"] = key
        self.settings_changed.emit()
        self._update_summary()

    def _suggest_copies(self):
        base = self._base_folder()
        if base:
            self.copies.setText(metacore.default_copies_folder(base))

    def _copies_edited(self, text):
        self.cfg["meta_copies"] = text.strip()
        self.settings_changed.emit()

    def _base_folder(self):
        if self.drop_files:
            try:
                return os.path.commonpath([p if os.path.isdir(p) else os.path.dirname(p) for p in self.drop_files])
            except ValueError:
                return os.path.dirname(self.drop_files[0])
        text = self.folder.text().strip().strip('"')
        return text if text and os.path.isdir(text) else ""

    def choose(self):
        d = QFileDialog.getExistingDirectory(self, tr("Где проверить метаданные"), self.folder.text() or "")
        if d:
            self.use_folder(d)

    def choose_copies(self):
        d = QFileDialog.getExistingDirectory(self, tr("Папка для очищенных копий"), self.copies.text() or "")
        if d:
            self.copies.setText(os.path.normpath(d))
            self._copies_edited(self.copies.text())

    def use_folder(self, path):
        self.use_files(None)
        self.folder.setText(os.path.normpath(path))
        if self.output() == "copies" and not self.cfg.get("meta_copies"):
            self._suggest_copies()
        self.btn_start.setFocus()

    def use_files(self, paths):
        """Проверить именно перетащенные файлы и папки (None — снова папку из поля)."""
        self.drop_files = [os.path.normpath(p) for p in paths] if paths else None
        on = self.drop_files is not None
        self.folder.setVisible(not on)
        self.files_note.setVisible(on)
        self.files_reset.setVisible(on)
        if on:
            dirs = sum(os.path.isdir(p) for p in self.drop_files)
            files = len(self.drop_files) - dirs
            parts = []
            if files:
                parts.append(f"{num(files)} {plural(files, 'файл|файла|файлов', 'file|files')}")
            if dirs:
                parts.append(f"{num(dirs)} {plural(dirs, 'папка|папки|папок', 'folder|folders')}")
            self.files_note.setText(tr("Перетащено: {what}", what=", ".join(parts)))
            self.files_note.setToolTip("\n".join(self.drop_files[:30]))
            self.btn_start.setFocus()

    # ---------- проверка файлов

    def start(self):
        if self.busy:
            return
        if self.drop_files:
            root = [p for p in self.drop_files if os.path.exists(p)]
            if not root:
                U.warn(self, tr("Перетащенных файлов больше нет на месте."))
                return
            self.scan_root = self._base_folder()
        else:
            root = self.folder.text().strip().strip('"')
            if not root or not os.path.isdir(root):
                U.warn(self, tr("Такой папки нет. Нажми «Выбрать…» и укажи папку."))
                return
            self.cfg["meta_folder"] = root
            self.settings_changed.emit()
            self.scan_root = os.path.abspath(root)
        if not compcore.tool("ffprobe"):
            log.warning("Метаданные: нет ffprobe — видео пропускаются при очистке")
        self.items, self.shown, self.marked, self.pending = [], [], set(), []
        self.result = None
        self._times = {}
        self.previews.clear()
        self.refresh()
        self.empty.setText(tr("Читаю файлы…"))
        self.btn_skipped.hide()
        self.btn_errors.hide()
        exclude = self.copies.text().strip() if self.output() == "copies" else None
        self._begin(tr("Ищу фото и видео…"))
        load = self.cfg.get("load", "gentle")
        log.info("Метаданные: проверка %s · нагрузка %s", root, load)
        self.phase = "scan"
        self.worker = threading.Thread(target=self._scan_worker, args=(root, self.cancel, load, exclude), daemon=True)
        self.worker.start()

    def _begin(self, text):
        self.cancel = threading.Event()
        self.clock = StepClock()
        self.started = time.monotonic()
        self._last_push = 0.0
        self._set_busy(True)
        self.step_text.setText(text)
        self._set_status("")
        self.ticker.start()
        self._tick()

    def _set_status(self, text):
        """Строка под полосой: пустая — прячется и не занимает высоту."""
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def _push(self, step, done, total, name=""):
        now = time.monotonic()
        if now - self._last_push > 0.15 or done >= total or done == 0:
            self._last_push = now
            self.bridge.progress.emit(step, done, total, name)

    def _scan_worker(self, root, cancel, load, exclude):
        try:
            res = metacore.scan(root, lambda d, t: self._push("scan", d, t), cancel, load, exclude=exclude)
            self.bridge.scanned.emit(res)
        except Exception as e:                     # окно не должно зависнуть в «читаю» навсегда
            log.exception("Метаданные: проверка упала")
            self.bridge.failed.emit(str(e))

    def _tick(self):
        if self.busy:
            self.elapsed.setText(tr("прошло {t}", t=dupcore.human_time(time.monotonic() - self.started)))

    def _show_progress(self, step, done, total, name):
        if not self.busy:
            return
        if step == "scan" and not done:
            self.bar.setRange(0, 0)
            self.step_text.setText(tr("Ищу фото и видео…"))
            self._set_status(tr("Найдено файлов: {n}.", n=num(total)))
            return
        self.bar.setRange(0, 1000)
        self.bar.setValue(int(1000 * done / total) if total else 0)
        if step == "scan":
            self.step_text.setText(tr("Читаю файлы · {done} из {total}", done=num(done), total=num(total)))
        elif step == "clean":
            self.step_text.setText(tr("Убираю метаданные · {done} из {total}", done=num(done), total=num(total)))
        else:
            self.step_text.setText(tr("Заменяю файлы · {done} из {total}", done=num(done), total=num(total))
                                   if step == "replace" else
                                   tr("Сохраняю копии · {done} из {total}", done=num(done), total=num(total)))
        pct = done * 100 // total if total else 0
        self.title_changed.emit(tr("{app} — метаданные, {pct}%", app=U.APP_TITLE, pct=pct))
        _rate, left = self.clock.update(step, done, total)
        parts = [tr("осталось ≈ {t}", t=dupcore.human_time(left)) if left is not None
                 else tr("считаю, сколько осталось…")]
        if name:
            parts.append(tr("сейчас: {name}", name=name))
        self._set_status(" · ".join(parts))

    def stop(self):
        if self.cancel:
            self.cancel.set()
            self.step_text.setText(tr("Останавливаю…"))

    def _failed(self, text):
        self._set_busy(False)
        self.title_changed.emit(U.APP_TITLE)
        U.warn(self, tr("Работа прервалась из-за ошибки:\n{text}", text=text))

    def _end(self):
        took = dupcore.human_time(time.monotonic() - self.started)
        self._set_busy(False)
        self.title_changed.emit(U.APP_TITLE)
        self.bar.setRange(0, 1000)
        self.elapsed.setText("")
        return took

    def _scan_done(self, res):
        took = self._end()
        self.result = res
        self.items = [i for i in res.items if not i.skip]
        self.bar.setValue(0 if res.cancelled else 1000)
        self.marked = set()
        self.refresh(mark_new=True)
        skipped = [i for i in res.items if i.skip]
        log.info("Метаданные: прочитано %d за %s, есть что убрать %d, не прочитано %d, ошибок %d",
                 res.files_seen, took, len(self.shown), len(skipped), len(res.errors))
        for i in skipped[:100]:
            log.info("   не прочитан: %s — %s", i.path, i.skip)
        seen = ""                                   # сколько прочитано — в итоге под полосой; здесь только особое
        if res.cloud_skipped:
            seen += tr(" Пропущено файлов, которые лежат только в облаке или на телефоне: {n} — их пришлось "
                       "бы скачивать.", n=num(res.cloud_skipped))
        if res.unsupported:
            seen += tr(" Перетащенных файлов другого типа: {n} — их программа не читает.", n=num(res.unsupported))
        if res.cancelled:
            self.step_text.setText(tr("Проверка остановлена.") + (tr(" Прочитанное — в списке.") if self.shown else ""))
            self._set_status(tr("Прошло {t}.", t=took))
        elif not self.shown:
            self.step_text.setText(tr("Готово за {t}. Убирать нечего.", t=took))
            self._set_status(seen.strip())
        else:
            self.step_text.setText(tr("Готово за {t}. Проверь список и «было → стало» и нажми кнопку внизу.", t=took))
            self._set_status(seen.strip())
        if not self.shown:
            self.empty.setText(tr("В этих файлах нет ничего из выбранного.") if res.files_seen
                               else tr("Подходящих фото и видео тут нет."))
        if skipped:
            self.btn_skipped.setText(tr("Не прочитались: {n}", n=num(len(skipped))))
            self.btn_skipped.show()
        if res.errors:
            self.btn_errors.setText(tr("Папки с ошибками: {n}", n=num(len(res.errors))))
            self.btn_errors.show()

    def _set_busy(self, busy):
        self.busy = busy
        self.btn_start.setEnabled(not busy)
        self.btn_stop.setEnabled(busy)
        for b in list(self.preset_btns.values()) + list(self.output_btns.values()) + list(self.checks.values()):
            b.setEnabled(not busy)
        self.copies.setEnabled(not busy)
        self.copies_choose.setEnabled(not busy)
        if not busy:
            self.ticker.stop()
        self._update_summary()

    def has_pending(self):
        return False                     # копий, которые пропадут при выходе, здесь не бывает

    # ---------- список

    def short_dir(self, path):
        rel = os.path.relpath(os.path.dirname(path), self.scan_root) if self.scan_root else os.path.dirname(path)
        return tr("(в самой папке)") if rel == "." else rel

    def _make_item(self, it):
        groups = self.groups()
        short, full = what_text(it, groups)
        partly = any(f.locked and f.group in groups for f in it.fields)   # часть выбранного убрать нельзя
        if partly:
            short += "  ·  " + tr("не всё")
            full += "\n" + tr("Часть полей убрать нельзя — какие и почему, видно справа.")
        row = QTreeWidgetItem(["", os.path.basename(it.path), short, self.short_dir(it.path)])
        row.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
        row.setData(1, FILE_ROLE, it)
        row.setToolTip(1, it.path)
        row.setToolTip(2, full)
        if partly:
            row.setForeground(2, QColor(self.colors["warn"]))
        row.setToolTip(0, tr("Отметка — из файла уберётся выбранное"))
        row.setCheckState(0, Qt.Checked if it.path in self.marked else Qt.Unchecked)
        self.tree_items[it.path] = row
        return row

    def refresh(self, mark_new=False):
        groups = self.groups()
        self.shown = [i for i in self.items if i.to_remove(groups)]
        if mark_new:
            self.marked = {i.path for i in self.shown}
        self._updating = True
        keep = self.current.path if self.current else None
        self.tree.setUpdatesEnabled(False)
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            self.tree_items.clear()
            self.tree.addTopLevelItems([self._make_item(i) for i in self.shown])
        finally:
            self.tree.blockSignals(False)
            self.tree.setUpdatesEnabled(True)
            self._updating = False
        self.stack.setCurrentIndex(1 if self.shown else 0)
        if keep in self.tree_items:
            self.tree.setCurrentItem(self.tree_items[keep])
        elif self.shown:
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        else:
            self.show_item(None)
        self._update_counts()
        self._update_summary()

    def _update_counts(self):
        """У галочек — в скольких файлах есть что убрать из этой группы."""
        for key, c in self.checks.items():
            n = sum(1 for i in self.items if any(f.group == key and not f.locked for f in i.fields))
            c.setText(tr(metacore.GROUPS[key]) + (f" · {num(n)}" if self.items else ""))
        if self.current is not None:
            self.show_item(self.current)

    def _item_changed(self, row, col):
        if self._updating or col != 0:
            return
        it = row.data(1, FILE_ROLE)
        (self.marked.add if row.checkState(0) == Qt.Checked else self.marked.discard)(it.path)
        self._update_summary()

    def _mark_all(self, on):
        self.marked = {i.path for i in self.shown} if on else set()
        self._updating = True
        try:
            for path, row in self.tree_items.items():
                row.setCheckState(0, Qt.Checked if path in self.marked else Qt.Unchecked)
        finally:
            self._updating = False
        self._update_summary()

    def _marked_items(self):
        return [i for i in self.shown if i.path in self.marked]

    def _update_summary(self):
        items = self._marked_items()
        n = len(items)
        files = plural(n, "файла|файлов|файлов", "file|files")
        if self.output() == "copies":
            self.btn_go.setObjectName("accent")
            self.btn_go.setText(tr("Сохранить {n} {copies}", n=num(n), copies=plural(
                n, "очищенную копию|очищенные копии|очищенных копий", "cleaned copy|cleaned copies")) if n else
                tr("Сохранить очищенные копии"))
        else:
            self.btn_go.setObjectName("danger")
            self.btn_go.setText(tr("Убрать из {n} {files}", n=num(n), files=files) if n else
                                tr("Убрать из отмеченных файлов"))
        U.repolish(self.btn_go)
        self.btn_go.setEnabled(n > 0 and not self.busy)
        self.summary.setVisible(bool(self.items))
        if self.items:
            self.summary.setText(tr("Прочитано: {seen}  ·  есть что убрать: {shown}  ·  отмечено: {n}",
                                    seen=num(len(self.items)), shown=num(len(self.shown)), n=num(n)))

    def _menu(self, pos):
        row = self.tree.itemAt(pos)
        it = row.data(1, FILE_ROLE) if row else None
        if it is None:
            return
        menu = QMenu(self)
        menu.addAction(tr("Открыть"), lambda: U.open_file(it.path))
        menu.addAction(tr("Показать в папке"), lambda: U.reveal(it.path))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # ---------- «было → стало»

    def frame_time(self, it):
        if it.path not in self._times:
            at = 0.0
            try:
                at = float(compcore.probe(it.path).get("format", {}).get("duration") or 0) / 3
            except (compcore.Skip, ValueError, OSError):
                pass
            self._times[it.path] = at
        return self._times[it.path]

    def show_item(self, it):
        self.current = it
        on = it is not None
        self.side_hint.setVisible(not on)
        self.side_body.setVisible(on)
        if not on:
            self.side_name.setText("")
            return
        self.side_name.setText(self.side_name.fontMetrics().elidedText(os.path.basename(it.path), Qt.ElideMiddle, 240))
        self._show_picture()
        groups = self.groups()
        bold = QFont(self.fields.font())
        bold.setBold(True)
        strike = QFont(self.fields.font())
        strike.setStrikeOut(True)
        rows, heads = [], []
        for g in metacore.GROUPS:
            fs = [f for f in it.fields if f.group == g]
            if not fs:
                continue
            head = QTreeWidgetItem([tr(metacore.GROUPS[g]), "", ""])
            head.setFont(0, bold)
            head.setBackground(0, QColor(self.colors["group"]))
            rows.append(head)
            heads.append(head)
            for f in fs:
                name = f.name + (f"  ·  {f.where}" if f.where else "")
                row = QTreeWidgetItem([name, f.value, ""])
                row.setToolTip(0, name)
                row.setToolTip(1, f.value)
                if f.locked:
                    row.setText(2, tr("не убрать"))
                    row.setForeground(2, QColor(self.colors["warn"]))
                    row.setToolTip(2, f.locked)
                elif g in groups:
                    row.setText(2, tr("уберётся"))
                    row.setForeground(2, QColor(self.colors["danger"]))
                    row.setFont(1, strike)
                    row.setForeground(1, QColor(self.colors["muted"]))
                else:
                    row.setText(2, tr("останется"))
                    row.setForeground(2, QColor(self.colors["muted"]))
                rows.append(row)
        self.fields.setUpdatesEnabled(False)
        self.fields.clear()
        self.fields.addTopLevelItems(rows)
        for r in heads:                                  # растянуть строку можно, только когда она уже в дереве
            r.setFirstColumnSpanned(True)
        self.fields.scrollToTop()                        # новый файл — с первой группы, а не с места прошлого
        self.fields.setUpdatesEnabled(True)

    def _show_picture(self):
        it = self.current
        if it is None:
            return
        at = self.frame_time(it) if it.is_video else None
        self.pic.set_image(self.previews.get(it.path, at), tr("Загружаю…"))

    def _preview_ready(self, key, img):
        if self.current is not None and key.split("|", 1)[0] == self.current.path:
            self._show_picture()

    # ---------- не прочитанные, ошибки

    def show_skipped(self):
        res = self.result
        by = {}
        for i in (res.items if res else []):
            if i.skip:
                by.setdefault(i.skip, []).append(i)
        lines = []
        for why, items in sorted(by.items(), key=lambda t: -len(t[1])):
            names = ", ".join(os.path.basename(i.path) for i in items[:3]) + (" …" if len(items) > 3 else "")
            lines.append(f"• {tr(why)} — {num(len(items))}: {names}")
        U.info(self, tr("Эти файлы не удалось прочитать — они остаются как есть:\n\n") + "\n".join(lines[:20]))

    def show_errors(self):
        errs = self.result.errors if self.result else []
        lines = [f"{p}\n    {e}" for p, e in errs[:40]]
        more = tr("\n…и ещё {n}", n=len(errs) - 40) if len(errs) > 40 else ""
        U.info(self, tr("Эти файлы или папки не удалось прочитать:\n\n") + "\n".join(lines) + more)

    # ---------- очистка

    def run_marked(self):
        items = self._marked_items()
        groups = self.groups()
        if not items or not groups:
            U.info(self, tr("Ничего не отмечено."))
            return
        what = ", ".join(tr(SHORT[g]) for g in metacore.GROUPS if g in groups)
        copies = self.output() == "copies"
        if copies:
            folder = self.copies.text().strip().strip('"')
            if not folder:
                U.warn(self, tr("Укажи папку для очищенных копий."))
                return
            folder = os.path.abspath(folder)
            if any(os.path.normcase(os.path.dirname(os.path.abspath(i.path))) == os.path.normcase(folder)
                   for i in items):
                U.warn(self, tr("Копии нельзя класть в ту же папку, где лежат оригиналы — выбери другую."))
                return
        else:
            folder = ""
            no_bin = sorted({d for d in (dupcore.drive_of(i.path) for i in items) if not dupcore.has_recycle_bin(d)})
            text = tr("Убрать ({what}) из {n} {files}?\n\nКартинка и видео не пересжимаются. Оригиналы уйдут в "
                      "Корзину — вернуть можно оттуда. Имена и даты файлов останутся прежними.", what=what,
                      n=num(len(items)), files=plural(len(items), "файла|файлов|файлов", "file|files"))
            if no_bin:
                text += tr("\n\n⚠ На дисках {drives} Корзины нет (флешка, карта памяти или сетевой диск): "
                           "оригиналы оттуда удалятся НАВСЕГДА, вернуть их будет нельзя.", drives=", ".join(no_bin))
            if not U.ask_yes_no(self, text, yes=tr("Убрать, оригиналы навсегда") if no_bin else tr("Убрать")):
                return
        self._begin(tr("Убираю метаданные…"))
        load = self.cfg.get("load", "gentle")
        hwnd = int(self.window().winId())
        log.info("Метаданные: убрать %s из %d · %s", ",".join(sorted(groups)), len(items),
                 f"копии в {folder}" if copies else "замена")
        self.phase = "clean"
        self.worker = threading.Thread(target=self._clean_worker, daemon=True,
                                       args=(items, groups, copies, folder, self.cancel, load, hwnd))
        self.worker.start()

    def finish_before_exit(self):
        """Выход: остановить работу; если файлы уже заменяются — дождаться конца, а не оборвать посередине."""
        if self.cancel:
            self.cancel.set()
        th = getattr(self, "worker", None)
        if th is not None and th.is_alive() and getattr(self, "phase", "") in ("replace", "copies"):
            th.join()

    def _clean_worker(self, items, groups, copies, folder, cancel, load, hwnd):
        out = {"done": [], "problems": [], "skipped": [], "cancelled": False, "copies": copies, "folder": folder}
        try:
            try:
                metacore.clean(items, groups, lambda d, t, name: self._push("clean", d, t, name), cancel, load,
                               need_writable=not copies)
            except dupcore.Cancelled:
                out["cancelled"] = True
                metacore.clean_work()
                self.bridge.cleaned.emit(out)
                return
            ready = [i for i in items if i.out]
            out["skipped"] = [i for i in items if not i.out]
            # Сначала отметка «меняю файлы», потом проверка «остановили?» — окно при выходе смотрит в обратном
            # порядке: так замена либо не начнётся, либо окно дождётся её конца (finish_before_exit).
            self.phase = "copies" if copies else "replace"
            if cancel.is_set():
                out["cancelled"] = True
                metacore.clean_work()
                self.bridge.cleaned.emit(out)
                return
            if copies:
                done, problems = metacore.save_copies(ready, folder, self.scan_root, "time" not in groups,
                                                      lambda n: self._push("copies", n, len(ready)))
            else:
                done, problems = compcore.replace(ready, hwnd=hwnd, progress=lambda n: self._push("replace", n,
                                                                                                    len(ready)))
            out["done"], out["problems"] = done, problems
            metacore.clean_work()
            self.bridge.cleaned.emit(out)
        except Exception as e:
            log.exception("Метаданные: очистка упала")
            self.bridge.failed.emit(str(e))

    def _clean_done(self, out):
        took = self._end()
        done, problems, skipped = out["done"], out["problems"], out["skipped"]
        if out["cancelled"]:
            self.step_text.setText(tr("Остановлено — ни один файл не изменён."))
            self._set_status(tr("Прошло {t}.", t=took))
            return
        log.info("Метаданные: готово %d, не тронуто %d, проблем %d за %s", len(done), len(skipped), len(problems), took)
        for i in skipped:
            log.info("   не тронут: %s — %s", i.path, i.skip)
        for path, why in problems:
            log.warning("   не сделан: %s — %s", path, why)
        if out["copies"]:
            msg = tr("Сохранено очищенных копий: {n}. Папка: {folder}", n=num(len(done)), folder=out["folder"])
            self.step_text.setText(tr("Сохранено очищенных копий: {n}.", n=num(len(done))))
        else:
            gone = {i.path for i in done}
            for i in done:                               # файл уже другой — перечитать, что в нём осталось
                fresh = metacore.read(i.path)
                i.fields, i.size, i.mtime = fresh.fields, fresh.size, fresh.mtime
            self.marked -= gone
            self.step_text.setText(tr("Готово: метаданные убраны из {n} {files}. Оригиналы — в Корзине.",
                                      n=num(len(done)), files=plural(len(done), "файла|файлов|файлов", "file|files")))
            # Проводник видит замену как «удалён и появился новый»: на рабочем столе значок прыгает в другое место,
            # и кажется, что файл пропал. Поэтому прямо говорим, где он, и даём его показать.
            msg = tr("Готово: метаданные убраны из {n} {files}.\n\nФайлы остались на своих местах с теми же именами "
                     "и датами. Старые версии — в Корзине: оттуда их можно вернуть.", n=num(len(done)),
                     files=plural(len(done), "файла|файлов|файлов", "file|files"))
        self._set_status(tr("Прошло {t}.", t=took))
        self.current = None
        self.refresh()
        if not self.shown:
            self.empty.setText(tr("Готово: в проверенных файлах больше нечего убирать."))
        if skipped:
            by = {}
            for i in skipped:
                by.setdefault(i.skip, []).append(i)
            lines = [f"• {tr(why)} — {num(len(v))}: " + ", ".join(os.path.basename(i.path) for i in v[:3]) +
                     (" …" if len(v) > 3 else "") for why, v in sorted(by.items(), key=lambda t: -len(t[1]))]
            msg += tr("\n\nОставлены как есть ({n}):\n", n=num(len(skipped))) + "\n".join(lines[:10])
        if problems:
            msg += tr("\n\nНе получилось ({n}):\n", n=num(len(problems))) + _problems_text(problems)
        if out["copies"] and done:
            if U.ask_yes_no(self, msg, yes=tr("Открыть папку"), no=tr("Закрыть")):
                U.open_file(out["folder"])
        elif done:
            if U.ask_yes_no(self, msg, yes=tr("Показать в папке"), no=tr("Закрыть")):
                U.reveal(done[0].path)                   # Проводник откроется с выделенным файлом
        else:
            U.info(self, msg)
