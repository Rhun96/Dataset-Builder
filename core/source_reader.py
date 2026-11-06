"""Чтение сырых пулов: XLSX/CSV/JSON/JSONL/ODS.

Независимое ядро: никаких импортов LocalReviewer.
Возвращаем исходные значения как есть (строками), нормализация —
отдельно в core.normalize. Исходники не трогаем.

Контракт:
- потоковое чтение через iter_*, отмена через should_cancel;
- прогресс через on_progress(done, total_or_none);
- диагностика: stats (счётчики) + errors (первые N, дальше только счётчик).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from collections.abc import Callable, Iterator

MAX_ERRORS_KEPT = 200
CHUNK_ROWS = 2000

# Коды ошибок формул Excel (EN+RU): втягиваем пустым + считаем.
EXCEL_ERRORS = frozenset({
    "#DIV/0!", "#N/A", "#NAME?", "#NULL!", "#NUM!", "#REF!", "#VALUE!",
    "#GETTING_DATA", "#SPILL!", "#CALC!", "#FIELD!", "#CONNECT!",
    "#BLOCKED!", "#UNKNOWN!",
    "#ДЕЛ/0!", "#Н/Д", "#ИМЯ?", "#ПУСТО!", "#ЧИСЛО!", "#ССЫЛКА!",
    "#ЗНАЧ!", "#ПОЛУЧЕНИЕ_ДАННЫХ",
})


class CancelledError(RuntimeError):
    pass


@dataclass
class ReadStats:
    total_lines: int = 0        # строк данных просмотрено (без заголовка)
    usable_rows: int = 0        # отдано наружу
    empty_skipped: int = 0      # полностью пустые строки
    excel_errors: int = 0       # ячеек-кодов ошибок формул
    decode_errors: int = 0      # битые строки JSON/JSONL
    errors_kept: int = 0


@dataclass
class ReadError:
    line: int
    reason: str
    column: str = ""


@dataclass
class ReadResult:
    headers: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    stats: ReadStats = field(default_factory=ReadStats)
    errors: list[ReadError] = field(default_factory=list)
    truncated: bool = False


def detect_format(path: str | Path) -> str:
    ext = Path(path).suffix.lower()
    return {
        ".xlsx": "xlsx",
        ".ods": "ods",
        ".csv": "csv",
        ".json": "json",
        ".jsonl": "jsonl",
    }.get(ext, "unknown")


def _is_excel_error(value: Any) -> bool:
    return isinstance(value, str) and value.strip().upper() in EXCEL_ERRORS


def _cell_to_str(value: Any, stats: ReadStats | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)
    s = str(value)
    if _is_excel_error(s):
        if stats is not None:
            stats.excel_errors += 1
        return ""
    return s


def _dedupe_headers(raw: list[str]) -> list[str]:
    out: list[str] = []
    seen: dict[str, int] = {}
    for i, h in enumerate(raw):
        name = (h or "").strip() or f"col_{i}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        out.append(name)
    return out


def _is_empty_row(values: list[str]) -> bool:
    return all((v or "").strip() == "" for v in values)


def _check_cancel(should_cancel: Callable[[], bool] | None):
    if should_cancel is not None and should_cancel():
        raise CancelledError("чтение отменено пользователем")


# --- XLSX ---

def list_sheets_xlsx(path: str | Path) -> list[str]:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()


def iter_xlsx(
    path: str | Path,
    sheet: str | None = None,
    header_row: int = 0,
    stats: ReadStats | None = None,
    errors: list[ReadError] | None = None,
    on_progress: Callable[[int, int | None], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> Iterator[tuple[list[str], dict[str, str]]]:
    """Yield (headers, row_dict). Headers — один раз первыми."""
    import openpyxl

    stats = stats or ReadStats()
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        name = sheet or wb.sheetnames[0]
        if name not in wb.sheetnames:
            raise ValueError(f"лист {name!r} не найден")
        ws = wb[name]
        headers: list[str] = []
        data_index = 0
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            _check_cancel(should_cancel)
            if i < header_row:
                continue
            cells = [_cell_to_str(v, stats) for v in row]
            if not headers:
                headers = _dedupe_headers(cells)
                continue
            stats.total_lines += 1
            if _is_empty_row(cells):
                stats.empty_skipped += 1
                continue
            data_index += 1
            d = {h: (cells[j] if j < len(cells) else "") for j, h in enumerate(headers)}
            stats.usable_rows += 1
            if on_progress and data_index % CHUNK_ROWS == 0:
                on_progress(data_index, None)
            yield headers, d
    finally:
        wb.close()


# --- CSV ---

def detect_delimiter(path: str | Path, encoding: str = "utf-8-sig",
                     line_no: int = 0) -> str:
    """Выбор разделителя по строке заголовка, а не первой строке файла."""
    try:
        with open(path, encoding=encoding, newline="") as f:
            lines = [ln for ln in (x.strip() for x in f.read(4096).splitlines()) if ln]
    except (OSError, UnicodeDecodeError):
        return ","
    if not lines:
        return ","
    first = lines[min(line_no, len(lines) - 1)]
    cands = [";", ",", "\t"]
    scored = [(first.count(c), c) for c in cands]
    best_count, best = max(scored)
    return best if best_count > 0 else ","


def iter_csv(
    path: str | Path,
    encoding: str = "utf-8-sig",
    delimiter: str = "auto",
    header_row: int = 0,
    stats: ReadStats | None = None,
    errors: list[ReadError] | None = None,
    on_progress: Callable[[int, int | None], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> Iterator[tuple[list[str], dict[str, str]]]:
    if delimiter == "auto":
        delimiter = detect_delimiter(path, encoding, header_row)
    if len(delimiter) != 1:
        raise ValueError("разделитель CSV — ровно один символ")
    stats = stats or ReadStats()
    with open(path, encoding=encoding, newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        headers: list[str] = []
        data_index = 0
        for i, row in enumerate(reader):
            _check_cancel(should_cancel)
            if i < header_row:
                continue
            if not headers:
                headers = _dedupe_headers([c or "" for c in row])
                continue
            stats.total_lines += 1
            if _is_empty_row(row):
                stats.empty_skipped += 1
                continue
            data_index += 1
            d = {h: (row[j] if j < len(row) else "") for j, h in enumerate(headers)}
            stats.usable_rows += 1
            if on_progress and data_index % CHUNK_ROWS == 0:
                on_progress(data_index, None)
            yield headers, d


# --- JSON / JSONL ---

def _flat(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def iter_json(
    path: str | Path,
    stats: ReadStats | None = None,
    errors: list[ReadError] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> Iterator[tuple[list[str], dict[str, str]]]:
    stats = stats or ReadStats()
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("JSON должен содержать массив объектов")
    # Заголовки — объединение ключей первых 50 объектов (устойчиво к рваной схеме).
    headers: list[str] = []
    for item in data[:50]:
        if isinstance(item, dict):
            for k in item.keys():
                if k not in headers:
                    headers.append(k)
    if not headers:
        return
    for i, item in enumerate(data):
        _check_cancel(should_cancel)
        stats.total_lines += 1
        if not isinstance(item, dict):
            stats.decode_errors += 1
            if errors is not None and len(errors) < MAX_ERRORS_KEPT:
                errors.append(ReadError(line=i + 1, reason="not an object, skipped"))
            continue
        if not item:
            stats.empty_skipped += 1
            continue
        d = {h: _flat(item.get(h, "")) for h in headers}
        if _is_empty_row([d[h] for h in headers]):
            stats.empty_skipped += 1
            continue
        stats.usable_rows += 1
        yield headers, d


def iter_jsonl(
    path: str | Path,
    stats: ReadStats | None = None,
    errors: list[ReadError] | None = None,
    on_progress: Callable[[int, int | None], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> Iterator[tuple[list[str], dict[str, str]]]:
    stats = stats or ReadStats()
    headers: list[str] = []
    data_index = 0
    with open(path, encoding="utf-8-sig") as f:
        for line_no, line in enumerate(f, 1):
            _check_cancel(should_cancel)
            s = line.strip()
            if not s:
                continue
            try:
                item = json.loads(s)
            except json.JSONDecodeError as e:
                stats.decode_errors += 1
                if errors is not None and len(errors) < MAX_ERRORS_KEPT:
                    errors.append(ReadError(line=line_no, reason=f"bad json: {e}"))
                continue
            if not isinstance(item, dict):
                stats.decode_errors += 1
                if errors is not None and len(errors) < MAX_ERRORS_KEPT:
                    errors.append(ReadError(line=line_no, reason="not an object, skipped"))
                continue
            stats.total_lines += 1
            if not headers:
                headers = list(item.keys())
                if not headers:
                    stats.empty_skipped += 1
                    continue
            if not item:
                stats.empty_skipped += 1
                continue
            d = {h: _flat(item.get(h, "")) for h in headers}
            if _is_empty_row([d[h] for h in headers]):
                stats.empty_skipped += 1
                continue
            data_index += 1
            stats.usable_rows += 1
            if on_progress and data_index % CHUNK_ROWS == 0:
                on_progress(data_index, None)
            yield headers, d


# --- ODS ---

def list_sheets_ods(path: str | Path) -> list[str]:
    try:
        from odf.opendocument import load as _load
        from odf.table import Table as _Table
    except ImportError as e:
        raise ValueError("для .ods нужен odfpy: pip install odfpy") from e
    doc = _load(str(path))
    return [t.getAttribute("name") or f"Лист{i + 1}"
            for i, t in enumerate(doc.getElementsByType(_Table))]


def iter_ods(
    path: str | Path,
    sheet: str | None = None,
    header_row: int = 0,
    stats: ReadStats | None = None,
    errors: list[ReadError] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> Iterator[tuple[list[str], dict[str, str]]]:
    try:
        from odf.opendocument import load as _load
        from odf.table import Table as _Table, TableRow as _Row, TableCell as _Cell
        from odf.text import P as _P
    except ImportError as e:
        raise ValueError("для .ods нужен odfpy: pip install odfpy") from e
    stats = stats or ReadStats()
    doc = _load(str(path))
    tables = doc.getElementsByType(_Table)
    if not tables:
        raise ValueError("в ODS нет листов")
    table = tables[0]
    if sheet:
        for t in tables:
            if t.getAttribute("name") == sheet:
                table = t
                break
        else:
            raise ValueError(f"лист {sheet!r} не найден")

    def _row_cells(r) -> list[str]:
        cells: list[str] = []
        for c in r.getElementsByType(_Cell):
            try:
                rep = int(c.getAttribute("numbercolumnsrepeated") or 1)
            except (TypeError, ValueError):
                rep = 1
            texts = []
            for p in c.getElementsByType(_P):
                parts = [n.data for n in p.childNodes if n.nodeType == n.TEXT_NODE]
                texts.append("".join(parts).strip())
            v = "\n".join(t for t in texts if t)
            if _is_excel_error(v):
                stats.excel_errors += 1
                v = ""
            cells.extend([v] * min(rep, 256))
        return cells

    headers: list[str] = []
    for i, r in enumerate(table.getElementsByType(_Row)):
        _check_cancel(should_cancel)
        if i < header_row:
            continue
        cells = _row_cells(r)
        if not headers:
            headers = _dedupe_headers(cells)
            continue
        stats.total_lines += 1
        if _is_empty_row(cells):
            stats.empty_skipped += 1
            continue
        d = {h: (cells[j] if j < len(cells) else "") for j, h in enumerate(headers)}
        stats.usable_rows += 1
        yield headers, d


# --- фасад ---

def iter_source(
    path: str | Path,
    sheet: str | None = None,
    header_row: int = 0,
    encoding: str = "utf-8-sig",
    delimiter: str = "auto",
    stats: ReadStats | None = None,
    errors: list[ReadError] | None = None,
    on_progress: Callable[[int, int | None], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> Iterator[tuple[list[str], dict[str, str]]]:
    _check_cancel(should_cancel)
    fmt = detect_format(path)
    if fmt == "xlsx":
        yield from iter_xlsx(path, sheet, header_row, stats, errors,
                             on_progress, should_cancel)
    elif fmt == "csv":
        yield from iter_csv(path, encoding, delimiter, header_row, stats,
                            errors, on_progress, should_cancel)
    elif fmt == "json":
        yield from iter_json(path, stats, errors, should_cancel)
    elif fmt == "jsonl":
        yield from iter_jsonl(path, stats, errors, on_progress, should_cancel)
    elif fmt == "ods":
        yield from iter_ods(path, sheet, header_row, stats, errors, should_cancel)
    else:
        raise ValueError(
            f"неизвестный формат: {Path(path).suffix!r} (ждём xlsx/csv/json/jsonl/ods)")


def read_preview(path: str | Path, max_rows: int = 100, **kwargs) -> ReadResult:
    """Первые max_rows для маппинга/профиля. Ошибки чтения — исключением."""
    stats = ReadStats()
    errors: list[ReadError] = []
    res = ReadResult(stats=stats, errors=errors)
    try:
        for headers, row in iter_source(path, stats=stats, errors=errors, **kwargs):
            if not res.headers:
                res.headers = headers
            res.rows.append(row)
            if len(res.rows) >= max_rows:
                res.truncated = True
                break
    except CancelledError:
        res.truncated = True
    res.stats.errors_kept = len(errors)
    return res
