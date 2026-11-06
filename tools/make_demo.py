"""Генерирует демо-пул для ручной проверки без реальных данных."""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROWS = [
    ("Запрос", "Категория", "Сложность", "ID"),
    ("Как вернуть товар?", "Возвраты", "Лёгкая", "A-1"),
    ("как  вернуть   товар? ", "Возвраты", "Лёгкая", "A-2"),
    ("Где мой заказ?", "Доставка", "Лёгкая", "B-1"),
    ("", "Доставка", "Сложная", "B-2"),
    ("Тариф для юрлиц?", "", "Сложная", "C-1"),
    ("#ДЕЛ/0!", "Мусор", "Лёгкая", "D-1"),
    ("Как вернуть товар?", "Возвраты", "Лёгкая", "A-1-дубль"),
]

MAPPING = {"Запрос": "main_text", "Категория": "group",
           "Сложность": "custom:Сложность", "ID": "ext_id"}


def write_demo_files(root: str | Path) -> list[str]:
    """Пишет demo_ru.csv + demo.jsonl в каталог. Возвращает пути."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with open(root / "demo_ru.csv", "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f, delimiter=";").writerows(ROWS)
    with open(root / "demo.jsonl", "w", encoding="utf-8") as f:
        for r in ROWS[1:]:
            f.write(json.dumps({"Запрос": r[0], "Категория": r[1],
                                "Сложность": r[2], "ID": r[3]},
                               ensure_ascii=False) + "\n")
    return [str(root / "demo_ru.csv"), str(root / "demo.jsonl")]


def main() -> None:
    root = Path(__file__).resolve().parent.parent / "demo_data"
    print(f"демо создано: {write_demo_files(root)}")


if __name__ == "__main__":
    main()
