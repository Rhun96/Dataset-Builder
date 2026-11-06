"""Сравнение двух состояний БЗ по разделам: added/removed/changed/unchanged."""

from __future__ import annotations

import difflib
import html as _html
from collections import defaultdict

from core.normalize import norm_key


def diff_sections(old: list[dict], new: list[dict]) -> dict:
    old_by: dict[str, list[dict]] = defaultdict(list)
    for s in old:
        old_by[norm_key(s.get("heading", ""))].append(s)
    new_by: dict[str, list[dict]] = defaultdict(list)
    for s in new:
        new_by[norm_key(s.get("heading", ""))].append(s)

    changes: list[dict] = []
    for key in list(old_by) + [k for k in new_by if k not in old_by]:
        o_list, n_list = old_by.get(key, []), new_by.get(key, [])
        common = min(len(o_list), len(n_list))
        for i in range(common):
            o, n = o_list[i], n_list[i]
            sim = difflib.SequenceMatcher(
                None, norm_key(o.get("text", "")), norm_key(n.get("text", ""))).ratio()
            if sim >= 0.999:
                changes.append({"type": "unchanged", "heading": n.get("heading", ""),
                                "old_pos": o.get("pos"), "new_pos": n.get("pos"),
                                "similarity": 1.0,
                                "old_text": o.get("text", ""), "new_text": n.get("text", "")})
            else:
                changes.append({"type": "changed", "heading": n.get("heading", ""),
                                "old_pos": o.get("pos"), "new_pos": n.get("pos"),
                                "similarity": round(sim, 3),
                                "old_text": o.get("text", ""), "new_text": n.get("text", "")})
        for o in o_list[common:]:
            changes.append({"type": "removed", "heading": o.get("heading", ""),
                            "old_pos": o.get("pos"), "new_pos": None, "similarity": 0.0,
                            "old_text": o.get("text", ""), "new_text": ""})
        for n in n_list[common:]:
            changes.append({"type": "added", "heading": n.get("heading", ""),
                            "old_pos": None, "new_pos": n.get("pos"), "similarity": 0.0,
                            "old_text": "", "new_text": n.get("text", "")})
    order = {"changed": 0, "added": 1, "removed": 2, "unchanged": 3}
    changes.sort(key=lambda c: (order[c["type"]],
                                c["new_pos"] if c["new_pos"] is not None else 10**9))
    summary = {t: sum(1 for c in changes if c["type"] == t)
               for t in ("changed", "added", "removed", "unchanged")}
    return {"changes": changes, "summary": summary}


def _word_pair(old_line: str, new_line: str) -> tuple[str, str]:
    """Подсветка различающихся слов: красным было, зелёным стало."""
    sm = difflib.SequenceMatcher(None, old_line.split(), new_line.split())
    old_parts, new_parts = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            old_parts.append(_html.escape(" ".join(old_line.split()[i1:i2])))
            new_parts.append(_html.escape(" ".join(new_line.split()[j1:j2])))
        elif tag == "delete":
            old_parts.append('<span style="background:#F5C6C6">' +
                             _html.escape(" ".join(old_line.split()[i1:i2])) + "</span>")
        elif tag == "insert":
            new_parts.append('<span style="background:#B7E4C7">' +
                             _html.escape(" ".join(new_line.split()[j1:j2])) + "</span>")
        else:
            old_parts.append('<span style="background:#F5C6C6">' +
                             _html.escape(" ".join(old_line.split()[i1:i2])) + "</span>")
            new_parts.append('<span style="background:#B7E4C7">' +
                             _html.escape(" ".join(new_line.split()[j1:j2])) + "</span>")
    return " ".join(old_parts), " ".join(new_parts)


def render_html(change: dict) -> str:
    """Конкретные правки раздела как HTML: было/стало с подсветкой."""
    t = change.get("type")
    new_text = change.get("new_text", "")
    old_text = change.get("old_text", "")
    if t == "added":
        return ('<b>Добавлено:</b><div style="background:#E6F4EA">' +
                _html.escape(new_text).replace("\n", "<br>") + "</div>")
    if t == "removed":
        return ('<b>Удалено:</b><div style="background:#FDE8E8">' +
                _html.escape(old_text).replace("\n", "<br>") + "</div>")
    if t == "unchanged":
        return "<i>Без изменений.</i>"
    old_lines = old_text.splitlines() or [""]
    new_lines = new_text.splitlines() or [""]
    sm = difflib.SequenceMatcher(None, old_lines, new_lines)
    parts = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for line in old_lines[i1:i2]:
                parts.append("<div>" + _html.escape(line) + "</div>")
        elif tag == "delete":
            for line in old_lines[i1:i2]:
                parts.append('<div style="background:#FDE8E8">− ' +
                             _html.escape(line) + "</div>")
        elif tag == "insert":
            for line in new_lines[j1:j2]:
                parts.append('<div style="background:#E6F4EA">+ ' +
                             _html.escape(line) + "</div>")
        else:
            olds, news = old_lines[i1:i2], new_lines[j1:j2]
            if len(olds) == len(news):
                for o, n in zip(olds, news, strict=True):
                    oh, nh = _word_pair(o, n)
                    parts.append('<div style="background:#FDE8E8">− ' + oh + "</div>")
                    parts.append('<div style="background:#E6F4EA">+ ' + nh + "</div>")
            else:
                for line in olds:
                    parts.append('<div style="background:#FDE8E8">− ' +
                                 _html.escape(line) + "</div>")
                for line in news:
                    parts.append('<div style="background:#E6F4EA">+ ' +
                                 _html.escape(line) + "</div>")
    return "<b>Что изменилось:</b>" + "".join(parts)
