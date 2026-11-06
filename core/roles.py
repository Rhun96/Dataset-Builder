"""Generic-роли колонок. Независимые от внешних ревьюеров.

Ядро знает только свои роли. Совместимость с любым потребителем —
дело export-адаптера, а не модели.
"""

from __future__ import annotations

import re

MAIN = "main_text"
RESPONSE = "response_text"
EXT_ID = "ext_id"
GROUP = "group"
TOPIC = "topic"
COMMENT = "comment"
KB_REF = "kb_ref"
EXTRA = "extra"
IGNORE = "ignore"
CUSTOM_PREFIX = "custom:"

ROLE_LABELS: dict[str, str] = {
    MAIN: "Основной текст",
    RESPONSE: "Ответ / результат",
    EXT_ID: "Идентификатор",
    GROUP: "Группа / категория",
    TOPIC: "Тема",
    COMMENT: "Комментарий",
    KB_REF: "Источник",
    EXTRA: "Дополнительное поле",
    IGNORE: "Не загружать",
}

# Что можно использовать как измерение для фильтров/квот/покрытия.
DIMENSION_ROLES: tuple[str, ...] = (GROUP, TOPIC, KB_REF, EXTRA, COMMENT)

_WS_RE = re.compile(r"\s+")


def is_custom(role: str) -> bool:
    return role.startswith(CUSTOM_PREFIX)


def custom_name(role: str) -> str:
    return role[len(CUSTOM_PREFIX):] if is_custom(role) else role


def dim_label(role: str) -> str:
    if is_custom(role):
        return custom_name(role)
    return ROLE_LABELS.get(role, role)


def sanitize_custom_name(name: str) -> str:
    txt = str(name or "").replace("\n", " ").replace("\r", " ").replace("\t", " ")
    cleaned = _WS_RE.sub(" ", txt).strip()
    if not cleaned:
        raise ValueError("пустое имя своей категории")
    if len(cleaned) > 64:
        raise ValueError("имя категории длиннее 64 символов")
    return cleaned


def validate_mapping(mapping: dict[str, str | None]) -> dict[str, str]:
    """Проверка сопоставления колонка -> роль. Нормализует custom:*."""
    out: dict[str, str] = {}
    for col, role in (mapping or {}).items():
        if not role:
            continue
        if role in ROLE_LABELS:
            out[col] = role
            continue
        if is_custom(role):
            out[col] = CUSTOM_PREFIX + sanitize_custom_name(custom_name(role))
            continue
        raise ValueError(f"неизвестная роль {role!r} для колонки {col!r}")
    if MAIN not in out.values():
        raise ValueError("не сопоставлено поле «Основной текст» — собирать не из чего")
    return out


def is_dimension(role: str) -> bool:
    return role in DIMENSION_ROLES or is_custom(role)


def all_roles_for_ui() -> list[tuple[str, str]]:
    """Список (код, подпись) для выпадающих списков маппинга."""
    base = [(MAIN, ROLE_LABELS[MAIN]), (RESPONSE, ROLE_LABELS[RESPONSE]),
            (EXT_ID, ROLE_LABELS[EXT_ID]), (GROUP, ROLE_LABELS[GROUP]),
            (TOPIC, ROLE_LABELS[TOPIC]), (COMMENT, ROLE_LABELS[COMMENT]),
            (KB_REF, ROLE_LABELS[KB_REF]), (EXTRA, ROLE_LABELS[EXTRA]),
            (IGNORE, ROLE_LABELS[IGNORE])]
    return base
