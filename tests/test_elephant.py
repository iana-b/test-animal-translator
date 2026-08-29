"""Тесты разбора сигналов слона.

Проверяется порядок уровней доказательности и то, что трактовка, известная
только по контексту, не занимает место проверенной проигрыванием.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from animal_translator.knowledge import load_species  # noqa: E402
from animal_translator.result import UnknownKind, Verdict  # noqa: E402
from animal_translator.species import elephant  # noqa: E402

KB = load_species("elephant")


class TestEvidenceTiers(unittest.TestCase):
    def test_tiers_are_strictly_ordered(self):
        ranks = [t["rank"] for t in KB["evidence_tiers"]["levels"]]
        self.assertEqual(len(ranks), len(set(ranks)))
        self.assertEqual(ranks, sorted(ranks, reverse=True))

    def test_every_signal_declares_a_known_tier(self):
        known = {t["id"] for t in KB["evidence_tiers"]["levels"]}
        for s in KB["signals"]:
            with self.subTest(s["id"]):
                self.assertIn(s["evidence_tier"], known)

    def test_contextual_signal_cannot_outrank_a_verified_one(self):
        """Оба описания подходят под наблюдение — выбрана проверенная проигрыванием."""
        res = elephant.translate({
            "headshaking": True, "threat_present": "bees",
            "group_response": "coordinated_departure", "f0_hz": 18,
        })
        self.assertIn("Пчёлы", res.headline_ru)
        self.assertTrue(any("не могут вытеснить" in w for w in res.warnings_ru))

    def test_contextual_answer_is_marked_partial(self):
        res = elephant.translate({"group_response": "coordinated_departure", "f0_hz": 17})
        self.assertIs(res.verdict, Verdict.PARTIAL)
        self.assertEqual(res.confidence_level_ru, "только связь с контекстом")
        self.assertTrue(any("проигрыванием не проверяли" in w or "не проигрывали" in w for w in res.warnings_ru))


class TestAlarmTypes(unittest.TestCase):
    """Тряска головой — единственный поведенческий разделитель двух тревог."""

    def test_headshaking_selects_the_bee_alarm(self):
        res = elephant.translate({"headshaking": True, "threat_present": "bees",
                                  "group_response": "retreat", "f0_hz": 18})
        self.assertIn("Пчёлы", res.headline_ru)

    def test_absence_of_headshaking_with_humans_selects_the_human_alarm(self):
        res = elephant.translate({"headshaking": False, "threat_present": "humans",
                                  "group_response": "retreat", "f0_hz": 19})
        self.assertIn("Люди", res.headline_ru)

    def test_bee_alarm_confidence_is_the_measured_playback_rate(self):
        res = elephant.translate({"headshaking": True, "threat_present": "bees",
                                  "group_response": "retreat", "f0_hz": 18})
        playback = next(s["playback_response"] for s in KB["signals"] if s["id"] == "bee_alarm")
        self.assertAlmostEqual(res.confidence, playback["retreated"] / playback["of_trials"])
        self.assertIn("проиграли запись", res.confidence_scope_ru)

    def test_playback_rate_is_not_labelled_on_the_plausibility_scale(self):
        """Доля отклика и правдоподобие трактовки — разные величины, шкала не общая."""
        res = elephant.translate({"headshaking": True, "threat_present": "bees",
                                  "group_response": "retreat", "f0_hz": 18})
        self.assertEqual(res.confidence_level_ru, "проверено проигрыванием")
        self.assertNotIn(res.confidence_level_ru, ("низкая", "средняя", "высокая"))


class TestInfrasound(unittest.TestCase):
    def test_hearing_only_observation_is_flagged_as_incomplete(self):
        res = elephant.translate({"reunion": True, "perceived": "heard"})
        gap = next(u for u in res.unknowns if u.field_ru == "Основная частота")
        self.assertIs(gap.kind, UnknownKind.DATA_GAP)

    def test_measured_frequency_removes_the_flag(self):
        res = elephant.translate({"reunion": True, "perceived": "heard", "f0_hz": 18})
        self.assertFalse([u for u in res.unknowns if u.field_ru == "Основная частота"])

    def test_nothing_perceived_is_refused(self):
        res = elephant.translate({"perceived": "not_perceived"})
        self.assertIs(res.verdict, Verdict.INSUFFICIENT)
        self.assertIsNone(res.confidence)

    def test_published_frequency_range_matches_poole_1988(self):
        h = KB["human_hearing"]
        self.assertEqual(h["f0_range_hz"], [14, 35])
        self.assertEqual(h["human_hearing_floor_hz"], 20)


class TestPublishedConstants(unittest.TestCase):
    def test_bee_playback_numbers_match_king_2010(self):
        p = next(s["playback_response"] for s in KB["signals"] if s["id"] == "bee_alarm")
        self.assertEqual((p["retreated"], p["of_trials"]), (6, 10))
        self.assertEqual((p["control_retreated"], p["control_of_trials"]), (2, 10))

    def test_paper_with_a_published_correction_records_it(self):
        """У Pardo 2024 есть опубликованная поправка — она должна быть в записи источника."""
        pardo = next(s for s in KB["sources"] if s["id"] == "pardo2024")
        self.assertIn("correction", pardo)
        self.assertTrue(pardo["correction"]["doi"])
        self.assertTrue(pardo["correction"]["what_ru"])


class TestNoMatch(unittest.TestCase):
    def test_unmatched_observation_is_refused(self):
        res = elephant.translate({"f0_hz": 18, "group_response": "no_change"})
        self.assertIs(res.verdict, Verdict.INSUFFICIENT)
        self.assertIs(res.unknowns[0].kind, UnknownKind.DATA_GAP)


if __name__ == "__main__":
    unittest.main(verbosity=2)
