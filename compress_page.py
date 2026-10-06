"""Вкладка «Сжатие»: подготовка сжатых копий, список «было → стало», сравнение рядом, замена оригиналов."""

import os
import subprocess
import threading
import time

from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QImageReader, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QDialog, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QProgressBar, QPushButton,
                               QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

import compcore
import dupcore
import i18n
import ui_util as U
from dups_page import LOAD_NAMES, RowTint, StepClock, _problems_text
from i18n import num, plural, tr
from logs import log

MODE_TEXT = {
    "lossless": ("Строго без потерь",
                 "Фото JPEG и PNG пересобираются без изменения пикселей — каждый файл сверяется байт в байт. "
                 "Экономия: обычно 5–20 %."),
    "visual": ("Без видимых потерь",
               "Фото JPEG — качество 85–90, видео — AV1, PNG — без потерь. На глаз разницы нет, и это "
               "проверяется числом. Экономия: обычно 30–70 %."),
}
FILE_ROLE = Qt.UserRole
COLS = 7


def EMPTY_TEXT():
    return tr("Здесь появятся сжатые копии: было → стало.\n\nПрограмма уменьшает файлы, не меняя их тип. "
              "Сначала готовит и проверяет сжатые копии — оригиналы не трогает, пока ты не нажмёшь «Заменить».")


def pct(part, whole):
    if not whole:
        return "—"
    v = round(100 * part / whole)
    return f"{v}\u00a0%" if i18n.LANG == "ru" else f"{v}%"      # по-русски — через неразрывный пробел


def score_text(v):
    s = f"{v:.3f}"
    return s.replace(".", ",") if i18n.LANG == "ru" else s


class WrapLabel(QLabel):
    """Надпись с переносом, которая просит себе столько высоты, сколько нужно при её ширине.

    Обычная QLabel с переносом в окне без прокрутки получает высоту «на глаз» и обрезает последние строки.
    """

    def __init__(self, text="", name=None):
        super().__init__(text)
        if name:
            self.setObjectName(name)
        self.setWordWrap(True)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        need = self.heightForWidth(self.width())
        if need > 0 and need != self.minimumHeight():
            self.setMinimumHeight(need)

    def setText(self, text):
        super().setText(text)
        self.setMinimumHeight(max(0, self.heightForWidth(self.width())) if self.width() > 0 else 0)


def check_text(job):
    if job.check == "pixels":
        return tr("байт в байт")
    if job.check == "ssim":
        return tr("SSIM {v}", v=score_text(job.score))
    return ""


# ---------------------------------------------------------------- превью: фото и кадр видео

def video_frame(path, at, box=None):
    """Кадр видео в момент at (секунды) через ffmpeg — один и тот же кадр у оригинала и сжатого."""
    ff = compcore.tool("ffmpeg")
    if not ff:
        return QImage()
    args = [ff, "-v", "error", "-nostdin", "-ss", f"{at:.3f}", "-i", path, "-frames:v", "1"]
    if box:
        args += ["-vf", f"scale={box}:{box}:force_original_aspect_ratio=decrease"]
    args += ["-f", "image2pipe", "-c:v", "png", "-"]
    try:
        out = subprocess.run(args, capture_output=True, timeout=60, creationflags=compcore.CREATE_NO_WINDOW,
                             env=compcore._env())
    except (OSError, subprocess.TimeoutExpired):
        return QImage()
    img = QImage()
    img.loadFromData(out.stdout)
    return img


def image(path, box=None):
    reader = QImageReader(path)
    reader.setAutoTransform(True)              # поворот по EXIF, как снимал телефон
    size = reader.size()
    if box and size.isValid():
        reader.setScaledSize(size.scaled(box, box, Qt.KeepAspectRatio))
    return reader.read()


class _Relay(QObject):
    ready = Signal(str, QImage)


class _Load(QRunnable):
    def __init__(self, key, path, at, box, done):
        super().__init__()
        self.key, self.path, self.at, self.box, self.done = key, path, at, box, done

    def run(self):
        img = video_frame(self.path, self.at, self.box) if self.at is not None else image(self.path, self.box)
        self.done(self.key, img)


class Previews(QObject):
    """Маленькие превью «было» и «стало» в фоне. Готовое приходит сигналом ready(ключ, QImage)."""

    ready = Signal(str, QImage)

    def __init__(self, box=420):
        super().__init__()
        self.box = box
        self.cache = {}
        self.waiting = set()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.relay = _Relay()
        self.relay.ready.connect(self._got)

    def get(self, path, at=None):
        key = f"{path}|{at}"
        if key in self.cache:
            return self.cache[key]
        if key not in self.waiting:
            self.waiting.add(key)
            self.pool.start(_Load(key, path, at, self.box, self.relay.ready.emit))
        return None

    def _got(self, key, img):
        self.waiting.discard(key)
        self.cache[key] = img
        if len(self.cache) > 200:
            self.cache.pop(next(iter(self.cache)))
        self.ready.emit(key, img)

    def clear(self):
        self.cache.clear()


def _badge(p, text, colors, x=8, y=8):
    f = QFont(p.font())
    f.setBold(True)
    p.setFont(f)
    fm = p.fontMetrics()
    w, h = fm.horizontalAdvance(text) + 14, fm.height() + 6
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(colors["surface"]))
    p.drawRoundedRect(QRectF(x, y, w, h), 6, 6)
    p.setPen(QColor(colors["text"]))
    p.drawText(QRectF(x, y, w, h), Qt.AlignCenter, text)


