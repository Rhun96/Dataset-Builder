"""Загрузка пула: оригиналы целы, нормы для отбора, custom — измерение."""
from core.pool_import import import_source
from core.roles import EXT_ID, GROUP, MAIN
from storage.database import connect, load_mapping, pool_counts


def test_import_csv(tmp_path):
    p = tmp_path / "pool.csv"
    p.write_text("З;Г;ИД\nКак вернуть?;Возвраты;A-1\n;Пустой;B-1\n", encoding="utf-8-sig")
    con = connect(tmp_path / "ws.sqlite")
    res = import_source(con, p, {"З": MAIN, "Г": GROUP, "ИД": EXT_ID})
    assert res["usable"] == 1  # пустой основной текст пропущен
    assert res["skipped_empty"] >= 1
    assert pool_counts(con)["total"] == 1
    row = con.execute("SELECT * FROM candidate").fetchone()
    assert row["main_raw"] == "Как вернуть?"
    assert row["ext_id"] == "A-1"
    dim = con.execute("SELECT * FROM candidate_dim").fetchone()
    assert dim["dim"] == GROUP and dim["value_norm"] == "возвраты"
    # маппинг сохранился
    assert load_mapping(con, res["source_id"])["З"] == MAIN
    con.close()


def test_custom_is_dimension(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("З;X\nпривет;мир\n", encoding="utf-8-sig")
    con = connect(tmp_path / "ws.sqlite")
    import_source(con, p, {"З": MAIN, "X": "custom:Мой раздел"})
    dims = con.execute("SELECT DISTINCT dim FROM candidate_dim").fetchall()
    assert "custom:Мой раздел" in [d[0] for d in dims]
    con.close()
