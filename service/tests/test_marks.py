"""`compute.marks` birim testleri: ortalama, eğilim, kohort bandı, güven kapısı."""

from __future__ import annotations

import unittest

from src.compute import marks
from src.compute.model import Band, Confidence

from .fakes import course_marks, mark_entry, profile

BASE = 1_700_000_000_000
DAY = 86_400_000


class TestCourseAverage(unittest.TestCase):
    def test_weighted_average(self) -> None:
        results = [
            mark_entry(BASE, 80, weight=1),
            mark_entry(BASE + DAY, 60, weight=3),
        ]
        # (80*1 + 60*3) / 4 = 65
        self.assertAlmostEqual(marks.course_average(results), 65.0)

    def test_missing_marks_are_dropped(self) -> None:
        results = [mark_entry(BASE, 80), {"exam": "x", "mark": None, "weight": 1}]
        self.assertAlmostEqual(marks.course_average(results), 80.0)

    def test_no_weight_means_none(self) -> None:
        self.assertIsNone(marks.course_average([]))


class TestTrend(unittest.TestCase):
    def _results(self, values: list[int], step: int = DAY) -> list[dict]:
        return [mark_entry(BASE + i * step, v) for i, v in enumerate(values)]

    def test_gate_blocks_short_history(self) -> None:
        """6 nottan az → eğilim hesaplanmaz (yeni öğrenci korunur)."""
        trend = marks.course_trend(self._results([70, 70, 70, 50, 50]))
        self.assertFalse(trend["available"])
        self.assertIsNone(trend["delta"])
        self.assertFalse(trend["dropped"])

    def test_drop_of_20_points_fires(self) -> None:
        trend = marks.course_trend(self._results([70, 70, 70, 50, 50, 50]))
        self.assertTrue(trend["available"])
        self.assertAlmostEqual(trend["previous_mean"], 70.0)
        self.assertAlmostEqual(trend["recent_mean"], 50.0)
        self.assertAlmostEqual(trend["delta"], -20.0)
        self.assertTrue(trend["dropped"])

    def test_drop_of_10_points_does_not_fire(self) -> None:
        """Eşik 15 puandır (`MODULLER.md` §2.8 tetikleyici 3)."""
        trend = marks.course_trend(self._results([70, 70, 70, 60, 60, 60]))
        self.assertAlmostEqual(trend["delta"], -10.0)
        self.assertFalse(trend["dropped"])

    def test_rising_student_is_not_flagged(self) -> None:
        """A5 (yükselen) yanlış-pozitif kontrolü — `[N§3.2]`."""
        # 2 günlük adım → 10 gün yayılım: eğim kapısı (`MIN_SPAN_DAYS_FOR_SLOPE`)
        # geçilir ve `slope_per_30d` üretilir.
        trend = marks.course_trend(self._results([40, 42, 45, 68, 70, 72], step=2 * DAY))
        self.assertGreater(trend["delta"], 0)
        self.assertFalse(trend["dropped"])
        self.assertGreater(trend["slope_per_30d"], 0)

    def test_short_span_suppresses_slope_with_its_own_reason(self) -> None:
        """Notlar dakikalar içinde oluşturulduysa eğim ekstrapole EDİLMEZ.

        Canlı kusur: tohumdaki sınavların `exam` kimlikleri neredeyse aynı
        anda damgalıydı, ama eğim 30 güne doğrusal taşınıyordu ve öğrenci
        "30 günlük değişim -2.460,7 puan / 30 gün" okuyordu. 6-not kuralı ve
        ortalama farkları KORUNUR; yalnız eğim bastırılır ve sebebi söylenir.
        """
        results = [
            mark_entry(BASE + i * 60_000, v) for i, v in enumerate([70, 70, 70, 50, 50, 50])
        ]
        trend = marks.course_trend(results)
        self.assertTrue(trend["available"])  # ≥6 not kuralı değişmedi
        self.assertIsNone(trend["slope_per_30d"])
        # 5 × 60 sn = 5/1440 gün.
        self.assertAlmostEqual(trend["span_days"], 5.0 / (24 * 60))
        self.assertEqual(
            trend["reason"],
            "eğilim eğimi için notların en az 7 güne yayılması gerekir",
        )
        # Ortalama farkları her yayılımda dürüsttür — bastırılmaz.
        self.assertAlmostEqual(trend["previous_mean"], 70.0)
        self.assertAlmostEqual(trend["recent_mean"], 50.0)
        self.assertAlmostEqual(trend["delta"], -20.0)
        self.assertTrue(trend["dropped"])
        self.assertFalse(trend["rising"])

    def test_long_span_reports_slope_and_its_span(self) -> None:
        """≥7 güne yayılan dizi eğimi üretir; span her durumda raporlanır."""
        # 2 günlük adım → 10 gün yayılım (≥ 7).
        results = [
            mark_entry(BASE + i * 2 * DAY, v) for i, v in enumerate([70, 70, 70, 50, 50, 50])
        ]
        trend = marks.course_trend(results)
        self.assertTrue(trend["available"])
        self.assertEqual(trend["span_days"], 10.0)
        self.assertIsNone(trend["reason"])
        # Gün başına eğim = Σ d·y / Σ d² = −180/70; 30 güne çevrilince ×30.
        self.assertAlmostEqual(trend["slope_per_30d"], (-180.0 / 70.0) * 30.0)

    def test_order_comes_from_ulid_not_list_order(self) -> None:
        """Liste karışık gelse bile sıralama ULID damgasından kurulur."""
        ordered = self._results([70, 70, 70, 50, 50, 50])
        shuffled = [ordered[3], ordered[0], ordered[5], ordered[1], ordered[4], ordered[2]]
        self.assertAlmostEqual(marks.course_trend(shuffled)["delta"], -20.0)


