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


class TestFormMatchesEngine(unittest.TestCase):
    """Поле, которое читает движок, должно быть в форме, иначе его нельзя заполнить."""

    def test_every_field_the_engine_reads_is_in_the_schema(self):
        import re

        src_dir = Path(__file__).resolve().parents[1] / "src" / "animal_translator" / "species"
        for slug, kb in SPECIES.items():
            schema = {f["id"] for f in kb["input_schema"]}
            source = (src_dir / f"{slug}.py").read_text(encoding="utf-8")

            used = set(re.findall(r'(?:observation|obs)\.get\("([a-z_0-9]+)"', source))
            for const in re.findall(r'^[A-Z_]+ = \((.*?)\)', source, re.M | re.S):
                used |= set(re.findall(r'"([a-z_0-9]+)"', const))

            def walk(node):
                if isinstance(node, dict):
                    for key, value in node.items():
                        if key in ("match", "supporting") and isinstance(value, dict):
                            used.update(value)
                        else:
                            walk(value)
                elif isinstance(node, list):
                    for item in node:
                        walk(item)

            walk(kb)
            with self.subTest(slug):
                self.assertEqual(used - schema, set(), f"{slug}: движок читает поля вне формы")

    def test_schema_fields_are_well_formed(self):
        for slug, kb in SPECIES.items():
            for field in kb["input_schema"]:
                with self.subTest(slug=slug, field=field["id"]):
                    self.assertIn(field["type"], ("choice", "boolean", "number", "integer", "numbers", "text"))
                    self.assertTrue(field.get("label_ru"))
                    if field["type"] == "choice":
                        self.assertTrue(field.get("options"))


class TestNumericFieldsShowAnExample(unittest.TestCase):
    """У числового поля без примера непонятен ни порядок величины, ни формат."""

    NUMERIC = ("number", "integer", "numbers")

    def test_every_numeric_field_has_an_example(self):
        for slug, kb in SPECIES.items():
            for field in kb["input_schema"]:
                if field["type"] in self.NUMERIC:
                    with self.subTest(slug=slug, field=field["id"]):
                        self.assertTrue(field.get("example_ru"), "нет примера значения")

    def test_examples_parse_as_the_declared_type(self):
        """Пример должен быть допустимым вводом для своего поля."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
        from animal_translator.forms import parse_observation

        for slug, kb in SPECIES.items():
            for field in kb["input_schema"]:
                example = field.get("example_ru")
                if not example:
                    continue
                value = example.replace("например,", "").strip()
                with self.subTest(slug=slug, field=field["id"]):
                    parsed = parse_observation([field], {field["id"]: [value]})
                    self.assertIn(field["id"], parsed)


class TestNoParametersHiddenInCode(unittest.TestCase):
    """Правила перевода и пороги должны лежать в хранилище, а не в модулях-движках."""

    SPECIES_DIR = Path(__file__).resolve().parents[1] / "src" / "animal_translator" / "species"

    def test_engines_declare_no_numeric_module_constants(self):
        import ast

        for path in sorted(self.SPECIES_DIR.glob("*.py")):
            if path.stem == "__init__":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            offenders = []
            for node in tree.body:
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    if (isinstance(target, ast.Name) and target.id.isupper()
                            and isinstance(node.value, ast.Constant)
                            and isinstance(node.value.value, (int, float))
                            and not isinstance(node.value.value, bool)):
                        offenders.append(f"{target.id} = {node.value.value}")
            with self.subTest(path.stem):
                self.assertEqual(offenders, [], "числовой параметр вне базы знаний")

    def test_engines_do_not_duplicate_knowledge_base_text(self):
        """Утверждение о животном живёт в базе; движок его читает, а не повторяет."""
        import re

        for slug, kb in SPECIES.items():
            kb_text = json.dumps(kb, ensure_ascii=False)
            source = (self.SPECIES_DIR / f"{slug}.py").read_text(encoding="utf-8")
            body = re.sub(r'"""(?:.|\n)*?"""', "", source)
            duplicated = [q for q in re.findall(r'"([^"\n]{35,})"', body)
                          if q.strip()[:45] in kb_text]
            with self.subTest(slug):
                self.assertEqual(duplicated, [], "текст базы знаний скопирован в движок")

    def test_knowledge_base_has_no_unused_explanatory_fields(self):
        """Поле с пояснением, которое никто не читает, до пользователя не доходит."""
        import re

        sources = "".join(p.read_text(encoding="utf-8")
                          for p in (self.SPECIES_DIR.parent).rglob("*.py"))
        checked = ("surface_note_ru", "classification_limit_ru", "discriminator_ru",
                   "meaning_kind_ru", "acoustic_ru")
        for slug, kb in SPECIES.items():
            present = {k for k in checked if f'"{k}"' in json.dumps(kb, ensure_ascii=False)}
            for key in present:
                with self.subTest(slug=slug, field=key):
                    self.assertIn(f'"{key}"', sources, "поле базы не используется в коде")


class TestReadmeMatchesKnowledgeBase(unittest.TestCase):
    """Раздел «Источники» в README собирается из базы и не должен от неё отставать."""

    def test_sources_section_is_up_to_date(self):
        import subprocess

        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, str(root / "scripts" / "build_readme.py"), "--check"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_every_source_appears_in_the_readme(self):
        readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
        for slug, kb in SPECIES.items():
            for source in kb["sources"]:
                with self.subTest(slug=slug, source=source["id"]):
                    self.assertIn(source["title"], readme)

    def test_screenshots_referenced_in_readme_exist(self):
        import re

        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text(encoding="utf-8")
        for path in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", readme):
            with self.subTest(path):
                self.assertTrue((root / path).exists(), f"нет файла {path}")


class TestReadmeNumbersAreCurrent(unittest.TestCase):
    """Число тестов указано в README; оно не должно расходиться с действительным."""

    def test_declared_test_count_matches_reality(self):
        import ast
        import re

        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text(encoding="utf-8")
        declared = {int(m) for m in re.findall(r"(\d+)\s+тест[аов]*", readme)}

        actual = 0
        for path in (root / "tests").glob("test_*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    actual += sum(1 for item in node.body
                                  if isinstance(item, ast.FunctionDef)
                                  and item.name.startswith("test_"))

        self.assertEqual(declared, {actual},
                         f"README обещает {declared}, тестов на деле {actual}")
