"""Рабочее пространство Builder: SQLite, только локальные данные пользователя.

Храним состояние источников (путь/размер/mtime/sha256/статус) и ПОЛНУЮ КОПИЮ
их содержимого (candidate + raw_json + нормы) — пул, сборки и отчёты строятся
по базе без обращения к исходным файлам. Сами файлы на диске не трогаем.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path

SCHEMA_VERSION = 8


def file_state(path: str | Path) -> dict:
    """Размер/mtime/sha256 для детекта «источник изменился» (ТЗ §4)."""
    p = Path(path)
    st = p.stat()
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return {"size": st.st_size, "mtime": st.st_mtime, "sha256": h.hexdigest()}


BACKUP_KEEP = 10
BACKUP_PREFIX = "datasetbuilder_"


def backup_dir(db_path: str | Path) -> Path:
    d = Path(db_path).parent / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def backup_now(db_path: str | Path) -> str:
    """Копия базы через SQLite backup API (консистентна и при WAL)."""
    import datetime as _dt
    src = Path(db_path)
    if not src.exists() or src.stat().st_size == 0:
        raise ValueError("базу пока нечего копировать: файл пуст")
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = backup_dir(src) / f"{BACKUP_PREFIX}{stamp}.sqlite"
    n = 1
    while dst.exists():
        n += 1
        dst = backup_dir(src) / f"{BACKUP_PREFIX}{stamp}_{n}.sqlite"
    s = sqlite3.connect(str(src))
    try:
        t = sqlite3.connect(str(dst))
        try:
            s.backup(t)
        finally:
            t.close()
    finally:
        s.close()
    olds = sorted(backup_dir(src).glob(f"{BACKUP_PREFIX}*.sqlite"))
    for extra in olds[:max(0, len(olds) - BACKUP_KEEP)]:
        try:
            extra.unlink()
        except OSError:
            pass
    return str(dst)


def connect(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    had_data = db_path.exists() and db_path.stat().st_size > 0
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    _migrate(con, backup_first=had_data)
    return con


def _migrate(con: sqlite3.Connection, backup_first: bool = False):
    cur = con.execute("PRAGMA user_version")
    ver = cur.fetchone()[0] or 0
    if ver < SCHEMA_VERSION and backup_first:
        try:
            db_file = con.execute("PRAGMA database_list").fetchone()[2]
            if db_file:
                backup_now(db_file)
        except Exception:  # noqa: BLE001 — бэкап не должен ронять миграцию
            pass
    if ver < 1:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS source (
          id INTEGER PRIMARY KEY,
          path TEXT NOT NULL UNIQUE,
          format TEXT NOT NULL DEFAULT '',
          sheet TEXT DEFAULT NULL,
          header_row INTEGER NOT NULL DEFAULT 0,
          encoding TEXT NOT NULL DEFAULT 'utf-8-sig',
          delimiter TEXT NOT NULL DEFAULT ',',
          size INTEGER NOT NULL DEFAULT 0,
          mtime REAL NOT NULL DEFAULT 0,
          sha256 TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'new',
          total_rows INTEGER NOT NULL DEFAULT 0,
          usable_rows INTEGER NOT NULL DEFAULT 0,
          added_at REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS source_error (
          id INTEGER PRIMARY KEY,
          source_id INTEGER NOT NULL REFERENCES source(id) ON DELETE CASCADE,
          line INTEGER NOT NULL,
          col TEXT NOT NULL DEFAULT '',
          reason TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_source_error_src ON source_error(source_id);
        """)
        con.execute("PRAGMA user_version=1")
        con.commit()
    if ver < 2:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS source_mapping (
          source_id INTEGER NOT NULL REFERENCES source(id) ON DELETE CASCADE,
          column_name TEXT NOT NULL,
          role TEXT NOT NULL,
          PRIMARY KEY (source_id, column_name)
        );
        CREATE TABLE IF NOT EXISTS candidate (
          id INTEGER PRIMARY KEY,
          source_id INTEGER NOT NULL REFERENCES source(id) ON DELETE CASCADE,
          row_no INTEGER NOT NULL,
          ext_id TEXT NOT NULL DEFAULT '',
          fingerprint TEXT NOT NULL DEFAULT '',
          main_raw TEXT NOT NULL DEFAULT '',
          main_norm TEXT NOT NULL DEFAULT '',
          raw_json TEXT NOT NULL DEFAULT '{}',
          added_at REAL NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_candidate_src ON candidate(source_id);
        CREATE INDEX IF NOT EXISTS idx_candidate_fp ON candidate(fingerprint);
        CREATE TABLE IF NOT EXISTS candidate_dim (
          candidate_id INTEGER NOT NULL REFERENCES candidate(id) ON DELETE CASCADE,
          dim TEXT NOT NULL,
          value_raw TEXT NOT NULL DEFAULT '',
          value_norm TEXT NOT NULL DEFAULT '',
          is_missing INTEGER NOT NULL DEFAULT 1,
          PRIMARY KEY (candidate_id, dim)
        );
        CREATE INDEX IF NOT EXISTS idx_cdim_dim_norm ON candidate_dim(dim, value_norm);
        """)
        con.execute("PRAGMA user_version=2")
        con.commit()
    if ver < 3:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS build (
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL DEFAULT '',
          created_at REAL NOT NULL DEFAULT 0,
          profile_json TEXT NOT NULL DEFAULT '{}',
          seed INTEGER NOT NULL DEFAULT 0,
          mode TEXT NOT NULL DEFAULT '',
          target_size INTEGER NOT NULL DEFAULT 0,
          picked INTEGER NOT NULL DEFAULT 0,
          short INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS build_item (
          build_id INTEGER NOT NULL REFERENCES build(id) ON DELETE CASCADE,
          candidate_id INTEGER NOT NULL,
          reason TEXT NOT NULL DEFAULT '',
          pos INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (build_id, candidate_id)
        );
        CREATE INDEX IF NOT EXISTS idx_bitem_build ON build_item(build_id);
        """)
        con.execute("PRAGMA user_version=3")
        con.commit()
    if ver < 4:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS pinned (
          candidate_id INTEGER PRIMARY KEY,
          added_at REAL NOT NULL DEFAULT 0
        );
        """)
        con.execute("PRAGMA user_version=4")
        con.commit()
    if ver < 5:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS kb_snapshot (
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL DEFAULT '',
          path TEXT NOT NULL DEFAULT '',
          added_at REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS kb_section (
          snapshot_id INTEGER NOT NULL REFERENCES kb_snapshot(id) ON DELETE CASCADE,
          heading TEXT NOT NULL DEFAULT '',
          level INTEGER NOT NULL DEFAULT 0,
          pos INTEGER NOT NULL DEFAULT 0,
          text TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_kbsec_snap ON kb_section(snapshot_id);
        """)
        con.execute("PRAGMA user_version=5")
        con.commit()
    if ver < 6:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS req_profile (
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL UNIQUE,
          profile_json TEXT NOT NULL DEFAULT '{}',
          created_at REAL NOT NULL DEFAULT 0,
          updated_at REAL NOT NULL DEFAULT 0
        );
        """)
        con.execute("PRAGMA user_version=6")
        con.commit()
    if ver < 7:
        cols7 = [r[1] for r in con.execute("PRAGMA table_info(build)").fetchall()]
        if "note" not in cols7:
            con.execute("ALTER TABLE build ADD COLUMN note TEXT NOT NULL DEFAULT ''")
        con.execute("PRAGMA user_version=7")
        con.commit()
    if ver < 8:
        cols = [r[1] for r in con.execute("PRAGMA table_info(source)").fetchall()]
        if "in_pool" not in cols:
            con.execute("ALTER TABLE source ADD COLUMN in_pool INTEGER NOT NULL DEFAULT 1")
        con.executescript("""
        CREATE VIEW IF NOT EXISTS pool_candidate AS
          SELECT * FROM candidate WHERE source_id IN
            (SELECT id FROM source WHERE in_pool=1);
        CREATE VIEW IF NOT EXISTS pool_dim AS
          SELECT d.* FROM candidate_dim d
          JOIN pool_candidate c ON c.id=d.candidate_id;
        """)
        con.execute("PRAGMA user_version=8")
        con.commit()


def upsert_source(con: sqlite3.Connection, path: str | Path, **kwargs) -> int:
    """Регистрирует/обновляет источник, возвращает id."""
    st = file_state(path)
    now = time.time()
    row = con.execute("SELECT id FROM source WHERE path=?", (str(path),)).fetchone()
    if row:
        sid = row["id"]
        sets = {"size": st["size"], "mtime": st["mtime"], "sha256": st["sha256"]}
        sets.update({k: v for k, v in kwargs.items()
                     if k in ("format", "sheet", "header_row", "encoding",
                              "delimiter", "status", "total_rows", "usable_rows")})
        con.execute(
            f"UPDATE source SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?",
            (*sets.values(), sid),
        )
    else:
        cur = con.execute(
            """INSERT INTO source
               (path, format, sheet, header_row, encoding, delimiter,
                size, mtime, sha256, status, total_rows, usable_rows, added_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (str(path), kwargs.get("format", ""), kwargs.get("sheet"),
             kwargs.get("header_row", 0), kwargs.get("encoding", "utf-8-sig"),
             kwargs.get("delimiter", ","), st["size"], st["mtime"], st["sha256"],
             kwargs.get("status", "new"), kwargs.get("total_rows", 0),
             kwargs.get("usable_rows", 0), now),
        )
        sid = cur.lastrowid
    con.commit()
    return sid


