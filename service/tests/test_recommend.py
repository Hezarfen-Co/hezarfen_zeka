"""`compute.recommend` testleri: kanıtsız tavsiye üretilmez, kim ne görür."""

from __future__ import annotations

import unittest

from src.compute import recommend
from src.compute.model import (
    Audience,
    AttentionItem,
    Band,
    Confidence,
    Recommendation,
    TriggerKind,
)

NOW = 1_700_000_000_000
DAY = 86_400_000


def marks_profile(band: Band = Band.REVIEW) -> dict:
    return {
        "limitation": "Konu kırılımı yok.",
        "courses": {
            "course-1": {
                "course_title": "Matematik",
                "n_marks": 6,
                "average": 45.0,
                "trend": {"available": True, "dropped": False},
                "placement": {
                    "band": band,
                    "confidence": Confidence.STABLE,
                    "z": -1.4,
                    "class_average": 68.0,
                    "class_sd": 12.0,
                    "cohort_n": 14,
                },
            }
        },
    }


def study_profile(n_stints: int = 12) -> dict:
    return {
        "limitation": "Ders bağı yok.",
        "streak_local": 3,
        "change": {"active_days_delta": 2},
        "recent_28d": {
            "n_stints": n_stints,
            "active_days": 9,
            "regularity": 9 / 28,
            "burstiness": 2.0,
            "bursty": False,
            "median_stint_ms": 1_500_000,
        },
    }


def submission_profile(upcoming: list[dict] | None = None) -> dict:
    return {
        "limitation": "counted_on_time yok.",
        "upcoming": upcoming or [],
    }


def build(**kw):
    args = {
        "marks_profile": marks_profile(),
        "attendance_profile": {"overall": {}},
        "submission_profile": submission_profile(),
        "study_profile": study_profile(),
        "attention_items": [],
        "course_teachers": {"course-1": ["teacher-1"]},
        "now_ms": NOW,
    }
    args.update(kw)
    return recommend.for_student("okul", "student-1", **args)


class TestEvidenceIsMandatory(unittest.TestCase):
    def test_empty_evidence_raises(self) -> None:
        """Kanıtsız tavsiye **kurulamaz** — assert değil, tip kısıtı."""
        with self.assertRaises(ValueError):
            Recommendation(
                school="okul",
                audience="a",
                audience_role=Audience.STUDENT,
                product="O1",
                rule_id="O1.review_band",
                evidence={},
                computed_at=NOW,
                expires_at=NOW + DAY,
                limitation="x",
            )

    def test_empty_limitation_raises(self) -> None:
        """'Neden?' beşinci bölümü (Sınır) zorunlu (`[T§6.3]`)."""
        with self.assertRaises(ValueError):
            Recommendation(
                school="okul",
                audience="a",
                audience_role=Audience.STUDENT,
                product="O1",
                rule_id="O1.review_band",
                evidence={"n": 1},
                computed_at=NOW,
                expires_at=NOW + DAY,
                limitation="",
            )

    def test_empty_rule_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            Recommendation(
                school="okul",
                audience="a",
                audience_role=Audience.STUDENT,
                product="O1",
                rule_id="",
                evidence={"n": 1},
                computed_at=NOW,
                expires_at=NOW + DAY,
                limitation="x",
            )

    def test_every_generated_recommendation_is_explainable(self) -> None:
        items = [
            AttentionItem(
                "student-1",
                TriggerKind.ATTENDANCE,
                "Katılım oranı %70.",
                {"rate": 0.70, "limitation": "Dönem kümülatifi."},
                NOW - 30 * DAY,
                NOW,
            )
        ]
        recs = build(attention_items=items)
        self.assertTrue(recs)
        for rec in recs:
            self.assertTrue(rec.evidence, rec.rule_id)
            self.assertTrue(rec.limitation, rec.rule_id)
            self.assertTrue(rec.rule_id)
            self.assertGreaterEqual(rec.rule_version, 1)
            self.assertEqual(rec.computed_at, NOW)
            self.assertGreater(rec.expires_at, rec.computed_at)
            self.assertIn("rule", {**rec.evidence, "rule": 1})


