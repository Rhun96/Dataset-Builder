"""Файловый пакет сборки: dataset + manifest + покрытие + отчёт.

Независимый формат: исходные колонки + стабильный «ID выборки» +
происхождение. Служебное (причины, отпечатки) — только в manifest.
Защита от formula injection, CSV — utf-8-sig с ';' для русского Excel.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

from core.build_manifest import build_manifest

ID_COL = "ID выборки"
SRC_FILE_COL = "Файл источника"
SRC_ROW_COL = "Строка источника"


def _safe(v: str) -> str:
    if v and v[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def _style_xlsx(ws, cols: list[str], data: list[dict]):
    """Читаемый лист: закреплённая шапка, фильтр, ширины по содержимому."""
    from openpyxl.styles import Alignment, Font, PatternFill
    head_font = Font(bold=True)
    head_fill = PatternFill(start_color="E8EDF3", fill_type="solid")
    for cell in ws[1]:
        cell.font = head_font
        cell.fill = head_fill
        cell.alignment = Alignment(vertical="center")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for i, col in enumerate(cols, start=1):
        longest = len(col)
        for d in data[:200]:
            longest = max(longest, len(str(d.get(col, ""))[:300]))
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(
            55, max(12, longest + 2))


def _dataset_rows(con: sqlite3.Connection, build_id: int) -> tuple[list[str], list[dict]]:
    rows = con.execute(
        """SELECT bi.candidate_id, bi.reason, c.ext_id, c.raw_json, c.row_no, s.path
           FROM build_item bi JOIN candidate c ON c.id=bi.candidate_id
           JOIN source s ON s.id=c.source_id
           WHERE bi.build_id=? ORDER BY bi.pos""", (build_id,)).fetchall()
    headers: list[str] = []
    out: list[dict] = []
    for r in rows:
        raw = json.loads(r["raw_json"] or "{}")
        for k in raw:
            if k not in headers:
                headers.append(k)
        out.append({"raw": raw, "ext_id": r["ext_id"], "cid": r["candidate_id"],
                    "src": Path(r["path"]).name, "row_no": r["row_no"]})
    cols = [ID_COL, *headers, SRC_FILE_COL, SRC_ROW_COL]
    data = []
    for o in out:
        d = {ID_COL: o["ext_id"] or f"auto-{o['cid']}"}
        d.update({h: o["raw"].get(h, "") for h in headers})
        d[SRC_FILE_COL] = o["src"]
        d[SRC_ROW_COL] = o["row_no"]
        data.append(d)
    return cols, data


def export_package(con: sqlite3.Connection, build_id: int, out_dir: str | Path,
                   formats: tuple[str, ...] = ("xlsx", "jsonl")) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(con, build_id)
    cols, data = _dataset_rows(con, build_id)

    made: dict[str, str] = {}
    if "xlsx" in formats:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "dataset"
        ws.append(cols)
        for d in data:
            ws.append([_safe(str(d.get(c, ""))) for c in cols])
        _style_xlsx(ws, cols, data)
        p = out / "dataset.xlsx"
        wb.save(p)
        made["xlsx"] = str(p)
    if "csv" in formats:
        p = out / "dataset.csv"
        with open(p, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, delimiter=";")
            w.writeheader()
            for d in data:
                w.writerow({c: _safe(str(d.get(c, ""))) for c in cols})
        made["csv"] = str(p)
    if "jsonl" in formats:
        p = out / "dataset.jsonl"
        with open(p, "w", encoding="utf-8") as f:
            for d in data:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        made["jsonl"] = str(p)

    mp = out / "manifest.json"
    mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    made["manifest"] = str(mp)

    cp = out / "coverage.csv"
    with open(cp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Измерение", "Значение", "Нужно", "Доступно", "Дефицит"])
        for c in manifest["coverage"]:
            w.writerow([_safe(c["dim"]), _safe(c["value"]),
                        c["need"], c["avail"], c["deficit"]])
    made["coverage"] = str(cp)

    rp = out / "selection_report.txt"
    lines = [f"Отчёт о сборке {manifest['build_name']} (id {manifest['build_id']})"]
    if manifest.get("note"):
        lines.append(f"Описание: {manifest['note']}")
    lines += [f"Цель: {manifest['target_size']}, собрано: {manifest['picked']}, "
              f"недобор: {manifest['short']}",
              f"Вариант: {manifest['variant']}, режим: {manifest['mode']}, "
              f"алгоритм: {manifest['algo']}",
              f"Пул пригодных: {manifest['pool_total']}",
              "", "Источники:"]
    lines += [f"  - {Path(s['path']).name} "
              f"(sha256 {s['sha256'][:12]}…)" for s in manifest["sources"]]
    lines += ["", "Покрытие:"]
    lines += [f"  - {c['dim']}={c['value']}: нужно {c['need']}, есть {c['avail']}"
              for c in manifest["coverage"]]
    if manifest["limitations"]:
        lines += ["", "Ограничения:"] + [f"  ! {x}" for x in manifest["limitations"]]
    rp.write_text("\n".join(lines), encoding="utf-8")
    made["report"] = str(rp)
    return made
