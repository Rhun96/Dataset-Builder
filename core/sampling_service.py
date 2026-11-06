"""Отбор: существующие записи, детерминированный seed, причины включения.

Порядок: обязательные минимумы/точные -> проценты -> добрать случайно.
Максимумы режут перебор в конце. Журнал причин ведётся сразу, не постфактум.
"""

from __future__ import annotations

import random
import sqlite3

from core.filter_service import apply_filters, build_items_union
from core.normalize import norm_key
from core.requirements import BuildProfile

ALGO_VERSION = 3  # +стратификация, доли, новизна, разнообразие, редкость


def _jaccard_over(a: frozenset, b: frozenset, thr: float) -> bool:
    """True, если сходство точно выше порога (с ранним выходом)."""
    if not a or not b:
        return False
    inter = 0
    smaller, larger = (a, b) if len(a) <= len(b) else (b, a)
    # верхняя граница: inter <= len(smaller)
    for t in smaller:
        if t in larger:
            inter += 1
            # оптимистичная оценка: (inter + rest) / union
            if inter / max(len(a) + len(b) - inter, 1) > thr:
                return True
    union = len(a) + len(b) - inter
    return inter / max(union, 1) > thr


def _cell_members(con: sqlite3.Connection, dim: str, value: str,
                  eligible: set[int] | None) -> list[int]:
    rows = con.execute(
        "SELECT candidate_id FROM pool_dim WHERE dim=? AND value_norm=?",
        (dim, norm_key(value))).fetchall()
    ids = [r[0] for r in rows]
    if eligible is not None:
        keep = set(ids) & eligible
        ids = [i for i in ids if i in keep]
    ids.sort()  # стабильность до shuffle с seed
    return ids


def quota_members(con: sqlite3.Connection, q, eligible: set[int] | None) -> list[int]:
    """Ячейка квоты: одно измерение или пересечение двух."""
    ids = set(_cell_members(con, q.dim, q.value, eligible))
    if q.dim2 and q.value2:
        ids &= set(_cell_members(con, q.dim2, q.value2, eligible))
    return sorted(ids)


