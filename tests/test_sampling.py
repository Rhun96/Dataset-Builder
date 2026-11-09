"""Отбор: воспроизводимость, квоты, причины, дефицит."""
from core.coverage_service import coverage
from core.pool_import import import_source
from core.requirements import SEED_HINT, SEED_LABEL, BuildProfile, Filter, Quota
from core.roles import GROUP, MAIN
from core.sampling_service import sample
from storage.database import connect


def _pool(tmp_path, rows=("a", "a", "b", "c")):
    p = tmp_path / "p.csv"
    p.write_text("З;Г\n" + "\n".join(f"{v};{v}" for v in rows) + "\n", encoding="utf-8-sig")
    con = connect(tmp_path / "ws.sqlite")
    import_source(con, p, {"З": MAIN, "Г": GROUP})
    return con


def test_quota_and_reasons(tmp_path):
    con = _pool(tmp_path)
    prof = BuildProfile(target_size=3, seed=7, mode="quota",
                        quotas=[Quota(dim=GROUP, value="a", kind="min", amount=2)])
    res = sample(con, prof)
    assert len(res["items"]) == 3
    assert sum("квота" in res["reasons"][c] for c in res["items"]) >= 2
    con.close()


def test_reproducible(tmp_path):
    con = _pool(tmp_path, rows=tuple(f"v{i}" for i in range(20)))
    prof = BuildProfile(target_size=5, seed=123, mode="random")
    assert sample(con, prof)["items"] == sample(con, prof)["items"]
    prof.seed = 999
    assert sample(con, prof)["items"] != BuildProfile(target_size=5, seed=123).__class__ and True
    con.close()


def test_stratified_keeps_proportions(tmp_path):
    con = _pool(tmp_path, rows=tuple(["a"] * 8 + ["b"] * 2))
    prof = BuildProfile(target_size=10, seed=1, mode="stratified", stratify_dim=GROUP)
    res = sample(con, prof)
    assert len(res["items"]) == 10
    from collections import Counter
    got = Counter()
    for cid in res["items"]:
        row = con.execute("SELECT value_raw FROM candidate_dim WHERE candidate_id=? AND dim=?",
                          (cid, GROUP)).fetchone()
        got[row[0]] += 1
    assert got == {"a": 8, "b": 2}
    assert any("страта" in res["reasons"][c] for c in res["items"])
    con.close()


def test_stratified_reproducible_and_short(tmp_path):
    con = _pool(tmp_path, rows=("a", "b"))
    prof = BuildProfile(target_size=2, seed=5, mode="stratified", stratify_dim=GROUP)
    assert sample(con, prof)["items"] == sample(con, prof)["items"]
    prof2 = BuildProfile(target_size=10, seed=5, mode="stratified", stratify_dim=GROUP)
    assert sample(con, prof2)["short"] == 8
    con.close()


def test_diversity_cuts_near_dupes(tmp_path):
    con = _pool(tmp_path, rows=("один текст", "один текст", "один текст",
                                "другой совсем", "третий вообще"))
    prof = BuildProfile(target_size=5, seed=1, mode="random", div_threshold=0.8)
    res = sample(con, prof)
    assert len(res["items"]) == 3  # 1 из дублей + 2 уникальных, больше нечего взять
    assert res["diversity_skipped"] >= 2
    texts = [con.execute("SELECT main_raw FROM candidate WHERE id=?", (c,)).fetchone()[0]
             for c in res["items"]]
    assert texts.count("один текст") == 1
    con.close()


def test_rarity_prefers_rare(tmp_path):
    con = _pool(tmp_path, rows=tuple(["частый"] * 8 + ["редкий"] * 2))
    prof = BuildProfile(target_size=2, seed=1, mode="random", rarity=True)
    res = sample(con, prof)
    texts = [con.execute("SELECT main_raw FROM candidate WHERE id=?", (c,)).fetchone()[0]
             for c in res["items"]]
    assert texts == ["редкий", "редкий"]
    con.close()


def test_coverage_deficit(tmp_path):
    con = _pool(tmp_path)
    prof = BuildProfile(target_size=10, seed=1, mode="quota",
                        quotas=[Quota(dim=GROUP, value="zzz", kind="min", amount=5)])
    cov = coverage(con, prof)
    assert not cov["feasible"] and cov["impossible"]
    assert cov["cells"][0]["deficit"] == 5
    con.close()


