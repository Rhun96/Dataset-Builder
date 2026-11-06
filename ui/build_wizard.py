"""Мастер сборки: три ответа вместо настроек.

Нативный QWizard + только Qt-виджеты (Fluent внутрь нативных диалогов нельзя).
Логика отбора — та же, что у экранов (sample/uniform), предпросмотр сухой
(без сохранения), сборка сохраняется только по «Готово». Детерминизм:
тот же seed даёт тот же набор, «Другой вариант» = seed+1.
"""

from __future__ import annotations

import random
from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

MODES = [
    ("random", "Случайная выборка", "Просто укажи размер — остальное само"),
    ("balanced", "Сбалансированная", "Поровну по выбранной колонке"),
    ("manual", "Свои настройки", "Квоты и фильтры вручную (откроются Требования)"),
]


def wizard_eligible_total(con) -> int:
    return con.execute("SELECT COUNT(*) FROM pool_candidate").fetchone()[0]


def wizard_dims(con) -> list[tuple[str, str]]:
    from core.pool_profile import list_dims
    return list_dims(con)


def wizard_profile(mode: str, dim: str, size: int, seed: int):
    """Пустой профиль под режим; квоты для balanced добавляет preview."""
    from core.requirements import BuildProfile
    if mode == "balanced":
        return BuildProfile(target_size=size, seed=seed, mode="quota")
    return BuildProfile(target_size=size, seed=seed, mode="random")


def wizard_preview(con, profile, dim: str | None) -> dict:
    """Сухой прогон отбора + разбивка состава. Ничего не сохраняет."""
    from core.quota_presets import uniform
    from core.sampling_service import sample
    if profile.mode == "quota":
        if not dim:
            raise ValueError("выбери колонку для балансировки")
        profile = replace(profile, quotas=uniform(con, profile, dim))
    res = sample(con, profile)
    breakdown: list[tuple[str, int]] = []
    if res["items"]:
        marks = ",".join("?" for _ in res["items"])
        if dim:
            rows = con.execute(
                "SELECT value_raw, COUNT(*) c FROM pool_dim "
                f"WHERE dim=? AND candidate_id IN ({marks}) "
                "GROUP BY value_norm ORDER BY c DESC",
                (dim, *res["items"])).fetchall()
            breakdown = [(r[0] or "<пусто>", r[1]) for r in rows]
        else:
            rows = con.execute(
                "SELECT s.path, COUNT(*) c FROM candidate c "
                "JOIN source s ON s.id=c.source_id "
                f"WHERE c.id IN ({marks}) GROUP BY s.id ORDER BY c DESC",
                (*res["items"],)).fetchall()
            breakdown = [(Path(r[0]).name, r[1]) for r in rows]
    return {"items": res["items"], "reasons": res["reasons"],
            "short": res.get("short", 0), "breakdown": breakdown,
            "seed": profile.seed, "quotas": profile.quotas,
            "profile": profile}


def wizard_build(con, name: str, preview: dict) -> int:
    """Сохраняет сухой прогон как сборку. Возвращает id."""
    from storage.database import save_build
    prof = preview["profile"]
    return save_build(con, name or f"Мастер {prof.target_size}/{prof.seed}",
                      prof, preview["items"], preview["reasons"],
                      preview["short"])


def wizard_export(con, bid: int, out_dir: str, fmts: tuple) -> dict:
    """Предпроверка + выгрузка пакета. При блоке — ValueError с причинами."""
    from core.precheck_service import precheck
    from export.package_exporter import export_package
    pc = precheck(con, bid)
    if pc["status"] == "blocked":
        msgs = "; ".join(c["message"] for c in pc["checks"] if c["level"] == "block")
        raise ValueError(f"экспорт заблокирован: {msgs}")
    return export_package(con, bid, out_dir, fmts)


