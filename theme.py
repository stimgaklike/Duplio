"""Оформление в духе Windows 11: светлая и тёмная палитры и таблица стилей Qt."""

import ctypes
import winreg

PALETTES = {
    "dark": {
        "bg": "#1c1c1c", "surface": "#272727", "surface2": "#2f2f2f", "hover": "#353535", "border": "#3a3a3a",
        "text": "#f2f2f2", "muted": "#a6a6a6", "accent": "#4cc2ff", "accent_hover": "#6ccfff",
        "accent_text": "#00131f", "danger": "#ff99a4", "danger_bg": "#5c2a2f", "danger_bg_hover": "#6d3238",
        "keep": "#6ccb5f", "warn": "#fce100", "selection": "#2d4153", "group": "#202020", "row_del": "#3a2427",
        "btn_hover": "#414141", "btn_pressed": "#232323", "border_hover": "#6a6a6a",
        "accent_pressed": "#2b9fd8", "danger_pressed": "#45202a",
    },
    "light": {
        "bg": "#f3f3f3", "surface": "#ffffff", "surface2": "#f7f7f7", "hover": "#ececec", "border": "#e2e2e2",
        "text": "#1b1b1b", "muted": "#5f5f5f", "accent": "#005fb8", "accent_hover": "#1a6fc0",
        "accent_text": "#ffffff", "danger": "#c42b1c", "danger_bg": "#fde7e9", "danger_bg_hover": "#f9d2d6",
        "keep": "#0f7b0f", "warn": "#9d5d00", "selection": "#dbeaf8", "group": "#f0f0f0", "row_del": "#fdeff0",
        "btn_hover": "#e6e6e6", "btn_pressed": "#d2d2d2", "border_hover": "#a8a8a8",
        "accent_pressed": "#00427f", "danger_pressed": "#f3bcc3",
    },
}


def system_theme():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return "light" if winreg.QueryValueEx(k, "AppsUseLightTheme")[0] else "dark"
    except OSError:
        return "light"


def taskbar_light():
    """Светлая ли панель задач (от этого зависит, белый или тёмный значок в трее)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return bool(winreg.QueryValueEx(k, "SystemUsesLightTheme")[0])
    except OSError:
        return False


def resolve(choice):
    return system_theme() if choice == "system" else choice


def dark_title_bar(widget, dark):
    """Тёмная или светлая полоса заголовка окна Windows под тему."""
    try:
        hwnd = int(widget.winId())
        value = ctypes.c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


# Шрифт — «Segoe UI»: у него есть настоящее жирное начертание. «Segoe UI Variable» в Qt даёт жирный только
# дорисованный (буквы с зубцами), а полужирное (600) у Segoe здесь рисуется как обычное — поэтому выделение
# везде настоящим Bold (700). Тест e2e_app проверяет это по пикселям.
def stylesheet(c, icons):
    """icons — папка со значками (галочка, стрелка); пути в QSS — с прямыми слэшами."""
    mode = "dark" if c["bg"] == PALETTES["dark"]["bg"] else "light"
    check = f"{icons}/check_{mode}.svg".replace("\\", "/")
    chevron = f"{icons}/chevron_{mode}.svg".replace("\\", "/")
    radio_on = f"{icons}/radio_on_{mode}.svg".replace("\\", "/")
    radio_off = f"{icons}/radio_off_{mode}.svg".replace("\\", "/")
    return f"""
* {{ font-family: "Segoe UI"; font-size: 14px; color: {c['text']}; }}
QMainWindow, QWidget#page, QScrollArea#page, QWidget#pageBody {{ background: {c['bg']}; }}
QToolTip {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 6px; }}

QLabel {{ background: transparent; }}
QLabel#title {{ font-size: 26px; font-weight: 700; }}
QLabel#h2 {{ font-size: 18px; font-weight: 700; }}
QLabel#strong {{ font-weight: 700; }}
QLabel#brand {{ font-size: 17px; font-weight: 700; }}
QLabel#muted {{ color: {c['muted']}; }}
QLabel#small {{ color: {c['muted']}; font-size: 12px; }}
QLabel#warn {{ color: {c['warn']}; }}
QLabel#empty {{ color: {c['muted']}; font-size: 15px; }}

QTabWidget::pane {{ border: none; background: {c['bg']}; }}
QTabBar {{ background: transparent; }}
QFrame#header {{ background: {c['bg']}; border: none; border-bottom: 1px solid {c['border']}; }}
QFrame#header QLabel {{ background: transparent; }}
QTabBar::tab {{ background: transparent; color: {c['muted']}; padding: 9px 18px; margin: 0 4px 0 0;
               border: none; border-bottom: 3px solid transparent; font-size: 15px; }}
QTabBar::tab:hover {{ color: {c['text']}; border-bottom: 3px solid {c['border_hover']}; }}
QTabBar::tab:selected {{ color: {c['text']}; border-bottom: 3px solid {c['accent']}; }}

QFrame#card {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px; }}
QFrame#card QLabel {{ background: transparent; }}
QFrame#fileCard {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px; }}
QFrame#fileCard:hover {{ border: 1px solid {c['border_hover']}; }}
QFrame#fileCard[current="true"] {{ border: 2px solid {c['accent']}; }}
QFrame#fileCard[marked="true"] QLabel#thumb {{ border: 2px solid {c['danger']}; }}
QFrame#fileCard[marked="false"] QLabel#thumb {{ border: 2px solid {c['keep']}; }}
QLabel#thumb {{ background: {c['surface2']}; border-radius: 6px; color: {c['muted']}; font-size: 28px; }}
QLabel#pillDel {{ color: {c['danger']}; font-weight: 700; }}
QLabel#pillKeep {{ color: {c['keep']}; font-weight: 700; }}

