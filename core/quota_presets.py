"""Пресеты квот: пропорционально пулу или равномерно. Без магии."""

from __future__ import annotations

import sqlite3

from core.filter_service import apply_filters
from core.requirements import BuildProfile, Quota


def _values_in_scope(con: sqlite3.Connection, dim: str,
                     eligible: set[int] | None) -> list[tuple[str, str, int]]:
    """(norm, raw, count) значений измерения в области фильтров."""
    rows = con.execute(
        "SELECT candidate_id, value_norm, value_raw FROM pool_dim "
        "WHERE dim=? AND is_missing=0", (dim,)).fetchall()
    agg: dict[str, list] = {}
    for cid, norm, raw in rows:
        if eligible is not None and cid not in eligible:
            continue
        cell = agg.setdefault(norm, [raw, 0])
        cell[1] += 1
    return [(n, v[0], v[1]) for n, v in sorted(agg.items(), key=lambda kv: -kv[1][1])]


def proportional(con: sqlite3.Connection, profile: BuildProfile, dim: str) -> list[Quota]:
    """Доля каждой ячейки = доле в пуле (вид: процент)."""
    eligible = apply_filters(con, profile.filters)
    vals = _values_in_scope(con, dim, eligible)
    total = sum(c for _, _, c in vals)
    if not total:
        raise ValueError(f"в измерении {dim!r} нет значений под фильтрами")
    return [Quota(dim=dim, value=raw, kind="percent",
                  amount=round(100.0 * cnt / total, 1))
            for _, raw, cnt in vals]


def uniform(con: sqlite3.Connection, profile: BuildProfile, dim: str) -> list[Quota]:
    """Поровну на ячейку (вид: точно, метод наибольших остатков)."""
    eligible = apply_filters(con, profile.filters)
    vals = _values_in_scope(con, dim, eligible)
    if not vals:
        raise ValueError(f"в измерении {dim!r} нет значений под фильтрами")
    n = len(vals)
    base, rest = divmod(profile.target_size, n)
    quotas = []
    for i, (_, raw, _) in enumerate(vals):
        quotas.append(Quota(dim=dim, value=raw, kind="exact",
                            amount=base + (1 if i < rest else 0)))
    return quotas