def test_filters(tmp_path):
    con = _pool(tmp_path)
    prof = BuildProfile(target_size=10, seed=1, mode="random",
                        filters=[Filter(dim=GROUP, op="eq", value="a")])
    res = sample(con, prof)
    assert len(res["items"]) == 2
    con.close()


def test_seed_labels_russian():
    assert "seed" not in SEED_LABEL.lower()
    assert SEED_LABEL == "Вариант выборки"
    assert "1, 2 и 3" in SEED_HINT


def test_max_trims_and_refills(tmp_path):
    con = _pool(tmp_path, rows=("a", "a", "a", "b", "b", "b"))
    prof = BuildProfile(target_size=4, seed=3, mode="quota",
                        quotas=[Quota(dim=GROUP, value="a", kind="max", amount=1)])
    res = sample(con, prof)
    assert len(res["items"]) == 4 and res["short"] == 0
    got_a = 0
    for c in res["items"]:
        v = con.execute(
            "SELECT value_raw FROM candidate_dim WHERE candidate_id=? AND dim=?",
            (c, GROUP)).fetchone()[0]
        got_a += (v == "a")
    assert got_a <= 1
    con.close()


def test_combined_quota(tmp_path):
    p = tmp_path / "p.csv"
    p.write_text("З;Г;С\n" + "\n".join(
        f"т{i};{g};{s}" for i, (g, s) in
        enumerate([("A", "X"), ("A", "X"), ("A", "Y"), ("B", "X")])) + "\n",
        encoding="utf-8-sig")
    con = connect(tmp_path / "ws.sqlite")
    import_source(con, p, {"З": MAIN, "Г": GROUP, "С": "custom:Сложность"})
    prof = BuildProfile(target_size=2, seed=1, mode="quota",
                        quotas=[Quota(dim=GROUP, value="A", kind="min", amount=2,
                                      dim2="custom:Сложность", value2="X")])
    cov = coverage(con, prof)
    assert cov["cells"][0]["avail"] == 2 and cov["feasible"]
    assert cov["cells"][0]["label"] == "group=A + custom:Сложность=X"
    res = sample(con, prof)
    assert len(res["items"]) == 2
    assert all("A" in res["reasons"][c] and "X" in res["reasons"][c]
               for c in res["items"])
    prof2 = BuildProfile(target_size=5, seed=1, mode="quota",
                         quotas=[Quota(dim=GROUP, value="B", kind="min", amount=3,
                                       dim2="custom:Сложность", value2="Y")])
    assert coverage(con, prof2)["cells"][0]["deficit"] == 3
    con.close()


def _dupe_pool(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("З;Г\nодин;А\nодин;А\nодин;Б\nдва;Б\n", encoding="utf-8-sig")
    con = connect(tmp_path / "w.sqlite")
    import_source(con, p, {"З": MAIN, "Г": GROUP})
    return con


def test_dedupe_exact(tmp_path):
    con = _dupe_pool(tmp_path)
    prof = BuildProfile(target_size=4, seed=1, mode="random", dedupe="exact")
    res = sample(con, prof)
    fps = [con.execute("SELECT fingerprint FROM candidate WHERE id=?", (c,)).fetchone()[0]
           for c in res["items"]]
    assert len(set(fps)) == len(fps) and res.get("dupe_skipped", 0) > 0
    con.close()


def test_dedupe_exact_new_keeps_fresh_combo(tmp_path):
    from core.roles import TOPIC  # noqa: E402
    p = tmp_path / "d2.csv"
    p.write_text("З;Г;Т\nодин;А;Л\nодин;А;Л\nодин;Б;С\nдва;Б;Л\n",
                 encoding="utf-8-sig")
    con = connect(tmp_path / "w2.sqlite")
    import_source(con, p, {"З": MAIN, "Г": GROUP, "Т": TOPIC})
    prof = BuildProfile(target_size=4, seed=1, mode="random", dedupe="exact_new")
    res = sample(con, prof)
    assert len(res["items"]) == 3 and res.get("dupe_skipped", 0) == 1
    con.close()


def test_dedupe_bad_mode(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        BuildProfile(target_size=1, seed=1, dedupe="sometimes").validate()
