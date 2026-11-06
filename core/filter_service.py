"""Применение фильтров: dim-условия -> множество candidate.id."""

from __future__ import annotations

import sqlite3

from core.normalize import norm_key
from core.requirements import Filter


def _numbers(texts: list[str]) -> list[float]:
    out = []
    for t in texts:
        try:
            out.append(float(t.replace(" ", "").replace(",", ".")))
        except ValueError:
            pass
    return out


def apply_filters(con: sqlite3.Connection, filters: list[Filter]) -> set[int] | None:
    """None — фильтров нет (все кандидаты). Иначе множество подходящих id."""
    if not filters:
        return None
    result: set[int] | None = None
    for f in filters:
        f.validate()
        ids = _one_filter(con, f)
        result = ids if result is None else (result & ids)
        if not result:
            return set()
    return result


def build_items_union(con: sqlite3.Connection, bids: list[int]) -> set[int]:
    """Все записи указанных сборок (для новизны)."""
    out: set[int] = set()
    for bid in bids or []:
        out.update(r[0] for r in con.execute(
            "SELECT candidate_id FROM build_item WHERE build_id=?", (bid,)))
    return out


def _one_filter(con: sqlite3.Connection, f: Filter) -> set[int]:
    if f.op == "missing":
        rows = con.execute(
            """SELECT c.id FROM pool_candidate c LEFT JOIN pool_dim d
               ON d.candidate_id=c.id AND d.dim=? WHERE d.value_norm IS NULL
               OR d.value_norm='' OR d.is_missing=1""", (f.dim,)).fetchall()
        return {r[0] for r in rows}
    if f.op == "notmissing":
        rows = con.execute(
            "SELECT candidate_id FROM pool_dim WHERE dim=? AND is_missing=0",
            (f.dim,)).fetchall()
        return {r[0] for r in rows}
    if f.op == "contains":
        needle = norm_key(f.value)
        rows = con.execute(
            "SELECT candidate_id, value_norm FROM pool_dim WHERE dim=?", (f.dim,)).fetchall()
        return {cid for cid, norm in rows if needle in (norm or "")}
    if f.op in ("eq", "ne", "in", "notin"):
        if f.op in ("eq", "ne"):
            norms = [norm_key(f.value)]
        else:
            norms = [norm_key(v) for v in f.values]
        marks = ",".join("?" for _ in norms)
        rows = con.execute(
            f"SELECT candidate_id FROM pool_dim WHERE dim=? AND value_norm IN ({marks})",
            (f.dim, *norms)).fetchall()
        hit = {r[0] for r in rows}
        if f.op in ("eq", "in"):
            return hit
        all_ids = {r[0] for r in con.execute("SELECT id FROM pool_candidate").fetchall()}
        return all_ids - hit
    # gt / lt — числовое сравнение по raw
    nums = _numbers([f.value])
    if not nums:
        raise ValueError(f"{f.op} требует число, получили {f.value!r}")
    bound = nums[0]
    rows = con.execute(
        "SELECT candidate_id, value_raw FROM pool_dim WHERE dim=? AND is_missing=0",
        (f.dim,)).fetchall()
    out = set()
    for cid, raw in rows:
        for n in _numbers([raw or ""]):
            if (f.op == "gt" and n > bound) or (f.op == "lt" and n < bound):
                out.add(cid)
    return out
