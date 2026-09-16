"""Depolama katmani testleri.

Iki kume:

* **Birim** -- veritabani gerektirmez: ifade ayirici, satir bicimi, saklama
  suresi hesabi, kanitsiz tavsiyenin reddi.
* **Entegrasyon** -- GERCEK SurrealDB'ye karsi kosar: sema yukleme, alan
  tiplerinin dogrulanmasi, toplu yazim, okuma dogrulamasi, supurme, kiraci
  izolasyonu, mezuniyet temizligi. Konteyner yoksa `skipUnless` ile atlanir
  (bkz. `tests/zeka_db.py`).
"""

from __future__ import annotations

import asyncio
import unittest

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
    RETENTION_DAYS,
    CollectingClient,
    Store,
    SurrealError,
    apply_schema,
    load_schema_text,
    recommendation_row,
    schema_field_types,
    schema_tables,
    split_statements,
    summary_row,
)

from .zeka_db import NOW, count_rows, fresh_client, fresh_schema_client, requires_db, select

DAY = 86_400_000


def make_summary(school: str, student: str, *, now_ms: int = NOW) -> StudentSummary:
    return StudentSummary(
        school=school,
        student=student,
        computed_at=now_ms,
        marks={"courses": {"course-1": {"placement": {"band": "on_track"}}}},
        attendance={"courses": {}},
        submission={"window_days": 30},
        study={"sessions": 6},
        attention=[
            {
                "trigger": "homework",
                "fact": "son 30 gunde 4 odev teslim edilmedi",
                "evidence": {"missed": 4, "window_days": 30},
                "window_from": now_ms - 30 * DAY,
                "window_to": now_ms,
            }
        ],
        confidence=Confidence.EXPLORATORY,
    )


def make_recommendation(
    school: str, about: str, *, rule_id: str = "O1-a", now_ms: int = NOW
) -> Recommendation:
    return Recommendation(
        school=school,
        audience=about,
        audience_role=Audience.STUDENT,
        product="O1",
        rule_id=rule_id,
        evidence={"missed": 4, "window_days": 30},
        computed_at=now_ms,
        expires_at=now_ms + 30 * DAY,
        about=about,
        course="course-1",
        confidence=Confidence.EXPLORATORY,
        limitation="Sinav verisi dahil degildir.",
    )


def make_question_segment(
    school: str, question: str, *, now_ms: int = NOW, trap: str | None = "choice-2"
) -> QuestionSegment:
    return QuestionSegment(
        school=school,
        question=question,
        exam="exam:E1",
        subject="subject:S1",
        labels={
            "bilissel_talep": "analiz",
            "adim_sayisi": "cok_adim",
            "dikkat_tuzagi": "var" if trap else "yok",
            "okuma_yuku": "yuksek",
        },
        confidences={
            "bilissel_talep": 0.91,
            "adim_sayisi": 0.55,
            "dikkat_tuzagi": 0.87,
            "okuma_yuku": 0.96,
        },
        rationale="Uzun kok, iki adimli cikarim.",
        model="deepseek-flash",
        prompt_version="v1",
        variant="baseline",
        trap_choice=trap,
        downstream_dimensions=("bilissel_talep", "dikkat_tuzagi", "okuma_yuku"),
        experimental_dimensions=("adim_sayisi",),
        computed_at=now_ms,
        confidence=Confidence.STABLE,
    )


def make_segment_profile(
    school: str,
    student: str,
    *,
    now_ms: int = NOW,
    dimension: str = "bilissel_talep",
    label: str = "analiz",
) -> StudentSegmentProfile:
    return StudentSegmentProfile(
        school=school,
        student=student,
        dimension=dimension,
        label=label,
        n_answers=180,
        n_correct=63,
        overall_n_answers=900,
        overall_accuracy=0.58,
        computed_at=now_ms,
        confidence=Confidence.STABLE,
    )


# ===========================================================================
# BIRIM
# ===========================================================================


