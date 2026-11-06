"""Покрытие: доступно/нужно/дефицит по каждой квоте. Без общих баллов."""

from __future__ import annotations

import sqlite3

from core.filter_service import apply_filters, build_items_union
from core.normalize import norm_key
from core.requirements import BuildProfile


def coverage(con: sqlite3.Connection, profile: BuildProfile) -> dict:
    profile.validate()
    eligible = apply_filters(con, profile.filters)
    old = build_items_union(con, profile.exclude_builds)
    if old and profile.min_new == 0:
        # жёсткое исключение: старые записи не участвуют вообще
        all_ids = {r[0] for r in con.execute("SELECT id FROM pool_candidate").fetchall()}
        eligible = (all_ids if eligible is None else eligible) - old
    if eligible is None:
        total_elig = con.execute("SELECT COUNT(*) FROM pool_candidate").fetchone()[0]
        new_avail = total_elig - len(old)
    else:
        total_elig = len(eligible)
        new_avail = len(set(eligible) - old)
    cells = []
    def _cell_set(dim, value):
        return {r[0] for r in con.execute(
            "SELECT candidate_id FROM pool_dim WHERE dim=? AND value_norm=?",
            (dim, norm_key(value))).fetchall()}

    for q in profile.quotas:
        q.validate()
        need = q.amount
        if q.kind == "percent":
            need = round(profile.target_size * q.amount / 100)
        rows = _cell_set(q.dim, q.value)
        if q.dim2 and q.value2:
            rows &= _cell_set(q.dim2, q.value2)
        avail = len(rows) if eligible is None else len(rows & eligible)
        status = "ok" if avail >= need else ("short" if q.kind in ("min", "exact") else "warn")
        if q.kind == "max" and avail < need:
            status = "ok"  # max не требует минимума
        cells.append({"dim": q.dim, "value": q.value, "kind": q.kind,
                      "dim2": q.dim2, "value2": q.value2,
                      "need": need, "avail": avail, "label": q.label(),
                      "deficit": max(0, need - avail), "status": status})
    impossible = [c for c in cells if c["status"] == "short"]
    return {"eligible": total_elig, "target": profile.target_size,
            "cells": cells, "impossible": impossible,
            "feasible": not impossible and total_elig >= profile.target_size,
            "excluded": len(old), "new_avail": new_avail}
