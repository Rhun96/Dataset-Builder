"""Экран «Изменения БЗ»: два состояния документа -> кандидаты на перепроверку."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import PushButton, TableWidget, TextEdit

from core.knowledge_diff_service import diff_sections, render_html
from core.knowledge_reader import read_kb
from core.related_cases_service import related_for_change, transfer_to_build
from storage.database import connect, save_kb_snapshot
from ui.theme import polish_table, set_status, wrap_in_scroll

TYPE_RU = {"changed": "изменён", "added": "добавлен",
           "removed": "удалён", "unchanged": "без изменений"}


class KnowledgeScreen(QWidget):
    def __init__(self, db_path: str | Path):
        super().__init__()
        self._db_path = str(db_path)
        self._old: list[dict] = []
        self._new: list[dict] = []
        self._doc = ""
        self._changes: list[dict] = []
        self._related: list[dict] = []
        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        self.btn_old = PushButton("Старое состояние…")
        self.btn_old.clicked.connect(lambda: self.pick("old"))
        self.btn_new = PushButton("Новое состояние…")
        self.btn_new.clicked.connect(lambda: self.pick("new"))
        self.btn_diff = PushButton("Сравнить")
        self.btn_diff.clicked.connect(self.compare)
        self.lbl_files = QLabel("выбери старое и новое состояние одного документа")
        self.lbl_files.setWordWrap(True)
        row.addWidget(self.btn_old)
        row.addWidget(self.btn_new)
        row.addWidget(self.btn_diff)
        row.addWidget(self.lbl_files, 1)
        layout.addLayout(row)

        layout.addWidget(QLabel("Изменения разделов:"))
        self.tbl_changes = TableWidget()
        self.tbl_changes.setColumnCount(3)
        self.tbl_changes.setHorizontalHeaderLabels(["Раздел", "Тип", "Сходство"])
        polish_table(self.tbl_changes)
        self.tbl_changes.itemClicked.connect(lambda *_: self.on_change_selected())
        layout.addWidget(self.tbl_changes, 1)
        layout.addWidget(QLabel("Что изменилось:"))
        self.txt_detail = TextEdit()
        self.txt_detail.setReadOnly(True)
        self.txt_detail.setMaximumHeight(150)
        layout.addWidget(self.txt_detail)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Кандидаты на перепроверку (повод посмотреть, не приговор):"))
        self.btn_all = PushButton("Найти по всем изменениям")
        self.btn_all.clicked.connect(lambda: self.find_related(all_changes=True))
        self.btn_tobuild = PushButton("В сборку")
        self.btn_tobuild.clicked.connect(self.to_build)
        row2.addWidget(self.btn_all)
        row2.addWidget(self.btn_tobuild)
        layout.addLayout(row2)
        self.tbl_rel = TableWidget()
        self.tbl_rel.setColumnCount(4)
        self.tbl_rel.setHorizontalHeaderLabels(["✓", "ID выборки", "Текст", "Почему"])
        polish_table(self.tbl_rel)
        layout.addWidget(self.tbl_rel, 2)
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)
        wrap_in_scroll(self)

    def pick(self, which: str):
        path, _ = QFileDialog.getOpenFileName(
            self, "Состояние документа", "", "Документы (*.txt *.md *.html *.docx)")
        if not path:
            return
        try:
            data = read_kb(path)
        except ValueError as e:
            QMessageBox.warning(self, "Формат", str(e))
            return
        if which == "old":
            self._old = data["sections"]
            self._old_path = path
        else:
            self._new = data["sections"]
            self._new_path = path
        self.lbl_files.setText(
            f"старое: {len(self._old)} разделов; новое: {len(self._new)} разделов")

    def compare(self):
        if not self._old or not self._new:
            QMessageBox.information(self, "Файлы", "Выбери оба состояния.")
            return
        doc = Path(getattr(self, "_new_path", "doc")).stem
        self._doc = doc
        try:
            con = connect(self._db_path)
            try:
                save_kb_snapshot(con, doc + " (старое)", self._old_path, self._old)
                save_kb_snapshot(con, doc + " (новое)", self._new_path, self._new)
            finally:
                con.close()
        except Exception as e:  # noqa: BLE001
            set_status(self.lbl_status, f"снимки не сохранены: {e}", "warn")
        res = diff_sections(self._old, self._new)
        self._changes = [c for c in res["changes"] if c["type"] != "unchanged"]
        s = res["summary"]
        self.tbl_changes.setRowCount(len(self._changes))
        for r, c in enumerate(self._changes):
            self.tbl_changes.setItem(r, 0, QTableWidgetItem(c["heading"][:120]))
            self.tbl_changes.setItem(r, 1, QTableWidgetItem(TYPE_RU[c["type"]]))
            self.tbl_changes.setItem(r, 2, QTableWidgetItem(str(c["similarity"])))
        self.lbl_status.setText(
            f"{doc}: изменено {s['changed']}, добавлено {s['added']}, "
            f"удалено {s['removed']}, без изменений {s['unchanged']}. "
            f"Выбери раздел — подберу кандидатов.")
        self._related = []
        self.tbl_rel.setRowCount(0)
        if self._changes:
            self.tbl_changes.selectRow(0)
            self.show_detail()

    def _current_change(self) -> dict | None:
        r = self.tbl_changes.currentRow()
        if 0 <= r < len(self._changes):
            return self._changes[r]
        return None

    def show_detail(self):
        change = self._current_change()
        self.txt_detail.setHtml(render_html(change) if change else "")

    def on_change_selected(self):
        self.show_detail()
        self.find_related()

    def find_related(self, all_changes: bool = False):
        targets = self._changes if all_changes else [self._current_change()]
        targets = [t for t in targets if t]
        if not targets:
            self.lbl_status.setText("выбери раздел в таблице изменений.")
            return
        try:
            con = connect(self._db_path)
            try:
                found: dict[int, dict] = {}
                for t in targets:
                    for rel in related_for_change(con, t, self._doc):
                        if rel["candidate_id"] not in found:
                            found[rel["candidate_id"]] = {
                                **rel, "why": f"{t['heading'][:60]} ({rel['method']})"}
                names = {r["id"]: r["main_raw"] for r in con.execute(
                    "SELECT id, main_raw FROM candidate").fetchall()}
                exts = {r["candidate_id"]: r["value_raw"] for r in con.execute(
                    "SELECT candidate_id, value_raw FROM candidate_dim "
                    "WHERE dim='ext_id'").fetchall()}
            finally:
                con.close()
        except Exception as e:  # noqa: BLE001
            set_status(self.lbl_status, f"ошибка: {e}", "block")
            return
        self._related = list(found.values())
        self.tbl_rel.setRowCount(len(self._related))
        for r, rel in enumerate(self._related):
            box = QTableWidgetItem()
            box.setFlags(box.flags() | Qt.ItemIsUserCheckable)
            box.setCheckState(Qt.Checked)
            self.tbl_rel.setItem(r, 0, box)
            eid = exts.get(rel["candidate_id"], "") or f"auto-{rel['candidate_id']}"
            self.tbl_rel.setItem(r, 1, QTableWidgetItem(eid))
            txt = str(names.get(rel["candidate_id"], ""))[:200]
            self.tbl_rel.setItem(r, 2, QTableWidgetItem(txt))
            self.tbl_rel.setItem(r, 3, QTableWidgetItem(
                f"{rel['method']}: {rel['detail']}"[:200]))
        self.lbl_status.setText(
            f"кандидатов: {len(self._related)} — сними галочки с лишних и жми «В сборку».")

    def to_build(self):
        picks = []
        for r, rel in enumerate(self._related):
            box = self.tbl_rel.item(r, 0)
            if box is not None and box.checkState() == Qt.Checked:
                picks.append(rel)
        if not picks:
            QMessageBox.information(self, "Выбор", "Отметь хотя бы один кейс.")
            return
        try:
            con = connect(self._db_path)
            try:
                bid = transfer_to_build(con, f"На перепроверку {self._doc}", picks)
            finally:
                con.close()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Ошибка", str(e))
            return
        self.lbl_status.setText(
            f"сборка #{bid} из {len(picks)} кейсов — смотри вкладку «Сборка и экспорт».")