class TestSplitStatements(unittest.TestCase):
    """`surreal sql`'in satir satir ayristirma tuzagina dusmeyen ayirici."""

    def test_schema_file_splits_into_statements(self) -> None:
        statements = split_statements(load_schema_text())
        self.assertGreater(len(statements), 40)
        self.assertTrue(all(s.endswith(";") for s in statements))
        self.assertTrue(all(not s.startswith("--") for s in statements))

    def test_multiline_statement_stays_whole(self) -> None:
        text = "DEFINE FIELD a\n  ON t\n  TYPE int;\nDEFINE FIELD b ON t TYPE int;"
        self.assertEqual(len(split_statements(text)), 2)

    def test_semicolon_inside_string_is_not_a_boundary(self) -> None:
        text = "UPSERT t CONTENT { note: 'a;b;c' };"
        self.assertEqual(split_statements(text), ["UPSERT t CONTENT { note: 'a;b;c' };"])

    def test_comments_are_dropped(self) -> None:
        text = "-- yorum; yine yorum\nDEFINE TABLE t SCHEMAFULL;"
        self.assertEqual(split_statements(text), ["DEFINE TABLE t SCHEMAFULL;"])

    def test_generated_upsert_uses_type_record(self) -> None:
        """`type::thing()` SurrealDB 3'te YOK; uretilen SQL `type::record()` olmali."""
        client = CollectingClient()
        asyncio.run(Store(client).write_summaries([make_summary("okul-a", "s1")]))
        sql = client.statements[0][0]
        self.assertIn("type::record(", sql)
        self.assertNotIn("type::thing(", sql)


class TestRecordLikeStrings(unittest.TestCase):
    """`"user:01K..."` biciminde bir metin uca `record` olarak gidiyordu.

    Sonuc: `TYPE string` alan reddediliyor ve 500 satirlik grubun TAMAMI
    dusuyordu. Fikstur kimlikleri (`student-00`) iki nokta tasimadigi icin
    testlerde hic gorunmeyen bir tuzakti.
    """

    def test_kimlik_bicimli_metin_type_string_ile_sarilir(self) -> None:
        client = CollectingClient()
        asyncio.run(
            Store(client).write_summaries([make_summary("okul-a", "user:01K6MDX")])
        )
        sql = client.statements[0][0]
        self.assertIn("student: type::string($v0.student)", sql)
        # Iki nokta tasimayan alan sarilmaz -- gereksiz gurultu olmasin.
        self.assertIn("school: $v0.school", sql)

    def test_kimlik_dizisi_array_map_ile_sarilir(self) -> None:
        client = CollectingClient()
        row = {
            "school": "okul-a",
            "started_at": NOW,
            "status": "ok",
            "students_total": 1,
            "students_ok": 1,
            "students_failed": 0,
            "students_skipped": 0,
            "rows_written": 0,
            "pending_students": ["user:01K6MDX", "user:01K6MDY"],
            "failed_modules": [],
            "budget_exceeded": False,
            "budget_ms": 1000,
        }
        asyncio.run(Store(client).write_run(row, "okul-a_2023-11-14"))
        sql = client.statements[0][0]
        self.assertIn(
            "pending_students: array::map($v0.pending_students, "
            "|$x| type::string($x))",
            sql,
        )
        self.assertIn("failed_modules: $v0.failed_modules", sql)

    def test_deger_asla_sql_metnine_gomulmez(self) -> None:
        """Kacis hatasi yuzeyi acilmadi: metne yalnizca ALAN ADI giriyor."""
        client = CollectingClient()
        asyncio.run(
            Store(client).write_summaries([make_summary("o'kul", "user:01K")])
        )
        sql, variables = client.statements[0]
        self.assertNotIn("o'kul", sql)
        self.assertEqual(variables["v0"]["school"], "o'kul")


class TestRowShapes(unittest.TestCase):
    def test_summary_row_matches_schema_fields(self) -> None:
        row = summary_row(make_summary("okul-a", "s1"))
        self.assertEqual(
            set(row),
            {
                "school",
                "student",
                "marks",
                "attendance",
                "submission",
                "study",
                "attention",
                "confidence",
                "computed_at",
                "retain_until",
            },
        )
        self.assertEqual(row["retain_until"], NOW + RETENTION_DAYS["student_summary"] * DAY)

    def test_recommendation_retention_is_the_earlier_of_two(self) -> None:
        rec = make_recommendation("okul-a", "s1")
        row = recommendation_row(rec)
        # 30 gunluk `expires_at`, 90 gunluk tavandan once gelir.
        self.assertEqual(row["retain_until"], rec.expires_at)

    def test_attention_items_have_no_score(self) -> None:
        row = summary_row(make_summary("okul-a", "s1"))
        for item in row["attention"]:
            self.assertNotIn("score", item)
            self.assertNotIn("rank", item)


