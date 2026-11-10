"""Предклассификатор: правила, Байес, бенчмарк по классам."""
from core.pool_import import import_source
from core.preclassify import (
    benchmark,
    dump_model,
    extract_keywords,
    labeled_rows,
    load_model,
    predict_nb,
    predict_rules,
    train_nb,
)
from core.roles import GROUP, MAIN
from storage.database import connect


def _pool(tmp_path, per_class=30):
    p = tmp_path / "p.csv"
    lines = ["З;Г"]
    for i in range(per_class):
        lines.append(f"как вернуть товар номер {i};Возвраты")
    for i in range(per_class):
        lines.append(f"где моя посылка номер {i};Доставка")
    for i in range(6):
        lines.append(f"подозрительное списание {i};Мошенничество")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    con = connect(tmp_path / "ws.sqlite")
    import_source(con, p, {"З": MAIN, "Г": GROUP})
    return con


def test_rules_guess_id_like(tmp_path):
    rows = [("вернуть товар назад", "Возвраты"), ("вернуть деньги назад", "Возвраты"),
            ("где посылка сейчас", "Доставка"), ("где посылка моя", "Доставка")]
    rules = extract_keywords(rows, top_n=4)
    assert rules["Возвраты"] and rules["Доставка"]
    pred, hits = predict_rules(rules, "хочу вернуть товар")
    assert pred == "Возвраты" and hits > 0
    assert predict_rules(rules, "абракадабра про луну")[0] is None


def test_nb_recalls_big_classes_and_serializes(tmp_path):
    con = _pool(tmp_path)
    rows = labeled_rows(con, GROUP)
    assert len(rows) == 66
    model = train_nb(rows)
    for text, true in [("как вернуть товар номер 999", "Возвраты"),
                       ("где моя посылка номер 999", "Доставка")]:
        pred, _scores = predict_nb(model, text)
        assert pred == true
    blob = dump_model(model)
    pred2, _s2 = predict_nb(load_model(blob), "как вернуть товар номер 1")
    assert pred2 == "Возвраты"
    con.close()


def test_benchmark_reports_rare_recall(tmp_path):
    con = _pool(tmp_path)
    rows = labeled_rows(con, GROUP)
    out = benchmark(rows)
    assert out["n_train"] + out["n_test"] == len(rows)
    assert any("recall" in line or "Проверено" in line for line in out["report"])
    assert "Мошенничество" in out["nb"]["per_class"]
    assert out["rules"]["per_class"]["Возвраты"]["r"] >= 0.8
    con.close()


def test_benchmark_needs_data(tmp_path):
    import pytest
    con = connect(tmp_path / "w.sqlite")
    try:
        with pytest.raises(ValueError):
            benchmark([])
    finally:
        con.close()
