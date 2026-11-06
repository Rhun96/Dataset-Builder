"""Манифест сборки: воспроизводимость без доступа к исходникам заново.

Содержит seed-вариант, версию алгоритма, конфиг, контрольные суммы
источников, покрытие и происхождение каждой записи с причиной.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from core.coverage_service import coverage
from core.requirements import BuildProfile, profile_from_dict
from core.sampling_service import ALGO_VERSION


def _profile_from_json(data: dict) -> BuildProfile:
    return profile_from_dict(data)


def build_manifest(con: sqlite3.Connection, build_id: int) -> dict:
    b = con.execute("SELECT * FROM build WHERE id=?", (build_id,)).fetchone()
    if b is None:
        raise ValueError(f"сборка {build_id} не найдена")
    profile_data = json.loads(b["profile_json"] or "{}")
    profile = _profile_from_json(profile_data)
    cov = coverage(con, profile)

    sources = [dict(r) for r in con.execute("SELECT * FROM source ORDER BY id")]
    items = con.execute(
        """SELECT bi.candidate_id, bi.reason, bi.pos, c.ext_id, c.fingerprint,
                  c.main_raw, c.row_no, c.source_id, c.raw_json
           FROM build_item bi JOIN candidate c ON c.id=bi.candidate_id
           WHERE bi.build_id=? ORDER BY bi.pos""", (build_id,)).fetchall()
    src_path = {s["id"]: s["path"] for s in sources}
    manifest_items = [{
        "export_id": r["ext_id"] or f"auto-{r['candidate_id']}",
        "internal_id": r["candidate_id"],
        "source_file": src_path.get(r["source_id"], ""),
        "source_row": r["row_no"],
        "fingerprint": r["fingerprint"],
        "reason": r["reason"] or "",
    } for r in items]

    return {
        "build_id": b["id"],
        "build_name": b["name"],
        "note": b["note"] if "note" in b.keys() else "",
        "created_at": b["created_at"],
        "target_size": b["target_size"],
        "picked": b["picked"],
        "short": b["short"],
        "variant": profile.seed,
        "mode": profile.mode,
        "algo": f"sampling-v{ALGO_VERSION}",
        "python": sys.version.split()[0],
        "profile": profile_data,
        "sources": [{"path": Path(s["path"]).name, "sha256": s["sha256"], "size": s["size"],
                     "format": s["format"], "sheet": s["sheet"]} for s in sources],
        "pool_total": cov["eligible"],
        "coverage": cov["cells"],
        "items": manifest_items,
        "limitations": [f"{c['dim']}={c['value']}: нужно {c['need']}, есть {c['avail']}"
                        for c in cov["impossible"]],
    }
