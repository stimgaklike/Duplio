"""Вкладка «Дубликаты»: поиск, список групп, сравнение копий с превью, удаление в Корзину."""

import os
import threading
import time
from datetime import datetime

from PySide6.QtCore import QEvent, QModelIndex, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QImageReader, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMenu, QProgressBar, QPushButton, QScrollArea,
                               QSizePolicy, QSplitter, QStackedWidget, QStyle, QStyledItemDelegate, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

import dupcore
import ui_util as U
from logs import log
from i18n import num, plural, tr

LOAD_NAMES = {"gentle": "бережная", "normal": "обычная", "fast": "быстрая (для SSD)"}
FILE_ROLE = Qt.UserRole


class Bridge(QObject):
    """Сигналы из потока поиска в окно. object, а не int: байты больше 2 ГБ не влезают в int Qt."""
    progress = Signal(int, str, object, object, str)
    group = Signal(object)            # подтверждённая группа копий — сразу, не дожидаясь конца поиска
    done = Signal(object)
    failed = Signal(str)


class StepClock:
    """Скорость и оставшееся время текущего шага: по среднему с начала шага."""

    def __init__(self):
        self.step, self.start = None, 0.0

    def update(self, step, done, total):
        now = time.monotonic()
        if step != self.step:
            self.step, self.start = step, now
        elapsed = now - self.start
        if not total or done <= 0 or elapsed < 1.5:
            return None, None
        rate = done / elapsed
        return rate, (total - done) / rate if rate > 0 else None


def fmt_date(ts):
    """Дата изменения. До 1970 года (камеры со сбитыми часами, архивы) Windows не умеет — показываем «—»."""
    from i18n import date_format
    try:
        return datetime.fromtimestamp(ts).strftime(date_format())
    except (OSError, ValueError, OverflowError):
        return "—"


class RowTint(QStyledItemDelegate):
    """Фон строки из данных элемента (подкраска отмеченных, фон заголовков групп).

    Когда строки таблицы оформлены через стиль (::item), Qt сам этот фон не рисует — рисуем мы.
    """

    def paint(self, painter, option, index):
        bg = index.data(Qt.BackgroundRole)
        if bg is not None and not (option.state & QStyle.State_Selected):
            painter.fillRect(option.rect, bg)
        super().paint(painter, option, index)


# ---------------------------------------------------------------- карточка файла в сравнении

class FileCard(QFrame):
    clicked = Signal(object)          # MediaFile
    toggle = Signal(object)
    preview = Signal(object)

    def __init__(self, mf, short_dir, colors):
        super().__init__(objectName="fileCard")
        self.mf = mf
        self.colors = colors
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(6)
        self.thumb = QLabel(objectName="thumb")
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setFixedSize(QSize(208, 150))
        self.thumb.setText("🎬" if mf.is_video else ("🖼" if mf.is_image else "📄"))
        self.thumb.setToolTip(tr("Двойной щелчок — быстрый просмотр"))
        lay.addWidget(self.thumb, 0, Qt.AlignHCenter)
        self.name = U.label(os.path.basename(mf.path), "strong")
        self.name.setToolTip(mf.path)
        lay.addWidget(self.name)
        self.folder = U.label(short_dir, "muted")
        self.folder.setToolTip(os.path.dirname(mf.path))
        lay.addWidget(self.folder)
        lay.addWidget(U.label(f"{dupcore.human_size(mf.size)} · {fmt_date(mf.mtime)}", "small"))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.pill = QLabel()
        row.addWidget(self.pill)
        row.addStretch()
        self.btn = QPushButton()
        self.btn.clicked.connect(lambda: self.toggle.emit(self.mf))
        row.addWidget(self.btn)
        lay.addLayout(row)
        links = QHBoxLayout()
        links.setSpacing(14)
        for text, fn in ((tr("Открыть"), lambda: U.open_file(mf.path)),
                         (tr("Показать в папке"), lambda: U.reveal(mf.path))):
            b = QPushButton(text, objectName="link")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(fn)
            links.addWidget(b)
        links.addStretch()
        lay.addLayout(links)
        self.setFixedWidth(234)
        self._elide()

    def _elide(self):
        fm = self.name.fontMetrics()
        self.name.setText(fm.elidedText(os.path.basename(self.mf.path), Qt.ElideMiddle, 206))
        self.folder.setText(self.folder.fontMetrics().elidedText(self.folder.text(), Qt.ElideMiddle, 206))

    def set_state(self, marked, current):
        self.setProperty("marked", "true" if marked else "false")
        self.setProperty("current", "true" if current else "false")
        self.pill.setObjectName("pillDel" if marked else "pillKeep")
        self.pill.setText(tr("Удалить") if marked else tr("Оставить"))
        self.btn.setText(tr("Оставить") if marked else tr("Удалить"))
        U.repolish(self)
        U.repolish(self.pill)
        U.repolish(self.thumb)

    def set_image(self, img):
        if img is None or img.isNull():
            return
        pm = QPixmap.fromImage(img).scaled(self.thumb.size() - QSize(8, 8), Qt.KeepAspectRatio,
                                           Qt.SmoothTransformation)
        self.thumb.setPixmap(pm)

    def mousePressEvent(self, e):
        self.clicked.emit(self.mf)
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        self.preview.emit(self.mf)


# ---------------------------------------------------------------- быстрый просмотр

