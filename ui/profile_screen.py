"""Экран «Профиль пула»: дашборд + распределение по измерению."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ComboBox,
    ProgressBar,
    PushButton,
    StrongBodyLabel,
    TableWidget,
)
from ui.donut import PALETTE, DonutWidget

from core.pool_profile import (
    anomalies,
    dim_distribution,
    fill_rate,
    get_summary,
    list_dims,
    pool_overview,
    source_dims,
)
from storage.database import connect
from ui.theme import polish_table, set_status, wrap_in_scroll


def _mb(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} МБ"
    if n >= 1024:
        return f"{n / 1024:.0f} КБ"
    return f"{n} Б"


def _card(title: str) -> tuple[CardWidget, QVBoxLayout]:
    card = CardWidget()
    box = QVBoxLayout(card)
    box.addWidget(StrongBodyLabel(title))
    return card, box


def _bignum(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("font-size: 22px; font-weight: 700;")
    return lbl


class ProfileScreen(QWidget):
    def __init__(self, db_path: str | Path):
        super().__init__()
        self._db_path = str(db_path)
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.btn_refresh = PushButton("Обновить")
        self.btn_refresh.clicked.connect(self.refresh)
        self.lbl_sum = QLabel("—")
        top.addWidget(self.btn_refresh)
        top.addWidget(self.lbl_sum, 1)
        layout.addLayout(top)

        self.card_data = CardWidget()
        data_layout = QVBoxLayout(self.card_data)
        data_head = QHBoxLayout()
        data_head.addWidget(StrongBodyLabel("Что у нас в данных?"))
        self.lbl_data_hint = BodyLabel("")
        self.lbl_data_hint.setWordWrap(True)
        data_head.addWidget(self.lbl_data_hint, 1)
        self.btn_more = PushButton("Подробнее →")
        self.btn_more.setToolTip("Обновить распределение ниже")
        self.btn_more.clicked.connect(lambda *_: self.show_dist())
        data_head.addWidget(self.btn_more)
        data_layout.addLayout(data_head)

        data_body = QHBoxLayout()
        data_body.setSpacing(12)
        left_box = QVBoxLayout()
        self.lbl_top_dim = BodyLabel("")
        left_box.addWidget(self.lbl_top_dim)
        self.donut = DonutWidget()
        self.donut.setMaximumHeight(170)
        left_box.addWidget(self.donut)
        self.top_bars: list[tuple[BodyLabel, ProgressBar]] = []
        for _ in range(6):
            brow = QHBoxLayout()
            brow.setSpacing(6)
            name = BodyLabel("")
            name.setFixedWidth(170)
            bar = ProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(False)
            brow.addWidget(name)
            brow.addWidget(bar, 1)
            left_box.addLayout(brow)
            self.top_bars.append((name, bar))
        data_body.addLayout(left_box, 3)

        right_box = QVBoxLayout()
        self.lbl_records = _bignum("—")
        self.lbl_pool_sub = BodyLabel("")
        self.lbl_pool_sub.setWordWrap(True)
        right_box.addWidget(self.lbl_records)
        right_box.addWidget(self.lbl_pool_sub)
        self.lbl_fill = _bignum("—")
        self.lbl_fill_sub = BodyLabel("")
        self.lbl_fill_sub.setWordWrap(True)
        right_box.addWidget(self.lbl_fill)
        right_box.addWidget(self.lbl_fill_sub)
        self.lbl_anom = BodyLabel("")
        self.lbl_anom.setWordWrap(True)
        right_box.addWidget(self.lbl_anom)
        right_box.addStretch(1)
        data_body.addLayout(right_box, 2)
        data_layout.addLayout(data_body)
        layout.addWidget(self.card_data)

        row = QHBoxLayout()
        row.addWidget(QLabel("Источник:"))
        self.cmb_src = ComboBox()
        self.cmb_src.setToolTip("Все — весь пул; один — только его записи")
        self.cmb_src.currentIndexChanged.connect(lambda *_: self.refresh())
        row.addWidget(self.cmb_src)
        row.addWidget(QLabel("Измерение:"))
        self.cmb_dim = ComboBox()
        self.cmb_dim.currentIndexChanged.connect(lambda *_: self.show_dist())
        row.addWidget(self.cmb_dim, 1)
        layout.addLayout(row)

        self.lbl_dim = QLabel("")
        layout.addWidget(self.lbl_dim)
        self.tbl = TableWidget()
        self.tbl.setColumnCount(3)
        self.tbl.setHorizontalHeaderLabels(["Значение", "Количество", "Доля"])
        polish_table(self.tbl)
        layout.addWidget(self.tbl, 1)
        wrap_in_scroll(self)
        self.refresh()

    def _selected_source(self) -> int | None:
        data = self.cmb_src.currentData() if hasattr(self, "cmb_src") else None
        return int(data) if data else None

    def refresh(self):
        try:
            con = connect(self._db_path)
            try:
                from storage.database import list_sources
                srcs = list_sources(con)
            finally:
                con.close()
        except Exception:  # noqa: BLE001
            srcs = []
        keep = self.cmb_src.currentData() if self.cmb_src.count() else None
        self.cmb_src.blockSignals(True)
        self.cmb_src.clear()
        self.cmb_src.addItem("Все (весь пул)", userData=None)
        for s in srcs:
            mark = "" if s.get("in_pool", 1) else " (вне пула)"
            self.cmb_src.addItem(f"{Path(s['path']).name}{mark}", userData=s["id"])
        if keep:
            self.cmb_src.setCurrentIndex(max(0, self.cmb_src.findData(keep)))
        self.cmb_src.blockSignals(False)
        sid = self._selected_source()
        try:
            con = connect(self._db_path)
            try:
                s = get_summary(con, sid)
                dims = list_dims(con) if sid is None else source_dims(con, sid)
                ov = pool_overview(con, sid)
                fr = fill_rate(con, sid)
                an = anomalies(con, sid)
            finally:
                con.close()
        except Exception as e:  # noqa: BLE001
            set_status(self.lbl_sum, f"база недоступна: {e}", "block")
            return
        self.lbl_sum.setText(
            f"Всего: {s['total']} · уникальных отпечатков: {s['uniq_fp']} · "
            f"точных дублей: {s['exact_dupes']} · без ID: {s['no_ext_id']} · "
            f"источников: {s['sources_ok']}")
        self.lbl_records.setText(f"{ov['records']:,}".replace(",", " "))
        if ov.get("name"):
            self.lbl_pool_sub.setText(
                f"{ov['name']}\nкатегорий: {len(s['dims'])} · {_mb(ov['bytes'])}")
            self.lbl_data_hint.setText(
                f"{ov['name']} · измерений: {len(s['dims'])}")
        else:
            self.lbl_pool_sub.setText(
                f"файлов: {ov['sources']} · категорий: {len(s['dims'])}"
                f"\nразмер: {_mb(ov['bytes'])}")
            self.lbl_data_hint.setText(
                f"файлов: {s['sources_ok']} · измерений: {len(s['dims'])}")
        self.lbl_fill.setText(f"{fr['pct']:.0f}%")
        self.lbl_fill_sub.setText(
            f"заполнено полей {fr['filled']:,}/{fr['total']:,} "
            f"по {fr['dims']} измерениям".replace(",", " "))
        imb = (f"дисбаланс: да ({an['top_source']} — {an['top_share']}%)"
               if an["imbalance"] else "дисбаланс источников: нет")
        self.lbl_anom.setText(
            f"дубликаты: {an['dupes']}\nбез ID: {an['no_ext_id']}\n{imb}\n"
            f"редкие значения: {an['rare']}")
        cur = self.cmb_dim.currentData()
        self.cmb_dim.blockSignals(True)
        self.cmb_dim.clear()
        for code, label in dims:
            self.cmb_dim.addItem(label, userData=code)
        if cur:
            idx = next((i for i in range(self.cmb_dim.count())
                        if self.cmb_dim.itemData(i) == cur), 0)
            self.cmb_dim.setCurrentIndex(idx)
        self.cmb_dim.blockSignals(False)
        self.show_dist()

    def show_dist(self):
        dim = self.cmb_dim.currentData()
        if not dim:
            self.lbl_dim.setText("пул пуст — загрузи источники.")
            self.lbl_top_dim.setText("")
            self.donut.set_parts([])
            self.tbl.setRowCount(0)
            for name, bar in self.top_bars:
                name.setText("")
                bar.setValue(0)
            return
        try:
            con = connect(self._db_path)
            try:
                d = dim_distribution(con, dim, source_id=self._selected_source())
            finally:
                con.close()
        except Exception as e:  # noqa: BLE001
            set_status(self.lbl_dim, f"ошибка: {e}", "block")
            return
        self.lbl_dim.setText(
            f"{d['label']}: заполнено {d['filled']}/{d['total']} "
            f"({d['fill_pct']:.0f}%), уникальных {d['unique']}, "
            f"без значения {d['missing']}")
        self.lbl_top_dim.setText(d["label"])
        from ui.theme import saved_theme
        dark = saved_theme() == "dark"
        parts = [(PALETTE[i % len(PALETTE)], r["count"] / d["total"] if d["total"] else 0)
                 for i, r in enumerate(d["top"][:6])]
        total_txt = f"{d['total']:,}".replace(",", " ")
        tips = [f"{r['raw'] or '<пусто>'} — {r['count']} ({r['pct']:.0f}%)"
                for r in d["top"][:6]]
        self.donut.set_parts(parts, center=f"{total_txt}\nзаписей", dark=dark,
                             tips=tips)
        for i, (name, bar) in enumerate(self.top_bars):
            if i < len(d["top"]):
                row = d["top"][i]
                raw = row["raw"] or "<пусто>"
                if len(raw) > 18:
                    raw = raw[:18] + "…"
                name.setText(f"{raw} — {row['count']} ({row['pct']:.0f}%)")
                name.setToolTip(f"{row['raw'] or '<пусто>'} — {row['count']}")
                bar.setValue(int(row["pct"]))
            else:
                name.setText("")
                bar.setValue(0)
        self.tbl.setRowCount(len(d["top"]))
        for r, row in enumerate(d["top"]):
            self.tbl.setItem(r, 0, QTableWidgetItem(row["raw"] or "<пусто>"))
            self.tbl.setItem(r, 1, QTableWidgetItem(str(row["count"])))
            self.tbl.setItem(r, 2, QTableWidgetItem(f"{row['pct']:.1f}%"))
