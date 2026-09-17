"""Köprü deposunun sözleşme testleri: `insight.*` çağrılarının şekli.

ZEKA'nın kendi veritabanı yoktur; yazdığı her satır `hezarfen_backend`'e bir
yetenek çağrısıyla gider. Bu dosya o sözleşmeyi sabitler:

1. **Dokuz operasyonun her biri** doğru yetenek adıyla, doğru çerçeve okuluyla
   ve beklenen payload anahtarlarıyla çağrılır. Satır değerleri GERÇEK hesap
   tiplerinden (`StudentSummary`, `Recommendation`, `QuestionSegment`,
   `StudentSegmentProfile`) türetilir; elle kurulmuş sözlüklerden değil.
2. **Grup bölme**: `BATCH_SIZE`'i aşan yazım 500 + kalan diye gider.
3. **Yeniden deneme sonra atlama**: iki denemesi de düşen grup `skipped_batches`
   olarak görünür ve rapor `partial` olur — düşen çağrı asla başarı sayılmaz.
4. **Boş mezuniyet listesi**: çağrı YAPILMAZ ("liste çekilemedi" herkesin
   verisini silerdi) ve `False` döner.
5. **Okul çerçevededir**: `insight.schools.list` dışında her çağrı okulu
   taşır, `insight.schools.list` ise okulsuz (`school == ""`) gider.
"""

from __future__ import annotations

import unittest

from src.compute import clock
from src.compute.model import (
    Audience,
    Confidence,
    QuestionSegment,
    Recommendation,
    StudentSegmentProfile,
    StudentSummary,
)
from src.store import (
    BATCH_SIZE,
    CAP_PENDING,
    CAP_PROFILE,
    CAP_PURGE,
    CAP_RECOMMENDATION,
    CAP_RUN,
    CAP_SCHOOLS,
    CAP_SEGMENT,
    CAP_SWEEP,
    CAP_SUMMARY,
    PURGE_TABLES,
    RETENTION_DAYS,
    SWEEP_TABLES,
    BridgeStore,
    BridgeUnavailable,
    RecordingCaller,
)

from .fakes import ReplyingCaller

DAY = clock.DAY_MS
NOW = 1_699_963_200_000  # 2023-11-14 12:00 UTC
SCHOOL = "okul-a"


def make_summary(student: str, *, now_ms: int = NOW) -> StudentSummary:
    return StudentSummary(
        school=SCHOOL,
        student=student,
        computed_at=now_ms,
        marks={"courses": {"course-1": {"placement": {"band": "review"}}}},
        attendance={"courses": {"course-1": {"present": 60, "absent": 40}}},
        submission={"window_days": 30, "missed": 4},
        study={"sessions": 6},
        attention=[
            {
                "trigger": "homework",
                "fact": "son 30 günde 4 ödev teslim edilmedi",
                "evidence": {"missed": 4, "window_days": 30},
                "window_from": now_ms - 30 * DAY,
                "window_to": now_ms,
            }
        ],
        confidence=Confidence.EXPLORATORY,
    )


def make_recommendation(about: str, *, now_ms: int = NOW) -> Recommendation:
    return Recommendation(
        school=SCHOOL,
        audience=about,
        audience_role=Audience.STUDENT,
        product="O1",
        rule_id="O1.review_band",
        evidence={"student_average": 42.5, "class_average": 68.0},
        computed_at=now_ms,
        expires_at=now_ms + 30 * DAY,
        about=about,
        course="course-1",
        confidence=Confidence.EXPLORATORY,
        limitation="Konu kırılımı yok.",
    )


def make_question_segment(question: str, *, now_ms: int = NOW) -> QuestionSegment:
    return QuestionSegment(
        school=SCHOOL,
        question=question,
        exam="exam:E1",
        subject="subject:S1",
        labels={"bilissel_talep": "analiz", "dikkat_tuzagi": "var"},
        confidences={"bilissel_talep": 0.91, "dikkat_tuzagi": 0.87},
        rationale="Uzun kök, iki adımlı çıkarım.",
        model="deepseek-flash",
        prompt_version="v1",
        variant="baseline",
        trap_choice="c-tuzak",
        downstream_dimensions=("bilissel_talep",),
        experimental_dimensions=("dikkat_tuzagi",),
        computed_at=now_ms,
        confidence=Confidence.STABLE,
    )


def make_profile(student: str, *, now_ms: int = NOW) -> StudentSegmentProfile:
    return StudentSegmentProfile(
        school=SCHOOL,
        student=student,
        dimension="bilissel_talep",
        label="analiz",
        n_answers=180,
        n_correct=63,
        overall_n_answers=900,
        overall_accuracy=0.58,
        computed_at=now_ms,
        confidence=Confidence.STABLE,
    )