class Picture(QWidget):
    """Картинка, вписанная в свой прямоугольник целиком; подпись «Было»/«Стало» сверху слева."""

    def __init__(self, caption, colors):
        super().__init__()
        self.caption, self.colors = caption, colors
        self.img = None
        self.text = ""
        self.setMinimumSize(140, 110)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_image(self, img, text=""):
        self.img = img if img is not None and not img.isNull() else None
        self.text = text
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self.colors["surface2"]))
        p.drawRoundedRect(r, 6, 6)
        if self.img is not None:
            s = self.img.size().scaled(self.size() - QSize(8, 8), Qt.KeepAspectRatio)
            target = QRectF((self.width() - s.width()) / 2, (self.height() - s.height()) / 2, s.width(), s.height())
            p.drawImage(target, self.img)
        else:
            p.setPen(QColor(self.colors["muted"]))
            p.drawText(r, Qt.AlignCenter, self.text)
        _badge(p, self.caption, self.colors)


# ---------------------------------------------------------------- сравнение крупно

ZOOMS = [0, 1.0, 2.0, 4.0]         # 0 — вписать целиком


class PairView(QWidget):
    """«Было» и «стало» рядом с одинаковым увеличением: тянешь одну половину — двигаются обе."""

    zoom_changed = Signal()

    def __init__(self, colors):
        super().__init__()
        self.colors = colors
        self.a = self.b = None
        self.zoom = 0
        self.center = QPointF()
        self.drag = None
        self.setMinimumSize(600, 360)
        self.setCursor(Qt.OpenHandCursor)

    def set_images(self, a, b):
        self.a, self.b = a, b
        if a is not None and not a.isNull():
            self.center = QPointF(a.width() / 2, a.height() / 2)
        self.update()

    def set_zoom(self, z):
        self.zoom = z
        self._clamp()
        self.zoom_changed.emit()
        self.update()

    def _clamp(self):
        """Видимое окно — внутри картинки; если картинка меньше окна — она посередине."""
        if self.a is None or self.a.isNull() or self.zoom == 0:
            return
        s = self.scale()
        r = self.halves()[0]
        w, h = r.width() / s, r.height() / s
        iw, ih = self.a.width(), self.a.height()
        x = iw / 2 if w >= iw else min(max(self.center.x(), w / 2), iw - w / 2)
        y = ih / 2 if h >= ih else min(max(self.center.y(), h / 2), ih - h / 2)
        self.center = QPointF(x, y)

    def halves(self):
        gap = 10
        half = (self.width() - gap) / 2
        return QRectF(0, 0, half, self.height()), QRectF(half + gap, 0, half, self.height())

    def scale(self):
        if self.a is None or self.a.isNull():
            return 1.0
        if self.zoom == 0:
            r = self.halves()[0]
            return min(r.width() / self.a.width(), r.height() / self.a.height())
        return self.zoom / self.devicePixelRatioF()         # 100 % — пиксель картинки на пиксель экрана

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, self.zoom == 0)
        s = self.scale()
        for rect, img, caption in zip(self.halves(), (self.a, self.b), (tr("Было"), tr("Стало"))):
            p.save()
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(self.colors["surface2"]))
            p.drawRoundedRect(rect, 6, 6)
            p.setClipRect(rect)
            if img is not None and not img.isNull() and self.a is not None and not self.a.isNull():
                k = img.width() / self.a.width()          # если размеры вдруг разные — по долям кадра
                if self.zoom == 0:
                    tw, th = self.a.width() * s, self.a.height() * s
                    target = QRectF(rect.center().x() - tw / 2, rect.center().y() - th / 2, tw, th)
                    src = QRectF(0, 0, img.width(), img.height())
                else:
                    w, h = rect.width() / s, rect.height() / s
                    src = QRectF((self.center.x() - w / 2) * k, (self.center.y() - h / 2) * k, w * k, h * k)
                    target = rect
                p.drawImage(target, img, src)
            p.restore()
            _badge(p, caption, self.colors, rect.x() + 8, 8)

    def mousePressEvent(self, e):
        self.drag = e.position()
        self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self.drag is None or self.zoom == 0:
            return
        d = e.position() - self.drag
        self.drag = e.position()
        s = self.scale()
        self.center -= QPointF(d.x() / s, d.y() / s)
        self._clamp()
        self.update()

    def mouseReleaseEvent(self, e):
        self.drag = None
        self.setCursor(Qt.OpenHandCursor)

    def wheelEvent(self, e):
        i = ZOOMS.index(self.zoom) + (1 if e.angleDelta().y() > 0 else -1)
        if not 0 <= i < len(ZOOMS):
            return
        if self.zoom == 0 and self.a is not None and not self.a.isNull():   # приблизить туда, где курсор
            pos = e.position()
            rect = next((r for r in self.halves() if r.contains(pos)), self.halves()[0])
            s = self.scale()
            x0 = rect.center().x() - self.a.width() * s / 2
            y0 = rect.center().y() - self.a.height() * s / 2
            self.center = QPointF((pos.x() - x0) / s, (pos.y() - y0) / s)
        self.set_zoom(ZOOMS[i])


