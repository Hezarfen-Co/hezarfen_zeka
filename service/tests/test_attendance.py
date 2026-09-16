"""`compute.attendance` birim testleri: oran formülü, güven kapısı, kohort."""

from __future__ import annotations

import unittest

from src.compute import attendance

from .fakes import course_attendance


class TestRateFormula(unittest.TestCase):
    def test_excused_is_excluded_from_both_sides(self) -> None:
        """`rate = (present + late) / (present + absent + late)`.

        Raporlu devamsızlık bir disiplin sinyali değildir
        (`MODULLER.md` §2.5 adım 1).
        """
        rate, denom = attendance.rate_of(
            {"present": 8, "absent": 1, "late": 1, "excused": 5}
        )
        self.assertEqual(denom, 10)
        self.assertAlmostEqual(rate, 0.9)

    def test_custom_statuses_do_not_enter_denominator(self) -> None:
        rate, denom = attendance.rate_of(
            {"present": 9, "absent": 1, "late": 0, "custom": {"gezi": 20}}
        )
        self.assertEqual(denom, 10)
        self.assertAlmostEqual(rate, 0.9)

    def test_zero_denominator_is_none_not_zero(self) -> None:
        rate, denom = attendance.rate_of({"excused": 4})
        self.assertEqual(denom, 0)
        self.assertIsNone(rate)


class TestConfidenceGate(unittest.TestCase):
    def test_gate_suppresses_rate_below_ten_observations(self) -> None:
        """GÜVEN KAPISI: 10 gözlemin altında oran GÖSTERİLMEZ."""
        rows = [course_attendance("c1", present=8, absent=1)]  # payda 9
        stats = attendance.course_stats(rows)
        self.assertTrue(stats["c1"]["rate_suppressed"])
        self.assertIsNone(stats["c1"]["rate"])

    def test_gate_opens_at_ten(self) -> None:
        rows = [course_attendance("c1", present=9, absent=1)]
        stats = attendance.course_stats(rows)
        self.assertFalse(stats["c1"]["rate_suppressed"])
        self.assertAlmostEqual(stats["c1"]["rate"], 0.9)


class TestCohort(unittest.TestCase):
    def _profile(self, own_rate: tuple[int, int], others: list[tuple[int, int]]):
        """Öğrenci + kohort kurar, profili döndürür."""
        per_student: dict[str, tuple[list[str], dict]] = {}
        for i, (present, absent) in enumerate(others):
            stats = attendance.course_stats(
                [course_attendance("c1", present=present, absent=absent)]
            )
            per_student[f"other-{i}"] = (["class-A"], stats)
        medians = attendance.cohort_medians(
            attendance.collect_cohort_samples(per_student)
        )
        rows = [course_attendance("c1", present=own_rate[0], absent=own_rate[1])]
        return attendance.student_profile(rows, ["class-A"], medians)

    def test_relative_gap_against_cohort_median(self) -> None:
        others = [(95, 5)] * 10  # kohort medyanı 0,95
        result = self._profile((70, 30), others)
        course = result["courses"]["c1"]
        self.assertAlmostEqual(course["cohort_median"], 0.95)
        self.assertAlmostEqual(course["relative_gap"], -0.25)

    def test_collective_event_produces_no_individual_gap(self) -> None:
        """GRİP HAFTASI TESTİ (`[N§7.5]` P26 = 0).

        Herkesin devamı birlikte düştüğünde göreli fark ~0 kalır; mutlak eşik
        burada onlarca yanlış pozitif üretirdi.
        """
        others = [(70, 30)] * 10  # tüm kohort düşük
        result = self._profile((70, 30), others)
        course = result["courses"]["c1"]
        self.assertAlmostEqual(course["relative_gap"], 0.0)
        self.assertLess(course["rate"], attendance.ATTENTION_RATE)
        # Oran eşiği geçse bile göreli fark tetikleyiciyi ateşlemez.
        self.assertGreater(course["relative_gap"], attendance.ATTENTION_RELATIVE_GAP)

    def test_small_cohort_yields_no_relative_measure(self) -> None:
        """GÜVEN KAPISI: kohort 8'den küçük → göreli ölçü YOK, mutlağa düşülmez."""
        others = [(95, 5)] * 5
        result = self._profile((70, 30), others)
        course = result["courses"]["c1"]
        self.assertIsNone(course["relative_gap"])
        self.assertIsNone(course["cohort_median"])


class TestUnavailableMeasures(unittest.TestCase):
    def test_weekday_pattern_is_declared_unavailable(self) -> None:
        """Sahte sayı üretilmez; yokluk gerekçesiyle taşınır."""
        result = attendance.student_profile([], [], {})
        self.assertIsNone(result["weekday_pattern"])
        self.assertIn("tarih", result["weekday_pattern_reason"])

    def test_trend_is_declared_unavailable(self) -> None:
        result = attendance.student_profile([], [], {})
        self.assertFalse(result["trend"]["available"])
        self.assertIsNone(result["trend"]["delta"])


if __name__ == "__main__":
    unittest.main()
