"""Несколько вариантов одной конфигурации (разный вариант перемешивания)."""

from __future__ import annotations

import json
import sqlite3

from core.build_manifest import _profile_from_json
from core.precheck_service import precheck
from core.sampling_service import sample
from storage.database import save_build


def generate_variants(con: sqlite3.Connection, build_id: int,
                      seeds: list[int]) -> list[int]:
    """Прогоняет профиль сборки с другими семенами. Возвращает id вариантов."""
    b = con.execute("SELECT * FROM build WHERE id=?", (build_id,)).fetchone()
    if b is None:
        raise ValueError(f"сборка {build_id} не найдена")
    profile = _profile_from_json(json.loads(b["profile_json"] or "{}"))
    out = []
    for seed in seeds:
        profile.seed = seed
        res = sample(con, profile)
        out.append(save_build(con, f"{b['name']} вариант {seed}",
                              profile, res["items"], res["reasons"],
                              res.get("short", 0), note=b["note"]))
    return out


def summarize(con: sqlite3.Connection, build_id: int) -> dict:
    """Строка сравнения вариантов: объём, статус, дубли, сорванные квоты."""
    b = con.execute("SELECT * FROM build WHERE id=?", (build_id,)).fetchone()
    if b is None:
        raise ValueError(f"сборка {build_id} не найдена")
    pc = precheck(con, build_id)
    dup_fp = con.execute(
        """SELECT COUNT(*) - COUNT(DISTINCT c.fingerprint) FROM build_item bi
           JOIN candidate c ON c.id=bi.candidate_id WHERE bi.build_id=?""",
        (build_id,)).fetchone()[0]
    short_q = sum(1 for c in pc["checks"]
                  if c["code"].startswith("quota:") and c["level"] == "block")
    return {"id": build_id, "name": b["name"], "seed": b["seed"],
            "picked": b["picked"], "target": b["target_size"],
            "status": pc["status"], "dup_fp": dup_fp, "short_quotas": short_q}
