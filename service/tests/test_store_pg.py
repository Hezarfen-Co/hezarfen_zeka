"""`store_pg.PgStore` — GERCEK PostgreSQL'e karsi.

Bu dosya sahte istemciyle kosmaz. Sebep deneyle sabit: SurrealDB surumunde
birim testlerin tamami yesilken gercek veritabaninda `type::thing()` diye bir
fonksiyon olmadigi icin TEK SATIR yazilamiyordu, ve `FLEXIBLE TYPE object`
yanlis sirada yazildigi icin bes alan sessizce dusuyordu. Mock bir istemci bu
hatalarin hicbirini goremez; yalnizca gercek sunucu gorebilir.

KOSMA KOSULU: `ZEKA_PG_DSN` tanimli ve adres cevap veriyor olmali. Yoksa
testler ATLANIR, birim testleri etkilenmez.

Her test kendi semasini (`search_path`) kullanir; boylece testler birbirinin
satirini gormez ve paralel kosabilir.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
import uuid
from pathlib import Path

from src.compute.model import (
    Audience,
    Confidence,
    QuestionSegment,
    Recommendation,
    StudentSegmentProfile,
    StudentSummary,
)
from src.store_pg import PgStore

DSN = os.environ.get("ZEKA_PG_DSN", "")
REPO = Path(__file__).resolve().parents[2]
ZEKA_DDL = REPO / "service" / "schema" / "postgres" / "school"
BACKEND_DDL = REPO.parent / "hezarfen_backend-main-yeni" / "hezarfen_backend-main" / "migrations"


def _available() -> bool:
    if not DSN:
        return False
    try:
        import psycopg

        with psycopg.connect(DSN, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:  # noqa: BLE001
        return False


AVAILABLE = _available()


def uid(n: int) -> str:
    """Sabit, okunabilir uuid — hangi satirin kim oldugu hata ciktisinda belli olsun."""
    return f"01920000-0000-7000-8000-{n:012d}"


@unittest.skipUnless(AVAILABLE, "ZEKA_PG_DSN yok/erisilemiyor; entegrasyon atlandi")
class PgStoreTest(unittest.IsolatedAsyncioTestCase):
    # Windows'un varsayilan ProactorEventLoop'u psycopg'nin async tarafiyla
    # calismaz ("Psycopg cannot use the 'ProactorEventLoop'"). Uretimde servis
    # Linux konteynerde kosar ve orada varsayilan zaten selector'dur; bu satir
    # yalnizca testin gelistirici makinesinde de kosabilmesi icin.
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    schema_name = ""

    async def asyncSetUp(self) -> None:
        import psycopg

        from src.pg_client import PsycopgClient

        self.schema_name = "t" + uuid.uuid4().hex[:12]
        self.conn = await psycopg.AsyncConnection.connect(DSN, autocommit=True)
        await self.conn.execute(f"CREATE SCHEMA {self.schema_name}")
        await self.conn.execute(f"SET search_path TO {self.schema_name}")

        # ZEKA'nin migration'i backend deposuna kopyalandi; ayni adli dosya
        # orada varsa iki kez uygulanmamali ("relation already exists").
        # Adlarla tekillestiriliyor, yol ile degil.
        applied: set[str] = set()
        for directory in ("control", "school"):
            for path in sorted((BACKEND_DDL / directory).glob("*.sql")):
                await self.conn.execute(path.read_text(encoding="utf-8"))
                applied.add(path.name)
        for path in sorted(ZEKA_DDL.glob("*.sql")):
            if path.name in applied:
                continue
            await self.conn.execute(path.read_text(encoding="utf-8"))

        await self._seed_school()
        self.client = PsycopgClient(self.conn)
        self.store = PgStore(self.client, batch_size=2)

    async def asyncTearDown(self) -> None:
        await self.conn.execute(f"DROP SCHEMA {self.schema_name} CASCADE")
        await self.conn.close()

    async def _seed_school(self) -> None:
        """Okul tarafinda ZEKA'nin FK'lerinin bakabilecegi asgari zincir."""
        await self.conn.execute(
            "INSERT INTO app_user (id, username, role, created_at) VALUES "
            "(%s,'ogr1','student',1),(%s,'ogr2','student',1),(%s,'ogt','teacher',1)",
            (uid(1), uid(2), uid(9)),
        )
        await self.conn.execute(
            "INSERT INTO course (id, creator, title, description, kind) "
            "VALUES (%s,%s,'Matematik','','course')",
            (uid(10), uid(9)),
        )
        await self.conn.execute(
            "INSERT INTO subject (id, course, name, description) "
            "VALUES (%s,%s,'Turev','')",
            (uid(11), uid(10)),
        )
        await self.conn.execute(
            "INSERT INTO exam (id, creator, course, title, description, kind) "
            "VALUES (%s,%s,%s,'Deneme','','quiz')",
            (uid(12), uid(9), uid(10)),
        )
        await self.conn.execute(
            "INSERT INTO exam_question (id, exam, text, kind, points, subject) "
            "VALUES (%s,%s,'Soru','multiple_choice',5,%s)",
            (uid(13), uid(12), uid(11)),
        )

    async def rows(self, sql: str, params: tuple = ()) -> list[tuple]:
        async with self.conn.cursor() as cur:
            await cur.execute(sql, params)
            return list(await cur.fetchall())

    # -- ozet + dikkat ------------------------------------------------------

    def _summary(self, student: str, *, attention: list | None = None) -> StudentSummary:
        return StudentSummary(
            school="okul",
            student=student,
            computed_at=1776056400000,
            marks={"courses": [{"course": uid(10), "average": 63.4}]},
            attendance={"courses": []},
            submission={"missing_rate": 0.18},
            study={"weekly_minutes": 213},
            attention=attention or [],
            confidence=Confidence.STABLE,
        )

    def _item(self, trigger: str, **evidence) -> dict:
        return {
            "trigger": trigger,
            "fact": f"{trigger} olgusu",
            "evidence": evidence or {"measure": trigger},
            "window_from": 1773464400000,
            "window_to": 1776056400000,
        }

    async def test_ozet_ve_dikkat_yazilir(self) -> None:
        summary = self._summary(
            uid(1),
            attention=[
                self._item("attendance"),
                self._item("mark_trend", course=uid(10)),
            ],
        )
        report = await self.store.write_summaries([summary])
        self.assertEqual(report.written, 1)
        self.assertEqual(report.skipped_batches, 0)

        got = await self.rows(
            "SELECT student, confidence, marks->'courses'->0->>'average' "
            "FROM zeka_student_summary"
        )
        self.assertEqual(len(got), 1)
        self.assertEqual(str(got[0][0]), uid(1))
        self.assertEqual(got[0][1], "stable")
        self.assertEqual(got[0][2], "63.4")

        items = await self.rows(
            "SELECT trigger, course, fact, window_from FROM zeka_attention_item "
            "ORDER BY ord"
        )
        self.assertEqual([r[0] for r in items], ["attendance", "mark_trend"])
        # Ders yalnizca not-egilimi maddesinde; kanitin icinden cikarilir.
        self.assertIsNone(items[0][1])
        self.assertEqual(str(items[1][1]), uid(10))
        # Gosterilecek CUMLE kayboluyor mu? Kolonu olmasaydi kaybolurdu.
        self.assertEqual(items[0][2], "attendance olgusu")
        self.assertEqual(items[0][3], 1773464400000)

    async def test_dikkat_maddeleri_sil_ve_yaz(self) -> None:
        """Artik uretilmeyen bir madde ekranda KALMAMALI."""
        await self.store.write_summaries(
            [self._summary(uid(1), attention=[self._item("attendance"),
                                              self._item("homework")])]
        )
        self.assertEqual(
            len(await self.rows("SELECT 1 FROM zeka_attention_item")), 2
        )
        # Ertesi gece yalniz biri uretildi.
        await self.store.write_summaries(
            [self._summary(uid(1), attention=[self._item("homework")])]
        )
        left = await self.rows("SELECT trigger FROM zeka_attention_item")
        self.assertEqual([r[0] for r in left], ["homework"])

    async def test_kanitsiz_dikkat_maddesi_yazilmaz(self) -> None:
        item = self._item("attendance")
        item["evidence"] = {}
        with self.assertLogs("src.store_pg", level="WARNING"):
            await self.store.write_summaries(
                [self._summary(uid(1), attention=[item])]
            )
        self.assertEqual(
            await self.rows("SELECT 1 FROM zeka_attention_item"), []
        )

    # -- tavsiye ------------------------------------------------------------

    def _rec(self, *, about: str, evidence: dict | None = None) -> Recommendation:
        return Recommendation(
            school="okul",
            audience=uid(9),
            audience_role=Audience.TEACHER,
            product="T4",
            rule_id="T4.homework",
            evidence=evidence or {"missing_rate": 0.44},
            computed_at=1776056400000,
            expires_at=1778648400000,
            about=about,
            course=uid(10),
            confidence=Confidence.STABLE,
            limitation="Kohort-goreli esik.",
        )

    async def test_ayni_kural_farkli_ogrenciler_cakismaz(self) -> None:
        """Ogretmenin iki ogrenci icin ayni kurali IKI satir olmali.

        Dogal anahtarin kapsam parcasi yalnizca derse baksaydi ikisi tek satira
        coker ve bir ogrenci sessizce kaybolurdu.
        """
        report = await self.store.write_recommendations(
            [self._rec(about=uid(1)), self._rec(about=uid(2))]
        )
        self.assertEqual(report.written, 2)
        got = await self.rows("SELECT about FROM zeka_recommendation ORDER BY about")
        self.assertEqual([str(r[0]) for r in got], [uid(1), uid(2)])

    async def test_kapatma_izi_gece_yaziminda_korunur(self) -> None:
        """KVKK m.11 izi: gece kosusu insan mudahalesini SILMEZ."""
        await self.store.write_recommendations([self._rec(about=uid(1))])
        await self.conn.execute(
            "UPDATE zeka_recommendation SET dismissed_at=%s, dismissed_by=%s, "
            "dismiss_reason=%s",
            (1776142800000, uid(9), "ogrenci rapor verdi"),
        )
        await self.store.write_recommendations(
            [self._rec(about=uid(1), evidence={"missing_rate": 0.46})]
        )
        got = await self.rows(
            "SELECT dismissed_at, dismiss_reason, evidence->>'missing_rate' "
            "FROM zeka_recommendation"
        )
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0][0], 1776142800000)
        self.assertEqual(got[0][1], "ogrenci rapor verdi")
        # ...ama kanit tazelenmis olmali.
        self.assertEqual(got[0][2], "0.46")

    async def test_kanitsiz_tavsiye_reddedilir(self) -> None:
        rec = self._rec(about=uid(1), evidence={"x": 1})
        object.__setattr__(rec, "evidence", {})
        with self.assertLogs("src.store_pg", level="WARNING"):
            report = await self.store.write_recommendations([rec])
        self.assertEqual(report.rejected, 1)
        self.assertEqual(report.written, 0)
        self.assertEqual(await self.rows("SELECT 1 FROM zeka_recommendation"), [])

    # -- segment ------------------------------------------------------------

    def _segment(self) -> QuestionSegment:
        return QuestionSegment(
            school="okul",
            question=uid(13),
            labels={
                "bilissel_talep": "uygulama",
                "dikkat_tuzagi": "var",
                "okuma_yuku": "dusuk",
                "adim_sayisi": "tek_adim",
            },
            confidences={
                "bilissel_talep": 0.91,
                "dikkat_tuzagi": 0.78,
                "okuma_yuku": 0.95,
                "adim_sayisi": 0.61,
            },
            confidence=Confidence.STABLE,
            exam=uid(12),
            course=uid(10),
            subject=uid(11),
            trap_choice="c",
            rationale="Turev kurali dogrudan uygulanir.",
            model="deepseek-v4-pro",
            prompt_version="v3",
            downstream_dimensions=("bilissel_talep", "dikkat_tuzagi", "okuma_yuku"),
            experimental_dimensions=("adim_sayisi",),
            computed_at=1776056400000,
        )

    async def test_segment_ve_boyut_ayrimi(self) -> None:
        report = await self.store.write_question_segments([self._segment()])
        self.assertEqual(report.written, 1)
        got = await self.rows(
            "SELECT bilissel_talep, confidence_adim_sayisi, trap_choice "
            "FROM zeka_question_segment"
        )
        self.assertEqual(got[0][0], "uygulama")
        self.assertAlmostEqual(got[0][1], 0.61)
        self.assertEqual(got[0][2], "c")

        dims = await self.rows(
            "SELECT dimension, role FROM zeka_question_segment_dimension "
            "ORDER BY ord"
        )
        self.assertEqual(
            dims,
            [
                ("bilissel_talep", "downstream"),
                ("dikkat_tuzagi", "downstream"),
                ("okuma_yuku", "downstream"),
                ("adim_sayisi", "experimental"),
            ],
        )

    async def test_profil_contrast_yazilir(self) -> None:
        profile = StudentSegmentProfile(
            school="okul",
            student=uid(1),
            dimension="bilissel_talep",
            label="analiz",
            n_answers=86,
            n_correct=31,
            overall_n_answers=412,
            overall_accuracy=240 / 412,
            confidence=Confidence.STABLE,
            computed_at=1776056400000,
        )
        report = await self.store.write_segment_profiles([profile])
        self.assertEqual(report.written, 1)
        got = await self.rows(
            "SELECT accuracy, overall_accuracy, contrast "
            "FROM zeka_student_segment_profile"
        )
        self.assertAlmostEqual(got[0][0], 0.360465, places=5)
        self.assertAlmostEqual(got[0][2], got[0][0] - got[0][1], places=6)
        # Kontrast negatif: ogrenci KENDI genel seviyesine gore geride.
        self.assertLess(got[0][2], 0)

    # -- kosu defteri -------------------------------------------------------

    async def test_kosu_defteri_ve_devreden_liste(self) -> None:
        ok = await self.store.write_run(
            {
                "started_at": 1776056400000,
                "status": "partial",
                "students_total": 250,
                "students_ok": 231,
                "budget_ms": 3600000,
                "budget_exceeded": True,
                "pending_students": [uid(1), uid(2)],
                "failed_modules": ["submission"],
            },
            "okul_2026-04-13",
        )
        self.assertTrue(ok)
        self.assertEqual(await self.store.last_pending("okul"), [uid(1), uid(2)])
        # Ikinci yazim cocuklari COGALTMAMALI.
        await self.store.write_run(
            {
                "started_at": 1776056400000,
                "status": "ok",
                "budget_ms": 3600000,
                "pending_students": [uid(2)],
            },
            "okul_2026-04-13",
        )
        self.assertEqual(await self.store.last_pending("okul"), [uid(2)])
        runs = await self.rows("SELECT run_day, status FROM zeka_run")
        self.assertEqual(runs, [("2026-04-13", "ok")])

    # -- supurme ve mezuniyet ----------------------------------------------

    async def test_supurme_once_cocugu_siler(self) -> None:
        """FK'ler NO ACTION; ters sirada supurme FK ihlaliyle duserdi."""
        await self.store.write_summaries(
            [self._summary(uid(1), attention=[self._item("attendance")])]
        )
        await self.store.write_question_segments([self._segment()])
        await self.store.write_run(
            {"started_at": 1, "status": "ok", "budget_ms": 1,
             "pending_students": [uid(1)], "failed_modules": ["x"]},
            "2020-01-01",
        )
        # Her seyin saklama suresi gecmis olsun.
        for table in ("zeka_student_summary", "zeka_question_segment",
                      "zeka_run", "zeka_recommendation",
                      "zeka_student_segment_profile"):
            await self.conn.execute(f"UPDATE {table} SET retain_until = 1")

        results = await self.store.sweep(now_ms=10_000)
        self.assertTrue(all(results.values()), results)
        for table in ("zeka_attention_item", "zeka_student_summary",
                      "zeka_question_segment_dimension", "zeka_question_segment",
                      "zeka_run_pending", "zeka_run_failed_module", "zeka_run"):
            self.assertEqual(
                await self.rows(f"SELECT 1 FROM {table}"), [], f"{table} bosalmadi"
            )

    async def test_mezuniyet_temizligi(self) -> None:
        await self.store.write_summaries(
            [self._summary(uid(1), attention=[self._item("attendance")]),
             self._summary(uid(2))]
        )
        await self.store.write_recommendations([self._rec(about=uid(1))])
        ok = await self.store.purge_departed("okul", [uid(2)])
        self.assertTrue(ok)
        left = await self.rows("SELECT student FROM zeka_student_summary")
        self.assertEqual([str(r[0]) for r in left], [uid(2)])
        self.assertEqual(await self.rows("SELECT 1 FROM zeka_attention_item"), [])
        self.assertEqual(await self.rows("SELECT 1 FROM zeka_recommendation"), [])

    async def test_bos_aktif_liste_hicbir_seyi_silmez(self) -> None:
        """Bos liste "okul bosaldi" degil, "listeyi cekemedik" demektir."""
        await self.store.write_summaries([self._summary(uid(1))])
        with self.assertLogs("src.store_pg", level="WARNING"):
            ok = await self.store.purge_departed("okul", [])
        self.assertFalse(ok)
        self.assertEqual(
            len(await self.rows("SELECT 1 FROM zeka_student_summary")), 1
        )

    # -- hata davranisi -----------------------------------------------------

    async def test_dusen_grup_hatti_durdurmaz(self) -> None:
        """Olmayan ogrenci -> FK ihlali. Grup atlanir, kosu devam eder."""
        good = self._summary(uid(1))
        bad = self._summary(uid(777))          # app_user'da yok
        with self.assertLogs("src.store_pg", level="WARNING"):
            report = await self.store.write_summaries([bad, good])
        # batch_size=2 -> ikisi ayni grupta, grup tumuyle atlanir.
        self.assertEqual(report.skipped_batches, 1)
        self.assertEqual(report.written, 0)
        self.assertEqual(await self.rows("SELECT 1 FROM zeka_student_summary"), [])


if __name__ == "__main__":
    unittest.main()
