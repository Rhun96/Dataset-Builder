"""Диалог импорта готового набора: колонка -> роль, остальное угадываем."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from core.roles import all_roles_for_ui, validate_mapping
from core.source_reader import read_preview
from ui.sources_screen import guess_role


class ImportBuildDialog(QDialog):
    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Импорт набора: {Path(path).name}")
        self.resize(560, 380)
        self._headers: list[str] = []
        self._combos: dict[str, QComboBox] = {}
        layout = QVBoxLayout(self)
        try:
            prev = read_preview(path, max_rows=3)
        except Exception as e:  # noqa: BLE001
            prev = None
            self._error = str(e)
        else:
            self._error = ""
        if prev is None:
            from PySide6.QtWidgets import QLabel
            layout.addWidget(QLabel(f"не читается: {self._error}"))
        else:
            self._headers = prev.headers
            tbl = QTableWidget(len(prev.headers), 3)
            tbl.setHorizontalHeaderLabels(["Колонка", "Роль", "Пример"])
            # Явные цвета: диалог системный (светлый) при любой теме приложения.
            tbl.setStyleSheet(
                "QTableWidget { background: white; color: #1B1B1B; "
                "gridline-color: #D5DDE5; }"
                "QTableWidget::item { color: #1B1B1B; }"
                "QHeaderView::section { background: #E8EDF3; color: #1B1B1B; "
                "border: 1px solid #D5DDE5; padding: 4px; }")
            tbl.horizontalHeader().setStretchLastSection(True)
            roles = all_roles_for_ui()
            for r, h in enumerate(prev.headers):
                tbl.setItem(r, 0, QTableWidgetItem(h))
                combo = QComboBox()
                for code, label in roles:
                    combo.addItem(label, code)
                combo.setCurrentIndex(next(
                    (i for i in range(combo.count())
                     if combo.itemData(i) == guess_role(h, [])), 0))
                tbl.setCellWidget(r, 1, combo)
                self._combos[h] = combo
                ex = next((row.get(h, "") for row in prev.rows if row.get(h, "")), "")
                tbl.setItem(r, 2, QTableWidgetItem(str(ex)[:120]))
            tbl.horizontalScrollBar().setValue(0)
            layout.addWidget(tbl)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _on_ok(self):
        try:
            self.mapping = self.current_mapping()
        except ValueError as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Маппинг", str(e))
            return
        self.accept()

    def current_mapping(self) -> dict[str, str]:
        out = {}
        for h, combo in self._combos.items():
            code = combo.currentData()
            if code and code != "__custom__" and code != "ignore":
                out[h] = code
            elif code == "ignore":
                out[h] = "ignore"
        plain = {k: v for k, v in out.items() if v != "ignore"}
        validate_mapping(plain)
        return out