def apply_wizard_theme(dlg, dark: bool):
    """Нативный QWizard не знает Fluent-тему. Фон — через палитру
    (QSS фон страниц ModernStyle игнорирует), мелочи — через QSS."""
    if not dark:
        dlg.setStyleSheet("")
        return
    from PySide6.QtGui import QColor, QPalette
    pal = dlg.palette()
    pal.setColor(QPalette.Window, QColor("#14161A"))
    pal.setColor(QPalette.WindowText, QColor("#F2F2F2"))
    pal.setColor(QPalette.Base, QColor("#23272E"))
    pal.setColor(QPalette.Text, QColor("#F2F2F2"))
    pal.setColor(QPalette.Button, QColor("#2A2F36"))
    pal.setColor(QPalette.ButtonText, QColor("#F2F2F2"))
    pal.setColor(QPalette.Highlight, QColor("#F5A524"))
    pal.setColor(QPalette.HighlightedText, QColor("#14161A"))
    for w in [dlg] + [dlg.page(i) for i in dlg.pageIds()]:
        if w is None:
            continue
        w.setPalette(pal)
        try:
            w.setAutoFillBackground(True)
        except RuntimeError:  # noqa: BLE001
            pass
    dlg.setStyleSheet(
        "QLabel { color: #F2F2F2; }"
        "QLabel[hint=\"true\"] { color: #A8B0B8; }"
        "QRadioButton { color: #F2F2F2; }"
        "QCheckBox { color: #F2F2F2; }"
        "QSpinBox, QComboBox, QLineEdit, QListWidget {"
        " background: #23272E; color: #F2F2F2;"
        " border: 1px solid #3F3F3F; border-radius: 4px; }"
        "QPushButton { background: #2A2F36; color: #F2F2F2;"
        " border: 1px solid #3F3F3F; border-radius: 4px; padding: 4px 12px; }"
        "QPushButton:hover { border-color: #F5A524; }")


class _IntroPage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        head = QLabel("Что собираем?")
        font = head.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        head.setFont(font)
        lay.addWidget(head)
        self.grp = QButtonGroup(self)
        self.rbs: dict[str, QRadioButton] = {}
        for i, (code, title, sub) in enumerate(MODES):
            rb = QRadioButton(title)
            rb.setToolTip(sub)
            lay.addWidget(rb)
            hint = QLabel(sub)
            hint.setProperty("hint", True)
            hint.setProperty("hint", True)
            hint.setWordWrap(True)
            lay.addWidget(hint)
            self.grp.addButton(rb, i)
            self.rbs[code] = rb
        self.rbs["random"].setChecked(True)

    def mode(self) -> str:
        ids = ["random", "balanced", "manual"]
        return ids[self.grp.checkedId()]

    def nextId(self) -> int:
        return -1 if self.mode() == "manual" else 1


class _SetupPage(QWizardPage):
    def __init__(self, db_path: str, parent=None):
        super().__init__(parent)
        self._db_path = db_path
        lay = QVBoxLayout(self)
        head = QLabel("Параметры")
        font = head.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        head.setFont(font)
        lay.addWidget(head)
        namerow = QHBoxLayout()
        namerow.addWidget(QLabel("Название:"))
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("авто: Мастер {размер}/{вариант}")
        namerow.addWidget(self.edit_name, 1)
        lay.addLayout(namerow)
        sizerow = QHBoxLayout()
        sizerow.addWidget(QLabel("Размер:"))
        self.spin_size = QSpinBox()
        self.spin_size.setRange(1, 100000)
        self.spin_size.setValue(50)
        sizerow.addWidget(self.spin_size)
        sizerow.addWidget(QLabel("Колонка:"))
        self.cmb_dim = QComboBox()
        sizerow.addWidget(self.cmb_dim, 1)
        lay.addLayout(sizerow)
        self.lbl_elig = QLabel("")
        self.lbl_elig.setWordWrap(True)
        lay.addWidget(self.lbl_elig)
        self.lbl_err = QLabel("")
        self.lbl_err.setWordWrap(True)
        lay.addWidget(self.lbl_err)

    def initializePage(self) -> None:  # noqa: N802
        from storage.database import connect
        try:
            con = connect(self._db_path)
            try:
                dims = wizard_dims(con)
                total = wizard_eligible_total(con)
            finally:
                con.close()
        except Exception:  # noqa: BLE001
            dims, total = [], 0
        self.cmb_dim.clear()
        for code, label in dims:
            self.cmb_dim.addItem(label, code)
        self.lbl_elig.setText(f"Подходящих записей: {total}")
        self.spin_size.setValue(max(1, min(50, total or 1)))
        self.lbl_err.setText("")

    def validatePage(self) -> bool:  # noqa: N802
        mode = self.wizard().intro_mode()
        if self.spin_size.value() <= 0:
            self.lbl_err.setText("размер должен быть больше нуля.")
            return False
        if mode == "balanced" and not self.cmb_dim.currentData():
            self.lbl_err.setText("выбери колонку для балансировки.")
            return False
        from storage.database import connect
        try:
            con = connect(self._db_path)
            try:
                total = wizard_eligible_total(con)
            finally:
                con.close()
        except Exception:  # noqa: BLE001
            total = 0
        if total == 0:
            self.lbl_err.setText("пул пуст — сначала загрузи файлы на вкладке «Источники».")
            return False
        self.lbl_err.setText("")
        return True