def check_changed(con: sqlite3.Connection, source_id: int) -> tuple[bool, str]:
    """Сверяет файл на диске с зафиксированным состоянием."""
    row = con.execute("SELECT * FROM source WHERE id=?", (source_id,)).fetchone()
    if row is None:
        return True, "источник не найден в базе"
    p = Path(row["path"])
    if not p.exists():
        return True, "файл недоступен"
    try:
        st = file_state(p)
    except OSError as e:
        return True, f"не читается: {e}"
    if st["sha256"] != row["sha256"]:
        return True, "содержимое изменилось (sha256)"
    if st["size"] != row["size"] or abs(st["mtime"] - row["mtime"]) > 1e-6:
        return True, "размер/время изменения отличается"
    return False, ""


def save_errors(con: sqlite3.Connection, source_id: int, errors: list) -> None:
    con.execute("DELETE FROM source_error WHERE source_id=?", (source_id,))
    for e in errors[:200]:
        line = e.get("line", 0) if isinstance(e, dict) else getattr(e, "line", 0)
        col = e.get("column", "") if isinstance(e, dict) else getattr(e, "column", "")
        reason = e.get("reason", "") if isinstance(e, dict) else getattr(e, "reason", "")
        con.execute(
            "INSERT INTO source_error(source_id, line, col, reason) VALUES (?,?,?,?)",
            (source_id, line, col, reason),
        )
    con.commit()


