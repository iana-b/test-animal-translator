"""Разбор наблюдений в виде данных.

Функции не знают ни про HTTP, ни про FastAPI: маршруты и модели ответов живут в
app.py и schemas.py. Ошибки поднимаются как ApiError с кодом ответа.
"""

from __future__ import annotations

import importlib
from dataclasses import asdict
from typing import Any

from .forms import FieldError, filled_count, parse_observation
from .knowledge import KNOWLEDGE_DIR, load_species
from .result import Result

API_VERSION = "1.0"



class ApiError(Exception):
    """Ошибка запроса: несёт код ответа и понятное сообщение."""

    def __init__(self, status: int, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.field = field

    def as_detail(self) -> dict[str, Any]:
        """Соглашение FastAPI: тело ошибки лежит в поле detail."""
        detail: dict[str, Any] = {"message": self.message}
        if self.field:
            detail["field"] = self.field
        return detail


def known_slugs() -> list[str]:
    order = ["honeybee", "dog", "elephant", "spermwhale"]
    slugs = sorted(p.stem for p in KNOWLEDGE_DIR.glob("*.json"))
    return sorted(slugs, key=lambda s: order.index(s) if s in order else 99)


def _species_or_404(slug: str) -> dict[str, Any]:
    if slug not in known_slugs():
        raise ApiError(404, f"Вид {slug!r} не найден. Доступны: {', '.join(known_slugs())}")
    return load_species(slug)


def _engine(slug: str):
    return importlib.import_module(f".species.{slug}", package=__package__)


def _source_records(kb: dict[str, Any], ids: list[str]) -> list[dict[str, Any]]:
    by_id = {s["id"]: s for s in kb["sources"]}
    return [by_id[i] for i in dict.fromkeys(ids) if i in by_id]


def serialise(result: Result) -> dict[str, Any]:
    """Result → словарь, пригодный для json.dumps. Перечисления разворачиваются в строки."""
    data = asdict(result)
    data["verdict"] = result.verdict.value
    for unknown, raw in zip(result.unknowns, data["unknowns"]):
        raw["kind"] = unknown.kind.value
    return data


def health() -> dict[str, Any]:
    return {"status": "ok", "api_version": API_VERSION, "species": len(known_slugs())}


def species_list() -> dict[str, Any]:
    items = []
    for slug in known_slugs():
        kb = load_species(slug)
        items.append({
            "slug": slug,
            "name_ru": kb["name_ru"],
            "name_en": kb.get("name_en"),
            "scientific_name": kb["scientific_name"],
            "engine": kb["engine"],
            "engine_note_ru": kb["engine_note_ru"],
            "sources": len(kb["sources"]),
            "href": f"/api/species/{slug}",
        })
    return {"species": items}


def species_detail(slug: str) -> dict[str, Any]:
    kb = _species_or_404(slug)
    return {
        "slug": slug,
        "name_ru": kb["name_ru"],
        "scientific_name": kb["scientific_name"],
        "engine": kb["engine"],
        "engine_note_ru": kb["engine_note_ru"],
        "research_maturity_ru": kb.get("research_maturity_ru"),
        "input_schema": kb["input_schema"],
        "sources": kb["sources"],
        "myths": kb["myths"],
    }


def translate(slug: str, values: dict[str, list[str]]) -> dict[str, Any]:
    kb = _species_or_404(slug)
    known = {f["id"] for f in kb["input_schema"]}
    unexpected = sorted(set(values) - known - {"species"})
    if unexpected:
        raise ApiError(400, f"Неизвестные поля для вида {slug!r}: {', '.join(unexpected)}",
                       field=unexpected[0])
    try:
        observation = parse_observation(kb["input_schema"], values)
    except FieldError as exc:
        raise ApiError(400, str(exc)) from exc

    result = _engine(slug).translate(observation)
    filled, total = filled_count(kb["input_schema"], observation)
    return {
        "species": slug,
        "observation": observation,
        "fields_filled": filled,
        "fields_total": total,
        "result": serialise(result),
        "sources": _source_records(kb, result.source_ids),
    }


def translate_from_json(payload: dict[str, Any]) -> dict[str, Any]:
    """POST-вариант: значения приходят типизированными, а не строками формы."""
    if not isinstance(payload, dict):
        raise ApiError(400, "Тело запроса должно быть объектом JSON")
    slug = payload.get("species")
    if not slug:
        raise ApiError(400, "Не указан вид: ожидается поле species", field="species")
    observation = payload.get("observation", {})
    if not isinstance(observation, dict):
        raise ApiError(400, "Поле observation должно быть объектом", field="observation")

    as_form = {}
    for key, value in observation.items():
        if isinstance(value, bool):
            as_form[key] = ["yes" if value else "no"]
        elif isinstance(value, (list, tuple)):
            as_form[key] = [", ".join(str(v) for v in value)]
        else:
            as_form[key] = [str(value)]
    return translate(slug, as_form)