class TestEvidenceGate(unittest.IsolatedAsyncioTestCase):
    async def test_evidence_free_recommendation_is_rejected(self) -> None:
        rec = make_recommendation("okul-a", "s1")
        # `Recommendation` bos kanitla kurulamaz; sozlukten yeniden kurulmus
        # satiri taklit etmek icin alani sonradan bosaltiyoruz.
        object.__setattr__(rec, "evidence", {})
        store = Store(CollectingClient())
        report = await store.write_recommendations([rec])
        self.assertEqual(report.rejected, 1)
        self.assertEqual(report.written, 0)

    async def test_second_failure_skips_the_batch_but_keeps_going(self) -> None:
        client = CollectingClient()
        client.fail_times = 2  # MAX_ATTEMPTS kadar
        store = Store(client)
        report = await store.write_summaries([make_summary("okul-a", "s1")])
        self.assertEqual(report.written, 0)
        self.assertEqual(report.skipped_batches, 1)


# ===========================================================================
# ENTEGRASYON -- gercek SurrealDB
# ===========================================================================


@requires_db
class TestSchemaApply(unittest.TestCase):
    def test_every_statement_applies_cleanly(self) -> None:
        client = fresh_client("sema")
        report = apply_schema(client)
        self.assertEqual(report.errors, [])
        self.assertEqual(report.total, report.applied)
        self.assertGreater(report.total, 40)

    def test_applying_twice_is_idempotent(self) -> None:
        client = fresh_client("sema2")
        first = apply_schema(client)
        second = apply_schema(client)
        self.assertTrue(first.ok)
        self.assertTrue(second.ok)

    def test_five_tables_and_nothing_else(self) -> None:
        client = fresh_schema_client("sema3")
        self.assertEqual(
            sorted(schema_tables(client)),
            [
                "insight_run",
                "question_segment",
                "recommendation",
                "student_segment_profile",
                "student_summary",
            ],
        )

    def test_declared_field_types_are_what_the_schema_says(self) -> None:
        """Her alanin tipi TEK TEK dogrulanir -- `INFO FOR TABLE` ciktisindan."""
        client = fresh_schema_client("tip")
        expected = {
            "student_summary": {
                "school": "string",
                "student": "string",
                "marks": "none | object",
                "attendance": "none | object",
                "submission": "none | object",
                "study": "none | object",
                "attention": "none | array<object>",
                "attention.*": "object",
                "confidence": "string",
                "computed_at": "int",
                "retain_until": "int",
            },
            "recommendation": {
                "school": "string",
                "audience": "string",
                "about": "none | string",
                "audience_role": "string",
                "product": "string",
                "course": "none | string",
                "rule_id": "string",
                "rule_version": "int",
                "evidence": "object",
                "confidence": "string",
                "created_at": "int",
                "expires_at": "int",
                "retain_until": "int",
                "dismissed_at": "none | int",
                "dismissed_by": "none | string",
                "dismiss_reason": "none | string",
            },
            "insight_run": {
                "school": "string",
                "started_at": "int",
                "finished_at": "none | int",
                "status": "string",
                "duration_ms": "none | int",
                "students_total": "int",
                "students_ok": "int",
                "students_failed": "int",
                "students_skipped": "int",
                "rows_written": "int",
                "pending_students": "none | array<string>",
                "pending_students.*": "string",
                "failed_modules": "none | array<string>",
                "failed_modules.*": "string",
                "budget_exceeded": "bool",
                "budget_ms": "int",
                "retain_until": "int",
            },
            "question_segment": {
                "school": "string",
                "question": "string",
                "exam": "none | string",
                "course": "none | string",
                "subject": "none | string",
                "bilissel_talep": "string",
                "dikkat_tuzagi": "string",
                "okuma_yuku": "string",
                "adim_sayisi": "string",
                "confidence_bilissel_talep": "float",
                "confidence_dikkat_tuzagi": "float",
                "confidence_okuma_yuku": "float",
                "confidence_adim_sayisi": "float",
                "confidence": "string",
                "experimental_dimensions": "none | array<string>",
                "experimental_dimensions.*": "string",
                "downstream_dimensions": "none | array<string>",
                "downstream_dimensions.*": "string",
                "trap_choice": "none | string",
                "rationale": "string",
                "model": "string",
                "prompt_version": "string",
                "variant": "none | string",
                "computed_at": "int",
                "retain_until": "int",
            },
            "student_segment_profile": {
                "school": "string",
                "student": "string",
                "dimension": "string",
                "label": "string",
                "n_answers": "int",
                "n_correct": "int",
                "accuracy": "float",
                "overall_n_answers": "int",
                "overall_accuracy": "float",
                "contrast": "float",
                "confidence": "string",
                "computed_at": "int",
                "retain_until": "int",
            },
        }
        for table, fields in expected.items():
            actual = schema_field_types(client, table)
            self.assertEqual(
                set(actual), set(fields), f"{table}: alan kumesi sapti"
            )
            for name, type_text in fields.items():
                self.assertIn(
                    f"TYPE {type_text}", actual[name], f"{table}.{name} tipi sapti"
                )

    def test_flexible_objects_really_are_flexible(self) -> None:
        """FLEXIBLE olmayan `object` alani ic anahtarlari SESSIZCE duserdi."""
        client = fresh_schema_client("esnek")
        for table, field in (
            ("student_summary", "marks"),
            ("student_summary", "attention.*"),
            ("recommendation", "evidence"),
        ):
            self.assertIn("FLEXIBLE", schema_field_types(client, table)[field])

    def test_schemafull_rejects_an_undeclared_field(self) -> None:
        """Semada olmayan alan SESSIZCE dusmuyor, satir tumden reddediliyor."""
        client = fresh_schema_client("kapali")
        with self.assertRaises(SurrealError) as caught:
            client.query_sync(
                "UPSERT type::record('student_summary', 'x') CONTENT $v;",
                {
                    "v": {
                        **summary_row(make_summary("okul-a", "s1")),
                        # Tek bir "risk skoru" alani semada KASITLI OLARAK yok.
                        "risk_score": 0.9,
                    }
                },
            )
        self.assertIn("risk_score", str(caught.exception))
        self.assertEqual(count_rows(client, "student_summary"), 0)

    def test_none_valued_optional_field_is_omitted_not_nulled(self) -> None:
        """`option<string>` NULL kabul etmez; alan hic gonderilmemeli."""
        client = fresh_schema_client("bosalan")
        row = recommendation_row(make_recommendation("okul-a", "s1"))
        self.assertIsNone(row["dismissed_at"])
        asyncio.run(Store(client).write_recommendations([make_recommendation("okul-a", "s1")]))
        stored = select(client, "SELECT * FROM recommendation;")[0]
        self.assertEqual(count_rows(client, "recommendation"), 1)
        self.assertIsNone(stored.get("dismissed_at"))

    def test_wrong_type_is_refused_loudly(self) -> None:
        client = fresh_schema_client("tiphata")
        with self.assertRaises(SurrealError):
            client.query_sync(
                "UPSERT type::record('student_summary', 'y') CONTENT $v;",
                {"v": {**summary_row(make_summary("okul-a", "s1")), "computed_at": "yarin"}},
            )


