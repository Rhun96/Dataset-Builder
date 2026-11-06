"""Экран «Настройки»: тема оформления и рабочая папка."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import CheckBox, ComboBox, PushButton

from ui.theme import (
    apply_theme,
    save_native_frame,
    save_theme,
    saved_native_frame,
    saved_theme,
    wrap_in_scroll,
)

THEME_NAMES = [("light", "Светлая"), ("dark", "Тёмная"), ("auto", "Системная")]


class SettingsScreen(QWidget):
    def __init__(self, db_path: str | Path, app=None):
        super().__init__()
        self._db_path = str(db_path)
        self._app = app
        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Тема оформления:"))
        self.cmb_theme = ComboBox()
        for code, label in THEME_NAMES:
            self.cmb_theme.addItem(label, userData=code)
        idx = next((i for i, (c, _) in enumerate(THEME_NAMES) if c == saved_theme()), 0)
        self.cmb_theme.setCurrentIndex(idx)
        self.cmb_theme.currentIndexChanged.connect(self.change_theme)
        row.addWidget(self.cmb_theme, 1)
        layout.addLayout(row)
        self.lbl_theme = QLabel("применяется сразу и запоминается")
        self.lbl_theme.setProperty("hint", True)
        layout.addWidget(self.lbl_theme)

        layout.addWidget(QLabel("Окно:"))
        self.cb_native = CheckBox("Классический заголовок окна")
        self.cb_native.setChecked(saved_native_frame())
        self.cb_native.stateChanged.connect(self.change_frame)
        layout.addWidget(self.cb_native)
        self.lbl_frame = QLabel("если не видны кнопки Свернуть/Развернуть/Закрыть. "
                                "Применяется после перезапуска.")
        self.lbl_frame.setProperty("hint", True)
        self.lbl_frame.setWordWrap(True)
        layout.addWidget(self.lbl_frame)

        layout.addWidget(QLabel("Рабочая папка:"))
        self.lbl_ws = QLabel(str(Path(db_path).parent))
        self.lbl_ws.setWordWrap(True)
        layout.addWidget(self.lbl_ws)
        row2 = QHBoxLayout()
        self.btn_open = PushButton("Открыть рабочую папку")
        self.btn_open.clicked.connect(self.open_folder)
        row2.addWidget(self.btn_open)
        self.btn_backup = PushButton("Сделать резервную копию")
        self.btn_backup.clicked.connect(self.make_backup)
        self.lbl_backup = QLabel("")
        self.lbl_backup.setWordWrap(True)
        self.lbl_backup.setProperty("hint", True)
        row2.addWidget(self.btn_backup)
        layout.addLayout(row2)
        layout.addWidget(self.lbl_backup)
        layout.addStretch(1)
        wrap_in_scroll(self)

    def change_theme(self):
        mode = self.cmb_theme.currentData() or "light"
        save_theme(mode)
        if self._app is not None:
            apply_theme(self._app)
        from ui.theme import refresh_scroll_bgs
        refresh_scroll_bgs()

    def change_frame(self):
        save_native_frame(self.cb_native.isChecked())

    def make_backup(self):
        from storage.database import backup_now
        try:
            path = backup_now(self._db_path)
        except ValueError as e:
            self.lbl_backup.setText(str(e))
            return
        except Exception as e:  # noqa: BLE001
            self.lbl_backup.setText(f"ошибка: {e}")
            return
        self.lbl_backup.setText(f"копия: {path}")

    def open_folder(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._db_path).parent)))