QPushButton {{ background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 6px;
              padding: 7px 16px; min-height: 18px; }}
QPushButton:hover {{ background: {c['btn_hover']}; border-color: {c['border_hover']}; }}
QPushButton:pressed {{ background: {c['btn_pressed']}; padding-top: 8px; padding-bottom: 6px; }}
QPushButton:disabled {{ color: {c['muted']}; background: {c['surface']}; }}
QPushButton#accent {{ background: {c['accent']}; color: {c['accent_text']}; border: none; font-weight: 700; }}
QPushButton#accent:hover {{ background: {c['accent_hover']}; }}
QPushButton#accent:pressed {{ background: {c['accent_pressed']}; }}
QPushButton#accent:disabled {{ background: {c['hover']}; color: {c['muted']}; }}
QPushButton#danger {{ background: {c['danger_bg']}; color: {c['danger']}; border: 1px solid {c['danger']};
                     font-weight: 700; }}
QPushButton#danger:hover {{ background: {c['danger_bg_hover']}; }}
QPushButton#danger:pressed {{ background: {c['danger_pressed']}; }}
QPushButton#danger:disabled {{ color: {c['muted']}; background: {c['surface']}; border-color: {c['border']}; }}
QPushButton#chip {{ border-radius: 15px; padding: 5px 14px; background: {c['surface2']}; }}
QPushButton#chip:hover {{ border-color: {c['accent']}; }}
QPushButton#chip:pressed {{ background: {c['btn_pressed']}; padding-top: 6px; padding-bottom: 4px; }}
QPushButton#chip:checked {{ background: {c['accent']}; color: {c['accent_text']}; border-color: {c['accent']}; }}
QPushButton#chip:checked:hover {{ background: {c['accent_hover']}; border-color: {c['accent_hover']}; }}
QPushButton#chip:checked:pressed {{ background: {c['accent_pressed']}; }}
QPushButton#chip:disabled, QPushButton#chip:checked:disabled {{ background: {c['surface']}; color: {c['muted']};
    border: 1px dashed {c['border_hover']}; }}
QPushButton#link {{ background: transparent; border: none; color: {c['accent']}; padding: 0; }}
QPushButton#link:hover {{ text-decoration: underline; }}
QPushButton#link:pressed {{ color: {c['accent_pressed']}; padding: 0; }}

QLineEdit, QComboBox {{ background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 6px;
                       padding: 6px 10px; selection-background-color: {c['accent']}; }}
QLineEdit:focus {{ border-bottom: 2px solid {c['accent']}; }}
QComboBox:hover {{ border-color: {c['border_hover']}; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{ image: url({chevron}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {c['surface']}; border: 1px solid {c['border']};
                              selection-background-color: {c['selection']}; selection-color: {c['text']}; }}

QProgressBar {{ background: {c['border']}; border: none; border-radius: 2px; max-height: 4px; min-height: 4px; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 2px; }}

QTreeWidget {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px;
              alternate-background-color: {c['surface']}; outline: none; padding: 4px; }}
QTreeWidget::item {{ height: 32px; border: none; padding-left: 4px; }}
QTreeWidget::item:selected {{ background: {c['selection']}; color: {c['text']}; }}
QTreeWidget::item:hover:!selected {{ background: {c['hover']}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: {c['surface']}; color: {c['muted']}; border: none;
                       border-bottom: 1px solid {c['border']}; padding: 8px 8px; font-size: 13px; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: {c['surface2']}; width: 12px; margin: 0; border-radius: 6px; }}
QScrollBar::handle:vertical {{ background: {c['muted']}; border-radius: 4px; min-height: 36px; margin: 2px; }}
QScrollBar::handle:vertical:hover {{ background: {c['text']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c['border']}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QSplitter::handle {{ background: transparent; width: 12px; }}

QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 18px; height: 18px; }}
QCheckBox::indicator {{ border: 1px solid {c['muted']}; border-radius: 4px; background: {c['surface2']}; }}
QCheckBox::indicator:hover {{ border-color: {c['accent']}; }}
QCheckBox::indicator:checked, QTreeView::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']};
                                                          image: url({check}); }}
QTreeView::indicator {{ width: 18px; height: 18px; border: 1px solid {c['muted']}; border-radius: 4px;
                       background: {c['surface2']}; }}
QTreeView::indicator:hover {{ border-color: {c['accent']}; }}
QRadioButton::indicator {{ width: 20px; height: 20px; image: url({radio_off}); }}
QRadioButton::indicator:checked {{ image: url({radio_on}); }}

QFrame#banner {{ background: {c['selection']}; border-bottom: 1px solid {c['border']}; }}
QFrame#banner QLabel {{ background: transparent; }}
QTextBrowser {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 8px; }}

QFrame#option {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px; }}
QFrame#option:hover {{ border: 1px solid {c['border_hover']}; }}
QFrame#option[selected="true"] {{ border: 2px solid {c['accent']}; }}

QDialog {{ background: {c['bg']}; }}
QMessageBox {{ background: {c['surface']}; }}
QMenu {{ background: {c['surface']}; border: 1px solid {c['border']}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {c['selection']}; }}
"""