@requires_db
class TestBulkWrite(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.client = fresh_schema_client("yazim")
        self.store = Store(self.client)

    async def test_write_and_read_back_summaries(self) -> None:
        summaries = [make_summary("okul-a", f"s{i:04d}") for i in range(37)]
        report = await self.store.write_summaries(summaries)
        self.assertEqual(report.written, 37)
        self.assertEqual(count_rows(self.client, "student_summary"), 37)
        rows = select(
            self.client,
            "SELECT * FROM student_summary WHERE student = 's0000';",
        )
        self.assertEqual(len(rows), 1)
        # Ic ice nesne ve dikkat maddesi aynen geri okunuyor mu?
        self.assertEqual(
            rows[0]["marks"]["courses"]["course-1"]["placement"]["band"], "on_track"
        )
        self.assertEqual(rows[0]["attention"][0]["evidence"]["missed"], 4)
        self.assertEqual(rows[0]["confidence"], "exploratory")

    async def test_batches_larger_than_batch_size_are_split_and_all_land(self) -> None:
        """`BATCH_SIZE`'i asan yazim birden fazla transaction'a boluniyor."""
        total = BATCH_SIZE + 123
        summaries = [make_summary("okul-a", f"b{i:05d}") for i in range(total)]
        store = Store(self.client)
        report = await store.write_summaries(summaries)
        self.assertEqual(report.written, total)
        self.assertEqual(report.skipped_batches, 0)
        self.assertEqual(count_rows(self.client, "student_summary"), total)

    async def test_upsert_is_idempotent(self) -> None:
        summaries = [make_summary("okul-a", "tek")]
        await self.store.write_summaries(summaries)
        await self.store.write_summaries(summaries)
        self.assertEqual(count_rows(self.client, "student_summary"), 1)

    async def test_recommendations_land_with_evidence(self) -> None:
        recs = [
            make_recommendation("okul-a", f"s{i}", rule_id=f"O1-{i}") for i in range(10)
        ]
        report = await self.store.write_recommendations(recs)
        self.assertEqual(report.written, 10)
        self.assertEqual(count_rows(self.client, "recommendation"), 10)
        rows = select(self.client, "SELECT * FROM recommendation LIMIT 1;")
        payload = {k: v for k, v in rows[0]["evidence"].items() if k != "limitation"}
        self.assertTrue(payload)
        self.assertIn("limitation", rows[0]["evidence"])

    async def test_rerun_does_not_erase_a_human_dismissal(self) -> None:
        """Gece kosusu, kullanicinin 'faydali degil' kaydini SILMEZ."""
        rec = make_recommendation("okul-a", "s1")
        await self.store.write_recommendations([rec])
        self.client.query_sync(
            "UPDATE type::record('recommendation', $k) MERGE $v;",
            {
                "k": rec.record_key(),
                "v": {
                    "dismissed_at": NOW + 1000,
                    "dismissed_by": "s1",
                    "dismiss_reason": "bu dogru degil",
                },
            },
        )
        await self.store.write_recommendations([rec])  # ertesi gece
        row = select(self.client, "SELECT * FROM recommendation;")[0]
        self.assertEqual(row["dismissed_at"], NOW + 1000)
        self.assertEqual(row["dismiss_reason"], "bu dogru degil")

    async def test_insight_run_row_is_written(self) -> None:
        row = {
            "school": "okul-a",
            "started_at": NOW,
            "finished_at": NOW + 1000,
            "status": "ok",
            "duration_ms": 1000,
            "students_total": 5,
            "students_ok": 5,
            "students_failed": 0,
            "students_skipped": 0,
            "rows_written": 12,
            "pending_students": [],
            "failed_modules": [],
            "budget_exceeded": False,
            "budget_ms": 60_000,
        }
        self.assertTrue(await self.store.write_run(row, "okul-a_2023-11-14"))
        rows = select(self.client, "SELECT * FROM insight_run;")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "ok")
        self.assertEqual(
            rows[0]["retain_until"], NOW + RETENTION_DAYS["insight_run"] * DAY
        )


