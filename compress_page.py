"""Вкладка «Сжатие»: пока описание будущей функции — сама функция будет следующим этапом."""

from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

import ui_util as U
from i18n import tr


class CompressPage(QScrollArea):
    def __init__(self):
        super().__init__(objectName="page", widgetResizable=True)
        self.setFrameShape(QFrame.NoFrame)
        body = QWidget(objectName="pageBody")
        self.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(28, 20, 28, 28)
        root.setSpacing(16)
        root.addWidget(U.label(tr("Сжатие фото и видео"), "title"))
        root.addWidget(U.label(tr("Скоро здесь можно будет уменьшить размер фото и видео. Пока вкладка "
                                  "показывает, как это будет устроено."), "muted", wrap=True))
        for title, text in [
            ("Строго без потерь",
             "Для фото JPEG и PNG: файл пересобирается так, что ни один пиксель не меняется — открой "
             "до и после, и они совпадут до последнего бита изображения. Экономия скромная: примерно 5–20%."),
            ("Без видимых потерь",
             "Для фото и видео: пережатие в современные форматы. На глаз разницу не увидеть, а места "
             "освобождается в разы больше — обычно 30–70%. Перед заменой программа покажет «было / стало» "
             "рядом, а оригинал отправит в Корзину."),
        ]:
            c, cl = U.card()
            cl.addWidget(U.label(tr(title), "h2"))
            cl.addWidget(U.label(tr(text), "muted", wrap=True))
            root.addWidget(c)
        root.addStretch()
