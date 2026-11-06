"""Нормализация текста для отбора и отпечатков.

Порядок зафиксирован ТЗ-уточнением:
NFKC -> NBSP->пробел -> схлопнуть пробелы -> strip -> casefold -> ё->е.

Оригиналы не меняем. Нормы — только для поиска/группировок/дедупа.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

_WS_RE = re.compile(r"\s+")


def clean_display(value: Any) -> str:
    """Текст для показа/хранения оригинала: NFKC + аккуратные пробелы."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = value if isinstance(value, str) else str(value)
    text = unicodedata.normalize("NFKC", text).replace("\u00a0", " ")
    return _WS_RE.sub(" ", text).strip()


def norm_key(value: Any) -> str:
    """Ключ для группировок/сравнений: регистр и ё не различаем."""
    text = clean_display(value)
    if not text:
        return ""
    text = text.casefold()
    return text.replace("ё", "е")


def fingerprint(value: Any) -> str:
    """Стабильный отпечаток основного текста (sha1 hex)."""
    return hashlib.sha1(norm_key(value).encode("utf-8")).hexdigest()


def is_missing(value: Any) -> bool:
    return clean_display(value) == ""