@requires_db
class TestSegmentTables(unittest.IsolatedAsyncioTestCase):
    """Iki yeni tablo GERCEKTEN yaziliyor ve geri okunuyor mu?"""

    async def asyncSetUp(self) -> None:
        self.client = fresh_schema_client("segment")
        self.store = Store(self.client)

    async def test_question_segment_round_trip(self) -> None:
        report = await self.store.write_question_segments(
            [make_question_segment("okul-a", f"exam_question:q{i}") for i in range(5)]
        )
        self.assertEqual(report.written, 5)
        self.assertEqual(count_rows(self.client, "question_segment"), 5)
        # DIKKAT: `WHERE question = $q` CALISMAZ. Kimlik bicimli bir degisken
        # ucta `record` olur ve metin alanla esitlik SESSIZCE bos doner --
        # hata degil, BOS SONUC. Okuyan taraf da `type::string()` ile
        # karsilastirmak zorunda (bkz. docs/CIKTI-SOZLESMESI.md §6).
        row = select(
            self.client,
            "SELECT * FROM question_segment WHERE question = type::string($q);",
            {"q": "exam_question:q0"},
        )[0]
        self.assertEqual(row["bilissel_talep"], "analiz")
        self.assertEqual(row["confidence_okuma_yuku"], 0.96)
        self.assertEqual(row["experimental_dimensions"], ["adim_sayisi"])
        self.assertNotIn("adim_sayisi", row["downstream_dimensions"])
        self.assertEqual(row["trap_choice"], "choice-2")

    async def test_tuzaksiz_soruda_trap_choice_alani_hic_yazilmaz(self) -> None:
        """`option<string>` NULL kabul etmez; alan gonderilmemeli."""
        await self.store.write_question_segments(
            [make_question_segment("okul-a", "exam_question:temiz", trap=None)]
        )
        row = select(self.client, "SELECT * FROM question_segment;")[0]
        self.assertIsNone(row.get("trap_choice"))
        self.assertEqual(row["dikkat_tuzagi"], "yok")

    async def test_profil_satiri_kontrastla_birlikte_geri_okunur(self) -> None:
        await self.store.write_segment_profiles(
            [make_segment_profile("okul-a", "s1")]
        )
        row = select(self.client, "SELECT * FROM student_segment_profile;")[0]
        self.assertEqual(row["n_answers"], 180)
        self.assertAlmostEqual(row["accuracy"], 63 / 180, places=5)
        self.assertAlmostEqual(row["contrast"], 63 / 180 - 0.58, places=5)
        self.assertEqual(row["confidence"], "stable")

    async def test_upsert_idempotent(self) -> None:
        rows = [make_segment_profile("okul-a", "s1")]
        await self.store.write_segment_profiles(rows)
        await self.store.write_segment_profiles(rows)
        self.assertEqual(count_rows(self.client, "student_segment_profile"), 1)

    async def test_ayni_ogrencinin_iki_segmenti_iki_satir(self) -> None:
        await self.store.write_segment_profiles(
            [
                make_segment_profile("okul-a", "s1"),
                make_segment_profile(
                    "okul-a", "s1", dimension="okuma_yuku", label="yuksek"
                ),
            ]
        )
        self.assertEqual(count_rows(self.client, "student_segment_profile"), 2)

    async def test_semada_olmayan_alan_satiri_dusurur(self) -> None:
        """Tek bir "risk skoru" alani buraya da SIZAMAZ."""
        from src.store import student_segment_profile_row

        with self.assertRaises(SurrealError):
            self.client.query_sync(
                "UPSERT type::record('student_segment_profile', 'x') CONTENT $v;",
                {
                    "v": {
                        **student_segment_profile_row(
                            make_segment_profile("okul-a", "s1")
                        ),
                        "risk_score": 0.9,
                    }
                },
            )

    async def test_gercek_kimlikler_metin_olarak_geri_okunur(self) -> None:
        """`user:<ULID>` / `exam_question:<ULID>` yazilabiliyor mu?

        Bu tam olarak uretimdeki kimlik bicimi. `type::string()` sarmasi
        olmadan bu test "Expected string but found user:..." ile duserdi.
        """
        await self.store.write_question_segments(
            [make_question_segment("okul-a", "exam_question:01K6MDXNC0A8XV7W34QBS0")]
        )
        await self.store.write_segment_profiles(
            [make_segment_profile("okul-a", "user:01K4216NC0H6T9EB460A6P3RNZ")]
        )
        soru = select(self.client, "SELECT * FROM question_segment;")[0]
        self.assertEqual(soru["question"], "exam_question:01K6MDXNC0A8XV7W34QBS0")
        self.assertEqual(soru["exam"], "exam:E1")
        profil = select(self.client, "SELECT * FROM student_segment_profile;")[0]
        self.assertEqual(profil["student"], "user:01K4216NC0H6T9EB460A6P3RNZ")

    async def test_kimlikle_sorgulama_type_string_ister(self) -> None:
        """Okuma tarafindaki ayni tuzak: cast olmadan sonuc BOS doner.

        Bu bir hata degil, sessiz bos sonuctur -- yani en kotu tur. Sozlesme
        belgesi (`docs/CIKTI-SOZLESMESI.md` §6) bu yuzden her kimlik
        karsilastirmasini `type::string()` ile yazar.
        """
        uid = "user:01K4216NC0H6T9EB460A6P3RNZ"
        await self.store.write_segment_profiles(
            [make_segment_profile("okul-a", uid)]
        )
        castsiz = select(
            self.client,
            "SELECT * FROM student_segment_profile WHERE student = $s;",
            {"s": uid},
        )
        castli = select(
            self.client,
            "SELECT * FROM student_segment_profile "
            "WHERE student = type::string($s);",
            {"s": uid},
        )
        self.assertEqual(castsiz, [])
        self.assertEqual(len(castli), 1)

    async def test_mezuniyet_profili_siler_soru_etiketini_birakir(self) -> None:
        await self.store.write_segment_profiles(
            [
                make_segment_profile("okul-a", "kalan"),
                make_segment_profile("okul-a", "mezun"),
            ]
        )
        await self.store.write_question_segments(
            [make_question_segment("okul-a", "exam_question:q1")]
        )
        self.assertTrue(await self.store.purge_departed("okul-a", ["kalan"]))
        kalanlar = {
            r["student"]
            for r in select(
                self.client, "SELECT student FROM student_segment_profile;"
            )
        }
        self.assertEqual(kalanlar, {"kalan"})
        # Soru etiketi kisisel veri DEGIL: mezuniyetle silinmez.
        self.assertEqual(count_rows(self.client, "question_segment"), 1)