class QuickLook(QDialog):
    """Большой просмотр файла группы: стрелки — соседние копии, пробел или Esc — закрыть."""

    def __init__(self, page, group, index):
        super().__init__(page)
        self.page, self.group, self.i = page, group, index
        self.setWindowTitle(tr("Быстрый просмотр"))
        self.resize(1100, 780)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        top = QHBoxLayout()
        self.title = U.label("", "h2")
        top.addWidget(self.title)
        top.addStretch()
        self.counter = U.label("", "muted")
        top.addWidget(self.counter)
        lay.addLayout(top)
        self.path = U.label("", "muted")
        lay.addWidget(self.path)
        self.view = QLabel(alignment=Qt.AlignCenter)
        self.view.setObjectName("thumb")
        self.view.setMinimumSize(400, 300)
        self.view.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        lay.addWidget(self.view, 1)
        bottom = QHBoxLayout()
        self.prev = QPushButton(tr("← Предыдущая"))
        self.prev.clicked.connect(lambda: self.go(-1))
        self.next = QPushButton(tr("Следующая →"))
        self.next.clicked.connect(lambda: self.go(1))
        bottom.addWidget(self.prev)
        bottom.addWidget(self.next)
        bottom.addStretch()
        self.state = QLabel()
        bottom.addWidget(self.state)
        self.toggle_btn = QPushButton()
        self.toggle_btn.clicked.connect(self._toggle)
        bottom.addWidget(self.toggle_btn)
        open_btn = QPushButton(tr("Открыть в программе"))
        open_btn.clicked.connect(lambda: U.open_file(self.group[self.i].path))
        bottom.addWidget(open_btn)
        lay.addLayout(bottom)
        for key, fn in ((Qt.Key_Left, lambda: self.go(-1)), (Qt.Key_Right, lambda: self.go(1)),
                        (Qt.Key_Space, self.close)):
            QShortcut(QKeySequence(key), self, activated=fn)
        # Закрытое окно удаляется, и Qt сам снимает его подписку на превью — иначе после удаления файлов
        # оно ловило бы превью для копий, которых в группе уже нет (IndexError).
        self.setAttribute(Qt.WA_DeleteOnClose)
        page.thumbs.ready.connect(self._thumb_ready)
        self.show_current()

    def go(self, d):
        self.i = (self.i + d) % len(self.group)
        self.show_current()

    def _toggle(self):
        self.page.toggle_file(self.group[self.i])
        self.show_current()

    def show_current(self):
        m = self.group[self.i]
        self.title.setText(os.path.basename(m.path))
        self.counter.setText(tr("копия {i} из {n}", i=self.i + 1, n=len(self.group)))
        self.path.setText(f"{m.path}   ·   {dupcore.human_size(m.size)}   ·   {fmt_date(m.mtime)}")
        marked = m.path in self.page.marked
        self.state.setObjectName("pillDel" if marked else "pillKeep")
        self.state.setText(tr("Будет удалена") if marked else tr("Остаётся"))
        U.repolish(self.state)
        self.toggle_btn.setText(tr("Оставить эту копию") if marked else tr("Удалить эту копию"))
        self._show_image(m)

    def _show_image(self, m):
        if m.is_image:
            reader = QImageReader(m.path)
            reader.setAutoTransform(True)
            box = self.view.size() - QSize(16, 16)
            size = reader.size()
            if size.isValid():
                reader.setScaledSize(size.scaled(box, Qt.KeepAspectRatio))
            img = reader.read()
            if not img.isNull():
                self.view.setPixmap(QPixmap.fromImage(img))
                return
        img = self.page.thumbs.get(m.path)
        if img is not None and not img.isNull():
            self.view.setPixmap(QPixmap.fromImage(img).scaled(self.view.size() - QSize(16, 16), Qt.KeepAspectRatio,
                                                              Qt.SmoothTransformation))
        else:
            self.view.setPixmap(QPixmap())
            self.view.setText(tr("🎬\n\nВидео — «Открыть в программе»") if m.is_video else tr("Превью недоступно"))

    def _thumb_ready(self, path, img):
        if self.i < len(self.group) and path == self.group[self.i].path:
            self._show_image(self.group[self.i])

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, lambda: self._show_image(self.group[self.i]))


# ---------------------------------------------------------------- вкладка

