"""Модели запросов и ответов.

Из них FastAPI собирает схему OpenAPI, поэтому описания полей здесь — это и есть
документация API.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class StepOut(BaseModel):
    """Шаг разбора: что посчитали, из чего и на основании какого источника."""

    label_ru: str = Field(description="Название шага")
    value_ru: str = Field(description="Что получилось на этом шаге")
    source_ids: list[str] = Field(default_factory=list,
                                  description="Идентификаторы источников из базы знаний")


class UnknownOut(BaseModel):
    """Причина, по которой часть ответа осталась неопределённой."""

    field_ru: str = Field(description="Чего не хватает или что не определено")
    kind: Literal["data_gap", "not_encoded", "not_applicable", "beyond_model"] = Field(
        description=("data_gap — не хватает наблюдения; not_encoded — сигнал этого не несёт; "
                     "not_applicable — правило здесь не работает; "
                     "beyond_model — информация есть, но модель её не покрывает"))
    explanation_ru: str = Field(description="Пояснение для пользователя")


class ResultOut(BaseModel):
    """Разбор наблюдения."""

    species: str
    verdict: Literal["translated", "partial", "insufficient", "no_translation_exists"] = Field(
        description="Чем закончился разбор")
    headline_ru: str = Field(description="Трактовка одной фразой")
    confidence: float | None = Field(
        default=None, ge=0, le=1,
        description="Число выводится только там, где есть измеренная величина")
    confidence_level_ru: str | None = None
    confidence_scope_ru: str | None = Field(
        default=None, description="К чему именно относится число")
    steps: list[StepOut] = Field(default_factory=list)
    unknowns: list[UnknownOut] = Field(default_factory=list)
    alternatives_ru: list[str] = Field(default_factory=list)
    warnings_ru: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


class SourceOut(BaseModel):
    """Запись библиографии."""

    id: str
    authors: str
    year: int
    title: str
    journal: str
    doi: str | None = None
    url: str | None = None
    licence: str
    evidence_grade: Literal["strong", "moderate", "limited"]
    open_access: dict[str, Any] | None = None
    sample_ru: str
    gives_ru: str
    correction: dict[str, Any] | None = None


class MythOut(BaseModel):
    claim_ru: str = Field(description="Распространённое утверждение")
    reality_ru: str = Field(description="Что на самом деле показывают исследования")
    source_ids: list[str]


class FieldOptionOut(BaseModel):
    value: str
    label_ru: str


class InputFieldOut(BaseModel):
    """Поле формы наблюдения. У каждого вида свой набор."""

    id: str
    label_ru: str
    type: Literal["choice", "boolean", "number", "integer", "numbers", "text"]
    required: bool = False
    hint_ru: str | None = None
    example_ru: str | None = None
    options: list[FieldOptionOut] | None = None


class SpeciesSummary(BaseModel):
    slug: str
    name_ru: str
    name_en: str | None = None
    scientific_name: str
    engine: str = Field(description="Какой движок разбирает сигналы этого вида")
    engine_note_ru: str = Field(description="Почему логика именно такая")
    sources: int = Field(description="Сколько источников в базе знаний вида")


class SpeciesDetail(BaseModel):
    slug: str
    name_ru: str
    scientific_name: str
    engine: str
    engine_note_ru: str
    research_maturity_ru: str | None = None
    input_schema: list[InputFieldOut]
    sources: list[SourceOut]
    myths: list[MythOut]


class TranslateRequest(BaseModel):
    """Наблюдение с типизированными значениями."""

    species: str = Field(description="Слаг вида, например dog")
    observation: dict[str, Any] = Field(
        default_factory=dict,
        description="Поля из input_schema вида. Незаполненные просто не передаются.")

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "species": "spermwhale",
                "observation": {
                    "signal_type": "coda",
                    "inter_click_intervals_s": [0.12, 0.12, 0.35, 0.12],
                    "extra_final_click": True,
                },
            }]
        }
    }


class TranslateResponse(BaseModel):
    species: str
    observation: dict[str, Any] = Field(description="Как приложение поняло ввод")
    fields_filled: int
    fields_total: int
    result: ResultOut
    sources: list[SourceOut] = Field(description="Полные записи источников, на которые опирается вывод")


class HealthResponse(BaseModel):
    status: Literal["ok"]
    api_version: str
    species: int


class ErrorResponse(BaseModel):
    error: str
    status: int
    field: str | None = Field(default=None, description="Поле, из-за которого запрос не прошёл")