class _PreviewPage(QWizardPage):
    def __init__(self, db_path: str, parent=None):
        super().__init__(parent)
        self._db_path = db_path
        self._preview: dict | None = None
        lay = QVBoxLayout(self)
        head = QLabel("Предпросмотр (не сохранено)")
        font = head.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        head.setFont(font)
        lay.addWidget(head)
        self.lbl_sum = QLabel("")
        self.lbl_sum.setWordWrap(True)
        lay.addWidget(self.lbl_sum)
        self.lst = QListWidget()
        self.lst.setMaximumHeight(160)
        lay.addWidget(self.lst)
        row = QHBoxLayout()
        self.btn_more = QPushButton("Другой вариант")
        self.btn_more.setToolTip("Тот же состав, другой seed")
        self.btn_more.clicked.connect(self._reroll)
        row.addWidget(self.btn_more)
        self.btn_build = QPushButton("Собрать выборку")
        self.btn_build.setToolTip("Сохранить как сборку и перейти к выгрузке")
        self.btn_build.clicked.connect(self._save_and_next)
        row.addWidget(self.btn_build)
        row.addStretch(1)
        lay.addLayout(row)
        self._seed = 0

    def initializePage(self) -> None:  # noqa: N802
        wiz = self.wizard()
        self._seed = random.randrange(0, 1000000)
        self._run(wiz.intro_mode(), wiz.setup_dim(),
                  wiz.setup_size(), wiz.setup_name(), self._seed)

    def _reroll(self):
        wiz = self.wizard()
        self._seed = random.randrange(0, 1000000)
        self._run(wiz.intro_mode(), wiz.setup_dim(),
                  wiz.setup_size(), wiz.setup_name(), self._seed)

    def _save_and_next(self):
        wiz = self.wizard()
        if wiz.save_current() is not None:
            wiz.next()

    def _run(self, mode: str, dim: str | None, size: int, _name: str, seed: int):
        from storage.database import connect
        try:
            con = connect(self._db_path)
            try:
                prof = wizard_profile(mode, dim or "", size, seed)
                self._preview = wizard_preview(con, prof, dim)
            finally:
                con.close()
        except ValueError as e:
            self._preview = None
            self.lbl_sum.setText(str(e))
            self.lst.clear()
            return
        except Exception as e:  # noqa: BLE001
            self._preview = None
            self.lbl_sum.setText(f"ошибка: {e}")
            self.lst.clear()
            return
        got = len(self._preview["items"])
        short = self._preview["short"]
        self.lbl_sum.setText(f"соберётся {got} (недобор {short}), вариант {seed}. "
                             "Нажми «Готово», чтобы сохранить.")
        self.lst.clear()
        for raw, cnt in self._preview["breakdown"]:
            self.lst.addItem(f"{raw} — {cnt}")
        self.completeChanged.emit()

    def isComplete(self) -> bool:  # noqa: N802
        return self._preview is not None and bool(self._preview.get("items"))

    def validatePage(self) -> bool:  # noqa: N802
        return self.isComplete()


