"""Точка входа: Dataset Builder v2, навигация Fluent."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import FluentWindow

from ui.builds_screen import BuildsScreen
from ui.knowledge_screen import KnowledgeScreen
from ui.profile_screen import ProfileScreen
from ui.requirements_screen import RequirementsScreen
from ui.settings_screen import SettingsScreen
from ui.sources_screen import SourcesScreen
from ui.theme import apply_theme, apply_window_bg, pad_below_titlebar, saved_native_frame


def default_db_path() -> Path:
    docs = Path.home() / "Documents" / "DatasetBuilderV2"
    docs.mkdir(parents=True, exist_ok=True)
    return docs / "workspace.sqlite"


class MainWindow(FluentWindow):
    def __init__(self, db: str, native_frame: bool = False):
        super().__init__()
        self.setWindowTitle("Dataset Builder v2")
        apply_window_bg(self)
        if native_frame:
            # Запасной вариант: системный заголовок с гарантированными
            # кнопками Свернуть/Развернуть/Закрыть.
            from PySide6.QtCore import Qt
            self.setWindowFlags(
                Qt.Window
                | Qt.WindowTitleHint
                | Qt.WindowSystemMenuHint
                | Qt.WindowMinimizeButtonHint
                | Qt.WindowMaximizeButtonHint
                | Qt.WindowCloseButtonHint
            )
            self.titleBar.hide()
        for widget, icon, text in (
            (SourcesScreen(db), FIF.DOCUMENT, "Источники"),
            (ProfileScreen(db), FIF.VIEW, "1 · Профиль пула"),
            (RequirementsScreen(db), FIF.FILTER, "2 · Требования"),
            (BuildsScreen(db), FIF.SAVE, "3 · Сборка и экспорт"),
            (KnowledgeScreen(db), FIF.SEARCH, "Изменения БЗ"),
        ):
            widget.setObjectName(text)
            self.addSubInterface(widget, icon, text)
        settings = SettingsScreen(db, QApplication.instance())
        settings.setObjectName("Настройки")
        self.addSubInterface(settings, FIF.SETTING, "Настройки")


def center_on_screen(win) -> None:
    """Окно целиком на экране: иначе при разворачивании кнопки уезжают."""
    avail = win.screen().availableGeometry() if win.screen() else None
    w = min(1280, int(avail.width() * 0.94)) if avail else 1200
    h = min(800, int(avail.height() * 0.92)) if avail else 720
    win.resize(w, h)
    if avail:
        win.move(avail.center() - win.rect().center())


def main() -> int:
    from PySide6.QtCore import Qt
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("Dataset Builder v2")
    apply_theme(app)
    win = MainWindow(str(default_db_path()), native_frame=saved_native_frame())
    center_on_screen(win)
    win.show()
    win.titleBar.raise_()
    app.processEvents()
    try:
        pad_below_titlebar(win, win.titleBar.height() + 8)
    except Exception:  # noqa: BLE001 — отступ не критичен для запуска
        pass
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