class CompareDialog(QDialog):
    """Крупное сравнение «было / стало»; стрелки — соседние файлы списка, пробел или Esc — закрыть."""

    def __init__(self, page, jobs, index):
        super().__init__(page)
        self.page, self.jobs, self.i = page, jobs, index
        self.setWindowTitle(tr("Сравнение «было / стало»"))
        self.resize(1200, 820)
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
        self.info = U.label("", "muted", wrap=True)
        lay.addWidget(self.info)
        zoom_row = QHBoxLayout()
        zoom_row.setSpacing(8)
        self.zoom_btns = []
        group = QButtonGroup(self)
        for z in ZOOMS:
            b = QPushButton(tr("Вписать") if z == 0 else f"{int(z * 100)} %", objectName="chip", checkable=True)
            group.addButton(b)
            b.clicked.connect(lambda _=False, z=z: self.view.set_zoom(z))
            zoom_row.addWidget(b)
            self.zoom_btns.append(b)
        zoom_row.addSpacing(12)
        zoom_row.addWidget(U.label(tr("Колёсико — масштаб, мышью — двигать: обе половины двигаются вместе."),
                                   "muted"))
        zoom_row.addStretch()
        lay.addLayout(zoom_row)
        self.view = PairView(page.colors)
        self.view.zoom_changed.connect(self._sync_zoom)
        lay.addWidget(self.view, 1)
        bottom = QHBoxLayout()
        self.prev = QPushButton(tr("← Предыдущий"))
        self.prev.clicked.connect(lambda: self.go(-1))
        self.next = QPushButton(tr("Следующий →"))
        self.next.clicked.connect(lambda: self.go(1))
        bottom.addWidget(self.prev)
        bottom.addWidget(self.next)
        bottom.addStretch()
        open_old = QPushButton(tr("Открыть оригинал"))
        open_old.clicked.connect(lambda: U.open_file(self.jobs[self.i].path))
        open_new = QPushButton(tr("Открыть сжатый"))
        open_new.clicked.connect(lambda: U.open_file(self.jobs[self.i].out))
        bottom.addWidget(open_old)
        bottom.addWidget(open_new)
        lay.addLayout(bottom)
        for key, fn in ((Qt.Key_Left, lambda: self.go(-1)), (Qt.Key_Right, lambda: self.go(1)),
                        (Qt.Key_Space, self.close)):
            QShortcut(QKeySequence(key), self, activated=fn)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.show_current()

    def _sync_zoom(self):
        for b, z in zip(self.zoom_btns, ZOOMS):
            b.setChecked(z == self.view.zoom)

    def go(self, d):
        self.i = (self.i + d) % len(self.jobs)
        self.show_current()

    def show_current(self):
        j = self.jobs[self.i]
        self.title.setText(os.path.basename(j.path))
        self.counter.setText(tr("{i} из {n}", i=self.i + 1, n=len(self.jobs)))
        line = tr("Было {old} → стало {new}, меньше на {pct}", old=dupcore.human_size(j.size),
                  new=dupcore.human_size(j.new_size), pct=pct(j.saved, j.size))
        line += "  ·  " + j.how + ("  ·  " + check_text(j) if j.check else "")
        if j.is_video:
            line += "\n" + tr("Показан один кадр из видео. Посмотреть целиком — «Открыть сжатый».")
        self.info.setText(line)
        if j.is_video:
            at = self.page.frame_time(j)
            a, b = video_frame(j.path, at), video_frame(j.out, at)
        else:
            a, b = image(j.path), image(j.out)
        self.view.set_images(a, b)
        self.view.set_zoom(0)


# ---------------------------------------------------------------- вкладка

class Bridge(QObject):
    """Сигналы из потока подготовки в окно. object — чтобы байты больше 2 ГБ не обрезались."""
    progress = Signal(object, object, int, int, str)
    job = Signal(object)
    done = Signal(object)
    failed = Signal(str)


