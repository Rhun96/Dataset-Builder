"""Советчик состава: анализирует пул и предлагает квоты с обоснованием.

Не истина, а рекомендация: редкие значения и редкие сочетания забираем
целиком (по всем измерениям, не только по выбранному), остальное по главному
измерению — пропорционально долям, похожие отсекаем. Пользователь утверждает.
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


def _pair_counts(con: sqlite3.Connection, dim1: str, dim2: str,
                 eligible: set[int] | None,
                 limit: int = 200) -> list[tuple[str, str, str, str, int]]:
    """Совместные ячейки двух измерений (norm1, raw1, norm2, raw2, count)."""
    rows = con.execute(
        "SELECT d1.candidate_id, d1.value_norm, d1.value_raw, "
        "d2.value_norm, d2.value_raw FROM pool_dim d1 "
        "JOIN pool_dim d2 ON d1.candidate_id=d2.candidate_id "
        "WHERE d1.dim=? AND d2.dim=? AND d1.is_missing=0 AND d2.is_missing=0",
        (dim1, dim2)).fetchall()
    agg: dict[tuple[str, str], list] = {}
    for cid, n1, r1, n2, r2 in rows:
        if eligible is not None and cid not in eligible:
            continue
        cell = agg.setdefault((n1, n2), [r1, r2, 0])
        cell[2] += 1
    out = [(k[0], v[0], k[1], v[1], v[2]) for k, v in agg.items()]
    out.sort(key=lambda x: (x[4], x[0], x[2]))
    return out[:limit]


def propose(con: sqlite3.Connection, profile: BuildProfile, dim: str,
            rare_min: int = 30) -> dict:
    """Возвращает target/quotas/diversity + человекочитаемое обоснование.

    dim — главное измерение (пропорции считаются по нему), редкости ищем
    по всем измерениям и их парам. Цель берём из профиля, не из константы.
    """
    from core.filter_service import apply_filters
    from core.pool_profile import list_dims
    from core.roles import dim_label
    eligible = apply_filters(con, profile.filters)
    total = (con.execute("SELECT COUNT(*) FROM pool_candidate").fetchone()[0]
             if eligible is None else len(eligible))
    if total == 0:
        raise ValueError("подходящих записей нет — ослабь фильтры или включи источники")
    vals = _counts(con, dim, eligible)
    if not vals:
        raise ValueError(f"в измерении {dim!r} нет значений под фильтрами")
    others = [d for d, _label in list_dims(con) if d != dim][:4]
    rare = [(n, r, c) for n, r, c in vals if c < rare_min]
    common = [(n, r, c) for n, r, c in vals if c >= rare_min]
    rare_sum = sum(c for _, _, c in rare)
    target = min(total, max(profile.target_size, 1))
    quotas: list[Quota] = []
    explain: list[str] = []
    explain.append(f"Под фильтры подходит записей: {total}.")

    shown_rare, hidden_rare = rare[:20], rare[20:]
    for _, r, c in shown_rare:
        quotas.append(Quota(dim=dim, value=r, kind="min", amount=c))
    if rare:
        names = ", ".join(f"{r} ({c})" for _, r, c in shown_rare[:5])
        tail = "" if len(shown_rare) <= 5 else f" и ещё {len(shown_rare) - 5}"
        explain.append(f"Редкие в «{dim_label(dim)}» (меньше {rare_min}): "
                       f"{names}{tail} — беру целиком.")
        if hidden_rare:
            explain.append(f"Там же ещё {len(hidden_rare)} редких — добавь руками, "
                           "если нужны.")

    for d in others:
        orare = [(n, r, c) for n, r, c in _counts(con, d, eligible) if c < rare_min][:5]
        for _, r, c in orare:
            quotas.append(Quota(dim=d, value=r, kind="min", amount=c))
        if orare:
            names = ", ".join(f"{r} ({c})" for _, r, c in orare)
            explain.append(f"Редкие в «{dim_label(d)}»: {names} — беру целиком.")

    cand: list[tuple] = []
    for d in others:
        for _n1, r1, _n2, r2, c in _pair_counts(con, dim, d, eligible):
            if 0 < c < rare_min:
                cand.append((c, r1, d, r2))
    cand.sort(key=lambda x: (x[0], x[1], x[3]))
    for c, r1, d, r2 in cand[:8]:
        quotas.append(Quota(dim=dim, value=r1, kind="min", amount=c,
                            dim2=d, value2=r2))
    if cand:
        pairs = ", ".join(f"{dim_label(dim)}={r1} + {dim_label(d)}={r2} ({c})"
                          for c, r1, d, r2 in cand[:8])
        explain.append("Редкие сочетания: " + pairs + " — беру целиком.")

    if not common:
        target = total
        explain.append("Все группы главного измерения малочисленные — "
                       "предлагаю взять всё целиком.")
    else:
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
