"""Тесты декодера пчелы.

Проверяется совпадение расчёта с опубликованной моделью и разграничение
причин, по которым значение остаётся неопределённым.
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
        """У ближних ресурсов относительная точность оценки хуже."""
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


class TestKindsOfUnknown(unittest.TestCase):
    """Разграничение причин, по которым значение не определено."""

    def test_round_dance_direction_is_beyond_the_model_not_absent(self):
        """Griffin et al. 2012: направление в круговом танце есть,
        но модель расстояния его не покрывает."""
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


class TestConfidenceScope(unittest.TestCase):
    """Уверенность сопровождается указанием, к чему именно она относится."""

    def test_scope_says_distance_only_when_direction_missing(self):
        res = honeybee.translate({"dance_type": "waggle", "waggle_run_duration_s": 0.6})
        self.assertIn("только к расстоянию", res.confidence_scope_ru)

    def test_scope_covers_whole_vector_when_direction_known(self):
        res = honeybee.translate(
            {"dance_type": "waggle", "waggle_run_duration_s": 1.2,
             "angle_from_vertical_deg": 40, "sun_azimuth_deg": 180}
        )
        self.assertIn("вектору целиком", res.confidence_scope_ru)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestPublishedConstants(unittest.TestCase):
    """Величины, взятые из статей, зафиксированы: правка в базе знаний должна ронять тест."""

    def test_distance_model_matches_kohl_rutschmann_2021(self):
        model = KB["quantitative_model"]["distance"]
        near, far = model["forward_equations"]
        self.assertAlmostEqual(near["intercept_s"], 0.2917)
        self.assertAlmostEqual(near["slope_s_per_km"], 1.4282)
        self.assertAlmostEqual(far["intercept_s"], 1.0767)
        self.assertAlmostEqual(far["slope_s_per_km"], 0.6683)
        self.assertAlmostEqual(model["breakpoint_km"], 1.0328)
        self.assertAlmostEqual(model["r_squared"], 0.947)
        self.assertEqual(model["calibrated_range_km"], [0.1, 1.7])
        self.assertEqual(model["calibrated_range_duration_s"], [0.41, 2.20])

    def test_standard_deviations_match_the_published_anchor_points(self):
        sd = KB["quantitative_model"]["distance"]["sd_model"]
        self.assertAlmostEqual(sd["sd_at_100m_s"], 0.10)
        self.assertAlmostEqual(sd["sd_at_1700m_s"], 0.19)
        self.assertAlmostEqual(honeybee._sd_for_distance(KB, 0.1), 0.10, places=6)
        self.assertAlmostEqual(honeybee._sd_for_distance(KB, 1.7), 0.19, places=6)

    def test_angular_error_matches_okada_2014(self):
        direction = KB["quantitative_model"]["direction"]
        self.assertEqual(direction["angular_error_deg"], 15)
        self.assertAlmostEqual(direction["angular_error_coverage"], 0.85)

    def test_individual_calibration_risk_matches_schurch_2016(self):
        risk = KB["quantitative_model"]["distance"]["individual_calibration_risk"]
        self.assertAlmostEqual(risk["systematic_bias_fraction"], 0.5)


class TestUncertaintyPropagation(unittest.TestCase):
    def test_absolute_uncertainty_grows_with_distance(self):
        near = honeybee.estimate_distance(KB, 0.6)
        far = honeybee.estimate_distance(KB, 2.0)
        self.assertGreater(far.sigma_metres, near.sigma_metres)

    def test_direction_corridor_width_equals_twice_the_published_error(self):
        err = KB["quantitative_model"]["direction"]["angular_error_deg"]
        res = honeybee.translate(
            {"dance_type": "waggle", "waggle_run_duration_s": 1.2,
             "angle_from_vertical_deg": 40, "sun_azimuth_deg": 180}
        )
        step = next(s for s in res.steps if "омпасное" in s.label_ru)
        self.assertIn(f"{220 - err:.0f}–{220 + err:.0f}°", step.value_ru)


class TestAchievableConfidence(unittest.TestCase):
    """Верхняя граница уверенности названа в README; она должна совпадать с расчётом."""

    def _best(self, with_direction: bool) -> float:
        best = 0.0
        for duration in (0.5, 0.6, 1.0, 1.2, 1.8, 2.1):
            for runs in (1, 2, 4, 8):
                for calibrated in (True, False):
                    observation = {"dance_type": "waggle",
                                   "waggle_run_duration_s": duration,
                                   "n_waggle_runs_measured": runs,
                                   "individual_calibration_known": calibrated}
                    if with_direction:
                        observation |= {"angle_from_vertical_deg": 40, "sun_azimuth_deg": 180}
                    result = honeybee.translate(observation)
                    if result.confidence:
                        best = max(best, result.confidence)
        return best

    def test_distance_only_tops_out_at_the_model_fit(self):
        r_squared = KB["quantitative_model"]["distance"]["r_squared"]
        self.assertAlmostEqual(self._best(with_direction=False), r_squared, places=6)

    def test_whole_vector_is_bounded_by_the_direction_corridor(self):
        coverage = KB["confidence_model"]["factors"]["direction_confidence"]["value"]
        self.assertAlmostEqual(self._best(with_direction=True), coverage, places=6)

    def test_species_cap_never_binds(self):
        """Потолок вида выше достижимого максимума, поэтому ограничивает R², а не он."""
        self.assertGreater(KB["confidence_cap"],
                           KB["quantitative_model"]["distance"]["r_squared"])
