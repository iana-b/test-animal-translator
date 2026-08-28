"""Тесты разбора сигналов кашалота.

Проверяется, что структура коды измеряется, а значение не выдаётся ни при
каком вводе, и что отказ отличается от нехватки наблюдений.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from animal_translator.knowledge import load_species  # noqa: E402
from animal_translator.result import UnknownKind, Verdict  # noqa: E402
from animal_translator.species import spermwhale  # noqa: E402

KB = load_species("spermwhale")

FULL_CODA = {
    "signal_type": "coda",
    "inter_click_intervals_s": [0.12, 0.12, 0.35, 0.12],
    "extra_final_click": True,
    "exchange_durations_s": [0.71, 0.74, 0.78, 0.80],
}


class TestRefusalIsStructural(unittest.TestCase):
    """Отказ вызван отсутствием науки, а не отсутствием данных у пользователя."""

    def test_complete_input_still_yields_no_translation(self):
        res = spermwhale.translate(FULL_CODA)
        self.assertIs(res.verdict, Verdict.NO_TRANSLATION_EXISTS)
        self.assertIsNone(res.confidence)

    def test_meaning_is_marked_not_encoded_not_a_data_gap(self):
        res = spermwhale.translate(FULL_CODA)
        meaning = next(u for u in res.unknowns if u.field_ru == "Что сказано")
        self.assertIs(meaning.kind, UnknownKind.NOT_ENCODED)
        self.assertIn("ни для одной коды", meaning.explanation_ru)

    def test_no_input_can_produce_a_meaning(self):
        """Перебор вариантов ввода: ни один не даёт содержательного перевода коды."""
        for extra in ({}, {"extra_final_click": False}, {"exchange_durations_s": [0.5, 0.5]},
                      {"inter_click_intervals_s": [0.1] * 9}, {"clan": "EC-1"}, {"context": "встреча групп"}):
            obs = {**FULL_CODA, **extra}
            with self.subTest(extra=extra):
                self.assertIs(spermwhale.translate(obs).verdict, Verdict.NO_TRANSLATION_EXISTS)

    def test_answer_quotes_the_authors_own_limitation(self):
        res = spermwhale.translate(FULL_CODA)
        self.assertTrue(any("not the semantics" in w for w in res.warnings_ru))


class TestStructureIsStillMeasured(unittest.TestCase):
    """Отказ переводить не означает пустого экрана: строение разбирается."""

    def test_all_four_features_are_reported(self):
        res = spermwhale.translate(FULL_CODA)
        labels = {s.label_ru for s in res.steps}
        for feature in KB["structure"]["features"]:
            with self.subTest(feature["id"]):
                self.assertIn(feature["label_ru"], labels)

    def test_rhythm_is_normalised_by_total_duration(self):
        res = spermwhale.translate(FULL_CODA)
        rhythm = next(s for s in res.steps if s.label_ru == "Ритм")
        self.assertIn("0.169", rhythm.value_ru)
        self.assertIn("5 щелчков", rhythm.value_ru)

    def test_rubato_needs_an_exchange_not_a_single_coda(self):
        obs = {k: v for k, v in FULL_CODA.items() if k != "exchange_durations_s"}
        res = spermwhale.translate(obs)
        rubato = next(u for u in res.unknowns if u.field_ru == "Рубато")
        self.assertIs(rubato.kind, UnknownKind.BEYOND_MODEL)

    def test_numbered_coda_types_are_not_invented(self):
        """Границы 18 ритмических типов в статье получены кластеризацией и здесь не воспроизводятся."""
        res = spermwhale.translate(FULL_CODA)
        self.assertTrue(any("не воспроизводятся" in w for w in res.warnings_ru))
        for step in res.steps:
            self.assertNotIn("тип №", step.value_ru)


class TestEcholocationIsTheOneAnswerableCase(unittest.TestCase):
    def test_usual_clicks_have_an_established_function(self):
        res = spermwhale.translate({"signal_type": "usual_clicks"})
        self.assertIs(res.verdict, Verdict.TRANSLATED)
        self.assertIn("эхолокац", res.headline_ru.lower())

    def test_function_is_distinguished_from_message_content(self):
        res = spermwhale.translate({"signal_type": "usual_clicks"})
        self.assertTrue(any("не содержание сообщения" in w for w in res.warnings_ru))

    def test_missing_signal_type_is_an_ordinary_data_gap(self):
        res = spermwhale.translate({})
        self.assertIs(res.verdict, Verdict.INSUFFICIENT)
        self.assertIs(res.unknowns[0].kind, UnknownKind.DATA_GAP)


class TestPublishedConstants(unittest.TestCase):
    def test_sample_and_inventory_match_sharma_2024(self):
        inv = KB["structure"]["inventory"]
        self.assertEqual(inv["previously_described_types"], 21)
        self.assertEqual(inv["combinations_found"], 143)

    def test_published_feature_type_counts(self):
        counts = {f["id"]: f["published_types"] for f in KB["structure"]["features"]}
        self.assertEqual(counts["rhythm"], 18)
        self.assertEqual(counts["tempo"], 5)

    def test_source_records_the_authors_stated_limit(self):
        sharma = next(s for s in KB["sources"] if s["id"] == "sharma2024")
        self.assertIn("not the semantics", sharma["authors_own_limit_ru"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
