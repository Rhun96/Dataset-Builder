"""Пресеты квот: доли из пула, равномерный дележ."""
import pytest

from core.pool_import import import_source
from core.quota_presets import proportional, uniform
from core.requirements import BuildProfile
from core.roles import GROUP, MAIN
from storage.database import connect


def _pool(tmp_path):
    p = tmp_path / "p.csv"
    p.write_text("З;Г\n" + "\n".join(f"в{i};{'А' if i < 6 else 'Б'}" for i in range(10)),
                 encoding="utf-8-sig")
    con = connect(tmp_path / "ws.sqlite")
    import_source(con, p, {"З": MAIN, "Г": GROUP})
    return con


def test_proportional(tmp_path):
    con = _pool(tmp_path)
    qs = proportional(con, BuildProfile(target_size=100, seed=1), GROUP)
    by_val = {q.value: q.amount for q in qs}
    assert by_val == {"А": 60.0, "Б": 40.0}
    assert all(q.kind == "percent" for q in qs)
    con.close()


def test_uniform(tmp_path):
    con = _pool(tmp_path)
    qs = uniform(con, BuildProfile(target_size=10, seed=1), GROUP)
    assert sorted(q.amount for q in qs) == [5, 5]
    assert all(q.kind == "exact" for q in qs)
    qs7 = uniform(con, BuildProfile(target_size=7, seed=1), GROUP)
    assert sorted(q.amount for q in qs7) == [3, 4]
    with pytest.raises(ValueError):
        uniform(con, BuildProfile(target_size=10, seed=1), "нетакого")
    con.close()