class DupsPage(QWidget):
    title_changed = Signal(str)
    finished = Signal(int, object)        # групп, байт к удалению — для уведомления из трея
    go_settings = Signal()
    settings_changed = Signal()

    def __init__(self, cfg, thumbs, colors):
        super().__init__(objectName="page")
        self.cfg, self.thumbs, self.colors = cfg, thumbs, colors
        self.groups, self.marked, self.errors = [], set(), []
        self.scan_root = ""
        self.cancel = None
        self.busy = False
        self.cards = {}
        self.current_group = None
        self.current_path = None
        self.items = {}            # путь → элемент дерева
        self._bold = QFont()
        self._bold.setBold(True)
        self._updating = False
        self.automark = True       # помечать лишние копии в новых группах (после «Снять все отметки» — нет)
        self.touched = False       # пользователь менял отметки руками — правило без спроса их не сотрёт
        self._rule_index = 0
        self.bridge = Bridge()
        self.bridge.progress.connect(self._show_progress)
        self.bridge.group.connect(self._group_found)
        self.pending = []
        self.flusher = QTimer(self, interval=400)       # новые группы — в список пачками, не по одной
        self.flusher.timeout.connect(self._flush)
        self.bridge.done.connect(self._finish)
        self.bridge.failed.connect(self._failed)
        self.thumbs.ready.connect(self._thumb_ready)
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

        head = QVBoxLayout()
        head.setSpacing(4)
        head.addWidget(U.label(tr("Поиск дубликатов"), "title"))
        head.addWidget(U.label(tr("Находит одинаковые файлы во всех вложенных папках и убирает лишние копии "
                                  "в Корзину."), "muted"))
        root.addLayout(head)

        card, cl = U.card()
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)
        grid.setColumnMinimumWidth(0, 96)
        grid.addWidget(U.label(tr("Папка"), "strong"), 0, 0)
        self.folder = QLineEdit(self.cfg.get("last_folder", ""))
        self.folder.setAcceptDrops(False)        # файлы бросают на окно целиком — поле их не перехватывает
        self.folder.setPlaceholderText(tr("Например, E:\\ или C:\\Users\\Имя\\Pictures"))
        self.folder.returnPressed.connect(self.start_scan)
        frow = QHBoxLayout()
        frow.setSpacing(8)
        frow.addWidget(self.folder, 1)
        choose = QPushButton(tr("Выбрать…"))
        choose.clicked.connect(self.choose)
        frow.addWidget(choose)
        grid.addLayout(frow, 0, 1)
        grid.addWidget(U.label(tr("Что искать"), "strong"), 1, 0)
        chips = QHBoxLayout()
        chips.setSpacing(8)
        self.chips = {}
        for key, (name, _exts) in dupcore.KINDS.items():
            b = QPushButton(tr(name), objectName="chip", checkable=True)
            b.setCursor(Qt.PointingHandCursor)
            b.setChecked(key in self.cfg.get("kinds", dupcore.DEFAULT_KINDS))
            b.toggled.connect(self._kinds_changed)
            chips.addWidget(b)
            self.chips[key] = b
        chips.addStretch()
        grid.addLayout(chips, 1, 1)
        self.hint = U.label("", "warn", wrap=True)
        grid.addWidget(self.hint, 2, 1)
        cl.addLayout(grid)
        act = QHBoxLayout()
        act.setSpacing(8)
        self.load_text = U.label("", "muted")
        act.addWidget(self.load_text)
        change = QPushButton(tr("Изменить"), objectName="link")
        change.setCursor(Qt.PointingHandCursor)
        change.clicked.connect(self.go_settings.emit)
        act.addWidget(change)
        act.addStretch()
        self.btn_stop = QPushButton(tr("Остановить"))
        self.btn_stop.clicked.connect(self.stop_scan)
        act.addWidget(self.btn_stop)
        self.btn_scan = QPushButton(tr("Начать поиск"), objectName="accent")
        self.btn_scan.clicked.connect(self.start_scan)
        act.addWidget(self.btn_scan)
        cl.addLayout(act)
        root.addWidget(card)

        prog = QVBoxLayout()
        prog.setSpacing(6)
        top = QHBoxLayout()
        self.step_text = U.label(tr("Выбери папку и нажми «Начать поиск»."), "strong")
        top.addWidget(self.step_text)
        top.addStretch()
        self.elapsed = U.label("", "muted")
        top.addWidget(self.elapsed)
        prog.addLayout(top)
        self.bar = QProgressBar(textVisible=False, maximum=1000)
        prog.addWidget(self.bar)
        self.status = U.label("", "muted", wrap=True)
        prog.addWidget(self.status)
        root.addLayout(prog)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(16)          # зазор между списком и сравнением (ширину ручки стиль не задаёт)
        self.stack = QStackedWidget()
        self.empty = U.label(tr("Здесь появятся найденные копии."), "empty")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        empty_box, eb = U.card()
        eb.addWidget(self.empty)
        self.stack.addWidget(empty_box)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels([tr("Удалить"), tr("Файл"), tr("Размер"), tr("Изменён"), tr("Где лежит")])
        self.tree.setRootIsDecorated(False)
        self.tree.setItemsExpandable(False)
        self.tree.setIndentation(0)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.setItemDelegate(RowTint(self.tree))
        self.tree.customContextMenuRequested.connect(self._menu)
        hdr = self.tree.header()
        hdr.setStretchLastSection(True)
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        self.tree.setColumnWidth(0, 76)
        self.tree.setColumnWidth(1, 250)
        self.tree.setColumnWidth(2, 90)
        self.tree.setColumnWidth(3, 140)
        hdr.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.currentItemChanged.connect(self._current_changed)
        self.tree.itemDoubleClicked.connect(self._double)
        self.tree.setMouseTracking(True)
        self.tree.viewport().installEventFilter(self)
        QShortcut(QKeySequence(Qt.Key_Space), self.tree, activated=self.quick_look)
        QShortcut(QKeySequence(Qt.Key_Delete), self.tree, activated=self._toggle_current)
        self.stack.addWidget(self.tree)
        split.addWidget(self.stack)

        cmp_card, cmp = U.card(margins=(16, 14, 16, 14), spacing=10)
        cmp_top = QHBoxLayout()
        cmp_top.addWidget(U.label(tr("Сравнение"), "h2"))
        cmp_top.addStretch()
        self.cmp_info = U.label("", "muted")
        cmp_top.addWidget(self.cmp_info)
        cmp.addLayout(cmp_top)
        self.cmp_hint = U.label(tr("Выбери группу или файл в списке — здесь появятся все копии рядом. "
                                   "Двойной щелчок по превью или пробел — быстрый просмотр."), "muted", wrap=True)
        cmp.addWidget(self.cmp_hint)
        self.cmp_scroll = QScrollArea(widgetResizable=True)
        self.cmp_scroll.setFrameShape(QFrame.NoFrame)
        self.cmp_body = QWidget()
        self.cmp_grid = QGridLayout(self.cmp_body)
        self.cmp_grid.setContentsMargins(0, 0, 0, 0)
        self.cmp_grid.setSpacing(12)
        self.cmp_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.cmp_scroll.setWidget(self.cmp_body)
        cmp.addWidget(self.cmp_scroll, 1)
        cmp_card.setMinimumWidth(270)
        split.addWidget(cmp_card)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([700, 520])
        self.split = split
        root.addWidget(split, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        bottom.addWidget(U.label(tr("В каждой группе оставлять")))
        self.rule = QComboBox()
        for key, name in dupcore.KEEP_RULES.items():
            self.rule.addItem(tr(name), key)
        self.rule.setCurrentIndex(max(0, self.rule.findData(self.cfg.get("keep_rule", "oldest"))))
        self._rule_index = self.rule.currentIndex()
        self.rule.currentIndexChanged.connect(self._rule_changed)
        bottom.addWidget(self.rule)
        unmark = QPushButton(tr("Снять все отметки"))
        unmark.clicked.connect(self.unmark_all)
        bottom.addWidget(unmark)
        self.btn_errors = QPushButton()
        self.btn_errors.clicked.connect(self.show_errors)
        self.btn_errors.hide()
        bottom.addWidget(self.btn_errors)
        bottom.addStretch()
        root.addLayout(bottom)

        # Итог и кнопка удаления — своей строкой в самом низу: при узком окне длинный итог не обрезается,
        # а главная кнопка там, где её ищут, — справа внизу.
        totals = QHBoxLayout()
        totals.setSpacing(10)
        self.summary = U.label("", "strong")
        totals.addWidget(self.summary, 1)
        self.btn_delete = QPushButton(tr("Удалить в Корзину"), objectName="danger")
        self.btn_delete.clicked.connect(self.delete_marked)
        totals.addWidget(self.btn_delete)
        root.addLayout(totals)
        self._kinds_changed()

    def eventFilter(self, obj, ev):
        """Над флажком «Удалить» в строке файла — курсор-«пальчик»."""
        if obj is self.tree.viewport() and ev.type() == QEvent.MouseMove:
            pos = ev.position().toPoint()
            it = self.tree.itemAt(pos)
            over_box = (it is not None and it.data(1, FILE_ROLE) is not None
                        and self.tree.columnAt(pos.x()) == 0)
            obj.setCursor(Qt.PointingHandCursor if over_box else Qt.ArrowCursor)
        return super().eventFilter(obj, ev)

    def set_load_text(self):
        self.load_text.setText(tr("Нагрузка на компьютер: {name}",
                                  name=tr(LOAD_NAMES[self.cfg.get("load", "gentle")])))

    # ---------- типы файлов

    def kinds(self):
        return {k for k, b in self.chips.items() if b.isChecked()}

    def _kinds_changed(self, *_):
        kinds = self.kinds()
        if "other" in kinds:
            self.hint.setText(tr("Осторожно с «остальными файлами»: в папках программ и игр одинаковые файлы нужны "
                                 "на своих местах. Удаляй только то, что узнаёшь. Системные файлы Windows "
                                 "программа пропускает сама."))
        elif not kinds:
            self.hint.setText(tr("Отметь хотя бы один тип файлов."))
        else:
            self.hint.setText("")
        self.hint.setVisible(bool(self.hint.text()))
        self.cfg["kinds"] = sorted(kinds)
        self.settings_changed.emit()

    # ---------- поиск

    def choose(self):
        d = QFileDialog.getExistingDirectory(self, tr("Где искать дубликаты"), self.folder.text() or "")
        if d:
            self.folder.setText(os.path.normpath(d))
            self.btn_scan.setFocus()           # поиск — по кнопке «Начать поиск», не сам

    def use_drop(self, paths):
        """Перетащенное: папка — в поле; файлы — их папка, и отмечается их тип (фото, видео…)."""
        dirs = [p for p in paths if os.path.isdir(p)]
        files = [p for p in paths if not os.path.isdir(p)]
        if dirs:
            folder = dirs[0]
        else:
            try:
                folder = os.path.commonpath([os.path.dirname(p) for p in files])
            except ValueError:                    # файлы с разных дисков — папка первого
                folder = os.path.dirname(files[0])
        for k in {dupcore.kind_of(p) for p in files}:
            self.chips[k].setChecked(True)
        self.folder.setText(os.path.normpath(folder))
        self.btn_scan.setFocus()                  # поиск — по кнопке «Начать поиск», не сам
        if len(dirs) > 1:
            self.step_text.setText(tr("Перетащено несколько папок — подставлена первая: {name}",
                                      name=os.path.basename(folder) or folder))
        return folder

    def start_scan(self):
        if self.busy:
            return
        root = self.folder.text().strip().strip('"')
        if not root or not os.path.isdir(root):
            U.warn(self, tr("Такой папки нет. Нажми «Выбрать…» и укажи папку."))
            return
        kinds = self.kinds()
        if not kinds:
            U.warn(self, tr("Отметь хотя бы один тип файлов: фото, видео, музыку…"))
            return
        self.cfg["last_folder"] = root
        self.settings_changed.emit()
        self.groups, self.marked, self.errors = [], set(), []
        self.pending = []
        self.current_path = None
        self.automark, self.touched = True, False
        self.scan_root = os.path.abspath(root)
        self.refresh()
        self.stack.setCurrentIndex(0)
        self.empty.setText(tr("Ищу… Найденные копии появятся здесь сразу, не дожидаясь конца поиска."))
        self.cancel = threading.Event()
        self.clock = StepClock()
        self.started = time.monotonic()
        self._last_push = 0.0
        self._set_busy(True)
        self.step_text.setText(tr("Начинаю…"))
        self.status.setText("")
        self.btn_errors.hide()
        self.ticker.start()
        self._tick()
        load = self.cfg.get("load", "gentle")
        log.info("Поиск: %s · типы %s · нагрузка %s", root, ",".join(sorted(kinds)), load)
        threading.Thread(target=self._worker, args=(root, self.cancel, kinds, load), daemon=True).start()

    def _worker(self, root, cancel, kinds, load):
        def progress(step, title, done, total, unit):
            now = time.monotonic()
            if now - self._last_push > 0.15 or (total and done >= total) or done == 0:
                self._last_push = now
                self.bridge.progress.emit(step, title, done, total, unit)
        try:
            self.bridge.done.emit(dupcore.find_duplicates(root, progress, cancel, kinds, load,
                                                          on_group=self.bridge.group.emit))
        except Exception as e:                   # чтобы окно не зависло в «ищу» навсегда
            log.exception("Поиск упал")
            self.bridge.failed.emit(str(e))

    def _tick(self):
        if self.busy:
            self.elapsed.setText(tr("прошло {t}", t=dupcore.human_time(time.monotonic() - self.started)))

    def _show_progress(self, step, title, done, total, unit):
        if not self.busy:
            return
        self.step_text.setText(tr("Шаг {step} из {steps} · {title}", step=step, steps=dupcore.STEPS, title=tr(title)))
        pct = f", {done * 100 // total}%" if total else ""
        self.title_changed.emit(tr("{app} — шаг {step} из {steps}{pct}", app=U.APP_TITLE, step=step,
                                   steps=dupcore.STEPS, pct=pct))
        rate, left = self.clock.update(step, done, total)
        if step == 1:
            self.bar.setRange(0, 0)               # бегущая полоса: сколько всего — ещё неизвестно
            self.status.setText(tr("Найдено файлов: {n}. Сколько осталось, станет ясно на следующих шагах.",
                                   n=num(done)))
            return
        self.bar.setRange(0, 1000)
        if not total:
            self.bar.setValue(1000)
            self.status.setText(tr("На этом шаге проверять нечего."))
            return
        self.bar.setValue(int(1000 * done / total))
        if unit == "bytes":
            parts = [tr("{done} из {total}", done=dupcore.human_size(done), total=dupcore.human_size(total))]
            if rate:
                parts.append(tr("{rate}/с", rate=dupcore.human_size(rate)))
        else:
            parts = [tr("{done} из {total} файлов", done=num(done), total=num(total))]
        parts.append(tr("осталось ≈ {t}", t=dupcore.human_time(left)) if left is not None
                     else tr("считаю, сколько осталось…"))
        if step < dupcore.STEPS:
            parts.append(tr("потом ещё шаг {n}", n=step + 1))
        self.status.setText(" · ".join(parts))

    def stop_scan(self):
        if self.cancel:
            self.cancel.set()
            self.step_text.setText(tr("Останавливаю…"))

    def _failed(self, text):
        self._set_busy(False)
        self.title_changed.emit(U.APP_TITLE)
        U.warn(self, tr("Поиск прервался из-за ошибки:\n{text}", text=text))

    def _finish(self, res):
        took = dupcore.human_time(time.monotonic() - self.started)
        self._set_busy(False)
        self.title_changed.emit(U.APP_TITLE)
        self.bar.setRange(0, 1000)
        self.bar.setValue(0 if res.cancelled else 1000)
        self.elapsed.setText("")
        self.errors = res.errors
        log.info("Поиск %s за %s: файлов %d (%s), групп %d, лишних копий %d, облачных пропущено %d, "
                 "не прочитано %d", "остановлен" if res.cancelled else "завершён", took, res.files_seen,
                 dupcore.human_size(res.bytes_seen), len(self.groups), sum(len(g) - 1 for g in self.groups),
                 res.cloud_skipped, len(res.errors))
        for path, err in res.errors[:50]:
            log.info("   не прочитан: %s — %s", path, err)
        seen = tr("Проверено файлов: {n} ({size}).", n=num(res.files_seen), size=dupcore.human_size(res.bytes_seen))
        if res.cloud_skipped:
            seen += tr(" Пропущено файлов, которые лежат только в облаке или на телефоне: {n} — их пришлось "
                       "бы скачивать.", n=num(res.cloud_skipped))
        if res.cancelled:
            self.step_text.setText(tr("Поиск остановлен.") + (tr(" Показаны копии, найденные до остановки.")
                                                              if self.groups else ""))
            self.status.setText(tr("Прошло {t}.", t=took))
            self.empty.setText(tr("Поиск остановлен раньше, чем нашлись копии."))
        elif not self.groups:
            self.step_text.setText(tr("Готово за {t}. Копий нет.", t=took))
            self.status.setText(seen)
            self.empty.setText(tr("Точных копий не нашлось 🎉"))
        else:
            self.step_text.setText(tr("Готово за {t}. Лишние копии отмечены — проверь и удали.", t=took))
            self.status.setText(seen)
        self.finished.emit(len(self.groups), self._marked_size())
        if self.errors:
            self.btn_errors.setText(tr("Не прочитались: {n}", n=num(len(self.errors))))
            self.btn_errors.show()

    def _set_busy(self, busy):
        self.busy = busy
        self.btn_scan.setEnabled(not busy)
        self.btn_stop.setEnabled(busy)
        if busy:
            self.flusher.start()                 # находки — в список, пока идёт поиск
        else:
            self.ticker.stop()
            self.flusher.stop()
            self._flush()
        self._update_summary()

    def _group_found(self, g):
        self.pending.append(g)

    def _flush(self):
        """Добавить найденные за последние доли секунды группы в конец списка."""
        if not self.pending:
            return
        new, self.pending = self.pending, []
        rule = self.rule.currentData()
        start = len(self.groups)
        add = set()
        for g in new:
            dupcore.sort_keep_first(g, rule)
            if self.automark:
                add.update(m.path for m in g[1:])
        # Сначала строки, и только потом группы и отметки — при сбое на строке список и отметки не разойдутся.
        self._updating = True
        try:
            heads = [self._make_head(start + i, g, add) for i, g in enumerate(new)]
            self.groups.extend(new)
            self.marked |= add
            self.tree.addTopLevelItems(heads)
            top = QModelIndex()
            for i, h in enumerate(heads):
                h.setExpanded(True)
                self.tree.setFirstColumnSpanned(start + i, top, True)
        finally:
            self._updating = False
        self.stack.setCurrentIndex(1)
        if self.tree.currentItem() is None:          # первая находка — сразу показать в сравнении
            self.tree.setCurrentItem(heads[0].child(0))
        self._update_summary()

    # ---------- отметки

    def apply_rule(self, refresh=True):
        key = self.rule.currentData()
        self.automark, self.touched = True, False
        self.marked = set()
        for g in self.groups:
            dupcore.sort_keep_first(g, key)
            self.marked.update(m.path for m in g[1:])
        if refresh:
            self.refresh()

    def _rule_changed(self, index):
        if self.touched and self.groups and not U.ask_yes_no(
                self, tr("Отметить копии заново по новому правилу? Отметки, которые ты менял вручную, сбросятся."),
                yes=tr("Отметить заново")):
            self.rule.blockSignals(True)
            self.rule.setCurrentIndex(self._rule_index)
            self.rule.blockSignals(False)
            return
        self._rule_index = index
        self.cfg["keep_rule"] = self.rule.currentData()
        self.settings_changed.emit()
        self.apply_rule()

    def unmark_all(self):
        self.marked.clear()
        self.automark = False          # и то, что найдётся дальше, не помечать без тебя
        self.touched = True
        self.refresh()

    def group_of(self, path):
        for g in self.groups:
            for m in g:
                if m.path == path:
                    return g
        return None

    def toggle_file(self, mf):
        """Переключить «удалить/оставить». Последнюю оставляемую копию отметить нельзя."""
        if mf.path in self.marked:
            self.marked.discard(mf.path)
        else:
            group = self.group_of(mf.path)
            if not any(m.path != mf.path and m.path not in self.marked for m in group):
                U.info(self, tr("Это последняя оставляемая копия в группе — хоть одну надо оставить."))
                self._sync_item(mf.path)
                return False
            self.marked.add(mf.path)
        self.touched = True
        self._sync_item(mf.path)
        self._sync_cards()
        self._update_summary()
        return True

    def _toggle_current(self):
        it = self.tree.currentItem()
        mf = it.data(1, FILE_ROLE) if it else None
        if mf is not None:
            self.toggle_file(mf)

    def _item_changed(self, item, col):
        if self._updating or col != 0:
            return
        mf = item.data(1, FILE_ROLE)
        if mf is None:
            return
        want = item.checkState(0) == Qt.Checked
        if want != (mf.path in self.marked):
            self.toggle_file(mf)

    def keep_only(self, mf):
        self.touched = True
        for m in self.group_of(mf.path):
            (self.marked.discard if m is mf else self.marked.add)(m.path)
        for m in self.group_of(mf.path):
            self._sync_item(m.path)
        self._sync_cards()
        self._update_summary()

    # ---------- список

    def short_dir(self, path):
        rel = os.path.relpath(os.path.dirname(path), self.scan_root) if self.scan_root else os.path.dirname(path)
        return tr("(в самой папке)") if rel == "." else rel

    def refresh(self):
        self._updating = True
        keep = self.current_path
        self.tree.setUpdatesEnabled(False)
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            self.items.clear()
            heads = [self._make_head(gi, g) for gi, g in enumerate(self.groups)]
            # Всё дерево разом, потом раскрыть и растянуть заголовки групп. По одной строке это
            # квадратично: 1736 групп — 940 мс против 9 мс пачкой (Qt пересчитывает список на каждую).
            self.tree.addTopLevelItems(heads)
            self.tree.expandAll()
            top = QModelIndex()
            for i in range(len(heads)):
                self.tree.setFirstColumnSpanned(i, top, True)
        finally:
            self.tree.blockSignals(False)
            self.tree.setUpdatesEnabled(True)
            self._updating = False
        self.stack.setCurrentIndex(1 if self.groups else 0)
        if keep in self.items:
            self.tree.setCurrentItem(self.items[keep])
        else:
            self.show_group(None)
        self._update_summary()

    def _make_head(self, gi, g, extra_marked=()):
        kind = tr(dupcore.KIND_WORD[dupcore.kind_of(g[0].path)])
        head = QTreeWidgetItem([tr("Группа {n}  ·  {count} одинаковых {kind}  ·  {size} каждая", n=gi + 1,
                                   count=len(g), kind=kind, size=dupcore.human_size(g[0].size))])
        head.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        head.setFont(0, self._bold)
        head.setForeground(0, QColor(self.colors["muted"]))
        head.setBackground(0, QColor(self.colors["group"]))
        head.setData(0, FILE_ROLE, gi)
        for m in g:
            it = QTreeWidgetItem(["", os.path.basename(m.path), dupcore.human_size(m.size),
                                  fmt_date(m.mtime), self.short_dir(m.path)])
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            it.setData(1, FILE_ROLE, m)
            it.setToolTip(1, m.path)
            it.setToolTip(0, tr("Отметка — файл уйдёт в Корзину"))
            it.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
            head.addChild(it)
            self.items[m.path] = it
            self._paint_item(it, m, m.path in extra_marked)
        return head

    def _paint_item(self, it, m, also_marked=False):
        on = m.path in self.marked or also_marked
        it.setCheckState(0, Qt.Checked if on else Qt.Unchecked)
        it.setForeground(1, QColor(self.colors["danger"] if on else self.colors["keep"]))
        tint = QBrush(QColor(self.colors["row_del"])) if on else QBrush()
        for col in range(5):                     # отмеченная строка целиком подкрашена — видно издалека
            it.setBackground(col, tint)

    def _sync_item(self, path):
        it = self.items.get(path)
        if it is not None:
            self._updating = True
            try:
                self._paint_item(it, it.data(1, FILE_ROLE))
            finally:
                self._updating = False

    def _marked_size(self):
        return sum(m.size for g in self.groups for m in g if m.path in self.marked)

    def _update_summary(self):
        n = len(self.marked)
        size = self._marked_size()
        if n:
            self.btn_delete.setText(tr("Удалить {n} {files} в Корзину  ·  освободится {size}", n=num(n),
                                       files=plural(n, "файл|файла|файлов", "file|files"),
                                       size=dupcore.human_size(size)))
        else:
            self.btn_delete.setText(tr("Удалить в Корзину"))
        self.btn_delete.setEnabled(n > 0)      # удалять можно и во время поиска — найденное уже проверено
        if not self.groups:
            self.summary.setText("")
            return
        extra = sum(len(g) - 1 for g in self.groups)
        more = tr("  ·  поиск продолжается…") if self.busy else ""
        self.summary.setText(tr("Групп: {groups}  ·  лишних копий: {extra}  ·  отмечено: {marked}",
                                groups=num(len(self.groups)), extra=num(extra), marked=num(n)) + more)

    def _current_changed(self, cur, _prev):
        if cur is None:
            self.show_group(None)
            return
        mf = cur.data(1, FILE_ROLE)
        if mf is not None:
            self.current_path = mf.path
            self.show_group(self.group_of(mf.path))
        else:
            gi = cur.data(0, FILE_ROLE)
            self.current_path = None
            self.show_group(self.groups[gi] if gi is not None and gi < len(self.groups) else None)

    def _double(self, item, col):
        mf = item.data(1, FILE_ROLE)
        if mf is not None and col != 0:
            U.open_file(mf.path)

    def _menu(self, pos):
        item = self.tree.itemAt(pos)
        mf = item.data(1, FILE_ROLE) if item else None
        if mf is None:
            return
        menu = QMenu(self)
        menu.addAction(tr("Быстрый просмотр  (пробел)"), self.quick_look)
        menu.addAction(tr("Открыть"), lambda: U.open_file(mf.path))
        menu.addAction(tr("Показать в папке"), lambda: U.reveal(mf.path))
        menu.addSeparator()
        menu.addAction(tr("Оставить только этот, остальные удалить"), lambda: self.keep_only(mf))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # ---------- сравнение

    def clear_cards(self):
        """Убрать карточки сравнения — после удаления и смены темы их надо построить заново.

        Только «current_group = None» мало: если после этого группы нет, show_group(None) не видит смены
        и оставляет на экране карточки удалённых файлов.
        """
        self.current_group = None
        for c in self.cards.values():
            c.setParent(None)
            c.deleteLater()
        self.cards = {}

    def show_group(self, group):
        if group is not self.current_group:
            self.clear_cards()
            self.current_group = group
            if group:
                for m in group:
                    c = FileCard(m, self.short_dir(m.path), self.colors)
                    c.clicked.connect(self._card_clicked)
                    c.toggle.connect(self.toggle_file)
                    c.preview.connect(lambda mf: self.quick_look(mf))
                    self.cards[m.path] = c
                    c.set_image(self.thumbs.get(m.path))
                self._layout_cards()
        self.cmp_hint.setVisible(not group)
        if not group:
            self.cmp_info.setText("")
        self._sync_cards()

    def _layout_cards(self):
        while self.cmp_grid.count():
            self.cmp_grid.takeAt(0)
        cols = max(1, (self.cmp_scroll.viewport().width() + 12) // (234 + 12))
        for i, c in enumerate(self.cards.values()):
            self.cmp_grid.addWidget(c, i // cols, i % cols)
        self._cols = cols

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._maybe_relayout)

    def _maybe_relayout(self):
        if self.cards:
            cols = max(1, (self.cmp_scroll.viewport().width() + 12) // (234 + 12))
            if cols != getattr(self, "_cols", 0):
                self._layout_cards()

    def _sync_cards(self):
        for path, c in self.cards.items():
            c.set_state(path in self.marked, path == self.current_path)
        if self.current_group:
            n = len(self.current_group)
            kept = sum(m.path not in self.marked for m in self.current_group)
            self.cmp_info.setText(tr("{n} {copies} · остаётся {kept}", n=n,
                                     copies=plural(n, "копия|копии|копий", "copy|copies"), kept=kept))

    def _card_clicked(self, mf):
        it = self.items.get(mf.path)
        if it is not None:
            self.tree.setCurrentItem(it)

    def _thumb_ready(self, path, img):
        c = self.cards.get(path)
        if c is not None:
            c.set_image(img)

    def quick_look(self, mf=None):
        if mf is None:
            it = self.tree.currentItem()
            mf = it.data(1, FILE_ROLE) if it else None
            if mf is None and self.current_group:
                mf = self.current_group[0]
        if mf is None:
            return
        group = self.group_of(mf.path)
        QuickLook(self, group, group.index(mf)).exec()

    # ---------- ошибки и удаление

    def _delete_with_progress(self, paths):
        """Удаление в фоне пачками, с полосой прогресса: тысячи файлов не вешают окно."""
        from PySide6.QtWidgets import QApplication, QProgressDialog
        dlg = QProgressDialog(tr("Отправляю в Корзину…"), None, 0, len(paths), self)
        dlg.setWindowTitle(U.APP_TITLE)
        dlg.setMinimumDuration(400)
        dlg.setWindowModality(Qt.WindowModal)
        result = {}
        hwnd = int(self.window().winId())

        def work():
            result["v"] = dupcore.to_recycle_bin(paths, hwnd=hwnd,
                                                 progress=lambda n: result.__setitem__("n", n))
        th = threading.Thread(target=work, daemon=True)
        th.start()
        while th.is_alive():
            n = result.get("n", 0)
            dlg.setValue(n)
            dlg.setLabelText(tr("Отправляю в Корзину: {done} из {total}", done=num(n), total=num(len(paths))))
            QApplication.processEvents()
            th.join(0.05)
        dlg.close()
        return result.get("v", ([], list(paths)))

    def show_errors(self):
        lines = [f"{p}\n    {e}" for p, e in self.errors[:40]]
        more = tr("\n…и ещё {n}", n=len(self.errors) - 40) if len(self.errors) > 40 else ""
        U.info(self, tr("Эти файлы или папки не удалось прочитать, они не участвовали в поиске:\n\n")
               + "\n".join(lines) + more)

    def delete_marked(self):
        if not self.marked:
            U.info(self, tr("Ничего не отмечено."))
            return
        ok, problems = dupcore.check_before_delete(self.groups, self.marked)
        if not ok:
            U.warn(self, tr("Удалять нечего:\n\n") + _problems_text(problems))
            return
        size = dupcore.human_size(sum(m.size for m in ok))
        no_bin = sorted({d for d in (dupcore.drive_of(m.path) for m in ok) if not dupcore.has_recycle_bin(d)})
        text = tr("Отправить в Корзину {n} {files}, {size}?\n\n"
                  "В каждой группе останется хотя бы одна копия. Вернуть можно из Корзины.",
                  n=num(len(ok)), files=plural(len(ok), "файл|файла|файлов", "file|files"), size=size)
        if no_bin:
            text += tr("\n\n⚠ На дисках {drives} Корзины нет (флешка, карта памяти или сетевой диск): "
                       "файлы оттуда удалятся НАВСЕГДА, вернуть их будет нельзя.", drives=", ".join(no_bin))
        if problems:
            text += tr("\n\nПропущу:\n") + _problems_text(problems)
        if not U.ask_yes_no(self, text, yes=tr("Удалить навсегда") if no_bin else tr("Удалить в Корзину")):
            return
        # Пока было открыто окно подтверждения, файлы могли измениться — проверяем ещё раз прямо перед удалением.
        ok, problems = dupcore.check_before_delete(self.groups, self.marked)
        if not ok:
            U.warn(self, tr("Удалять нечего:\n\n") + _problems_text(problems))
            return
        removed, left = self._delete_with_progress([m.path for m in ok])
        log.info("В Корзину: %d файлов, не удалось %d, пропущено проверкой %d", len(removed), len(left),
                 len(problems))
        for path in removed:
            log.info("   в Корзине: %s", path)
        for path in left:
            log.warning("   не удалось удалить: %s", path)
        for path, why in problems:
            log.info("   пропущен: %s — %s", path, why)
        # Сверка по точному пути, без приведения регистра: в папках с учётом регистра a.jpg и A.jpg — разные файлы.
        gone = set(removed)
        freed = dupcore.human_size(sum(m.size for m in ok if os.path.abspath(m.path) in gone))
        for g in self.groups:
            g[:] = [m for m in g if os.path.abspath(m.path) not in gone]
        self.groups = [g for g in self.groups if len(g) > 1]
        self.marked = {p for p in self.marked if os.path.abspath(p) not in gone}
        alive = {m.path for g in self.groups for m in g}
        self.marked &= alive               # отметки файлов, чьи группы распались, — больше не считаются
        for p in removed:
            self.thumbs.forget(p)
        self.clear_cards()
        self.refresh()
        if not self.groups:
            self.empty.setText(tr("Все отмеченные копии в Корзине."))
        msg = tr("В Корзину отправлено: {n} ({size}).", n=num(len(removed)), size=freed)
        if left:
            msg += tr("\n\nНе удалось удалить {n}:\n", n=len(left)) + "\n".join(left[:20])
        U.info(self, msg)
        self.step_text.setText(tr("Отправлено в Корзину: {n} ({size}). Вернуть можно из Корзины.",
                                  n=num(len(removed)), size=freed))


def _problems_text(problems):
    lines = [f"• {os.path.basename(p)} — {tr(why)}" for p, why in problems[:15]]
    if len(problems) > 15:
        lines.append(tr("…и ещё {n}", n=len(problems) - 15))
    return "\n".join(lines)
