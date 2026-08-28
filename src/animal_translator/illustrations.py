"""Пиктограммы видов и цветовые акценты.

Пиктограммы взяты с game-icons.net и лежат в data/illustrations. Они
встраиваются в страницу, поэтому внешних запросов при открытии не происходит.
Авторы и лицензии хранятся в data/illustrations/sources.json и показываются
в интерфейсе.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ILLUSTRATION_DIR = Path(__file__).resolve().parents[2] / "data" / "illustrations"

ACCENTS = {
    "honeybee": {"ink": "#a86a10", "wash": "#fbf1dc", "line": "#e5cf9f"},
    "dog": {"ink": "#9c4a2a", "wash": "#fbeae3", "line": "#e8c4b3"},
    "elephant": {"ink": "#4a6076", "wash": "#eaeff5", "line": "#c3d0de"},
    "spermwhale": {"ink": "#255f66", "wash": "#e4f0f0", "line": "#b6d5d6"},
}


@lru_cache(maxsize=None)
def svg(slug: str) -> str:
    path = ILLUSTRATION_DIR / f"{slug}.svg"
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


@lru_cache(maxsize=None)
def _sources() -> dict[str, Any]:
    path = ILLUSTRATION_DIR / "sources.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def credit(slug: str) -> dict[str, Any] | None:
    return _sources().get(slug)


def credit_line(slug: str) -> str:
    """Строка авторства для подписи под пиктограммой."""
    info = credit(slug)
    if not info:
        return ""
    who = f"{info['author']}, " if info.get("author") else ""
    return f"Пиктограмма: {who}{info['source']}, {info['licence']}"


def accent(slug: str) -> dict[str, str]:
    return ACCENTS.get(slug, {"ink": "#2f5d50", "wash": "#eef2ef", "line": "#d9d7cf"})
