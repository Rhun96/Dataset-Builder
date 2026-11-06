"""Варианты: воспроизводимость по семенам, сводка без интегрального балла."""
from core.pool_import import import_source
from core.requirements import BuildProfile
from core.roles import GROUP, MAIN
from core.sampling_service import sample
from core.variant_service import generate_variants, summarize
from storage.database import connect, save_build


def test_variants(tmp_path):
    p = tmp_path / "p.csv"
    p.write_text("З;Г\n" + "\n".join(f"в{i};{'А' if i % 2 else 'Б'}" for i in range(20)),
                 encoding="utf-8-sig")
    con = connect(tmp_path / "ws.sqlite")
    import_source(con, p, {"З": MAIN, "Г": GROUP})
    prof = BuildProfile(target_size=5, seed=1, mode="random")
    res = sample(con, prof)
    base = save_build(con, "base", prof, res["items"], res["reasons"], 0)
    ids = generate_variants(con, base, [2, 3, 4])
    assert len(ids) == 3 and len(set(ids)) == 3
    # воспроизводимость: те же семена — тот же состав
    again = generate_variants(con, base, [2, 3, 4])
    first = {r[0] for r in con.execute(
        "SELECT candidate_id FROM build_item WHERE build_id=?", (ids[0],))}
    first_again = {r[0] for r in con.execute(
        "SELECT candidate_id FROM build_item WHERE build_id=?", (again[0],))}
    assert first == first_again
    s = summarize(con, ids[0])
    assert s["seed"] == 2 and s["picked"] == 5 and s["status"] in ("ready", "warnings")
    assert s["dup_fp"] >= 0
    con.close()
