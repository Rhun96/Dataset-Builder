"""БЗ-дифф и связанные кейсы: только кандидаты на перепроверку."""
from core.knowledge_diff_service import diff_sections, render_html
from core.knowledge_reader import read_kb
from core.pool_import import import_source
from core.related_cases_service import related_for_change, transfer_to_build
from core.roles import MAIN
from storage.database import connect, save_kb_snapshot


def _pool(tmp_path):
    p = tmp_path / "p.csv"
    p.write_text("З\nвозврат денег за билет\nзамена экрана телефона\n", encoding="utf-8-sig")
    con = connect(tmp_path / "ws.sqlite")
    import_source(con, p, {"З": MAIN})
    return con


def test_reader_md_txt(tmp_path):
    md = tmp_path / "d.md"
    md.write_text("# Возвраты\nТекст про возврат денег.\n# Доставка\nСроки.\n", encoding="utf-8")
    secs = read_kb(md)["sections"]
    assert [s["heading"] for s in secs] == ["Возвраты", "Доставка"]
    txt = tmp_path / "d.txt"
    txt.write_text("Тарифы:\nцены и сроки\n\nПрочее\n", encoding="utf-8")
    assert read_kb(txt)["sections"][0]["heading"] == "Тарифы:"
    try:
        read_kb(tmp_path / "d.pdf")
        raise AssertionError("pdf должен отклоняться")
    except ValueError:
        pass


def test_diff_types():
    old = [{"heading": "A", "level": 1, "pos": 0, "text": "одно и то же"},
           {"heading": "B", "level": 1, "pos": 1, "text": "было"}]
    new = [{"heading": "A", "level": 1, "pos": 0, "text": "одно и то же"},
           {"heading": "B", "level": 1, "pos": 1, "text": "стало совсем"},
           {"heading": "C", "level": 1, "pos": 2, "text": "новое"}]
    d = diff_sections(old, new)
    types = {c["heading"]: c["type"] for c in d["changes"]}
    assert types == {"A": "unchanged", "B": "changed", "C": "added"}
    assert d["summary"]["changed"] == 1


def test_render_html_shows_words():
    change = {"type": "changed", "heading": "Возвраты",
              "old_text": "возврат в течение 14 дней",
              "new_text": "возврат в течение 30 дней"}
    h = render_html(change)
    assert "14" in h and "30" in h
    assert "#F5C6C6" in h and "#B7E4C7" in h
    assert "Что изменилось" in h
    assert "Добавлено" in render_html({"type": "added", "new_text": "новое"})
    assert "Без изменений" in render_html({"type": "unchanged"})


def test_related_and_transfer(tmp_path):
    con = _pool(tmp_path)
    change = {"heading": "Возвраты", "new_text": "возврат денег за билет", "old_text": ""}
    rel = related_for_change(con, change)
    assert rel and rel[0]["method"] in ("phrase", "words")
    assert "возврат" in rel[0]["detail"] or "Возврат" in rel[0]["detail"]
    bid = transfer_to_build(con, "recheck", [{"candidate_id": rel[0]["candidate_id"],
                                              "why": "Возвраты (phrase)"}])
    row = con.execute("SELECT * FROM build WHERE id=?", (bid,)).fetchone()
    assert row["picked"] == 1
    sid = save_kb_snapshot(con, "doc", "d.md", [{"heading": "A", "level": 1,
                                                "pos": 0, "text": "t"}])
    assert sid > 0
    con.close()