class TestStudentRules(unittest.TestCase):
    def test_review_band_produces_o1(self) -> None:
        recs = [r for r in build() if r.rule_id == "O1.review_band"]
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].audience_role, Audience.STUDENT)
        self.assertEqual(recs[0].evidence["cohort_n"], 14)

    def test_insufficient_data_produces_nothing(self) -> None:
        """Güven kapısı devralınır: sinyali olmayan ürün kendini gizler."""
        recs = build(marks_profile=marks_profile(Band.INSUFFICIENT_DATA))
        self.assertEqual([r for r in recs if r.product == "O1"], [])

    def test_on_track_produces_no_o1(self) -> None:
        recs = build(marks_profile=marks_profile(Band.ON_TRACK))
        self.assertEqual([r for r in recs if r.product == "O1"], [])

    def test_study_pattern_gate(self) -> None:
        self.assertTrue([r for r in build() if r.rule_id == "O3.pattern"])
        recs = build(study_profile=study_profile(n_stints=4))
        self.assertEqual([r for r in recs if r.rule_id == "O3.pattern"], [])

    def test_deadline_rule_only_inside_reminder_window(self) -> None:
        near = {
            "homework": "h1",
            "course": "course-1",
            "title": "Ödev",
            "due_at": NOW + 6 * 3_600_000,
            "remind_at": NOW - 18 * 3_600_000,
            "submitted": False,
            "high_priority": True,
            "hours_left": 6.0,
        }
        far = {**near, "homework": "h2", "remind_at": NOW + DAY, "due_at": NOW + 3 * DAY}
        recs = build(submission_profile=submission_profile([near, far]))
        deadline = [r for r in recs if r.rule_id == "O4.deadline"]
        self.assertEqual(len(deadline), 1)
        self.assertEqual(deadline[0].evidence["homework"], "h1")
        self.assertEqual(deadline[0].expires_at, near["due_at"])


class TestTeacherRules(unittest.TestCase):
    def _items(self) -> list[AttentionItem]:
        return [
            AttentionItem(
                "student-1",
                TriggerKind.MARK_TREND,
                "Fizik dersinde son 3 not ortalaması 45.",
                {"course": "course-1", "limitation": "Sıralama ULID'e göre."},
                NOW - 30 * DAY,
                NOW,
            )
        ]

    def test_t4_goes_only_to_teachers(self) -> None:
        """`[T§6.8]`: dikkat listesi öğrenciye ve veliye GÖSTERİLMEZ."""
        recs = [r for r in build(attention_items=self._items()) if r.product == "T4"]
        self.assertTrue(recs)
        for rec in recs:
            self.assertEqual(rec.audience_role, Audience.TEACHER)
            self.assertNotEqual(rec.audience, "student-1")
            self.assertEqual(rec.about, "student-1")

    def test_t4_expires_in_thirty_days(self) -> None:
        recs = [r for r in build(attention_items=self._items()) if r.product == "T4"]
        self.assertEqual(recs[0].expires_at, NOW + 30 * DAY)

    def test_no_recommendation_when_teacher_unknown(self) -> None:
        """Alıcısı çözülemeyen tetikleyici yayınlanmaz — yetki genişletilmez."""
        recs = build(attention_items=self._items(), course_teachers={})
        self.assertEqual([r for r in recs if r.product in ("T3", "T4")], [])

    def test_t3_individual_gap_when_class_is_fine(self) -> None:
        recs = [r for r in build() if r.product == "T3"]
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].rule_id, "T3.individual_gap")

    def test_t3_class_gap_when_class_is_low(self) -> None:
        profile = marks_profile()
        profile["courses"]["course-1"]["placement"]["class_average"] = 42.0
        recs = [r for r in build(marks_profile=profile) if r.product == "T3"]
        self.assertEqual(recs[0].rule_id, "T3.class_gap")


class TestCatalogHonesty(unittest.TestCase):
    def test_unavailable_rules_are_declared(self) -> None:
        blocked = recommend.unavailable_rules()
        for rule_id in ("O2.retry_item", "T1.hard_item", "T2.key_suspect",
                        "V1.weekly_digest", "Y1.ungraded_exam", "T4.exam_missed"):
            self.assertIn(rule_id, blocked)
            self.assertTrue(blocked[rule_id])

    def test_catalog_and_blocked_lists_do_not_overlap(self) -> None:
        self.assertEqual(
            set(recommend.RULE_CATALOG) & set(recommend.unavailable_rules()), set()
        )

    def test_no_rule_id_outside_catalog_is_emitted(self) -> None:
        recs = build(
            attention_items=[
                AttentionItem(
                    "student-1",
                    TriggerKind.HOMEWORK,
                    "Son 30 günde 4 ödev teslim edilmedi.",
                    {"n_missing_30d": 4, "limitation": "last_touch"},
                    NOW - 30 * DAY,
                    NOW,
                )
            ]
        )
        for rec in recs:
            self.assertIn(rec.rule_id, recommend.RULE_CATALOG)

    def test_record_key_is_composite_and_idempotent(self) -> None:
        first = build()
        second = build()
        self.assertEqual(
            [r.record_key() for r in first], [r.record_key() for r in second]
        )
        self.assertEqual(len({r.record_key() for r in first}), len(first))


if __name__ == "__main__":
    unittest.main()
