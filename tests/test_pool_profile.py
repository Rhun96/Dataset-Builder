"""Профиль: сводка пула + распределение по измерению."""
from core.pool_import import import_source
from core.pool_profile import (
    dim_distribution,
    get_summary,
    list_dims,
    sources_breakdown,
)
from core.roles import GROUP, MAIN
from storage.database import connect


def _seed(tmp_path):
    p = tmp_path / "p.csv"
    p.write_text("З;Г\nодин;А\nдва;А\nтри;Б\n", encoding="utf-8-sig")
    con = connect(tmp_path / "ws.sqlite")
    import_source(con, p, {"З": MAIN, "Г": GROUP})
    return con


def test_summary_and_dist(tmp_path):
    con = _seed(tmp_path)
    s = get_summary(con)
    assert s["total"] == 3 and s["exact_dupes"] == 0
    assert any(d == GROUP for d, _ in list_dims(con))
    d = dim_distribution(con, GROUP)
    assert d["filled"] == 3 and d["unique"] == 2
    assert d["top"][0]["count"] == 2  # А
    assert len(sources_breakdown(con)) == 1
    con.close()


def test_pool_cards(tmp_path):
    from core.pool_profile import anomalies, fill_rate, pool_overview  # noqa: E402
    con = _seed(tmp_path)
    ov = pool_overview(con)
    assert ov["records"] == 3 and ov["sources"] == 1 and ov["bytes"] > 0
    fr = fill_rate(con)
    assert fr["total"] == 3 and fr["pct"] == 100.0
    an = anomalies(con)
    assert an["dupes"] == 0 and an["no_ext_id"] == 3 and not an["imbalance"]
    con.close()
