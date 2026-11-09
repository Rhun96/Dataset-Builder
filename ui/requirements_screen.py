"""Экран «Требования»: размер, зерно, квоты, покрытие, сборка."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidgetItem,
    QMessageBox,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    DoubleSpinBox,
    LineEdit,
    ListWidget,
    PrimaryPushButton,
    PushButton,
    RadioButton,
    SpinBox,
    StrongBodyLabel,
    TableWidget,
)

from core.coverage_service import coverage
from core.pool_profile import dim_values, list_dims
from core.requirements import (
    SEED_HINT,
    SEED_LABEL,
    BuildProfile,
    Filter,
    Quota,
    profile_from_dict,
    profile_to_dict,
)
from core.roles import dim_label
from core.sampling_service import sample
from storage.database import (
    connect,
    delete_req_profile,
    list_req_profiles,
    load_req_profile,
    save_build,
    save_req_profile,
)
from ui.donut import PALETTE, DonutWidget
from ui.theme import polish_table, saved_theme, set_status, wrap_in_scroll

FILTER_OPS_UI = [("eq", "равно"), ("ne", "не равно"),
                 ("in", "в списке"), ("notin", "не в списке"),
                 ("missing", "пусто"), ("notmissing", "не пусто"),
                 ("contains", "содержит"), ("gt", "больше"), ("lt", "меньше")]

QUOTA_KINDS = [("min", "минимум"), ("max", "максимум"),
               ("exact", "точно"), ("percent", "процент")]
MODES = [("quota", "По квотам"), ("random", "Случайный"),
         ("stratified", "Стратифицированный"), ("mixed", "Смешанный")]


class FormationCard(CardWidget):
    """Карточка режима набора как в референсе: заголовок + подпись, клик — выбор."""

    def __init__(self, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        box = QVBoxLayout(self)
        box.setContentsMargins(10, 8, 10, 8)
        box.setSpacing(2)
        self.lbl_title = StrongBodyLabel(title)
        self.lbl_title.setWordWrap(True)
        self.lbl_sub = QLabel(subtitle)
        self.lbl_sub.setWordWrap(True)
        self.lbl_sub.setProperty("hint", True)
        for w in (self.lbl_title, self.lbl_sub):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        box.addWidget(self.lbl_title)
        box.addWidget(self.lbl_sub)
        self.setMinimumWidth(130)
        self._click_cb = None

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        if self._click_cb is not None:
            self._click_cb()

    def setSelected(self, on: bool):
        if on:
            self.setStyleSheet(
                "FormationCard { border: 2px solid #F5A524; border-radius: 8px; }")
        else:
            self.setStyleSheet("")


class FilterColumnCard(CardWidget):
    """Колонка быстрых фильтров по одному измерению (как в референсе)."""

    def __init__(self, dim: str, label: str, parent=None):
        super().__init__(parent)
        self.dim = dim
        box = QVBoxLayout(self)
        box.setContentsMargins(8, 8, 8, 8)
        box.setSpacing(4)
        head = QHBoxLayout()
        self.lbl = StrongBodyLabel(label)
        self.lbl.setWordWrap(True)
        self.badge = QLabel("Все")
        self.badge.setProperty("hint", True)
        head.addWidget(self.lbl, 1)
        head.addWidget(self.badge)
        box.addLayout(head)
        self.lst = ListWidget()
        self.lst.setFixedHeight(140)
        box.addWidget(self.lst)
        for w in (self.lbl, self.badge):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._click_cb = None
        self.setMinimumWidth(150)

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        if self._click_cb is not None:
            self._click_cb()

    def setActive(self, on: bool):
        if on:
            self.setStyleSheet(
                "FilterColumnCard { border: 2px solid #F5A524; border-radius: 8px; }")
        else:
            self.setStyleSheet("")


class RequirementsScreen(QWidget):
    def __init__(self, db_path: str | Path):
        super().__init__()
        self._db_path = str(db_path)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)

        moderow = QHBoxLayout()
        self.chk_adv = CheckBox("Продвинутые настройки")
        self.chk_adv.setToolTip("Фильтры, лимиты, новизна, редкость, ручные квоты")
        self.chk_adv.toggled.connect(self._apply_mode_visibility)
        moderow.addWidget(self.chk_adv)
        self.lbl_mode_hint = QLabel("Простой режим")
        self.lbl_mode_hint.setToolTip("Размер + баланс, остальное само. "
                                     "Всё управление — за галочкой «Продвинутые настройки».")
        self.lbl_mode_hint.setProperty("hint", True)
        self.lbl_mode_hint.setWordWrap(True)
        moderow.addWidget(self.lbl_mode_hint, 1)
        ll.addLayout(moderow)

        top = QHBoxLayout()
        top.addWidget(QLabel("Целевой размер:"))
        self.spin_size = SpinBox()
        self.spin_size.setRange(1, 100000)
        self.spin_size.setValue(500)
        top.addWidget(self.spin_size)
        self.btn_fit = PushButton("Сколько есть")
        self.btn_fit.setToolTip("Не знаю сколько нужно — подогнать размер под подходящие записи")
        self.btn_fit.clicked.connect(self.fit_to_pool)
        top.addWidget(self.btn_fit)
        self.lbl_seed_t = QLabel(SEED_LABEL + ":")
        top.addWidget(self.lbl_seed_t)
        self.spin_seed = SpinBox()
        self.spin_seed.setRange(0, 999999)
        self.spin_seed.setValue(42)
        self.spin_seed.setToolTip(SEED_HINT)
        top.addWidget(self.spin_seed)
        self.lbl_mode_t = QLabel("Режим:")
        top.addWidget(self.lbl_mode_t)
        self.cmb_mode = ComboBox()
        for code, label in MODES:
            self.cmb_mode.addItem(label, userData=code)
        self.cmb_mode.currentIndexChanged.connect(self._toggle_stratify)
        top.addWidget(self.cmb_mode)
        self.lbl_strat_t = QLabel("Страта:")
        top.addWidget(self.lbl_strat_t)
        self.cmb_strat = ComboBox()
        self.cmb_strat.setToolTip("Измерение, доли которого сохраняет стратификация")
        self.cmb_strat.setEnabled(False)
        top.addWidget(self.cmb_strat)
        self.lbl_hint = QLabel(SEED_HINT)
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setProperty("hint", True)
        ll.addLayout(top)
        ll.addWidget(self.lbl_hint)

        namerow = QHBoxLayout()
        namerow.addWidget(QLabel("Название набора:"))
        self.edit_name = LineEdit()
        self.edit_name.setPlaceholderText("авто: Сборка {размер}/{вариант}")
        self.edit_name.setClearButtonEnabled(True)
        namerow.addWidget(self.edit_name, 1)
        namerow.addWidget(QLabel("Описание:"))
        self.edit_desc = LineEdit()
        self.edit_desc.setPlaceholderText("необязательно")
        self.edit_desc.setClearButtonEnabled(True)
        namerow.addWidget(self.edit_desc, 1)
        ll.addLayout(namerow)

        divrow = QHBoxLayout()
        self.lbl_div_t = QLabel("Разнообразие:")
        self.lbl_div_t.setToolTip("Порог сходства: 0 — выкл, обычно 0.8–0.9. "
                                  "Не брать записи, слишком похожие на уже выбранные.")
        divrow.addWidget(self.lbl_div_t)
        self.spin_div = DoubleSpinBox()
        self.spin_div.setRange(0, 0.99)
        self.spin_div.setSingleStep(0.05)
        self.spin_div.setValue(0)
        self.spin_div.setToolTip("Убирает тексты с высоким БУКВАЛЬНЫМ сходством "
                                "(общие слова), а не смысловые дубли. "
                                "0 — выкл, обычно 0.8–0.9.")
        divrow.addWidget(self.spin_div)
        self.cb_rarity = CheckBox("Редкие сочетания первыми")
        divrow.addWidget(self.cb_rarity)
        self.lbl_dd_t = QLabel("Дубли:")
        self.lbl_dd_t.setToolTip("Точные дубли текста: оставить как есть, убрать все "
                                 "повторы или брать повтор только с новыми значениями")
        divrow.addWidget(self.lbl_dd_t)
        self.cmb_dedupe = ComboBox()
        for code, label in (("off", "как есть"), ("exact", "убрать повторы"),
                            ("exact_new", "повтор только с новым")):
            self.cmb_dedupe.addItem(label, userData=code)
        self.cmb_dedupe.setToolTip("«Повтор только с новым» — дубль берём, если у него "
                                   "есть значения измерений, ещё не встречавшиеся в наборе")
        divrow.addWidget(self.cmb_dedupe)
        self.lbl_mix_hint = QLabel("Смешанный: всё сразу")
        self.lbl_mix_hint.setToolTip("Смешанный = квоты + разнообразие + редкость")
        self.lbl_mix_hint.setWordWrap(True)
        self.lbl_mix_hint.setProperty("hint", True)
        divrow.addWidget(self.lbl_mix_hint, 1)
        ll.addLayout(divrow)
        raretip = QHBoxLayout()
        self.lbl_rare_tip = QLabel("")
        self.lbl_rare_tip.setWordWrap(True)
        self.lbl_rare_tip.setProperty("hint", True)
        self.btn_rare = PushButton("Включить редкие")
        self.btn_rare.setToolTip("Сначала редкие сочетания значений")
        self.btn_rare.clicked.connect(self._enable_rarity)
        raretip.addWidget(self.lbl_rare_tip, 1)
        raretip.addWidget(self.btn_rare)
        ll.addLayout(raretip)
        self.lbl_rare_tip.setVisible(False)
        self.btn_rare.setVisible(False)

        self.lbl_q_t = QLabel("Квоты вручную:")
        self.lbl_q_t.setToolTip("Измерение = значение, вид, количество")
        self.lbl_q_t.setWordWrap(True)
        ll.addWidget(self.lbl_q_t)
        poolrow = QHBoxLayout()
        poolrow.addWidget(QLabel("Пул:"))
        self.btn_pool = PushButton("Источники…")
        self.btn_pool.setToolTip("Какие файлы входят в пул")
        self.btn_pool.clicked.connect(self.pick_pool)
        poolrow.addWidget(self.btn_pool)
        self.lbl_pool = QLabel("")
        self.lbl_pool.setWordWrap(True)
        poolrow.addWidget(self.lbl_pool, 1)
        ll.addLayout(poolrow)
        ll.addWidget(QLabel("Как набирать:"))
        cards_row = QHBoxLayout()
        cards_row.setSpacing(8)
        self.grp_formation = QButtonGroup(self)
        self.rb_all = RadioButton("Всё подходящее", self)
        self.rb_all.setToolTip("Взять всё, что подошло под фильтры и пул")
        self.rb_equal = RadioButton("Поровну", self)
        self.rb_equal.setToolTip("Каждое значение поровну")
        self.rb_prop = RadioButton("Пропорционально", self)
        self.rb_prop.setToolTip("Доли как в пуле")
        self.rb_auto = RadioButton("Авто-подбор", self)
        self.rb_auto.setToolTip("Советчик: редкие — целиком, остальные — долями, с объяснением")
        self.rb_manual = RadioButton("Вручную", self)
        self.rb_manual.setToolTip("Квоты руками в таблице ниже")
        self.rb_manual.setChecked(True)
        for rb in (self.rb_all, self.rb_equal, self.rb_prop,
                   self.rb_auto, self.rb_manual):
            rb.hide()
        for i, rb in enumerate([self.rb_all, self.rb_equal, self.rb_prop,
                               self.rb_auto, self.rb_manual]):
            self.grp_formation.addButton(rb, i)
        self.grp_formation.buttonClicked.connect(self._on_formation)
        self.card_all = FormationCard("Всё подходящее", "Без ограничений по количеству")
        self.card_equal = FormationCard("Поровну", "Равномерно по выбранным группам")
        self.card_prop = FormationCard("Пропорционально", "Доли как в пуле")
        self.card_auto = FormationCard("Авто-подбор", "Программа сама предложит состав")
        self.card_manual = FormationCard("Вручную", "Указать значения и количество")
        self._formation_cards = {"all": self.card_all, "equal": self.card_equal,
                                "prop": self.card_prop, "auto": self.card_auto,
                                "manual": self.card_manual}
        for name, card in self._formation_cards.items():
            card._click_cb = lambda n=name: self.apply_formation(n)
            cards_row.addWidget(card, 1)
        ll.addLayout(cards_row)
        self._formation = "manual"
        self.tbl_q = TableWidget()
        self.tbl_q.setColumnCount(6)
        self.tbl_q.setHorizontalHeaderLabels(
            ["Изм. 1", "Знач. 1", "Изм. 2", "Знач. 2", "Вид", "Количество"])
        polish_table(self.tbl_q)
        ll.addWidget(self.tbl_q, 1)
        qr = QHBoxLayout()
        self.btn_qrow = PushButton("+ Строка")
        self.btn_qrow.setToolTip("Добавить строку квоты вручную")
        self.btn_qrow.clicked.connect(lambda: self.add_quota_row())
        qr.addWidget(self.btn_qrow)
        self.btn_del = PushButton("− Убрать")
        self.btn_del.clicked.connect(self.del_quota_row)
        qr.addWidget(self.btn_del)
        qr.addWidget(QLabel("строки выше — ручной режим"), 1)
        ll.addLayout(qr)

        self.lbl_f_t = QLabel("Фильтры (что берём):")
        self.lbl_f_t.setToolTip("Условия на пул до квот")
        self.lbl_f_t.setWordWrap(True)
        ll.addWidget(self.lbl_f_t)
        ff = QHBoxLayout()
        ff.addWidget(QLabel("Что берём:"))
        ff.addWidget(QLabel("Колонка:"))
        self.cmb_ff_dim = ComboBox()
        self.cmb_ff_dim.setToolTip("Колонка для пресетов, авто-подбора "
                                   "и разбивки «Всё подходящее». "
                                   "Клик по шапке колонки ниже тоже её выбирает.")
        self.cmb_ff_dim.currentIndexChanged.connect(self._on_ff_dim_changed)
        ff.addWidget(self.cmb_ff_dim, 1)
        self.btn_ff_add = PushButton("Добавить отмеченные ↓")
        self.btn_ff_add.setToolTip("Отмеченные в колонках = «подходит любое из них» "
                                    "(по каждой колонке свой фильтр)")
        self.btn_ff_add.clicked.connect(self.quick_add_filter)
        ff.addWidget(self.btn_ff_add)
        self.btn_ff_clear = PushButton("Очистить")
        self.btn_ff_clear.setToolTip("Убрать все условия")
        self.btn_ff_clear.clicked.connect(self.clear_filters)
        ff.addWidget(self.btn_ff_clear)
        ll.addLayout(ff)
        ff_search = QHBoxLayout()
        ff_search.addWidget(QLabel("Поиск:"))
        self.edit_ff_search = LineEdit()
        self.edit_ff_search.setPlaceholderText("Поиск по значениям…")
        self.edit_ff_search.setClearButtonEnabled(True)
        self.edit_ff_search.textChanged.connect(lambda *_: self._apply_ff_search())
        ff_search.addWidget(self.edit_ff_search, 1)
        ll.addLayout(ff_search)
        self._ff_checked: dict[str, set[str]] = {}
        self._ff_cols: dict = {}
        self.ff_cols = QHBoxLayout()
        self.ff_cols.setSpacing(8)
        ll.addLayout(self.ff_cols)
        self.lbl_match = StrongBodyLabel("Подходящих записей: —")
        ll.addWidget(self.lbl_match)
        self.tbl_f = TableWidget()
        self.tbl_f.setColumnCount(3)
        self.tbl_f.setHorizontalHeaderLabels(["Измерение", "Условие", "Значение"])
        polish_table(self.tbl_f)
        ll.addWidget(self.tbl_f, 1)
        fr = QHBoxLayout()
        self.btn_fadd = PushButton("+ Фильтр")
        self.btn_fadd.clicked.connect(self.add_filter_row)
        self.btn_fdel = PushButton("− Убрать")
        self.btn_fdel.clicked.connect(self.del_filter_row)
        fr.addWidget(self.btn_fadd)
        fr.addWidget(self.btn_fdel)
        self.lbl_f_hint = QLabel("в списке — значения через «;»")
        self.lbl_f_hint.setWordWrap(True)
        self.lbl_f_hint.setProperty("hint", True)
        fr.addWidget(self.lbl_f_hint, 1)
        ll.addLayout(fr)

        run = QHBoxLayout()
        self.btn_wizard = PushButton("Мастер сборки…")
        self.btn_wizard.setToolTip("Три ответа вместо настроек: случайная, "
                                     "сбалансированная или вручную")
        self.btn_wizard.clicked.connect(self.open_wizard)
        self.btn_check = PushButton("Проверить покрытие")
        self.btn_check.clicked.connect(self.check_coverage)
        self.btn_build = PrimaryPushButton("Собрать выборку")
        self.btn_build.clicked.connect(self.build)
        run.addWidget(self.btn_wizard)
        run.addWidget(self.btn_check)
        run.addWidget(self.btn_build, 1)
        ll.addLayout(run)

        self.lbl_prof_t = QLabel("Профиль требований:")
        self.lbl_prof_t.setToolTip("Сохранить и переиспользовать конфигурацию")
        self.lbl_prof_t.setWordWrap(True)
        ll.addWidget(self.lbl_prof_t)
        prof_row = QHBoxLayout()
        self.cmb_profiles = ComboBox()
        self.btn_psave = PushButton("Сохранить")
        self.btn_psave.clicked.connect(self.save_profile)
        self.btn_pload = PushButton("Загрузить")
        self.btn_pload.clicked.connect(self.load_profile)
        self.btn_pdel = PushButton("Удалить")
        self.btn_pdel.clicked.connect(self.delete_profile)
        self.btn_pref = PushButton("↻")
        self.btn_pref.setToolTip("Обновить список профилей")
        self.btn_pref.clicked.connect(self.refresh_profiles)
        prof_row.addWidget(self.cmb_profiles, 1)
        prof_row.addWidget(self.btn_psave)
        prof_row.addWidget(self.btn_pload)
        prof_row.addWidget(self.btn_pdel)
        prof_row.addWidget(self.btn_pref)
        ll.addLayout(prof_row)
        self.refresh_profiles()

        self.lbl_nov_t = QLabel("Новизна и доли:")
        self.lbl_nov_t.setWordWrap(True)
        ll.addWidget(self.lbl_nov_t)
        nov1 = QHBoxLayout()
        self.lbl_share_t = QLabel("Лимит доли, %:")
        self.lbl_share_t.setToolTip("0 — без лимита")
        nov1.addWidget(self.lbl_share_t)
        self.spin_share = DoubleSpinBox()
        self.spin_share.setRange(0, 100)
        self.spin_share.setValue(0)
        nov1.addWidget(self.spin_share)
        nov1.addWidget(QLabel("Не менее новых:"))
        self.spin_new = SpinBox()
        self.spin_new.setRange(0, 100000)
        nov1.addWidget(self.spin_new)
        self.btn_novref = PushButton("↻")
        self.btn_novref.setToolTip("Обновить список сборок")
        self.btn_novref.clicked.connect(self.refresh_novelty)
        self.btn_novref.clicked.connect(self.refresh_strat_dims)
        nov1.addWidget(self.btn_novref)
        ll.addLayout(nov1)
        nov2 = QHBoxLayout()
        nov2.addWidget(QLabel("Исключить сборки:"))
        self.lst_exclude = ListWidget()
        self.lst_exclude.setFixedHeight(70)
        nov2.addWidget(self.lst_exclude, 1)
        nov2.addWidget(QLabel("Сохранить из:"))
        self.cmb_keep = ComboBox()
        nov2.addWidget(self.cmb_keep)
        nov2.addWidget(QLabel("минимум:"))
        self.spin_keep = SpinBox()
        self.spin_keep.setRange(0, 100000)
        nov2.addWidget(self.spin_keep)
        ll.addLayout(nov2)
        self.lbl_nov = QLabel("Исключённые: без требования — вон, с требованием — добираем.")
        self.lbl_nov.setToolTip("Без «не менее новых» записи исключённых сборок "
                                "убираются полностью; с требованием ими добираем остаток.")
        self.lbl_nov.setWordWrap(True)
        self.lbl_nov.setProperty("hint", True)
        ll.addWidget(self.lbl_nov)
        self.refresh_novelty()
        self.refresh_ff_dim()

        self.lbl_cov = QLabel("покрытие не проверено")
        self.lbl_cov.setWordWrap(True)
        ll.addWidget(self.lbl_cov)
        self.tbl_cov = TableWidget()
        self.tbl_cov.setColumnCount(5)
        self.tbl_cov.setHorizontalHeaderLabels(
            ["Измерение", "Значение", "Нужно", "Доступно", "Статус"])
        polish_table(self.tbl_cov)
        ll.addWidget(self.tbl_cov, 1)
        self.lbl_res = QLabel("")
        self.lbl_res.setWordWrap(True)
        ll.addWidget(self.lbl_res)

        side = CardWidget()
        side.setFixedWidth(280)
        sbox = QVBoxLayout(side)
        sbox.addWidget(StrongBodyLabel("Сводка сборки"))
        self.lbl_s_name = BodyLabel("—")
        self.lbl_s_name.setWordWrap(True)
        self.lbl_s_cfg = BodyLabel("")
        self.lbl_s_cfg.setWordWrap(True)
        self.lbl_s_comp_t = StrongBodyLabel("Состав (план)")
        self.lbl_s_comp = BodyLabel("—")
        self.lbl_s_comp.setWordWrap(True)
        self.donut_prev = DonutWidget()
        self.donut_prev.setMaximumHeight(120)
        self.lbl_s_cov = QLabel("покрытие не проверено")
        self.lbl_s_cov.setWordWrap(True)
        self.btn_go = PrimaryPushButton("Собрать выборку")
        self.btn_go.clicked.connect(self.build)
        for w in (self.lbl_s_name, self.lbl_s_cfg, self.lbl_s_comp_t,
                    self.lbl_s_comp, self.donut_prev, self.lbl_s_cov, self.btn_go):
            sbox.addWidget(w)
        sbox.addStretch(1)
        from PySide6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(left)
        body = QHBoxLayout()
        body.addWidget(scroll, 1)
        body.addWidget(side)
        layout.addLayout(body)
        self._adv = [
            self.lbl_seed_t, self.spin_seed,
            self.lbl_mode_t, self.cmb_mode,
            self.lbl_strat_t, self.cmb_strat, self.lbl_hint,
            self.lbl_div_t, self.spin_div, self.cb_rarity, self.lbl_mix_hint,
            self.lbl_prof_t, self.cmb_profiles,
            self.btn_psave, self.btn_pload, self.btn_pdel, self.btn_pref,
            self.lbl_nov_t, self.lbl_share_t, self.spin_share, self.spin_new, self.btn_novref,
            self.lst_exclude, self.cmb_keep, self.spin_keep, self.lbl_nov,
        ]
        self._manual = [self.lbl_q_t, self.tbl_q, self.btn_qrow, self.btn_del]
        self._formation = "manual"
        self._adv_on = True
        try:
            from PySide6.QtCore import QSettings
            saved = QSettings("DatasetBuilder", "DatasetBuilderV2").value(
                "requirements/advanced", False, type=bool)
        except Exception:  # noqa: BLE001
            saved = False
        self.chk_adv.blockSignals(True)
        self.chk_adv.setChecked(bool(saved))
        self.chk_adv.blockSignals(False)
        self._apply_mode_visibility()
        self.update_summary()
        self.refresh_pool_label()
        self._sync_formation_buttons()
        wrap_in_scroll(self)

    def showEvent(self, event):
        super().showEvent(event)
        # Списки измерений протухают после загрузки новых источников —
        # обновляем тихо, пользовательский ввод (квоты/фильтры) не трогаем.
        try:
            self.refresh_pool_label()
            self.refresh_strat_dims()
            self.refresh_novelty()
            self.refresh_profiles()
        except Exception:  # noqa: BLE001 — обновление списков не должно ронять экран
            pass

    def _apply_mode_visibility(self):
        on = self.chk_adv.isChecked()
        self._adv_on = on
        for w in self._adv:
            try:
                w.setVisible(on)
            except RuntimeError:  # noqa: BLE001 — виджет уже удалён
                pass
        self.lbl_mode_hint.setText("Всё управление открыто" if on else "Простой режим")
        self._refresh_manual_visibility()
        try:
            from PySide6.QtCore import QSettings
            QSettings("DatasetBuilder", "DatasetBuilderV2").setValue(
                "requirements/advanced", bool(on))
        except Exception:  # noqa: BLE001
            pass

    # --- квоты ---
    def pick_pool(self):
        from ui.pool_dialog import PoolDialog, pool_label
        dlg = PoolDialog(self._db_path, self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            self.lbl_pool.setText(pool_label(self._db_path))
            self.refresh_novelty()
            self.refresh_strat_dims()
            self.check_coverage()

    def refresh_pool_label(self):
        from ui.pool_dialog import pool_label
        self.lbl_pool.setText(pool_label(self._db_path))

    def _toggle_stratify(self):
        is_strat = self.cmb_mode.currentData() == "stratified"
        self.cmb_strat.setEnabled(is_strat)
        if is_strat and self.cmb_strat.count() == 0:
            self.refresh_strat_dims()

    def refresh_strat_dims(self):
        keep = self.cmb_strat.currentData()
        self.cmb_strat.blockSignals(True)
        self.cmb_strat.clear()
        for code, label in self._dims():
            self.cmb_strat.addItem(label, userData=code)
        if keep:
            self.cmb_strat.setCurrentIndex(max(0, self.cmb_strat.findData(keep)))
        self.cmb_strat.blockSignals(False)
        self.refresh_ff_dim()

    def refresh_ff_dim(self):
        """Обновить список колонки-наблюдения (фильтры/пресеты/советчик)."""
        keep = self.cmb_ff_dim.currentData() if hasattr(self, "cmb_ff_dim") else None
        self.cmb_ff_dim.blockSignals(True)
        self.cmb_ff_dim.clear()
        for code, label in self._dims():
            self.cmb_ff_dim.addItem(label, userData=code)
        if keep:
            self.cmb_ff_dim.setCurrentIndex(max(0, self.cmb_ff_dim.findData(keep)))
        self.cmb_ff_dim.blockSignals(False)
        self._fill_ff_vals()

    def _save_ff_checks(self):
        from PySide6.QtCore import Qt
        for dim, card in getattr(self, "_ff_cols", {}).items():
            try:
                vals = set()
                for r in range(card.lst.count()):
                    it = card.lst.item(r)
                    if it is not None and it.checkState() == Qt.Checked:
                        v = it.data(256)
                        if v:
                            vals.add(v)
                self._ff_checked[dim] = vals
            except RuntimeError:  # noqa: BLE001 — виджет уже удалён
                pass

    def _apply_ff_search(self):
        self._rebuild_ff_cols(
            (self.edit_ff_search.text() or "").strip() or None)

    @staticmethod
    def _ff_values(con, dim: str, needle: str | None) -> list[dict]:
        """Значения измерения: топ-200 без поиска, до 500 совпадений с поиском.
        Поиск идёт по всему измерению в БД, а не только по загруженным."""
        if needle:
            from core.normalize import norm_key as _nk
            esc = _nk(needle).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            rows = con.execute(
                "SELECT value_raw, value_norm, COUNT(*) c FROM pool_dim "
                "WHERE dim=? AND is_missing=0 AND value_norm LIKE '%' || ? || '%' "
                "ESCAPE '\\' GROUP BY value_norm ORDER BY c DESC, value_norm LIMIT 500",
                (dim, esc)).fetchall()
        else:
            rows = con.execute(
                "SELECT value_raw, value_norm, COUNT(*) c FROM pool_dim "
                "WHERE dim=? AND is_missing=0 "
                "GROUP BY value_norm ORDER BY c DESC, value_norm LIMIT 200",
                (dim,)).fetchall()
        return [{"raw": r[0], "count": r[2]} for r in rows]

    def _update_ff_badge(self, card):
        from PySide6.QtCore import Qt
        try:
            total = card.lst.count()
            checked = sum(1 for r in range(total)
                          if card.lst.item(r) is not None
                          and card.lst.item(r).checkState() == Qt.Checked)
        except RuntimeError:  # noqa: BLE001
            return
        card.badge.setText("Все" if checked == 0 else f"{checked} из {total}")

    def _on_ff_checked(self, dim: str):
        from PySide6.QtCore import Qt
        card = getattr(self, "_ff_cols", {}).get(dim)
        if card is None:
            return
        vals = set()
        try:
            for r in range(card.lst.count()):
                it = card.lst.item(r)
                if it is not None and it.checkState() == Qt.Checked:
                    v = it.data(256)
                    if v:
                        vals.add(v)
        except RuntimeError:  # noqa: BLE001
            return
        self._ff_checked[dim] = vals
        self._update_ff_badge(card)

    def _on_ff_dim_changed(self):
        self._highlight_ff_cols()
        self.check_coverage()

    def _highlight_ff_cols(self):
        dim = self.cmb_ff_dim.currentData() if hasattr(self, "cmb_ff_dim") else None
        for d, card in getattr(self, "_ff_cols", {}).items():
            try:
                card.setActive(d == dim)
            except RuntimeError:  # noqa: BLE001
                pass

    def _fill_ff_vals(self):
        self._rebuild_ff_cols(
            (self.edit_ff_search.text() or "").strip() or None)

    def _rebuild_ff_cols(self, needle: str | None):
        self._save_ff_checks()
        while self.ff_cols.count():
            item = self.ff_cols.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._ff_cols = {}
        dims = [code for code, _label in self._dims()]
        if not dims:
            hint = QLabel("пул пуст — загрузи источники.")
            hint.setProperty("hint", True)
            hint.setWordWrap(True)
            self.ff_cols.addWidget(hint)
            return
        try:
            con = connect(self._db_path)
            try:
                dists = {d: self._ff_values(con, d, needle) for d in dims}
            finally:
                con.close()
        except Exception:  # noqa: BLE001
            return
        label_of = dict(self._dims())
        for dim in dims:
            card = FilterColumnCard(dim, label_of.get(dim, dim))
            card._click_cb = lambda d=dim: self._select_data(self.cmb_ff_dim, d)
            card.lst.blockSignals(True)
            for row in dists[dim]:
                raw = row["raw"] or ""
                item = QListWidgetItem(f"{raw or '<пусто>'} — {row['count']}")
                item.setData(256, row["raw"])
                item.setToolTip(raw)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked
                                   if row["raw"] in self._ff_checked.get(dim, set())
                                   else Qt.Unchecked)
                card.lst.addItem(item)
            card.lst.blockSignals(False)
            card.lst.itemChanged.connect(lambda _it, d=dim: self._on_ff_checked(d))
            self._update_ff_badge(card)
            self.ff_cols.addWidget(card, 1)
            self._ff_cols[dim] = card
        self._highlight_ff_cols()

    def clear_filters(self):
        self.tbl_f.setRowCount(0)
        self._ff_checked = {}
        for card in getattr(self, "_ff_cols", {}).values():
            try:
                card.lst.blockSignals(True)
                for r in range(card.lst.count()):
                    it = card.lst.item(r)
                    if it is not None:
                        it.setCheckState(Qt.Unchecked)
                card.lst.blockSignals(False)
                self._update_ff_badge(card)
            except RuntimeError:  # noqa: BLE001
                pass
        self.check_coverage()

    def _upsert_in_filter(self, dim: str, vals: list[str]):
        for r in range(self.tbl_f.rowCount()):
            d = self.tbl_f.cellWidget(r, 0).currentData()
            op = self.tbl_f.cellWidget(r, 1).currentData()
            if d == dim and op == "in":
                self.tbl_f.cellWidget(r, 2).setText("; ".join(vals))
                return
        self.add_filter_row(dim=dim, op="in", value="; ".join(vals))

    def quick_add_filter(self):
        from PySide6.QtCore import Qt
        picked: dict[str, list[str]] = {}
        for dim, card in getattr(self, "_ff_cols", {}).items():
            try:
                vals = [card.lst.item(r).data(256)
                        for r in range(card.lst.count())
                        if card.lst.item(r) is not None
                        and card.lst.item(r).checkState() == Qt.Checked]
            except RuntimeError:  # noqa: BLE001
                continue
            vals = [v for v in vals if v]
            if vals:
                picked[dim] = vals
        if not picked:
            set_status(self.lbl_cov, "отметь хотя бы одно значение в колонках.", "warn")
            return
        for dim, vals in picked.items():
            self._upsert_in_filter(dim, vals)
        self.check_coverage()

    def _on_formation(self, button):
        names = ["all", "equal", "prop", "auto", "manual"]
        self.apply_formation(names[self.grp_formation.id(button)])

    def apply_formation(self, name: str):
        dim = self.cmb_ff_dim.currentData()
        kind = {"equal": "unif", "unif": "unif"}.get(name, "prop")
        if name == "all":
            self.tbl_q.setRowCount(0)
            self.fit_to_pool()
        elif name in ("equal", "prop", "unif"):
            if not dim:
                set_status(self.lbl_cov, "выбери колонку в «Что берём».", "warn")
                return
            self.tbl_q.setRowCount(0)
            self.apply_preset(kind, dim)
        elif name == "auto":
            if not dim:
                set_status(self.lbl_cov, "выбери колонку в «Что берём».", "warn")
                return
            self.auto_propose(dim)
        self._formation = name
        self._refresh_manual_visibility()
        self._sync_formation_buttons()

    def _sync_formation_buttons(self):
        names = {"all": self.rb_all, "equal": self.rb_equal, "prop": self.rb_prop,
                 "auto": self.rb_auto, "manual": self.rb_manual}
        if self._formation in names and not names[self._formation].isChecked():
            names[self._formation].blockSignals(True)
            names[self._formation].setChecked(True)
            names[self._formation].blockSignals(False)
        for name, card in getattr(self, "_formation_cards", {}).items():
            try:
                card.setSelected(self._formation == name)
            except RuntimeError:  # noqa: BLE001
                pass

    def _set_rare_tip(self, visible: bool, text: str):
        try:
            self.lbl_rare_tip.setText(text)
            self.lbl_rare_tip.setVisible(visible)
            self.btn_rare.setVisible(visible)
        except RuntimeError:  # noqa: BLE001
            pass

    def _enable_rarity(self):
        if not self.chk_adv.isChecked():
            self.chk_adv.setChecked(True)
        self.cb_rarity.setChecked(True)
        self.check_coverage()

    def _refresh_manual_visibility(self):
        show = self._adv_on or self._formation == "manual"
        for w in self._manual:
            try:
                w.setVisible(show)
            except RuntimeError:  # noqa: BLE001
                pass

    def auto_propose(self, dim: str | None = None):
        from core.advisor import propose
        from ui.proposal_dialog import ProposalDialog
        dim = dim if dim is not None else self.cmb_ff_dim.currentData()
        if not dim:
            set_status(self.lbl_cov, "выбери колонку в «Что берём».", "warn")
            return
        try:
            prof = self._profile()
            con = connect(self._db_path)
            try:
                out = propose(con, prof, dim)
            finally:
                con.close()
        except ValueError as e:
            set_status(self.lbl_cov, str(e), "warn")
            return
        except Exception as e:  # noqa: BLE001
            set_status(self.lbl_cov, f"ошибка: {e}", "block")
            return
        dlg = ProposalDialog(out["explanation"], self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            set_status(self.lbl_cov, "предложение отклонено — состав не менялся.", "info")
            return
        self.spin_size.setValue(out["target"])
        self.tbl_q.setRowCount(0)
        for q in out["quotas"]:
            self.add_quota_row(dim=q.dim, value=q.value, kind=q.kind, amount=q.amount)
        self.spin_div.setValue(out["div_threshold"])
        self.check_coverage()

    def fit_to_pool(self):
        """Не знаешь сколько надо — берём всё подходящее."""
        try:
            prof = self._profile()
            con = connect(self._db_path)
            try:
                cov = coverage(con, prof)
            finally:
                con.close()
        except ValueError as e:
            set_status(self.lbl_cov, str(e), "warn")
            return
        except Exception as e:  # noqa: BLE001
            set_status(self.lbl_cov, f"ошибка: {e}", "block")
            return
        self.spin_size.setValue(max(1, min(cov["eligible"], 100000)))
        self.check_coverage()
        set_status(self.lbl_res if hasattr(self, "lbl_res") else self.lbl_cov,
                   f"размер подогнан под пул: {cov['eligible']}. Жми «Собрать выборку».", "ok")

    def apply_preset(self, which: str, dim: str | None = None):
        from core.quota_presets import proportional, uniform
        if dim is None:
            dim = self.cmb_ff_dim.currentData()
        if not dim:
            set_status(self.lbl_cov, "выбери колонку в «Что берём».", "warn")
            return
        try:
            prof = self._profile()
            con = connect(self._db_path)
            try:
                if which == "prop":
                    quotas = proportional(con, prof, dim)
                else:
                    quotas = uniform(con, prof, dim)
            finally:
                con.close()
        except ValueError as e:
            set_status(self.lbl_cov, str(e), "warn")
            self.update_summary()
            return
        except Exception as e:  # noqa: BLE001
            set_status(self.lbl_cov, f"ошибка: {e}", "block")
            self.update_summary()
            return
        self.tbl_q.setRowCount(0)
        for q in quotas:
            self.add_quota_row(dim=q.dim, value=q.value, kind=q.kind, amount=q.amount)
        self.check_coverage()

    def _dims(self) -> list[tuple[str, str]]:
        try:
            con = connect(self._db_path)
            try:
                return list_dims(con)
            finally:
                con.close()
        except Exception:  # noqa: BLE001
            return []

    @staticmethod
    def _select_data(cmb, code):
        idx = cmb.findData(code)
        cmb.setCurrentIndex(idx if idx >= 0 else 0)

    @staticmethod
    def _select_text(cmb, value: str):
        for i in range(cmb.count()):
            if cmb.itemText(i) == value:
                cmb.setCurrentIndex(i)
                return
        cmb.addItem(value)
        cmb.setCurrentIndex(cmb.count() - 1)

    def _dim_combo(self, dims, on_change=None):
        cmb = ComboBox()
        for code, label in dims:
            cmb.addItem(label, userData=code)
        if on_change is not None:
            cmb.currentIndexChanged.connect(on_change)
        return cmb

    def _val_combo(self):
        cmb = ComboBox()
        cmb.setToolTip("значение из пула")
        return cmb

    def add_quota_row(self, dim=None, value=None, kind=None, amount=None,
                      dim2=None, value2=None):
        dims = self._dims()
        if not dims and dim is None:
            QMessageBox.information(self, "Пусто", "Сначала загрузи пул на вкладке «Источники».")
            return
        dims = dims or [(dim or dim2, dim_label(dim or dim2))]
        r = self.tbl_q.rowCount()
        self.tbl_q.insertRow(r)
        cmb_d = self._dim_combo(dims, lambda *_: self._fill_values(r, 0, 1))
        self.tbl_q.setCellWidget(r, 0, cmb_d)
        cmb_v = self._val_combo()
        self.tbl_q.setCellWidget(r, 1, cmb_v)
        cmb_d2 = self._dim_combo([("—", "")] + list(dims),
                                 lambda *_: self._fill_values(r, 2, 3))
        self.tbl_q.setCellWidget(r, 2, cmb_d2)
        cmb_v2 = self._val_combo()
        self.tbl_q.setCellWidget(r, 3, cmb_v2)
        cmb_k = ComboBox()
        for code, label in QUOTA_KINDS:
            cmb_k.addItem(label, userData=code)
        self.tbl_q.setCellWidget(r, 4, cmb_k)
        num = DoubleSpinBox()
        num.setRange(0, 100000)
        num.setValue(10)
        self.tbl_q.setCellWidget(r, 5, num)
        self._fill_values(r, 0, 1)
        if dim is not None:
            self._select_data(cmb_d, dim)
            self._fill_values(r, 0, 1)
        if value is not None:
            self._select_text(cmb_v, value)
        if dim2:
            self._select_data(cmb_d2, dim2)
            self._fill_values(r, 2, 3)
        if value2:
            self._select_text(cmb_v2, value2)
        if kind is not None:
            self._select_data(cmb_k, kind)
        if amount is not None:
            num.setValue(float(amount))

    def _fill_values(self, row: int, dcol: int = 0, vcol: int = 1):
        try:
            cmb_d = self.tbl_q.cellWidget(row, dcol)
            cmb_v = self.tbl_q.cellWidget(row, vcol)
            if cmb_d is None or cmb_v is None:
                return
            dim = cmb_d.currentData()
            if not dim:
                cmb_v.clear()
                return
            con = connect(self._db_path)
            try:
                vals = dim_values(con, dim)
            finally:
                con.close()
            cmb_v.clear()
            for v in vals[:200]:
                cmb_v.addItem(v)
        except Exception:  # noqa: BLE001
            pass

    def del_quota_row(self):
        r = self.tbl_q.currentRow()
        if r >= 0:
            self.tbl_q.removeRow(r)

    def add_filter_row(self, dim=None, op=None, value=None):
        dims = self._dims()
        if not dims and dim is None:
            QMessageBox.information(self, "Пусто", "Сначала загрузи пул на вкладке «Источники».")
            return
        dims = dims or [(dim, dim_label(dim))]
        r = self.tbl_f.rowCount()
        self.tbl_f.insertRow(r)
        cmb_d = ComboBox()
        for code, label in dims:
            cmb_d.addItem(label, userData=code)
        self.tbl_f.setCellWidget(r, 0, cmb_d)
        cmb_o = ComboBox()
        for code, label in FILTER_OPS_UI:
            cmb_o.addItem(label, userData=code)
        self.tbl_f.setCellWidget(r, 1, cmb_o)
        edit = LineEdit()
        edit.setPlaceholderText("значение; для списка — через «;»")
        self.tbl_f.setCellWidget(r, 2, edit)
        if dim is not None:
            self._select_data(cmb_d, dim)
        if op is not None:
            self._select_data(cmb_o, op)
        if value is not None:
            edit.setText(value)

    def del_filter_row(self):
        r = self.tbl_f.currentRow()
        if r >= 0:
            self.tbl_f.removeRow(r)

    @staticmethod
    def _split_list(text: str) -> list[str]:
        import re
        return [x.strip() for x in re.split(r"[;\n]+", text) if x.strip()]

    def refresh_novelty(self):
        checked = set(self._excluded_ids()) if hasattr(self, "lst_exclude") else set()
        keep_cur = self.cmb_keep.currentData() if hasattr(self, "cmb_keep") else None
        try:
            from storage.database import list_builds
            con = connect(self._db_path)
            try:
                builds = list_builds(con)
            finally:
                con.close()
        except Exception:  # noqa: BLE001
            builds = []
        self.lst_exclude.clear()
        for b in builds:
            item = QListWidgetItem(f"#{b['id']} {b['name']} — {b['picked']}")
            item.setData(256, b["id"])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if b["id"] in checked else Qt.Unchecked)
            self.lst_exclude.addItem(item)
        self.cmb_keep.blockSignals(True)
        self.cmb_keep.clear()
        self.cmb_keep.addItem("—", userData=None)
        for b in builds:
            self.cmb_keep.addItem(f"#{b['id']} {b['name']}", userData=b["id"])
        if keep_cur:
            idx = next((i for i in range(self.cmb_keep.count())
                        if self.cmb_keep.itemData(i) == keep_cur), 0)
            self.cmb_keep.setCurrentIndex(idx)
        self.cmb_keep.blockSignals(False)

    def _excluded_ids(self) -> list[int]:
        out = []
        for r in range(self.lst_exclude.count()):
            item = self.lst_exclude.item(r)
            if item.checkState() == Qt.Checked:
                out.append(item.data(256))
        return out

    # --- профили требований ---
    def refresh_profiles(self):
        cur = self.cmb_profiles.currentData() if hasattr(self, "cmb_profiles") else None
        try:
            con = connect(self._db_path)
            try:
                profiles = list_req_profiles(con)
            finally:
                con.close()
        except Exception:  # noqa: BLE001
            profiles = []
        self.cmb_profiles.blockSignals(True)
        self.cmb_profiles.clear()
        for p in profiles:
            self.cmb_profiles.addItem(p["name"], userData=p["id"])
        if cur:
            idx = next((i for i in range(self.cmb_profiles.count())
                        if self.cmb_profiles.itemData(i) == cur), 0)
            self.cmb_profiles.setCurrentIndex(idx)
        self.cmb_profiles.blockSignals(False)

    def save_profile(self):
        try:
            prof = self._profile()
            prof.validate()
        except ValueError as e:
            set_status(self.lbl_res, str(e), "warn")
            return
        name, ok = QInputDialog.getText(self, "Профиль требований", "Название:")
        if not ok or not name.strip():
            return
        try:
            con = connect(self._db_path)
            try:
                pid = save_req_profile(con, name.strip()[:80], profile_to_dict(prof))
            finally:
                con.close()
        except Exception as e:  # noqa: BLE001
            set_status(self.lbl_res, f"ошибка: {e}", "block")
            return
        self.refresh_profiles()
        idx = next((i for i in range(self.cmb_profiles.count())
                    if self.cmb_profiles.itemData(i) == pid), 0)
        self.cmb_profiles.setCurrentIndex(idx)
        set_status(self.lbl_res, f"профиль «{name.strip()[:80]}» сохранён.", "ok")

    def load_profile(self):
        pid = self.cmb_profiles.currentData()
        if not pid:
            set_status(self.lbl_res, "выбери профиль.", "warn")
            return
        try:
            con = connect(self._db_path)
            try:
                data = load_req_profile(con, pid)
            finally:
                con.close()
            prof = profile_from_dict(data)
            prof.validate()
        except ValueError as e:
            set_status(self.lbl_res, str(e), "warn")
            return
        except Exception as e:  # noqa: BLE001
            set_status(self.lbl_res, f"ошибка: {e}", "block")
            return
        self.apply_profile(prof)

    def delete_profile(self):
        pid = self.cmb_profiles.currentData()
        if not pid:
            return
        go = QMessageBox.question(self, "Удалить", "Удалить профиль?",
                                  QMessageBox.Yes | QMessageBox.No)
        if go != QMessageBox.Yes:
            return
        try:
            con = connect(self._db_path)
            try:
                delete_req_profile(con, pid)
            finally:
                con.close()
        except Exception as e:  # noqa: BLE001
            set_status(self.lbl_res, f"ошибка: {e}", "block")
            return
        self.refresh_profiles()

    def apply_profile(self, prof: BuildProfile):
        advanced = bool(prof.filters or prof.exclude_builds or prof.keep_build
                        or prof.keep_min or prof.min_new or prof.div_threshold
                        or prof.rarity or prof.dedupe != "off" or prof.max_source_pct
                        or prof.mode not in ("quota", "random") or prof.stratify_dim)
        self.chk_adv.blockSignals(True)
        self.chk_adv.setChecked(self.chk_adv.isChecked() or advanced)
        self.chk_adv.blockSignals(False)
        self._apply_mode_visibility()
        self.spin_size.setValue(prof.target_size)
        self.spin_seed.setValue(prof.seed)
        self._select_data(self.cmb_mode, prof.mode)
        self.refresh_strat_dims()
        if prof.stratify_dim:
            self._select_data(self.cmb_strat, prof.stratify_dim)
        self._toggle_stratify()
        self.spin_div.setValue(prof.div_threshold)
        self.cb_rarity.setChecked(prof.rarity)
        self._select_data(self.cmb_dedupe, prof.dedupe)
        self.tbl_q.setRowCount(0)
        for q in prof.quotas:
            self.add_quota_row(dim=q.dim, value=q.value, kind=q.kind, amount=q.amount,
                               dim2=q.dim2 or None, value2=q.value2 or None)
        self.tbl_f.setRowCount(0)
        for f in prof.filters:
            val = "; ".join(f.values) if f.op in ("in", "notin") else f.value
            self.add_filter_row(dim=f.dim, op=f.op, value=val)
        self.spin_share.setValue(prof.max_source_pct)
        self.spin_new.setValue(prof.min_new)
        self.refresh_novelty()
        for r in range(self.lst_exclude.count()):
            item = self.lst_exclude.item(r)
            item.setCheckState(Qt.Checked if item.data(256) in set(prof.exclude_builds)
                               else Qt.Unchecked)
        self._select_data(self.cmb_keep, prof.keep_build)
        self.spin_keep.setValue(prof.keep_min)
        self._formation = "manual"
        self._refresh_manual_visibility()
        self._sync_formation_buttons()
        set_status(self.lbl_cov, "профиль загружен — проверь покрытие.", "info")
        self.check_coverage()

    def _profile(self) -> BuildProfile:
        quotas = []
        for r in range(self.tbl_q.rowCount()):
            dim = self.tbl_q.cellWidget(r, 0).currentData()
            val_widget = self.tbl_q.cellWidget(r, 1)
            val = val_widget.currentText().strip()
            dim2box = self.tbl_q.cellWidget(r, 2)
            dim2 = dim2box.currentData() if dim2box.currentIndex() > 0 else ""
            val2_widget = self.tbl_q.cellWidget(r, 3)
            val2 = val2_widget.currentText().strip()
            kind = self.tbl_q.cellWidget(r, 4).currentData()
            amt = self.tbl_q.cellWidget(r, 5).value()
            if dim and val:
                quotas.append(Quota(dim=dim, value=val, kind=kind, amount=amt,
                                    dim2=dim2, value2=val2 if dim2 else ""))
        filters = []
        for r in range(self.tbl_f.rowCount()):
            dim = self.tbl_f.cellWidget(r, 0).currentData()
            op = self.tbl_f.cellWidget(r, 1).currentData()
            val = self.tbl_f.cellWidget(r, 2).text().strip()
            if not dim:
                continue
            if op in ("in", "notin"):
                filters.append(Filter(dim=dim, op=op, values=self._split_list(val)))
            else:
                filters.append(Filter(dim=dim, op=op, value=val))
        if getattr(self, "_adv_on", True):
            mode = self.cmb_mode.currentData() or "quota"
            strat = (self.cmb_strat.currentData()
                     if self.cmb_mode.currentData() == "stratified" else "")
            seed = self.spin_seed.value()
            div = self.spin_div.value()
            rare = self.cb_rarity.isChecked()
            dedupe = self.cmb_dedupe.currentData() or "off"
            share = self.spin_share.value()
            excl = self._excluded_ids()
            new_min = self.spin_new.value()
            keep = self.cmb_keep.currentData()
            keep_min = self.spin_keep.value()
        else:
            # простой режим: размер + фильтры-п picked + баланс;
            # тонкости (новизна, разнообразие, доли, дубли) — в продвинутом
            mode = "quota" if quotas else "random"
            strat, seed, div, rare = "", 0, 0.0, False
            dedupe = self.cmb_dedupe.currentData() or "off"
            share, excl, new_min, keep, keep_min = 0.0, [], 0, None, 0
        return BuildProfile(target_size=self.spin_size.value(),
                            seed=seed,
                            mode=mode,
                            stratify_dim=strat,
                            div_threshold=div,
                            rarity=rare,
                            dedupe=dedupe,
                            filters=filters,
                            quotas=quotas,
                            max_source_pct=share,
                            exclude_builds=excl,
                            min_new=new_min,
                            keep_build=keep,
                            keep_min=keep_min)

    # --- покрытие и сборка ---
    def open_wizard(self):
        from ui.build_wizard import WizardDialog
        dlg = WizardDialog(self._db_path, self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        res = dlg.result or {}
        if res.get("action") == "advanced":
            self.chk_adv.setChecked(True)
            self.apply_formation("manual")
            set_status(self.lbl_res, "мастер закрыт — настраивай вручную.", "info")
        elif res.get("action") == "built":
            self.refresh_novelty()
            self.check_coverage()
            set_status(self.lbl_res,
                       f"мастер собрал {res['picked']} (id сборки {res['bid']}), "
                       f"недобор {res.get('short', 0)}. Состав — на вкладке "
                       "«3 · Сборка и экспорт».",
                       "warn" if res.get("short", 0) else "ok")

    def check_coverage(self):
        try:
            prof = self._profile()
            prof.validate()
            con = connect(self._db_path)
            try:
                n_all = con.execute("SELECT COUNT(*) FROM source").fetchone()[0]
                n_on = con.execute("SELECT COUNT(*) FROM source WHERE in_pool=1").fetchone()[0]
                cov = coverage(con, prof)
                rare_n = con.execute(
                    "SELECT COUNT(*) FROM (SELECT 1 FROM pool_dim "
                    "WHERE is_missing=0 GROUP BY dim, value_norm "
                    "HAVING COUNT(*)=1)").fetchone()[0]
            finally:
                con.close()
        except ValueError as e:
            set_status(self.lbl_cov, str(e), "warn")
            self._set_rare_tip(False, "")
            self.update_summary()
            return
        except Exception as e:  # noqa: BLE001
            set_status(self.lbl_cov, f"ошибка: {e}", "block")
            self._set_rare_tip(False, "")
            self.update_summary()
            return
        KIND_RU = {"min": "не менее", "max": "не более",
                   "exact": "ровно", "percent": "%"}
        cells = cov["cells"]
        # Режим «Всё подходящее»: квот нет — таблица была пустой и казалось,
        # что «ничего не показывает». Показываем разбивку по текущей колонке.
        info_mode = False
        info_dim = None
        info_dist: list = []
        if not cells and cov["eligible"] > 0:
            try:
                _dim = self.cmb_ff_dim.currentData() if hasattr(self, "cmb_ff_dim") else None
            except Exception:  # noqa: BLE001
                _dim = None
            if _dim:
                info_mode = True
                info_dim = _dim
                try:
                    from core.filter_service import apply_filters as _af
                    from core.filter_service import build_items_union as _union
                    con2 = connect(self._db_path)
                    try:
                        elig = _af(con2, prof.filters)
                        old2 = _union(con2, prof.exclude_builds)
                        if old2 and prof.min_new == 0:
                            _all = {r[0] for r in con2.execute(
                                "SELECT id FROM pool_candidate").fetchall()}
                            elig_set = (set(_all) if elig is None else set(elig)) - old2
                        else:
                            if elig is None:
                                elig_set = {r[0] for r in con2.execute(
                                    "SELECT id FROM pool_candidate").fetchall()}
                            else:
                                elig_set = set(elig)
                        _rows = con2.execute(
                            "SELECT candidate_id, value_raw, value_norm FROM pool_dim "
                            "WHERE dim=? AND is_missing=0", (_dim,)).fetchall()
                        _agg: dict = {}
                        for _cid, _raw, _norm in _rows:
                            if _cid not in elig_set:
                                continue
                            _cell = _agg.setdefault(_norm, [_raw, 0])
                            _cell[1] += 1
                        info_dist = sorted(_agg.items(), key=lambda kv: -kv[1][1])
                    finally:
                        con2.close()
                except Exception:  # noqa: BLE001
                    info_dist = []
        if info_mode:
            self.tbl_cov.setRowCount(len(info_dist))
            for r, (_norm, (_raw, _cnt)) in enumerate(info_dist):
                self.tbl_cov.setItem(r, 0, QTableWidgetItem(dim_label(info_dim)))
                self.tbl_cov.setItem(r, 1, QTableWidgetItem(str(_raw or "")))
                self.tbl_cov.setItem(r, 2, QTableWidgetItem(f"все {_cnt}"))
                self.tbl_cov.setItem(r, 3, QTableWidgetItem(str(_cnt)))
                self.tbl_cov.setItem(r, 4, QTableWidgetItem("взять всё"))
        else:
            self.tbl_cov.setRowCount(len(cells))
            for r, c in enumerate(cells):
                dim_txt = dim_label(c["dim"])
                if c.get("dim2"):
                    dim_txt += " + " + dim_label(c["dim2"])
                self.tbl_cov.setItem(r, 0, QTableWidgetItem(dim_txt))
                val_txt = str(c["value"] or "")
                if c.get("value2"):
                    val_txt += " + " + str(c["value2"])
                self.tbl_cov.setItem(r, 1, QTableWidgetItem(val_txt))
                need = c["need"]
                need_txt = f"{KIND_RU.get(c['kind'], c['kind'])} " \
                    f"{int(need) if float(need).is_integer() else need}"
                self.tbl_cov.setItem(r, 2, QTableWidgetItem(need_txt))
                self.tbl_cov.setItem(r, 3, QTableWidgetItem(str(c["avail"])))
                st = {"ok": "выполнимо", "short": "ДЕФИЦИТ", "warn": "предупреждение"}[c["status"]]
                self.tbl_cov.setItem(r, 4, QTableWidgetItem(st))
        def _short(v: str, n: int = 44) -> str:
            v = str(v or "")
            return v if len(v) <= n else v[: n - 1] + "…"

        def _num(x) -> str:
            return str(int(x)) if float(x).is_integer() else str(x)

        def _dot(color: str) -> str:
            return f'<font color="{color}">■</font> '

        comp_lines = []
        legend: list[tuple[str, float, str]] = []  # (color, frac, tip)
        if cells and cov["target"] > 0:
            takes = sorted(
                ((c["value"], min(c["need"], c["avail"]), c["need"]) for c in cells),
                key=lambda t: (-t[1], str(t[0])))
            takes = [(v, t, n) for v, t, n in takes if t > 0]
            head, tail = takes[:20], takes[20:]
            for i, (v, t, n) in enumerate(head):
                color = PALETTE[i % len(PALETTE)]
                comp_lines.append(
                    f"{_dot(color)}{_short(v)}: {_num(t)}/{_num(n)}")
                legend.append((color, t / cov["target"],
                               f"{v}: взять {_num(t)} из {_num(n)}"))
            if tail:
                rest = sum(t for _v, t, _n in tail)
                comp_lines.append(f"{_dot('#9AA0A6')}Остальные ({len(tail)}): "
                                  f"{_num(rest)}")
                legend.append(("#9AA0A6", rest / cov["target"],
                               f"Остальные ({len(tail)}): {_num(rest)}"))
        elif info_mode and info_dist and cov["eligible"] > 0:
            head, tail = info_dist[:20], info_dist[20:]
            for i, (_norm, (_raw, _cnt)) in enumerate(head):
                color = PALETTE[i % len(PALETTE)]
                comp_lines.append(f"{_dot(color)}{_short(_raw)}: {_cnt}")
                legend.append((color, _cnt / cov["eligible"], f"{_raw}: {_cnt}"))
            if tail:
                rest = sum(_cnt for _norm, (_raw, _cnt) in tail)
                comp_lines.append(f"{_dot('#9AA0A6')}Остальные ({len(tail)}): "
                                  f"{rest}")
                legend.append(("#9AA0A6", rest / cov["eligible"],
                               f"Остальные ({len(tail)}): {rest}"))
        self.lbl_s_comp.setText("<br>".join(comp_lines) if comp_lines else "—")
        dark = saved_theme() == "dark"
        if legend:
            total = cov["target"] if cells else cov["eligible"]
            center_n = _num(total) if cells else str(total)
            self.donut_prev.set_parts(
                [(c, f) for c, f, _t in legend],
                center=f"{center_n}\nплан", dark=dark)
        else:
            self.donut_prev.set_parts([], center="", dark=dark)
        if rare_n > 0 and not prof.rarity and prof.div_threshold == 0:
            self._set_rare_tip(True, f"совет: в пуле {rare_n} редких значений "
                                     "(встречаются 1 раз) — возьми их первыми.")
        else:
            self._set_rare_tip(False, "")
        if cov["feasible"]:
            if info_mode:
                base = (f"Всё подходящее: будет взято {cov['eligible']} "
                        f"— разбивка по «{dim_label(info_dim)}» ниже. Жми «Собрать выборку».")
            else:
                base = f"пригодных {cov['eligible']} под цель {cov['target']} — собирай."
            kind = "ok"
        else:
            bad = "; ".join(
                f"{dim_label(c['dim'])}={c['value']}: нужно {c['need']}, есть {c['avail']}"
                for c in cov["impossible"])
            base = (f"НЕВЫПОЛНИМО: {bad}" if bad
                    else f"мало пригодных: {cov['eligible']} < {cov['target']}")
            kind = "block"
        if cov.get("excluded"):
            base += f" Исключено прошлых: {cov['excluded']}, новых доступно: {cov['new_avail']}."
        if n_on < n_all:
            base += f" В пуле источников: {n_on} из {n_all} (остальные выключены)."
        if cov["eligible"] == 0:
            base = "пул пуст: включи хотя бы один источник на вкладке «Источники»."
            kind = "block"
        set_status(self.lbl_cov, base, kind)
        self.lbl_match.setText(f"Подходящих записей: {cov['eligible']}")
        self.update_summary(cov)
        self.refresh_pool_label()

    def build(self):
        try:
            prof = self._profile()
            prof.validate()
            if not getattr(self, "_adv_on", True):
                import random as _random
                prof.seed = _random.randrange(0, 1000000)
            con = connect(self._db_path)
            try:
                total = con.execute("SELECT COUNT(*) FROM candidate").fetchone()[0]
                if total == 0:
                    set_status(self.lbl_res,
                               "пул пуст — сначала загрузи файлы на вкладке «Источники».",
                               "warn")
                    return
                res = sample(con, prof)
                name = self.edit_name.text().strip()[:80]
                note = self.edit_desc.text().strip()[:200]
                bid = save_build(con, name or f"Сборка {prof.target_size}/{prof.seed}",
                                 prof, res["items"], res["reasons"], res.get("short", 0),
                                 note=note)
            finally:
                con.close()
        except ValueError as e:
            set_status(self.lbl_res, str(e), "warn")
            return
        except Exception as e:  # noqa: BLE001
            set_status(self.lbl_res, f"ошибка: {e}", "block")
            return
        extra = ""
        if res.get("pinned_skipped"):
            extra += f" Закреплённых вне фильтров: {len(res['pinned_skipped'])}."
        if res.get("new_short"):
            extra += f" Не хватило новых: {res['new_short']}."
        if res.get("kept"):
            extra += f" Сохранено старых: {len(res['kept'])}."
        if res.get("diversity_skipped"):
            extra += f" Отсеяно похожих: {res['diversity_skipped']}."
        if res.get("dupe_skipped"):
            extra += f" Отсеяно дублей: {res['dupe_skipped']}."
        set_status(self.lbl_res,
                     f"собрано {len(res['items'])} (id сборки {bid}), "
                     f"недобор {res.get('short', 0)}. Причины записаны к каждой записи." + extra,
                     "warn" if (res.get('short', 0) or res.get('new_short')) else "ok")
        self.check_coverage()

    def update_summary(self, cov: dict | None = None):
        try:
            prof = self._profile()
        except ValueError:
            self.lbl_s_name.setText("—")
            self.lbl_s_cfg.setText("")
            return
        name = self.edit_name.text().strip() or f"Сборка {prof.target_size}/{prof.seed}"
        self.lbl_s_name.setText(name)
        mode = {"quota": "по квотам", "random": "случайный",
                "stratified": "стратификация", "mixed": "смешанный"}.get(prof.mode, prof.mode)
        dd_ru = {"off": "как есть", "exact": "без дублей",
                 "exact_new": "только новое"}.get(prof.dedupe, prof.dedupe)
        self.lbl_s_cfg.setText(
            f"Цель {prof.target_size} · вариант {prof.seed} · {mode}\n"
            f"Квот {len(prof.quotas)} · фильтров {len(prof.filters)}\n"
            f"Доля источника {prof.max_source_pct or '—'}% · "
            f"новых ≥{prof.min_new or '—'}\n"
            f"Разнообразие {prof.div_threshold or 'выкл'} · "
            f"редкие {'да' if prof.rarity else 'нет'} · дубли: {dd_ru}")
        if cov is None:
            set_status(self.lbl_s_cov, "покрытие не проверено", "info")
            self.lbl_s_comp.setText("—")
        elif cov["feasible"]:
            set_status(self.lbl_s_cov, f"готово: пригодных {cov['eligible']}", "ok")
        else:
            set_status(self.lbl_s_cov, "есть дефицит — смотри покрытие", "warn")
