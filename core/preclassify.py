"""Предклассификатор пула: правила и наивный Байес, без внешних зависимостей.

Назначение — предложить метки неразмеченным записям до отбора (квоты и дефицит
дальше работают как обычно). От классификатора требуется recall редких классов,
точность дотягивает человек и квоты. Всё детерминировано, всё тестируется.
"""

from __future__ import annotations

import json
import math
import sqlite3

from core.normalize import norm_key


def tokens(text: str) -> list[str]:
    """Те же токены, что и в отборе (нормализация + сплит)."""
    return (norm_key(text or "")).split()


# --- правила по ключевым словам ---

def extract_keywords(rows: list[tuple[str, str]], top_n: int = 8) -> dict[str, list[str]]:
    """Авто-правила из размеченных строк: (текст, значение) -> {значение: [слова]}.

    Скоринг — отношение частоты слова внутри значения к частоте снаружи.
    Детерминирован: сортировка по (-отношение, слово).
    """
    from collections import Counter
    in_c: dict[str, Counter] = {}
    in_tot: dict[str, int] = {}
    for text, value in rows:
        toks = tokens(text)
        if not toks:
            continue
        in_c.setdefault(value, Counter()).update(toks)
        in_tot[value] = in_tot.get(value, 0) + len(toks)
    # частоты снаружи = всё минус своё
    all_c: Counter = Counter()
    for cnt in in_c.values():
        all_c.update(cnt)
    all_tot = sum(in_tot.values())
    rules: dict[str, list[str]] = {}
    for value, cnt in sorted(in_c.items()):
        scored = []
        for tok, c in cnt.items():
            if c < 2:
                continue
            p_in = c / max(in_tot[value], 1)
            p_out = (all_c[tok] - c) / max(all_tot - in_tot[value], 1)
            scored.append((p_in / (p_out + 1e-9), tok))
        scored.sort(key=lambda x: (-x[0], x[1]))
        rules[value] = [tok for _, tok in scored[:top_n]]
    return rules


def predict_rules(rules: dict[str, list[str]], text: str) -> tuple[str | None, int]:
    """(значение с максимумом вхождений ключевых слов, число вхождений).

    Одно слово ищется среди токенов, фраза из нескольких слов — подстрокой
    в нормализованном тексте.
    """
    toks = set(tokens(text))
    nt = norm_key(text or "")
    if not toks:
        return None, 0
    best: str | None = None
    best_hits = 0
    for value in sorted(rules):
        hits = sum(1 for kw in rules[value]
                   if kw in toks or (" " in kw and kw in nt))
        if hits > best_hits:
            best, best_hits = value, hits
    return best, best_hits


def parse_rules(text: str) -> dict[str, list[str]]:
    """'Возврат: вернуть, возврат; Покупка: купить' -> {значение: [слова]}.

    Слова приводятся к той же норме, что и токены текстов.
    """
    rules: dict[str, list[str]] = {}
    for part in (text or "").split(";"):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ValueError(f"нет двоеточия в «{part}» — "
                             "формат: Значение: слово1, слово2; ...")
        name, words = part.split(":", 1)
        name = name.strip()
        kws = [norm_key(w.strip()) for w in words.split(",")]
        kws = [w for w in kws if w]
        if not name or not kws:
            raise ValueError(f"пусто в «{part}» — формат: Значение: слово1, слово2; ...")
        rules[name] = kws
    if not rules:
        raise ValueError("пустые правила — пример: Возврат: вернуть, возврат")
    return rules


# --- наивный Байес ---

def train_nb(rows: list[tuple[str, str]], alpha: float = 1.0,
             balanced: bool = False) -> dict:
    """Модель как dict (сериализуется в JSON): приоры + log P(токен|класс).

    balanced=True — равные приоры классов: большинство не топит редкие.
    """
    from collections import Counter
    docs: dict[str, list[list[str]]] = {}
    for text, value in rows:
        toks = tokens(text)
        if toks:
            docs.setdefault(value, []).append(toks)
    vocab = sorted({t for ds in docs.values() for d in ds for t in d})
    vsize = len(vocab)
    total = sum(len(ds) for ds in docs.values())
    n_labels = len(docs)
    model = {"labels": sorted(docs), "alpha": alpha, "balanced": balanced,
             "log_prior": {}, "log_prob": {}, "vocab_size": vsize}
    for label in sorted(docs):
        ds = docs[label]
        if balanced and n_labels:
            lp = math.log(1.0 / n_labels)
        else:
            lp = math.log(len(ds) / total) if total else 0.0
        model["log_prior"][label] = lp
        cnt: Counter = Counter()
        for d in ds:
            cnt.update(d)
        tot = sum(cnt.values())
        model["log_prob"][label] = {
            t: math.log((cnt.get(t, 0) + alpha) / (tot + alpha * vsize))
            for t in vocab}
    return model


