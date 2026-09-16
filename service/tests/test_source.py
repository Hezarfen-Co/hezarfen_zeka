"""Veri erisim cephesinin testleri.

En onemlisi `ForbiddenSurfaceTests`: cephede yemek, odeme, diyet, mesaj ve
sohbet yontemi OLMADIGINI dogrular. O test kirilirsa yapisal kapi acilmis
demektir.
"""

from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from pathlib import Path

from src import config, protocol, source


class ForbiddenSurfaceTests(unittest.TestCase):
    def test_no_forbidden_data_methods(self):
        # Yapisal kapi: hesap modulu yemek/odeme/diyet/mesaj/sohbet verisini
        # ISTEYEMEZ, cunku cagiracagi fonksiyon yok.
        for holder in (source.Source, source.BridgeSource, source.FileSource):
            for name in dir(holder):
                if name.startswith("_"):
                    continue
                lowered = name.lower()
                for term in source.FORBIDDEN_DATA_TERMS:
                    self.assertNotIn(
                        term,
                        lowered,
                        f"{holder.__name__}.{name} yasakli veri terimini ('{term}') tasiyor",
                    )

    def test_surface_is_exactly_the_eight_declared_methods(self):
        declared = {
            name
            for name in dir(source.Source)
            if not name.startswith("_") and callable(getattr(source.Source, name, None))
        }
        self.assertEqual(declared, set(source.SOURCE_METHODS))

    def test_both_implementations_cover_the_whole_surface(self):
        for holder in (source.BridgeSource, source.FileSource):
            for name in source.SOURCE_METHODS:
                method = getattr(holder, name, None)
                self.assertTrue(
                    callable(method), f"{holder.__name__}.{name} eksik"
                )
                self.assertTrue(
                    inspect.iscoroutinefunction(method),
                    f"{holder.__name__}.{name} es zamansiz olmali",
                )

    def test_signatures_match_the_protocol(self):
        for name in source.SOURCE_METHODS:
            expected = inspect.signature(getattr(source.Source, name))
            for holder in (source.BridgeSource, source.FileSource):
                self.assertEqual(
                    inspect.signature(getattr(holder, name)),
                    expected,
                    f"{holder.__name__}.{name} imzasi arayuzden sapiyor",
                )

    def test_every_method_documents_its_allowlist_path(self):
        for name, template in source._TEMPLATES.items():
            doc = inspect.getdoc(getattr(source.BridgeSource, name)) or ""
            self.assertIn(template, doc, f"source.{name} docstring'i yolunu yazmiyor")

    def test_every_template_is_on_the_backend_allowlist(self):
        for name, template in source._TEMPLATES.items():
            self.assertIn(
                template,
                protocol.AI_API_ALLOWLIST,
                f"source.{name} izin listesi disinda bir yol kullaniyor",
            )


class _RecordingClient:
    """Sahte kopru istemcisi: cagrilari kaydeder, hazir cevap doner."""

    def __init__(self, body=None, status: int = 200):
        self.calls: list[dict] = []
        self._body = body
        self._status = status

    async def api_get(self, school, path, query=None, on_behalf_of=None):
        self.calls.append(
            {
                "school": school,
                "path": path,
                "query": query,
                "on_behalf_of": on_behalf_of,
            }
        )
        return protocol.ApiResponse("01J", school, self._status, self._body)


class BridgeSourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_marks_uses_the_allowlisted_path(self):
        client = _RecordingClient(body={"user": "u1", "courses": [{"average": 88}]})
        rows = await source.BridgeSource(client).marks("demo", "u1")
        self.assertEqual(rows, [{"average": 88}])
        self.assertEqual(client.calls[0]["path"], "/marks/u1")
        self.assertEqual(client.calls[0]["school"], "demo")

    async def test_page_envelope_is_unwrapped(self):
        client = _RecordingClient(body={"items": [{"id": "n1"}], "total": 1})
        rows = await source.BridgeSource(client).notes("demo", "u1")
        self.assertEqual(rows, [{"id": "n1"}])
        self.assertEqual(client.calls[0]["on_behalf_of"], "u1")

    async def test_course_notes_sends_the_required_course_query(self):
        client = _RecordingClient(body={"items": [], "total": 0})
        await source.BridgeSource(client).course_notes("demo", "c1")
        self.assertEqual(client.calls[0]["path"], "/course-notes")
        self.assertEqual(client.calls[0]["query"], "course=c1")

    async def test_course_notes_without_a_course_sends_nothing(self):
        client = _RecordingClient(body={"items": [], "total": 0})
        self.assertEqual(await source.BridgeSource(client).course_notes("demo"), [])
        self.assertEqual(client.calls, [])

    async def test_404_is_an_empty_result_not_an_error(self):
        client = _RecordingClient(body=None, status=404)
        self.assertIsNone(await source.BridgeSource(client).profile("demo", "u1"))

    async def test_empty_school_is_refused_before_the_wire(self):
        client = _RecordingClient(body={"items": []})
        with self.assertRaises(source.SourceError):
            await source.BridgeSource(client).marks("", "u1")
        self.assertEqual(client.calls, [])

    async def test_a_path_outside_the_allowlist_is_blocked(self):
        # Cephe izin listesi disina cikamaz; ciksa bile ikinci kemer tutar.
        client = _RecordingClient(body={"items": []})
        with self.assertRaises(source.SourceError) as caught:
            await source.BridgeSource(client)._get("marks", "demo", "/meals")
        self.assertEqual(caught.exception.code, protocol.ApiErrorCode.PATH_NOT_ALLOWED)
        self.assertEqual(client.calls, [])

    async def test_bridge_refusal_becomes_a_source_error(self):
        class _Refusing:
            async def api_get(self, school, path, query=None, on_behalf_of=None):
                raise protocol.ApiRefused(
                    protocol.ApiErrorCode.UNKNOWN_SCHOOL, "boyle bir okul yok"
                )

        with self.assertRaises(source.SourceError) as caught:
            await source.BridgeSource(_Refusing()).marks("yok-boyle", "u1")
        self.assertEqual(caught.exception.code, protocol.ApiErrorCode.UNKNOWN_SCHOOL)


