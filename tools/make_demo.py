"""Генерирует демо-пул для ручной проверки без реальных данных."""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "demo_data"
ROOT.mkdir(exist_ok=True)

rows = [
    ("Запрос", "Категория", "Сложность", "ID"),
    ("Как вернуть товар?", "Возвраты", "Лёгкая", "A-1"),
    ("как  вернуть   товар? ", "Возвраты", "Лёгкая", "A-2"),
    ("Где мой заказ?", "Доставка", "Лёгкая", "B-1"),
    ("", "Доставка", "Сложная", "B-2"),
    ("Тариф для юрлиц?", "", "Сложная", "C-1"),
    ("#ДЕЛ/0!", "Мусор", "Лёгкая", "D-1"),
    ("Как вернуть товар?", "Возвраты", "Лёгкая", "A-1-дубль"),
]

with open(ROOT / "demo_ru.csv", "w", encoding="utf-8-sig", newline="") as f:
    csv.writer(f, delimiter=";").writerows(rows)

with open(ROOT / "demo.jsonl", "w", encoding="utf-8") as f:
    for r in rows[1:]:
        f.write(json.dumps({"Запрос": r[0], "Категория": r[1],
                            "Сложность": r[2], "ID": r[3]},
                           ensure_ascii=False) + "\n")

print(f"демо создано: {ROOT}")