@requires_db
class TestSweep(unittest.IsolatedAsyncioTestCase):
    """Saklama suresi supurmesi GERCEKTEN siliyor mu?"""

    async def asyncSetUp(self) -> None:
        self.client = fresh_schema_client("supurme")
        self.store = Store(self.client)

    async def test_expired_rows_are_deleted_and_fresh_ones_survive(self) -> None:
        eski = [make_summary("okul-a", f"eski-{i}", now_ms=NOW - 500 * DAY) for i in range(5)]
        taze = [make_summary("okul-a", f"taze-{i}", now_ms=NOW) for i in range(7)]
        await self.store.write_summaries(eski + taze)
        self.assertEqual(count_rows(self.client, "student_summary"), 12)

        results = await self.store.sweep(NOW)
        self.assertTrue(all(results.values()))
        self.assertEqual(count_rows(self.client, "student_summary"), 7)
        kalanlar = {
            r["student"] for r in select(self.client, "SELECT student FROM student_summary;")
        }
        self.assertTrue(all(s.startswith("taze-") for s in kalanlar))

    async def test_sweep_touches_every_table(self) -> None:
        # RETENTION_DAYS'te olan her tablonun bir eski satiri yazilir;
        # supurmeden sonra HICBIRI kalmamali. Yeni bir tablo eklenip
        # supurmeye baglanmazsa bu test duser.
        eski = NOW - 1200 * DAY
        await self.store.write_question_segments(
            [make_question_segment("okul-a", "q1", now_ms=eski)]
        )
        await self.store.write_segment_profiles(
            [make_segment_profile("okul-a", "s", now_ms=eski)]
        )
        await self.store.write_summaries(
            [make_summary("okul-a", "s", now_ms=NOW - 500 * DAY)]
        )
        await self.store.write_recommendations(
            [make_recommendation("okul-a", "s", now_ms=NOW - 500 * DAY)]
        )
        await self.store.write_run(
            {
                "school": "okul-a",
                "started_at": NOW - 500 * DAY,
                "finished_at": None,
                "status": "ok",
                "duration_ms": None,
                "students_total": 1,
                "students_ok": 1,
                "students_failed": 0,
                "students_skipped": 0,
                "rows_written": 1,
                "pending_students": [],
                "failed_modules": [],
                "budget_exceeded": False,
                "budget_ms": 60_000,
            },
            "okul-a_eski",
        )
        for table in RETENTION_DAYS:
            self.assertEqual(count_rows(self.client, table), 1, table)
        await self.store.sweep(NOW)
        for table in RETENTION_DAYS:
            self.assertEqual(count_rows(self.client, table), 0, table)

    async def test_recommendation_dies_at_expires_at_not_at_ninety_days(self) -> None:
        """30 gunde dusen tavsiye, 90 gunu beklemez."""
        rec = make_recommendation("okul-a", "s", now_ms=NOW - 60 * DAY)
        await self.store.write_recommendations([rec])
        self.assertEqual(count_rows(self.client, "recommendation"), 1)
        await self.store.sweep(NOW)  # olusumdan 60 gun sonra; expires 30 gundu
        self.assertEqual(count_rows(self.client, "recommendation"), 0)