class RealResponseShapeTests(unittest.IsolatedAsyncioTestCase):
    """Her uc icin backend struct'larindan TURETILMIS gercek bicimli yanitlar.

    Bu sinif, `_as_list()` doneminde kacirilan hatanin nobetcisidir: o surumde
    `/marks` ve `/attendance` yanitlari `items` tasimadigi icin sessizce `[]`
    donuyordu. Asagidaki govdelerin her biri backend kaynagindaki struct'in
    alanlarina birebir uyar.
    """

    # web/marks.rs:65 MarksReport -> web/marks.rs:50 CourseMarks -> :33 MarkEntry
    MARKS_REPORT = {
        "user": "u1",
        "courses": [
            {
                "course": {"id": "c1", "name": "Matematik"},
                "results": [
                    {
                        "exam": "e1",
                        "title": "1. Yazili",
                        "kind": "yazili",
                        "weight": 2,
                        "mark": 72,
                        "grade": "CB",
                        "graded_by": "t1",
                    }
                ],
                "average": 72.0,
                "average_grade": "CB",
            },
            {
                "course": {"id": "c2", "name": "Fizik"},
                "results": [],
                "average": None,
                "average_grade": None,
            },
        ],
        "overall_average": 72.0,
        "overall_grade": "CB",
    }

    # web/attendance.rs:84 AttendanceReport -> :76 CourseAttendance -> :31 StatusCounts
    ATTENDANCE_REPORT = {
        "user": "u1",
        "events": {
            "present": 3,
            "absent": 0,
            "late": 0,
            "excused": 0,
            "custom": {},
            "total": 3,
            "rate": 1.0,
        },
        "sessions": {
            "present": 40,
            "absent": 6,
            "late": 4,
            "excused": 2,
            "custom": {"gorevli": 1},
            "total": 53,
            "rate": 0.88,
        },
        "courses": [
            {
                "course": {"id": "c1", "name": "Matematik"},
                "counts": {
                    "present": 20,
                    "absent": 4,
                    "late": 2,
                    "excused": 1,
                    "custom": {},
                    "total": 27,
                    "rate": 0.8461538461538461,
                },
            }
        ],
    }

    # web/pomodoro.rs:78 PomodoroLog -> :40 PomodoroResponse
    POMODORO_LOG = {
        "items": [
            {
                "id": "p1",
                "user": "u1",
                "started_at": 1776067200000,
                "finished_at": 1776068700000,
                "duration_ms": 1500000,
                "counted": True,
            },
            {
                "id": "p2",
                "user": "u1",
                "started_at": 1776070000000,
                "finished_at": None,
                "duration_ms": None,
                "counted": None,
            },
        ],
        "total": 256,
        "limit": 100,
        "offset": 0,
        "total_focus_ms": 384000000,
    }

    # web/homework.rs:1206 Page<HomeworkReportEntry> -> :1166 HomeworkReportEntry
    HOMEWORK_REPORT_PAGE = {
        "items": [
            {
                "course": "c1",
                "homework": "h1",
                "title": "Turev calisma kagidi",
                "subject": "s1",
                "due_at": 1776067200000,
                "submitted": True,
                "late": False,
                "missing": False,
                "result": {"mark": 85},
            }
        ],
        "total": 1,
        "limit": None,
        "offset": 0,
    }

    # web/users.rs:707 ProfileResponse
    PROFILE = {
        "id": "u1",
        "username": "ada",
        "display_name": "Ada Lovelace",
        "stats": {"pomodoro_total": 128, "study_streak_current": 4},
    }

    async def test_marks_unwraps_the_courses_block_not_items(self):
        # REGRESYON: `_as_list()` burada `[]` donuyordu -- MarksReport'ta
        # `items` yok, `courses` var (web/marks.rs:65).
        client = _RecordingClient(body=self.MARKS_REPORT)
        rows = await source.BridgeSource(client).marks("demo", "u1")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["course"]["id"], "c1")
        self.assertEqual(rows[0]["results"][0]["mark"], 72)
        self.assertEqual(rows[1]["average"], None)

    async def test_attendance_unwraps_the_courses_block_not_items(self):
        # REGRESYON: aynisi AttendanceReport icin (web/attendance.rs:84).
        client = _RecordingClient(body=self.ATTENDANCE_REPORT)
        rows = await source.BridgeSource(client).attendance("demo", "u1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["course"]["id"], "c1")
        # Ders basina SAYAC dondurur, satir/tarih degil.
        self.assertEqual(rows[0]["counts"]["absent"], 4)
        self.assertNotIn("date", rows[0])

    async def test_pomodoro_unwraps_items_from_the_pomodoro_log(self):
        client = _RecordingClient(body=self.POMODORO_LOG)
        rows = await source.BridgeSource(client).pomodoro("demo", "u1")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["duration_ms"], 1500000)
        # Devam eden seansta `counted` null.
        self.assertIsNone(rows[1]["counted"])

    async def test_homework_report_returns_the_whole_page_envelope(self):
        client = _RecordingClient(body=self.HOMEWORK_REPORT_PAGE)
        report = await source.BridgeSource(client).homework_report("demo", "u1")
        self.assertEqual(report["total"], 1)
        self.assertEqual(report["items"][0]["homework"], "h1")

    async def test_profile_returns_the_plain_object(self):
        client = _RecordingClient(body=self.PROFILE)
        profile = await source.BridgeSource(client).profile("demo", "u1")
        self.assertEqual(profile["username"], "ada")
        self.assertEqual(profile["stats"]["pomodoro_total"], 128)

    async def test_page_envelope_endpoints_unwrap_items(self):
        page = {"items": [{"id": "x1"}], "total": 1, "limit": None, "offset": 0}
        bridge = source.BridgeSource(_RecordingClient(body=page))
        self.assertEqual(await bridge.notes("demo", "u1"), [{"id": "x1"}])
        self.assertEqual(await bridge.homework_list("demo", "u1"), [{"id": "x1"}])
        self.assertEqual(await bridge.course_notes("demo", "c1"), [{"id": "x1"}])