class _DonePage(QWizardPage):
    def __init__(self, db_path: str, parent=None):
        super().__init__(parent)
        self._db_path = db_path
        lay = QVBoxLayout(self)
        head = QLabel("Готово — выгрузка пакета")
        font = head.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        head.setFont(font)
        lay.addWidget(head)
        self.lbl_done = QLabel("")
        self.lbl_done.setWordWrap(True)
        lay.addWidget(self.lbl_done)
        fmtrow = QHBoxLayout()
        from PySide6.QtWidgets import QCheckBox
        self.cb_xlsx = QCheckBox("XLSX")
        self.cb_xlsx.setChecked(True)
        self.cb_csv = QCheckBox("CSV")
        self.cb_jsonl = QCheckBox("JSONL")
        self.cb_jsonl.setChecked(True)
        for cb in (self.cb_xlsx, self.cb_csv, self.cb_jsonl):
            fmtrow.addWidget(cb)
        fmtrow.addStretch(1)
        lay.addLayout(fmtrow)
        dirrow = QHBoxLayout()
        dirrow.addWidget(QLabel("Папка:"))
        self.lbl_dir = QLabel(str(Path.home() / "Documents"
                                  / "DatasetBuilderV2" / "exports"))
        self.lbl_dir.setWordWrap(True)
        dirrow.addWidget(self.lbl_dir, 1)
        self.btn_dir = QPushButton("Папка…")
        self.btn_dir.clicked.connect(self._pick_dir)
        dirrow.addWidget(self.btn_dir)
        lay.addLayout(dirrow)
        self.btn_export = QPushButton("Выгрузить пакет")
        self.btn_export.clicked.connect(self._do_export)
        lay.addWidget(self.btn_export)
        self.lbl_out = QLabel("")
        self.lbl_out.setWordWrap(True)
        lay.addWidget(self.lbl_out)

    def initializePage(self) -> None:  # noqa: N802
        wiz = self.wizard()
        saved = wiz.saved or {}
        self.lbl_done.setText(
            f"Сборка #{saved.get('bid')}: собрано {saved.get('picked')} "
            f"(недобор {saved.get('short', 0)}). Пакет — сюда или на вкладке "
            "«3 · Сборка и экспорт».")
        self.lbl_out.setText("")

    def _pick_dir(self):
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, "Папка для пакета",
                                             self.lbl_dir.text())
        if d:
            self.lbl_dir.setText(d)

    def _do_export(self):
        from storage.database import connect
        wiz = self.wizard()
        saved = wiz.saved or {}
        if not saved.get("bid"):
            self.lbl_out.setText("сначала собери выборку на предыдущем шаге.")
            return
        fmts = tuple(f for f, cb in (("xlsx", self.cb_xlsx), ("csv", self.cb_csv),
                                     ("jsonl", self.cb_jsonl)) if cb.isChecked())
        if not fmts:
            self.lbl_out.setText("выбери хотя бы один формат.")
            return
        try:
            con = connect(self._db_path)
            try:
                made = wizard_export(con, saved["bid"], self.lbl_dir.text(), fmts)
            finally:
                con.close()
        except ValueError as e:
            self.lbl_out.setText(str(e))
            return
        except Exception as e:  # noqa: BLE001
            self.lbl_out.setText(f"ошибка: {e}")
            return
        self.lbl_out.setText("пакет готов: " + ", ".join(made.values()))


class WizardDialog(QWizard):
    """Мастер сборки. После accept(): result = {'action': ...}."""

    def __init__(self, db_path: str, parent=None):
        super().__init__(parent)
        self._db_path = str(db_path)
        self.result: dict | None = None
        self.saved: dict | None = None
        self.setWindowTitle("Мастер сборки")
        self.setWizardStyle(QWizard.ModernStyle)
        self.setOption(QWizard.NoBackButtonOnStartPage, True)
        self._intro = _IntroPage(self)
        self._setup = _SetupPage(self._db_path, self)
        self._preview = _PreviewPage(self._db_path, self)
        self._done = _DonePage(self._db_path, self)
        self.setPage(0, self._intro)
        self.setPage(1, self._setup)
        self.setPage(2, self._preview)
        self.setPage(3, self._done)
        try:
            from qfluentwidgets import isDarkTheme
            dark = bool(isDarkTheme())
        except Exception:  # noqa: BLE001
            from ui.theme import saved_theme
            dark = saved_theme() == "dark"
        apply_wizard_theme(self, dark)

    def intro_mode(self) -> str:
        return self._intro.mode()

    def setup_dim(self) -> str | None:
        return self._setup.cmb_dim.currentData()

    def setup_size(self) -> int:
        return self._setup.spin_size.value()

    def setup_name(self) -> str:
        return self._setup.edit_name.text().strip()

    def save_current(self) -> int | None:
        """Сохранить текущее превью как сборку. Возвращает id или None."""
        pv = self._preview._preview
        if not pv or not pv.get("items"):
            return None
        from storage.database import connect
        try:
            con = connect(self._db_path)
            try:
                bid = wizard_build(con, self.setup_name(), pv)
            finally:
                con.close()
        except Exception:  # noqa: BLE001
            return None
        self.saved = {"bid": bid, "picked": len(pv["items"]),
                      "short": pv["short"], "seed": pv["seed"]}
        return bid

    def accept(self) -> None:  # noqa: N802
        mode = self.intro_mode()
        if mode == "manual":
            self.result = {"action": "advanced"}
            super().accept()
            return
        if self.saved is None:
            if self.save_current() is None:
                return
        self.result = {"action": "built", "bid": self.saved["bid"],
                       "picked": self.saved["picked"],
                       "short": self.saved["short"],
                       "seed": self.saved["seed"]}
        super().accept()
