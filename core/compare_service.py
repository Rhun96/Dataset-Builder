"""Сравнение сборок: добавлено/исключено/сохранено, сдвиги покрытия и баланса."""

from __future__ import annotations

import sqlite3
from collections import Counter


def _items(con: sqlite3.Connection, bid: int) -> set[int]:
    return {r[0] for r in con.execute(
        "SELECT candidate_id FROM build_item WHERE build_id=?", (bid,)).fetchall()}


def compare_builds(con: sqlite3.Connection, old_id: int, new_id: int) -> dict:
    old, new = _items(con, old_id), _items(con, new_id)

    def _dist(ids: set[int], dim: str) -> Counter:
        if not ids:
            return Counter()
        marks = ",".join("?" for _ in ids)
        rows = con.execute(
            f"""SELECT value_raw, COUNT(*) FROM candidate_dim
                WHERE dim=? AND candidate_id IN ({marks})
                GROUP BY value_norm ORDER BY COUNT(*) DESC""",
            (dim, *ids)).fetchall()
        return Counter({r[0]: r[1] for r in rows})

    dims = [r[0] for r in con.execute(
        "SELECT DISTINCT dim FROM candidate_dim ORDER BY dim").fetchall()]
    coverage_delta = {}
    for d in dims:
        a, b = _dist(old, d), _dist(new, d)
        if a != b:
            coverage_delta[d] = {"old": dict(a), "new": dict(b)}
    srcs = {r[0]: r[1] for r in con.execute("SELECT id, path FROM source").fetchall()}

    def _src(ids: set[int]) -> dict:
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        rows = con.execute(
            f"""SELECT source_id, COUNT(*) FROM candidate
                WHERE id IN ({marks}) GROUP BY source_id""",
            (*ids,)).fetchall()
        from pathlib import Path as _P
        return {_P(srcs.get(r[0], "?")).name: r[1] for r in rows}

    return {"old_id": old_id, "new_id": new_id,
            "kept": sorted(old & new), "added": sorted(new - old),
            "removed": sorted(old - new),
            "coverage_delta": coverage_delta,
            "sources_old": _src(old), "sources_new": _src(new)}
