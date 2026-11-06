"""Роли маппинга: обязательный main_text, custom:* с санитизацией."""
import pytest

from core.roles import (
    CUSTOM_PREFIX,
    MAIN,
    all_roles_for_ui,
    is_dimension,
    sanitize_custom_name,
    validate_mapping,
)


def test_require_main():
    with pytest.raises(ValueError):
        validate_mapping({"A": "group"})
    m = validate_mapping({"Запрос": MAIN, "Категор": "group"})
    assert m["Запрос"] == MAIN


def test_custom():
    m = validate_mapping({"X": "custom:  Мой  раздел ", "З": MAIN})
    assert m["X"] == CUSTOM_PREFIX + "Мой раздел"
    assert is_dimension(m["X"])
    with pytest.raises(ValueError):
        sanitize_custom_name("  ")
    with pytest.raises(ValueError):
        validate_mapping({"X": "custom:\n\t", "З": MAIN})
    with pytest.raises(ValueError):
        validate_mapping({"X": "unknown_role", "З": MAIN})


def test_ui_list_has_main_and_ignore():
    codes = [c for c, _ in all_roles_for_ui()]
    assert MAIN in codes and "ignore" in codes
