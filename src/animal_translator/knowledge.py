"""Загрузка базы знаний из data/knowledge/*.json."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "data" / "knowledge"


@lru_cache(maxsize=None)
def load_species(slug: str) -> dict[str, Any]:
    path = KNOWLEDGE_DIR / f"{slug}.json"
    if not path.exists():
        raise FileNotFoundError(f"Нет базы знаний для вида {slug!r}: ожидался {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def sources_by_id(species: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s["id"]: s for s in species["sources"]}
