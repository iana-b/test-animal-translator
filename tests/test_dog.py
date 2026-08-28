"""Тесты разбора сигналов собаки.

Проверяется расчёт распределения по контекстам и поведение на входных данных,
для которых опубликованные исследования не дают различения.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from animal_translator.knowledge import load_species  # noqa: E402
from animal_translator.result import UnknownKind, Verdict  # noqa: E402
from animal_translator.species import dog  # noqa: E402

KB = load_species("dog")


def bark(**over):
    obs = {"signal_type": "bark"}
    obs.update(over)
    return dog.translate(obs)


class TestConfusionMatrix(unittest.TestCase):
    def test_rows_are_probability_distributions(self):
        for ctx, row in KB["confusion_matrix"]["rows"].items():
            self.assertAlmostEqual(sum(row.values()), 1.0, delta=0.02, msg=ctx)

    def test_posterior_sums_to_one(self):
        posterior, _ = dog._posterior(KB, ["fight", "stranger"], {})
        self.assertAlmostEqual(sum(posterior.values()), 1.0, places=6)

    def test_matrix_covers_every_context(self):
        ids = {c["id"] for c in KB["contexts"]}
        self.assertEqual(set(KB["confusion_matrix"]["rows"]), ids)
        for row in KB["confusion_matrix"]["rows"].values():
            self.assertEqual(set(row), ids)


class TestHonestRefusal(unittest.TestCase):
    """Поведение, когда акустика контекст не определяет."""

    def test_sound_alone_does_not_reach_the_threshold(self):
        res = bark(pitch="low", repetition="fast", tonality="atonal")
        self.assertIs(res.verdict, Verdict.INSUFFICIENT)
        self.assertLess(res.confidence, KB["decision_rules"]["refusal_threshold"])

    def test_refusal_still_shows_the_reasoning(self):
        res = bark(pitch="low", repetition="fast", tonality="atonal")
        self.assertTrue(any("Распределение" in s.label_ru for s in res.steps))
        self.assertTrue(res.alternatives_ru)

    def test_context_not_separable_by_sound_is_flagged(self):
        """Контекст «одна» распознаётся не лучше случайного; ответ должен это сообщать."""
        res = bark(pitch="high", repetition="slow", tonality="tonal")
        self.assertIs(res.verdict, Verdict.PARTIAL)
        self.assertTrue(any("не отличалось от случайного" in w for w in res.warnings_ru))


class TestEvidenceSharpensTheAnswer(unittest.TestCase):
    def test_reported_situation_raises_confidence(self):
        without = bark(pitch="low", repetition="fast", tonality="atonal")
        with_ctx = bark(pitch="low", repetition="fast", tonality="atonal", reported_situation="stranger")
        self.assertGreater(with_ctx.confidence, without.confidence)
        self.assertIs(with_ctx.verdict, Verdict.TRANSLATED)

    def test_play_bow_shifts_towards_play_contexts(self):
        without = bark(pitch="high", repetition="slow", tonality="atonal")
        with_bow = bark(pitch="high", repetition="slow", tonality="atonal", play_bow=True)
        self.assertGreater(with_bow.confidence, without.confidence)

    def test_missing_tonality_widens_the_candidate_set(self):
        res = bark(pitch="high", repetition="slow")
        gap = next(u for u in res.unknowns if u.field_ru == "Тональность")
        self.assertIs(gap.kind, UnknownKind.DATA_GAP)
        self.assertIn("Оставлена одна", next(s.value_ru for s in res.steps if "Кандидаты" in s.label_ru))

    def test_missing_core_features_is_a_data_gap(self):
        res = bark(tonality="tonal")
        self.assertIs(res.verdict, Verdict.INSUFFICIENT)
        self.assertIs(res.unknowns[0].kind, UnknownKind.DATA_GAP)


class TestGrowls(unittest.TestCase):
    def test_play_growl_is_separable(self):
        res = dog.translate({"signal_type": "growl", "pitch": "high", "duration": "short"})
        self.assertIs(res.verdict, Verdict.TRANSLATED)
        self.assertFalse(res.unknowns)

    def test_agonistic_growl_cannot_be_split_by_sound(self):
        res = dog.translate({"signal_type": "growl", "pitch": "low", "duration": "long"})
        self.assertIs(res.verdict, Verdict.PARTIAL)
        self.assertIs(res.unknowns[0].kind, UnknownKind.NOT_ENCODED)


class TestOutOfScopeSignals(unittest.TestCase):
    def test_howl_has_no_model_in_this_knowledge_base(self):
        res = dog.translate({"signal_type": "howl"})
        self.assertIs(res.verdict, Verdict.NO_TRANSLATION_EXISTS)
        self.assertIs(res.unknowns[0].kind, UnknownKind.BEYOND_MODEL)

    def test_unknown_combination_is_beyond_the_model(self):
        res = bark(pitch="low", repetition="slow", tonality="tonal")
        self.assertIs(res.unknowns[0].kind, UnknownKind.BEYOND_MODEL)


class TestConfidenceBounds(unittest.TestCase):
    def test_confidence_stays_a_probability(self):
        for obs in (
            {"pitch": "low", "repetition": "fast", "tonality": "atonal", "reported_situation": "fight"},
            {"pitch": "high", "repetition": "slow", "tonality": "atonal", "play_bow": True,
             "reported_situation": "play"},
        ):
            res = bark(**obs)
            self.assertGreaterEqual(res.confidence, 0.0)
            self.assertLessEqual(res.confidence, 1.0)

    def test_dog_can_never_be_as_certain_as_the_bee(self):
        """Верхняя граница задана путаницей между контекстами, а не настройкой движка."""
        best = bark(pitch="low", repetition="fast", tonality="atonal", reported_situation="fight")
        self.assertLess(best.confidence, 0.80)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestPublishedConstants(unittest.TestCase):
    """Величины из Molnár et al. 2008 зафиксированы, включая внутреннюю согласованность."""

    def test_headline_numbers_match_the_paper(self):
        r = KB["reliability"]
        self.assertAlmostEqual(r["overall_accuracy"], 0.43)
        self.assertAlmostEqual(r["random_baseline"], 0.18)
        self.assertAlmostEqual(r["overall_kappa"], 0.30)
        self.assertAlmostEqual(r["individual_recognition"], 0.52)

    def test_diagonal_of_the_matrix_equals_per_context_recall(self):
        """Доля правильных ответов записана в двух местах — они обязаны совпадать."""
        rows = KB["confusion_matrix"]["rows"]
        for ctx, stats in KB["reliability"]["per_context"].items():
            with self.subTest(ctx):
                self.assertAlmostEqual(rows[ctx][ctx], stats["recall"], places=6)

    def test_context_sample_sizes_match_the_paper(self):
        expected = {"play": 742, "fight": 1118, "alone": 752, "stranger": 1802, "walk": 1231, "ball": 1001}
        self.assertEqual({c["id"]: c["n"] for c in KB["contexts"]}, expected)
        self.assertEqual(sum(expected.values()), 6646)

    def test_only_three_contexts_beat_chance(self):
        beats = {c for c, s in KB["reliability"]["per_context"].items() if s["better_than_random"]}
        self.assertEqual(beats, {"fight", "stranger", "ball"})

    def test_play_kappa_is_negative(self):
        self.assertLess(KB["reliability"]["per_context"]["play"]["kappa"], 0)
