"""Нормализация: порядок NFKC -> пробелы -> casefold -> ё->е."""
from core.normalize import clean_display, fingerprint, is_missing, norm_key


def test_order_nfkc_casefold_yo():
    assert norm_key("ЁЛКА") == norm_key("елка") == "елка"
    assert norm_key("  Каталог\u00a0товаров  ") == "каталог товаров"
    assert norm_key("ﬁ") == "fi"  # NFKC-лигатура
    assert clean_display("  a  b ") == "a b"
    assert is_missing("   ")
    assert not is_missing("0")


def test_fingerprint_stable():
    assert fingerprint("Ёлка") == fingerprint("елка ")
    assert fingerprint("a") != fingerprint("b")
