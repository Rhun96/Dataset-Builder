"""Замена записей: та же ячейка покрытия, новая ревизия сборки."""

from __future__ import annotations

import json
import random
import sqlite3

from core.build_manifest import _profile_from_json
from storage.database import save_build


def _signature(con: sqlite3.Connection, cid: int) -> dict[str, str]:
    return {r["dim"]: r["value_norm"] for r in con.execute(
        "SELECT dim, value_norm FROM candidate_dim WHERE candidate_id=?", (cid,))}


def _same_cell(con: sqlite3.Connection, sig: dict[str, str],
               exclude: set[int]) -> list[int]:
    """Кандидаты с тем же набором измерений. Стабильный порядок."""
    if not sig:
        rows = con.execute("SELECT id FROM candidate ORDER BY id").fetchall()
        return [r[0] for r in rows if r[0] not in exclude]
    cands: set[int] | None = None
    for dim, norm in sig.items():
        hit = {r[0] for r in con.execute(
            "SELECT candidate_id FROM candidate_dim WHERE dim=? AND value_norm=?",
            (dim, norm)).fetchall()}
        cands = hit if cands is None else (cands & hit)
        if not cands:
            return []
    assert cands is not None
    # без лишних измерений: то же множество dim
    out = []
    for cid in sorted(cands - exclude):
        if _signature(con, cid) == sig:
            out.append(cid)
    return out


def replace_items(con: sqlite3.Connection, build_id: int, victim_ids: list[int],
                  seed: int = 1) -> dict:
    b = con.execute("SELECT * FROM build WHERE id=?", (build_id,)).fetchone()
    if b is None:
        raise ValueError(f"сборка {build_id} не найдена")
    profile = _profile_from_json(json.loads(b["profile_json"] or "{}"))
    items = con.execute(
        "SELECT candidate_id, reason, pos FROM build_item WHERE build_id=? ORDER BY pos",
        (build_id,)).fetchall()
    in_build = {x["candidate_id"] for x in items}
    rng = random.Random(seed)
    replaced: dict[int, int] = {}
    unreplaced: list[int] = []
    used = set(in_build)
    for v in victim_ids:
        if v not in in_build:
            continue
        sig = _signature(con, v)
        pool = _same_cell(con, sig, used)
        if not pool:
            unreplaced.append(v)
            continue
        rng.shuffle(pool)
        new = pool[0]
        replaced[v] = new
        used.add(new)
    new_items: list[int] = []
    reasons: dict[int, str] = {}
    old_reasons = {x["candidate_id"]: x["reason"] for x in items}
    for x in items:
        cid = x["candidate_id"]
        if cid in replaced:
            new_items.append(replaced[cid])
            reasons[replaced[cid]] = f"замена из той же ячейки вместо {cid}"
        else:
            new_items.append(cid)
            reasons[cid] = old_reasons[cid]
    short = max(0, profile.target_size - len(new_items))
    bid = save_build(con, f"{b['name']} замена {len(replaced)}",
                     profile, new_items, reasons, short, note=b["note"])
    total = con.execute("SELECT COUNT(*) FROM candidate").fetchone()[0]
    return {"build_id": bid, "replaced": replaced, "unreplaced": unreplaced,
            "pool_outside": total - len(in_build)}
