"""Хранилище: регистрация источников и детект изменений."""
import sqlite3
from pathlib import Path

from storage.database import (
    check_changed,
    connect,
    delete_build,
    delete_req_profile,
    list_req_profiles,
    list_sources,
    load_req_profile,
    save_req_profile,
    upsert_source,
)


def test_upsert_and_change(tmp_path):
    f = tmp_path / "a.csv"
    f.write_text("a\n1\n", encoding="utf-8")
    con = connect(tmp_path / "ws.sqlite")
    sid = upsert_source(con, f, format="csv", status="ok")
    changed, _ = check_changed(con, sid)
    assert not changed
    f.write_text("a\n1\n2\n", encoding="utf-8")
    changed, why = check_changed(con, sid)
    assert changed and "sha256" in why
    assert len(list_sources(con)) == 1
    con.close()


def test_req_profile_crud(tmp_path):
    con = connect(tmp_path / "ws.sqlite")
    pid = save_req_profile(con, "base", {"target_size": 100, "seed": 7})
    assert len(list_req_profiles(con)) == 1
    assert load_req_profile(con, pid)["seed"] == 7
    save_req_profile(con, "base", {"target_size": 200, "seed": 8})  # перезапись
    assert len(list_req_profiles(con)) == 1
    assert load_req_profile(con, pid)["target_size"] == 200
    delete_req_profile(con, pid)
    assert list_req_profiles(con) == []
    con.close()


def test_build_delete_cascade_and_refs(tmp_path):
    from core.requirements import BuildProfile, profile_to_dict  # noqa: E402
    con = connect(tmp_path / "ws.sqlite")
    cur = con.execute("INSERT INTO build(name, target_size, picked) VALUES (?,?,?)",
                      ("t", 1, 1))
    bid = cur.lastrowid
    con.execute("INSERT INTO build_item(build_id, candidate_id, pos) VALUES (?,?,?)",
                (bid, 999, 0))
    prof = profile_to_dict(BuildProfile(exclude_builds=[bid]))
    save_req_profile(con, "p1", prof)
    out = delete_build(con, bid)
    assert out["referenced_in"] == ["p1"]
    assert con.execute("SELECT COUNT(*) FROM build_item WHERE build_id=?",
                       (bid,)).fetchone()[0] == 0
    con.close()


def test_backup_copy_and_rotation(tmp_path):
    from storage.database import SCHEMA_VERSION, backup_now, connect as _connect
    db = tmp_path / "w.sqlite"
    con = _connect(db)
    con.execute("CREATE TABLE t(x TEXT)")
    con.commit()
    con.close()
    p1 = backup_now(db)
    assert Path(p1).exists()
    con2 = sqlite3.connect(p1)
    try:
        assert con2.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
        assert con2.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    finally:
        con2.close()
    for _ in range(12):
        backup_now(db)
    olds = list((tmp_path / "backups").glob("datasetbuilder_*.sqlite"))
    assert 1 <= len(olds) <= 10


def test_migration_makes_backup(tmp_path):
    from storage.database import connect as _connect
    db = tmp_path / "w.sqlite"
    con = _connect(db)
    con.execute("CREATE TABLE t(x TEXT)")
    con.execute("PRAGMA user_version=0")
    con.commit()
    con.close()
    con = _connect(db)
    con.close()
    assert list((tmp_path / "backups").glob("datasetbuilder_*.sqlite"))