class CompressPage(QWidget):
    title_changed = Signal(str)
    finished = Signal(int, object)            # готово к замене файлов, освободится байт — для уведомления из трея
    go_settings = Signal()
    settings_changed = Signal()

    def __init__(self, cfg, colors):
        super().__init__(objectName="page")
        self.cfg, self.colors = cfg, colors
        self.busy = False
        self.cancel = None
        self.result = None
        self.ready = []            # сжатые и проверенные — строки списка
        self.skipped = []
        self.marked = set()        # пути, которые заменить
        self.items = {}
        self.current = None
        self.scan_root = ""
        self._updating = False
        self._times = {}
        self.previews = Previews()
        self.previews.ready.connect(self._preview_ready)
        self.bridge = Bridge()
        self.bridge.progress.connect(self._show_progress)
        self.bridge.job.connect(self._job_done)
        self.bridge.done.connect(self._finish)
        self.bridge.failed.connect(self._failed)
        self.pending = []
        self.flusher = QTimer(self, interval=400)       # готовые файлы — в список пачками, не по одному
        self.flusher.timeout.connect(self._flush)
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
        root.addWidget(U.label(tr("Сжатие фото и видео"), "title"))

        card, cl = U.card()
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnMinimumWidth(0, 96)
        grid.addWidget(U.label(tr("Папка"), "strong"), 0, 0)
        self.folder = QLineEdit(self.cfg.get("compress_folder") or self.cfg.get("last_folder", ""))
        self.folder.setPlaceholderText(tr("Например, E:\\ или C:\\Users\\Имя\\Pictures"))
        self.folder.returnPressed.connect(self.start)
        frow = QHBoxLayout()
        frow.setSpacing(8)
        frow.addWidget(self.folder, 1)
        choose = QPushButton(tr("Выбрать…"))
        choose.clicked.connect(self.choose)
        frow.addWidget(choose)
        grid.addLayout(frow, 0, 1)

        grid.addWidget(U.label(tr("Режим"), "strong"), 1, 0)
        modes = QHBoxLayout()
        modes.setSpacing(8)
        self.mode_group = QButtonGroup(self)
        self.mode_btns = {}
        for key, (title, _text) in MODE_TEXT.items():
            b = QPushButton(tr(title), objectName="chip", checkable=True)
            self.mode_group.addButton(b)
            b.toggled.connect(lambda on, k=key: on and self._mode_picked(k))
            modes.addWidget(b)
            self.mode_btns[key] = b
        modes.addStretch()
        grid.addLayout(modes, 1, 1)
        self.mode_text = WrapLabel("", "muted")
        grid.addWidget(self.mode_text, 2, 1)

        grid.addWidget(U.label(tr("Что сжимать"), "strong"), 3, 0)
        chips = QHBoxLayout()
        chips.setSpacing(8)
        self.chips = {}
        for key, name in compcore.KINDS.items():
            b = QPushButton(tr(name), objectName="chip", checkable=True)
            b.setChecked(key in self.cfg.get("compress_kinds", ["photo", "video"]))
            b.toggled.connect(self._kinds_changed)
            chips.addWidget(b)
            self.chips[key] = b
        chips.addSpacing(8)
        self.kinds_note = U.label("", "muted")
        chips.addWidget(self.kinds_note, 1)
        grid.addLayout(chips, 3, 1)
        self.hint = WrapLabel("", "warn")
        grid.addWidget(self.hint, 4, 1)
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
        self.btn_start = QPushButton(tr("Подготовить сжатые копии"), objectName="accent")
        self.btn_start.clicked.connect(self.start)
        act.addWidget(self.btn_start)
        cl.addLayout(act)
        root.addWidget(card)

        prog = QVBoxLayout()
        prog.setSpacing(6)
        top = QHBoxLayout()
        self.step_text = U.label(tr("Выбери папку и режим и нажми «Подготовить сжатые копии»."), "strong")
        top.addWidget(self.step_text)
        top.addStretch()
        self.elapsed = U.label("", "muted")
        top.addWidget(self.elapsed)
        prog.addLayout(top)
        self.bar = QProgressBar(textVisible=False, maximum=1000)
        prog.addWidget(self.bar)
        self.status = WrapLabel("", "muted")
        prog.addWidget(self.status)
        self.summary = U.label("", "strong")
        prog.addWidget(self.summary)
        root.addLayout(prog)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(16)          # зазор между списком и сравнением (ширину ручки стиль не задаёт)
        self.stack = QStackedWidget()
        self.empty = U.label(EMPTY_TEXT(), "empty")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        empty_box, eb = U.card()
        eb.addWidget(self.empty)
        self.stack.addWidget(empty_box)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(COLS)
        self.tree.setHeaderLabels([tr("Заменить"), tr("Файл"), tr("Было"), tr("Стало"), tr("Меньше на"),
                                   tr("Проверка"), tr("Где лежит")])
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
        for col, w in enumerate((84, 180, 80, 80, 86, 104)):
            self.tree.setColumnWidth(col, w)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.currentItemChanged.connect(self._current_changed)
        self.tree.itemDoubleClicked.connect(lambda it, col: col and self.compare_big())
        QShortcut(QKeySequence(Qt.Key_Space), self.tree, activated=self.compare_big)
        self.stack.addWidget(self.tree)
        split.addWidget(self.stack)

        cmp_card, cmp = U.card(margins=(16, 14, 16, 14), spacing=10)
        ctop = QHBoxLayout()
        ctop.addWidget(U.label(tr("Было → стало"), "h2"))
        ctop.addStretch()
        self.cmp_name = U.label("", "muted")
        ctop.addWidget(self.cmp_name)
        cmp.addLayout(ctop)
        self.cmp_hint = WrapLabel(tr("Выбери файл в списке — здесь будут оригинал и сжатая копия рядом. "
                                     "Двойной щелчок или пробел — сравнить крупно, с увеличением."), "muted")
        cmp.addWidget(self.cmp_hint)
        # Содержимое — в прокрутке: в низком окне карточка ужимается сама, а не сминает соседей.
        self.cmp_scroll = QScrollArea(widgetResizable=True)
        self.cmp_scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        inner = QVBoxLayout(body)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(10)
        self.cmp_scroll.setWidget(body)
        cmp.addWidget(self.cmp_scroll, 1)
        self.pics = QWidget()
        pics = QHBoxLayout(self.pics)
        pics.setContentsMargins(0, 0, 0, 0)
        pics.setSpacing(10)
        self.pic_old = Picture(tr("Было"), self.colors)
        self.pic_new = Picture(tr("Стало"), self.colors)
        pics.addWidget(self.pic_old)
        pics.addWidget(self.pic_new)
        inner.addWidget(self.pics, 1)
        self.cmp_sizes = WrapLabel("", "strong")
        inner.addWidget(self.cmp_sizes)
        self.cmp_how = WrapLabel("", "muted")
        inner.addWidget(self.cmp_how)
        self.cmp_buttons = QWidget()
        crow = QHBoxLayout(self.cmp_buttons)
        crow.setContentsMargins(0, 0, 0, 0)
        crow.setSpacing(8)
        self.btn_big = QPushButton(tr("Сравнить крупно"))
        self.btn_big.clicked.connect(self.compare_big)
        crow.addWidget(self.btn_big)
        self.btn_open = QPushButton(tr("Открыть"))
        open_menu = QMenu(self.btn_open)
        open_menu.addAction(tr("Открыть оригинал"), lambda: self.current and U.open_file(self.current.path))
        open_menu.addAction(tr("Открыть сжатый"), lambda: self.current and U.open_file(self.current.out))
        open_menu.addAction(tr("Показать в папке"), lambda: self.current and U.reveal(self.current.path))
        self.btn_open.setMenu(open_menu)
        crow.addWidget(self.btn_open)
        crow.addStretch()
        inner.addWidget(self.cmp_buttons)
        cmp_card.setMinimumWidth(330)
        split.addWidget(cmp_card)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([700, 520])
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
        # Главная кнопка — справа внизу, как у «Дубликатов»; итог отметок — над списком, под полосой хода.
        self.btn_replace = QPushButton(tr("Заменить оригиналы"), objectName="danger")
        self.btn_replace.clicked.connect(self.replace_marked)
        bottom.addWidget(self.btn_replace)
        root.addLayout(bottom)

        mode = self.cfg.get("compress_mode", "lossless")
        self.mode_btns[mode if mode in MODE_TEXT else "lossless"].setChecked(True)
        self._mode_picked(self.mode())
        self.show_job(None)

    def set_load_text(self):
        self.load_text.setText(tr("Нагрузка на компьютер: {name}",
                                  name=tr(LOAD_NAMES[self.cfg.get("load", "gentle")])))

    # ---------- режим и типы

    def mode(self):
        return next((k for k, b in self.mode_btns.items() if b.isChecked()), "lossless")

    def kinds(self):
        return {k for k, b in self.chips.items() if b.isChecked() and b.isEnabled()}

    def _mode_picked(self, key):
        lossless = key == "lossless"
        self.chips["video"].setEnabled(not lossless)
        self.chips["video"].setToolTip(tr("Видео строго без потерь не сжимается — только в режиме «Без видимых потерь»")
                                       if lossless else "")
        self.mode_text.setText(tr(MODE_TEXT[key][1]))
        self.cfg["compress_mode"] = key
        self.settings_changed.emit()
        self._kinds_changed()

    def _kinds_changed(self, *_):
        kinds = self.kinds()
        lossless = self.mode() == "lossless"
        if lossless:
            note = tr("Фото: JPEG и PNG. Видео — только «без видимых потерь».")
        elif "video" in kinds:
            note = tr("Фото: JPEG и PNG; видео — в формат AV1 (MP4, MOV, MKV, WebM).")
        else:
            note = tr("Фото: JPEG и PNG.")
        self.kinds_note.setText(note)
        self.kinds_note.setToolTip(tr("AV1 Windows 11 показывает сразу, Windows 10 — после бесплатного расширения "
                                      "«AV1 Video Extension» из Microsoft Store.") if "AV1" in note else "")
        hint = tr("Отметь, что сжимать.") if not kinds else ""
        missing = compcore.missing_tools(kinds, self.mode())
        if missing:
            hint = tr("Не хватает программ: {names}. Запусти tools/fetch_tools.py.", names=", ".join(missing))
        self.hint.setText(hint)
        self.hint.setVisible(bool(hint))
        self.cfg["compress_kinds"] = sorted(k for k, b in self.chips.items() if b.isChecked())
        self.settings_changed.emit()

    # ---------- подготовка

    def choose(self):
        d = QFileDialog.getExistingDirectory(self, tr("Что сжимать"), self.folder.text() or "")
        if d:
            self.folder.setText(os.path.normpath(d))
            self.btn_start.setFocus()

    def start(self):
        if self.busy:
            return
        root = self.folder.text().strip().strip('"')
        if not root or not os.path.isdir(root):
            U.warn(self, tr("Такой папки нет. Нажми «Выбрать…» и укажи папку."))
            return
        kinds, mode = self.kinds(), self.mode()
        if not kinds:
            U.warn(self, tr("Отметь, что сжимать: фото или видео."))
            return
        missing = compcore.missing_tools(kinds, mode)
        if missing:
            U.warn(self, tr("Не хватает программ: {names}. Запусти tools/fetch_tools.py.", names=", ".join(missing)))
            return
        if self.marked and not U.ask_yes_no(
                self, tr("Подготовленные копии ещё не заменили оригиналы. Начать заново? Они пропадут."),
                yes=tr("Начать заново")):
            return
        self.cfg["compress_folder"] = root
        self.settings_changed.emit()
        self.scan_root = os.path.abspath(root)
        self.ready, self.skipped, self.marked, self.pending = [], [], set(), []
        self.result = None
        self._times = {}
        self.previews.clear()
        self.refresh()
        self.empty.setText(tr("Готовлю… Сжатые копии появятся здесь сразу, по одной."))
        self.btn_skipped.hide()
        self.btn_errors.hide()
        self.cancel = threading.Event()
        self.clock = StepClock()
        self.started = time.monotonic()
        self._last_push = 0.0
        self._set_busy(True)
        self.step_text.setText(tr("Начинаю…"))
        self.status.setText("")
        self.ticker.start()
        self._tick()
        load = self.cfg.get("load", "gentle")
        log.info("Сжатие: %s · режим %s · типы %s · нагрузка %s", root, mode, ",".join(sorted(kinds)), load)
        threading.Thread(target=self._worker, args=(root, kinds, mode, self.cancel, load), daemon=True).start()

    def _worker(self, root, kinds, mode, cancel, load):
        def progress(done_b, total_b, done_f, total_f, name):
            now = time.monotonic()
            if now - self._last_push > 0.15 or (total_f and done_f >= total_f) or done_f == 0:
                self._last_push = now
                self.bridge.progress.emit(done_b, total_b, done_f, total_f, name)
        try:
            self.bridge.done.emit(compcore.prepare(root, kinds, mode, progress, cancel, load,
                                                   on_job=self.bridge.job.emit))
        except Exception as e:                     # окно не должно зависнуть в «готовлю» навсегда
            log.exception("Сжатие упало")
            self.bridge.failed.emit(str(e))

    def _tick(self):
        if self.busy:
            self.elapsed.setText(tr("прошло {t}", t=dupcore.human_time(time.monotonic() - self.started)))

    def _show_progress(self, done_b, total_b, done_f, total_f, name):
        if not self.busy:
            return
        if not total_b:                            # ещё обходим папки
            self.bar.setRange(0, 0)
            self.step_text.setText(tr("Ищу фото и видео…"))
            self.status.setText(tr("Найдено файлов: {n}.", n=num(total_f)))
            return
        self.bar.setRange(0, 1000)
        self.bar.setValue(int(1000 * done_b / total_b))
        self.step_text.setText(tr("Готовлю сжатые копии · {done} из {total}", done=num(done_f), total=num(total_f)))
        self.title_changed.emit(tr("{app} — сжатие, {pct}%", app=U.APP_TITLE, pct=done_b * 100 // total_b))
        _rate, left = self.clock.update(1, done_b, total_b)
        parts = [tr("{done} из {total}", done=dupcore.human_size(done_b), total=dupcore.human_size(total_b))]
        parts.append(tr("осталось ≈ {t}", t=dupcore.human_time(left)) if left is not None
                     else tr("считаю, сколько осталось…"))
        saved = sum(j.saved for j in self.ready)
        done_bytes = sum(j.size for j in self.ready) + sum(j.size for j in self.skipped)
        if saved and done_bytes:
            parts.append(tr("освободится уже {now}, по всей папке ≈ {all}", now=dupcore.human_size(saved),
                            all=dupcore.human_size(saved * total_b / done_bytes)))
        if name:
            parts.append(tr("сейчас: {name}", name=name))
        self.status.setText(" · ".join(parts))

    def stop(self):
        if self.cancel:
            self.cancel.set()
            self.step_text.setText(tr("Останавливаю…"))

    def _job_done(self, job):
        self.pending.append(job)

    def _flush(self):
        """Добавить готовые за последние доли секунды файлы в конец списка."""
        if not self.pending:
            return
        new, self.pending = self.pending, []
        rows = []
        for j in new:
            if j.out:
                self.ready.append(j)
                self.marked.add(j.path)
                rows.append(self._make_item(j))
            else:
                self.skipped.append(j)
        if rows:
            self._updating = True
            try:
                self.tree.addTopLevelItems(rows)
            finally:
                self._updating = False
            self.stack.setCurrentIndex(1)
            if self.tree.currentItem() is None:          # первая готовая копия — сразу в сравнение
                self.tree.setCurrentItem(rows[0])
        self._update_summary()

    def _failed(self, text):
        self._set_busy(False)
        self.title_changed.emit(U.APP_TITLE)
        U.warn(self, tr("Подготовка прервалась из-за ошибки:\n{text}", text=text))

    def _finish(self, res):
        took = dupcore.human_time(time.monotonic() - self.started)
        self.result = res
        self._set_busy(False)
        self.title_changed.emit(U.APP_TITLE)
        self.bar.setRange(0, 1000)
        self.bar.setValue(0 if res.cancelled else 1000)
        self.elapsed.setText("")
        saved = sum(j.saved for j in self.ready)
        log.info("Сжатие %s за %s: файлов %d (%s), готово %d, освободится %s, не сжато %d, не прочитано %d",
                 "остановлено" if res.cancelled else "подготовлено", took, res.files_seen,
                 dupcore.human_size(res.bytes_seen), len(self.ready), dupcore.human_size(saved), len(self.skipped),
                 len(res.errors))
        for j in self.skipped[:100]:
            log.info("   не сжат: %s — %s", j.path, j.skip)
        seen = tr("Проверено файлов: {n} ({size}).", n=num(res.files_seen), size=dupcore.human_size(res.bytes_seen))
        if res.cloud_skipped:
            seen += tr(" Пропущено файлов, которые лежат только в облаке или на телефоне: {n} — их пришлось "
                       "бы скачивать.", n=num(res.cloud_skipped))
        if res.no_space:
            self.step_text.setText(tr("Место на диске кончается — подготовку остановил."))
            self.status.setText(tr("Замени готовые файлы — место освободится, и можно продолжить."))
        elif res.cancelled:
            self.step_text.setText(tr("Подготовка остановлена.") + (tr(" Готовые копии — в списке.")
                                                                    if self.ready else ""))
            self.status.setText(tr("Прошло {t}.", t=took))
            self.empty.setText(EMPTY_TEXT())
        elif not self.ready:
            self.step_text.setText(tr("Готово за {t}. Сжимать нечего.", t=took))
            self.status.setText(seen)
            self.empty.setText(tr("Ни один файл не уменьшился заметно — они уже сжаты хорошо.")
                               if res.files_seen else tr("Подходящих фото и видео в папке нет."))
        else:
            self.step_text.setText(tr("Готово за {t}. Проверь «было → стало» и нажми «Заменить».", t=took))
            self.status.setText(seen)
        if self.skipped:
            self.btn_skipped.setText(tr("Не сжаты: {n}", n=num(len(self.skipped))))
            self.btn_skipped.show()
        if res.errors:
            self.btn_errors.setText(tr("Не прочитались: {n}", n=num(len(res.errors))))
            self.btn_errors.show()
        self.finished.emit(len(self.ready), saved)

    def _set_busy(self, busy):
        self.busy = busy
        self.btn_start.setEnabled(not busy)
        self.btn_stop.setEnabled(busy)
        for b in self.mode_btns.values():
            b.setEnabled(not busy)
        if busy:
            self.flusher.start()                 # готовые копии — в список, пока идёт подготовка
        else:
            self.ticker.stop()
            self.flusher.stop()
            self._flush()
        self._update_summary()

    def has_pending(self):
        """Подготовленные копии, которые ещё не заменили оригиналы (при выходе пропадут)."""
        return bool(self.marked)

    # ---------- список

    def short_dir(self, path):
        rel = os.path.relpath(os.path.dirname(path), self.scan_root) if self.scan_root else os.path.dirname(path)
        return tr("(в самой папке)") if rel == "." else rel

    def _make_item(self, j):
        it = QTreeWidgetItem(["", os.path.basename(j.path), dupcore.human_size(j.size), dupcore.human_size(j.new_size),
                              pct(j.saved, j.size), check_text(j), self.short_dir(j.path)])
        it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
        it.setData(1, FILE_ROLE, j)
        it.setToolTip(1, j.path)
        it.setToolTip(0, tr("Отметка — оригинал уйдёт в Корзину, на его место встанет сжатый файл"))
        for col in (2, 3, 4):
            it.setTextAlignment(col, Qt.AlignRight | Qt.AlignVCenter)
        it.setForeground(4, QColor(self.colors["keep"]))
        it.setCheckState(0, Qt.Checked if j.path in self.marked else Qt.Unchecked)
        self.items[j.path] = it
        return it

    def refresh(self):
        self._updating = True
        keep = self.current.path if self.current else None
        self.tree.setUpdatesEnabled(False)
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            self.items.clear()
            self.tree.addTopLevelItems([self._make_item(j) for j in self.ready])
        finally:
            self.tree.blockSignals(False)
            self.tree.setUpdatesEnabled(True)
            self._updating = False
        self.stack.setCurrentIndex(1 if self.ready else 0)
        if keep in self.items:
            self.tree.setCurrentItem(self.items[keep])
        else:
            self.show_job(None)
        self._update_summary()

    def _item_changed(self, item, col):
        if self._updating or col != 0:
            return
        j = item.data(1, FILE_ROLE)
        if j is None:
            return
        (self.marked.add if item.checkState(0) == Qt.Checked else self.marked.discard)(j.path)
        self._update_summary()

    def _mark_all(self, on):
        self.marked = {j.path for j in self.ready} if on else set()
        self._updating = True
        try:
            for path, it in self.items.items():
                it.setCheckState(0, Qt.Checked if path in self.marked else Qt.Unchecked)
        finally:
            self._updating = False
        self._update_summary()

    def _marked_jobs(self):
        return [j for j in self.ready if j.path in self.marked]

    def _update_summary(self):
        jobs = self._marked_jobs()
        n, saved = len(jobs), sum(j.saved for j in jobs)
        if n:
            self.btn_replace.setText(tr("Заменить {n} {files}  ·  освободится {size}", n=num(n),
                                        files=plural(n, "файл|файла|файлов", "file|files"),
                                        size=dupcore.human_size(saved)))
        else:
            self.btn_replace.setText(tr("Заменить оригиналы"))
        self.btn_replace.setEnabled(n > 0 and not self.busy)
        self.summary.setVisible(bool(self.ready))
        if not self.ready:
            self.summary.setText("")
            return
        old = sum(j.size for j in jobs)
        more = tr("  ·  подготовка продолжается…") if self.busy else ""
        self.summary.setText(tr("Готово к замене: {ready}  ·  отмечено: {n}  ·  было {old} → станет {new}",
                                ready=num(len(self.ready)), n=num(n), old=dupcore.human_size(old),
                                new=dupcore.human_size(old - saved)) + more)

    def _current_changed(self, cur, _prev):
        self.show_job(cur.data(1, FILE_ROLE) if cur is not None else None)

    def _menu(self, pos):
        item = self.tree.itemAt(pos)
        j = item.data(1, FILE_ROLE) if item else None
        if j is None:
            return
        menu = QMenu(self)
        menu.addAction(tr("Сравнить крупно  (пробел)"), self.compare_big)
        menu.addAction(tr("Открыть оригинал"), lambda: U.open_file(j.path))
        menu.addAction(tr("Открыть сжатый"), lambda: U.open_file(j.out))
        menu.addAction(tr("Показать в папке"), lambda: U.reveal(j.path))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # ---------- сравнение

    def frame_time(self, job):
        """Один и тот же момент видео для «было» и «стало»: треть длины (первые кадры часто чёрные)."""
        if job.path not in self._times:
            at = 0.0
            try:
                at = float(compcore.probe(job.path).get("format", {}).get("duration") or 0) / 3
            except (compcore.Skip, ValueError, OSError):
                pass
            self._times[job.path] = at
        return self._times[job.path]

    def show_job(self, job):
        self.current = job
        on = job is not None
        self.cmp_hint.setVisible(not on)
        self.cmp_scroll.setVisible(on)
        if not on:
            self.cmp_name.setText("")
            return
        self.cmp_name.setText(self.cmp_name.fontMetrics().elidedText(os.path.basename(job.path), Qt.ElideMiddle, 240))
        self.cmp_sizes.setText(tr("{old} → {new}, меньше на {pct} ({saved})", old=dupcore.human_size(job.size),
                                  new=dupcore.human_size(job.new_size), pct=pct(job.saved, job.size),
                                  saved=dupcore.human_size(job.saved)))
        how = job.how
        if job.check == "pixels":
            how += " · " + tr("пиксели совпадают байт в байт — изображение то же самое")
        elif job.check == "ssim":
            how += " · " + tr("SSIM {v}: на глаз разницы нет", v=score_text(job.score))
        self.cmp_how.setText(how)
        self._show_pictures()

    def _show_pictures(self):
        j = self.current
        if j is None:
            return
        at = self.frame_time(j) if j.is_video else None
        for pic, path in ((self.pic_old, j.path), (self.pic_new, j.out)):
            pic.set_image(self.previews.get(path, at), tr("Загружаю…"))

    def _preview_ready(self, key, img):
        if self.current is not None and key.split("|", 1)[0] in (self.current.path, self.current.out):
            self._show_pictures()

    def compare_big(self):
        it = self.tree.currentItem()
        j = it.data(1, FILE_ROLE) if it else None
        if j is None:
            return
        CompareDialog(self, self.ready, self.ready.index(j)).exec()

    # ---------- не сжатые, ошибки, замена

    def show_skipped(self):
        by = {}
        for j in self.skipped:
            by.setdefault(j.skip, []).append(j)
        lines = []
        for why, jobs in sorted(by.items(), key=lambda t: -len(t[1])):
            names = ", ".join(os.path.basename(j.path) for j in jobs[:3]) + (" …" if len(jobs) > 3 else "")
            lines.append(f"• {tr(why)} — {num(len(jobs))}: {names}")
        U.info(self, tr("Эти файлы оставлены как есть:\n\n") + "\n".join(lines[:20]))

    def show_errors(self):
        errs = self.result.errors if self.result else []
        lines = [f"{p}\n    {e}" for p, e in errs[:40]]
        more = tr("\n…и ещё {n}", n=len(errs) - 40) if len(errs) > 40 else ""
        U.info(self, tr("Эти файлы или папки не удалось прочитать:\n\n") + "\n".join(lines) + more)

    def _replace_with_progress(self, jobs):
        """Замена в фоне, с полосой прогресса: тысячи файлов не вешают окно."""
        from PySide6.QtWidgets import QApplication, QProgressDialog
        dlg = QProgressDialog(tr("Заменяю файлы…"), None, 0, len(jobs), self)
        dlg.setWindowTitle(U.APP_TITLE)
        dlg.setMinimumDuration(400)
        dlg.setWindowModality(Qt.WindowModal)
        result = {}
        hwnd = int(self.window().winId())

        def work():
            result["v"] = compcore.replace(jobs, hwnd=hwnd, progress=lambda n: result.__setitem__("n", n))
        th = threading.Thread(target=work, daemon=True)
        th.start()
        while th.is_alive():
            dlg.setValue(result.get("n", 0))
            QApplication.processEvents()
            th.join(0.05)
        dlg.close()
        return result.get("v", ([], [(j.path, "не удалось") for j in jobs]))

    def replace_marked(self):
        jobs = self._marked_jobs()
        if not jobs:
            U.info(self, tr("Ничего не отмечено."))
            return
        ok, problems = compcore.check_before_replace(jobs)
        if not ok:
            U.warn(self, tr("Заменять нечего:\n\n") + _problems_text(problems))
            return
        size = dupcore.human_size(sum(j.saved for j in ok))
        no_bin = sorted({d for d in (dupcore.drive_of(j.path) for j in ok) if not dupcore.has_recycle_bin(d)})
        text = tr("Заменить {n} {files} сжатыми копиями? Освободится {size}.\n\n"
                  "Оригиналы уйдут в Корзину — вернуть можно оттуда. Имена и даты файлов останутся прежними.",
                  n=num(len(ok)), files=plural(len(ok), "файл|файла|файлов", "file|files"), size=size)
        if no_bin:
            text += tr("\n\n⚠ На дисках {drives} Корзины нет (флешка, карта памяти или сетевой диск): "
                       "оригиналы оттуда удалятся НАВСЕГДА, вернуть их будет нельзя.", drives=", ".join(no_bin))
        if problems:
            text += tr("\n\nПропущу:\n") + _problems_text(problems)
        if not U.ask_yes_no(self, text, yes=tr("Заменить, оригиналы навсегда") if no_bin else tr("Заменить")):
            return
        # Пока было открыто окно подтверждения, файлы могли измениться — replace проверит их ещё раз сам.
        done, problems = self._replace_with_progress(self._marked_jobs())
        freed = sum(j.saved for j in done)
        log.info("Сжатие: заменено %d (освободилось %s), не заменено %d", len(done), dupcore.human_size(freed),
                 len(problems))
        for j in done:
            log.info("   заменён: %s (%s → %s)", j.path, dupcore.human_size(j.size), dupcore.human_size(j.new_size))
        for path, why in problems:
            log.warning("   не заменён: %s — %s", path, why)
        gone = {j.path for j in done}
        self.ready = [j for j in self.ready if j.path not in gone]
        self.marked -= gone
        self.current = None
        self.refresh()
        if not self.ready:
            self.empty.setText(tr("Все отмеченные файлы заменены сжатыми."))
        msg = tr("Заменено файлов: {n}. Освободилось {size}. Оригиналы — в Корзине.", n=num(len(done)),
                 size=dupcore.human_size(freed))
        if problems:
            msg += tr("\n\nНе заменены {n}:\n", n=len(problems)) + _problems_text(problems)
        U.info(self, msg)
        self.step_text.setText(tr("Заменено файлов: {n}, освободилось {size}. Оригиналы — в Корзине.",
                                  n=num(len(done)), size=dupcore.human_size(freed)))
