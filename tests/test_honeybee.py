"""Тесты декодера пчелы.

Проверяют не «код не падает», а что арифметика совпадает с опубликованной
моделью и что три вида неизвестности не смешиваются между собой.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from animal_translator.knowledge import load_species  # noqa: E402
from animal_translator.result import UnknownKind, Verdict  # noqa: E402
from animal_translator.species import honeybee  # noqa: E402

KB = load_species("honeybee")


class TestDistanceModel(unittest.TestCase):
    def test_published_equations_invert_correctly(self):
        """Пробег 1.2 с → 636 м по обращённому уравнению ближнего сегмента."""
        est = honeybee.estimate_distance(KB, 1.2)
        self.assertIsNotNone(est)
        self.assertAlmostEqual(est.metres, 636, delta=1)

    def test_segments_meet_at_breakpoint(self):
        """Оба уравнения дают одно расстояние в точке перелома — модель непрерывна."""
        model = KB["quantitative_model"]["distance"]
        bp_duration = model["breakpoint_duration_s"]
        est = honeybee.estimate_distance(KB, bp_duration)
        self.assertAlmostEqual(est.metres / 1000, model["breakpoint_km"], places=2)

    def test_far_segment_used_above_breakpoint(self):
        """За переломом наклон меньше, поэтому та же прибавка времени даёт больший прирост дистанции."""
        near = honeybee.estimate_distance(KB, 1.5)
        far = honeybee.estimate_distance(KB, 2.0)
        near_gain = honeybee.estimate_distance(KB, 1.6).metres - near.metres
        far_gain = honeybee.estimate_distance(KB, 2.1).metres - far.metres
        self.assertGreater(far_gain, near_gain)

    def test_relative_precision_improves_with_distance(self):
        """Следствие модели: у ближних ресурсов относительная точность заметно хуже."""
        near = honeybee.estimate_distance(KB, 0.5)
        far = honeybee.estimate_distance(KB, 2.0)
        self.assertGreater(near.sigma_metres / near.metres, far.sigma_metres / far.metres)

    def test_duration_below_intercept_refused(self):
        self.assertIsNone(honeybee.estimate_distance(KB, 0.2))


class TestDirection(unittest.TestCase):
    def test_bearing_from_sun_azimuth(self):
        res = honeybee.translate(
            {"dance_type": "waggle", "waggle_run_duration_s": 1.2,
             "angle_from_vertical_deg": 40, "sun_azimuth_deg": 180}
        )
        step = next(s for s in res.steps if "аправление" in s.label_ru)
        self.assertIn("220°", step.value_ru)
        self.assertIn("ЮЗ", step.value_ru)

    def test_missing_angle_is_a_data_gap(self):
        res = honeybee.translate({"dance_type": "waggle", "waggle_run_duration_s": 1.2})
        gap = next(u for u in res.unknowns if u.field_ru == "Направление")
        self.assertIs(gap.kind, UnknownKind.DATA_GAP)
        self.assertIs(res.verdict, Verdict.PARTIAL)

    def test_horizontal_surface_makes_angle_inapplicable(self):
        res = honeybee.translate(
            {"dance_type": "waggle", "waggle_run_duration_s": 1.2,
             "angle_from_vertical_deg": 40, "dance_surface": "horizontal"}
        )
        gap = next(u for u in res.unknowns if u.field_ru == "Направление")
        self.assertIs(gap.kind, UnknownKind.NOT_APPLICABLE)


class TestThreeKindsOfUnknown(unittest.TestCase):
    """Ядро честности: «я не знаю» и «этого в сигнале нет» — разные ответы."""

    def test_round_dance_direction_is_beyond_the_model_not_absent(self):
        """Классическое «направления там нет» опровергнуто Griffin et al. 2012:
        направление есть, но наша модель его не покрывает — это разные вещи."""
        res = honeybee.translate({"dance_type": "round"})
        gap = next(u for u in res.unknowns if u.field_ru == "Направление")
        self.assertIs(gap.kind, UnknownKind.BEYOND_MODEL)

    def test_tremble_carries_no_vector_at_all(self):
        res = honeybee.translate({"dance_type": "tremble"})
        self.assertIs(res.verdict, Verdict.TRANSLATED)
        self.assertIsNone(res.confidence)
        self.assertIs(res.unknowns[0].kind, UnknownKind.NOT_ENCODED)

    def test_missing_duration_is_insufficient_not_a_guess(self):
        res = honeybee.translate({"dance_type": "waggle"})
        self.assertIs(res.verdict, Verdict.INSUFFICIENT)
        self.assertIsNone(res.confidence)


class TestConfidence(unittest.TestCase):
    def _full(self, **over):
        obs = {"dance_type": "waggle", "waggle_run_duration_s": 1.2,
               "angle_from_vertical_deg": 40, "sun_azimuth_deg": 180,
               "n_waggle_runs_measured": 4, "individual_calibration_known": True}
        obs.update(over)
        return honeybee.translate(obs)

    def test_never_exceeds_species_cap(self):
        self.assertLessEqual(self._full().confidence, KB["confidence_cap"])

    def test_fewer_runs_lowers_confidence(self):
        self.assertLess(self._full(n_waggle_runs_measured=1).confidence, self._full().confidence)

    def test_extrapolation_lowers_confidence(self):
        self.assertLess(self._full(waggle_run_duration_s=2.6).confidence, self._full().confidence)

    def test_unknown_calibration_lowers_confidence_and_warns(self):
        res = self._full(individual_calibration_known=False)
        self.assertLess(res.confidence, self._full().confidence)
        self.assertTrue(any("систематическое смещение" in w for w in res.warnings_ru))


class TestKnowledgeBaseIntegrity(unittest.TestCase):
    def test_every_referenced_source_exists(self):
        known = {s["id"] for s in KB["sources"]}
        referenced = set()
        for rule in KB["rules"]:
            referenced.update(rule["source_ids"])
        for myth in KB["myths"]:
            referenced.update(myth["source_ids"])
        referenced.add(KB["quantitative_model"]["distance"]["source_id"])
        referenced.add(KB["quantitative_model"]["direction"]["source_id"])
        self.assertEqual(referenced - known, set())

    def test_every_source_has_a_verifiable_link(self):
        for s in KB["sources"]:
            self.assertTrue(s.get("doi") or s.get("url"), f"{s['id']} без ссылки")

    def test_every_coefficient_declares_where_it_came_from(self):
        """Каждое число — либо из статьи, либо явно помечено как эвристика."""
        factors = KB["confidence_model"]["factors"]
        for name, factor in factors.items():
            self.assertIn(factor["derivation"]["kind"], ("source", "heuristic"), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestConfidenceScope(unittest.TestCase):
    """Процент без указания, к чему он относится, вводит в заблуждение."""

    def test_scope_says_distance_only_when_direction_missing(self):
        res = honeybee.translate({"dance_type": "waggle", "waggle_run_duration_s": 0.6})
        self.assertIn("только к расстоянию", res.confidence_scope_ru)

    def test_scope_covers_whole_vector_when_direction_known(self):
        res = honeybee.translate(
            {"dance_type": "waggle", "waggle_run_duration_s": 1.2,
             "angle_from_vertical_deg": 40, "sun_azimuth_deg": 180}
        )
        self.assertIn("вектору целиком", res.confidence_scope_ru)
