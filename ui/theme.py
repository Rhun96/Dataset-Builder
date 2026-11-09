"""Единый визуал: Fluent-тема, сетка таблиц, статусы."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget
from qfluentwidgets import Theme, setTheme

GRID_LIGHT = "#D5DDE5"
HEAD_LIGHT = "#E8EDF3"
GRID_DARK = "#3F3F3F"
HEAD_DARK = "#2B2B2B"

THEME_QSETTINGS_KEY = "appearance/theme"  # light | dark | auto
NATIVE_FRAME_KEY = "appearance/native_frame"  # классический заголовок окна


def app_qss(dark: bool = False) -> str:
    grid = GRID_DARK if dark else GRID_LIGHT
    head = HEAD_DARK if dark else HEAD_LIGHT
    page_bg = GRAPHITE_BG if dark else LIGHT_BG
    text = """
QLabel { color: #F2F2F2; }
QLabel[hint="true"] { color: #A8B0B8; }
QTableWidget::item { color: #F2F2F2; }
QHeaderView::section { color: #F2F2F2; }
""" if dark else ""
    return f"""
* {{ font-family: "Segoe UI"; font-size: 9pt; }}
QLabel[hint="true"] {{ color: #5D6B7A; }}
{TIP_DARK if dark else TIP_LIGHT}
TableWidget {{ gridline-color: {grid}; }}
TableWidget::item {{
    border-right: 1px solid {grid};
    border-bottom: 1px solid {grid};
}}
QHeaderView::section {{
    background: {head};
    border-right: 1px solid {grid};
    border-bottom: 1px solid {grid};
    padding: 4px;
}}
QScrollArea {{ background: {page_bg}; border: none; }}
QWidget#scrollInner {{ background: {page_bg}; }}
{text}
"""

STATUS_QSS = {
    "ok": "background: #E6F4EA; color: #0B6A2B; padding: 4px; border-radius: 4px;",
    "warn": "background: #FFF4CE; color: #7A4A00; padding: 4px; border-radius: 4px;",
    "block": "background: #FDE7E9; color: #B10E1E; padding: 4px; border-radius: 4px;",
    "info": "",
}

TIP_DARK = ("QToolTip { background: #2A2F36; color: #F2F2F2; "
            "border: 1px solid #F5A524; padding: 4px; }")
TIP_LIGHT = ("QToolTip { background: #FFFBEA; color: #1B1B1B; "
             "border: 1px solid #D5DDE5; padding: 4px; }")


THEME_MODES = {"light": Theme.LIGHT, "dark": Theme.DARK, "auto": Theme.AUTO}

# Фирменный акцент вместо fluent-бирюзы. Только наш процесс, никуда не пишем.
ACCENT = "#F5A524"
GRAPHITE_BG = "#14161A"
LIGHT_BG = "#F2F4F7"


def saved_theme() -> str:
    from PySide6.QtCore import QSettings
    mode = QSettings("DatasetBuilder", "DatasetBuilderV2").value(THEME_QSETTINGS_KEY, "light")
    return mode if mode in THEME_MODES else "light"


def save_theme(mode: str) -> None:
    from PySide6.QtCore import QSettings
    if mode in THEME_MODES:
        QSettings("DatasetBuilder", "DatasetBuilderV2").setValue(THEME_QSETTINGS_KEY, mode)


def saved_native_frame() -> bool:
    from PySide6.QtCore import QSettings
    return QSettings("DatasetBuilder", "DatasetBuilderV2").value(
        NATIVE_FRAME_KEY, False, type=bool)


def save_native_frame(on: bool) -> None:
    from PySide6.QtCore import QSettings
    QSettings("DatasetBuilder", "DatasetBuilderV2").setValue(NATIVE_FRAME_KEY, bool(on))


def apply_theme(app) -> None:
    from PySide6.QtGui import QColor
    from qfluentwidgets import qconfig
    mode = saved_theme()
    setTheme(THEME_MODES[mode])
    try:
        qconfig.set(qconfig.themeMode, THEME_MODES[mode])
    except Exception:  # noqa: BLE001 — версия без qconfig, хватит setTheme
        pass
    try:
        qconfig.set(qconfig.themeColor, QColor(ACCENT), save=False)
    except Exception:  # noqa: BLE001 — акцент не встал, останутся стандартные цвета
        pass
    app.setStyleSheet(app_qss(dark=(mode == "dark")))


def apply_window_bg(win) -> None:
    """Фирменный фон окна: графит в тёмной, светлый в светлой."""
    from PySide6.QtGui import QColor
    try:
        win.setCustomBackgroundColor(QColor(LIGHT_BG), QColor(GRAPHITE_BG))
    except Exception:  # noqa: BLE001
        pass


def set_status(label, text: str, kind: str = "info") -> None:
    label.setText(text)
    label.setStyleSheet(STATUS_QSS.get(kind, ""))


def polish_table(tbl) -> None:
    tbl.setSelectionBehavior(tbl.SelectionBehavior.SelectRows)
    tbl.setEditTriggers(tbl.EditTrigger.NoEditTriggers)
    tbl.verticalHeader().setVisible(False)
    tbl.horizontalHeader().setStretchLastSection(True)
    tbl.horizontalHeader().setMinimumSectionSize(24)


def _scroll_bg() -> str:
    """Фон прокрутки под текущую тему."""
    try:
        from qfluentwidgets import isDarkTheme
        dark = bool(isDarkTheme())
    except Exception:  # noqa: BLE001
        dark = saved_theme() == "dark"
    return GRAPHITE_BG if dark else LIGHT_BG


def paint_scroll_viewport(scroll) -> None:
    from PySide6.QtGui import QColor, QPalette
    bg = QColor(_scroll_bg())
    vp = scroll.viewport()
    pal = vp.palette()
    pal.setColor(QPalette.Window, bg)
    pal.setColor(QPalette.Base, bg)
    vp.setPalette(pal)
    vp.setAutoFillBackground(True)
    inner = scroll.widget()
    if inner is not None:
        inner.setObjectName("scrollInner")
        inner.setStyleSheet(f"background-color: {_scroll_bg()}; border: none;")


def refresh_scroll_bgs() -> None:
    """Перекрасить все прокрутки после смены темы."""
    try:
        from PySide6.QtWidgets import QApplication, QScrollArea
        app = QApplication.instance()
        if app is None:
            return
        for w in app.allWidgets():
            if isinstance(w, QScrollArea):
                try:
                    paint_scroll_viewport(w)
                except RuntimeError:
                    continue
    except RuntimeError:  # noqa: BLE001 — что-то уже удалено
        pass


def pad_below_titlebar(root, top: int) -> None:
    """Сдвинуть контент экранов ниже системного заголовка, чтобы шапка
    ничего не перекрывала. Вызывать после show(), когда высота известна."""
    from PySide6.QtWidgets import QScrollArea
    for sa in root.findChildren(QScrollArea):
        inner = sa.widget()
        lay = inner.layout() if inner is not None else None
        if lay is None:
            continue
        m = lay.contentsMargins()
        if m.top() < top:
            lay.setContentsMargins(m.left(), top, m.right(), m.bottom())


def wrap_in_scroll(widget) -> None:
    """Контент экрана в скролл: окно свободно ресайзится,
    таблицы/списки скроллятся внутри себя и страницей."""
    from PySide6.QtWidgets import QScrollArea, QVBoxLayout
    inner = QWidget()
    inner.setObjectName("scrollInner")
    inner.setLayout(widget.layout())
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setWidget(inner)
    paint_scroll_viewport(scroll)
    root = QVBoxLayout(widget)
    root.setContentsMargins(0, 0, 0, 0)
    root.addWidget(scroll)