def sample(con: sqlite3.Connection, profile: BuildProfile) -> dict:
    profile.validate()
    rng = random.Random(profile.seed)
    eligible = apply_filters(con, profile.filters)
    if eligible is None:
        eligible = {r[0] for r in con.execute("SELECT id FROM pool_candidate").fetchall()}
    else:
        eligible = set(eligible)
    old = build_items_union(con, profile.exclude_builds)
    if old and profile.min_new == 0:
        # жёсткое исключение: старые записи не участвуют вообще
        eligible -= old
    new_ids = eligible - old

    src_of = {r[0]: r[1] for r in
              con.execute("SELECT id, source_id FROM pool_candidate").fetchall()}
    cap = None
    if profile.max_source_pct > 0:
        cap = max(1, int(profile.target_size * profile.max_source_pct / 100))
    from collections import Counter
    src_count: Counter = Counter()

    chosen: list[int] = []
    reasons: dict[int, str] = {}
    pinned_skipped: list[int] = []
    kept: list[int] = []
    kept_skipped: list[int] = []
    div_skipped: int = 0

    div_thr = profile.div_threshold or (0.85 if profile.mode == "mixed" else 0)
    rarity_on = profile.rarity or profile.mode == "mixed"

    norms: dict[int, str] = {}
    if div_thr:
        norms = {r[0]: r[1] for r in
                 con.execute("SELECT id, main_norm FROM pool_candidate").fetchall()}
    tok_cache: dict[int, frozenset] = {}

    def _toks(cid: int) -> frozenset:
        t = tok_cache.get(cid)
        if t is None:
            t = frozenset((norms.get(cid) or "").split())
            tok_cache[cid] = t
        return t

    def _too_similar(cid: int) -> bool:
        a = _toks(cid)
        if not a:
            return False
        # окно: весь состав до 2000, дальше последние 500 (иначе O(n^2))
        rivals = chosen if len(chosen) <= 2000 else chosen[-500:]
        return any(_jaccard_over(a, _toks(o), div_thr) for o in rivals)

    freq: dict = {}
    if rarity_on:
        for d, n, c in con.execute(
                "SELECT dim, value_norm, COUNT(*) FROM pool_dim "
                "GROUP BY dim, value_norm").fetchall():
            freq[(d, n)] = c
    score_cache: dict[int, float] = {}

    def _score(cid: int) -> float:
        s = score_cache.get(cid)
        if s is None:
            s = 0.0
            for d, n in con.execute(
                    "SELECT dim, value_norm FROM pool_dim WHERE candidate_id=?",
                    (cid,)).fetchall():
                s += 1.0 / freq.get((d, n), 1)
            score_cache[cid] = s
        return s

    def _capped(cid: int) -> bool:
        return cap is not None and src_count[src_of.get(cid, -1)] >= cap

    def _take(cid: int, why: str, count_src: bool = True, div: bool = True):
        nonlocal div_skipped
        if cid in reasons or cid not in eligible or _capped(cid):
            return False
        if div and div_thr and _too_similar(cid):
            div_skipped += 1
            return False
        chosen.append(cid)
        reasons[cid] = why
        if count_src:
            src_count[src_of.get(cid, -1)] += 1
        return True

    def _new_first(ids: list[int]) -> list[int]:
        fresh = [c for c in ids if c not in reasons]
        new = [c for c in fresh if c in new_ids]
        oldies = [c for c in fresh if c not in new_ids]
        if rarity_on:
            new.sort(key=lambda c: (-_score(c), rng.random()))
            oldies.sort(key=lambda c: (-_score(c), rng.random()))
        else:
            rng.shuffle(new)
            rng.shuffle(oldies)
        return new + oldies

    pool = _new_first(sorted(eligible))

    # сохранить часть старого состава — явно, поверх лимитов
    if profile.keep_build is not None and profile.keep_min > 0:
        keep_cands = [r[0] for r in con.execute(
            "SELECT candidate_id FROM build_item WHERE build_id=? ORDER BY pos",
            (profile.keep_build,))]
        for cid in keep_cands[:profile.keep_min]:
            if len(chosen) >= profile.target_size:
                break
            if _take(cid, f"сохранено из сборки #{profile.keep_build}",
                     count_src=False, div=False):
                kept.append(cid)
            else:
                kept_skipped.append(cid)

    # закреплённые идут следом, пока влезают в цель
    try:
        from storage.database import list_pinned as _pinned
        for cid in _pinned(con):
            if len(chosen) >= profile.target_size:
                break
            if cid in eligible:
                _take(cid, "закреплено вручную", count_src=False, div=False)
            else:
                pinned_skipped.append(cid)
    except Exception:  # noqa: BLE001 — старая база без таблицы pinned
        pass

    if profile.mode == "random":
        for cid in pool:
            if len(chosen) >= profile.target_size:
                break
            _take(cid, "случайный отбор")
        truncated = len(pool) < profile.target_size
    else:
        truncated = False
        # квоты min/exact/percent, новые в приоритете
        for q in profile.quotas:
            if q.kind == "max":
                continue
            need = q.amount if q.kind != "percent" else round(profile.target_size * q.amount / 100)
            members = _new_first(quota_members(con, q, eligible))
            got = 0
            for cid in members:
                if got >= need or len(chosen) >= profile.target_size:
                    break
                if _take(cid, f"квота {q.label()} ({q.kind} {need})"):
                    got += 1
        if profile.mode == "stratified" and profile.stratify_dim:
            _stratified_fill(con, profile, rng, eligible, new_ids, _take, _new_first, chosen)
        else:
            # добор: новые в приоритете
            for cid in pool:
                if len(chosen) >= profile.target_size:
                    break
                _take(cid, "добрано случайно в рамках стратегии")

    # максимумы: срезаем перебор (поздние по порядку добра),
    # затем добираем из пула вне урезанных ячеек, чтобы не терять объём
    max_cells = [(set(quota_members(con, q, eligible)), q.amount)
                 for q in profile.quotas if q.kind == "max"]
    trimmed = False
    for members, amount in max_cells:
        over = [c for c in chosen if c in members]
        while len(over) > amount and over:
            victim = over.pop()  # последний добавленный из ячейки
            chosen.remove(victim)
            del reasons[victim]
            trimmed = True
    if trimmed:
        counts = [sum(1 for c in chosen if c in members) for members, _ in max_cells]
        for cid in pool:
            if len(chosen) >= profile.target_size:
                break
            if cid in reasons:
                continue
            full = any(cid in members and counts[i] >= amount
                       for i, (members, amount) in enumerate(max_cells))
            if full:
                continue
            if _take(cid, "добрано после ограничения максимума"):
                for i, (members, _amount) in enumerate(max_cells):
                    if cid in members:
                        counts[i] += 1

    new_count = len([c for c in chosen if c in new_ids])
    return {"items": chosen, "reasons": reasons,
            "short": max(0, profile.target_size - len(chosen)),
            "truncated": truncated,
            "pinned_skipped": pinned_skipped,
            "excluded_n": len(old), "new_count": new_count,
            "new_short": max(0, profile.min_new - new_count),
            "kept": kept, "kept_skipped": kept_skipped,
            "diversity_skipped": div_skipped}


def _stratified_fill(con, profile, rng, eligible, new_ids, _take, _new_first, chosen):
    """Добор с сохранением долей измерения в пуле (метод наибольших остатков)."""
    from collections import Counter
    remaining = profile.target_size - len(chosen)
    if remaining <= 0:
        return
    left = [c for c in sorted(eligible) if c not in set(chosen)]
    if not left:
        return
    rows = con.execute(
        "SELECT candidate_id, value_norm, value_raw FROM pool_dim "
        "WHERE dim=?", (profile.stratify_dim,)).fetchall()
    val_of = {r[0]: (r[1], r[2]) for r in rows}
    dist = Counter(val_of[c][0] for c in left if c in val_of)
    if not dist:
        for cid in _new_first(left):
            if len(chosen) >= profile.target_size:
                break
            _take(cid, "страта: без значения")
        return
    total = sum(dist.values())
    alloc = {}
    remainders = []
    for norm, cnt in dist.items():
        exact = remaining * cnt / total
        alloc[norm] = int(exact)
        remainders.append((exact - int(exact), norm))
    short = remaining - sum(alloc.values())
    remainders.sort(reverse=True)
    for _, norm in remainders[:short]:
        alloc[norm] += 1
    by_val: dict[str, list[int]] = {}
    for c in left:
        if c in val_of:
            by_val.setdefault(val_of[c][0], []).append(c)
    raw_of = {}
    for c in left:
        if c in val_of:
            raw_of.setdefault(val_of[c][0], val_of[c][1])
    for norm in sorted(alloc):
        members = _new_first(by_val.get(norm, []))
        label = raw_of.get(norm, norm)
        got = 0
        for cid in members:
            if got >= alloc[norm] or len(chosen) >= profile.target_size:
                break
            if _take(cid, f"страта {profile.stratify_dim}={label}"):
                got += 1