def list_sources(con: sqlite3.Connection) -> list[dict]:
    cols = [r[1] for r in con.execute("PRAGMA table_info(source)").fetchall()]
    if "in_pool" in cols:
        rows = con.execute("SELECT * FROM source ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    out = []
    for r in con.execute("SELECT * FROM source ORDER BY id"):
        d = dict(r)
        d["in_pool"] = 1
        out.append(d)
    return out


def set_source_enabled(con: sqlite3.Connection, source_id: int, on: bool) -> None:
    con.execute("UPDATE source SET in_pool=? WHERE id=?", (1 if on else 0, source_id))
    con.commit()


def delete_source(con: sqlite3.Connection, source_id: int) -> dict:
    """Удаляет источник из пула (файл на диске не трогаем).

    Сборки иммутабельны: если источник уже использован в сборках,
    удаление запрещено — сначала удали эти сборки.
    """
    row = con.execute("SELECT path FROM source WHERE id=?", (source_id,)).fetchone()
    if row is None:
        raise ValueError(f"источник {source_id} не найден")
    used = [r[0] for r in con.execute(
        """SELECT DISTINCT build_id FROM build_item WHERE candidate_id IN
           (SELECT id FROM candidate WHERE source_id=?)""", (source_id,)).fetchall()]
    if used:
        nums = ", ".join(f"#{b}" for b in sorted(used))
        raise ValueError(f"источник используется в сборках {nums} — сначала удали их")
    cids = [r[0] for r in con.execute(
        "SELECT id FROM candidate WHERE source_id=?", (source_id,)).fetchall()]
    if cids:
        marks = ",".join("?" for _ in cids)
        con.execute(f"DELETE FROM pinned WHERE candidate_id IN ({marks})", (*cids,))
    con.execute("DELETE FROM source WHERE id=?", (source_id,))
    con.commit()
    return {"deleted": source_id, "candidates": len(cids)}


def save_mapping(con: sqlite3.Connection, source_id: int, mapping: dict[str, str]) -> None:
    con.execute("DELETE FROM source_mapping WHERE source_id=?", (source_id,))
    for col, role in mapping.items():
        con.execute(
            "INSERT INTO source_mapping(source_id, column_name, role) VALUES (?,?,?)",
            (source_id, col, role),
        )
    con.commit()


def load_mapping(con: sqlite3.Connection, source_id: int) -> dict[str, str]:
    return {r["column_name"]: r["role"] for r in
            con.execute("SELECT * FROM source_mapping WHERE source_id=?", (source_id,))}


def clear_pool(con: sqlite3.Connection, source_id: int) -> None:
    con.execute("DELETE FROM candidate WHERE source_id=?", (source_id,))
    con.commit()


def pool_counts(con: sqlite3.Connection) -> dict:
    row = con.execute(
        "SELECT COUNT(*) c, COUNT(DISTINCT fingerprint) u FROM pool_candidate").fetchone()
    return {"total": row["c"], "uniq_fp": row["u"]}


def save_build(con: sqlite3.Connection, name: str, profile, items: list[int],
               reasons: dict, short: int = 0, note: str = "") -> int:
    """Сохраняет сборку как неизменяемый снимок. Возвращает id."""
    import json as _json
    import time as _time
    from dataclasses import asdict as _asdict
    cur = con.execute(
        """INSERT INTO build(name, created_at, profile_json, seed, mode,
           target_size, picked, short, note) VALUES (?,?,?,?,?,?,?,?,?)""",
        (name, _time.time(), _json.dumps(_asdict(profile), ensure_ascii=False),
         profile.seed, profile.mode, profile.target_size, len(items), short, note),
    )
    bid = cur.lastrowid
    con.executemany(
        "INSERT INTO build_item(build_id, candidate_id, reason, pos) VALUES (?,?,?,?)",
        [(bid, cid, reasons.get(cid, ""), i) for i, cid in enumerate(items)],
    )
    con.commit()
    return bid


def list_builds(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in
            con.execute("SELECT * FROM build ORDER BY id DESC")]


def set_pinned(con: sqlite3.Connection, ids: list[int]) -> None:
    import time as _time
    con.executemany("INSERT OR IGNORE INTO pinned(candidate_id, added_at) VALUES (?,?)",
                    [(i, _time.time()) for i in ids])
    con.commit()


def unpin(con: sqlite3.Connection, ids: list[int]) -> None:
    marks = ",".join("?" for _ in ids)
    if marks:
        con.execute(f"DELETE FROM pinned WHERE candidate_id IN ({marks})", (*ids,))
        con.commit()


def list_pinned(con: sqlite3.Connection) -> list[int]:
    return [r[0] for r in con.execute("SELECT candidate_id FROM pinned ORDER BY candidate_id")]


def save_kb_snapshot(con: sqlite3.Connection, name: str, path: str,
                     sections: list[dict]) -> int:
    import time as _time
    cur = con.execute("INSERT INTO kb_snapshot(name, path, added_at) VALUES (?,?,?)",
                      (name, path, _time.time()))
    sid = cur.lastrowid
    con.executemany(
        "INSERT INTO kb_section(snapshot_id, heading, level, pos, text) VALUES (?,?,?,?,?)",
        [(sid, s.get("heading", ""), s.get("level", 0), s.get("pos", 0),
          s.get("text", "")) for s in sections],
    )
    con.commit()
    return sid


def list_kb_snapshots(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in
            con.execute("SELECT * FROM kb_snapshot ORDER BY id DESC")]


def load_kb_sections(con: sqlite3.Connection, snapshot_id: int) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT heading, level, pos, text FROM kb_section "
        "WHERE snapshot_id=? ORDER BY pos", (snapshot_id,))]