class StoreFixture(unittest.IsolatedAsyncioTestCase):
    """Sahte köprüyü kuran taban sınıf."""

    async def asyncSetUp(self) -> None:
        self.caller = RecordingCaller()
        self.store = BridgeStore(self.caller)

    @property
    def calls(self) -> list[tuple[str, str, dict]]:
        return self.caller.calls

    def only_call(self) -> tuple[str, str, dict]:
        self.assertEqual(len(self.calls), 1)
        return self.calls[0]


# ===========================================================================
# Dokuz operasyon
# ===========================================================================


class TestActiveSchools(StoreFixture):
    async def test_schools_are_listed_without_a_school_in_the_frame(self) -> None:
        caller = ReplyingCaller({CAP_SCHOOLS: {"schools": ["b-okul", "a-okul", "a-okul"]}})
        store = BridgeStore(caller)
        schools = await store.active_schools()
        self.assertEqual(caller.calls, [(CAP_SCHOOLS, "", {})])
        # Tekilleştirilir ve sıralanır: sabit sıra zamanlayıcının kuralıdır.
        self.assertEqual(schools, ["a-okul", "b-okul"])


class TestSummaryWrite(StoreFixture):
    async def test_capability_school_and_payload(self) -> None:
        report = await self.store.store_for(SCHOOL).write_summaries(
            [make_summary("s1")]
        )
        capability, school, payload = self.only_call()
        self.assertEqual(capability, CAP_SUMMARY)
        self.assertEqual(school, SCHOOL)
        self.assertEqual(set(payload), {"rows"})

        row = payload["rows"][0]
        self.assertEqual(
            set(row),
            {
                "student",
                "marks",
                "attendance",
                "submission",
                "study",
                "confidence",
                "computed_at",
                "retain_until",
                "attention",
            },
        )
        # Okul SATIRDA yoktur: çerçevede bir kez gider, çelişecek ikinci bir
        # yer bırakmaz.
        self.assertNotIn("school", row)
        self.assertEqual(row["student"], "s1")
        self.assertEqual(row["confidence"], "exploratory")
        self.assertEqual(row["marks"]["courses"]["course-1"]["placement"]["band"], "review")
        self.assertEqual(
            row["retain_until"],
            NOW + RETENTION_DAYS["student_summary"] * DAY,
        )
        item = row["attention"][0]
        self.assertEqual(item["trigger"], "homework")
        self.assertEqual(item["evidence"], {"missed": 4, "window_days": 30})
        self.assertNotIn("score", item)
        self.assertNotIn("rank", item)
        self.assertEqual(report.written, 1)
        self.assertEqual(report.status, "ok")


class TestRecommendationWrite(StoreFixture):
    async def test_capability_school_and_payload(self) -> None:
        await self.store.store_for(SCHOOL).write_recommendations(
            [make_recommendation("s1")]
        )
        capability, school, payload = self.only_call()
        self.assertEqual(capability, CAP_RECOMMENDATION)
        self.assertEqual(school, SCHOOL)

        row = payload["rows"][0]
        self.assertEqual(
            set(row),
            {
                "audience",
                "product",
                "rule_id",
                "rule_version",
                "scope",
                "about",
                "audience_role",
                "course",
                "evidence",
                "limitation",
                "confidence",
                "computed_at",
                "expires_at",
                "retain_until",
            },
        )
        # Kimliği YAZAN taraf üretir: satırda `id` yoktur.
        self.assertNotIn("id", row)
        self.assertEqual(row["audience"], "s1")
        self.assertEqual(row["audience_role"], "student")
        # `scope` boşsa ders devralır; `about` kendi alanında kalır.
        self.assertEqual(row["scope"], "course-1")
        self.assertEqual(row["about"], "s1")
        # `expires_at` 30 gün: 90 günlük tavandan önce gelir.
        self.assertEqual(
            row["retain_until"], NOW + 30 * DAY
        )


class TestEvidenceGate(StoreFixture):
    async def test_evidence_free_recommendation_is_rejected_not_written(self) -> None:
        """Kanıtsız satır yazılmaz; sayısı raporda REJECTED görünür."""
        rec = make_recommendation("s1")
        # `Recommendation` boş kanıtla kurulamaz; sözlükten kurulmuş bir
        # satırı taklit etmek için alan sonradan boşaltılır.
        object.__setattr__(rec, "evidence", {})
        report = await self.store.store_for(SCHOOL).write_recommendations([rec])
        self.assertEqual(report.written, 0)
        self.assertEqual(report.rejected, 1)
        # Hiç satır gitmedi: red yerel kapıda durdu.
        self.assertEqual(self.calls, [])


