"""Тесты запрашиваемой базы.

База производна от data/knowledge, поэтому проверяется и схема, и то, что
содержимое не разошлось с исходными файлами.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_db  # noqa: E402

KNOWLEDGE = {p.stem: json.loads(p.read_text(encoding="utf-8"))
             for p in sorted((ROOT / "data" / "knowledge").glob("*.json"))}


class DatabaseCase(unittest.TestCase):
    """База собирается во временном файле, отдельно от рабочей."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.connection = build_db.build(Path(cls._tmp.name) / "knowledge.db")
        cls.connection.row_factory = sqlite3.Row

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()
        cls._tmp.cleanup()

    def rows(self, query: str, *params):
        return self.connection.execute(query, params).fetchall()

    def scalar(self, query: str, *params):
        return self.connection.execute(query, params).fetchone()[0]


class TestSchema(DatabaseCase):
    def test_expected_tables_exist(self):
        names = {r["name"] for r in
                 self.rows("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertEqual(names, {
            "species", "sources", "myths", "myth_sources", "input_fields",
            "input_options", "contexts", "context_reliability", "confusion", "meta"})

    def test_indexes_exist(self):
        names = {r["name"] for r in
                 self.rows("SELECT name FROM sqlite_master WHERE type = 'index'")}
        for expected in ("idx_sources_year", "idx_sources_grade",
                         "idx_sources_access", "idx_confusion_predicted"):
            with self.subTest(expected):
                self.assertIn(expected, names)

    def test_foreign_keys_are_declared(self):
        for table in ("sources", "myths", "myth_sources", "input_fields",
                      "input_options", "contexts", "context_reliability", "confusion"):
            with self.subTest(table):
                self.assertTrue(self.rows(f"PRAGMA foreign_key_list({table})"))

    def test_orphan_row_is_rejected(self):
        self.connection.execute("PRAGMA foreign_keys = ON")
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "INSERT INTO sources VALUES ('tiger','x','a',2020,'t','j',NULL,NULL,"
                "'l','strong',NULL,NULL,'s','g',NULL,NULL)")
        self.connection.rollback()

    def test_evidence_grade_is_constrained(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "INSERT INTO sources VALUES ('dog','zzz','a',2020,'t','j',NULL,NULL,"
                "'l','отличная',NULL,NULL,'s','g',NULL,NULL)")
        self.connection.rollback()


class TestContentMatchesJson(DatabaseCase):
    def test_species_row_count(self):
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM species"), len(KNOWLEDGE))

    def test_every_source_is_loaded(self):
        for slug, kb in KNOWLEDGE.items():
            stored = {r["source_id"] for r in
                      self.rows("SELECT source_id FROM sources WHERE species_slug = ?", slug)}
            with self.subTest(slug):
                self.assertEqual(stored, {s["id"] for s in kb["sources"]})

    def test_open_access_is_split_into_kind_and_reference(self):
        for slug, kb in KNOWLEDGE.items():
            for source in kb["sources"]:
                row = self.rows("SELECT open_access_kind, open_access_ref FROM sources "
                                "WHERE species_slug = ? AND source_id = ?",
                                slug, source["id"])[0]
                with self.subTest(slug=slug, source=source["id"]):
                    info = source.get("open_access")
                    if info is None:
                        self.assertIsNone(row["open_access_kind"])
                    else:
                        self.assertEqual(row["open_access_kind"], info["kind"])
                        self.assertIsNotNone(row["open_access_ref"])

    def test_myths_and_their_sources_are_linked(self):
        expected = sum(len(m["source_ids"]) for kb in KNOWLEDGE.values() for m in kb["myths"])
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM myth_sources"), expected)

    def test_input_fields_keep_their_order(self):
        for slug, kb in KNOWLEDGE.items():
            ordered = [r["field_id"] for r in
                       self.rows("SELECT field_id FROM input_fields WHERE species_slug = ? "
                                 "ORDER BY position", slug)]
            with self.subTest(slug):
                self.assertEqual(ordered, [f["id"] for f in kb["input_schema"]])

    def test_confusion_matrix_is_complete(self):
        rows = KNOWLEDGE["dog"]["confusion_matrix"]["rows"]
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM confusion"),
                         sum(len(row) for row in rows.values()))

    def test_confusion_rows_still_sum_to_one(self):
        for row in self.rows("SELECT true_context, SUM(share) AS total FROM confusion "
                             "GROUP BY true_context"):
            with self.subTest(row["true_context"]):
                self.assertAlmostEqual(row["total"], 1.0, delta=0.02)

    def test_reliability_matches_the_diagonal(self):
        for row in self.rows(
                "SELECT r.context_id, r.recall, c.share FROM context_reliability r "
                "JOIN confusion c ON c.species_slug = r.species_slug "
                "AND c.true_context = r.context_id AND c.predicted_context = r.context_id"):
            with self.subTest(row["context_id"]):
                self.assertAlmostEqual(row["recall"], row["share"], places=6)


class TestDrifting(DatabaseCase):
    def test_meta_records_the_source_checksum(self):
        stored = self.scalar("SELECT value FROM meta WHERE key = 'source_checksum'")
        self.assertEqual(stored, build_db.checksum())

    def test_checksum_changes_when_knowledge_changes(self):
        path = ROOT / "data" / "knowledge" / "dog.json"
        original = path.read_bytes()
        before = build_db.checksum()
        try:
            path.write_bytes(original + b"\n")
            self.assertNotEqual(build_db.checksum(), before)
        finally:
            path.write_bytes(original)
        self.assertEqual(build_db.checksum(), before)


class TestDemoQueries(DatabaseCase):
    def test_every_documented_query_runs_and_returns_rows(self):
        for title, query in build_db.DEMO_QUERIES:
            with self.subTest(title):
                rows = self.rows(query)
                self.assertTrue(rows, "запрос из документации не вернул ни строки")

    def test_contexts_not_better_than_chance_are_the_expected_three(self):
        labels = {r["context_id"] for r in
                  self.rows("SELECT context_id FROM context_reliability "
                            "WHERE better_than_random = 0")}
        self.assertEqual(labels, {"walk", "alone", "play"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
