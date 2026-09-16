"""Uçtan uca hat testleri: `FakeSource` → hesap → tavsiye → `Store`.

`FakeSource` imzaları `Source` protokolüyle birebir aynıdır; köprü ajanının
`FileSource`'u geldiğinde bu testler değişmeden çalışmalıdır.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.compute import clock
from src.pipeline import RunResult, discover_students, run_school
from src.source import FileSource
from src.store import RETENTION_DAYS, CollectingClient, Store

from . import zeka_db

from .fakes import (
    FakeSource,
    course_attendance,
    course_marks,
    homework,
    pomodoro,
    profile,
    report_entry,
)

DAY = 86_400_000
HOUR = 3_600_000
NOW = 1_699_963_200_000  # 2023-11-14 12:00 UTC
TERM_START = NOW - 150 * DAY


def _student(uid: str, class_id: str, marks: list[int], present: int, absent: int):
    """Bir öğrencinin tüm kaynak verisi."""
    base = NOW - 100 * DAY
    return {
        "profile": profile(uid, [class_id], ["course-1"]),
        "marks": [course_marks("course-1", marks, base, teachers=["teacher-1"])],
        "attendance": [course_attendance("course-1", present=present, absent=absent)],
        "pomodoro": [
            pomodoro((clock.tr_day(NOW) - d) * DAY + 10 * HOUR - clock.TR_OFFSET_MS)
            for d in range(1, 7)
        ],
        "homework_report": [
            report_entry(f"hw-{uid}-{i}", "course-1", NOW - (i + 1) * DAY,
                         submitted=True)
            for i in range(6)
        ],
        "homework_list": [homework("upcoming", "course-1", NOW + 6 * HOUR, [uid])],
    }


def _dataset(n: int = 12) -> dict[str, dict]:
    """Bir şube, bir ders, `n` öğrenci. Biri belirgin biçimde düşük."""
    data: dict[str, dict] = {}
    for i in range(n):
        uid = f"student-{i:02d}"
        if i == 0:
            data[uid] = _student(uid, "class-A", [40, 41, 39, 42, 40, 38], 60, 40)
        else:
            data[uid] = _student(uid, "class-A", [70, 72, 71, 69, 70, 71], 95, 5)
    data["_school"] = {
        "homework_list": [
            homework("hw-school", "course-1", NOW + DAY, list(data.keys()))
        ]
    }
    return data


class TestDiscoverStudents(unittest.TestCase):
    def test_students_derived_from_assigned_field(self) -> None:
        import asyncio

        data = {"_school": {"homework_list": [homework("h", "c", NOW, ["a", "b", "a"])]}}
        found = asyncio.run(discover_students(FakeSource(data), "okul"))
        self.assertEqual(found, ["a", "b"])

    def test_unassigned_homework_yields_nothing(self) -> None:
        import asyncio

        data = {"_school": {"homework_list": [homework("h", "c", NOW, None)]}}
        self.assertEqual(asyncio.run(discover_students(FakeSource(data), "okul")), [])


class PipelineTestCase(unittest.IsolatedAsyncioTestCase):
    async def _run(self, data: dict, **kw) -> tuple[RunResult, CollectingClient]:
        client = CollectingClient()
        store = Store(client)
        fail = kw.pop("fail", set())
        ids = [k for k in data if not k.startswith("_")]
        args = {
            "now_ms": NOW,
            "student_ids": ids,
            "term_start_ms": TERM_START,
        }
        args.update(kw)
        result = await run_school(
            FakeSource(data, fail=fail), store, "okul", **args
        )
        return result, client


class TestEndToEnd(PipelineTestCase):
    async def test_full_run_succeeds(self) -> None:
        result, client = await self._run(_dataset())
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.students_total, 12)
        self.assertEqual(result.students_ok, 12)
        self.assertEqual(result.students_failed, 0)
        self.assertGreater(result.rows_written, 0)
        self.assertTrue(client.statements)

    async def test_insight_run_row_is_written_twice(self) -> None:
        _, client = await self._run(_dataset())
        runs = [
            s
            for s in client.statements
            if "insight_run" in s[0] and not s[0].startswith("DELETE")
        ]
        self.assertEqual(len(runs), 2)  # başlangıç ("running") + bitiş

    async def test_run_key_is_tr_date_scoped(self) -> None:
        result, _ = await self._run(_dataset())
        self.assertEqual(result.run_key(), f"okul_{clock.tr_date_key(NOW)}")

    async def test_summaries_carry_retention(self) -> None:
        _, client = await self._run(_dataset())
        summary = next(
            variables
            for sql, variables in client.statements
            if "student_summary" in sql and "DELETE" not in sql
        )
        row = summary["v0"]
        self.assertEqual(
            row["retain_until"],
            NOW + RETENTION_DAYS["student_summary"] * DAY,
        )

    async def test_sweep_runs_for_every_table(self) -> None:
        _, client = await self._run(_dataset())
        deletes = [sql for sql, _ in client.statements if sql.startswith("DELETE")]
        for table in RETENTION_DAYS:
            self.assertTrue(any(table in sql for sql in deletes), table)

    async def test_low_performer_gets_review_band_via_cohort(self) -> None:
        """Kohort şube × ders düzeyinde kuruldu; düşük öğrenci ayrışıyor."""
        _, client = await self._run(_dataset())
        rows = [
            variables
            for sql, variables in client.statements
            if "student_summary" in sql and "DELETE" not in sql
        ]
        bands: dict[str, str] = {}
        for batch in rows:
            index = 0
            while f"v{index}" in batch:
                row = batch[f"v{index}"]
                placement = row["marks"]["courses"]["course-1"]["placement"]
                bands[row["student"]] = str(placement["band"])
                index += 1
        self.assertEqual(bands["student-00"], "review")
        self.assertEqual(bands["student-01"], "on_track")


class TestPartialFailure(PipelineTestCase):
    async def test_one_failing_student_does_not_stop_the_run(self) -> None:
        data = _dataset()
        result, _ = await self._run(data, fail={"student-03"})
        self.assertEqual(result.students_failed, 1)
        self.assertEqual(result.students_ok, 11)
        self.assertIn("fetch", result.failed_modules)
        # Hat devam etti ve satır yazıldı.
        self.assertGreater(result.rows_written, 0)

    async def test_write_failure_is_recorded_but_run_continues(self) -> None:
        client = CollectingClient()
        client.fail_times = 10  # ilk gruplar düşsün
        store = Store(client)
        data = _dataset()
        result = await run_school(
            FakeSource(data),
            store,
            "okul",
            now_ms=NOW,
            student_ids=[k for k in data if not k.startswith("_")],
            term_start_ms=TERM_START,
        )
        self.assertIn("store", result.failed_modules)


class TestBudget(PipelineTestCase):
    async def test_zero_budget_stops_and_records_pending(self) -> None:
        """Bütçe aşımında hat durur ve kalanlar bir sonraki koşuya yazılır."""
        result, _ = await self._run(_dataset(), budget_ms=-1)
        self.assertTrue(result.budget_exceeded)
        self.assertEqual(result.status, "partial")
        self.assertEqual(len(result.pending_students), 12)
        self.assertEqual(result.students_ok, 0)

    async def test_generous_budget_completes(self) -> None:
        result, _ = await self._run(_dataset(), budget_ms=60_000)
        self.assertFalse(result.budget_exceeded)
        self.assertEqual(result.pending_students, [])


class TestPrivacyInPipelineOutput(PipelineTestCase):
    async def test_attention_rows_have_no_score(self) -> None:
        _, client = await self._run(_dataset())
        for sql, variables in client.statements:
            if "student_summary" not in sql or "DELETE" in sql:
                continue
            index = 0
            while f"v{index}" in variables:
                for item in variables[f"v{index}"]["attention"]:
                    self.assertIn("trigger", item)
                    self.assertNotIn("score", item)
                    self.assertNotIn("rank", item)
                index += 1

    async def test_t4_recommendations_never_address_the_student(self) -> None:
        _, client = await self._run(_dataset())
        for sql, variables in client.statements:
            if "recommendation" not in sql or "DELETE" in sql:
                continue
            index = 0
            while f"v{index}" in variables:
                row = variables[f"v{index}"]
                if row["product"] == "T4":
                    self.assertEqual(row["audience_role"], "teacher")
                    self.assertNotEqual(row["audience"], row["about"])
                index += 1

    async def test_every_stored_recommendation_has_evidence(self) -> None:
        _, client = await self._run(_dataset())
        seen = 0
        for sql, variables in client.statements:
            if "recommendation" not in sql or "DELETE" in sql:
                continue
            index = 0
            while f"v{index}" in variables:
                row = variables[f"v{index}"]
                payload = {
                    k: v for k, v in row["evidence"].items() if k != "limitation"
                }
                self.assertTrue(payload, row["rule_id"])
                seen += 1
                index += 1
        self.assertGreater(seen, 0)


# ===========================================================================
# `FileSource` FIKSTURLERIYLE UCTAN UCA + GERCEK SurrealDB
# ===========================================================================
#
# Yukaridaki testler `FakeSource` ile kosar (hizli, bellek ici). Asagidakiler
# ayni hatti **diskteki JSON fiksturlerle** ve `FileSource` ile kosturur:
# "imzalar ayni" iddiasi boylece iddia olmaktan cikip kanita donusur.


class TestFileSourceEndToEnd(unittest.IsolatedAsyncioTestCase):
    """Disk fiksturu -> `FileSource` -> hat. Veritabani gerekmez."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.data = zeka_db.dataset(6)
        self.students = zeka_db.write_fixtures(self.root, "okul-a", self.data)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    async def test_run_from_disk_fixtures(self) -> None:
        client = CollectingClient()
        result = await run_school(
            FileSource(self.root),
            Store(client),
            "okul-a",
            now_ms=NOW,
            term_start_ms=TERM_START,
        )
        # Ogrenci listesi fiksturdeki `_service.json` odevinden turetildi.
        self.assertEqual(result.students_total, 6)
        self.assertEqual(result.students_ok, 6)
        self.assertEqual(result.status, "ok")
        self.assertGreater(result.rows_written, 0)

    async def test_missing_fixture_file_fails_only_that_student(self) -> None:
        """Bir ogrencinin dosyasi bozuksa yalniz o ogrenci duser."""
        (self.root / "okul-a" / "marks" / "student-02.json").write_text(
            '{"items": []}', encoding="utf-8"  # yanlis zarf -> unexpected_shape
        )
        result = await run_school(
            FileSource(self.root),
            Store(CollectingClient()),
            "okul-a",
            now_ms=NOW,
            term_start_ms=TERM_START,
        )
        self.assertEqual(result.students_failed, 1)
        self.assertEqual(result.students_ok, 5)
        self.assertIn("fetch", result.failed_modules)
        self.assertGreater(result.rows_written, 0)


