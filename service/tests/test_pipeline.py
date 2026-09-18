"""Uçtan uca hat testleri: `FakeSource` → hesap → tavsiye → `BridgeStore`.

`FakeSource` imzaları `Source` protokolüyle birebir aynıdır; köprü ajanının
`FileSource`'u geldiğinde bu testler değişmeden çalışmalıdır.

Yazma yolu artık **köprüden** geçer: satırları `RecordingCaller` toplar
(`capture` testlerinde `CapturingCaller` tablolara da yazar). Gerçek bir
veritabanı yoktur — ZEKA'nın veritabanı yoktur.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.compute import clock
from src.pipeline import RunResult, discover_students, run_school
from src.report.capture import CapturingCaller
from src.source import FileSource
from src.store import (
    CAP_PURGE,
    CAP_RECOMMENDATION,
    CAP_RUN,
    CAP_SUMMARY,
    CAP_SWEEP,
    RETENTION_DAYS,
    BridgeStore,
    RecordingCaller,
)

from .fakes import (
    FakeSource,
    dataset,
    homework,
    write_fixtures,
)

DAY = 86_400_000
NOW = 1_699_963_200_000  # 2023-11-14 12:00 UTC
TERM_START = NOW - 150 * DAY


def _rows(caller: RecordingCaller, capability: str) -> list[dict]:
    """Toplanan çağrılardan bir yeteneğin satırlarını düzleştir."""
    rows: list[dict] = []
    for kind, _, payload in caller.calls:
        if kind == capability:
            rows.extend(payload.get("rows") or [])
    return rows


def _run_calls(caller: RecordingCaller) -> list[dict]:
    return [payload["run"] for kind, _, payload in caller.calls if kind == CAP_RUN]


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
    async def _run(self, data: dict, **kw) -> tuple[RunResult, RecordingCaller]:
        caller = RecordingCaller()
        store = BridgeStore(caller)
        fail = kw.pop("fail", set())
        ids = [k for k in data if not k.startswith("_")]
        args = {
            "now_ms": NOW,
            "student_ids": ids,
            "term_start_ms": TERM_START,
        }
        args.update(kw)
        result = await run_school(
            FakeSource(data, fail=fail), store.store_for("okul"), "okul", **args
        )
        return result, caller


class TestEndToEnd(PipelineTestCase):
    async def test_full_run_succeeds(self) -> None:
        result, caller = await self._run(dataset())
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.students_total, 12)
        self.assertEqual(result.students_ok, 12)
        self.assertEqual(result.students_failed, 0)
        self.assertGreater(result.rows_written, 0)
        self.assertTrue(caller.calls)

    async def test_insight_run_row_is_written_twice(self) -> None:
        _, caller = await self._run(dataset())
        runs = _run_calls(caller)
        self.assertEqual(len(runs), 2)  # başlangıç ("running") + bitiş

    async def test_run_key_is_tr_date_scoped(self) -> None:
        result, _ = await self._run(dataset())
        self.assertEqual(result.run_key(), f"okul_{clock.tr_date_key(NOW)}")

    async def test_summaries_carry_retention(self) -> None:
        _, caller = await self._run(dataset())
        row = _rows(caller, CAP_SUMMARY)[0]
        self.assertEqual(
            row["retain_until"],
            NOW + RETENTION_DAYS["student_summary"] * DAY,
        )

    async def test_cleanup_calls_go_out_once(self) -> None:
        """Koşu sonunda süpürme ve mezuniyet temizliği çağrılır.

        Kadro DİZİNDEN okunur (`student_ids=None`): temizlik yalnız tam kadro
        için koşar, çağıranın verdiği alt küme için koşmaz (bkz.
        `run_school` docstring'i).
        """
        _, caller = await self._run(dataset(), student_ids=None)
        kinds = [capability for capability, _, _ in caller.calls]
        self.assertEqual(kinds.count(CAP_SWEEP), 1)
        purge = [
            payload
            for capability, _, payload in caller.calls
            if capability == CAP_PURGE
        ]
        self.assertEqual(len(purge), 1)
        self.assertEqual(len(purge[0]["students"]), 12)

    async def test_low_performer_gets_review_band_via_cohort(self) -> None:
        """Kohort şube × ders düzeyinde kuruldu; düşük öğrenci ayrışıyor."""
        _, caller = await self._run(dataset())
        bands: dict[str, str] = {}
        for row in _rows(caller, CAP_SUMMARY):
            placement = row["marks"]["courses"]["course-1"]["placement"]
            bands[row["student"]] = str(placement["band"])
        self.assertEqual(bands["student-00"], "review")
        self.assertEqual(bands["student-01"], "on_track")


class TestPartialFailure(PipelineTestCase):
    async def test_one_failing_student_does_not_stop_the_run(self) -> None:
        data = dataset()
        result, _ = await self._run(data, fail={"student-03"})
        self.assertEqual(result.students_failed, 1)
        self.assertEqual(result.students_ok, 11)
        self.assertIn("fetch", result.failed_modules)
        # Hat devam etti ve satır yazıldı.
        self.assertGreater(result.rows_written, 0)

    async def test_write_failure_is_recorded_but_run_continues(self) -> None:
        caller = RecordingCaller(fail_times=10)  # ilk gruplar düşsün
        store = BridgeStore(caller)
        data = dataset()
        result = await run_school(
            FakeSource(data),
            store.store_for("okul"),
            "okul",
            now_ms=NOW,
            student_ids=[k for k in data if not k.startswith("_")],
            term_start_ms=TERM_START,
        )
        self.assertIn("store", result.failed_modules)


class TestBudget(PipelineTestCase):
    async def test_zero_budget_stops_and_records_pending(self) -> None:
        """Bütçe aşımında hat durur ve kalanlar bir sonraki koşuya yazılır."""
        result, caller = await self._run(dataset(), budget_ms=-1)
        self.assertTrue(result.budget_exceeded)
        self.assertEqual(result.status, "partial")
        self.assertEqual(len(result.pending_students), 12)
        self.assertEqual(result.students_ok, 0)
        # Koşu defteri satırı devredenleri taşır: bir sonraki koşu buradan
        # devam eder.
        self.assertEqual(len(_run_calls(caller)[-1]["pending_students"]), 12)

    async def test_generous_budget_completes(self) -> None:
        result, _ = await self._run(dataset(), budget_ms=60_000)
        self.assertFalse(result.budget_exceeded)
        self.assertEqual(result.pending_students, [])


class TestPrivacyInPipelineOutput(PipelineTestCase):
    async def test_attention_rows_have_no_score(self) -> None:
        _, caller = await self._run(dataset())
        rows = _rows(caller, CAP_SUMMARY)
        self.assertTrue(rows)
        for row in rows:
            for item in row["attention"]:
                self.assertIn("trigger", item)
                self.assertNotIn("score", item)
                self.assertNotIn("rank", item)

    async def test_t4_recommendations_never_address_the_student(self) -> None:
        _, caller = await self._run(dataset())
        rows = _rows(caller, CAP_RECOMMENDATION)
        self.assertTrue(rows)
        for row in rows:
            if row["product"] == "T4":
                self.assertEqual(row["audience_role"], "teacher")
                self.assertNotEqual(row["audience"], row["about"])

    async def test_every_stored_recommendation_has_evidence(self) -> None:
        _, caller = await self._run(dataset())
        rows = _rows(caller, CAP_RECOMMENDATION)
        self.assertTrue(rows)
        for row in rows:
            payload = {k: v for k, v in row["evidence"].items() if k != "limitation"}
            self.assertTrue(payload, row["rule_id"])


# ===========================================================================
# `FileSource` FIKSTURLERIYLE UCTAN UCA + KOPRU TABLOLARI
# ===========================================================================
#
# Yukaridaki testler `FakeSource` ile kosar (hizli, bellek ici). Asagidakiler
# ayni hatti **diskteki JSON fiksturlerle** ve `FileSource` ile kosturur;
# `CapturingCaller` satirlari tablolara yazar, boylece satirlari OKUYARAK
# dogrulariz. Veritabani gerekmez.


class TestFileSourceEndToEnd(unittest.IsolatedAsyncioTestCase):
    """Disk fikstürü → `FileSource` → hat. Veritabanı gerekmez."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.data = dataset(6)
        self.students = write_fixtures(self.root, "okul-a", self.data)
        self.caller = CapturingCaller()
        self.store = BridgeStore(self.caller)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    async def test_run_from_disk_fixtures(self) -> None:
        result = await run_school(
            FileSource(self.root),
            self.store.store_for("okul-a"),
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
            self.store.store_for("okul-a"),
            "okul-a",
            now_ms=NOW,
            term_start_ms=TERM_START,
        )
        self.assertEqual(result.students_failed, 1)
        self.assertEqual(result.students_ok, 5)
        self.assertIn("fetch", result.failed_modules)
        self.assertGreater(result.rows_written, 0)


class TestPipelineWritesThroughTheBridge(unittest.IsolatedAsyncioTestCase):
    """Satırlar gerçekten yazıldı mı: yakalanan tabloları OKUYARAK dogrula."""

    async def asyncSetUp(self) -> None:
        self.caller = CapturingCaller()
        self.store = BridgeStore(self.caller)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.data = dataset(12)
        write_fixtures(self.root, "okul-a", self.data)

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def _run(self, **kw) -> RunResult:
        args = {"now_ms": NOW, "term_start_ms": TERM_START}
        args.update(kw)
        return await run_school(
            FileSource(self.root), self.store.store_for("okul-a"), "okul-a", **args
        )

    @property
    def tables(self) -> dict[str, list[dict]]:
        return self.caller.as_tables()

    async def test_end_to_end_rows_land_and_match_the_report(self) -> None:
        result = await self._run()
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.students_ok, 12)

        summaries = len(self.tables["student_summary"])
        recs = len(self.tables["recommendation"])
        self.assertEqual(summaries, 12)
        self.assertGreater(recs, 0)
        # `rows_written` gercekten yazilan satir sayisidir.
        self.assertEqual(result.rows_written, summaries + recs)

    async def test_insight_run_is_written_and_ends_ok(self) -> None:
        result = await self._run()
        rows = self.tables["insight_run"]
        self.assertEqual(len(rows), 1)  # basta 'running', sonda 'ok' -- ayni anahtar
        row = rows[0]
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["students_total"], 12)
        self.assertEqual(row["students_ok"], 12)
        self.assertEqual(row["rows_written"], result.rows_written)
        self.assertFalse(row["budget_exceeded"])
        self.assertEqual(row["pending_students"], [])

    async def test_nested_compute_output_survives_the_bridge(self) -> None:
        """Ic ice hesap ciktisi satirda kaybolmadan duruyor."""
        await self._run()
        row = self.tables["student_summary"][0]
        self.assertIn("courses", row["marks"])
        self.assertIn("course-1", row["marks"]["courses"])
        self.assertIn("placement", row["marks"]["courses"]["course-1"])
        expected = {r["student"]: r for r in self.tables["student_summary"]}
        self.assertEqual(
            expected["student-00"]["marks"]["courses"]["course-1"]["placement"]["band"],
            "review",
        )
        self.assertIsInstance(row["attendance"], dict)
        self.assertIsInstance(row["submission"], dict)
        self.assertIsInstance(row["study"], dict)

    async def test_stored_recommendations_keep_their_evidence(self) -> None:
        await self._run()
        rows = self.tables["recommendation"]
        self.assertTrue(rows)
        for row in rows:
            payload = {k: v for k, v in row["evidence"].items() if k != "limitation"}
            self.assertTrue(payload, row["rule_id"])
            # `limitation` satırda KENDİ alanıdır; `evidence` içine katılması
            # sunucunun işidir (köprü sözleşmesi: alanı sunucu ekler).
            self.assertTrue(row["limitation"])

    async def test_partial_failure_keeps_the_written_rows(self) -> None:
        """Bir ogrenci duser, digerlerinin satirlari YAZILMIS kalir."""
        (self.root / "okul-a" / "attendance" / "student-05.json").write_text(
            '{"yanlis": []}', encoding="utf-8"
        )
        result = await self._run()
        self.assertEqual(result.students_failed, 1)
        self.assertEqual(result.students_ok, 11)
        self.assertEqual(len(self.tables["student_summary"]), 11)
        row = self.tables["insight_run"][0]
        self.assertEqual(row["students_failed"], 1)
        self.assertIn("fetch", row["failed_modules"])

    async def test_budget_exceeded_writes_pending_students(self) -> None:
        result = await self._run(budget_ms=-1)
        self.assertEqual(result.status, "partial")
        row = self.tables["insight_run"][0]
        self.assertTrue(row["budget_exceeded"])
        self.assertEqual(len(row["pending_students"]), 12)
        self.assertNotIn("student_summary", self.tables)

    async def test_second_run_is_idempotent(self) -> None:
        await self._run()
        before = len(self.tables["student_summary"])
        recs_before = len(self.tables["recommendation"])
        await self._run()
        self.assertEqual(len(self.tables["student_summary"]), before)
        self.assertEqual(len(self.tables["recommendation"]), recs_before)

    async def test_departed_student_leaves_the_purge_roster(self) -> None:
        """Ayrilan ogrenci temizlik listesinde YOKTUR: profili kalmamalidir.

        Silme backend'in isidir; burada dogrulanan sey gonderilen listenin
        gercekten daralmis olmasidir. Kadro her iki kosuda da DIZINDEN okunur:
        `student-11` okulun odev listesinden cikar ve temizlik onu istemez.
        """
        await self._run()
        self.assertEqual(len(self.tables["student_summary"]), 12)
        roster = [f"student-{i:02d}" for i in range(10)]
        data = {key: value for key, value in self.data.items() if key in roster}
        data["_school"] = {
            "homework_list": [homework("hw-school", "course-1", NOW + DAY, roster)]
        }
        write_fixtures(self.root, "okul-a", data)
        await self._run()
        purge_calls = [
            payload
            for capability, _, payload in self.caller.calls
            if capability == CAP_PURGE
        ]
        self.assertEqual(len(purge_calls), 2)
        self.assertEqual(len(purge_calls[-1]["students"]), 10)
        self.assertNotIn("student-11", purge_calls[-1]["students"])

    async def test_a_scoped_list_never_purges(self) -> None:
        """Cagiranin verdigi liste bir ALT KUME: temizlige verilemez.

        `refresh user_ids` ve `cli --students` boyle kosar; o listeyi "aktif
        kadro" saymak, adi gecmeyen herkesin turetilmis verisini sildirirdi.
        """
        await self._run(student_ids=[f"student-{i:02d}" for i in range(10)])
        self.assertEqual(self.tables["student_summary"][0]["student"], "student-00")
        self.assertNotIn(CAP_PURGE, [capability for capability, _, _ in self.caller.calls])


if __name__ == "__main__":
    unittest.main()
