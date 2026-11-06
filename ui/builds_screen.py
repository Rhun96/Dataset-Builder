"""Экран «Сборка и экспорт»: состав, предпроверки, файловый пакет."""

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
    PushButton,
    SpinBox,
    TableWidget,
)

from core.build_manifest import _profile_from_json, build_manifest
from core.compare_service import compare_builds
from core.precheck_service import precheck
from core.replace_service import replace_items
from core.variant_service import generate_variants, summarize
from export.package_exporter import export_package
from storage.database import (
    connect,
    delete_build,
    list_builds,
    save_build,
    set_pinned,
)
from ui.theme import polish_table, set_status, wrap_in_scroll

STATUS_RU = {"ready": "Готово к экспорту",
             "warnings": "Экспорт возможен с предупреждениями",
             "blocked": "Экспорт заблокирован"}
LEVEL_RU = {"ok": "ок", "warn": "предупреждение", "block": "блок"}


class BuildsScreen(QWidget):
    def __init__(self, db_path: str | Path):
        super().__init__()
        self._db_path = str(db_path)
        self._build_id: int | None = None
        self._item_cids: list[int] = []
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.btn_refresh = PushButton("Обновить")
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_delete = PushButton("Удалить сборку")
        self.btn_delete.clicked.connect(lambda: self.delete_selected(True))
        self.btn_import = PushButton("Импорт набора…")
        self.btn_import.clicked.connect(self.import_external)
        top.addWidget(self.btn_refresh)
        top.addWidget(self.btn_delete)
        top.addWidget(self.btn_import)
        self.lbl_sum = QLabel("выбери сборку слева")
        self.lbl_sum.setWordWrap(True)
        top.addWidget(self.lbl_sum, 1)
        layout.addLayout(top)

        mid = QHBoxLayout()
        self.lst = ListWidget()
        self.lst.itemClicked.connect(lambda *_: self.open_selected())
        self.lst.currentItemChanged.connect(lambda *_: self.open_selected())
        mid.addWidget(self.lst, 1)

        right = QVBoxLayout()
        right.addWidget(QLabel("Состав (ID, текст, причина):"))
        self.tbl_items = TableWidget()
        self.tbl_items.setColumnCount(3)
        self.tbl_items.setHorizontalHeaderLabels(["ID выборки", "Текст", "Причина"])
        polish_table(self.tbl_items)
        right.addWidget(self.tbl_items, 2)
        row = QHBoxLayout()
        self.btn_pin = PushButton("Закрепить выбранные")
        self.btn_pin.clicked.connect(self.pin_selected)
        self.btn_replace = PushButton("Заменить (та же ячейка)")
        self.btn_replace.clicked.connect(self.replace_selected)
        self.btn_exclude = PushButton("Исключить (новой ревизией)")
        self.btn_exclude.clicked.connect(self.exclude_selected)
        row.addWidget(self.btn_pin)
        row.addWidget(self.btn_replace)
        row.addWidget(self.btn_exclude)
        right.addLayout(row)
        cmp_row = QHBoxLayout()
        cmp_row.addWidget(QLabel("Сравнить с:"))
        self.cmb_compare = ComboBox()
        self.btn_compare = PushButton("Сравнить")
        self.btn_compare.clicked.connect(self.compare_current)
        cmp_row.addWidget(self.cmb_compare, 1)
        cmp_row.addWidget(self.btn_compare)
        right.addLayout(cmp_row)
        var_row = QHBoxLayout()
        var_row.addWidget(QLabel("Вариантов:"))
        self.spin_variants = SpinBox()
        self.spin_variants.setRange(2, 5)
        self.spin_variants.setValue(3)
        self.btn_variants = PushButton("Собрать варианты")
        self.btn_variants.clicked.connect(self.make_variants)
        var_row.addWidget(self.spin_variants)
        var_row.addWidget(self.btn_variants, 1)
        right.addLayout(var_row)
        self.lbl_cmp = QLabel("")
        self.lbl_cmp.setWordWrap(True)
        right.addWidget(self.lbl_cmp)
        right.addWidget(QLabel("Предпроверки:"))
        self.tbl_checks = TableWidget()
        self.tbl_checks.setColumnCount(2)
        self.tbl_checks.setHorizontalHeaderLabels(["Проверка", "Итог"])
        polish_table(self.tbl_checks)
        right.addWidget(self.tbl_checks, 1)
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        right.addWidget(self.lbl_status)

        exp = QHBoxLayout()
        self.cb_xlsx = CheckBox("XLSX")
        self.cb_xlsx.setChecked(True)
        self.cb_csv = CheckBox("CSV")
        self.cb_jsonl = CheckBox("JSONL")
        self.cb_jsonl.setChecked(True)
        self.btn_dir = PushButton("Папка…")
        self.btn_dir.clicked.connect(self.pick_dir)
        self.lbl_dir = QLabel(str(Path.home() / "Documents" / "DatasetBuilderV2" / "exports"))
        self.btn_export = PrimaryPushButton("Выгрузить пакет")
        self.btn_export.clicked.connect(self.do_export)
        exp.addWidget(self.cb_xlsx)
        exp.addWidget(self.cb_csv)
        exp.addWidget(self.cb_jsonl)
        exp.addWidget(self.btn_dir)
        exp.addWidget(self.btn_export)
        right.addLayout(exp)
        right.addWidget(self.lbl_dir)
        self.lbl_out = QLabel("")
        self.lbl_out.setWordWrap(True)
        right.addWidget(self.lbl_out)
        mid.addLayout(right, 2)
        layout.addLayout(mid)
        wrap_in_scroll(self)
        self.refresh()

    def refresh(self):
        keep = self._build_id
        self.lst.blockSignals(True)
        self.lst.clear()
        try:
            con = connect(self._db_path)
            try:
                builds = list_builds(con)
            finally:
                con.close()
        except Exception as e:  # noqa: BLE001
            self.lst.blockSignals(False)
            set_status(self.lbl_sum, f"база недоступна: {e}", "block")
            return
        for b in builds:
            self.lst.addItem(f"#{b['id']} {b['name']} — {b['picked']}/{b['target_size']}")
            self.lst.item(self.lst.count() - 1).setData(256, b["id"])
        self.cmb_compare.blockSignals(True)
        self.cmb_compare.clear()
        for b in builds:
            self.cmb_compare.addItem(f"#{b['id']} {b['name']}", userData=b["id"])
        self.cmb_compare.blockSignals(False)
        self.lst.blockSignals(False)
        if not builds:
            self._build_id = None
            self.tbl_items.setRowCount(0)
            self.tbl_checks.setRowCount(0)
            self.lbl_sum.setText("сборок нет — собери на вкладке «Требования».")
            return
        if keep and any(b["id"] == keep for b in builds):
            for r in range(self.lst.count()):
                if self.lst.item(r).data(256) == keep:
                    self.lst.setCurrentRow(r)
                    break
            self.open_build(keep)

    def open_selected(self):
        item = self.lst.currentItem()
        if item:
            self.open_build(int(item.data(256)))

    def import_external(self):
        from core.external_import import import_external
        from ui.import_dialog import ImportBuildDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Готовый набор", "",
            "Набор (*.xlsx *.csv *.json *.jsonl *.ods);;Все файлы (*)")
        if not path:
            return
        dlg = ImportBuildDialog(path, self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        name, ok = QInputDialog.getText(self, "Название", "Название сборки:",
                                       text=Path(path).stem[:80])
        if not ok or not name.strip():
            return
        try:
            con = connect(self._db_path)
            try:
                out = import_external(con, path, dlg.mapping, name.strip())
            finally:
                con.close()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Ошибка", str(e))
            return
        self.refresh()
        self.open_build(out["build_id"])
        set_status(self.lbl_sum,
                   f"импортировано {out['matched']} из {out['total']} "
                   f"(не найдено в пуле: {out['unmatched']}).", "ok")

    def delete_selected(self, confirm: bool = True):
        if self._build_id is None:
            item = self.lst.currentItem()
            if item and item.data(256):
                self.open_build(int(item.data(256)))
            else:
                set_status(self.lbl_sum,
                           "нечего удалять: кликни по сборке слева, чтобы открыть её.",
                           "warn")
                return
        if confirm:
            go = QMessageBox.question(
                self, "Удалить",
                f"Удалить сборку #{self._build_id} вместе с составом?",
                QMessageBox.Yes | QMessageBox.No)
            if go != QMessageBox.Yes:
                return
        try:
            con = connect(self._db_path)
            try:
                out = delete_build(con, self._build_id)
            finally:
                con.close()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Ошибка", str(e))
            return
        self._build_id = None
        self.refresh()
        if self.lst.count():
            # сразу открываем первую оставшуюся — экран не висит в пустоте
            self.lst.setCurrentRow(0)
            self.open_selected()
            msg = f"сборка #{out['deleted']} удалена."
        else:
            self.tbl_items.setRowCount(0)
            self.tbl_checks.setRowCount(0)
            msg = f"сборка #{out['deleted']} удалена."
        if out["referenced_in"]:
            msg += (" Она упомянута в профилях: " + ", ".join(out["referenced_in"])
                    + " — там останутся только id, выборки это не ломает.")
        set_status(self.lbl_sum, msg, "warn")

    def open_build(self, bid: int):
        self._build_id = bid
        try:
            con = connect(self._db_path)
            try:
                m = build_manifest(con, bid)
                pc = precheck(con, bid)
            finally:
                con.close()
        except Exception as e:  # noqa: BLE001
            set_status(self.lbl_sum, f"ошибка: {e}", "block")
            return
        self.lbl_sum.setText(
            f"#{m['build_id']} {m['build_name']}: собрано {m['picked']}/{m['target_size']}, "
            f"вариант {m['variant']}, режим {m['mode']}")
        self.tbl_items.setRowCount(len(m["items"]))
        self._item_cids = [it["internal_id"] for it in m["items"]]
        for r, it in enumerate(m["items"]):
            self.tbl_items.setItem(r, 0, QTableWidgetItem(it["export_id"]))
            self.tbl_items.setItem(r, 1, QTableWidgetItem(""))
            self.tbl_items.setItem(r, 2, QTableWidgetItem(it["reason"]))
        self._fill_texts(m)
        self.tbl_checks.setRowCount(len(pc["checks"]))
        for r, c in enumerate(pc["checks"]):
            self.tbl_checks.setItem(r, 0, QTableWidgetItem(c["message"]))
            self.tbl_checks.setItem(r, 1, QTableWidgetItem(LEVEL_RU[c["level"]]))
        status_kind = {"ready": "ok", "warnings": "warn", "blocked": "block"}[pc["status"]]
        set_status(self.lbl_status, STATUS_RU[pc["status"]], status_kind)
        self.lbl_out.setText("")

    def _fill_texts(self, m: dict):
        try:
            con = connect(self._db_path)
            try:
                rows = {r["id"]: r["main_raw"] for r in con.execute(
                    "SELECT id, main_raw FROM candidate").fetchall()}
            finally:
                con.close()
        except Exception:  # noqa: BLE001
            rows = {}
        for r, it in enumerate(m["items"]):
            txt = str(rows.get(it["internal_id"], ""))[:200]
            self.tbl_items.setItem(r, 1, QTableWidgetItem(txt))

    def _selected_cids(self) -> list[int]:
        rows = sorted({i.row() for i in self.tbl_items.selectedIndexes()})
        return [self._item_cids[r] for r in rows if r < len(self._item_cids)]

    def pin_selected(self):
        cids = self._selected_cids()
        if not cids:
            QMessageBox.information(self, "Выбор", "Выдели строки для закрепления.")
            return
        try:
            con = connect(self._db_path)
            try:
                set_pinned(con, cids)
            finally:
                con.close()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Ошибка", str(e))
            return
        set_status(self.lbl_cmp,
                     f"закреплено {len(cids)}: войдут первыми в следующую сборку.")

    def replace_selected(self):
        if self._build_id is None:
            return
        cids = self._selected_cids()
        if not cids:
            QMessageBox.information(self, "Выбор", "Выдели строки для замены.")
            return
        try:
            con = connect(self._db_path)
            try:
                out = replace_items(con, self._build_id, cids, seed=1)
            finally:
                con.close()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Ошибка", str(e))
            return
        self.refresh()
        self.open_build(out["build_id"])
        if not out["replaced"] and out.get("pool_outside", 1) == 0:
            set_status(self.lbl_cmp,
                       "замен нет: пул выбран целиком — менять не на что. "
                       "Попробуй на частичной сборке (например, 100 из 250).", "warn")
        else:
            set_status(self.lbl_cmp,
                       f"заменено {len(out['replaced'])}, без пары в ячейке "
                       f"{len(out['unreplaced'])} (новая ревизия #{out['build_id']}).")

    def make_variants(self):
        if self._build_id is None:
            QMessageBox.information(self, "Сборка", "Сначала выбери сборку.")
            return
        try:
            import json as _json
            con = connect(self._db_path)
            try:
                b = con.execute("SELECT * FROM build WHERE id=?",
                                (self._build_id,)).fetchone()
                prof = _profile_from_json(_json.loads(b["profile_json"] or "{}"))
                seeds = [prof.seed + k for k in
                         range(1, self.spin_variants.value() + 1)]
                ids = generate_variants(con, self._build_id, seeds)
                rows = [summarize(con, i) for i in ids]
            finally:
                con.close()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Ошибка", str(e))
            return
        self.refresh()
        self.open_build(ids[0])
        set_status(self.lbl_cmp,
                   "варианты (без общего балла — выбирай сам):\n" + "\n".join(
                       f"#{r['id']} вариант {r['seed']}: {r['picked']}/{r['target']}, "
                       f"статус {STATUS_RU[r['status']]}, дублей {r['dup_fp']}, "
                       f"сорванных квот {r['short_quotas']}" for r in rows))

    def compare_current(self):
        if self._build_id is None:
            QMessageBox.information(self, "Сборка", "Сначала выбери сборку.")
            return
        other = self.cmb_compare.currentData()
        if not other or other == self._build_id:
            set_status(self.lbl_cmp, "выбери другую сборку для сравнения.", "warn")
            return
        try:
            con = connect(self._db_path)
            try:
                d = compare_builds(con, other, self._build_id)
            finally:
                con.close()
        except Exception as e:  # noqa: BLE001
            set_status(self.lbl_cmp, f"ошибка: {e}", "block")
            return
        lines = [f"vs #{other}: добавлено {len(d['added'])}, "
                 f"исключено {len(d['removed'])}, сохранено {len(d['kept'])}"]
        for dim, ch in d["coverage_delta"].items():
            lines.append(f"{dim}: было {ch['old']} → стало {ch['new']}")
        if d["sources_old"] != d["sources_new"]:
            lines.append(f"источники: было {d['sources_old']} → стало {d['sources_new']}")
        set_status(self.lbl_cmp, "\n".join(lines))

    def exclude_selected(self):
        if self._build_id is None:
            return
        sel = sorted({i.row() for i in self.tbl_items.selectedIndexes()})
        if not sel:
            QMessageBox.information(self, "Выбор", "Выдели строки для исключения.")
            return
        try:
            con = connect(self._db_path)
            try:
                import json as _json
                b = con.execute("SELECT * FROM build WHERE id=?", (self._build_id,)).fetchone()
                items = con.execute(
                    "SELECT candidate_id, reason, pos FROM build_item "
                    "WHERE build_id=? ORDER BY pos",
                    (self._build_id,)).fetchall()
                drop = set()
                for r in sel:
                    if r < len(items):
                        drop.add(items[r]["candidate_id"])
                keep = [(x["candidate_id"], x["reason"]) for x in items
                        if x["candidate_id"] not in drop]
                from core.build_manifest import _profile_from_json
                prof = _profile_from_json(_json.loads(b["profile_json"] or "{}"))
                short = max(0, prof.target_size - len(keep))
                reasons = {cid: rs for cid, rs in keep}
                bid = save_build(con, f"{b['name']} без {len(drop)}",
                                 prof, [c for c, _ in keep], reasons, short)
            finally:
                con.close()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Ошибка", str(e))
            return
        self.refresh()
        self.open_build(bid)

    def pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Папка для пакета", self.lbl_dir.text())
        if d:
            self.lbl_dir.setText(d)

    def do_export(self):
        if self._build_id is None:
            QMessageBox.information(self, "Сборка", "Сначала выбери сборку.")
            return
        fmts = tuple(f for f, cb in (("xlsx", self.cb_xlsx), ("csv", self.cb_csv),
                                     ("jsonl", self.cb_jsonl)) if cb.isChecked())
        if not fmts:
            QMessageBox.information(self, "Формат", "Выбери хотя бы один формат.")
            return
        try:
            con = connect(self._db_path)
            try:
                pc = precheck(con, self._build_id)
                if pc["status"] == "blocked":
                    msgs = "; ".join(c["message"] for c in pc["checks"]
                                     if c["level"] == "block")
                    QMessageBox.warning(
                        self, "Заблокировано",
                        f"Экспорт невозможен: {msgs}. Исправь требования.")
                    return
                if pc["status"] == "warnings":
                    go = QMessageBox.question(
                        self, "Предупреждения",
                        "Есть предупреждения. Выгрузить всё равно?",
                        QMessageBox.Yes | QMessageBox.No)
                    if go != QMessageBox.Yes:
                        return
                out = Path(self.lbl_dir.text()) / f"build_{self._build_id}"
                made = export_package(con, self._build_id, out, fmts)
            finally:
                con.close()
        except Exception as e:  # noqa: BLE001
            set_status(self.lbl_out, f"ошибка: {e}", "block")
            return
        set_status(self.lbl_out, "пакет готов: " + ", ".join(made.values()), "ok")
