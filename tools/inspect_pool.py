"""Разведка пула без UI: листы/шапки/счётчики/заполненность/примеры.

Использование:
  py -3 tools/inspect_pool.py <файл|папка> [--sheet Лист1] [--target 500]
Исходники не меняются. Временная база — в temp, удаляется после отчёта.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import normalize as N  # noqa: E402
from core.source_reader import detect_format, iter_source, ReadStats  # noqa: E402
from storage import database as db  # noqa: E402


def collect(path: Path, args) -> dict:
    stats = ReadStats()
    errors: list = []
    counts: Counter = Counter()
    filled: Counter = Counter()
    examples: dict[str, list[str]] = {}
    headers: list[str] = []
    n = 0
    kwargs = dict(sheet=args.sheet, header_row=args.header_row,
                  encoding=args.encoding, delimiter=args.delimiter,
                  stats=stats, errors=errors)
    for h, row in iter_source(path, **kwargs):
        if not headers:
            headers = h
            for c in headers:
                examples[c] = []
        n += 1
        for c in headers:
            v = (row.get(c) or "")
            nv = N.norm_key(v)
            if nv:
                filled[c] += 1
                if len(examples[c]) < 3 and v.strip() not in examples[c]:
                    examples[c].append(v.strip()[:120])
            counts[(c, nv or "<пусто>")] += 1
        if n >= args.max_scan:
            break
    uniq = {c: len({k[1] for k in counts if k[0] == c}) for c in headers}
    return {"headers": headers, "rows": n, "filled": filled,
            "uniq": uniq, "examples": examples, "stats": stats, "errors": errors}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="файл или папка")
    ap.add_argument("--sheet", default=None)
    ap.add_argument("--header-row", type=int, default=0)
    ap.add_argument("--encoding", default="utf-8-sig")
    ap.add_argument("--delimiter", default="auto",
                    help="',' ';' таб или auto")
    ap.add_argument("--target", type=int, default=500, help="ориентир выборки для дефицита")
    ap.add_argument("--max-scan", type=int, default=100_000)
    args = ap.parse_args()

    root = Path(args.input)
    files = [root] if root.is_file() else sorted(
        p for p in root.rglob("*")
        if p.suffix.lower() in (".xlsx", ".csv", ".json", ".jsonl", ".ods"))
    if not files:
        print("файлы пула не найдены")
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        con = db.connect(Path(tmp) / "ws.sqlite")
        for f in files:
            fmt = detect_format(f)
            try:
                sid = db.upsert_source(con, f, format=fmt, sheet=args.sheet,
                                       header_row=args.header_row, encoding=args.encoding,
                                       delimiter=args.delimiter, status="scanning")
                info = collect(f, args)
                db.upsert_source(con, f, status="ok",
                                 total_rows=info["stats"].total_lines,
                                 usable_rows=info["stats"].usable_rows)
                db.save_errors(con, sid, [{"line": e.line, "column": e.column,
                                           "reason": e.reason} for e in info["errors"]])
            except Exception as e:
                print(f"\n== {f.name} [{fmt}] ОШИБКА: {e}")
                continue
            st = info["stats"]
            print(f"\n== {f.name} [{fmt}] строк: {info['rows']} "
                  f"(всего {st.total_lines}, пригодных {st.usable_rows}, "
                  f"пустых {st.empty_skipped}, битых {st.decode_errors}, "
                  f"ошибок формул {st.excel_errors})")
            print(f"   колонки ({len(info['headers'])}): {', '.join(info['headers'][:20])}")
            for c in info["headers"][:20]:
                fill = info["filled"][c]
                pct = (100 * fill / max(info["rows"], 1))
                print(f"   - {c}: заполнено {fill}/{info['rows']} ({pct:.0f}%), "
                      f"уникальных {info['uniq'][c]}, примеры: {info['examples'][c][:2]}")
            if info["errors"]:
                print(f"   первые ошибки чтения ({len(info['errors'])}):")
                for e in info["errors"][:5]:
                    print(f"     строка {e.line}: {e.reason}")
            # грубый ориентир: хватит ли пула под target
            if st.usable_rows < args.target:
                print(f"   ДЕФИЦИТ: пригодных {st.usable_rows} < цели {args.target}")
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
