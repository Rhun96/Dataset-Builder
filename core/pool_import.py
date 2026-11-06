"""Загрузка пула в SQLite: сырые оригиналы + нормированные признаки.

Оригиналы храним как есть в raw_json/main_raw.
Нормы (main_norm/dim) — только для поиска/отбора.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

from core.normalize import clean_display, fingerprint, norm_key
from core.roles import EXT_ID, MAIN, is_dimension, validate_mapping
from core.source_reader import ReadStats, detect_format, iter_source
from storage import database as db


class CancelledError(RuntimeError):
    pass


def import_source(
    con: sqlite3.Connection,
    path: str | Path,
    mapping: dict[str, str],
    sheet: str | None = None,
    header_row: int = 0,
    encoding: str = "utf-8-sig",
    delimiter: str = "auto",
    on_progress: Callable[[int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> dict:
    mapping = validate_mapping(mapping)
    fmt = detect_format(path)
    sid = db.upsert_source(con, path, format=fmt, sheet=sheet,
                           header_row=header_row, encoding=encoding,
                           delimiter=delimiter, status="loading")
    db.save_mapping(con, sid, mapping)
    db.clear_pool(con, sid)

    # колонка -> роль (обратный индекс)
    inv: dict[str, str] = dict(mapping)
    stats = ReadStats()
    errors: list = []
    now = time.time()
    batch: list = []
    row_no = 0
    usable = 0

    def _flush():
        nonlocal usable
        if not batch:
            return
        con.executemany(
            """INSERT INTO candidate
               (source_id, row_no, ext_id, fingerprint, main_raw, main_norm, raw_json, added_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            [(sid, b["row_no"], b["ext_id"], b["fp"], b["main_raw"],
              b["main_norm"], b["raw_json"], now) for b in batch],
        )
        # id только что вставленных — забираем по rowid порядку
        first_id = con.execute("SELECT last_insert_rowid()").fetchone()[0] - len(batch) + 1
        dims = []
        for k, b in enumerate(batch):
            cid = first_id + k
            for dim, (raw, norm, miss) in b["dims"].items():
                dims.append((cid, dim, raw, norm, miss))
        con.executemany(
            "INSERT INTO candidate_dim(candidate_id, dim, value_raw, value_norm, is_missing)"
            " VALUES (?,?,?,?,?)", dims,
        )
        con.commit()
        usable += len(batch)
        batch.clear()
        if on_progress:
            on_progress(usable)

    for _headers, row in iter_source(path, sheet=sheet, header_row=header_row,
                                    encoding=encoding, delimiter=delimiter,
                                    stats=stats, errors=errors,
                                    should_cancel=should_cancel):
        if should_cancel is not None and should_cancel():
            con.commit()
            db.upsert_source(con, path, status="cancelled")
            raise CancelledError("загрузка отменена")
        row_no += 1
        # основной текст обязателен
        main_col = next((c for c, r in inv.items() if r == MAIN), None)
        main_raw = clean_display(row.get(main_col, "")) if main_col else ""
        if not main_raw:
            stats.empty_skipped += 1
            continue
        main_norm = norm_key(main_raw)
        ext_col = next((c for c, r in inv.items() if r == EXT_ID), None)
        ext_id = clean_display(row.get(ext_col, "")) if ext_col else ""
        dims: dict[str, tuple[str, str, int]] = {}
        for col, role in inv.items():
            if not is_dimension(role):
                continue
            raw = clean_display(row.get(col, ""))
            norm = norm_key(raw)
            dims[role] = (raw, norm, 1 if not raw else 0)
        batch.append({"row_no": row_no, "ext_id": ext_id,
                      "fp": fingerprint(main_raw), "main_raw": main_raw,
                      "main_norm": main_norm,
                      "raw_json": json.dumps(row, ensure_ascii=False), "dims": dims})
        if len(batch) >= 2000:
            _flush()
    _flush()

    db.upsert_source(con, path, status="ok",
                     total_rows=stats.total_lines, usable_rows=usable)
    db.save_errors(con, sid, [{"line": e.line, "column": e.column, "reason": e.reason}
                              for e in errors])
    return {"source_id": sid, "rows_seen": row_no, "usable": usable,
            "skipped_empty": stats.empty_skipped, "decode_errors": stats.decode_errors,
            "excel_errors": stats.excel_errors}
