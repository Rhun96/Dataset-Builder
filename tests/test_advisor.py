"""Советчик: редких — целиком, остальных — пропорционально, с объяснением."""
from core.advisor import propose
from core.pool_import import import_source
from core.requirements import BuildProfile
from core.roles import GROUP, MAIN
from storage.database import connect


def _pool(tmp_path):
    p = tmp_path / "p.csv"
    p.write_text("З;Г\n" + "\n".join(f"в{i};{'А' if i < 2 else 'Б'}" for i in range(102)),
                 encoding="utf-8-sig")
    con = connect(tmp_path / "ws.sqlite")
    import_source(con, p, {"З": MAIN, "Г": GROUP})
    return con


def test_propose_takes_rare_fully(tmp_path):
    con = _pool(tmp_path)
    out = propose(con, BuildProfile(target_size=50, seed=1), GROUP, rare_min=30)
    by_val = {q.value: (q.kind, q.amount) for q in out["quotas"]}
    assert by_val["А"][0] == "min" and by_val["А"][1] == 2
    assert by_val["Б"][0] == "percent"
    assert out["target"] == 50 and out["div_threshold"] == 0.85
    assert any("Редкие" in line for line in out["explanation"])
    assert any("рекомендация" in line for line in out["explanation"])
    con.close()


def test_propose_multi_dim_and_pairs(tmp_path):
    from core.roles import TOPIC  # noqa: E402
    p = tmp_path / "p.csv"
    rows = ["т0;Редкий;x", "т1;Редкий;x", "т2;Частый;y", "т3;Частый;y",
            "т4;Частый;y", "т5;Частый;y"]
    p.write_text("З;Г;Т\n" + "\n".join(rows) + "\n", encoding="utf-8-sig")
    con = connect(tmp_path / "ws.sqlite")
    import_source(con, p, {"З": MAIN, "Г": GROUP, "Т": TOPIC})
    out = propose(con, BuildProfile(target_size=6, seed=1), GROUP, rare_min=3)
    kinds = {(q.dim, q.value, q.kind) for q in out["quotas"]}
    assert (GROUP, "Редкий", "min") in kinds  # редкое значение другой грани
    assert (TOPIC, "x", "min") in kinds  # редкое значение второй грани
    assert any(q.dim2 == TOPIC for q in out["quotas"])  # редкое сочетание
    assert out["target"] == 6
    assert any("сочетания" in line for line in out["explanation"])
    con.close()


def test_propose_empty_pool(tmp_path):
    con = connect(tmp_path / "w.sqlite")
    try:
        propose(con, BuildProfile(target_size=10, seed=1), "nope")
        raise AssertionError("должна быть ошибка")
    except ValueError:
        pass
    con.close()