class TestPlacement(unittest.TestCase):
    def test_review_band(self) -> None:
        dist = {"mean": 70.0, "sd": 10.0, "n": 12, "usable": True, "homogeneous": False}
        placement = marks.place_in_cohort(50.0, 6, dist)
        self.assertAlmostEqual(placement["z"], -2.0)
        self.assertEqual(placement["band"], Band.REVIEW)
        self.assertEqual(placement["confidence"], Confidence.STABLE)

    def test_on_track_and_strong(self) -> None:
        dist = {"mean": 70.0, "sd": 10.0, "n": 12, "usable": True, "homogeneous": False}
        self.assertEqual(marks.place_in_cohort(72.0, 6, dist)["band"], Band.ON_TRACK)
        self.assertEqual(marks.place_in_cohort(85.0, 6, dist)["band"], Band.STRONG)

    def test_gate_few_marks_shows_no_band(self) -> None:
        """GÜVEN KAPISI: 3 nottan az → bant gösterilmez, ilerleme gösterilir."""
        dist = {"mean": 70.0, "sd": 10.0, "n": 12, "usable": True, "homogeneous": False}
        placement = marks.place_in_cohort(10.0, 2, dist)
        self.assertEqual(placement["band"], Band.INSUFFICIENT_DATA)
        self.assertIsNone(placement["z"])
        self.assertEqual(placement["progress"], "2/3")

    def test_gate_small_cohort_does_not_pool_upwards(self) -> None:
        """GÜVEN KAPISI: kohort 8'den küçükse üst kırılıma ÇIKILMAZ ([L-6])."""
        dist = {"mean": 70.0, "sd": 10.0, "n": 5, "usable": False, "homogeneous": False}
        placement = marks.place_in_cohort(50.0, 6, dist)
        self.assertEqual(placement["band"], Band.INSUFFICIENT_DATA)
        self.assertIsNone(placement["z"])
        self.assertIsNone(placement["class_average"])

    def test_no_cohort_at_all(self) -> None:
        placement = marks.place_in_cohort(50.0, 6, None)
        self.assertEqual(placement["band"], Band.INSUFFICIENT_DATA)

    def test_homogeneous_cohort_downgrades_confidence(self) -> None:
        dist = {"mean": 70.0, "sd": 0.2, "n": 12, "usable": True, "homogeneous": True}
        placement = marks.place_in_cohort(69.0, 6, dist)
        self.assertEqual(placement["confidence"], Confidence.EXPLORATORY)


class TestCohortConstruction(unittest.TestCase):
    def test_cohort_is_class_by_course_not_school_wide(self) -> None:
        """Aynı ders, iki farklı şube → iki AYRI kohort ([L-6], §0 kural 2)."""
        per_student = {
            f"s{i}": (
                ["class-A" if i < 10 else "class-B"],
                {"course-1": {"average": 90.0 if i < 10 else 40.0, "n_marks": 6}},
            )
            for i in range(20)
        }
        buckets = marks.collect_cohort_samples(per_student)
        self.assertEqual(sorted(buckets), ["class-A|course-1", "class-B|course-1"])
        dists = marks.cohort_distributions(buckets)
        self.assertAlmostEqual(dists["class-A|course-1"]["mean"], 90.0)
        self.assertAlmostEqual(dists["class-B|course-1"]["mean"], 40.0)

    def test_marks_below_gate_do_not_enter_cohort(self) -> None:
        per_student = {"s1": (["class-A"], {"c1": {"average": 50.0, "n_marks": 2}})}
        self.assertEqual(marks.collect_cohort_samples(per_student), {})


class TestStudentProfile(unittest.TestCase):
    def test_end_to_end_band_and_limitation(self) -> None:
        rows = [course_marks("course-1", [40, 42, 44, 41, 43, 40], BASE)]
        prof = profile("student-1", ["class-A"], ["course-1"])
        dists = {
            "class-A|course-1": {
                "mean": 70.0,
                "sd": 10.0,
                "n": 12,
                "usable": True,
                "homogeneous": False,
            }
        }
        result = marks.student_profile(rows, prof, dists)
        placement = result["courses"]["course-1"]["placement"]
        self.assertEqual(placement["band"], Band.REVIEW)
        # Sınır satırı her zaman dolu ("Neden?" beşinci bölümü, `[T§6.3]`).
        self.assertTrue(result["limitation"])

    def test_without_cohort_no_band_is_produced(self) -> None:
        rows = [course_marks("course-1", [40, 42, 44, 41, 43, 40], BASE)]
        prof = profile("student-1", ["class-A"], ["course-1"])
        result = marks.student_profile(rows, prof, None)
        self.assertEqual(
            result["courses"]["course-1"]["placement"]["band"],
            Band.INSUFFICIENT_DATA,
        )

    def test_course_teachers_resolved(self) -> None:
        rows = [course_marks("course-1", [50], BASE, teachers=["t1", "t2"])]
        self.assertEqual(marks.course_teachers(rows), {"course-1": ["t1", "t2"]})


if __name__ == "__main__":
    unittest.main()
