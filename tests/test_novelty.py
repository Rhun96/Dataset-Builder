"""Доли источников и новизна: лимиты, исключения, минимум новых, сохранение."""
from core.pool_import import import_source
from core.requirements import BuildProfile
from core.roles import GROUP, MAIN
from core.sampling_service import sample
from storage.database import connect, save_build


def _pool2(tmp_path):
    """Два источника: p.csv (А) и q.csv (Б)."""
    p = tmp_path / "p.csv"
    p.write_text("З;Г\n" + "\n".join(f"п{i};А" for i in range(6)), encoding="utf-8-sig")
    q = tmp_path / "q.csv"
    q.write_text("З;Г\n" + "\n".join(f"к{i};Б" for i in range(6)), encoding="utf-8-sig")
    con = connect(tmp_path / "ws.sqlite")
    import_source(con, p, {"З": MAIN, "Г": GROUP})
    import_source(con, q, {"З": MAIN, "Г": GROUP})
    srcs = {r["path"]: r["id"] for r in con.execute("SELECT id, path FROM source").fetchall()}
    return con, srcs


def test_source_cap(tmp_path):
    con, _ = _pool2(tmp_path)
    prof = BuildProfile(target_size=6, seed=1, mode="random", max_source_pct=50)
    res = sample(con, prof)
    assert len(res["items"]) == 6
    from collections import Counter
    marks = ",".join("?" for _ in res["items"])
    counts = Counter(r[0] for r in con.execute(
        f"SELECT source_id FROM candidate WHERE id IN ({marks})",
        res["items"]).fetchall())
    assert max(counts.values()) <= 3  # 50% от 6
    con.close()


def test_hard_exclude(tmp_path):
    con, _ = _pool2(tmp_path)
    prof = BuildProfile(target_size=4, seed=1)
    first = sample(con, prof)
    b1 = save_build(con, "b1", prof, first["items"], first["reasons"], 0)
    prof2 = BuildProfile(target_size=4, seed=2, exclude_builds=[b1])
    res = sample(con, prof2)
    assert not set(res["items"]) & set(first["items"])
    assert res["excluded_n"] == len(first["items"])
    con.close()


def test_min_new_and_keep(tmp_path):
    con, _ = _pool2(tmp_path)
    prof = BuildProfile(target_size=4, seed=1)
    first = sample(con, prof)
    b1 = save_build(con, "b1", prof, first["items"], first["reasons"], 0)
    prof2 = BuildProfile(target_size=4, seed=3, exclude_builds=[b1],
                         min_new=3, keep_build=b1, keep_min=1)
    res = sample(con, prof2)
    assert res["items"][0] in first["items"]
    assert "сохранено" in res["reasons"][res["items"][0]]
    assert res["new_count"] >= 3 and res["new_short"] == 0
    con.close()
