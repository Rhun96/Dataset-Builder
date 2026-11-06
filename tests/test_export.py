"""Манифест, предпроверки, пакет: воспроизводимость и безопасный экспорт."""
import json

import pytest

from core.build_manifest import build_manifest
from core.pool_import import import_source
from core.precheck_service import precheck
from core.requirements import BuildProfile, Quota
from core.roles import GROUP, MAIN
from core.sampling_service import sample
from export.package_exporter import export_package
from storage.database import connect, save_build


def _build(tmp_path, quotas=()):
    p = tmp_path / "p.csv"
    p.write_text("З;Г\nодин;А\nдва;А\nтри;Б\n=формула;В\n", encoding="utf-8-sig")
    con = connect(tmp_path / "ws.sqlite")
    import_source(con, p, {"З": MAIN, "Г": GROUP})
    prof = BuildProfile(target_size=3, seed=5, quotas=list(quotas))
    res = sample(con, prof)
    bid = save_build(con, "t", prof, res["items"], res["reasons"], res.get("short", 0))
    return con, bid


def test_manifest_reasons_and_sources(tmp_path):
    con, bid = _build(tmp_path, [Quota(dim=GROUP, value="А", kind="min", amount=1)])
    m = build_manifest(con, bid)
    assert m["picked"] == 3 and m["variant"] == 5 and m["algo"].startswith("sampling-v")
    assert m["sources"] and m["sources"][0]["sha256"]
    assert all(i["export_id"] and i["reason"] for i in m["items"])
    con.close()


def test_precheck_ok_and_block(tmp_path):
    con, bid = _build(tmp_path, [Quota(dim=GROUP, value="А", kind="min", amount=1)])
    assert precheck(con, bid)["status"] == "ready"
    con2, bid2 = _build(tmp_path, [Quota(dim=GROUP, value="нет", kind="min", amount=2)])
    pc = precheck(con2, bid2)
    assert pc["status"] == "blocked"
    assert any(c["code"].startswith("quota:") and c["level"] == "block" for c in pc["checks"])
    con.close()
    con2.close()


def test_export_roundtrip_and_formula_guard(tmp_path):
    con, bid = _build(tmp_path)
    made = export_package(con, bid, tmp_path / "out", formats=("xlsx", "jsonl", "csv"))
    assert set(made) >= {"xlsx", "jsonl", "csv", "manifest", "coverage", "report"}
    import openpyxl
    ws = openpyxl.load_workbook(made["xlsx"], read_only=True)["dataset"]
    header = [c.value for c in next(ws.rows)]
    assert "ID выборки" in header and "Файл источника" in header
    found_guard = False
    for row in ws.iter_rows(values_only=True):
        for v in row:
            if isinstance(v, str) and v.startswith("'="):
                found_guard = True
    assert found_guard
    lines = (tmp_path / "out" / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3 and all(json.loads(x) for x in lines)
    m = json.loads((tmp_path / "out" / "manifest.json").read_text(encoding="utf-8"))
    assert len(m["items"]) == 3
    ws2 = openpyxl.load_workbook(made["xlsx"])["dataset"]
    assert ws2.freeze_panes == "A2"
    assert ws2.auto_filter.ref is not None
    assert ws2["A1"].font.bold is True
    assert all(ws2.column_dimensions[c].width for c in ("A", "B", "C"))
    with pytest.raises(ValueError):
        build_manifest(con, 9999)
    con.close()


def test_export_privacy_and_coverage_guard(tmp_path):
    con, bid = _build(tmp_path, [Quota(dim=GROUP, value="=формула", kind="min", amount=1)])
    made = export_package(con, bid, tmp_path / "out3", formats=("jsonl",))
    assert set(made) >= {"manifest", "coverage", "report"}
    m = json.loads((tmp_path / "out3" / "manifest.json").read_text(encoding="utf-8"))
    assert m["sources"] and all("\\" not in s["path"] and "/" not in s["path"]
                                for s in m["sources"])
    cov = (tmp_path / "out3" / "coverage.csv").read_text(encoding="utf-8-sig")
    assert "'=формула" in cov
    rep = (tmp_path / "out3" / "selection_report.txt").read_text(encoding="utf-8")
    assert str(tmp_path) not in rep and "p.csv" in rep
    con.close()


def test_build_note_in_manifest_and_report(tmp_path):
    from core.pool_import import import_source as _imp
    from core.roles import GROUP as _G, MAIN as _M
    from storage.database import connect as _connect
    p = tmp_path / "n.csv"
    p.write_text("З;Г\nодин;А\n", encoding="utf-8-sig")
    con = _connect(tmp_path / "w2.sqlite")
    _imp(con, p, {"З": _M, "Г": _G})
    prof = BuildProfile(target_size=1, seed=1)
    res = sample(con, prof)
    bid = save_build(con, "имя", prof, res["items"], res["reasons"], 0, note="для регресса")
    assert build_manifest(con, bid)["note"] == "для регресса"
    export_package(con, bid, tmp_path / "out2", formats=("jsonl",))
    rep = (tmp_path / "out2" / "selection_report.txt").read_text(encoding="utf-8")
    assert "Описание: для регресса" in rep
    con.close()