@requires_db
class TestPurgeDeparted(unittest.IsolatedAsyncioTestCase):
    async def test_departed_student_profile_is_removed(self) -> None:
        client = fresh_schema_client("mezun")
        store = Store(client)
        await store.write_summaries(
            [make_summary("okul-a", "kalan"), make_summary("okul-a", "mezun")]
        )
        await store.write_recommendations(
            [
                make_recommendation("okul-a", "kalan", rule_id="O1-k"),
                make_recommendation("okul-a", "mezun", rule_id="O1-m"),
            ]
        )
        self.assertTrue(await store.purge_departed("okul-a", ["kalan"]))
        kalanlar = {
            r["student"] for r in select(client, "SELECT student FROM student_summary;")
        }
        self.assertEqual(kalanlar, {"kalan"})
        hakkinda = {r["about"] for r in select(client, "SELECT about FROM recommendation;")}
        self.assertEqual(hakkinda, {"kalan"})


@requires_db
class TestTenantIsolation(unittest.IsolatedAsyncioTestCase):
    """Iki okulun verisi birbirine karismiyor."""

    async def asyncSetUp(self) -> None:
        self.client = fresh_schema_client("kiraci")
        self.store = Store(self.client)
        await self.store.write_summaries(
            [make_summary("okul-a", f"a{i}") for i in range(6)]
            + [make_summary("okul-b", f"b{i}") for i in range(9)]
        )
        await self.store.write_recommendations(
            [make_recommendation("okul-a", f"a{i}", rule_id=f"O1-{i}") for i in range(4)]
            + [make_recommendation("okul-b", f"b{i}", rule_id=f"O1-{i}") for i in range(5)]
        )

    async def test_row_counts_are_separate(self) -> None:
        self.assertEqual(count_rows(self.client, "student_summary", "school = 'okul-a'"), 6)
        self.assertEqual(count_rows(self.client, "student_summary", "school = 'okul-b'"), 9)
        self.assertEqual(count_rows(self.client, "recommendation", "school = 'okul-a'"), 4)
        self.assertEqual(count_rows(self.client, "recommendation", "school = 'okul-b'"), 5)

    async def test_no_row_of_one_school_carries_the_other_students(self) -> None:
        for school, prefix in (("okul-a", "a"), ("okul-b", "b")):
            rows = select(
                self.client,
                "SELECT student FROM student_summary WHERE school = $s;",
                {"s": school},
            )
            self.assertTrue(rows)
            for row in rows:
                self.assertTrue(row["student"].startswith(prefix), row)

    async def test_record_keys_are_school_scoped(self) -> None:
        """Ayni ogrenci kimligi iki okulda olsa bile satirlar ayri kalir."""
        await self.store.write_summaries(
            [make_summary("okul-a", "ayni"), make_summary("okul-b", "ayni")]
        )
        self.assertEqual(
            count_rows(self.client, "student_summary", "student = 'ayni'"), 2
        )

    async def test_purging_one_school_leaves_the_other_untouched(self) -> None:
        await self.store.purge_departed("okul-a", ["a0"])
        self.assertEqual(count_rows(self.client, "student_summary", "school = 'okul-a'"), 1)
        self.assertEqual(count_rows(self.client, "student_summary", "school = 'okul-b'"), 9)


if __name__ == "__main__":
    unittest.main()
