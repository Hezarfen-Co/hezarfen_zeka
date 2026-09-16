"""`compute.attention` testleri.

En kritik iddialar burada sabitlenir:
* **tek skor üretilmez**, **sıralama yapılmaz**;
* kolektif olay bireysel uyarı üretmez;
* geçmişi olmayan öğrenci işaretlenemez;
* dönem başında ürün kapalıdır;
* dördüncü tetikleyici (sınav kaçırma) ateşlenemez ve bu **raporlanır**.
"""

from __future__ import annotations

import dataclasses
import unittest

from src.compute import attention
from src.compute.model import AttentionItem, TriggerKind

DAY = 86_400_000
NOW = 1_700_000_000_000
TERM_START = NOW - 120 * DAY  # soğuk başlangıç penceresinin dışında


def attendance_profile(rate: float | None, gap: float | None, n_obs: int = 40) -> dict:
    return {"overall": {"rate": rate, "relative_gap": gap, "n_obs": n_obs}}


# Şube kimliği + kohort — ödev tetikleyicisi artık kohort-göreli çalışır
# (kusur K1). Kohortsuz çağrıda madde **hiç** üretilmez; bu bilinçli bir
# fail-closed'dır ve aşağıda ayrı bir testle sabitlenir.
CLASS_ID = "class_group:test"
# Şubenin medyan eksik ödev oranı %10. Eşik bunun iki katı → %20.
COHORT = {CLASS_ID: 0.10}


def submission_profile(
    *,
    n_total: int = 20,
    missing_30: int = 0,
    on_time_now: float | None = None,
    on_time_prev: float | None = None,
    n_30: int = 10,
    n_prev: int = 10,
    missing_prev: int = 0,
) -> dict:
    """`submission.student_profile()` çıktısının test karşılığı.

    `missing_rate` alanı gerçek modülde `n >= MIN_OBSERVATIONS` kapısının
    ardında üretilir; burada aynı sözleşme elle kurulur.
    """

    def rate(missing: int, n: int) -> float | None:
        return (missing / n) if n >= 5 else None

    return {
        "overall": {"n": n_total},
        "recent_30d": {
            "n": n_30,
            "n_missing": missing_30,
            "missing_rate": rate(missing_30, n_30),
            "on_time_rate_by_last_touch": on_time_now,
        },
        "previous_30d": {
            "n": n_prev,
            "n_missing": missing_prev,
            "missing_rate": rate(missing_prev, n_prev),
            "on_time_rate_by_last_touch": on_time_prev,
        },
    }


def marks_profile(dropped_course: str | None = None) -> dict:
    courses: dict[str, dict] = {
        "course-1": {
            "course_title": "Matematik",
            "trend": {"available": False, "dropped": False},
        }
    }
    if dropped_course:
        courses[dropped_course] = {
            "course_title": "Fizik",
            "trend": {
                "available": True,
                "dropped": True,
                "recent_mean": 45.0,
                "previous_mean": 68.0,
                "delta": -23.0,
                "n": 6,
            },
        }
    return {"classes": [CLASS_ID], "courses": courses}


def evaluate(**kw):
    args = {
        "attendance_profile": attendance_profile(None, None),
        "submission_profile": submission_profile(),
        "marks_profile": marks_profile(),
        "now_ms": NOW,
        "term_start_ms": TERM_START,
        "submission_cohort": COHORT,
    }
    args.update(kw)
    return attention.evaluate("student-1", **args)


