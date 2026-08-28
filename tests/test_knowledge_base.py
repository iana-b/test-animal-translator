"""Проверки, общие для всех видов.

Применяются к каждому файлу в data/knowledge.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from animal_translator.knowledge import KNOWLEDGE_DIR  # noqa: E402

SPECIES = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(KNOWLEDGE_DIR.glob("*.json"))}


class TestEverySpeciesFile(unittest.TestCase):
    def test_at_least_one_species_is_loaded(self):
        self.assertTrue(SPECIES, "в data/knowledge не найдено ни одного вида")

    def test_required_fields_present(self):
        for slug, kb in SPECIES.items():
            with self.subTest(slug):
                for field in ("slug", "name_ru", "scientific_name", "engine", "sources", "myths"):
                    self.assertIn(field, kb)
                self.assertEqual(kb["slug"], slug)

    def test_every_source_is_checkable(self):
        """У источника должен быть DOI или ссылка."""
        for slug, kb in SPECIES.items():
            for s in kb["sources"]:
                with self.subTest(slug=slug, source=s["id"]):
                    self.assertTrue(s.get("doi") or s.get("url"))
                    self.assertTrue(s.get("authors") and s.get("year") and s.get("title"))
                    self.assertIn(s.get("evidence_grade"), ("strong", "moderate", "limited"))
                    self.assertTrue(s.get("licence"), "не указано, что можно делать с источником")

    def test_source_ids_are_unique(self):
        for slug, kb in SPECIES.items():
            ids = [s["id"] for s in kb["sources"]]
            with self.subTest(slug):
                self.assertEqual(len(ids), len(set(ids)))

    def test_no_dangling_source_references(self):
        """Все идентификаторы источников внутри файла должны существовать."""
        for slug, kb in SPECIES.items():
            known = {s["id"] for s in kb["sources"]}
            referenced: set[str] = set()

            def walk(node):
                if isinstance(node, dict):
                    for key, value in node.items():
                        if key == "source_ids" and isinstance(value, list):
                            referenced.update(value)
                        elif key.endswith("source_id") and isinstance(value, str):
                            referenced.add(value)
                        else:
                            walk(value)
                elif isinstance(node, list):
                    for item in node:
                        walk(item)

            walk(kb)
            with self.subTest(slug):
                self.assertEqual(referenced - known, set())

    def test_every_myth_is_backed_by_a_source(self):
        for slug, kb in SPECIES.items():
            for myth in kb["myths"]:
                with self.subTest(slug=slug, myth=myth["claim_ru"][:40]):
                    self.assertTrue(myth["source_ids"])

    def test_every_coefficient_declares_its_origin(self):
        """Каждый коэффициент указывает происхождение: источник или эвристика."""
        found = []

        def walk(node, path=""):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k.endswith("derivation") and isinstance(v, dict):
                        found.append((f"{path}.{k}", v))
                    else:
                        walk(v, f"{path}.{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{path}[{i}]")

        for slug, kb in SPECIES.items():
            found.clear()
            walk(kb, slug)
            with self.subTest(slug):
                self.assertTrue(found, f"{slug}: ни один коэффициент не объявляет происхождение")
                for path, d in found:
                    self.assertIn(d.get("kind"), ("source", "heuristic"), path)
                    if d["kind"] == "heuristic":
                        self.assertTrue(d.get("rationale_ru"), f"{path}: эвристика без объяснения")
                    else:
                        self.assertTrue(d.get("where_ru") or d.get("source_id"), f"{path}: не сказано, откуда")


class TestSpeciesDifferByDesign(unittest.TestCase):
    """Разбор у разных видов устроен по-разному."""

    def test_engines_are_distinct(self):
        engines = [kb["engine"] for kb in SPECIES.values()]
        self.assertEqual(len(engines), len(set(engines)))

    def test_each_species_explains_why_its_logic_differs(self):
        for slug, kb in SPECIES.items():
            with self.subTest(slug):
                self.assertTrue(kb.get("engine_note_ru"))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestNoDecorativeBibliography(unittest.TestCase):
    """Источник, на который ничто не ссылается, ничего не подкрепляет."""

    def test_every_source_is_actually_used(self):
        for slug, kb in SPECIES.items():
            referenced: set[str] = set()

            def walk(node):
                if isinstance(node, dict):
                    for key, value in node.items():
                        if key == "source_ids" and isinstance(value, list):
                            referenced.update(value)
                        elif key.endswith("source_id") and isinstance(value, str):
                            referenced.add(value)
                        else:
                            walk(value)
                elif isinstance(node, list):
                    for item in node:
                        walk(item)

            walk(kb)
            unused = {s["id"] for s in kb["sources"]} - referenced
            with self.subTest(slug):
                self.assertEqual(unused, set(), f"{slug}: источники не используются: {sorted(unused)}")
