"""Экран «Источники»: файл -> роли колонок -> загрузка в пул."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CheckBox,
    ComboBox,
    ListWidget,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    SpinBox,
    TableWidget,
)

from core.roles import all_roles_for_ui, validate_mapping
from core.source_reader import (
    detect_format,
    list_sheets_ods,
    list_sheets_xlsx,
    read_preview,
)
from storage.database import connect, list_sources
from ui.theme import polish_table, set_status, wrap_in_scroll
from ui.workers import ImportWorker


def guess_role(column: str, sample: list[str]) -> str:
    import re as _re
    name = (column or "").strip().lower()
    if "запрос" in name or "вопрос" in name or name in ("text", "текст", "query", "prompt"):
        return "main_text"
    if name in ("id", "ид", "идентификатор", "номер"):
        return "ext_id"
    if "категор" in name or "групп" in name:
        return "group"
    if "сложн" in name:
        return "custom:Сложность"
    if "ответ" in name or "результат" in name:
        return "response_text"
    if "тема" in name:
        return "topic"
    if "источник" in name or name == "source":
        return "kb_ref"
    # имя ни о чём не говорит — смотрим на примеры: короткие уникальные
    # значения без пробелов похожи на идентификаторы, а не на мусор
    vals = [str(v or "").strip() for v in (sample or []) if str(v or "").strip()]
    if len(vals) >= 2 and len(set(vals)) == len(vals):
        avg_len = sum(len(v) for v in vals) / len(vals)
        if avg_len <= 40 and all(_re.fullmatch(r"[\w./:-]+", v) for v in vals):
            return "ext_id"
    return "extra"


class SourcesScreen(QWidget):
    def __init__(self, db_path: str | Path):
        super().__init__()
        self._db_path = str(db_path)
        self._current_file: str | None = None
        self._headers: list[str] = []
        self._combos: dict[str, ComboBox] = {}
        self._worker: ImportWorker | None = None

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.btn_add = PushButton("Добавить файл…")
        self.btn_add.clicked.connect(self.pick_file)
        self.btn_demo = PushButton("Демо-пул")
        self.btn_demo.setToolTip("Создать учебный файл без своих данных")
        self.btn_demo.clicked.connect(self.make_demo_pool)
        self.btn_reload = PushButton("Обновить")
        self.btn_reload.clicked.connect(self.refresh_sources)
        self.btn_del_src = PushButton("Удалить")
        self.btn_del_src.setToolTip("Убрать источник из пула (файл на диске не трогаем)")
        self.btn_del_src.clicked.connect(self.delete_selected)
        self.lbl_ws = QLabel(f"Рабочая папка: {Path(db_path).parent}")
        self.lbl_ws.setProperty("hint", True)
        top.addWidget(self.btn_add)
        top.addWidget(self.btn_demo)
        top.addWidget(self.btn_reload)
        top.addWidget(self.btn_del_src)
        top.addWidget(self.lbl_ws, 1)
        layout.addLayout(top)

        filerow = QHBoxLayout()
        self.chk_fileopts = CheckBox("Настроить параметры файла")
        self.chk_fileopts.setToolTip("Лист, строка заголовка, кодировка, разделитель. "
                                     "По умолчанию всё определяется само — открывай при проблемах.")
        self.chk_fileopts.setChecked(False)
        self.chk_fileopts.toggled.connect(self._toggle_fileopts)
        filerow.addWidget(self.chk_fileopts)
        filerow.addStretch(1)
        layout.addLayout(filerow)

        self.file_opts = QWidget()
        params = QHBoxLayout(self.file_opts)
        params.setContentsMargins(0, 0, 0, 0)
        params.addWidget(QLabel("Лист:"))
        self.cmb_sheet = ComboBox()
        self.cmb_sheet.setEnabled(False)
        self.cmb_sheet.currentIndexChanged.connect(lambda *_: self.reopen())
        params.addWidget(self.cmb_sheet)
        params.addWidget(QLabel("Строка заголовка:"))
        self.spin_header = SpinBox()
        self.spin_header.setRange(0, 20)
        self.spin_header.setToolTip("0 — первая строка файла")
        self.spin_header.valueChanged.connect(lambda *_: self.reopen())
        params.addWidget(self.spin_header)
        params.addWidget(QLabel("Кодировка:"))
        self.cmb_encoding = ComboBox()
        for enc in ("utf-8-sig", "utf-8", "cp1251", "koi8-r"):
            self.cmb_encoding.addItem(enc, userData=enc)
        self.cmb_encoding.currentIndexChanged.connect(lambda *_: self.reopen())
        params.addWidget(self.cmb_encoding)
        params.addWidget(QLabel("Разделитель:"))
        self.cmb_delim = ComboBox()
        for code, label in (("auto", "авто"), (";", ";"), (",", ","), ("\t", "таб")):
            self.cmb_delim.addItem(label, userData=code)
        self.cmb_delim.currentIndexChanged.connect(lambda *_: self.reopen())
        params.addWidget(self.cmb_delim)
        layout.addWidget(self.file_opts)
        self.file_opts.setVisible(False)

        mid = QHBoxLayout()
        self.lst = ListWidget()
        self.lst.itemClicked.connect(lambda *_: self.open_selected())
        self.lst.itemChanged.connect(self.toggle_selected)
        mid.addWidget(self.lst, 1)

        right = QVBoxLayout()
        right.addWidget(QLabel("Сопоставление колонок ролям:"))
        self.tbl_map = TableWidget()
        self.tbl_map.setColumnCount(3)
        self.tbl_map.setHorizontalHeaderLabels(["Колонка", "Роль", "Пример"])
        polish_table(self.tbl_map)
        header = self.tbl_map.horizontalHeader()
        from PySide6.QtWidgets import QHeaderView
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.tbl_map.setMinimumWidth(520)
        right.addWidget(self.tbl_map, 1)

        row_btns = QHBoxLayout()
        self.btn_custom = PushButton("+ Своя категория")
        self.btn_custom.clicked.connect(self.add_custom_to_selected)
        self.btn_load = PrimaryPushButton("Загрузить в пул")
        self.btn_load.clicked.connect(self.start_import)
        self.btn_cancel = PushButton("Отмена")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_import)
        row_btns.addWidget(self.btn_custom)
        row_btns.addWidget(self.btn_load, 1)
        row_btns.addWidget(self.btn_cancel)
        right.addLayout(row_btns)

        self.progress = ProgressBar()
        self.progress.setMinimum(0)
        self.progress.setMaximum(0)
        self.progress.setVisible(False)
        self.lbl_status = QLabel("Выбери файл слева или добавь новый.")
        right.addWidget(self.progress)
        right.addWidget(self.lbl_status)
        mid.addLayout(right, 2)
        layout.addLayout(mid)
        wrap_in_scroll(self)
        self.refresh_sources()

    # --- список источников ---
    def refresh_sources(self):
        from PySide6.QtCore import Qt
        cur = self.lst.currentItem()
        keep = cur.data(256) if cur is not None else None
        self.lst.blockSignals(True)
        self.lst.clear()
        try:
            con = connect(self._db_path)
            try:
                for s in list_sources(con):
                    self.lst.addItem(f"{Path(s['path']).name}  [{s.get('status','')}] "
                                     f"{s.get('usable_rows',0)}/{s.get('total_rows',0)}")
                    item = self.lst.item(self.lst.count() - 1)
                    item.setData(256, s["id"])
                    item.setData(257, s["path"])
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked if s.get("in_pool", 1) else Qt.Unchecked)
            finally:
                con.close()
        except Exception as e:  # noqa: BLE001
            set_status(self.lbl_status, f"база недоступна: {e}", "block")
        finally:
            self.lst.blockSignals(False)
        if keep is not None:
            for r in range(self.lst.count()):
                try:
                    match = self.lst.item(r).data(256) == keep
                except RuntimeError:  # noqa: BLE001
                    match = False
                if match:
                    self.lst.setCurrentRow(r)
                    break

    def make_demo_pool(self):
        """Учебный файл в рабочую папку + открыть маппинг. Загрузка — кнопкой."""
        import csv as _csv
        from tools.make_demo import ROWS as _DROWS
        demo_path = str(Path(self._db_path).parent / "Демо-пул.csv")
        with open(demo_path, "w", encoding="utf-8-sig", newline="") as f:
            _csv.writer(f, delimiter=";").writerows(_DROWS)
        self._reset_params(demo_path)
        self.open_file(demo_path)
        set_status(self.lbl_status,
                   "демо-файл создан — проверь роли и жми «Загрузить в пул».",
                   "ok")

    def pick_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выбрать файл пула", "",
            "Пул (*.xlsx *.csv *.json *.jsonl *.ods);;Все файлы (*)")
        if path:
            self._reset_params(path)
            self.open_file(path)

    def open_selected(self):
        item = self.lst.currentItem()
        if item and item.data(257):
            self._reset_params(item.data(257))
            self.open_file(item.data(257))

    def toggle_selected(self, item):
        from storage.database import set_source_enabled
        if item is None or item.data(256) is None:
            return
        try:
            self.lst.setCurrentRow(self.lst.row(item))
        except RuntimeError:  # noqa: BLE001
            pass
        from PySide6.QtCore import Qt
        on = item.checkState() == Qt.Checked
        try:
            con = connect(self._db_path)
            try:
                set_source_enabled(con, int(item.data(256)), on)
            finally:
                con.close()
        except Exception as e:  # noqa: BLE001
            set_status(self.lbl_status, f"ошибка: {e}", "block")
            return
        self.lbl_status.setText(
            f"источник {'в пуле' if on else 'исключён из пула'} — "
            f"отбор, профиль и покрытие считают по включённым.")

    def delete_selected(self):
        from storage.database import delete_source
        item = self.lst.currentItem()
        if (item is None or item.data(256) is None) and self._current_file:
            for r in range(self.lst.count()):
                try:
                    match = self.lst.item(r).data(257) == self._current_file
                except RuntimeError:  # noqa: BLE001
                    match = False
                if match:
                    self.lst.setCurrentRow(r)
                    item = self.lst.item(r)
                    break
        if item is None or item.data(256) is None:
            set_status(self.lbl_status, "выбери источник слева для удаления.", "warn")
            return
        sid = int(item.data(256))
        name = Path(item.data(257) or f"id {sid}").name
        go = QMessageBox.question(
            self, "Удалить",
            f"Убрать «{name}» из пула?\nФайл на диске не трогаем, из базы записи уйдут.",
            QMessageBox.Yes | QMessageBox.No)
        if go != QMessageBox.Yes:
            return
        try:
            con = connect(self._db_path)
            try:
                delete_source(con, sid)
            finally:
                con.close()
        except ValueError as e:
            QMessageBox.warning(self, "Нельзя удалить", str(e))
            return
        except Exception as e:  # noqa: BLE001
            set_status(self.lbl_status, f"ошибка: {e}", "block")
            return
        if self._current_file and item.data(257) == self._current_file:
            self._current_file = None
            self.tbl_map.setRowCount(0)
        self.refresh_sources()
        set_status(self.lbl_status, f"«{name}» удалён из пула.", "ok")

    def _toggle_fileopts(self):
        self.file_opts.setVisible(self.chk_fileopts.isChecked())

    def _reset_params(self, path: str):
        fmt = detect_format(path)
        self.cmb_sheet.blockSignals(True)
        self.cmb_sheet.clear()
        if fmt in ("xlsx", "ods"):
            try:
                sheets = list_sheets_xlsx(path) if fmt == "xlsx" else list_sheets_ods(path)
            except ValueError:
                sheets = []
            for s in sheets:
                self.cmb_sheet.addItem(s, userData=s)
            self.cmb_sheet.setEnabled(bool(sheets))
        else:
            self.cmb_sheet.setEnabled(False)
        self.cmb_sheet.blockSignals(False)
        self.spin_header.blockSignals(True)
        self.spin_header.setValue(0)
        self.spin_header.blockSignals(False)

    def _read_kwargs(self) -> dict:
        kw: dict = {"header_row": self.spin_header.value(),
                    "encoding": self.cmb_encoding.currentData() or "utf-8-sig",
                    "delimiter": self.cmb_delim.currentData() or "auto"}
        if self.cmb_sheet.isEnabled() and self.cmb_sheet.currentData():
            kw["sheet"] = self.cmb_sheet.currentData()
        return kw

    def reopen(self):
        if self._current_file:
            self.open_file(self._current_file)

    # --- маппинг ---
    def open_file(self, path: str):
        self._current_file = path
        try:
            prev = read_preview(path, max_rows=5, **self._read_kwargs())
        except Exception as e:  # noqa: BLE001
            set_status(self.lbl_status, f"не читается: {e}", "block")
            return
        self._headers = prev.headers
        self._combos = {}
        self.tbl_map.setRowCount(len(prev.headers))
        roles = all_roles_for_ui()
        for r, h in enumerate(prev.headers):
            self.tbl_map.setItem(r, 0, QTableWidgetItem(h))
            combo = ComboBox()
            for code, label in roles:
                combo.addItem(label, userData=code)
            combo.addItem("Своя категория…", userData="__custom__")
            guessed = guess_role(h, [row.get(h, "") for row in prev.rows])
            idx = next((i for i in range(combo.count())
                        if combo.itemData(i) == guessed), 0)
            # своя угаданная — добавим пункт явно
            if guessed.startswith("custom:"):
                combo.insertItem(combo.count() - 1, guessed[7:], userData=guessed)
                idx = combo.count() - 2
            combo.setCurrentIndex(idx)
            combo.currentIndexChanged.connect(self._combo_changed)
            self._combos[h] = combo
            self.tbl_map.setCellWidget(r, 1, combo)
            ex = next((row.get(h, "") for row in prev.rows if row.get(h, "")), "")
            self.tbl_map.setItem(r, 2, QTableWidgetItem(str(ex)[:120]))
        self.lbl_status.setText(f"{Path(path).name}: {len(prev.headers)} колонок, "
                                f"проверь роли и жми «Загрузить в пул».")
        self.refresh_sources()

    def _add_custom_everywhere(self, label: str, select_in=None):
        """Своя категория — сразу во все списки ролей, не разовая акция."""
        code = f"custom:{label}"
        for combo in self._combos.values():
            if combo.findData(code) < 0:
                combo.insertItem(combo.count() - 1, label, userData=code)
        if select_in is not None:
            select_in.setCurrentIndex(max(0, select_in.findData(code)))

    def _combo_changed(self):
        combo = self.sender()
        if isinstance(combo, ComboBox) and combo.currentData() == "__custom__":
            name, ok = QInputDialog.getText(self, "Своя категория", "Название:")
            if ok and name and name.strip():
                self._add_custom_everywhere(name.strip()[:64], select_in=combo)
            else:
                combo.setCurrentIndex(0)

    def add_custom_to_selected(self):
        r = self.tbl_map.currentRow()
        if r < 0 or r >= len(self._headers):
            self.lbl_status.setText("выбери строку колонки в таблице.")
            return
        name, ok = QInputDialog.getText(self, "Своя категория", "Название:")
        if ok and name and name.strip():
            self._add_custom_everywhere(name.strip()[:64],
                                        select_in=self._combos[self._headers[r]])

    def current_mapping(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for h, combo in self._combos.items():
            code = combo.currentData()
            if code and code != "__custom__" and code != "ignore":
                out[h] = code
            elif code == "ignore":
                out[h] = "ignore"
        # validate_mapping выкинет ignore? нет — проверим отдельно
        plain = {k: v for k, v in out.items() if v != "ignore"}
        validate_mapping(plain)
        return out

    # --- загрузка ---
    def start_import(self):
        if not self._current_file:
            self.lbl_status.setText("сначала выбери файл.")
            return
        try:
            mapping = self.current_mapping()
        except ValueError as e:
            self.lbl_status.setText(str(e))
            return
        # ignore-колонки не грузим как измерения, но для пула они не нужны вовсе
        mapping = {k: v for k, v in mapping.items() if v != "ignore"}
        self.btn_load.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress.setVisible(True)
        self.lbl_status.setText("загрузка…")
        self._worker = ImportWorker(self._db_path, self._current_file, mapping,
                                      self._read_kwargs())
        self._worker.progressed.connect(lambda n: self.lbl_status.setText(f"загружено {n}…"))
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_fail)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def cancel_import(self):
        if self._worker is not None:
            self._worker.request_cancel()
            self.lbl_status.setText("отмена…")

    def _on_done(self, res: dict):
        set_status(self.lbl_status,
                   f"готово: пригодных {res.get('usable')} из {res.get('rows_seen')}, "
                   f"пропущено пустых {res.get('skipped_empty')}.", "ok")
        self.refresh_sources()

    def _on_fail(self, msg: str):
        if "отмен" in msg.lower():
            set_status(self.lbl_status, "отменено, пул источника очищен частично.", "warn")
        else:
            set_status(self.lbl_status, f"ошибка: {msg}", "block")

    def _on_finished(self):
        self.btn_load.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress.setVisible(False)
        self._worker = None