def save_req_profile(con: sqlite3.Connection, name: str, profile: dict) -> int:
    """Сохранить именованную конфигурацию (по имени — перезапись)."""
    import json as _json
    import time as _time
    blob = _json.dumps(profile, ensure_ascii=False)
    row = con.execute("SELECT id FROM req_profile WHERE name=?", (name,)).fetchone()
    if row:
        con.execute("UPDATE req_profile SET profile_json=?, updated_at=? WHERE id=?",
                    (blob, _time.time(), row["id"]))
        con.commit()
        return row["id"]
    cur = con.execute(
        "INSERT INTO req_profile(name, profile_json, created_at, updated_at) VALUES (?,?,?,?)",
        (name, blob, _time.time(), _time.time()))
    con.commit()
    return cur.lastrowid


def list_req_profiles(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in
            con.execute("SELECT id, name, updated_at FROM req_profile ORDER BY name")]


def load_req_profile(con: sqlite3.Connection, pid: int) -> dict:
    import json as _json
    row = con.execute("SELECT profile_json FROM req_profile WHERE id=?", (pid,)).fetchone()
    if row is None:
        raise ValueError(f"профиль {pid} не найден")
    return _json.loads(row["profile_json"] or "{}")


def delete_req_profile(con: sqlite3.Connection, pid: int) -> None:
    con.execute("DELETE FROM req_profile WHERE id=?", (pid,))
    con.commit()


def delete_build(con: sqlite3.Connection, bid: int) -> dict:
    """Удаляет сборку и её состав. Возвращает имена профилей, где она упомянута."""
    import json as _json
    refs = []
    for p in con.execute("SELECT name, profile_json FROM req_profile").fetchall():
        try:
            d = _json.loads(p["profile_json"] or "{}")
        except ValueError:
            continue
        if bid in (d.get("exclude_builds") or []) or d.get("keep_build") == bid:
            refs.append(p["name"])
    con.execute("DELETE FROM build_item WHERE build_id=?", (bid,))
    con.execute("DELETE FROM build WHERE id=?", (bid,))
    con.commit()
    return {"deleted": bid, "referenced_in": refs}
