"""Тесты JSON-интерфейса.

Часть проверок вызывает функции разбора напрямую, часть ходит через TestClient,
чтобы покрыть маршруты, коды ответов и схему OpenAPI.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from animal_translator import api  # noqa: E402
from animal_translator.app import app  # noqa: E402
from animal_translator.knowledge import load_species  # noqa: E402

client = TestClient(app)

SLUGS = api.known_slugs()


class TestApiFunctions(unittest.TestCase):
    def test_health_reports_species_count(self):
        body = api.health()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["species"], len(SLUGS))

    def test_species_list_covers_every_species(self):
        listed = {item["slug"] for item in api.species_list()["species"]}
        self.assertEqual(listed, set(SLUGS))

    def test_species_detail_carries_schema_sources_and_myths(self):
        for slug in SLUGS:
            detail = api.species_detail(slug)
            kb = load_species(slug)
            with self.subTest(slug):
                self.assertEqual(len(detail["input_schema"]), len(kb["input_schema"]))
                self.assertEqual(len(detail["sources"]), len(kb["sources"]))
                self.assertEqual(len(detail["myths"]), len(kb["myths"]))

    def test_unknown_species_is_404(self):
        with self.assertRaises(api.ApiError) as ctx:
            api.species_detail("tiger")
        self.assertEqual(ctx.exception.status, 404)

    def test_unknown_field_is_reported_by_name(self):
        with self.assertRaises(api.ApiError) as ctx:
            api.translate("dog", {"pitchh": ["low"]})
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.field, "pitchh")

    def test_unparsable_number_is_400(self):
        with self.assertRaises(api.ApiError) as ctx:
            api.translate("honeybee", {"waggle_run_duration_s": ["abc"]})
        self.assertEqual(ctx.exception.status, 400)


class TestSerialisation(unittest.TestCase):
    def test_result_is_json_serialisable(self):
        for slug in SLUGS:
            body = api.translate(slug, {})
            with self.subTest(slug):
                json.dumps(body, ensure_ascii=False)

    def test_enums_become_plain_strings(self):
        body = api.translate("spermwhale", {"signal_type": ["coda"],
                                            "inter_click_intervals_s": ["0.1, 0.1"]})
        result = body["result"]
        self.assertIsInstance(result["verdict"], str)
        self.assertEqual(result["verdict"], "no_translation_exists")
        for unknown in result["unknowns"]:
            self.assertIsInstance(unknown["kind"], str)

    def test_sources_match_the_ids_used(self):
        body = api.translate("dog", {"signal_type": ["bark"], "pitch": ["low"],
                                     "repetition": ["fast"], "tonality": ["atonal"]})
        returned = [s["id"] for s in body["sources"]]
        self.assertEqual(returned, list(dict.fromkeys(body["result"]["source_ids"])))
        for source in body["sources"]:
            self.assertTrue(source.get("doi") or source.get("url"))

    def test_get_and_post_agree(self):
        via_get = api.translate("honeybee", {"dance_type": ["waggle"],
                                             "waggle_run_duration_s": ["1.2"],
                                             "individual_calibration_known": ["yes"]})
        via_post = api.translate_from_json({
            "species": "honeybee",
            "observation": {"dance_type": "waggle", "waggle_run_duration_s": 1.2,
                            "individual_calibration_known": True},
        })
        self.assertEqual(via_get["result"], via_post["result"])
        self.assertEqual(via_get["observation"], via_post["observation"])

    def test_post_accepts_lists_of_numbers(self):
        body = api.translate_from_json({
            "species": "spermwhale",
            "observation": {"signal_type": "coda",
                            "inter_click_intervals_s": [0.12, 0.12, 0.35]},
        })
        self.assertEqual(body["observation"]["inter_click_intervals_s"], [0.12, 0.12, 0.35])

    def test_post_without_species_is_400(self):
        with self.assertRaises(api.ApiError) as ctx:
            api.translate_from_json({"observation": {}})
        self.assertEqual(ctx.exception.field, "species")


class TestOverHttp(unittest.TestCase):
    """Маршруты, коды ответов и содержимое — через TestClient."""

    def test_health(self):
        response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_species_list_is_a_list_of_summaries(self):
        body = client.get("/api/species").json()
        self.assertEqual({item["slug"] for item in body}, set(SLUGS))
        for item in body:
            self.assertIn("engine_note_ru", item)

    def test_translate_over_get(self):
        response = client.get("/api/translate", params={
            "species": "elephant", "perceived": "heard", "f0_hz": "18",
            "headshaking": "yes", "threat_present": "bees", "group_response": "retreat"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["result"]["verdict"], "translated")
        self.assertAlmostEqual(body["result"]["confidence"], 0.6)

    def test_translate_over_post(self):
        response = client.post("/api/translate", json={
            "species": "dog",
            "observation": {"signal_type": "growl", "pitch": "high", "duration": "short"}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"]["verdict"], "translated")

    def test_unknown_species_is_404_in_the_standard_shape(self):
        response = client.get("/api/species/tiger")
        self.assertEqual(response.status_code, 404)
        self.assertIn("message", response.json()["detail"])

    def test_unknown_field_is_400_and_names_the_field(self):
        response = client.get("/api/translate", params={"species": "dog", "pitchh": "low"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["field"], "pitchh")

    def test_all_errors_share_one_shape(self):
        """Ошибки разбора и ошибки валидации кладут тело в detail."""
        for request in (lambda: client.get("/api/species/tiger"),
                        lambda: client.get("/api/translate", params={"species": "dog",
                                                                     "pitchh": "low"}),
                        lambda: client.get("/api/translate")):
            response = request()
            with self.subTest(response.status_code):
                self.assertGreaterEqual(response.status_code, 400)
                self.assertIn("detail", response.json())

    def test_missing_species_is_422_by_framework_validation(self):
        response = client.get("/api/translate")
        self.assertEqual(response.status_code, 422)

    def test_broken_json_body_is_422(self):
        response = client.post("/api/translate", content=b"not json",
                               headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 422)

    def test_html_pages_still_work(self):
        for path in ("/", "/species/dog", "/species/dog/kb"):
            with self.subTest(path):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn("text/html", response.headers["content-type"])

    def test_unknown_species_page_is_404(self):
        self.assertEqual(client.get("/species/tiger").status_code, 404)


class TestOpenApiSchema(unittest.TestCase):
    """Схема генерируется фреймворком; проверяется, что она описывает заявленное поведение."""

    @classmethod
    def setUpClass(cls):
        cls.schema = client.get("/openapi.json").json()

    def test_documented_paths(self):
        self.assertEqual(set(self.schema["paths"]), {
            "/api/health", "/api/species", "/api/species/{slug}", "/api/translate"})

    def test_html_pages_are_not_in_the_schema(self):
        for path in self.schema["paths"]:
            self.assertTrue(path.startswith("/api/"))

    def test_response_models_are_described(self):
        models = self.schema["components"]["schemas"]
        for expected in ("TranslateResponse", "ResultOut", "SourceOut",
                         "SpeciesDetail", "ErrorResponse"):
            with self.subTest(expected):
                self.assertIn(expected, models)

    def test_unknown_kinds_are_enumerated_in_the_schema(self):
        kind = self.schema["components"]["schemas"]["UnknownOut"]["properties"]["kind"]
        self.assertEqual(set(kind["enum"]),
                         {"data_gap", "not_encoded", "not_applicable", "beyond_model"})

    def test_endpoints_are_grouped_by_tags(self):
        tags = {t["name"] for t in self.schema["tags"]}
        self.assertEqual(tags, {"Виды", "Разбор", "Служебное"})

    def test_interactive_docs_are_served(self):
        for path in ("/docs", "/redoc"):
            with self.subTest(path):
                self.assertEqual(client.get(path).status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
