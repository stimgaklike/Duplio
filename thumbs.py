"""Быстрые превью: фото уменьшаются при чтении в фоновых потоках, из видео берётся один кадр.

Готовое превью приходит сигналом ready(путь, QImage). Повторный запрос берётся из памяти.
"""

import os
from collections import OrderedDict

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QImage, QImageReader
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink

import dupcore

CACHE_LIMIT = 300


class _ImageJob(QRunnable):
    def __init__(self, path, box, done):
        super().__init__()
        self.path, self.box, self.done = path, box, done

    def run(self):
        reader = QImageReader(self.path)
        reader.setAutoTransform(True)          # поворот по EXIF, как снимал телефон
        size = reader.size()
        if size.isValid():
            reader.setScaledSize(size.scaled(self.box, self.box, Qt.KeepAspectRatio))  # JPEG декодируется сразу мелким
        img = reader.read()
        self.done(self.path, img)


class _Relay(QObject):
    ready = Signal(str, QImage)


def _brightness(img):
    small = img.scaled(16, 16).convertToFormat(QImage.Format_Grayscale8)
    data = bytes(small.constBits())[: 16 * small.bytesPerLine()]
    vals = [data[y * small.bytesPerLine() + x] for y in range(16) for x in range(16)]
    return sum(vals) / len(vals)


class VideoFrames(QObject):
    """Кадр из видео через встроенный в Qt проигрыватель: по одному видео за раз, без звука."""

    ready = Signal(str, QImage)

    def __init__(self, box):
        super().__init__()
        self.box = box
        self.queue = []
        self.current = None
        self.player = QMediaPlayer(self)
        self.sink = QVideoSink(self)
        self.player.setVideoOutput(self.sink)
        self.sink.videoFrameChanged.connect(self._frame)
        self.player.mediaStatusChanged.connect(self._status)
        self.player.errorOccurred.connect(lambda *a: self._finish(QImage()))
        self.timeout = QTimer(self, singleShot=True, interval=6000)
        self.timeout.timeout.connect(lambda: self._finish(QImage()))

    def request(self, path):
        if path not in self.queue and path != self.current:
            self.queue.append(path)
            self._next()

    def _next(self):
        if self.current or not self.queue:
            return
        self.current = self.queue.pop(0)
        self.target_ms = 0
        self.retried = False
        self.timeout.start()
        self.player.setSource(QUrl.fromLocalFile(self.current))

    def _status(self, st):
        if st == QMediaPlayer.LoadedMedia and self.current:
            dur = self.player.duration()
            # Кадр не с самого начала: первые кадры часто чёрные.
            self.target_ms = min(1500, dur // 3) if dur > 0 else 0
            self.player.setPosition(self.target_ms)
            self.player.play()
        elif st == QMediaPlayer.InvalidMedia:
            self._finish(QImage())

    def _frame(self, frame):
        if not self.current or not frame.isValid():
            return
        # Первые кадры приходят ещё до перемотки — ждём кадр с нужного места.
        if frame.startTime() >= 0 and frame.startTime() < (self.target_ms - 200) * 1000:
            return
        img = frame.toImage()
        if img.isNull():
            return
        # Почти чёрный кадр (затемнение в начале ролика) — пробуем ещё раз ближе к середине.
        if not self.retried and _brightness(img) < 24 and self.player.duration() > 0:
            self.retried = True
            self.target_ms = int(self.player.duration() * 0.45)
            self.player.setPosition(self.target_ms)
            return
        self._finish(img.scaled(self.box, self.box, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _finish(self, img):
        if not self.current:
            return
        path, self.current = self.current, None
        self.timeout.stop()
        self.player.stop()
        self.player.setSource(QUrl())
        self.ready.emit(path, img)
        QTimer.singleShot(0, self._next)


class Thumbs(QObject):
    ready = Signal(str, QImage)

    def __init__(self, box=360):
        super().__init__()
        self.box = box
        self.cache = OrderedDict()
        self.pending = set()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)          # превью не должно отнимать диск у поиска
        self.relay = _Relay()
        self.relay.ready.connect(self._done)
        self.video = VideoFrames(box)
        self.video.ready.connect(self._done)

    def get(self, path):
        """Превью из памяти или None; если нет — запросить, придёт сигналом ready."""
        if path in self.cache:
            self.cache.move_to_end(path)
            return self.cache[path]
        if path not in self.pending:
            self.pending.add(path)
            ext = os.path.splitext(path)[1].lower()
            if ext in dupcore.VIDEO_EXT:
                self.video.request(path)
            else:
                self.pool.start(_ImageJob(path, self.box, self.relay.ready.emit))
        return None

    def _done(self, path, img):
        self.pending.discard(path)
        self.cache[path] = img
        while len(self.cache) > CACHE_LIMIT:
            self.cache.popitem(last=False)
        self.ready.emit(path, img)

    def forget(self, path):
        self.cache.pop(path, None)
