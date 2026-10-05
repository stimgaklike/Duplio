"""Общие мелочи окна: диалоги по-русски, карточки, вспомогательные функции. Тесты подменяют диалоги."""

import os
import subprocess

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (QAbstractButton, QComboBox, QFrame, QLabel, QMessageBox, QTabBar,
                               QVBoxLayout)

CLICKABLE = (QAbstractButton, QComboBox, QTabBar)

APP_TITLE = "Duplio"

from i18n import tr  # noqa: E402


def ask_yes_no(parent, text, yes=None, no=None):
    box = QMessageBox(QMessageBox.Question, APP_TITLE, text, parent=parent)
    b_yes = box.addButton(yes or tr("Да"), QMessageBox.AcceptRole)
    box.addButton(no or tr("Отмена"), QMessageBox.RejectRole)
    box.setDefaultButton(b_yes)
    box.exec()
    return box.clickedButton() is b_yes


def info(parent, text):
    box = QMessageBox(QMessageBox.Information, APP_TITLE, text, parent=parent)
    box.addButton(tr("Понятно"), QMessageBox.AcceptRole)
    box.exec()


def warn(parent, text):
    box = QMessageBox(QMessageBox.Warning, APP_TITLE, text, parent=parent)
    box.addButton(tr("Понятно"), QMessageBox.AcceptRole)
    box.exec()


class HandCursor(QObject):
    """Фильтр событий приложения: у кнопок, вкладок, переключателей и списков — курсор-«пальчик»,
    у неактивных — обычная стрелка. Ставится один раз на всё приложение."""

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Polish, QEvent.EnabledChange) and isinstance(obj, CLICKABLE):
            if obj.isEnabled():
                obj.setCursor(Qt.PointingHandCursor)
            else:
                obj.unsetCursor()
        return False


def install_hand_cursor(app):
    if not getattr(app, "_hand_cursor", None):
        app._hand_cursor = HandCursor(app)
        app.installEventFilter(app._hand_cursor)


def card(parent=None, margins=(18, 16, 18, 16), spacing=12):
    """Белая (или тёмная) карточка со скруглёнными углами и вертикальной раскладкой внутри."""
    frame = QFrame(parent, objectName="card")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return frame, lay


def label(text="", name=None, wrap=False):
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    return lbl


def open_file(path):
    if os.path.exists(path):
        os.startfile(path)


def reveal(path):
    subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])


from i18n import num, plural  # noqa: E402,F401  (для старых вызовов U.num / U.plural)


def repolish(widget):
    """Перечитать стиль после смены свойства (например, current/marked у карточки)."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()
