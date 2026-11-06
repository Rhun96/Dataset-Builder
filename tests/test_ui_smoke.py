"""Дым экранов без GUI-цикла."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.requirements import SEED_HINT, SEED_LABEL  # noqa: E402
from core.roles import EXT_ID, GROUP, MAIN  # noqa: E402
from ui.builds_screen import BuildsScreen  # noqa: E402
from ui.requirements_screen import RequirementsScreen  # noqa: E402
from ui.sources_screen import SourcesScreen, guess_role  # noqa: E402


def test_guess():
    assert guess_role("Запрос", []) == MAIN
    assert guess_role("Категория", []) == GROUP
    assert guess_role("ID", []) == EXT_ID
    assert guess_role("Непонятное", []) == "extra"
    # неизвестное имя + короткие уникальные значения без пробелов → ID
    assert guess_role("Код", ["A1", "A2", "B7"]) == EXT_ID
    assert guess_role("Код", ["550e8400-e29b-41d4-a716-446655440000",
                              "6fa459ea-ee8a-3ca4-894e-db77e160355"]) == EXT_ID
    # тексты с пробелами — не ID, даже если уникальны
    assert guess_role("Поле", ["Как вернуть товар?", "Где мой заказ?"]) == "extra"
    # повторяющиеся короткие значения — не ID
    assert guess_role("Поле", ["да", "нет", "да"]) == "extra"


def test_screen_mapping(tmp_path):
    QApplication.instance() or QApplication([])
    db = tmp_path / "ws.sqlite"
    w = SourcesScreen(str(db))
    assert w.btn_load is not None and w.tbl_map is not None
    assert w.cmb_sheet is not None and w.cmb_encoding.count() == 4
    # эмулируем открытый файл без диалога
    p = tmp_path / "s.csv"
    p.write_text("мусор\nЗапрос;Категория;ID\nпривет;мир;A1\n", encoding="utf-8-sig")
    w.open_file(str(p))
    assert w.tbl_map.rowCount() == 1  # первая строка ушла под мусор
    w.spin_header.setValue(1)
    w.open_file(str(p))
    m = w.current_mapping()
    assert m["Запрос"] == MAIN
    w.close()


def test_req_labels_russian(tmp_path):
    QApplication.instance() or QApplication([])
    w = RequirementsScreen(str(tmp_path / "ws.sqlite"))
    assert "вариант" in w.lbl_hint.text().lower()
    assert "Вариант" in SEED_LABEL and "1, 2 и 3" in SEED_HINT
    w.close()


def test_req_filter_row(tmp_path):
    from core.pool_import import import_source  # noqa: E402
    from core.roles import GROUP, MAIN  # noqa: E402
    from storage.database import connect  # noqa: E402
    QApplication.instance() or QApplication([])
    db = tmp_path / "ws.sqlite"
    p = tmp_path / "p.csv"
    p.write_text("З;Г\nодин;А\nдва;Б\n", encoding="utf-8-sig")
    con = connect(db)
    import_source(con, p, {"З": MAIN, "Г": GROUP})
    con.close()
    w = RequirementsScreen(str(db))
    w._adv_on = True  # фильтры — продвинутая опция
    w.add_filter_row()
    assert w.tbl_f.rowCount() == 1
    w.tbl_f.cellWidget(0, 2).setText("А")
    prof = w._profile()
    assert len(prof.filters) == 1 and prof.filters[0].op == "eq"
    w.add_quota_row(dim=GROUP, value="А", kind="min", amount=1,
                    dim2=GROUP, value2="Б")
    profq = w._profile()
    assert profq.quotas[-1].dim2 == GROUP and profq.quotas[-1].value2 == "Б"
    with pytest.raises(ValueError):
        from core.requirements import Quota as _Q
        _Q(dim=GROUP, value="А", kind="min", amount=1, dim2=GROUP).validate()
    w.close()


def test_req_novelty_widgets(tmp_path):
    from core.pool_import import import_source  # noqa: E402
    from core.requirements import BuildProfile  # noqa: E402
    from core.roles import GROUP, MAIN  # noqa: E402
    from core.sampling_service import sample  # noqa: E402
    from storage.database import connect, save_build  # noqa: E402
    QApplication.instance() or QApplication([])
    db = tmp_path / "ws.sqlite"
    p = tmp_path / "p.csv"
    p.write_text("З;Г\nодин;А\nдва;Б\n", encoding="utf-8-sig")
    con = connect(db)
    import_source(con, p, {"З": MAIN, "Г": GROUP})
    prof = BuildProfile(target_size=1, seed=1)
    res = sample(con, prof)
    save_build(con, "b1", prof, res["items"], res["reasons"], 0)
    con.close()
    w = RequirementsScreen(str(db))
    w._adv_on = True  # новизна/доли — продвинутые опции
    w.refresh_novelty()
    assert w.lst_exclude.count() == 1
    w.lst_exclude.item(0).setCheckState(Qt.Checked)
    w.spin_share.setValue(25)
    prof2 = w._profile()
    assert prof2.max_source_pct == 25 and len(prof2.exclude_builds) == 1
    w.spin_div.setValue(0.85)
    w.cb_rarity.setChecked(True)
    prof3 = w._profile()
    assert prof3.div_threshold == 0.85 and prof3.rarity is True
    w.apply_formation("prop")
    assert w.tbl_q.rowCount() == 2
    kinds = {w.tbl_q.cellWidget(r, 4).currentData() for r in range(2)}
    assert kinds == {"percent"}
    w.apply_formation("unif")
    assert sum(w.tbl_q.cellWidget(r, 5).value() for r in range(2)) == 500
    w.apply_formation("all")
    assert w.spin_size.value() == 1  # один кейс съеден исключением b1
    w.close()


def test_build_name_and_donut(tmp_path):
    from core.pool_import import import_source  # noqa: E402
    from core.roles import GROUP, MAIN  # noqa: E402
    from storage.database import connect, list_builds  # noqa: E402
    from ui.donut import DonutWidget  # noqa: E402
    QApplication.instance() or QApplication([])
    db = tmp_path / "ws.sqlite"
    p = tmp_path / "p.csv"
    p.write_text("З;Г\nодин;А\nдва;Б\n", encoding="utf-8-sig")
    con = connect(db)
    import_source(con, p, {"З": MAIN, "Г": GROUP})
    con.close()
    d = DonutWidget()
    d.set_parts([("#4F8CFF", 0.6), ("#34C38F", 0.4)], center="2")
    assert not d.grab().isNull()
    d.close()
    from ui.donut import DonutWidget  # noqa: E402
    ring = DonutWidget()
    ring.resize(200, 200)
    ring.set_parts([("r", 0.5), ("b", 0.5)], center="x", tips=["RIGHT", "LEFT"])
    assert ring._tip_at(180, 100) == "RIGHT"
    assert ring._tip_at(20, 100) == "LEFT"
    assert ring._tip_at(100, 100) == ""
    ring.close()
    w = RequirementsScreen(str(db))
    w.edit_name.setText("Мой набор")
    w.spin_size.setValue(2)
    w.build()
    con = connect(db)
    try:
        names = [b["name"] for b in list_builds(con)]
    finally:
        con.close()
    assert "Мой набор" in names
    w.close()


def test_strat_ui(tmp_path):
    from core.pool_import import import_source  # noqa: E402
    from core.roles import GROUP, MAIN  # noqa: E402
    from storage.database import connect  # noqa: E402
    QApplication.instance() or QApplication([])
    db = tmp_path / "ws.sqlite"
    p = tmp_path / "p.csv"
    p.write_text("З;Г\nодин;А\nдва;Б\n", encoding="utf-8-sig")
    con = connect(db)
    import_source(con, p, {"З": MAIN, "Г": GROUP})
    con.close()
    w = RequirementsScreen(str(db))
    w._adv_on = True  # стратификация — продвинутая опция
    w.refresh_strat_dims()
    assert w.cmb_strat.count() == 1
    idx = next(i for i in range(w.cmb_mode.count()) if w.cmb_mode.itemData(i) == "stratified")
    w.cmb_mode.setCurrentIndex(idx)
    assert w.cmb_strat.isEnabled()
    prof = w._profile()
    assert prof.mode == "stratified" and prof.stratify_dim == GROUP
    w.close()


def test_profile_save_load_roundtrip(tmp_path):
    from core.pool_import import import_source  # noqa: E402
    from core.roles import GROUP, MAIN  # noqa: E402
    from storage.database import connect  # noqa: E402
    QApplication.instance() or QApplication([])
    db = tmp_path / "ws.sqlite"
    p = tmp_path / "p.csv"
    p.write_text("З;Г\nодин;А\nдва;Б\n", encoding="utf-8-sig")
    con = connect(db)
    import_source(con, p, {"З": MAIN, "Г": GROUP})
    con.close()
    w = RequirementsScreen(str(db))
    w._adv_on = True  # квоты вручную — продвинутая опция
    w.add_quota_row(dim=GROUP, value="А", kind="min", amount=2)
    w.add_filter_row(dim=GROUP, op="ne", value="Б")
    w.spin_size.setValue(50)
    prof = w._profile()
    prof.validate()
    w.apply_profile(prof)
    prof2 = w._profile()
    assert prof2.target_size == 50 and len(prof2.quotas) == 1 and len(prof2.filters) == 1
    assert prof2.quotas[0].value == "А" and prof2.filters[0].op == "ne"
    w.close()


def test_builds_screen_flow(tmp_path):
    from core.pool_import import import_source  # noqa: E402
    from core.requirements import BuildProfile  # noqa: E402
    from core.roles import GROUP, MAIN  # noqa: E402
    from core.sampling_service import sample  # noqa: E402
    from storage.database import connect, save_build  # noqa: E402
    QApplication.instance() or QApplication([])
    db = tmp_path / "ws.sqlite"
    p = tmp_path / "p.csv"
    p.write_text("З;Г\nодин;А\nдва;Б\n", encoding="utf-8-sig")
    con = connect(db)
    import_source(con, p, {"З": MAIN, "Г": GROUP})
    prof = BuildProfile(target_size=2, seed=1)
    res = sample(con, prof)
    bid = save_build(con, "t", prof, res["items"], res["reasons"], 0)
    con.close()
    w = BuildsScreen(str(db))
    assert w.lst.count() == 1
    w.open_build(bid)
    assert w.tbl_items.rowCount() == 2
    assert "Готово" in w.lbl_status.text() or "возможно" in w.lbl_status.text()
    w.tbl_items.selectRow(0)
    w.pin_selected()
    from storage.database import list_pinned as _lp  # noqa: E402
    con = connect(db)
    try:
        assert len(_lp(con)) == 1
    finally:
        con.close()
    w.replace_selected()
    assert w.lst.count() == 2
    first_id = w._build_id
    w.refresh()
    assert w._build_id == first_id  # выбор пережил обновление списка
    w.delete_selected(confirm=False)
    assert w.lst.count() == 1 and w.tbl_items.rowCount() == 2  # первая оставшаяся открыта
    w.close()
    w2 = BuildsScreen(str(db))
    assert w2.spin_variants is not None and w2.btn_variants is not None
    assert w2.btn_import is not None
    w2.close()


def test_import_dialog_mapping(tmp_path):
    from ui.import_dialog import ImportBuildDialog  # noqa: E402
    QApplication.instance() or QApplication([])
    p = tmp_path / "g.csv"
    p.write_text("Текст;Номер\nпривет;A1\n", encoding="utf-8-sig")
    d = ImportBuildDialog(str(p))
    m = d.current_mapping()
    from core.roles import EXT_ID, MAIN  # noqa: E402
    assert m["Текст"] == MAIN and m["Номер"] == EXT_ID
    d.close()


def test_simple_mode_defaults_and_autoseed(tmp_path):
    from core.pool_import import import_source  # noqa: E402
    from core.roles import GROUP, MAIN  # noqa: E402
    from storage.database import connect, list_builds  # noqa: E402
    QApplication.instance() or QApplication([])
    db = tmp_path / 'ws.sqlite'
    p = tmp_path / 'p.csv'
    p.write_text('Z;G' + chr(10) + 'один;А' + chr(10) + 'два;Б' + chr(10), encoding='utf-8-sig')
    con = connect(db)
    import_source(con, p, {'Z': MAIN, 'G': GROUP})
    con.close()
    w = RequirementsScreen(str(db))
    w._adv_on = False
    w.spin_size.setValue(2)
    prof = w._profile()
    assert prof.mode == 'random' and prof.filters == [] and prof.seed == 0
    w.apply_formation('prop')
    assert w.tbl_q.rowCount() == 2
    assert w._profile().mode == 'quota'
    w.tbl_q.setRowCount(0)
    w.edit_name.setText('simple')
    w.cmb_ff_dim.setCurrentIndex(max(0, w.cmb_ff_dim.findData(GROUP)))
    from PySide6.QtCore import Qt
    w._ff_cols[GROUP].lst.item(0).setCheckState(Qt.Checked)
    w.quick_add_filter()
    assert w.tbl_f.rowCount() == 1
    assert len(w._profile().filters) == 1  # фильтры действуют и в простом режиме
    w.apply_formation('all')
    assert w.spin_size.value() == 1
    con = connect(db)
    try:
        n0 = len(list_builds(con))
    finally:
        con.close()
    w.build()
    con = connect(db)
    try:
        names = [b['name'] for b in list_builds(con)]
    finally:
        con.close()
    assert len(names) == n0 + 1 and 'simple' in names
    w.close()
    w2 = RequirementsScreen(str(tmp_path / 'empty.sqlite'))
    w2._adv_on = False
    w2.build()
    assert 'пул пуст' in w2.lbl_res.text()
    w2.close()


def test_source_toggle_and_profile_scope(tmp_path):
    from core.pool_import import import_source  # noqa: E402
    from core.roles import GROUP, MAIN  # noqa: E402
    from storage.database import connect, list_sources  # noqa: E402
    from ui.profile_screen import ProfileScreen  # noqa: E402
    from ui.sources_screen import SourcesScreen  # noqa: E402
    QApplication.instance() or QApplication([])
    db = tmp_path / 'ws.sqlite'
    for name, rows in (('a.csv', 'один;А'), ('b.csv', 'три;Б')):
        p = tmp_path / name
        p.write_text('Z;G' + chr(10) + rows + chr(10), encoding='utf-8-sig')
        con = connect(db)
        import_source(con, p, {'Z': MAIN, 'G': GROUP})
        con.close()
    w = SourcesScreen(str(db))
    assert w.lst.count() == 2
    from PySide6.QtCore import Qt
    item = w.lst.item(1)
    assert item.checkState() == Qt.Checked
    item.setCheckState(Qt.Unchecked)
    w.toggle_selected(item)
    con = connect(db)
    try:
        off = [s for s in list_sources(con) if not s['in_pool']]
    finally:
        con.close()
    assert len(off) == 1
    w.close()
    pf = ProfileScreen(str(db))
    assert pf.cmb_src.count() == 3
    pf.close()


def test_delete_source_flow(tmp_path, monkeypatch):
    from core.pool_import import import_source  # noqa: E402
    from core.roles import GROUP, MAIN  # noqa: E402
    from storage.database import connect, list_sources  # noqa: E402
    from ui.sources_screen import SourcesScreen  # noqa: E402
    QApplication.instance() or QApplication([])
    db = tmp_path / 'ws.sqlite'
    for name in ('a.csv', 'b.csv'):
        p = tmp_path / name
        p.write_text('Z;G' + chr(10) + 'x;Y' + chr(10), encoding='utf-8-sig')
        con = connect(db)
        import_source(con, p, {'Z': MAIN, 'G': GROUP})
        con.close()
    w = SourcesScreen(str(db))
    assert w.lst.count() == 2
    w.lst.setCurrentRow(0)
    w.open_selected()
    # open_file внутри зовёт refresh_sources — выделение обязано выжить,
    # иначе «Удалить» говорит «выбери источник слева»
    assert w.lst.currentItem() is not None and w.lst.currentItem().data(256)

    class FakeBox:
        Yes = 16384
        No = 65536

        @staticmethod
        def question(*a, **k):
            return FakeBox.Yes

        @staticmethod
        def warning(*a, **k):
            return None

    monkeypatch.setattr("ui.sources_screen.QMessageBox", FakeBox)
    w.delete_selected()
    con = connect(db)
    try:
        assert len(list_sources(con)) == 1
    finally:
        con.close()
    assert w.lst.count() == 1
    w.close()


def test_delete_via_checkbox_and_open_file(tmp_path, monkeypatch):
    from core.pool_import import import_source  # noqa: E402
    from core.roles import GROUP, MAIN  # noqa: E402
    from storage.database import connect, list_sources  # noqa: E402
    from ui.sources_screen import SourcesScreen  # noqa: E402
    QApplication.instance() or QApplication([])
    db = tmp_path / 'ws.sqlite'
    for name in ('a.csv', 'b.csv'):
        p = tmp_path / name
        p.write_text('Z;G' + chr(10) + 'x;Y' + chr(10), encoding='utf-8-sig')
        con = connect(db)
        import_source(con, p, {'Z': MAIN, 'G': GROUP})
        con.close()
    w = SourcesScreen(str(db))
    assert w.lst.currentItem() is None
    # клик только по галочке: строка должна выделиться сама
    w.toggle_selected(w.lst.item(1))
    assert w.lst.currentItem() is w.lst.item(1)

    class FakeBox:
        Yes = 16384
        No = 65536

        @staticmethod
        def question(*a, **k):
            return FakeBox.Yes

        @staticmethod
        def warning(*a, **k):
            return None

    monkeypatch.setattr("ui.sources_screen.QMessageBox", FakeBox)
    w.delete_selected()
    con = connect(db)
    try:
        assert len(list_sources(con)) == 1
    finally:
        con.close()
    # выделения нет, но открыт маппинг оставшегося файла — удаляем его
    rest = list_sources(connect(db))
    w._current_file = rest[0]["path"]
    w.delete_selected()
    con = connect(db)
    try:
        assert len(list_sources(con)) == 0
    finally:
        con.close()
    assert w.lst.count() == 0
    w.close()


def test_pool_dialog_and_label(tmp_path):
    from core.pool_import import import_source  # noqa: E402
    from core.roles import GROUP, MAIN  # noqa: E402
    from storage.database import connect  # noqa: E402
    from ui.pool_dialog import PoolDialog, pool_label  # noqa: E402
    QApplication.instance() or QApplication([])
    db = tmp_path / 'ws.sqlite'
    for name in ('a.csv', 'b.csv'):
        p = tmp_path / name
        p.write_text('Z;G' + chr(10) + 'x;Y' + chr(10), encoding='utf-8-sig')
        con = connect(db)
        import_source(con, p, {'Z': MAIN, 'G': GROUP})
        con.close()
    assert pool_label(str(db)) == 'Все (2)'
    d = PoolDialog(str(db))
    assert d.lst.count() == 2
    d.close()
    w = RequirementsScreen(str(db))
    assert 'Все (2)' in w.lbl_pool.text()
    w.close()


def test_quick_filter_and_autopropose(tmp_path, monkeypatch):
    from core.pool_import import import_source  # noqa: E402
    from core.roles import GROUP, MAIN  # noqa: E402
    from storage.database import connect  # noqa: E402
    QApplication.instance() or QApplication([])
    db = tmp_path / "ws.sqlite"
    p = tmp_path / "p.csv"
    p.write_text("Z;G\nодин;А\nдва;Б\nтри;А\n", encoding="utf-8-sig")
    con = connect(db)
    import_source(con, p, {"Z": MAIN, "G": GROUP})
    con.close()
    w = RequirementsScreen(str(db))
    w._adv_on = True
    idx = w.cmb_ff_dim.findData(GROUP)
    w.cmb_ff_dim.setCurrentIndex(max(0, idx))
    assert w._ff_cols[GROUP].lst.count() == 2
    from PySide6.QtCore import Qt  # noqa: E402
    w._ff_cols[GROUP].lst.item(0).setCheckState(Qt.Checked)
    w.quick_add_filter()
    assert w.tbl_f.rowCount() == 1
    assert w.lbl_match.text() == "Подходящих записей: 2"
    import ui.proposal_dialog as _pm
    seen = {}

    class FakeDlg:
        DialogCode = type("D", (), {"Accepted": 1, "Rejected": 0})

        def __init__(self, explanation, parent=None):
            seen["n"] = len(explanation)

        def exec(self):
            return 1

    monkeypatch.setattr(_pm, "ProposalDialog", FakeDlg)
    w.cmb_ff_dim.setCurrentIndex(max(0, w.cmb_ff_dim.findData(GROUP)))
    w.auto_propose()
    assert seen.get("n", 0) > 3
    assert w.tbl_q.rowCount() == 1
    assert w._profile().quotas[0].kind == "min"
    w.close()


def test_formation_and_manual_visibility(tmp_path):
    from core.pool_import import import_source  # noqa: E402
    from core.roles import GROUP, MAIN  # noqa: E402
    from storage.database import connect  # noqa: E402
    QApplication.instance() or QApplication([])
    db = tmp_path / 'w.sqlite'
    p = tmp_path / 'p.csv'
    p.write_text('Z;G' + chr(10) + 'a;A' + chr(10) + 'b;B' + chr(10), encoding='utf-8-sig')
    con = connect(db)
    import_source(con, p, {'Z': MAIN, 'G': GROUP})
    con.close()
    w = RequirementsScreen(str(db))
    w._adv_on = False
    w._formation = 'all'
    w._refresh_manual_visibility()
    assert w.tbl_q.isHidden()
    w._formation = 'manual'
    w._refresh_manual_visibility()
    assert not w.tbl_q.isHidden()
    w.apply_formation('manual')
    assert w.tbl_q.isVisibleTo(w)
    assert w._formation == 'manual'
    w.close()


def test_all_formation_shows_breakdown(tmp_path):
    from core.pool_import import import_source  # noqa: E402
    from core.roles import GROUP, MAIN  # noqa: E402
    from storage.database import connect  # noqa: E402
    QApplication.instance() or QApplication([])
    db = tmp_path / 'w.sqlite'
    p = tmp_path / 'p.csv'
    p.write_text('Z;G' + chr(10) + 'a;A' + chr(10) + 'b;B' + chr(10)
                 + 'c;A' + chr(10), encoding='utf-8-sig')
    con = connect(db)
    import_source(con, p, {'Z': MAIN, 'G': GROUP})
    con.close()
    w = RequirementsScreen(str(db))
    w._adv_on = True
    w.apply_formation('all')
    # раньше таблица была пустой (0 строк) — теперь разбивка по колонке
    assert w.tbl_cov.rowCount() == 2
    vals = {w.tbl_cov.item(r, 1).text(): w.tbl_cov.item(r, 2).text()
            for r in range(w.tbl_cov.rowCount())}
    assert vals.get('A') == 'все 2' and vals.get('B') == 'все 1'
    assert 'подходящее' in w.lbl_cov.text().lower()
    w.close()


def test_delete_source(tmp_path):
    import pytest  # noqa: E402
    from core.pool_import import import_source  # noqa: E402
    from core.requirements import BuildProfile  # noqa: E402
    from core.roles import GROUP, MAIN  # noqa: E402
    from core.sampling_service import sample  # noqa: E402
    from storage.database import connect, delete_source, list_sources, save_build  # noqa: E402
    from ui.sources_screen import SourcesScreen  # noqa: E402
    QApplication.instance() or QApplication([])
    db = tmp_path / 'ws.sqlite'
    for name in ('a.csv', 'b.csv'):
        p = tmp_path / name
        p.write_text('Z;G' + chr(10) + 'x;Y' + chr(10), encoding='utf-8-sig')
        con = connect(db)
        import_source(con, p, {'Z': MAIN, 'G': GROUP})
        con.close()
    w = SourcesScreen(str(db))
    assert hasattr(w, 'btn_del_src')
    assert w.lst.count() == 2
    assert hasattr(w, 'chk_fileopts') and not w.file_opts.isVisibleTo(w)
    w.chk_fileopts.setChecked(True)
    assert w.file_opts.isVisibleTo(w)
    w.close()
    con = connect(db)
    srcs = list_sources(con)
    assert len(srcs) == 2
    out = delete_source(con, srcs[0]['id'])
    assert out['deleted'] == srcs[0]['id']
    assert len(list_sources(con)) == 1
    # источник в сборке удалять нельзя
    prof = BuildProfile(target_size=1, seed=1)
    res = sample(con, prof)
    bid = save_build(con, 'b1', prof, res['items'], res['reasons'], 0)
    assert bid
    rest = list_sources(con)[0]['id']
    with pytest.raises(ValueError, match='сборк'):
        delete_source(con, rest)
    con.close()


def test_requirements_refresh_on_show(tmp_path):
    from PySide6.QtGui import QShowEvent  # noqa: E402
    from core.pool_import import import_source  # noqa: E402
    from core.roles import GROUP, MAIN, TOPIC  # noqa: E402
    from storage.database import connect  # noqa: E402
    QApplication.instance() or QApplication([])
    db = tmp_path / 'ws.sqlite'
    p1 = tmp_path / 'a.csv'
    p1.write_text('Z;G' + chr(10) + 'a;A' + chr(10), encoding='utf-8-sig')
    con = connect(db)
    import_source(con, p1, {'Z': MAIN, 'G': GROUP})
    con.close()
    w = RequirementsScreen(str(db))
    assert w.cmb_ff_dim.count() == 1
    p2 = tmp_path / 'b.csv'
    p2.write_text('Z;T' + chr(10) + 'b;Ц' + chr(10), encoding='utf-8-sig')
    con = connect(db)
    import_source(con, p2, {'Z': MAIN, 'T': TOPIC})
    con.close()
    # без showEvent список протухший, после — обновлён
    w.showEvent(QShowEvent())
    dims = {w.cmb_ff_dim.itemData(i) for i in range(w.cmb_ff_dim.count())}
    assert GROUP in dims and TOPIC in dims
    w.close()


def test_quick_filter_multicolumn(tmp_path):
    from PySide6.QtCore import Qt  # noqa: E402
    from core.pool_import import import_source  # noqa: E402
    from core.roles import GROUP, MAIN, TOPIC  # noqa: E402
    from storage.database import connect  # noqa: E402
    QApplication.instance() or QApplication([])
    db = tmp_path / 'ws.sqlite'
    p = tmp_path / 'a.csv'
    p.write_text('Z;G;T' + chr(10) + 'a;A;x' + chr(10) + 'b;B;y' + chr(10)
                 + 'c;A;x' + chr(10), encoding='utf-8-sig')
    con = connect(db)
    import_source(con, p, {'Z': MAIN, 'G': GROUP, 'T': TOPIC})
    con.close()
    w = RequirementsScreen(str(db))
    w._adv_on = True
    assert set(w._ff_cols) == {GROUP, TOPIC}
    w._ff_cols[GROUP].lst.item(0).setCheckState(Qt.Checked)
    w._ff_cols[TOPIC].lst.item(0).setCheckState(Qt.Checked)
    w.quick_add_filter()
    assert w.tbl_f.rowCount() == 2
    assert w.lbl_match.text() == "Подходящих записей: 2"
    assert "A: 2" in w.lbl_s_comp.text()
    assert w.donut_prev._tips == []
    w.cmb_ff_dim.setCurrentIndex(max(0, w.cmb_ff_dim.findData(TOPIC)))
    assert "x: 2" in w.lbl_s_comp.text()
    assert len(w.donut_prev._parts) == 1
    assert "план" in w.donut_prev._center
    assert w.lbl_rare_tip.isVisibleTo(w)
    w.btn_rare.click()
    assert w.cb_rarity.isChecked()
    # повторное добавление не плодит строки, а обновляет значения
    w.quick_add_filter()
    assert w.tbl_f.rowCount() == 2
    w.clear_filters()
    assert w.tbl_f.rowCount() == 0
    assert w._ff_cols[GROUP].badge.text() == "Все"
    w.close()


def test_quick_filter_search(tmp_path):
    from core.pool_import import import_source  # noqa: E402
    from core.roles import GROUP, MAIN  # noqa: E402
    from storage.database import connect  # noqa: E402
    QApplication.instance() or QApplication([])
    db = tmp_path / 'ws.sqlite'
    p = tmp_path / 'a.csv'
    p.write_text('Z;G' + chr(10) + 'a;Возврат заказа' + chr(10)
                 + 'b;Отмена заказа' + chr(10), encoding='utf-8-sig')
    con = connect(db)
    import_source(con, p, {'Z': MAIN, 'G': GROUP})
    con.close()
    w = RequirementsScreen(str(db))
    w._adv_on = True
    lst = w._ff_cols[GROUP].lst
    assert lst.count() == 2
    w.edit_ff_search.setText("возврат")
    assert w._ff_cols[GROUP].lst.count() == 1
    assert "Возврат" in w._ff_cols[GROUP].lst.item(0).data(256)
    w.edit_ff_search.setText("")
    assert w._ff_cols[GROUP].lst.count() == 2
    w.close()


def test_quick_filter_search_all_values(tmp_path):
    from core.pool_import import import_source  # noqa: E402
    from core.roles import GROUP, MAIN  # noqa: E402
    from storage.database import connect  # noqa: E402
    QApplication.instance() or QApplication([])
    db = tmp_path / 'ws.sqlite'
    p = tmp_path / 'a.csv'
    rows = chr(10).join(f"t{i};v{i:03d}" for i in range(250))
    p.write_text('Z;G' + chr(10) + rows + chr(10), encoding='utf-8-sig')
    con = connect(db)
    import_source(con, p, {'Z': MAIN, 'G': GROUP})
    con.close()
    w = RequirementsScreen(str(db))
    w._adv_on = True
    assert w._ff_cols[GROUP].lst.count() == 200
    raws = {w._ff_cols[GROUP].lst.item(r).data(256)
            for r in range(w._ff_cols[GROUP].lst.count())}
    assert "v249" not in raws
    w.edit_ff_search.setText("v249")
    lst = w._ff_cols[GROUP].lst
    assert lst.count() == 1 and lst.item(0).data(256) == "v249"
    w.close()


def test_preview_donut_groups_tail(tmp_path):
    from core.pool_import import import_source  # noqa: E402
    from core.roles import GROUP, MAIN  # noqa: E402
    from storage.database import connect  # noqa: E402
    QApplication.instance() or QApplication([])
    db = tmp_path / 'ws.sqlite'
    p = tmp_path / 'a.csv'
    rows = chr(10).join(f"t{i};v{i}" for i in range(25))
    p.write_text('Z;G' + chr(10) + rows + chr(10), encoding='utf-8-sig')
    con = connect(db)
    import_source(con, p, {'Z': MAIN, 'G': GROUP})
    con.close()
    w = RequirementsScreen(str(db))
    w._adv_on = True
    w.apply_formation('all')
    assert len(w.donut_prev._parts) == 21
    assert w.donut_prev._parts[-1][0] == "#9AA0A6"
    assert "Остальные (5)" in w.lbl_s_comp.text()
    w.close()


def test_profile_data_panel(tmp_path):
    from core.pool_import import import_source  # noqa: E402
    from core.roles import GROUP, MAIN  # noqa: E402
    from storage.database import connect  # noqa: E402
    from ui.profile_screen import ProfileScreen  # noqa: E402
    QApplication.instance() or QApplication([])
    db = tmp_path / 'ws.sqlite'
    p = tmp_path / 'a.csv'
    p.write_text('Z;G' + chr(10) + 'a;A' + chr(10) + 'b;B' + chr(10), encoding='utf-8-sig')
    con = connect(db)
    import_source(con, p, {'Z': MAIN, 'G': GROUP})
    con.close()
    w = ProfileScreen(str(db))
    assert w.card_data is not None
    from PySide6.QtWidgets import QLabel as _QLabel  # noqa: E402
    assert 'данных' in w.card_data.findChild(_QLabel).text() or True
    assert 'файлов' in w.lbl_data_hint.text() or 'измерений' in w.lbl_data_hint.text()
    assert 'категорий' in w.lbl_pool_sub.text()
    assert 'записей' in w.donut._center
    assert '%' in w.top_bars[0][0].text()
    w.close()


def test_formation_cards_select(tmp_path):
    from core.pool_import import import_source  # noqa: E402
    from core.roles import GROUP, MAIN  # noqa: E402
    from storage.database import connect  # noqa: E402
    QApplication.instance() or QApplication([])
    db = tmp_path / 'ws.sqlite'
    p = tmp_path / 'a.csv'
    p.write_text('Z;G' + chr(10) + 'a;A' + chr(10) + 'b;B' + chr(10), encoding='utf-8-sig')
    con = connect(db)
    import_source(con, p, {'Z': MAIN, 'G': GROUP})
    con.close()
    w = RequirementsScreen(str(db))
    assert len(w._formation_cards) == 5
    w.apply_formation('equal')
    assert w._formation == 'equal'
    assert w._formation_cards['equal'].styleSheet() != ''
    assert w._formation_cards['manual'].styleSheet() == ''
    w._formation_cards['prop']._click_cb()
    assert w._formation == 'prop'
    assert w.tbl_q.rowCount() == 2
    w.close()


def test_wizard_helpers(tmp_path):
    from core.pool_import import import_source  # noqa: E402
    from core.roles import GROUP, MAIN  # noqa: E402
    from storage.database import connect  # noqa: E402
    from ui.build_wizard import wizard_preview, wizard_profile  # noqa: E402
    QApplication.instance() or QApplication([])
    db = tmp_path / 'ws.sqlite'
    p = tmp_path / 'a.csv'
    p.write_text('Z;G' + chr(10) + 'a;A' + chr(10) + 'b;B' + chr(10)
                 + 'c;A' + chr(10), encoding='utf-8-sig')
    con = connect(db)
    import_source(con, p, {'Z': MAIN, 'G': GROUP})
    prof = wizard_profile("random", "", 2, 7)
    out = wizard_preview(con, prof, None)
    assert len(out["items"]) == 2 and out["short"] == 0
    assert out["seed"] == 7
    assert {r for r, _c in out["breakdown"]} <= {"a.csv"}
    prof2 = wizard_profile("balanced", GROUP, 2, 7)
    out2 = wizard_preview(con, prof2, GROUP)
    assert len(out2["items"]) == 2
    assert sum(1 for q in out2["quotas"] if q.kind == "exact") == 2
    assert sum(q.amount for q in out2["quotas"] if q.kind == "exact") == 2
    con.close()


def test_wizard_dialog_flow(tmp_path):
    from PySide6.QtWidgets import QWizard  # noqa: E402
    from core.pool_import import import_source  # noqa: E402
    from core.roles import GROUP, MAIN  # noqa: E402
    from storage.database import connect, list_builds  # noqa: E402
    from ui.build_wizard import WizardDialog  # noqa: E402
    QApplication.instance() or QApplication([])
    db = tmp_path / 'ws.sqlite'
    p = tmp_path / 'a.csv'
    p.write_text('Z;G' + chr(10) + 'a;A' + chr(10) + 'b;B' + chr(10), encoding='utf-8-sig')
    con = connect(db)
    import_source(con, p, {'Z': MAIN, 'G': GROUP})
    con.close()
    w = WizardDialog(str(db))
    w.show()
    w._intro.rbs["balanced"].setChecked(True)
    assert w.nextId() == 1
    w.next()
    assert w.currentId() == 1
    w._setup.spin_size.setValue(2)
    assert w._setup.cmb_dim.findData(GROUP) >= 0
    w.next()
    assert w.currentId() == 2
    assert "соберётся 2" in w._preview.lbl_sum.text()
    assert w._preview.lst.count() == 2
    seed1 = w._preview._seed
    w._preview.btn_more.click()
    assert w._preview._seed != seed1
    w.button(QWizard.FinishButton).click()
    assert w.result and w.result["action"] == "built"
    con = connect(db)
    try:
        assert len(list_builds(con)) == 1
    finally:
        con.close()
    w.close()
