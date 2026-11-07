"""Синтетический пул для проверки конструктора: обращения в поддержку.

Задача как у AI-тренера: собрать сбалансированную выборку по категориям,
не потерять редкую тему «Мошенничество», отсечь дубли и мусор.
Детерминировано (seed) — файл всегда одинаковый.

Использование: py -3 tools/make_synth.py [N] [выходной.csv]
"""

from __future__ import annotations

import csv
import random
import sys
from pathlib import Path

SEED = 7
DEFAULT_N = 800

CAT_WEIGHTS = [
    ("Возвраты", 0.34),
    ("Доставка", 0.24),
    ("Оплата", 0.16),
    ("Вопросы", 0.12),
    ("Мусор", 0.08),
    ("Мошенничество", 0.02),
]

# (шаблон, сложная?)
TEMPLATES: dict[str, list[tuple[str, bool]]] = {
    "Возвраты": [
        ("Как вернуть товар по заказу {n}?", False),
        ("Хочу оформить возврат, заказ {n}", False),
        ("Верните деньги за заказ {n}, товар бракованный", True),
        ("Можно ли вернуть часть заказа {n}?", False),
        ("Отмените возврат по заказу {n}, передумал", True),
    ],
    "Доставка": [
        ("Где мой заказ {n}?", False),
        ("Курьер не приехал, заказ {n}", False),
        ("Смените адрес доставки заказа {n}", False),
        ("Заказ {n} застрял на сортировке уже неделю", True),
    ],
    "Оплата": [
        ("Не проходит оплата заказа {n}", False),
        ("Списали дважды за заказ {n}", True),
        ("Как применить промокод к заказу {n}?", False),
        ("Верните комиссию за отмену заказа {n}", True),
    ],
    "Вопросы": [
        ("Какой срок гарантии на товар из заказа {n}?", False),
        ("Есть ли инструкция на русском для заказа {n}?", False),
        ("Подскажите вес посылки {n}", False),
    ],
    "Мусор": [
        ("ываыва {n}", False),
        ("Тестовое сообщение {n}", False),
        ("Позовите маму к телефону", False),
    ],
    "Мошенничество": [
        ("С вашего сайта списали деньги, я ничего не заказывал", True),
        ("Звонили якобы из поддержки и просили код из SMS", True),
        ("Фишинговое письмо про выигрыш и мой заказ {n}", True),
    ],
}


def gen_rows(n: int, seed: int = SEED) -> list[tuple[str, str, str, str]]:
    rng = random.Random(seed)
    cats, weights = zip(*CAT_WEIGHTS)
    rows = [("Запрос", "Категория", "Сложность", "ID")]
    for i in range(1, n + 1):
        cat = rng.choices(cats, weights)[0]
        tpl, hard = rng.choice(TEMPLATES[cat])
        text = tpl.format(n=1000 + i)
        roll = rng.random()
        if roll < 0.03 and len(rows) > 1:
            text = rng.choice(rows[1:])[0]  # точный дубль
        elif roll < 0.06:
            text = " " + text.lower() + "  "  # near-дубль
        comp = "Сложная" if (hard or rng.random() < 0.15) else "Легкая"
        cat_out = "" if rng.random() < 0.02 else cat
        rows.append((text, cat_out, comp, f"T-{i:04d}"))
    rows[10] = (rows[10][0], rows[10][1], rows[10][2], "T-0001")  # дубль ID
    rows.append(("", "Мусор", "Легкая", "T-EMPTY"))  # пустой текст — пропуск
    return rows


def main(argv: list[str]) -> Path:
    n = int(argv[1]) if len(argv) > 1 else DEFAULT_N
    out = Path(argv[2]) if len(argv) > 2 else (
        Path(__file__).resolve().parent.parent / "demo_data" / "synth_support.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f, delimiter=";").writerows(gen_rows(n))
    print(f"синтетика: {out} ({n} строк)")
    return out


if __name__ == "__main__":
    main(sys.argv)
