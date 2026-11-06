"""Связанные кейсы: какие записи пула — кандидаты на перепроверку.

Методы (по убыванию точности): source (ссылка на документ),
phrase (дословный кусок), words (общие значимые слова).
Вывод — повод посмотреть, а не приговор (ТЗ §15).
"""

from __future__ import annotations

import re
import sqlite3

from core.normalize import norm_key

TOKEN_RE = re.compile(r"[a-zа-яё0-9]+")
KB_DIM = "kb_ref"


def tokens(text: str) -> set[str]:
    return {t for t in TOKEN_RE.findall(norm_key(text)) if len(t) >= 4}


def related_for_change(con: sqlite3.Connection, change: dict,
                       doc_name: str = "", limit: int = 50) -> list[dict]:
    heading = change.get("heading", "")
    text = change.get("new_text") or change.get("old_text") or ""
    frag = norm_key(f"{heading} {text}")
    frag_tokens = tokens(frag)
    doc_norm = norm_key(doc_name)
    head_norm = norm_key(heading)
    snippet = norm_key(text)[:80]

    kb_by: dict[int, str] = {r["candidate_id"]: r["value_norm"] for r in con.execute(
        "SELECT candidate_id, value_norm FROM pool_dim WHERE dim=?", (KB_DIM,))}

    best: dict[int, dict] = {}
    cur = con.execute("SELECT id, main_raw, main_norm FROM pool_candidate")
    batch = cur.fetchmany(5000)
    while batch:
        for r in batch:
            cid = r["id"]
            main_norm = r["main_norm"] or ""
            if not main_norm:
                continue
            hit = None
            if doc_norm and len(doc_norm) >= 4:
                kb = kb_by.get(cid, "")
                if kb and (doc_norm in kb or (len(kb) >= 4 and kb in doc_norm)):
                    hit = {"method": "source", "score": 100,
                           "detail": f"в поле «Источник»: {kb[:60]}"}
            if hit is None and len(head_norm) >= 12 and head_norm in main_norm:
                hit = {"method": "phrase", "score": 60,
                       "detail": f"дословно из заголовка: {heading[:80]}"}
            if hit is None and len(snippet) >= 30 and snippet in main_norm:
                hit = {"method": "phrase", "score": 50,
                       "detail": "дословный кусок текста раздела"}
            if hit is None and frag_tokens:
                common = frag_tokens & set(TOKEN_RE.findall(main_norm))
                if len(common) >= 2:
                    words = sorted(common)[:5]
                    hit = {"method": "words", "score": len(common),
                           "detail": f"общие слова: {', '.join(words)}"}
            if hit is not None:
                prev = best.get(cid)
                if prev is None or hit["score"] > prev["score"]:
                    best[cid] = {"candidate_id": cid, "main_raw": r["main_raw"],
                                 **hit}
        batch = cur.fetchmany(5000)

    ranked = sorted(best.values(), key=lambda x: -x["score"])
    return ranked[:limit]


def transfer_to_build(con: sqlite3.Connection, name: str,
                      picks: list[dict], note: str = "") -> int:
    """Выбранные кандидаты -> сборка на перепроверку (reasons с причиной)."""
    from core.requirements import BuildProfile
    from storage.database import save_build
    ids = [p["candidate_id"] for p in picks]
    reasons = {p["candidate_id"]: f"кандидат на перепроверку: {p.get('why', '')}"
               for p in picks}
    prof = BuildProfile(target_size=max(len(ids), 1), seed=0, mode="random")
    return save_build(con, name, prof, ids, reasons, 0, note=note)
