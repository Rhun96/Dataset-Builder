"""Чтение источников: форматы, пустые строки, битые строки, отмена."""

import pytest

from core.source_reader import (
    CancelledError,
    ReadStats,
    detect_format,
    iter_source,
    read_preview,
)


def _write(path, text, encoding="utf-8-sig"):
    path.write_text(text, encoding=encoding)
    return str(path)


def test_detect_format():
    assert detect_format("a.xlsx") == "xlsx"
    assert detect_format("a.CSV") == "csv"
    assert detect_format("a.jsonl") == "jsonl"
    assert detect_format("a.txt") == "unknown"


def test_csv_empty_and_dedupe(tmp_path):
    p = _write(tmp_path / "p.csv", "a,a,b\n1,2,\n\n , , \n3,4,5\n")
    stats, errors = ReadStats(), []
    rows = list(iter_source(p, stats=stats, errors=errors))
    assert rows[0][0] == ["a", "a_2", "b"]
    assert len(rows) == 2
    assert stats.empty_skipped == 2


def test_delimiter_from_header_row(tmp_path):
    p = _write(tmp_path / "p.csv", "мусор\nЗ;Г\n1;2\n")
    rows = list(iter_source(str(p), header_row=1))
    assert rows[0][0] == ["З", "Г"]


def test_jsonl_broken_lines_kept(tmp_path):
    p = tmp_path / "p.jsonl"
    p.write_text('{"a": "1"}\nnot json\n{"a": ""}\n', encoding="utf-8")
    stats, errors = ReadStats(), []
    rows = list(iter_source(str(p), stats=stats, errors=errors))
    assert stats.decode_errors == 1
    assert len(errors) == 1 and errors[0].line == 2
    # третья строка пустая -> пропущена
    assert len(rows) == 1


def test_json_must_be_list(tmp_path):
    p = tmp_path / "p.json"
    p.write_text('{"a": 1}', encoding="utf-8")
    with pytest.raises(ValueError):
        list(iter_source(str(p)))


def test_xlsx_excel_errors(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    p = str(tmp_path / "p.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["h1", "h2"])
    ws.append(["#ДЕЛ/0!", "ok"])
    ws.append(["x", "y"])
    wb.save(p)
    stats = ReadStats()
    rows = list(iter_source(p, stats=stats, errors=[]))
    assert stats.excel_errors == 1
    assert rows[0][1]["h1"] == ""


def test_cancel():
    def _cancel():
        return True
    with pytest.raises(CancelledError):
        list(iter_source("dummy.csv", should_cancel=_cancel))


def test_preview_truncation(tmp_path):
    p = _write(tmp_path / "p.csv", "a\n" + "1\n" * 10)
    res = read_preview(str(p), max_rows=3)
    assert len(res.rows) == 3 and res.truncated
