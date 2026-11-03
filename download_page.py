"""Вкладка «Скачать»: видео и звук по ссылке — очередь, ход, готовое — сразу в «Сжатие», «Конвертацию», «Метаданные».

Логика — в dlcore.py (yt-dlp). Здесь: поле ссылок, что и куда, очередь (по одному видео), разрешение скачать
сам yt-dlp. Защищённое от копирования (DRM) не скачивается — в строке видна причина.
"""

import os
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QFileDialog, QGridLayout, QHBoxLayout,
                               QHeaderView, QLineEdit, QMenu, QPlainTextEdit, QProgressBar, QPushButton,
                               QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import dlcore
import dupcore
import ui_util as U
from compress_page import WrapLabel
from dups_page import RowTint
from i18n import num, plural, tr
from logs import log

ITEM_ROLE = Qt.UserRole
TICK_MS = 500                # ход скачивания окно перечитывает дважды в секунду


def EMPTY_TEXT():
    return tr("Здесь появятся видео и песни, которые ты скачаешь.\n\nВставь ссылку выше и нажми «Скачать».")


class LinksEdit(QPlainTextEdit):
    """Поле ссылок: одна строка, растёт с текстом до MAX_LINES строк (с переносом длинных ссылок), дальше — прокрутка."""

    MAX_LINES = 4

    def __init__(self):
        super().__init__()
        self.textChanged.connect(self.fit)

    def lines(self):
        """Сколько строк сейчас на экране — вместе с перенесёнными длинными ссылками."""
        return max(1, int(round(self.document().documentLayout().documentSize().height())))

    def fit(self):
        lines = self.lines()
        n = min(lines, self.MAX_LINES)
        chrome = self.height() - self.viewport().height()          # рамка и поля из стиля
        h = n * self.fontMetrics().lineSpacing() + int(2 * self.document().documentMargin()) + chrome
        if h != self.height():
            self.setFixedHeight(h)
        # QPlainTextEdit считает прокрутку строками и даёт её даже при одной строке, которая влезает целиком —
        # поле могло сдвинуться и спрятать первую ссылку. Пока всё видно, прокрутки нет вовсе.
        fits = lines <= self.MAX_LINES
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff if fits else Qt.ScrollBarAsNeeded)
        if fits:
            self.verticalScrollBar().setValue(0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit()                       # ширина другая — длинные ссылки переносятся иначе

    def showEvent(self, e):
        super().showEvent(e)
        self.fit()


class DlBridge(QObject):
    changed = Signal(object)              # dlcore.Item
    expanded = Signal(object, object)     # ссылка на плейлист → видео из него
    step = Signal(str)                    # что сейчас с самим yt-dlp
    done = Signal()


class DownloadPage(QWidget):
    title_changed = Signal(str)
    settings_changed = Signal()
    send = Signal(str, object)            # ("compress" / "convert" / "meta", пути готовых файлов)

    def __init__(self, cfg, colors):
        super().__init__(objectName="page")
        self.cfg, self.colors = cfg, colors
        self.busy = False
        self.cancel = None
        self.queue = []                   # все строки списка по порядку
        self.lock = threading.Lock()
        self.rows = {}                    # id(item) → QTreeWidgetItem
        self._last_emit = {}
        self.bridge = DlBridge()
        self.bridge.changed.connect(self._changed)
        self.bridge.expanded.connect(self._expanded)
        self.bridge.step.connect(self._step)
        self.bridge.done.connect(self._finished)
        self.ticker = QTimer(self, interval=TICK_MS)
        self.ticker.timeout.connect(self._tick)
        self._build()
        self._set_busy(False)

    # ---------- раскладка

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(16)
        root.addWidget(U.label(tr("Скачать по ссылке"), "title"))

        card, cl = U.card()
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnMinimumWidth(0, 96)
        self.links_label = U.label(tr("Ссылки"), "strong")
        grid.addWidget(self.links_label, 0, 0, Qt.AlignTop)
        lrow = QHBoxLayout()
        lrow.setSpacing(8)
        self.links = LinksEdit()
        self.links.setPlaceholderText(tr("Вставь ссылку на видео, песню или плейлист — можно несколько"))
        self.links.setTabChangesFocus(True)
        self.links.setAcceptDrops(False)          # файлы бросают на окно целиком — поле их не перехватывает
        self.links.viewport().setAcceptDrops(False)
        self.links.textChanged.connect(self._update_buttons)
        lrow.addWidget(self.links, 1)
        paste = QPushButton(tr("Вставить"))
        paste.setToolTip(tr("Вставить ссылки из буфера обмена"))
        paste.clicked.connect(self.paste)
        lrow.addWidget(paste, 0, Qt.AlignTop)
        grid.addLayout(lrow, 0, 1)

        grid.addWidget(U.label(tr("Что"), "strong"), 1, 0)
        krow = QHBoxLayout()
        krow.setSpacing(8)
        self.kind_group = QButtonGroup(self)
        self.kind_btns = {}
        for key, name in dlcore.KINDS.items():
            b = QPushButton(tr(name), objectName="chip", checkable=True)
            self.kind_group.addButton(b)
            b.toggled.connect(lambda on, k=key: on and self._kind_picked(k))
            krow.addWidget(b)
            self.kind_btns[key] = b
        krow.addSpacing(16)
        self.quality = self._combo(dlcore.QUALITIES, "dl_quality")
        self.quality_label = U.label(tr("Качество"), "muted")
        krow.addWidget(self.quality_label)
        krow.addWidget(self.quality)
        self.audio = self._combo(dlcore.AUDIO_FORMATS, "dl_audio")
        self.audio.setToolTip(tr("MP3 откроется везде. M4A — чуть меньше при том же звуке."))
        self.audio_label = U.label(tr("Формат"), "muted")
        krow.addWidget(self.audio_label)
        krow.addWidget(self.audio)
        krow.addStretch()
        grid.addLayout(krow, 1, 1)

        grid.addWidget(U.label(tr("Куда"), "strong"), 2, 0)
        frow = QHBoxLayout()
        frow.setSpacing(8)
        self.folder = QLineEdit(self.cfg.get("dl_folder") or dlcore.default_folder())
        self.folder.setAcceptDrops(False)
        self.folder.editingFinished.connect(self._folder_edited)
        frow.addWidget(self.folder, 1)
        choose = QPushButton(tr("Выбрать…"))
        choose.clicked.connect(self.choose)
        frow.addWidget(choose)
        open_btn = QPushButton(tr("Открыть папку"), objectName="link")
        open_btn.clicked.connect(self.open_folder)
        frow.addWidget(open_btn)
        grid.addLayout(frow, 2, 1)
        cl.addLayout(grid)

        act = QHBoxLayout()
        act.setSpacing(8)
        act.addWidget(U.label(tr("Скачивай только то, на что у тебя есть право."), "muted"))
        act.addStretch()
        self.btn_stop = QPushButton(tr("Остановить"))
        self.btn_stop.clicked.connect(self.stop)
        act.addWidget(self.btn_stop)
        self.btn_start = QPushButton(tr("Скачать"), objectName="accent")
        self.btn_start.clicked.connect(self.start)
        act.addWidget(self.btn_start)
        cl.addLayout(act)
        root.addWidget(card)

        prog = QVBoxLayout()
        prog.setSpacing(6)
        self.step_text = U.label(tr("Вставь ссылку и нажми «Скачать»."), "strong")
        prog.addWidget(self.step_text)
        self.bar = QProgressBar(textVisible=False, maximum=1000)
        prog.addWidget(self.bar)
        self.status = WrapLabel("", "muted")
        prog.addWidget(self.status)
        root.addLayout(prog)

        self.stack = QStackedWidget()
        empty_box, eb = U.card()
        self.empty = U.label(EMPTY_TEXT(), "empty")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        eb.addWidget(self.empty)
        self.stack.addWidget(empty_box)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels([tr("Название"), tr("Что"), tr("Размер"), tr("Как идёт")])
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setItemDelegate(RowTint(self.tree))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemSelectionChanged.connect(self._update_buttons)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._open(it.data(0, ITEM_ROLE)))
        hdr = self.tree.header()
        hdr.setStretchLastSection(False)
        hdr.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, w in ((1, 130), (2, 90), (3, 420)):     # причина отказа — целиком, полный текст — в подсказке
            hdr.setSectionResizeMode(col, QHeaderView.Interactive)
            self.tree.setColumnWidth(col, w)
        self.stack.addWidget(self.tree)
        root.addWidget(self.stack, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self.btn_show = QPushButton(tr("Показать в папке"))
        self.btn_show.clicked.connect(lambda: self._done_selected() and U.reveal(self._done_selected()[0].path))
        bottom.addWidget(self.btn_show)
        bottom.addSpacing(12)
        self.btn_to = {}
        for key, name in (("compress", tr("Сжать")), ("convert", tr("Конвертировать")),
                          ("meta", tr("Убрать метаданные"))):
            b = QPushButton(name)
            b.clicked.connect(lambda _=False, k=key: self.send.emit(k, [i.path for i in self._done_selected()]))
            bottom.addWidget(b)
            self.btn_to[key] = b
        bottom.addStretch()
        self.btn_clear = QPushButton(tr("Очистить список"))
        self.btn_clear.setToolTip(tr("Убрать из списка всё, кроме того, что ещё скачивается. Файлы останутся в "
                                     "папке."))
        self.btn_clear.clicked.connect(self.clear_list)
        bottom.addWidget(self.btn_clear)
        root.addLayout(bottom)

        kind = self.cfg.get("dl_kind", "video")
        self.kind_btns[kind if kind in dlcore.KINDS else "video"].setChecked(True)

    def showEvent(self, e):
        super().showEvent(e)
        # «Ссылки» — на одной линии с первой строкой поля, а не выше: поле растёт вниз, подпись стоит у верха
        top = self.links.viewport().y() + int(self.links.document().documentMargin())
        self.links_label.setContentsMargins(0, top, 0, 0)

    def _combo(self, table, key):
        box = QComboBox(sizeAdjustPolicy=QComboBox.AdjustToContents)
        for value, name in table.items():
            box.addItem(tr(name), value)
        box.setCurrentIndex(max(0, box.findData(self.cfg.get(key))))
        box.currentIndexChanged.connect(lambda _i, k=key, b=box: self._save(k, b.currentData()))
        return box

    def _save(self, key, value):
        self.cfg[key] = value
        self.settings_changed.emit()

    def _kind_picked(self, key):
        video = key == "video"
        for w in (self.quality, self.quality_label):
            w.setVisible(video)                 # у звука качество кадра ни при чём — не показываем вовсе
        for w in (self.audio, self.audio_label):
            w.setVisible(not video)
        self._save("dl_kind", key)

    def kind(self):
        return next((k for k, b in self.kind_btns.items() if b.isChecked()), "video")

    # ---------- папка и ссылки

    def folder_path(self):
        return os.path.normpath(self.folder.text().strip().strip('"') or dlcore.default_folder())

    def _folder_edited(self):
        self._save("dl_folder", self.folder.text().strip().strip('"'))

    def choose(self):
        start = self.folder_path() if os.path.isdir(self.folder_path()) else os.path.expanduser("~")
        d = QFileDialog.getExistingDirectory(self, tr("Куда класть скачанное"), start)
        if d:
            self.folder.setText(os.path.normpath(d))
            self._folder_edited()

    def open_folder(self):
        folder = self.folder_path()
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError:
            pass
        U.open_file(folder)

    def paste(self):
        text = QGuiApplication.clipboard().text().strip()
        if not dlcore.links(text):
            U.warn(self, tr("В буфере обмена нет ссылки. Скопируй её в браузере и нажми «Вставить» ещё раз."))
            return
        old = self.links.toPlainText().strip()
        self.links.setPlainText((old + "\n" if old else "") + "\n".join(dlcore.links(text)))

    # ---------- очередь

    def start(self):
        urls = dlcore.links(self.links.toPlainText())
        if not urls:
            U.warn(self, tr("Вставь ссылку на видео — она начинается с https://"))
            return
        folder = self.folder_path()
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            U.warn(self, tr("Не получается создать папку {folder}: {err}", folder=folder, err=e.strerror or e))
            return
        if dlcore.command() is None and not self._allow_tool():
            return
        if self.cfg.get("dl_folder") != folder:
            self._save("dl_folder", folder)          # вписали руками и сразу «Скачать» — тоже запомнить
        kind = self.kind()
        items = [dlcore.Item(u, kind=kind, quality=self.quality.currentData(), audio=self.audio.currentData())
                 for u in urls]
        self.links.clear()
        self._add(items)
        log.info("Скачать: %d %s · %s · %s", len(items), "ссылок", kind, folder)
        if not self.busy:
            self._run(folder)

    def _allow_tool(self):
        """yt-dlp ещё нет — спросить разрешения скачать его (один раз)."""
        if self.cfg.get("dl_allowed"):
            return True
        ok = U.ask_yes_no(self, tr("Чтобы скачивать по ссылке, нужна программа yt-dlp. Она бесплатная, её делают "
                                   "отдельно от Duplio.\n\nСкачать её с github.com/yt-dlp/yt-dlp (около 25 МБ)? "
                                   "Duplio проверит файл и дальше будет обновлять его сам."),
                          yes=tr("Скачать yt-dlp"), no=tr("Отмена"))
        if ok:
            self._save("dl_allowed", True)
        return ok

    def _add(self, items, at=None):
        rows = [self._make_row(i) for i in items]
        with self.lock:
            pos = len(self.queue) if at is None else at
            self.queue[pos:pos] = items
        if at is None:
            self.tree.addTopLevelItems(rows)
        else:
            self.tree.insertTopLevelItems(at, rows)
        self.stack.setCurrentIndex(1)
        self._update_buttons()

    def _make_row(self, item):
        row = QTreeWidgetItem()
        row.setData(0, ITEM_ROLE, item)
        self.rows[id(item)] = row
        self._fill(row, item)
        return row

    def _run(self, folder):
        self.cancel = threading.Event()
        self._set_busy(True)
        threading.Thread(target=self._worker, args=(folder, self.cancel), daemon=True).start()

    def _worker(self, folder, cancel):
        try:
            self._ensure_tool(cancel)
            while not cancel.is_set():
                with self.lock:
                    item = next((i for i in self.queue if i.state == "wait"), None)
                if item is None:
                    break
                if not item.looked:
                    self._look(item, cancel)
                    continue
                dlcore.download(item, folder, self._emit, cancel)
                if item.state == "failed":
                    log.info("Скачать: не вышло %s — %s", item.url, item.tech)
                else:
                    log.info("Скачать: %s %s", "уже было" if item.state == "had" else "скачано", item.path)
        except dlcore.Cancelled:
            pass
        except dlcore.Failed as e:
            self._fail_waiting(str(e))
        except Exception as e:                       # окно не должно зависнуть в «скачиваю» навсегда
            log.exception("Скачать упало")
            self._fail_waiting(tr("Не получилось: {err}", err=e))
        finally:
            if cancel.is_set():
                with self.lock:
                    waiting = [i for i in self.queue if i.state in ("wait", "look")]
                for i in waiting:
                    i.state = "stopped"
                    self.bridge.changed.emit(i)
            self.bridge.done.emit()

    def _fail_waiting(self, why):
        with self.lock:
            waiting = [i for i in self.queue if i.state in ("wait", "look")]
        for i in waiting:
            i.state, i.error = "failed", why
            self.bridge.changed.emit(i)

    def _ensure_tool(self, cancel):
        """yt-dlp: нет — скачать; давно не проверяли — обновить. Без сети старый остаётся рабочим."""
        have = dlcore.command() is not None
        if have and not dlcore.update_due(self.cfg.get("dl_checked", 0)):
            return
        self.bridge.step.emit(tr("Проверяю, свежий ли yt-dlp…") if have else tr("Скачиваю yt-dlp…"))
        try:
            v = dlcore.refresh(lambda d, t: self.bridge.step.emit(
                tr("Скачиваю yt-dlp: {done} из {total}", done=dupcore.human_size(d),
                   total=dupcore.human_size(t or d))), cancel)
            self.cfg["dl_checked"] = time.time()
            self.settings_changed.emit()
            log.info("yt-dlp %s", v)
        except dlcore.Cancelled:
            raise
        except Exception as e:
            log.warning("yt-dlp: обновить не вышло: %s", e)
            if not have:
                raise dlcore.Failed(tr("Не удалось скачать yt-dlp. Проверь интернет и попробуй ещё раз."))

    def _look(self, item, cancel):
        item.state = "look"
        self.bridge.changed.emit(item)
        try:
            found = dlcore.probe(item.url, cancel)
        except dlcore.Failed as e:
            item.state, item.error = "failed", str(e)
            log.info("Скачать: ссылка %s — %s", item.url, e)
            self.bridge.changed.emit(item)
            return
        entries = [dlcore.Item(url, kind=item.kind, quality=item.quality, audio=item.audio, title=title,
                               index=index, looked=True) for url, title, index in found]
        if len(entries) == 1:
            item.url, item.title, item.index = entries[0].url, entries[0].title, entries[0].index
            item.looked, item.state = True, "wait"
            self.bridge.changed.emit(item)
            return
        with self.lock:
            at = self.queue.index(item)
            self.queue[at:at + 1] = entries
        log.info("Скачать: плейлист %s — %d видео", item.url, len(entries))
        self.bridge.expanded.emit(item, entries)

    def _emit(self, item):
        """Из потока в окно — только смена состояния; проценты и скорость окно перечитывает само (_tick).

        Раньше ход шёл сигналом не чаще раза в 0,25 с — и последнее число перед паузой терялось: строка
        стояла на 0 %, пока видео качалось.
        """
        key = (item.state, item.stage)
        if self._last_emit.get(id(item)) != key:
            self._last_emit[id(item)] = key
            self.bridge.changed.emit(item)

    def _tick(self):
        with self.lock:
            moving = [i for i in self.queue if i.state in ("work", "look")]
        for item in moving:
            row = self.rows.get(id(item))
            if row is not None:
                self._fill(row, item)
        self._update_progress()

    def stop(self):
        if self.cancel:
            self.cancel.set()
            self.step_text.setText(tr("Останавливаю…"))

    # ---------- окно

    def _step(self, text):
        self.step_text.setText(text)

    def _changed(self, item):
        row = self.rows.get(id(item))
        if row is not None:
            self._fill(row, item)
        self._update_progress()
        self._update_buttons()

    def _expanded(self, link, entries):
        row = self.rows.pop(id(link), None)
        at = self.tree.indexOfTopLevelItem(row) if row is not None else self.tree.topLevelItemCount()
        if row is not None:
            self.tree.takeTopLevelItem(at)
        self.tree.insertTopLevelItems(at, [self._make_row(i) for i in entries])
        self._update_progress()

    def _fill(self, row, item):
        what = tr(dlcore.KINDS["video"]) if item.kind == "video" else dlcore.AUDIO_FORMATS[item.audio]
        if item.kind == "video" and item.quality != "best":
            what += " · " + tr("до {h}p", h=item.quality)
        row.setText(0, item.title or item.url)
        row.setToolTip(0, item.url)
        row.setText(1, what)
        row.setText(2, dupcore.human_size(item.total) if item.total else "")
        row.setText(3, self.state_text(item))
        row.setToolTip(3, tr(item.error or "Не получилось скачать.") + ("\n" + item.tech if item.tech else "")
                       if item.state == "failed" else "")
        color = {"failed": "danger", "done": "keep", "had": "muted", "stopped": "muted"}.get(item.state)
        row.setForeground(3, QColor(self.colors[color]) if color else QColor(self.colors["text"]))

    @staticmethod
    def state_text(item):
        if item.state == "wait":
            return tr("В очереди")
        if item.state == "look":
            return tr("Смотрю, что по ссылке…")
        if item.state == "work":
            if item.stage == "process":
                return tr("Собираю файл…")
            parts = [tr("{pct} %", pct=int(item.percent))]
            if item.speed:
                parts.append(tr("{speed}/с", speed=dupcore.human_size(item.speed)))
            if item.eta >= 0:
                parts.append(tr("осталось {t}", t=dupcore.human_time(item.eta)))
            return " · ".join(parts)
        if item.state == "done":
            return tr("Готово")
        if item.state == "had":
            return tr("Уже есть в папке")
        if item.state == "stopped":
            return tr("Остановлено")
        return tr(item.error or "Не получилось скачать.")

    def _update_progress(self):
        with self.lock:
            items = list(self.queue)
        total = len(items)
        finished = [i for i in items if i.state in ("done", "had", "failed", "stopped")]
        current = next((i for i in items if i.state in ("work", "look")), None)
        if not total:
            self.bar.setValue(0)
            return
        part = current.percent / 100 if current and current.state == "work" else 0
        self.bar.setValue(int(1000 * (len(finished) + part) / total))
        if self.busy and current is not None:
            self.step_text.setText(tr("Скачиваю {n} из {total}", n=num(len(finished) + 1), total=num(total)))
            self.status.setText(current.title or current.url)
            self.title_changed.emit(tr("{app} — скачиваю, {pct}%", app=U.APP_TITLE,
                                       pct=int(100 * (len(finished) + part) / total)))

    def _finished(self):
        self._set_busy(False)
        self.title_changed.emit(U.APP_TITLE)
        with self.lock:
            items = list(self.queue)
        got = sum(i.state == "done" for i in items)
        had = sum(i.state == "had" for i in items)
        bad = sum(i.state == "failed" for i in items)
        stopped = any(i.state == "stopped" for i in items)
        parts = [tr("Скачано: {n}", n=num(got))]
        if had:
            parts.append(tr("уже было: {n}", n=num(had)))
        if bad:
            parts.append(tr("не получилось: {n} — причина в строке", n=num(bad)))
        self.step_text.setText((tr("Остановлено.") + " " if stopped else "") + " · ".join(parts))
        self.status.setText(tr("Файлы лежат в папке {folder}", folder=self.folder_path()) if got or had else "")
        self.bar.setValue(1000 if not stopped else self.bar.value())
        self._update_buttons()

    def _set_busy(self, busy):
        self.busy = busy
        if busy:
            self.ticker.start()
        else:
            self.ticker.stop()
        self.btn_stop.setEnabled(busy)
        U.why(self.btn_stop, "" if busy else tr("Сейчас ничего не скачивается — останавливать нечего."))
        self._update_buttons()

    def _done_selected(self):
        """Выбранные строки, у которых файл на месте (скачан или уже был)."""
        out = []
        for row in self.tree.selectedItems():
            item = row.data(0, ITEM_ROLE)
            if item.state in ("done", "had") and item.path and os.path.exists(item.path):
                out.append(item)
        return out

    def _update_buttons(self):
        ready = self._done_selected()
        why = "" if ready else tr("Выбери в списке скачанные файлы.")
        for b in [self.btn_show, *self.btn_to.values()]:
            b.setEnabled(bool(ready))
            U.why(b, why)
        has_links = bool(self.links.toPlainText().strip())
        self.btn_start.setEnabled(has_links)
        U.why(self.btn_start, "" if has_links else tr("Сначала вставь ссылку."))
        self.btn_start.setText(tr("Добавить в очередь") if self.busy else tr("Скачать"))
        with self.lock:
            idle = [i for i in self.queue if i.state not in ("wait", "look", "work")]
        self.btn_clear.setEnabled(bool(idle))
        U.why(self.btn_clear, "" if idle else tr("Убирать нечего — список пуст или всё ещё скачивается."))

    def clear_list(self):
        with self.lock:
            keep = [i for i in self.queue if i.state in ("wait", "look", "work")]
            gone = [i for i in self.queue if i not in keep]
            self.queue[:] = keep
        for i in gone:
            row = self.rows.pop(id(i), None)
            if row is not None:
                self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(row))
        if not keep:
            self.stack.setCurrentIndex(0)
            self.bar.setValue(0)
            self.step_text.setText(tr("Вставь ссылку и нажми «Скачать»."))
            self.status.setText("")
        self._update_buttons()

    def refresh(self):
        """Тема сменилась — перекрасить строки."""
        for row in self.rows.values():
            self._fill(row, row.data(0, ITEM_ROLE))

    def _open(self, item):
        if item and item.state in ("done", "had") and os.path.exists(item.path):
            U.open_file(item.path)

    def _menu(self, pos):
        row = self.tree.itemAt(pos)
        if row is None:
            return
        item = row.data(0, ITEM_ROLE)
        menu = QMenu(self)
        if item.state in ("done", "had") and os.path.exists(item.path):
            menu.addAction(tr("Открыть"), lambda: self._open(item))
            menu.addAction(tr("Показать в папке"), lambda: U.reveal(item.path))
        if item.state in ("failed", "stopped"):
            menu.addAction(tr("Скачать ещё раз"), lambda: self.retry([r.data(0, ITEM_ROLE)
                                                                       for r in self.tree.selectedItems()]))
        menu.addAction(tr("Скопировать ссылку"), lambda: QGuiApplication.clipboard().setText(item.url))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def retry(self, items):
        again = [i for i in items if i.state in ("failed", "stopped")]
        for i in again:
            i.state, i.error, i.tech, i.percent, i.speed, i.eta = "wait", "", "", 0.0, 0.0, -1
            self._changed(i)
        if again and not self.busy:
            self._run(self.folder_path())
