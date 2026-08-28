"""Разбор присланных значений формы по input_schema вида.

Набор полей у каждого вида свой и берётся из его базы знаний.
"""

from __future__ import annotations

from typing import Any

# Логическое поле имеет три состояния: не указано, да, нет.
# Движки различают незаполненное поле и наблюдённое отсутствие признака.
BOOL_CHOICES = [("", "не указано"), ("yes", "да"), ("no", "нет")]


class FieldError(ValueError):
    pass


def parse_observation(schema: list[dict[str, Any]], form: dict[str, list[str]]) -> dict[str, Any]:
    """Преобразует строки формы в наблюдение. Пустое поле в результат не попадает."""
    observation: dict[str, Any] = {}

    for field in schema:
        raw = (form.get(field["id"], [""])[0] or "").strip()
        if not raw:
            continue
        kind = field["type"]

        if kind in ("choice", "text"):
            observation[field["id"]] = raw
        elif kind == "boolean":
            observation[field["id"]] = raw == "yes"
        elif kind in ("number", "integer"):
            try:
                value = float(raw.replace(",", "."))
            except ValueError:
                raise FieldError(f"«{field['label_ru']}»: ожидалось число, получено {raw!r}")
            observation[field["id"]] = int(value) if kind == "integer" else value
        elif kind == "numbers":
            parts = [p for p in raw.replace(";", ",").replace(" ", ",").split(",") if p]
            try:
                observation[field["id"]] = [float(p.replace(",", ".")) for p in parts]
            except ValueError:
                raise FieldError(f"«{field['label_ru']}»: ожидались числа через запятую, получено {raw!r}")
        else:
            raise FieldError(f"Неизвестный тип поля: {kind}")

    return observation


def filled_count(schema: list[dict[str, Any]], observation: dict[str, Any]) -> tuple[int, int]:
    return sum(1 for f in schema if f["id"] in observation), len(schema)
