#!/usr/bin/env python3
"""Пересборка изменяемых частей README.

Список источников собирается из data/knowledge, число тестов — из tests, поэтому
README не может разойтись с тем, на чём работает приложение.

    python3 scripts/build_readme.py           обновить
    python3 scripts/build_readme.py --check   убедиться, что README не отстал
"""

from __future__ import annotations

import ast
import json
import re
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


def count_tests() -> int:
    """Число тест-методов во всех файлах tests/, без запуска unittest."""
    total = 0
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                total += sum(1 for item in node.body
                             if isinstance(item, ast.FunctionDef)
                             and item.name.startswith("test_"))
    return total


def plural_tests(count: int) -> str:
    """Согласование числительного: 1 тест, 2 теста, 5 тестов."""
    last, tens = count % 10, count % 100
    if last == 1 and tens != 11:
        return "тест"
    if 2 <= last <= 4 and not 12 <= tens <= 14:
        return "теста"
    return "тестов"


def with_test_count(text: str) -> str:
    count = count_tests()
    return re.sub(r"\b\d+ тест[аов]*", f"{count} {plural_tests(count)}", text)


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
    updated = with_test_count(f"{before}{START}\n\n{render()}\n{END}{after}")
    if "--check" in sys.argv:
        if updated != text:
            sys.exit("README устарел: запустите scripts/build_readme.py")
        print("README соответствует базе знаний и тестам")
        return
    README.write_text(updated, encoding="utf-8")
    sources = sum(1 for line in render().splitlines() if line.startswith("- **"))
    print(f"Обновлено: источников {sources}, тестов {count_tests()}")


if __name__ == "__main__":
    main()
