#!/usr/bin/env python3
"""Пересборка раздела «Источники» в README из базы знаний.

Список источников собирается из data/knowledge, поэтому README не может
разойтись с тем, на чём работает приложение.

    python3 scripts/build_readme.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
START = "<!-- sources:start -->"
END = "<!-- sources:end -->"

ORDER = ["honeybee", "dog", "elephant", "spermwhale"]
GRADE_RU = {"strong": "сильная", "moderate": "средняя", "limited": "ограниченная"}


def access_ru(source: dict) -> str:
    info = source.get("open_access")
    if not info:
        return "полный текст закрыт"
    if info["kind"] == "pmc":
        return f'открытый текст: [{info["id"]}](https://pmc.ncbi.nlm.nih.gov/articles/{info["id"]}/)'
    if info["kind"] == "url":
        return f'открытый текст: [{info["note_ru"]}]({info["url"]})'
    return info["note_ru"]


def render() -> str:
    lines: list[str] = []
    for slug in ORDER:
        kb = json.loads((ROOT / "data" / "knowledge" / f"{slug}.json").read_text(encoding="utf-8"))
        lines.append(f'### {kb["name_ru"]} — *{kb["scientific_name"]}*\n')
        for s in kb["sources"]:
            link = f'https://doi.org/{s["doi"]}' if s.get("doi") else s.get("url", "")
            label = f'doi.org/{s["doi"]}' if s.get("doi") else "ссылка"
            head = f'- **{s["authors"]}** ({s["year"]}). {s["title"]}. *{s["journal"]}*.'
            if link:
                head += f' [{label}]({link})'
            lines.append(head)
            lines.append(f'  <br>Доказательность: {GRADE_RU.get(s["evidence_grade"], s["evidence_grade"])}'
                         f' · {access_ru(s)}')
            lines.append(f'  <br>{s["gives_ru"]}')
            if s.get("correction"):
                c = s["correction"]
                lines.append(f'  <br>**Опубликована поправка:** [{c["doi"]}]({c["url"]}) — {c["what_ru"]}')
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    text = README.read_text(encoding="utf-8")
    before, rest = text.split(START, 1)
    _, after = rest.split(END, 1)
    updated = f"{before}{START}\n\n{render()}\n{END}{after}"
    if "--check" in sys.argv:
        if updated != text:
            sys.exit("Раздел «Источники» в README устарел: запустите scripts/build_readme.py")
        print("README соответствует базе знаний")
        return
    README.write_text(updated, encoding="utf-8")
    print(f"Раздел «Источники» обновлён: {sum(1 for line in render().splitlines() if line.startswith('- **'))} записей")


if __name__ == "__main__":
    main()
