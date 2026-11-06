"""Предэкспортные проверки состава. Уровни: ok / warn / block.

Блок — только обязательное: пустой основной текст, сорванные min/exact.
Остальное — предупреждения, экспорт разрешён сознательно.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter

from core.build_manifest import _profile_from_json


def precheck(con: sqlite3.Connection, build_id: int) -> dict:
    b = con.execute("SELECT * FROM build WHERE id=?", (build_id,)).fetchone()
    if b is None:
        raise ValueError(f"сборка {build_id} не найдена")
    profile = _profile_from_json(json.loads(b["profile_json"] or "{}"))
    rows = con.execute(
        """SELECT bi.candidate_id, c.ext_id, c.fingerprint, c.main_raw
           FROM build_item bi JOIN candidate c ON c.id=bi.candidate_id
           WHERE bi.build_id=?""", (build_id,)).fetchall()
    checks: list[dict] = []

    def _add(code: str, level: str, msg: str):
        checks.append({"code": code, "level": level, "message": msg})

    # целевой объём
    if len(rows) >= profile.target_size:
        _add("target", "ok", f"объём {len(rows)}/{profile.target_size}")
    else:
        _add("target", "warn", f"собрано {len(rows)} из {profile.target_size}")

    # пустой основной текст
    empty = sum(1 for r in rows if not (r["main_raw"] or "").strip())
    _add("empty_main", "block" if empty else "ok",
         f"без основного текста: {empty}" if empty else "пустых текстов нет")

    # дубли ID и отпечатков внутри сборки
    ids = [r["ext_id"] or f"auto-{r['candidate_id']}" for r in rows]
    dup_ids = sum(1 for _, c in Counter(ids).items() if c > 1)
    _add("dup_ids", "warn" if dup_ids else "ok",
         f"повторных ID: {dup_ids}" if dup_ids else "ID уникальны")
    fps = [r["fingerprint"] for r in rows]
    dup_fp = sum(1 for _, c in Counter(fps).items() if c > 1)
    _add("dup_fp", "warn" if dup_fp else "ok",
         f"точных дублей текста: {dup_fp}" if dup_fp else "точных дублей нет")

    # квоты min/exact по факту в сборке
    from core.normalize import norm_key as _nk
    for q in profile.quotas:
        if q.kind == "percent":
            need = round(profile.target_size * q.amount / 100)
        else:
            need = q.amount
        if q.kind == "max":
            continue
        have = con.execute(
            """SELECT COUNT(*) FROM build_item bi
               JOIN candidate_dim d ON d.candidate_id=bi.candidate_id
               WHERE bi.build_id=? AND d.dim=? AND d.value_norm=?""",
            (build_id, q.dim, _nk(q.value))).fetchone()[0]
        if have >= need:
            _add(f"quota:{q.dim}={q.value}", "ok", f"{q.dim}={q.value}: {have}/{need}")
        else:
            _add(f"quota:{q.dim}={q.value}", "block",
                 f"{q.dim}={q.value}: есть {have}, нужно {need}")

    blocked = any(c["level"] == "block" for c in checks)
    warned = any(c["level"] == "warn" for c in checks)
    status = "blocked" if blocked else ("warnings" if warned else "ready")
    return {"build_id": build_id, "status": status, "checks": checks}