class TestNoScoreNoRanking(unittest.TestCase):
    def test_item_type_has_no_score_field(self) -> None:
        """TEK SKOR YOK: tipte `score`/`rank`/`severity`/`weight` alanı bulunmaz."""
        names = {f.name for f in dataclasses.fields(AttentionItem)}
        for forbidden in ("score", "rank", "severity", "weight", "priority", "total"):
            self.assertNotIn(forbidden, names)

    def test_output_carries_no_aggregate(self) -> None:
        items = evaluate(attendance_profile=attendance_profile(0.70, -0.15))
        self.assertEqual(len(items), 1)
        for key in ("score", "rank", "severity", "total"):
            self.assertNotIn(key, items[0].evidence)

    def test_each_item_is_exactly_one_trigger(self) -> None:
        items = evaluate(
            attendance_profile=attendance_profile(0.70, -0.15),
            submission_profile=submission_profile(missing_30=4, n_30=10),
            marks_profile=marks_profile("course-2"),
        )
        self.assertEqual(len(items), 3)
        self.assertEqual(len({i.trigger for i in items}), 3)

    def test_ordering_is_alphabetical_not_by_severity(self) -> None:
        """SIRALAMA YOK — alfabetik sabit (`[T§6.6]` madde 2)."""
        raw = [
            AttentionItem("zeynep", TriggerKind.MARK_TREND, "olgu", {"a": 1}, 0, 1),
            AttentionItem("ahmet", TriggerKind.HOMEWORK, "olgu", {"a": 1}, 0, 1),
            AttentionItem("ahmet", TriggerKind.ATTENDANCE, "olgu", {"a": 1}, 0, 1),
        ]
        ordered = attention.order_items(raw)
        self.assertEqual(
            [(i.student, i.trigger.value) for i in ordered],
            [("ahmet", "attendance"), ("ahmet", "homework"), ("zeynep", "mark_trend")],
        )


class TestEvidenceRequired(unittest.TestCase):
    def test_item_without_evidence_cannot_exist(self) -> None:
        with self.assertRaises(ValueError):
            AttentionItem("s", TriggerKind.HOMEWORK, "olgu", {}, 0, 1)

    def test_every_produced_item_carries_evidence(self) -> None:
        items = evaluate(
            attendance_profile=attendance_profile(0.70, -0.15),
            submission_profile=submission_profile(missing_30=4, n_30=10),
            marks_profile=marks_profile("course-2"),
        )
        for item in items:
            self.assertTrue(item.evidence)
            self.assertIn("limitation", item.evidence)


class TestAttendanceTrigger(unittest.TestCase):
    def test_fires_when_low_and_below_cohort(self) -> None:
        items = evaluate(attendance_profile=attendance_profile(0.70, -0.15))
        self.assertEqual([i.trigger for i in items], [TriggerKind.ATTENDANCE])

    def test_does_not_fire_when_whole_cohort_dropped(self) -> None:
        """P26: grip haftası nedeniyle bireysel uyarı = 0."""
        items = evaluate(attendance_profile=attendance_profile(0.70, 0.0))
        self.assertEqual(items, [])

    def test_does_not_fire_without_cohort(self) -> None:
        items = evaluate(attendance_profile=attendance_profile(0.70, None))
        self.assertEqual(items, [])

    def test_does_not_fire_above_rate_threshold(self) -> None:
        items = evaluate(attendance_profile=attendance_profile(0.85, -0.15))
        self.assertEqual(items, [])


