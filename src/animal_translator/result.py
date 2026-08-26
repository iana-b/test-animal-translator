"""Общий формат ответа для всех видов.

Один вид — один движок, но наружу все они отдают одну и ту же структуру,
иначе интерфейс пришлось бы писать заново под каждое животное.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Verdict(str, Enum):
    TRANSLATED = "translated"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"
    NO_TRANSLATION_EXISTS = "no_translation_exists"


class UnknownKind(str, Enum):
    """Четыре разных «не знаю». Их смешение — главная нечестность в такой задаче.

    DATA_GAP       — не хватает наблюдения, его можно доснять.
    NOT_ENCODED    — сигнал этой информации не несёт в принципе.
    NOT_APPLICABLE — правило не работает в этих условиях.
    BEYOND_MODEL   — информация в сигнале есть, но опубликованная модель её не покрывает.
    """

    DATA_GAP = "data_gap"
    NOT_ENCODED = "not_encoded"
    NOT_APPLICABLE = "not_applicable"
    BEYOND_MODEL = "beyond_model"


@dataclass
class Unknown:
    field_ru: str
    kind: UnknownKind
    explanation_ru: str


@dataclass
class Step:
    """Шаг рассуждения: что посчитали, из чего и на основании какого источника."""

    label_ru: str
    value_ru: str
    source_ids: list[str] = field(default_factory=list)


@dataclass
class Result:
    species: str
    verdict: Verdict
    headline_ru: str
    confidence: float | None = None
    confidence_level_ru: str | None = None
    confidence_scope_ru: str | None = None
    steps: list[Step] = field(default_factory=list)
    unknowns: list[Unknown] = field(default_factory=list)
    alternatives_ru: list[str] = field(default_factory=list)
    warnings_ru: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)


def confidence_level_ru(value: float) -> str:
    if value >= 0.70:
        return "высокая"
    if value >= 0.50:
        return "средняя"
    if value >= 0.30:
        return "низкая"
    return "недостаточно данных"
