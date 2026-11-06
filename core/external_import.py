"""Импорт готового набора: сопоставить с пулом, сохранить как сборку.

Сначала ищем по внешнему ID, затем по отпечатку (ТЗ §7.5: семантика
сама по себе не доказательство идентичности).
Несовпавшие строки — в отчёте, в пул ничего не добавляем.
"""

from __future__ import annotations

import sqlite3

from core.normalize import fingerprint
from core.requirements import BuildProfile
from core.roles import EXT_ID, MAIN, validate_mapping
from core.source_reader import iter_source
from storage.database import save_build


def import_external(con: sqlite3.Connection, path: str,
                    mapping: dict[str, str], name: str, **reader_opts) -> dict:
    mapping = validate_mapping(mapping)
    main_col = next((c for c, r in mapping.items() if r == MAIN), None)
    ext_col = next((c for c, r in mapping.items() if r == EXT_ID), None)

    by_ext: dict[str, int] = {}
    for cid, ext in con.execute(
            "SELECT id, ext_id FROM candidate WHERE ext_id<>''").fetchall():
        by_ext.setdefault(ext, cid)
    by_fp: dict[str, int] = {}
    for cid, fp in con.execute("SELECT id, fingerprint FROM candidate").fetchall():
        by_fp.setdefault(fp, cid)

    matched: list[int] = []
    seen: set[int] = set()
    total, no_id, no_fp = 0, 0, 0
    for _headers, row in iter_source(path, **reader_opts):
        total += 1
        cid = None
        if ext_col:
            ext = (row.get(ext_col) or "").strip()
            if ext:
                cid = by_ext.get(ext)
            else:
                no_id += 1
        if cid is None and main_col:
            fp = fingerprint(row.get(main_col, ""))
            if fp and fp != fingerprint(""):
                cid = by_fp.get(fp)
            else:
                no_fp += 1
        if cid is not None and cid not in seen:
            seen.add(cid)
            matched.append(cid)
    prof = BuildProfile(target_size=max(len(matched), 1), seed=0, mode="random")
    reasons = {c: "импортирован из готового набора" for c in matched}
    bid = save_build(con, name, prof, matched, reasons, 0)
    return {"build_id": bid, "total": total, "matched": len(matched),
            "unmatched": total - len(matched),
            "no_id": no_id, "no_main": no_fp}