class TestHomeworkTrigger(unittest.TestCase):
    """Kohort-göreli seviye **VE** koruyucu değişim (kusur K1/K2 düzeltmesi).

    Eşik artık mutlak bir sayı değil: şube medyanının `MISSING_COHORT_FACTOR`
    katı. Aşağıdaki fikstürde şube medyanı %10, yani eşik %20.
    """

    def test_twice_the_cohort_median_fires(self) -> None:
        # 10 ödevde 3 eksik = %30 ≥ 2 × %10.
        items = evaluate(submission_profile=submission_profile(missing_30=3))
        self.assertEqual([i.trigger for i in items], [TriggerKind.HOMEWORK])
        self.assertEqual(items[0].evidence["rule_basis"], attention.BASIS_LEVEL)
        self.assertAlmostEqual(
            items[0].evidence["cohort_missing_rate_median"], 0.10
        )

    def test_at_the_cohort_median_does_not_fire(self) -> None:
        # 10 ödevde 1 eksik = %10 = şube ortancası → madde yok.
        items = evaluate(submission_profile=submission_profile(missing_30=1))
        self.assertEqual(items, [])

    def test_absolute_count_alone_is_not_a_threshold(self) -> None:
        """Aynı **sayı**, farklı ödev yoğunluğunda farklı sonuç vermeli.

        Kusur K1 tam olarak buydu: 3 eksik, 20 ödevlik bir okulda da 6 ödevlik
        bir okulda da aynı şeyi söylüyordu.
        """
        az_odev = evaluate(submission_profile=submission_profile(missing_30=3, n_30=6))
        cok_odev = evaluate(
            submission_profile=submission_profile(missing_30=3, n_30=40)
        )
        self.assertEqual([i.trigger for i in az_odev], [TriggerKind.HOMEWORK])
        self.assertEqual(cok_odev, [])

    def test_improving_student_is_protected(self) -> None:
        """Koruyucu değişim kuralı: eşiği geçse bile iyileşen listelenmez."""
        items = evaluate(
            submission_profile=submission_profile(
                missing_30=3, n_30=10, missing_prev=6, n_prev=10
            )
        )
        self.assertEqual(items, [])

    def test_on_time_improvement_also_protects(self) -> None:
        items = evaluate(
            submission_profile=submission_profile(
                missing_30=3, n_30=10, on_time_prev=0.40, on_time_now=0.55
            )
        )
        self.assertEqual(items, [])

    def test_worsening_fires_at_cohort_median(self) -> None:
        """Değişim yolu: %60 → %50 altı düşüş, eksik oran ≥ şube ortancası."""
        items = evaluate(
            submission_profile=submission_profile(
                missing_30=1, n_30=10, on_time_prev=0.75, on_time_now=0.40
            )
        )
        self.assertEqual([i.trigger for i in items], [TriggerKind.HOMEWORK])
        self.assertEqual(items[0].evidence["rule_basis"], attention.BASIS_CHANGE)

    def test_worsening_below_cohort_median_does_not_fire(self) -> None:
        """Şubesinden hâlâ iyi durumdaki öğrenci, kötüleşse de listelenmez."""
        items = evaluate(
            submission_profile=submission_profile(
                missing_30=0, n_30=10, on_time_prev=0.75, on_time_now=0.40
            )
        )
        self.assertEqual(items, [])

    def test_drop_needs_a_previous_window(self) -> None:
        items = evaluate(
            submission_profile=submission_profile(
                missing_30=1, n_30=10, on_time_prev=None, on_time_now=0.40
            )
        )
        self.assertEqual(items, [])

    def test_without_cohort_it_never_fires(self) -> None:
        """Fail-closed: kohort bilinmeden mutlak eşiğe düşülmez."""
        items = evaluate(
            submission_profile=submission_profile(missing_30=9, n_30=10),
            submission_cohort=None,
        )
        self.assertEqual(items, [])

    def test_small_cohort_is_not_pooled_upward(self) -> None:
        """`COHORT_MIN` altındaki şube kohort üretmez, okul havuzuna çıkılmaz."""
        cohort = attention.submission_cohort_medians(
            {
                f"s{i}": ([CLASS_ID], submission_profile(missing_30=i, n_30=10))
                for i in range(attention.COHORT_MIN - 1)
            }
        )
        self.assertEqual(cohort, {})

    def test_cohort_median_is_built_per_class(self) -> None:
        cohort = attention.submission_cohort_medians(
            {
                f"s{i}": ([CLASS_ID], submission_profile(missing_30=2, n_30=10))
                for i in range(attention.COHORT_MIN)
            }
        )
        self.assertAlmostEqual(cohort[CLASS_ID], 0.20)


class TestMarkTrendTrigger(unittest.TestCase):
    def test_fires_per_course(self) -> None:
        items = evaluate(marks_profile=marks_profile("course-2"))
        self.assertEqual([i.trigger for i in items], [TriggerKind.MARK_TREND])
        self.assertEqual(items[0].evidence["course"], "course-2")

    def test_language_is_factual_not_judgemental(self) -> None:
        """`[T§6.6]` madde 1: madde bir olgu cümlesidir; 'risk' geçmez."""
        items = evaluate(
            attendance_profile=attendance_profile(0.70, -0.15),
            submission_profile=submission_profile(missing_30=4, n_30=10),
            marks_profile=marks_profile("course-2"),
        )
        for item in items:
            lowered = item.fact.lower()
            for word in ("risk", "zayıf", "başarısız", "tembel"):
                self.assertNotIn(word, lowered, item.fact)


