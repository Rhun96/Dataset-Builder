"""Профиль пула: сводка + распределения по измерениям. Только SQL-агрегаты.

Без source_id — весь пул (включённые источники). С source_id — один источник.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from core.roles import dim_label


def _cand(table: str, source_id: int | None) -> tuple[str, str, list]:
    """(таблица, условие на источник, параметры)."""
    if source_id is None:
        return "pool_candidate", "", []
    return "candidate", " AND source_id=?", [source_id]


def _dim_in_pool(source_id: int | None) -> tuple[str, str, list]:
    """(таблица dims, условие на источник, параметры)."""
    if source_id is None:
        return "pool_dim", "", []
    return ("candidate_dim",
            " AND candidate_id IN (SELECT id FROM candidate WHERE source_id=?)",
            [source_id])


def get_summary(con: sqlite3.Connection, source_id: int | None = None) -> dict:
    ct, cw, cp = _cand("candidate", source_id)
    total = con.execute(f"SELECT COUNT(*) FROM {ct} WHERE 1=1{cw}", cp).fetchone()[0]
    uniq_fp = con.execute(
        f"SELECT COUNT(DISTINCT fingerprint) FROM {ct} WHERE 1=1{cw}", cp).fetchone()[0]
    no_ext = con.execute(
        f"SELECT COUNT(*) FROM {ct} WHERE ext_id='' {cw}", cp).fetchone()[0]
    if source_id is None:
        srcs = con.execute(
            "SELECT COUNT(*) FROM source WHERE status='ok' AND in_pool=1").fetchone()[0]
        dims = [r[0] for r in con.execute("SELECT DISTINCT dim FROM pool_dim")]
    else:
        srcs = 1
        dims = [r[0] for r in con.execute(
            "SELECT DISTINCT dim FROM candidate_dim WHERE candidate_id IN "
            "(SELECT id FROM candidate WHERE source_id=?)", [source_id])]
    return {"total": total, "uniq_fp": uniq_fp, "exact_dupes": total - uniq_fp,
            "no_ext_id": no_ext, "sources_ok": srcs, "dims": sorted(dims)}


def list_dims(con: sqlite3.Connection) -> list[tuple[str, str]]:
    dims = [r[0] for r in con.execute("SELECT DISTINCT dim FROM pool_dim ORDER BY dim")]
    return [(d, dim_label(d)) for d in dims]


def source_dims(con: sqlite3.Connection, source_id: int) -> list[tuple[str, str]]:
    dims = [r[0] for r in con.execute(
        "SELECT DISTINCT dim FROM candidate_dim WHERE candidate_id IN "
        "(SELECT id FROM candidate WHERE source_id=?) ORDER BY dim", [source_id])]
    return [(d, dim_label(d)) for d in dims]


def dim_values(con: sqlite3.Connection, dim: str, limit: int = 200) -> list[str]:
    rows = con.execute(
        """SELECT value_raw FROM pool_dim WHERE dim=? AND is_missing=0
           GROUP BY value_norm ORDER BY COUNT(*) DESC, value_raw LIMIT ?""",
        (dim, limit)).fetchall()
    return [r[0] for r in rows]


def dim_distribution(con: sqlite3.Connection, dim: str, limit: int = 50,
                     source_id: int | None = None) -> dict:
    ct, cw, cp = _cand("candidate", source_id)
    total = con.execute(f"SELECT COUNT(*) FROM {ct} WHERE 1=1{cw}", cp).fetchone()[0]
    dt, dw, dp = _dim_in_pool(source_id)
    filled = con.execute(
        f"SELECT COUNT(*) FROM {dt} WHERE dim=? AND is_missing=0{dw}",
        (dim, *dp)).fetchone()[0]
    uniq = con.execute(
        "SELECT COUNT(DISTINCT value_norm) FROM "
        f"{dt} WHERE dim=? AND is_missing=0{dw}", (dim, *dp)).fetchone()[0]
    top = con.execute(
        f"SELECT value_raw, value_norm, COUNT(*) c FROM {dt} "
        f"WHERE dim=?{dw} GROUP BY value_norm ORDER BY c DESC, value_norm LIMIT ?",
        (dim, *dp, limit)).fetchall()
    rows = [{"raw": r[0], "norm": r[1], "count": r[2],
             "pct": (100.0 * r[2] / total if total else 0)} for r in top]
    missing = total - filled
    return {"dim": dim, "label": dim_label(dim), "total": total, "filled": filled,
            "missing": missing,
            "fill_pct": (100.0 * filled / total if total else 0),
            "unique": uniq, "top": rows}


def sources_breakdown(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in con.execute(
        """SELECT s.path, s.status, s.in_pool, COUNT(c.id) AS cnt
           FROM source s LEFT JOIN candidate c ON c.source_id=s.id
           GROUP BY s.id ORDER BY s.id""")]


def pool_overview(con: sqlite3.Connection, source_id: int | None = None) -> dict:
    if source_id is None:
        row = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(size),0) FROM source "
            "WHERE status='ok' AND in_pool=1").fetchone()
        total = con.execute("SELECT COUNT(*) FROM pool_candidate").fetchone()[0]
        return {"sources": row[0], "bytes": row[1], "records": total}
    row = con.execute("SELECT path, size FROM source WHERE id=?", [source_id]).fetchone()
    total = con.execute(
        "SELECT COUNT(*) FROM candidate WHERE source_id=?", [source_id]).fetchone()[0]
    return {"sources": 1, "bytes": row[1] if row else 0, "records": total,
            "name": Path(row[0]).name if row else ""}


def fill_rate(con: sqlite3.Connection, source_id: int | None = None) -> dict:
    dt, dw, dp = _dim_in_pool(source_id)
    row = con.execute(
        f"SELECT COUNT(*), SUM(is_missing=0) FROM {dt} WHERE 1=1{dw}", dp).fetchone()
    total, filled = row[0] or 0, row[1] or 0
    ndims = con.execute(
        f"SELECT COUNT(DISTINCT dim) FROM {dt} WHERE 1=1{dw}", dp).fetchone()[0]
    return {"total": total, "filled": filled,
            "pct": (100.0 * filled / total if total else 0.0), "dims": ndims}


def anomalies(con: sqlite3.Connection, source_id: int | None = None) -> dict:
    ct, cw, cp = _cand("candidate", source_id)
    total = con.execute(f"SELECT COUNT(*) FROM {ct} WHERE 1=1{cw}", cp).fetchone()[0]
    uniq_fp = con.execute(
        f"SELECT COUNT(DISTINCT fingerprint) FROM {ct} WHERE 1=1{cw}", cp).fetchone()[0]
    no_ext = con.execute(
        f"SELECT COUNT(*) FROM {ct} WHERE ext_id='' {cw}", cp).fetchone()[0]
    dt, dw, dp = _dim_in_pool(source_id)
    if source_id is None:
        srcs = con.execute(
            """SELECT s.path, COUNT(c.id) AS cnt FROM source s
               LEFT JOIN pool_candidate c ON c.source_id=s.id
               WHERE s.in_pool=1 GROUP BY s.id ORDER BY cnt DESC""").fetchall()
    else:
        srcs = []
    top_share, top_name = 0.0, ""
    if srcs and total:
        top_share = srcs[0][1] / total
        top_name = Path(srcs[0][0]).name
    rare = con.execute(
        "SELECT COUNT(*) FROM ("
        f"SELECT 1 FROM {dt} WHERE is_missing=0{dw} "
        "GROUP BY dim, value_norm HAVING COUNT(*)=1)", dp).fetchone()[0]
    multi = len(srcs) > 1 if source_id is None else False
    return {"dupes": total - uniq_fp, "no_ext_id": no_ext,
            "imbalance": top_share >= 0.7 and multi,
            "top_share": round(100.0 * top_share, 1), "top_source": top_name,
            "rare": rare}
