"""Вкладка «Настройки»: нагрузка, оформление, язык, поведение крестика, обновления, что хранится на диске."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QFrame, QHBoxLayout, QPushButton, QRadioButton, QScrollArea,
                               QVBoxLayout, QWidget)

import i18n
import logs
import settings
import ui_util as U
from i18n import tr
from version import VERSION

LOAD_OPTIONS = [
    ("gentle", "Бережно",
     "Поиск уступает другим программам диск и процессор: компьютер не тормозит, даже если ты работаешь "
     "или играешь. Когда компьютер свободен, скорость почти та же; когда занят — поиск идёт медленнее."),
    ("normal", "Обычно",
     "Обычный приоритет, файлы читаются по одному. Лучший выбор для обычных жёстких дисков (HDD), "
     "например внешнего WD: им вредно читать несколько файлов сразу."),
    ("fast", "Быстро — для SSD",
     "Читает четыре файла одновременно. На SSD и NVMe это заметно быстрее. На обычном жёстком диске "
     "может оказаться даже медленнее: головка диска прыгает между файлами."),
]

THEME_OPTIONS = [("system", "Как в Windows"), ("light", "Светлое"), ("dark", "Тёмное")]


class OptionCard(QFrame):
    """Карточка-вариант: переключатель, заголовок и пояснение. Щелчок по любому месту выбирает её."""

    def __init__(self, title, text, group):
        super().__init__(objectName="option")
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(12)
        self.radio = QRadioButton()
        group.addButton(self.radio)
        lay.addWidget(self.radio, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(4)
        col.addWidget(U.label(title, "strong"))
        col.addWidget(U.label(text, "muted", wrap=True))
        lay.addLayout(col, 1)
        self.radio.toggled.connect(self._mark)

    def _mark(self, on):
        self.setProperty("selected", "true" if on else "false")
        U.repolish(self)

    def mousePressEvent(self, e):
        self.radio.setChecked(True)


def radio_row(group, options, current, on_pick):
    row = QHBoxLayout()
    row.setSpacing(24)
    radios = {}
    for key, title in options:
        r = QRadioButton(title)
        group.addButton(r)
        r.setChecked(current == key)
        r.toggled.connect(lambda on, k=key: on and on_pick(k))
        radios[key] = r
        row.addWidget(r)
    row.addStretch()
    return row, radios


class SettingsPage(QScrollArea):
    load_changed = Signal()
    theme_changed = Signal()
    close_changed = Signal()
    restart_requested = Signal()
    open_logs_requested = Signal()
    check_updates_requested = Signal()

    def __init__(self, cfg):
        super().__init__(objectName="page", widgetResizable=True)
        self.cfg = cfg
        self.setFrameShape(QFrame.NoFrame)
        body = QWidget(objectName="pageBody")
        self.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(28, 20, 28, 28)
        root.setSpacing(14)
        root.addWidget(U.label(tr("Настройки"), "title"))

        root.addWidget(U.label(tr("Нагрузка на компьютер"), "h2"))
        root.addWidget(U.label(tr("Как сильно поиск дубликатов занимает диск и процессор."), "muted"))
        self.load_group = QButtonGroup(self)
        self.load_cards = {}
        for key, title, text in LOAD_OPTIONS:
            c = OptionCard(tr(title), tr(text), self.load_group)
            c.radio.setChecked(cfg.get("load") == key)
            c._mark(cfg.get("load") == key)
            c.radio.toggled.connect(lambda on, k=key: on and self._set("load", k, self.load_changed))
            self.load_cards[key] = c
            root.addWidget(c)

        root.addSpacing(8)
        root.addWidget(U.label(tr("Оформление"), "h2"))
        self.theme_group = QButtonGroup(self)
        row, self.theme_radios = radio_row(self.theme_group, [(k, tr(t)) for k, t in THEME_OPTIONS],
                                           cfg.get("theme"), lambda k: self._set("theme", k, self.theme_changed))
        root.addLayout(row)

        root.addSpacing(8)
        root.addWidget(U.label(tr("Язык"), "h2"))
        self.lang_group = QButtonGroup(self)
        row, self.lang_radios = radio_row(self.lang_group, [(k, tr(t)) for k, t in i18n.LANGS.items()],
                                          cfg.get("lang", "auto"), self._lang_picked)
        root.addLayout(row)
        self.lang_note = QHBoxLayout()
        self.lang_hint = U.label(tr("Язык сменится после перезапуска программы."), "warn")
        self.lang_restart = QPushButton(tr("Перезапустить сейчас"))
        self.lang_restart.clicked.connect(self.restart_requested.emit)
        self.lang_note.addWidget(self.lang_hint)
        self.lang_note.addWidget(self.lang_restart)
        self.lang_note.addStretch()
        root.addLayout(self.lang_note)
        self._show_lang_note(False)

        root.addSpacing(8)
        root.addWidget(U.label(tr("Когда закрываешь окно"), "h2"))
        self.close_group = QButtonGroup(self)
        self.close_radios = {}
        for value, title in (("ask", tr("Спрашивать каждый раз")),
                             ("tray", tr("Сворачивать в трей — значок у часов, поиск продолжается")),
                             ("quit", tr("Закрывать программу"))):
            r = QRadioButton(title)
            self.close_group.addButton(r)
            r.setChecked(cfg.get("close_action", "ask") == value)
            r.toggled.connect(lambda on, v=value: on and self._set("close_action", v, self.close_changed))
            self.close_radios[value] = r
            root.addWidget(r)

        root.addSpacing(8)
        root.addWidget(U.label(tr("Обновления"), "h2"))
        upd, ul = U.card()
        top = QHBoxLayout()
        top.addWidget(U.label(tr("Версия {v}", v=VERSION), "strong"))
        top.addStretch()
        self.btn_check = QPushButton(tr("Проверить обновления"))
        self.btn_check.clicked.connect(self.check_updates_requested.emit)
        top.addWidget(self.btn_check)
        ul.addLayout(top)
        self.update_status = U.label("", "muted", wrap=True)
        self.update_status.hide()
        ul.addWidget(self.update_status)
        self.auto_check = QCheckBox(tr("Проверять при запуске"))
        self.auto_check.setChecked(bool(cfg.get("check_updates", True)))
        self.auto_check.toggled.connect(lambda on: self._set("check_updates", on, None))
        ul.addWidget(self.auto_check)
        ul.addWidget(U.label(tr("Проверка обращается к GitHub, где лежат выпуски программы; никаких данных о тебе "
                                "и твоих файлах не отправляется."), "small", wrap=True))
        root.addWidget(upd)

        root.addSpacing(8)
        root.addWidget(U.label(tr("Что программа хранит на компьютере"), "h2"))
        info, il = U.card()
        il.addWidget(U.label(tr("Файл настроек (меньше 1 КБ):"), "muted", wrap=True))
        path = U.label(settings.PATH)
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        il.addWidget(path)
        il.addWidget(U.label(tr("Журнал работы — что программа делала и какие ошибки случились. Он нужен, "
                                "чтобы разобраться, если что-то пошло не так; никуда не отправляется. "
                                "Размер ограничен: не больше 3 МБ, старые записи вытесняются новыми."),
                             "muted", wrap=True))
        logs_row = QHBoxLayout()
        logs_path = U.label(logs.DIR)
        logs_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        logs_row.addWidget(logs_path)
        logs_row.addStretch()
        open_logs = QPushButton(tr("Открыть папку журнала"))
        open_logs.clicked.connect(self.open_logs_requested.emit)
        logs_row.addWidget(open_logs)
        il.addLayout(logs_row)
        il.addWidget(U.label(tr("Временных файлов и кэша на диске нет: превью живут только в памяти, пока открыто "
                                "окно. Удалённые копии лежат в Корзине, пока ты её не очистишь."), "muted",
                             wrap=True))
        root.addWidget(info)
        root.addStretch()
        self._lang_at_start = cfg.get("lang", "auto")

    def _show_lang_note(self, on):
        self.lang_hint.setVisible(on)
        self.lang_restart.setVisible(on)

    def _lang_picked(self, key):
        self._set("lang", key, None)
        self._show_lang_note(key != self._lang_at_start)

    def show_close_action(self):
        """Обновить переключатель после «Больше не спрашивать» в окне закрытия."""
        r = self.close_radios.get(self.cfg.get("close_action", "ask"))
        if r is not None:
            r.blockSignals(True)
            r.setChecked(True)
            r.blockSignals(False)

    def set_update_status(self, text):
        self.update_status.setText(text)
        self.update_status.setVisible(bool(text))

    def _set(self, key, value, signal):
        self.cfg[key] = value
        settings.save(self.cfg)
        if signal is not None:
            signal.emit()