class TestGuards(unittest.TestCase):
    def test_cold_start_closes_the_product(self) -> None:
        """Dönem başlangıcından < 4 hafta → ürün kapalı (`[T§3 T4]`)."""
        items = evaluate(
            attendance_profile=attendance_profile(0.50, -0.40),
            submission_profile=submission_profile(missing_30=9, n_30=10),
            term_start_ms=NOW - 7 * DAY,
        )
        self.assertEqual(items, [])

    def test_unknown_term_start_fails_closed(self) -> None:
        items = evaluate(
            attendance_profile=attendance_profile(0.50, -0.40), term_start_ms=None
        )
        self.assertEqual(items, [])

    def test_new_student_is_never_flagged(self) -> None:
        """P25 = 0: geçmişi olmayan öğrenci işaretlenemez."""
        items = evaluate(
            attendance_profile=attendance_profile(0.50, -0.40),
            submission_profile=submission_profile(n_total=2, missing_30=9, n_30=10),
        )
        self.assertEqual(items, [])


class TestRisingProtection(unittest.TestCase):
    """A5 koruması — yükselen öğrenci tek seviye maddesiyle listelenmez."""

    @staticmethod
    def _rising_marks() -> dict:
        trend = {
            "available": True,
            "dropped": False,
            "rising": True,
            "recent_mean": 78.0,
            "previous_mean": 58.0,
            "delta": 20.0,
            "slope_per_30d": 7.0,
            "n": 6,
        }
        return {
            "classes": [CLASS_ID],
            "courses": {
                "course-1": {"course_title": "Matematik", "trend": dict(trend)},
                "course-2": {"course_title": "Fizik", "trend": dict(trend)},
            },
        }

    def test_single_level_item_is_suppressed_for_rising_student(self) -> None:
        items = evaluate(
            attendance_profile=attendance_profile(0.70, -0.15),
            marks_profile=self._rising_marks(),
        )
        self.assertEqual(items, [])

    def test_two_level_items_are_not_suppressed(self) -> None:
        """İki bağımsız tetikleyici tek bir eşiğin gürültüsü değildir."""
        items = evaluate(
            attendance_profile=attendance_profile(0.70, -0.15),
            submission_profile=submission_profile(missing_30=3, n_30=10),
            marks_profile=self._rising_marks(),
        )
        self.assertEqual(len(items), 2)

    def test_change_based_item_is_never_suppressed(self) -> None:
        marks = self._rising_marks()
        items = evaluate(
            submission_profile=submission_profile(
                missing_30=1, n_30=10, on_time_prev=0.75, on_time_now=0.40
            ),
            marks_profile=marks,
        )
        self.assertEqual([i.trigger for i in items], [TriggerKind.HOMEWORK])
        self.assertEqual(items[0].evidence["rule_basis"], attention.BASIS_CHANGE)

    def test_is_rising_requires_majority_and_no_drop(self) -> None:
        marks = self._rising_marks()
        self.assertTrue(attention.is_rising(marks))
        marks["courses"]["course-2"]["trend"]["dropped"] = True
        marks["courses"]["course-2"]["trend"]["rising"] = False
        self.assertFalse(attention.is_rising(marks))

    def test_is_rising_is_false_without_any_trend(self) -> None:
        self.assertFalse(attention.is_rising(marks_profile()))


class TestUnavailableTrigger(unittest.TestCase):
    def test_exam_missed_is_reported_as_unavailable(self) -> None:
        """Yarım liste sessizce gösterilmez (`MODULLER.md` §2.8)."""
        reasons = attention.unavailable_triggers()
        self.assertIn(TriggerKind.EXAM_MISSED.value, reasons)
        self.assertTrue(reasons[TriggerKind.EXAM_MISSED.value])

    def test_exam_missed_never_fires(self) -> None:
        items = evaluate(
            attendance_profile=attendance_profile(0.70, -0.15),
            submission_profile=submission_profile(missing_30=4, n_30=10),
            marks_profile=marks_profile("course-2"),
        )
        self.assertNotIn(TriggerKind.EXAM_MISSED, {i.trigger for i in items})


if __name__ == "__main__":
    unittest.main()
