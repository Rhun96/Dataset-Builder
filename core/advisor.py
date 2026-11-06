"""Советчик объёма: анализирует пул и предлагает состав с обоснованием.

Не истина, а рекомендация: редкие забираем целиком, остальные —
пропорционально долям, похожие отсекаем. Пользователь утверждает.
"""

from __future__ import annotations

import sqlite3

from core.requirements import BuildProfile, Quota


def _counts(con: sqlite3.Connection, dim: str,
            eligible: set[int] | None) -> list[tuple[str, str, int]]:
    rows = con.execute(
        "SELECT candidate_id, value_norm, value_raw FROM pool_dim "
        "WHERE dim=? AND is_missing=0", (dim,)).fetchall()
    agg: dict[str, list] = {}
    for cid, norm, raw in rows:
        if eligible is not None and cid not in eligible:
            continue
        cell = agg.setdefault(norm, [raw, 0])
        cell[1] += 1
    out = [(n, v[0], v[1]) for n, v in agg.items()]
    out.sort(key=lambda x: -x[2])
    return out


def propose(con: sqlite3.Connection, profile: BuildProfile, dim: str,
            base_target: int = 500, rare_min: int = 30) -> dict:
    """Возвращает target/quotas/diversity + человекочитаемое обоснование."""
    from core.filter_service import apply_filters
    eligible = apply_filters(con, profile.filters)
    total = (con.execute("SELECT COUNT(*) FROM pool_candidate").fetchone()[0]
             if eligible is None else len(eligible))
    if total == 0:
        raise ValueError("подходящих записей нет — ослабь фильтры или включи источники")
    vals = _counts(con, dim, eligible)
    if not vals:
        raise ValueError(f"в измерении {dim!r} нет значений под фильтрами")
    rare = [(n, r, c) for n, r, c in vals if c < rare_min]
    common = [(n, r, c) for n, r, c in vals if c >= rare_min]
    rare_sum = sum(c for _, _, c in rare)
    target = min(total, max(base_target, 1))
    quotas: list[Quota] = []
    explain: list[str] = []
    explain.append(f"Под фильтры подходит записей: {total}.")
    if not common:
        quotas = [Quota(dim=dim, value=r, kind="min", amount=c) for _, r, c in rare]
        target = total
        explain.append("Все группы малочисленные — предлагаю взять всё целиком.")
    else:
        for _, r, c in rare:
            quotas.append(Quota(dim=dim, value=r, kind="min", amount=c))
        if rare:
            names = ", ".join(f"{r} ({c})" for _, r, c in rare[:5])
            tail = "" if len(rare) <= 5 else f" и ещё {len(rare) - 5}"
            explain.append(f"Редкие (меньше {rare_min}): {names}{tail} — беру целиком.")
        rest = max(target - rare_sum, 0)
        denom = sum(c for _, _, c in common) or 1
        for _, r, c in common:
            share = (100.0 * rest * c / denom / target) if target else 0
            quotas.append(Quota(dim=dim, value=r, kind="percent",
                                amount=round(share, 1)))
        big = ", ".join(f"{r} ({c})" for _, r, c in common[:3])
        explain.append(f"Остальные — пропорционально долям (например: {big}).")
        explain.append(f"Итого рекомендую {target} из {total}.")
    explain.append("Включил отсечение почти одинаковых (сходство выше 0.85).")
    dupes = con.execute(
        "SELECT COUNT(*)-COUNT(DISTINCT fingerprint) FROM pool_candidate").fetchone()[0]
    if dupes:
        explain.append(f"Точных дублей в пуле: {dupes} — в выборку пойдёт по одному.")
    explain.append("Это рекомендация, а не истина: поправь размер и квоты под задачу.")
    return {"target": target, "quotas": quotas, "div_threshold": 0.85,
            "explanation": explain}
