"""Выбор пулов: выключение источников режет отбор и профиль."""
from core.pool_import import import_source
from core.pool_profile import dim_distribution, get_summary
from core.requirements import BuildProfile
from core.roles import GROUP, MAIN
from core.sampling_service import sample
from storage.database import connect, list_sources, set_source_enabled


def _two(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("З;Г\nодин;А\nдва;А\n", encoding="utf-8-sig")
    q = tmp_path / "b.csv"
    q.write_text("З;Г\nтри;Б\nчетыре;Б\n", encoding="utf-8-sig")
    con = connect(tmp_path / "ws.sqlite")
    import_source(con, p, {"З": MAIN, "Г": GROUP})
    import_source(con, q, {"З": MAIN, "Г": GROUP})
    return con


def test_exclude_source_from_pool(tmp_path):
    con = _two(tmp_path)
    from pathlib import Path as _P
    srcs = {_P(s["path"]).name: s["id"] for s in list_sources(con)}
    bid = srcs["b.csv"]
    set_source_enabled(con, bid, False)
    assert get_summary(con)["total"] == 2
    res = sample(con, BuildProfile(target_size=10, seed=1))
    assert len(res["items"]) == 2 and res["short"] == 8
    texts = {con.execute("SELECT main_raw FROM candidate WHERE id=?", (c,)).fetchone()[0]
             for c in res["items"]}
    assert texts == {"один", "два"}
    # а по отдельности виден и выключенный
    assert get_summary(con, bid)["total"] == 2
    d = dim_distribution(con, GROUP, source_id=bid)
    assert d["filled"] == 2 and d["unique"] == 1
    con.close()