@zeka_db.requires_db
class TestPipelineAgainstSurreal(unittest.IsolatedAsyncioTestCase):
    """Hat gercekten yaziyor mu: satirlari OKUYARAK dogrula."""

    async def asyncSetUp(self) -> None:
        self.client = zeka_db.fresh_schema_client("hat")
        self.store = Store(self.client)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.data = zeka_db.dataset(12)
        zeka_db.write_fixtures(self.root, "okul-a", self.data)

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def _run(self, **kw):
        args = {"now_ms": NOW, "term_start_ms": TERM_START}
        args.update(kw)
        return await run_school(
            FileSource(self.root), self.store, "okul-a", **args
        )

    async def test_end_to_end_rows_land_and_match_the_report(self) -> None:
        result = await self._run()
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.students_ok, 12)

        summaries = zeka_db.count_rows(self.client, "student_summary")
        recs = zeka_db.count_rows(self.client, "recommendation")
        self.assertEqual(summaries, 12)
        self.assertGreater(recs, 0)
        # `rows_written` gercekten yazilan satir sayisidir.
        self.assertEqual(result.rows_written, summaries + recs)

    async def test_insight_run_is_written_and_ends_ok(self) -> None:
        result = await self._run()
        rows = zeka_db.select(self.client, "SELECT * FROM insight_run;")
        self.assertEqual(len(rows), 1)  # basta 'running', sonda 'ok' -- ayni anahtar
        row = rows[0]
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["students_total"], 12)
        self.assertEqual(row["students_ok"], 12)
        self.assertEqual(row["rows_written"], result.rows_written)
        self.assertFalse(row["budget_exceeded"])
        self.assertEqual(row["pending_students"], [])

    async def test_nested_compute_output_survives_the_round_trip(self) -> None:
        """FLEXIBLE alanlar: ic ice hesap ciktisi kaybolmadan geri okunuyor."""
        await self._run()
        row = zeka_db.select(
            self.client,
            "SELECT * FROM student_summary WHERE student = 'student-00';",
        )[0]
        self.assertIn("courses", row["marks"])
        self.assertIn("course-1", row["marks"]["courses"])
        self.assertIn("placement", row["marks"]["courses"]["course-1"])
        self.assertEqual(
            row["marks"]["courses"]["course-1"]["placement"]["band"], "review"
        )
        self.assertIsInstance(row["attendance"], dict)
        self.assertIsInstance(row["submission"], dict)
        self.assertIsInstance(row["study"], dict)

    async def test_stored_recommendations_keep_their_evidence(self) -> None:
        await self._run()
        rows = zeka_db.select(self.client, "SELECT * FROM recommendation;")
        self.assertTrue(rows)
        for row in rows:
            payload = {k: v for k, v in row["evidence"].items() if k != "limitation"}
            self.assertTrue(payload, row["rule_id"])
            self.assertTrue(row["evidence"]["limitation"])

    async def test_partial_failure_keeps_the_written_rows(self) -> None:
        """Bir ogrenci duser, digerlerinin satirlari veritabaninda KALIR."""
        (self.root / "okul-a" / "attendance" / "student-05.json").write_text(
            '{"yanlis": []}', encoding="utf-8"
        )
        result = await self._run()
        self.assertEqual(result.students_failed, 1)
        self.assertEqual(result.students_ok, 11)
        self.assertEqual(zeka_db.count_rows(self.client, "student_summary"), 11)
        row = zeka_db.select(self.client, "SELECT * FROM insight_run;")[0]
        self.assertEqual(row["students_failed"], 1)
        self.assertIn("fetch", row["failed_modules"])

    async def test_budget_exceeded_writes_pending_students(self) -> None:
        result = await self._run(budget_ms=-1)
        self.assertEqual(result.status, "partial")
        row = zeka_db.select(self.client, "SELECT * FROM insight_run;")[0]
        self.assertTrue(row["budget_exceeded"])
        self.assertEqual(len(row["pending_students"]), 12)
        self.assertEqual(zeka_db.count_rows(self.client, "student_summary"), 0)

    async def test_second_run_is_idempotent(self) -> None:
        await self._run()
        before = zeka_db.count_rows(self.client, "student_summary")
        recs_before = zeka_db.count_rows(self.client, "recommendation")
        await self._run()
        self.assertEqual(zeka_db.count_rows(self.client, "student_summary"), before)
        self.assertEqual(zeka_db.count_rows(self.client, "recommendation"), recs_before)

    async def test_departed_student_is_purged_by_the_pipeline(self) -> None:
        await self._run()
        self.assertEqual(zeka_db.count_rows(self.client, "student_summary"), 12)
        # Ikinci kosuda liste daraliyor: ayrilan ogrencinin profili kalmamali.
        await run_school(
            FileSource(self.root),
            self.store,
            "okul-a",
            now_ms=NOW,
            term_start_ms=TERM_START,
            student_ids=[f"student-{i:02d}" for i in range(10)],
        )
        kalanlar = {
            r["student"]
            for r in zeka_db.select(self.client, "SELECT student FROM student_summary;")
        }
        self.assertEqual(len(kalanlar), 10)
        self.assertNotIn("student-11", kalanlar)


if __name__ == "__main__":
    unittest.main()