def predict_nb(model: dict, text: str) -> tuple[str | None, dict[str, float]]:
    """(лучший класс, {класс: скор}). Пустой текст -> (None, {})."""
    from collections import Counter
    toks = tokens(text)
    if not toks or not model.get("labels"):
        return None, {}
    cnt = Counter(toks)
    scores = {}
    for label in model["labels"]:
        lp = model["log_prior"].get(label, 0.0)
        probs = model["log_prob"].get(label, {})
        unk = math.log(model.get("alpha", 1.0) / max(model.get("vocab_size", 1), 1))
        s = lp + sum(c * probs.get(t, unk) for t, c in cnt.items())
        scores[label] = s
    best = max(sorted(scores), key=lambda k: scores[k])
    return best, scores


def dump_model(model: dict) -> str:
    return json.dumps(model, ensure_ascii=False)


def load_model(blob: str) -> dict:
    return json.loads(blob)


# --- данные и бенчмарк ---

def labeled_rows(con: sqlite3.Connection, dim: str,
                 limit: int = 100000) -> list[tuple[str, str]]:
    """(текст, значение) размеченных записей пула."""
    rows = con.execute(
        "SELECT c.main_raw, d.value_raw FROM pool_candidate c "
        "JOIN pool_dim d ON d.candidate_id=c.id "
        "WHERE d.dim=? AND d.is_missing=0 AND c.main_raw<>'' "
        "ORDER BY c.id LIMIT ?", (dim, limit)).fetchall()
    return [(r[0], r[1]) for r in rows if (r[1] or "").strip()]


def _split(rows: list, test_mod: int = 5) -> tuple[list, list]:
    train = [r for i, r in enumerate(rows) if i % test_mod != test_mod - 1]
    test = [r for i, r in enumerate(rows) if i % test_mod == test_mod - 1]
    return train, test


def _evaluate(predict, test: list[tuple[str, str]]) -> dict:
    labels = sorted({v for _, v in test})
    stats = {lb: {"tp": 0, "fp": 0, "fn": 0, "support": 0} for lb in labels}
    conf: dict[tuple[str, str], int] = {}
    for text, true in test:
        pred, _score = predict(text)
        stats[true]["support"] += 1
        if pred == true:
            stats[true]["tp"] += 1
        else:
            stats[true]["fn"] += 1
            if pred is not None:
                if pred not in stats:
                    stats[pred] = {"tp": 0, "fp": 0, "fn": 0, "support": 0}
                stats[pred]["fp"] += 1
                conf[(true, pred)] = conf.get((true, pred), 0) + 1
    out = {}
    for lb, s in sorted(stats.items()):
        p = s["tp"] / (s["tp"] + s["fp"]) if (s["tp"] + s["fp"]) else 0.0
        r = s["tp"] / (s["tp"] + s["fn"]) if (s["tp"] + s["fn"]) else 0.0
        out[lb] = {"p": round(p, 3), "r": round(r, 3),
                   "f1": round(2 * p * r / (p + r), 3) if (p + r) else 0.0,
                   "support": s["support"]}
    worst = sorted(conf.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1]))[:3]
    return {"per_class": out, "confused": [{"true": t, "pred": p, "n": n}
                                           for (t, p), n in worst]}


def benchmark(rows: list[tuple[str, str]], balanced: bool = False) -> dict:
    """NB + правила на фиксированном сплите 80/20. Детерминирован."""
    train, test = _split(rows)
    if not test:
        raise ValueError("мало размеченных записей для проверки")
    model = train_nb(train, balanced=balanced)
    nb = _evaluate(lambda t: predict_nb(model, t), test)
    rules = extract_keywords(train)
    kw = _evaluate(lambda t: predict_rules(rules, t), test)
    rep = [f"Проверено записей: {len(test)} из {len(rows)}.",
           "Приоры выровнены: большинство не топит редкие." if balanced else
           "Приоры по долям классов: большинство может топить редкие."]
    for name, res in (("Байес", nb), ("Правила", kw)):
        bad = [f"{lb} (r={m['r']})" for lb, m in sorted(res["per_class"].items())
               if m["support"] > 0 and m["r"] < 0.5]
        rep.append(f"{name}: худший recall — "
                   + (", ".join(bad) if bad else "все классы ≥ 0.5") + ".")
    for c in nb["confused"]:
        rep.append(f"Путает: «{c['true']}» → «{c['pred']}» ({c['n']}).")
    rep.append("Смотри recall редких классов — он решает, теряем ли темы.")
    return {"nb": nb, "rules": kw, "report": rep, "n_train": len(train),
            "n_test": len(test)}