class TestSegmentWrite(StoreFixture):
    async def test_capability_school_and_payload(self) -> None:
        await self.store.store_for(SCHOOL).write_question_segments(
            [make_question_segment("q1")]
        )
        capability, school, payload = self.only_call()
        self.assertEqual(capability, CAP_SEGMENT)
        self.assertEqual(school, SCHOOL)

        row = payload["rows"][0]
        self.assertEqual(
            set(row),
            {
                "question",
                "exam",
                "course",
                "subject",
                "labels",
                "confidences",
                "confidence",
                "trap_choice",
                "rationale",
                "model",
                "prompt_version",
                "variant",
                "computed_at",
                "retain_until",
                "downstream_dimensions",
                "experimental_dimensions",
            },
        )
        self.assertEqual(row["question"], "q1")
        self.assertEqual(row["labels"], {"bilissel_talep": "analiz", "dikkat_tuzagi": "var"})
        self.assertEqual(row["confidences"], {"bilissel_talep": 0.91, "dikkat_tuzagi": 0.87})
        self.assertEqual(row["trap_choice"], "c-tuzak")
        self.assertEqual(row["downstream_dimensions"], ["bilissel_talep"])
        self.assertEqual(row["experimental_dimensions"], ["dikkat_tuzagi"])
        self.assertEqual(
            row["retain_until"],
            NOW + RETENTION_DAYS["question_segment"] * DAY,
        )


class TestProfileWrite(StoreFixture):
    async def test_capability_school_and_payload(self) -> None:
        await self.store.store_for(SCHOOL).write_segment_profiles(
            [make_profile("s1")]
        )
        capability, school, payload = self.only_call()
        self.assertEqual(capability, CAP_PROFILE)
        self.assertEqual(school, SCHOOL)

        row = payload["rows"][0]
        self.assertEqual(
            set(row),
            {
                "student",
                "dimension",
                "label",
                "n_answers",
                "n_correct",
                "accuracy",
                "overall_n_answers",
                "overall_accuracy",
                "contrast",
                "confidence",
                "computed_at",
                "retain_until",
            },
        )
        self.assertEqual(row["student"], "s1")
        self.assertAlmostEqual(row["accuracy"], 63 / 180, places=6)
        self.assertAlmostEqual(row["contrast"], 63 / 180 - 0.58, places=6)
        self.assertEqual(
            row["retain_until"],
            NOW + RETENTION_DAYS["student_segment_profile"] * DAY,
        )


class TestRunWrite(StoreFixture):
    async def test_capability_school_and_payload(self) -> None:
        ok = await self.store.store_for(SCHOOL).write_run(
            {
                "school": SCHOOL,  # satıra GİRMEZ: okul çerçevededir
                "started_at": NOW,
                "finished_at": NOW + 1000,
                "status": "ok",
                "students_total": 5,
                "students_ok": 5,
                "rows_written": 12,
                "budget_exceeded": False,
                "budget_ms": 60_000,
            },
            f"{SCHOOL}_2023-11-14",
        )
        self.assertTrue(ok)
        capability, school, payload = self.only_call()
        self.assertEqual(capability, CAP_RUN)
        self.assertEqual(school, SCHOOL)
        self.assertEqual(set(payload), {"run"})

        run = payload["run"]
        self.assertNotIn("school", run)
        self.assertEqual(run["run_day"], "2023-11-14")
        self.assertEqual(run["started_at"], NOW)
        # Gönderilmeyen alanlar varsayılanlanır: liste boş, `retain_until`
        # koşu süresinden türetilir.
        self.assertEqual(run["pending_students"], [])
        self.assertEqual(run["failed_modules"], [])
        self.assertEqual(
            run["retain_until"], NOW + RETENTION_DAYS["insight_run"] * DAY
        )


class TestPendingRead(StoreFixture):
    async def test_capability_school_and_payload(self) -> None:
        caller = ReplyingCaller({CAP_PENDING: {"students": ["s1", "s2"]}})
        store = BridgeStore(caller)
        students = await store.store_for(SCHOOL).last_pending(SCHOOL)
        self.assertEqual(caller.calls, [(CAP_PENDING, SCHOOL, {})])
        self.assertEqual(students, ["s1", "s2"])


class TestSweepWrite(StoreFixture):
    async def test_capability_school_and_every_table(self) -> None:
        # Cevap şekli backend'in `TableVerdicts`idir: kararlar `tables`
        # anahtarının altında, tablo adına göre gelir.
        caller = ReplyingCaller(
            {CAP_SWEEP: {"tables": {table: True for table in SWEEP_TABLES}}}
        )
        store = BridgeStore(caller)
        result = await store.store_for(SCHOOL).sweep(NOW)
        self.assertEqual(caller.calls, [(CAP_SWEEP, SCHOOL, {})])
        self.assertEqual(tuple(result), SWEEP_TABLES)
        self.assertTrue(all(result.values()))


