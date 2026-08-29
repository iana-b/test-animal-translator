"""Приложение FastAPI: JSON-интерфейс и страницы, один процесс и один порт.

Здесь только маршруты и модели ответов. Сам разбор живёт в species/ поверх общего
разбора формы в forms.py; api.py оборачивает его для JSON, web.py — для разметки.
Эти два модуля не зависят друг от друга: страницы не ходят в собственный API, обе
ветки вызывают один и тот же код.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from . import api, web
from .knowledge import load_species
from .schemas import (
    ErrorResponse,
    HealthResponse,
    SpeciesDetail,
    SpeciesSummary,
    TranslateRequest,
    TranslateResponse,
)

DESCRIPTION = """
Разбор сигналов животных по опубликованным исследованиям.

Каждое число возводится к источнику, а там, где данных нет, приложение
отказывается отвечать и объясняет, какого рода это незнание.

Схема наблюдения своя у каждого вида: она приходит в `GET /api/species/{slug}`
полем `input_schema`, и поля запроса берутся оттуда.
"""

TAGS = [
    {"name": "Виды", "description": "Что есть в базе знаний и как устроен разбор"},
    {"name": "Разбор", "description": "Трактовка наблюдения с уверенностью и источниками"},
    {"name": "Служебное", "description": "Health check: отвечает ли сервис"},
]

app = FastAPI(
    title="Переводчик сигналов животных",
    description=DESCRIPTION,
    version=api.API_VERSION,
    openapi_tags=TAGS,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)


@app.exception_handler(api.ApiError)
async def _api_error(request: Request, exc: api.ApiError) -> JSONResponse:
    """Ошибки разбора отдаются в том же виде, что и ошибки валидации FastAPI."""
    return JSONResponse({"detail": exc.as_detail()}, status_code=exc.status)


# --- JSON ---------------------------------------------------------------------

@app.get("/api/health", tags=["Служебное"], summary="Health check")
def health() -> HealthResponse:
    return HealthResponse(**api.health())


@app.get("/api/species", tags=["Виды"], summary="Список видов")
def species_list() -> list[SpeciesSummary]:
    return [SpeciesSummary(**{k: v for k, v in item.items() if k != "href"})
            for item in api.species_list()["species"]]


@app.get("/api/species/{slug}", tags=["Виды"], summary="Схема ввода, источники и мифы")
def species_detail(slug: str) -> SpeciesDetail:
    return SpeciesDetail(**api.species_detail(slug))


@app.get("/api/translate", tags=["Разбор"], summary="Разбор наблюдения (значения строками)")
def translate_get(
    request: Request,
    species: Annotated[str, Query(description="Слаг вида, например dog")],
) -> TranslateResponse:
    values = {key: request.query_params.getlist(key)
              for key in request.query_params if key != "species"}
    return TranslateResponse(**api.translate(species, values))


@app.post("/api/translate", tags=["Разбор"], summary="Разбор наблюдения (значения своих типов)")
def translate_post(payload: TranslateRequest) -> TranslateResponse:
    return TranslateResponse(**api.translate_from_json(payload.model_dump()))


# --- Страницы -----------------------------------------------------------------

def _html(payload: bytes, status: int = 200) -> HTMLResponse:
    return HTMLResponse(payload.decode("utf-8"), status_code=status)


@app.get("/", include_in_schema=False)
def page_index() -> HTMLResponse:
    return _html(web.index_page())


@app.get("/species/{slug}", include_in_schema=False)
def page_species(slug: str, request: Request) -> HTMLResponse:
    if slug not in api.known_slugs():
        return _html(web.not_found_page(), 404)
    values: dict[str, list[str]] = {key: request.query_params.getlist(key)
                                    for key in request.query_params}
    if not any(v and v[0] for v in values.values()):
        return _html(web.species_page(slug))
    return _html(web.render_species(slug, values))


@app.get("/species/{slug}/kb", include_in_schema=False)
def page_knowledge(slug: str) -> HTMLResponse:
    if slug not in api.known_slugs():
        return _html(web.not_found_page(), 404)
    return _html(web.knowledge_page(load_species(slug)))


def serve(port: int = 8000, host: str = "127.0.0.1") -> None:
    import uvicorn

    print(f"Открой http://{host}:{port}  ·  документация API: http://{host}:{port}/docs")
    uvicorn.run(app, host=host, port=port, log_level="warning")