class SilentEmptyGuardTests(unittest.IsolatedAsyncioTestCase):
    """Beklenmeyen bicim SESSIZCE BOS DONMEZ.

    Sessiz bos, bu projede en pahali hata sinifidir: hesap bosalir, hata
    cikmaz, gunluk sessiz kalir. Her sapma ayirt edilebilir bir
    `unexpected_shape` uretmek zorunda.
    """

    def _assert_shape_error(self, error: source.SourceError, needle: str) -> None:
        self.assertEqual(error.code, "unexpected_shape")
        self.assertIn(needle, str(error))

    async def test_marks_with_an_items_envelope_is_not_silently_empty(self):
        # Tam da eski hatanin tersi: `items` gelirse de fark edilsin.
        client = _RecordingClient(body={"items": [{"course": "c1"}], "total": 1})
        with self.assertRaises(source.SourceError) as caught:
            await source.BridgeSource(client).marks("demo", "u1")
        self._assert_shape_error(caught.exception, "courses")

    async def test_attendance_without_courses_is_not_silently_empty(self):
        client = _RecordingClient(body={"user": "u1", "events": {}, "sessions": {}})
        with self.assertRaises(source.SourceError) as caught:
            await source.BridgeSource(client).attendance("demo", "u1")
        self._assert_shape_error(caught.exception, "courses")

    async def test_pomodoro_without_items_is_not_silently_empty(self):
        client = _RecordingClient(body={"sessions": [], "total_focus_ms": 0})
        with self.assertRaises(source.SourceError) as caught:
            await source.BridgeSource(client).pomodoro("demo", "u1")
        self._assert_shape_error(caught.exception, "items")

    async def test_notes_without_items_is_not_silently_empty(self):
        client = _RecordingClient(body={"rows": []})
        with self.assertRaises(source.SourceError) as caught:
            await source.BridgeSource(client).notes("demo", "u1")
        self._assert_shape_error(caught.exception, "items")

    async def test_homework_report_without_items_is_not_silently_empty(self):
        client = _RecordingClient(body={"total": 0, "limit": None, "offset": 0})
        with self.assertRaises(source.SourceError) as caught:
            await source.BridgeSource(client).homework_report("demo", "u1")
        self._assert_shape_error(caught.exception, "items")

    async def test_profile_without_an_id_is_not_silently_half(self):
        client = _RecordingClient(body={"username": "ada"})
        with self.assertRaises(source.SourceError) as caught:
            await source.BridgeSource(client).profile("demo", "u1")
        self._assert_shape_error(caught.exception, "id")

    async def test_a_scalar_body_is_refused(self):
        client = _RecordingClient(body="beklenmedik")
        with self.assertRaises(source.SourceError) as caught:
            await source.BridgeSource(client).marks("demo", "u1")
        self.assertEqual(caught.exception.code, "unexpected_shape")

    async def test_a_bare_list_is_accepted_but_warned(self):
        # Belgelenen bicim zarf; duz liste sapma isaretidir ama veri kullanilir.
        client = _RecordingClient(body=[{"course": "c1"}])
        with self.assertLogs_bridge() as logs:
            rows = await source.BridgeSource(client).marks("demo", "u1")
        self.assertEqual(rows, [{"course": "c1"}])
        self.assertTrue(any("duz liste" in line for line in logs))

    def assertLogs_bridge(self):
        """`config.log` ASCII `print` kullanir, `logging` degil -- yakalayalim."""

        class _Capture:
            def __init__(self):
                self.lines: list[str] = []

            def __enter__(self):
                self._original = config.log

                def spy(level, message):
                    self.lines.append(message)

                config.log = spy
                return self.lines

            def __exit__(self, *exc):
                config.log = self._original
                return False

        return _Capture()

    async def test_404_stays_an_empty_result_for_every_endpoint(self):
        # 404 bir bicim sorunu DEGILDIR: router calisti ve "yok" dedi.
        bridge = source.BridgeSource(_RecordingClient(body=None, status=404))
        self.assertEqual(await bridge.marks("demo", "u1"), [])
        self.assertEqual(await bridge.attendance("demo", "u1"), [])
        self.assertEqual(await bridge.pomodoro("demo", "u1"), [])
        self.assertEqual(await bridge.notes("demo", "u1"), [])
        self.assertIsNone(await bridge.profile("demo", "u1"))
        self.assertIsNone(await bridge.homework_report("demo", "u1"))


class FileSourceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.src = source.FileSource(self.root)

    def _write(self, school: str, kind: str, key: str, body) -> None:
        target = self.root / school / source.FileSource.DIRECTORIES[kind]
        target.mkdir(parents=True, exist_ok=True)
        with (target / f"{key}.json").open("w", encoding="utf-8") as handle:
            json.dump(body, handle, ensure_ascii=False)

    async def test_end_to_end_read_of_one_student_from_bare_lists(self):
        # Elle yazilan kucuk fiksturler duz liste olabilir; bu bicim uyari
        # uretmeden kabul edilir (fikstur yazilmistir, telden gelmemistir).
        self._write("demo", "profile", "u1", {"id": "u1", "grade": "11-A"})
        self._write("demo", "marks", "u1", [{"course": "mat", "average": 72}])
        self._write("demo", "attendance", "u1", [{"course": "mat", "counts": {}}])
        self._write("demo", "pomodoro", "u1", [{"id": "p1", "duration_ms": 1500000}])
        self._write("demo", "homework_report", "u1", {"items": [{"homework": "h1"}]})
        self._write("demo", "homework_list", "u1", [{"id": "h1"}])
        self._write("demo", "notes", "u1", [{"id": "n1"}])
        self._write("demo", "course_notes", "c1", [{"id": "cn1"}])

        self.assertEqual((await self.src.profile("demo", "u1"))["grade"], "11-A")
        self.assertEqual(
            await self.src.marks("demo", "u1"), [{"course": "mat", "average": 72}]
        )
        self.assertEqual(
            await self.src.attendance("demo", "u1"), [{"course": "mat", "counts": {}}]
        )
        self.assertEqual(
            await self.src.pomodoro("demo", "u1"),
            [{"id": "p1", "duration_ms": 1500000}],
        )
        report = await self.src.homework_report("demo", "u1")
        self.assertEqual(report["items"][0]["homework"], "h1")
        self.assertEqual(await self.src.homework_list("demo", "u1"), [{"id": "h1"}])
        self.assertEqual(await self.src.notes("demo", "u1"), [{"id": "n1"}])
        self.assertEqual(await self.src.course_notes("demo", "c1"), [{"id": "cn1"}])

    async def test_a_real_response_saved_verbatim_works_as_a_fixture(self):
        # Gercek bir cevabi dosyaya oldugu gibi kaydetmek calismali: kopru ve
        # fikstur ayni zarflari acar.
        real = RealResponseShapeTests
        self._write("demo", "marks", "u1", real.MARKS_REPORT)
        self._write("demo", "attendance", "u1", real.ATTENDANCE_REPORT)
        self._write("demo", "pomodoro", "u1", real.POMODORO_LOG)
        self._write("demo", "homework_report", "u1", real.HOMEWORK_REPORT_PAGE)
        self._write("demo", "profile", "u1", real.PROFILE)

        marks = await self.src.marks("demo", "u1")
        self.assertEqual([row["course"]["id"] for row in marks], ["c1", "c2"])
        attendance = await self.src.attendance("demo", "u1")
        self.assertEqual(attendance[0]["counts"]["absent"], 4)
        self.assertEqual(len(await self.src.pomodoro("demo", "u1")), 2)
        self.assertEqual((await self.src.homework_report("demo", "u1"))["total"], 1)
        self.assertEqual((await self.src.profile("demo", "u1"))["username"], "ada")

    async def test_a_fixture_with_the_wrong_envelope_key_is_not_silently_empty(self):
        self._write("demo", "marks", "u1", {"items": [{"course": "mat"}]})
        with self.assertRaises(source.SourceError) as caught:
            await self.src.marks("demo", "u1")
        self.assertEqual(caught.exception.code, "unexpected_shape")

    async def test_missing_fixture_is_empty_not_an_error(self):
        self.assertIsNone(await self.src.profile("demo", "yok"))
        self.assertEqual(await self.src.marks("demo", "yok"), [])

    async def test_other_schools_are_not_visible(self):
        self._write("demo", "marks", "u1", [{"value": 1}])
        self.assertEqual(await self.src.marks("baska-okul", "u1"), [])

    async def test_path_traversal_in_an_id_cannot_escape_the_root(self):
        self._write("demo", "marks", "u1", [{"value": 1}])
        self.assertEqual(await self.src.marks("demo", "../../u1"), [])

    async def test_homework_list_without_a_user_reads_the_service_fixture(self):
        self._write("demo", "homework_list", "_service", [{"id": "h0"}])
        self.assertEqual(await self.src.homework_list("demo"), [{"id": "h0"}])

    async def test_fixture_source_is_the_same_class(self):
        self.assertIs(source.FixtureSource, source.FileSource)

    async def test_file_source_satisfies_the_protocol(self):
        self.assertIsInstance(self.src, source.Source)


if __name__ == "__main__":
    unittest.main()
