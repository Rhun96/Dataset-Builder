"""Диалог выбора источников в пул: галочки, счётчики по каждому."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from storage.database import connect, list_sources, set_source_enabled


class PoolDialog(QDialog):
    def __init__(self, db_path: str, parent=None):
        super().__init__(parent)
        self._db_path = str(db_path)
        self.setWindowTitle("Источники в пуле")
        self.resize(460, 380)
        layout = QVBoxLayout(self)
        self.lst = QListWidget()
        layout.addWidget(self.lst)
        try:
            con = connect(self._db_path)
            try:
                sources = list_sources(con)
            finally:
                con.close()
        except Exception:  # noqa: BLE001
            sources = []
        for s in sources:
            item = QListWidgetItem(
                f"{Path(s['path']).name} — пригодных "
                f"{s.get('usable_rows', 0)}/{s.get('total_rows', 0)}")
            item.setData(256, s["id"])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if s.get("in_pool", 1) else Qt.Unchecked)
            self.lst.addItem(item)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _on_ok(self):
        try:
            con = connect(self._db_path)
            try:
                for r in range(self.lst.count()):
                    item = self.lst.item(r)
                    set_source_enabled(con, int(item.data(256)),
                                       item.checkState() == Qt.Checked)
            finally:
                con.close()
        except Exception:  # noqa: BLE001
            pass
        self.accept()


def pool_label(db_path: str) -> str:
    """Коротко о пуле для кнопок: «Все (2)» или «Выбрано 1 из 2»."""
    try:
        con = connect(db_path)
        try:
            srcs = list_sources(con)
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return "Источники: —"
    on = sum(1 for s in srcs if s.get("in_pool", 1))
    if on == len(srcs):
        return f"Все ({len(srcs)})"
    return f"Выбрано {on} из {len(srcs)}"
