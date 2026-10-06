"""Duplio — главное окно: вкладки «Дубликаты», «Сжатие», «Настройки», значок в трее, обновления."""

import ctypes
import getpass
import html
import os
import sys
import threading
import time

from PySide6.QtCore import QByteArray, QObject, QProcess, QTimer, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu, QProgressBar,
                               QPushButton, QStackedWidget, QSystemTrayIcon, QTabBar, QTextBrowser,
                               QVBoxLayout, QWidget)

import compcore
import dupcore
import i18n
import logs
import metacore
import settings
import theme
import ui_util as U
import updater
from i18n import tr
from logs import log
from version import VERSION

# Имя «почтового ящика» запущенной программы: второй запуск передаёт ему папку и закрывается.
INSTANCE_KEY = "Duplio-" + getpass.getuser()
# По этому имени установщик понимает, что программа открыта, и ждёт её закрытия.
APP_MUTEX = "DuplioAppMutex"
QUIT_REQUEST = "duplio:quit"      # установщик просит закрыться перед установкой (installer.iss); пути с «:» не бывает
CHECK_EVERY = 20 * 3600         # автоматическая проверка обновлений — не чаще раза в ~сутки


def resource(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


class UpdateBridge(QObject):
    found = Signal(object)          # Update или None
    failed = Signal(str)
    progress = Signal(object, object)
    downloaded = Signal(str)


class UpdateDialog(QDialog):
    """Что нового → скачать (с прогрессом и проверкой) → установить и перезапустить."""

    def __init__(self, win, upd):
        super().__init__(win)
        self.win, self.upd = win, upd
        self.path = None
        self.cancel = threading.Event()
        self.setWindowTitle(tr("Доступна версия {v}", v=upd.version))
        self.resize(560, 440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(12)
        lay.addWidget(U.label(tr("Доступна версия {v}", v=upd.version), "h2"))
        lay.addWidget(U.label(tr("Что нового"), "strong"))
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(upd.notes or "—")
        lay.addWidget(notes, 1)
        self.bar = QProgressBar(textVisible=False, maximum=1000)
        self.bar.hide()
        lay.addWidget(self.bar)
        self.status = U.label("", "muted", wrap=True)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch()
        self.later = QPushButton(tr("Позже"))
        self.later.clicked.connect(self.reject)
        row.addWidget(self.later)
        self.go = QPushButton(tr("Обновить"), objectName="accent")
        self.go.clicked.connect(self._go)
        row.addWidget(self.go)
        lay.addLayout(row)
        self.bridge = UpdateBridge()
        self.bridge.progress.connect(self._progress)
        self.bridge.downloaded.connect(self._downloaded)
        self.bridge.failed.connect(self._failed)

    def _go(self):
        if self.path:                       # уже скачано — ставим
            note = self.win.busy_note()
            text = (tr("Сейчас идёт поиск. Остановить его и обновиться сейчас? Найденное будет потеряно.")
                    if self.win.dups.busy else
                    tr("Сжатие ещё идёт или сжатые копии не заменили оригиналы. Обновиться сейчас? Готовые копии "
                       "пропадут."))
            if note and not U.ask_yes_no(self, text, yes=tr("Остановить и обновить"), no=tr("Позже")):
                return
            log.info("Обновление: запускаю установщик %s", self.path)
            updater.install(self.path)
            self.win.quit_app(confirmed=True)
            return
        self.go.setEnabled(False)
        self.bar.show()

        def work():
            try:
                self.bridge.downloaded.emit(updater.download(self.upd, self.bridge.progress.emit, self.cancel))
            except updater.Cancelled:
                pass
            except ValueError:
                log.warning("Обновление: контрольная сумма не совпала")
                self.bridge.failed.emit(tr("Скачанный файл повреждён (не совпала контрольная сумма). "
                                           "Попробуй ещё раз."))
            except Exception as e:
                log.exception("Обновление: скачать не удалось")
                self.bridge.failed.emit(tr("Не удалось скачать обновление: {err}", err=e))
        threading.Thread(target=work, daemon=True).start()

    def _progress(self, done, total):
        if total:
            self.bar.setValue(int(1000 * done / total))
        self.status.setText(tr("Скачиваю обновление… {done} из {total}", done=dupcore.human_size(done),
                               total=dupcore.human_size(total or done)))

    def _downloaded(self, path):
        self.path = path
        self.bar.setValue(1000)
        self.status.setText(tr("Обновление скачано. Программа закроется, установит новую версию и откроется снова."))
        self.go.setText(tr("Установить и перезапустить"))
        self.go.setEnabled(True)

    def _failed(self, text):
        self.status.setText(text)
        self.bar.hide()
        self.go.setEnabled(True)

    def reject(self):
        self.cancel.set()
        super().reject()


class Tabs(QWidget):
    """Шапка со знаком и вкладками + страницы под ней.

    Своя, а не QTabWidget: у того угловая область рисует собственную рамку, и знак слева
    от вкладок оказывался в лишней полосе и ниже вкладок.
    """

    def __init__(self, brand):
        super().__init__()
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self.header = QFrame(objectName="header")
        row = QHBoxLayout(self.header)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(brand)
        self.bar = QTabBar()
        self.bar.setDrawBase(False)
        self.bar.setExpanding(False)
        self.bar.setDocumentMode(True)
        row.addWidget(self.bar, 0, Qt.AlignBottom)
        row.addStretch()
        col.addWidget(self.header)
        self.stack = QStackedWidget()
        col.addWidget(self.stack, 1)
        self.bar.currentChanged.connect(self.stack.setCurrentIndex)

    def addTab(self, page, text):
        self.stack.addWidget(page)
        self.bar.addTab(text)

    def setCurrentWidget(self, page):
        self.bar.setCurrentIndex(self.stack.indexOf(page))

    def currentWidget(self):
        return self.stack.currentWidget()

    def tabText(self, i):
        return self.bar.tabText(i)

    def count(self):
        return self.bar.count()

    def tabBar(self):
        return self.bar


class MainWindow(QMainWindow):
    def __init__(self, cfg):
        super().__init__()
        from compress_page import CompressPage      # после выбора языка: тексты вкладок берутся при создании
        from dups_page import DupsPage
        from meta_page import MetaPage
        from settings_page import SettingsPage
        from thumbs import Thumbs
        U.install_hand_cursor(QApplication.instance())     # до создания вкладок: их кнопки тоже получат «пальчик»
        self.cfg = cfg
        self.quitting = False
        self.update_info = None
        self._manual_check = False
        self.setWindowTitle(U.APP_TITLE)
        self.icon = QIcon(resource("icon.ico"))
        self.setWindowIcon(self.icon)
        self.resize(1320, 880)
        self.setMinimumSize(1040, 700)
        self.mode = theme.resolve(cfg.get("theme", "system"))
        self.colors = dict(theme.PALETTES[self.mode])
        self.thumbs = Thumbs(360)

        central = QWidget()
        col = QVBoxLayout(central)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self.banner = self._build_banner()
        col.addWidget(self.banner)
        self.tabs = Tabs(self._brand())
        self.dups = DupsPage(cfg, self.thumbs, self.colors)
        self.compress = CompressPage(cfg, self.colors)
        self.meta = MetaPage(cfg, self.colors)
        self.settings = SettingsPage(cfg)
        self.tabs.addTab(self.dups, tr("Дубликаты"))
        self.tabs.addTab(self.compress, tr("Сжатие"))
        self.tabs.addTab(self.meta, tr("Метаданные"))
        self.tabs.addTab(self.settings, tr("Настройки"))
        col.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        # Перетаскивание файлов и папок на окно: подсказка поверх, пока тащат (drop_plan решает, куда что).
        self.setAcceptDrops(True)
        self.drop_hint = QLabel(central, objectName="dropHint", alignment=Qt.AlignCenter, wordWrap=True)
        self.drop_hint.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.drop_hint.hide()

        self.dups.title_changed.connect(self._title)
        self.dups.go_settings.connect(lambda: self.tabs.setCurrentWidget(self.settings))
        self.dups.settings_changed.connect(lambda: settings.save(self.cfg))
        self.dups.finished.connect(self._scan_finished)
        self.settings.load_changed.connect(self.dups.set_load_text)
        self.settings.load_changed.connect(self.compress.set_load_text)
        self.compress.title_changed.connect(self._title)
        self.compress.go_settings.connect(lambda: self.tabs.setCurrentWidget(self.settings))
        self.compress.settings_changed.connect(lambda: settings.save(self.cfg))
        self.compress.finished.connect(self._compress_finished)
        self.settings.load_changed.connect(self.meta.set_load_text)
        self.meta.title_changed.connect(self._title)
        self.meta.go_settings.connect(lambda: self.tabs.setCurrentWidget(self.settings))
        self.meta.settings_changed.connect(lambda: settings.save(self.cfg))
        self.settings.theme_changed.connect(self.apply_theme)
        self.settings.restart_requested.connect(self.restart)
        self.settings.check_updates_requested.connect(lambda: self.check_updates(manual=True))
        self.upd_bridge = UpdateBridge()
        self.upd_bridge.found.connect(self._update_found)
        self.upd_bridge.failed.connect(self._update_failed)
        self.settings.open_logs_requested.connect(lambda: U.open_file(logs.DIR))
        self._build_tray()
        self.apply_theme()
        self._crash_shown = False
        logs.on_crash(self._crashed)

    def _crashed(self, err):
        """Неожиданная ошибка: сказать об этом и показать, где журнал. Один раз — без лавины окон."""
        if self._crash_shown:
            return
        self._crash_shown = True
        if U.ask_yes_no(self, tr("Что-то пошло не так: {err}\n\nПодробности записаны в журнал. "
                                 "Программа продолжит работать.", err=err),
                        yes=tr("Открыть журнал"), no=tr("Закрыть")):
            U.open_file(logs.DIR)
        self._crash_shown = False

    def _brand(self):
        """Знак и название слева от вкладок."""
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(22, 0, 22, 0)
        row.setSpacing(8)
        mark = QLabel()
        mark.setPixmap(QPixmap(resource(os.path.join("icons", "mark-64.png"))).scaled(
            26, 26, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        row.addWidget(mark)
        row.addWidget(U.label("Duplio", "brand"))
        return box

    # ---------- обновления

    def _build_banner(self):
        banner = QFrame(objectName="banner")
        row = QHBoxLayout(banner)
        row.setContentsMargins(28, 10, 28, 10)
        row.setSpacing(12)
        self.banner_text = U.label("", "strong")
        row.addWidget(self.banner_text)
        notes = QPushButton(tr("Что нового"), objectName="link")
        notes.setCursor(Qt.PointingHandCursor)
        notes.clicked.connect(self.show_update)
        row.addWidget(notes)
        row.addStretch()
        later = QPushButton(tr("Позже"))
        later.clicked.connect(banner.hide)
        row.addWidget(later)
        go = QPushButton(tr("Обновить"), objectName="accent")
        go.clicked.connect(self.show_update)
        row.addWidget(go)
        banner.hide()
        return banner

    def check_updates(self, manual=False):
        if manual:
            self.settings.set_update_status(tr("Проверяю…"))
        self._manual_check = manual

        def work():
            try:
                upd = updater.check()
                log.info("Обновления: %s", f"доступна {upd.version}" if upd else "последняя версия")
                self.upd_bridge.found.emit(upd)
            except Exception as e:
                log.warning("Обновления: проверка не удалась: %s", e)
                self.upd_bridge.failed.emit(str(e))
        threading.Thread(target=work, daemon=True).start()

    def maybe_check_updates(self):
        if self.cfg.get("check_updates", True) and time.time() - self.cfg.get("last_update_check", 0) > CHECK_EVERY:
            self.check_updates()

    def _update_found(self, upd):
        self.update_info = upd
        self.cfg["last_update_check"] = int(time.time())     # только удачная проверка откладывает следующую
        settings.save(self.cfg)
        if upd is None:
            if self._manual_check:
                self.settings.set_update_status(tr("Установлена последняя версия."))
            return
        self.settings.set_update_status(tr("Доступна версия {v}", v=upd.version))
        self.banner_text.setText(tr("Доступна версия {v}", v=upd.version))
        self.banner.show()

    def _update_failed(self, err):
        if self._manual_check:
            self.settings.set_update_status(tr("Не удалось проверить обновления: {err}", err=err))

    def show_update(self):
        if self.update_info:
            dlg = UpdateDialog(self, self.update_info)
            dlg.setAttribute(Qt.WA_DeleteOnClose)
            dlg.exec()

    # ---------- трей

    def _build_tray(self):
        tray_icon = "tray-light-taskbar.ico" if theme.taskbar_light() else "tray-dark-taskbar.ico"
        self.tray = QSystemTrayIcon(QIcon(resource(os.path.join("icons", tray_icon))), self)
        self.tray.setToolTip(U.APP_TITLE)
        menu = QMenu()
        menu.addAction(tr("Открыть"), self.bring_back)
        menu.addSeparator()
        self.act_stop = menu.addAction(tr("Остановить поиск"), self.dups.stop_scan)
        self.act_stop_compress = menu.addAction(tr("Остановить сжатие"), self.compress.stop)
        self.act_stop_meta = menu.addAction(tr("Остановить работу с метаданными"), self.meta.stop)
        menu.addAction(tr("Выход"), self.quit_app)
        menu.aboutToShow.connect(lambda: (self.act_stop.setVisible(self.dups.busy),
                                          self.act_stop_compress.setVisible(self.compress.busy),
                                          self.act_stop_meta.setVisible(self.meta.busy)))
        self.tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.bring_back() if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick)
            else None)
        self.tray.messageClicked.connect(self.bring_back)
        self.tray.show()

    def _title(self, text):
        self.setWindowTitle(text)
        self.tray.setToolTip(text)              # ход поиска виден и при наведении на значок в трее

    def bring_back(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _scan_finished(self, groups, size):
        if self.isVisible() and not self.isMinimized():
            return
        if groups:
            text = tr("Найдено групп копий: {n}. Можно освободить {size}.", n=i18n.num(groups),
                      size=dupcore.human_size(size))
        else:
            text = tr("Точных копий не нашлось.")
        self.tray.showMessage(tr("Поиск завершён"), text, self.icon, 8000)

    def _compress_finished(self, ready, size):
        if self.isVisible() and not self.isMinimized():
            return
        if ready:
            text = tr("Сжатые копии готовы: {n}. Можно освободить {size}.", n=i18n.num(ready),
                      size=dupcore.human_size(size))
        else:
            text = tr("Сжимать нечего: файлы уже сжаты хорошо.")
        self.tray.showMessage(tr("Сжатие подготовлено"), text, self.icon, 8000)

    def busy_note(self):
        """Что пропадёт при выходе: (текст для окна крестика, вопрос, кнопка «не закрывать») или None."""
        if self.dups.busy:
            return (True, tr("Идёт поиск. Закрыть программу и остановить его? Найденное будет потеряно."),
                    tr("Продолжить поиск"))
        if self.compress.busy:
            return (tr("Сейчас идёт сжатие — если закрыть программу, оно остановится, а готовые копии пропадут."),
                    tr("Идёт сжатие. Закрыть программу и остановить его? Готовые копии пропадут."),
                    tr("Продолжить сжатие"))
        if self.meta.busy:
            return (tr("Сейчас идёт работа с метаданными — если закрыть программу, она остановится. "
                       "Уже готовые файлы останутся готовыми."),
                    tr("Идёт работа с метаданными. Закрыть программу и остановить её?"),
                    tr("Продолжить"))
        if self.compress.has_pending():
            return (tr("Сжатые копии ещё не заменили оригиналы — при закрытии они пропадут."),
                    tr("Сжатые копии ещё не заменили оригиналы. Закрыть программу? Они пропадут."),
                    tr("Не закрывать"))
        return None

    def quit_app(self, confirmed=False):
        """confirmed — про идущий поиск уже спросили (например, в окне обновления)."""
        self.quitting = True
        self._quit_confirmed = confirmed
        self.close()
        self._quit_confirmed = False

    def restart(self):
        """Перезапуск (например, после смены языка): новая копия поднимется, когда эта закроется."""
        if getattr(self, "server", None):
            self.server.close()
        if getattr(sys, "frozen", False):
            QProcess.startDetached(sys.executable, [])
        else:
            QProcess.startDetached(sys.executable, [os.path.abspath(__file__)])
        self.quit_app()

    def closeEvent(self, e):
        action = "quit" if self.quitting else self.cfg.get("close_action", "ask")
        warned = getattr(self, "_quit_confirmed", False)
        if action == "ask":
            warned = True                       # в окне вопроса про идущий поиск уже сказано
            note = self.busy_note()
            action, remember = U.ask_close(self, busy=note[0] if note else False)
            if action is None:                  # «Отмена» — окно остаётся
                e.ignore()
                return
            if remember:
                self.cfg["close_action"] = action
                settings.save(self.cfg)
                self.settings.show_close_action()
        note = None if warned else self.busy_note()
        if action == "quit" and note and not U.ask_yes_no(self, note[1], yes=tr("Закрыть"), no=note[2]):
            e.ignore()
            self.quitting = False
            return
        if action == "tray":
            e.ignore()
            self.hide()
            if not self.cfg.get("tray_hint_shown"):
                self.tray.showMessage(U.APP_TITLE, tr("Программа свёрнута в трей и продолжает работать. Открыть — "
                                                      "щелчок по значку, выйти — правой кнопкой → «Выход». "
                                                      "Поменять можно в «Настройках»."), self.icon, 8000)
                self.cfg["tray_hint_shown"] = True
                settings.save(self.cfg)
            return
        if self.dups.cancel:
            self.dups.cancel.set()
        if self.compress.cancel:
            self.compress.cancel.set()
        self.meta.finish_before_exit()          # замену, начатую на «Метаданных», не обрываем на середине
        compcore.clean_work()                   # сжатые копии, которые не заменили оригиналы, больше не нужны
        metacore.clean_work()
        settings.save(self.cfg)
        log.info("Выход")
        release_mutex()
        self.tray.hide()
        super().closeEvent(e)
        QApplication.instance().quit()

    # ---------- тема

    def apply_theme(self):
        self.mode = theme.resolve(self.cfg.get("theme", "system"))
        self.colors.clear()
        self.colors.update(theme.PALETTES[self.mode])     # тот же словарь — страницы видят новые цвета
        QApplication.instance().setStyleSheet(theme.stylesheet(self.colors, resource("icons")))
        theme.dark_title_bar(self, self.mode == "dark")
        if self.dups.groups:
            self.dups.clear_cards()
            self.dups.refresh()
        if self.compress.ready:
            self.compress.refresh()
        self.compress.update()
        if self.meta.items:
            self.meta.refresh()
        self.meta.update()

    # ---------- второй запуск

    # ---------- перетаскивание

    @staticmethod
    def dropped_paths(mime):
        return [os.path.normpath(u.toLocalFile()) for u in mime.urls()
                if u.isLocalFile() and os.path.exists(u.toLocalFile())]

    def drop_plan(self, paths):
        """Куда пойдёт перетащенное: (вкладка, что сказать до броска, None) или (None, почему нельзя)."""
        cur = self.tabs.currentWidget()
        dirs = [p for p in paths if os.path.isdir(p)]
        files = [p for p in paths if not os.path.isdir(p)]
        media = compcore.wanted_ext({"photo", "video"})
        if cur is self.settings:
            cur = self.compress if files and not dirs and all(
                os.path.splitext(p)[1].lower() in media for p in files) else self.dups
        if cur.busy:
            what = tr("поиск") if cur is self.dups else tr("сжатие") if cur is self.compress else \
                tr("работа с метаданными")
            return None, tr("Сейчас идёт {what} — дождись конца или останови его.", what=what), ""
        if cur is self.dups:
            folder = dirs[0] if dirs else os.path.dirname(files[0])
            return (cur, tr("Отпусти — подставлю папку «{name}» в «Дубликаты»", name=os.path.basename(folder) or folder),
                    tr("Искать начну по кнопке «Начать поиск»."))
        if cur is self.meta:
            if len(dirs) == 1 and not files:
                return (cur, tr("Отпусти — подставлю папку «{name}» в «Метаданные»",
                                name=os.path.basename(dirs[0]) or dirs[0]),
                        tr("Проверю файлы по кнопке «Проверить файлы»."))
            parts = []
            if dirs:
                parts.append(f"{i18n.num(len(dirs))} {i18n.plural(len(dirs), 'папку|папки|папок', 'folder|folders')}")
            if files:
                parts.append(f"{i18n.num(len(files))} {i18n.plural(len(files), 'файл|файла|файлов', 'file|files')}")
            return (cur, tr("Отпусти — проверю только {what}", what=tr(" и ").join(parts)),
                    tr("Остальные файлы в папках не трону. Проверю по кнопке."))
        if len(dirs) == 1 and not files:
            return (cur, tr("Отпусти — подставлю папку «{name}» в «Сжатие»", name=os.path.basename(dirs[0]) or dirs[0]),
                    tr("Сжатые копии начну готовить по кнопке."))
        parts = []
        if dirs:
            parts.append(f"{i18n.num(len(dirs))} {i18n.plural(len(dirs), 'папку|папки|папок', 'folder|folders')}")
        if files:
            parts.append(f"{i18n.num(len(files))} {i18n.plural(len(files), 'файл|файла|файлов', 'file|files')}")
        return (cur, tr("Отпусти — сожму только {what}", what=tr(" и ").join(parts)),
                tr("Остальные файлы в папках не трону. Сжатые копии начну готовить по кнопке."))

    def _show_drop_hint(self, title, sub=""):
        self.drop_hint_text = title               # без разметки — для журнала и тестов
        self.drop_hint.setText(f"{html.escape(title)}<div style='font-size:14px; font-weight:400; "
                               f"color:{self.colors['muted']}; margin-top:10px'>{html.escape(sub)}</div>")
        self.drop_hint.setGeometry(self.centralWidget().rect().adjusted(16, 16, -16, -16))
        self.drop_hint.raise_()
        self.drop_hint.show()

    def dragEnterEvent(self, e):
        paths = self.dropped_paths(e.mimeData())
        if not paths:
            e.ignore()
            return
        page, title, sub = self.drop_plan(paths)
        self._show_drop_hint(title, sub)
        e.acceptProposedAction()

    def dragMoveEvent(self, e):
        e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.drop_hint.hide()

    def dropEvent(self, e):
        self.drop_hint.hide()
        paths = self.dropped_paths(e.mimeData())
        if not paths:
            return
        page, title, _sub = self.drop_plan(paths)
        if page is None:
            U.warn(self, title)
            return
        e.acceptProposedAction()
        self.bring_back()
        self.tabs.setCurrentWidget(page)
        dirs = [p for p in paths if os.path.isdir(p)]
        log.info("Перетащено: %d (папок %d) → %s", len(paths), len(dirs), type(page).__name__)
        if page is self.dups:
            page.use_drop(paths)
        elif len(dirs) == 1 and len(paths) == 1:
            page.use_folder(dirs[0])
        else:
            page.use_files(paths)

    def open_folder(self, folder):
        self.bring_back()
        if folder and os.path.isdir(folder) and not self.dups.busy:
            self.tabs.setCurrentWidget(self.dups)
            self.dups.folder.setText(os.path.normpath(folder))


_mutex = None


def release_mutex():
    """Отпустить метку «программа открыта» — установщик обновления дальше не ждёт."""
    global _mutex
    if _mutex:
        ctypes.windll.kernel32.CloseHandle(_mutex)
        _mutex = None


def already_running(folder):
    """Если программа уже запущена — показать её окно (и передать папку) и вернуть True."""
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_KEY)
    if not sock.waitForConnected(300):
        return False
    sock.write(QByteArray((folder or "").encode("utf-8")))
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def listen(win):
    server = QLocalServer(win)
    QLocalServer.removeServer(INSTANCE_KEY)          # хвост от программы, закрытой аварийно
    server.listen(INSTANCE_KEY)

    def incoming():
        conn = server.nextPendingConnection()

        def read():
            text = bytes(conn.readAll()).decode("utf-8", "replace")
            if not text:                              # второй вызов после того, как всё уже прочитано
                return
            if text == QUIT_REQUEST:
                # Как «Выход» из трея: если идёт поиск или сжатие — программа спросит, и можно отказаться.
                log.info("Установщик просит закрыть программу")
                QTimer.singleShot(0, win.quit_app)
            else:
                win.open_folder(text)
        conn.readyRead.connect(read)
        conn.disconnected.connect(conn.deleteLater)
        if conn.bytesAvailable() or conn.waitForReadyRead(300):
            read()
        else:
            win.bring_back()
    server.newConnection.connect(incoming)
    return server


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(U.APP_TITLE)
    app.setQuitOnLastWindowClosed(False)            # окно может прятаться в трей
    args = [a for a in sys.argv[1:] if a != "--scan"]
    folder = args[0] if args and os.path.isdir(args[0]) else ""
    autostart = "--scan" in sys.argv[1:]
    if already_running(folder):
        return
    global _mutex
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, APP_MUTEX)
    cfg = settings.load()
    i18n.set_lang(cfg.get("lang", "auto"))
    logs.setup(VERSION)
    log.info("Язык %s, тема %s, нагрузка %s", i18n.LANG, cfg.get("theme"), cfg.get("load"))
    updater.cleanup()                                 # установщик прошлого обновления больше не нужен
    compcore.clean_work()                             # сжатые копии от прошлого запуска (если он упал)
    win = MainWindow(cfg)
    win.server = listen(win)
    win.show()
    theme.dark_title_bar(win, win.mode == "dark")
    # Duplio.exe "E:\Фото" или перетащить папку на значок — папка подставится, поиск — кнопкой.
    # Duplio.exe --scan "E:\Фото" — сразу начать поиск.
    if folder:
        win.dups.folder.setText(os.path.normpath(folder))
        if autostart:
            win.dups.start_scan()
    win.maybe_check_updates()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
