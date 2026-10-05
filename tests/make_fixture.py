"""Создать tests/fixtures/sample.mp4 — короткое видео для тестов (кадры с превью), средствами Qt.

Своё содержимое (градиент и надпись), чтобы в репозитории не было чужих роликов.
python tests/make_fixture.py
"""

import os

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter
from PySide6.QtMultimedia import QMediaCaptureSession, QMediaFormat, QMediaRecorder, QVideoFrame, QVideoFrameInput
from PySide6.QtWidgets import QApplication

W, H, FPS, N = 320, 180, 15, 45
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "sample.mp4")


def frame(i):
    img = QImage(W, H, QImage.Format_ARGB32)
    p = QPainter(img)
    g = QLinearGradient(0, 0, W, H)
    g.setColorAt(0, QColor(0, 102, 255))
    g.setColorAt(1, QColor(8, 191, 120))
    p.fillRect(img.rect(), g)
    p.setPen(QColor("white"))
    f = QFont("Segoe UI")
    f.setPixelSize(40)
    f.setBold(True)
    p.setFont(f)
    p.drawText(img.rect(), Qt.AlignCenter, f"Duplio {i // FPS + 1}")
    p.end()
    fr = QVideoFrame(img)
    fr.setStartTime(int(i * 1e6 / FPS))
    fr.setEndTime(int((i + 1) * 1e6 / FPS))
    return fr


def main():
    app = QApplication([])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if os.path.exists(OUT):
        os.remove(OUT)
    vin = QVideoFrameInput()
    session = QMediaCaptureSession()
    session.setVideoFrameInput(vin)
    rec = QMediaRecorder()
    session.setRecorder(rec)
    fmt = QMediaFormat(QMediaFormat.FileFormat.MPEG4)
    fmt.setVideoCodec(QMediaFormat.VideoCodec.H264)
    rec.setMediaFormat(fmt)
    rec.setVideoFrameRate(FPS)
    rec.setVideoResolution(QSize(W, H))
    rec.setOutputLocation(QUrl.fromLocalFile(OUT))
    sent = [0]

    def push():
        # Кадры принимаются только во время записи; если очередь полна — ждём сигнала готовности.
        if rec.recorderState() != QMediaRecorder.RecorderState.RecordingState:
            return
        while sent[0] < N:
            if not vin.sendVideoFrame(frame(sent[0])):
                return
            sent[0] += 1
        rec.stop()

    def state(s):
        if s == QMediaRecorder.RecorderState.RecordingState:
            QTimer.singleShot(0, push)
        elif s == QMediaRecorder.RecorderState.StoppedState and sent[0] >= N:
            QTimer.singleShot(500, app.quit)

    vin.readyToSendVideoFrame.connect(push)
    rec.recorderStateChanged.connect(state)
    rec.errorOccurred.connect(lambda e, s: (print("ошибка записи:", s), app.quit()))
    rec.record()
    QTimer.singleShot(20000, app.quit)
    app.exec()
    print(OUT, os.path.getsize(OUT) if os.path.exists(OUT) else "не создан")


if __name__ == "__main__":
    main()