class TestPurgeWrite(StoreFixture):
    async def test_capability_school_and_students(self) -> None:
        caller = ReplyingCaller(
            {CAP_PURGE: {"tables": {table: True for table in PURGE_TABLES}}}
        )
        store = BridgeStore(caller)
        ok = await store.store_for(SCHOOL).purge_departed(SCHOOL, ["kalan"])
        self.assertTrue(ok)
        self.assertEqual(caller.calls, [(CAP_PURGE, SCHOOL, {"students": ["kalan"]})])

    async def test_a_false_verdict_is_reported(self) -> None:
        """Süpürülemeyen tablo `False` döner; hata yutulmaz."""
        caller = ReplyingCaller(
            {
                CAP_PURGE: {
                    "tables": {
                        table: table != PURGE_TABLES[0] for table in PURGE_TABLES
                    }
                }
            }
        )
        store = BridgeStore(caller)
        self.assertFalse(await store.store_for(SCHOOL).purge_departed(SCHOOL, ["kalan"]))


# ===========================================================================
# Grup bölme, yeniden deneme, kapılar
# ===========================================================================


class TestBatching(StoreFixture):
    async def test_more_than_batch_size_is_split_into_two_calls(self) -> None:
        total = BATCH_SIZE + 1
        report = await self.store.store_for(SCHOOL).write_summaries(
            [make_summary(f"s{i:04d}") for i in range(total)]
        )
        sizes = [len(payload["rows"]) for _, _, payload in self.calls]
        self.assertEqual(sizes, [BATCH_SIZE, 1])
        self.assertTrue(all(capability == CAP_SUMMARY for capability, _, _ in self.calls))
        self.assertEqual(report.written, total)
        self.assertEqual(report.skipped_batches, 0)
        self.assertEqual(report.status, "ok")


class TestFailureVisibility(StoreFixture):
    async def test_a_dead_batch_is_retried_then_skipped_never_successful(self) -> None:
        caller = RecordingCaller(fail_times=2)  # `MAX_ATTEMPTS` kadar
        store = BridgeStore(caller)
        report = await store.store_for(SCHOOL).write_summaries(
            [make_summary("s1")]
        )
        self.assertEqual(report.written, 0)
        self.assertEqual(report.skipped_batches, 1)
        self.assertEqual(report.status, "partial")
        # Düşen çağrı kaydedilmez: başarı gibi görünen bir iz kalmaz.
        self.assertEqual(caller.calls, [])

    async def test_run_write_returns_false_when_the_bridge_refuses(self) -> None:
        store = BridgeStore(RecordingCaller(fail_times=2))
        ok = await store.store_for(SCHOOL).write_run({"started_at": NOW}, "okul-a_2023-11-14")
        self.assertFalse(ok)

    async def test_purge_refusal_is_false_not_an_exception(self) -> None:
        store = BridgeStore(RecordingCaller(fail_capabilities={CAP_PURGE}))
        ok = await store.store_for(SCHOOL).purge_departed(SCHOOL, ["kalan"])
        self.assertFalse(ok)

    async def test_pending_read_failure_yields_an_empty_list(self) -> None:
        """Devretmemek, yanlış listeyle koşmaktan iyidir."""
        store = BridgeStore(RecordingCaller(fail_capabilities={CAP_PENDING}))
        self.assertEqual(await store.store_for(SCHOOL).last_pending(SCHOOL), [])


class TestEmptyDepartedGuard(StoreFixture):
    async def test_empty_list_makes_no_call_and_returns_false(self) -> None:
        ok = await self.store.store_for(SCHOOL).purge_departed(SCHOOL, [])
        self.assertFalse(ok)
        self.assertEqual(self.calls, [])


class TestClosedBridge(unittest.IsolatedAsyncioTestCase):
    """Taşıma yokken okuma yükseltir; yazma raporda GÖRÜNÜR, sessiz kalmaz."""

    async def test_a_read_raises_instead_of_returning_an_empty_answer(self) -> None:
        store = BridgeStore(None)
        with self.assertRaises(BridgeUnavailable):
            await store.active_schools()

    async def test_a_write_is_not_reported_as_a_success(self) -> None:
        store = BridgeStore(None)
        report = await store.store_for(SCHOOL).write_summaries([make_summary("s1")])
        self.assertEqual(report.written, 0)
        self.assertEqual(report.skipped_batches, 1)
        self.assertEqual(report.status, "partial")


if __name__ == "__main__":
    unittest.main()
