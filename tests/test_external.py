"""Импорт готового набора: сопоставление с пулом, без добавления мусора."""
from core.external_import import import_external
from core.pool_import import import_source
from core.roles import EXT_ID, GROUP, MAIN
from storage.database import connect


def test_external_import(tmp_path):
    p = tmp_path / "pool.csv"
    p.write_text("З;Г;ИД\nодин;А;A1\nдва;Б;B1\nтри;В;C1\n", encoding="utf-8-sig")
    con = connect(tmp_path / "ws.sqlite")
    import_source(con, p, {"З": MAIN, "Г": GROUP, "ИД": EXT_ID})
    g = tmp_path / "golden.csv"
    g.write_text("Текст;Номер\nдва;B1\nтри;C1\nчужой;\n", encoding="utf-8-sig")
    out = import_external(con, g, {"Текст": MAIN, "Номер": EXT_ID}, "Golden")
    assert out["matched"] == 2 and out["unmatched"] == 1
    row = con.execute("SELECT picked FROM build WHERE id=?",
                      (out["build_id"],)).fetchone()
    assert row[0] == 2
    con.close()
