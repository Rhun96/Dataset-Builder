"""Закрепление, замена, сравнение: честность ревизий."""
from core.compare_service import compare_builds
from core.pool_import import import_source
from core.replace_service import replace_items
from core.requirements import BuildProfile
from core.roles import GROUP, MAIN
from core.sampling_service import sample
from storage.database import connect, list_pinned, save_build, set_pinned


def _pool(tmp_path):
    p = tmp_path / "p.csv"
    p.write_text("З;Г\nодин;А\nдва;А\nтри;А\nчетыре;Б\n", encoding="utf-8-sig")
    con = connect(tmp_path / "ws.sqlite")
    import_source(con, p, {"З": MAIN, "Г": GROUP})
    return con


def test_pinned_go_first(tmp_path):
    con = _pool(tmp_path)
    cids = [r[0] for r in con.execute("SELECT id FROM candidate ORDER BY id").fetchall()]
    set_pinned(con, [cids[-1]])
    assert list_pinned(con) == [cids[-1]]
    prof = BuildProfile(target_size=2, seed=3, mode="random")
    res = sample(con, prof)
    assert res["items"][0] == cids[-1]
    assert "закреплено" in res["reasons"][cids[-1]]
    con.close()


def test_replace_same_cell(tmp_path):
    con = _pool(tmp_path)
    prof = BuildProfile(target_size=2, seed=1)
    res = sample(con, prof)
    bid = save_build(con, "t", prof, res["items"], res["reasons"], 0)
    victim = res["items"][0]
    out = replace_items(con, bid, [victim], seed=2)
    assert out["build_id"] != bid
    assert victim in out["replaced"] or victim in out["unreplaced"]
    if victim in out["replaced"]:
        new = out["replaced"][victim]
        assert new != victim
    # полный пул: менять не на кого
    prof_full = BuildProfile(target_size=10, seed=1)
    rfull = sample(con, prof_full)
    bfull = save_build(con, "full", prof_full, rfull["items"], rfull["reasons"], 0)
    out2 = replace_items(con, bfull, rfull["items"][:2], seed=2)
    assert out2["replaced"] == {} and out2["pool_outside"] == 0
    con.close()


def test_compare(tmp_path):
    con = _pool(tmp_path)
    prof = BuildProfile(target_size=2, seed=1)
    r1 = sample(con, prof)
    b1 = save_build(con, "a", prof, r1["items"], r1["reasons"], 0)
    prof.seed = 2
    r2 = sample(con, prof)
    b2 = save_build(con, "b", prof, r2["items"], r2["reasons"], 0)
    d = compare_builds(con, b1, b2)
    assert d["old_id"] == b1 and d["new_id"] == b2
    assert len(d["kept"]) + len(d["added"]) == len(r2["items"])
    assert len(d["kept"]) + len(d["removed"]) == len(r1["items"])
    con.close()
