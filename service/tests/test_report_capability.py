"""`insight.report` -- the school report document, end to end over the table.

What is proven here, in the order it matters:

1. The fail-pre-fix fact, for the fourth served name: with an empty handler
   table the dispatch answers `unknown_capability`; `handlers.wire()` makes the
   same call reach a real handler, and the boot self-check counts the name
   dispatchable -- and refuses to boot when it is not.
2. The whole point of the seam: row lists shaped EXACTLY like what the backend
   sends -- built here by the very writers that wrote them in production
   (`store.summary_rows` / `recommendation_rows` / `profile_rows` / `run_row`),
   with NO `school` key anywhere (ZEKA never wrote one; the frame carries it) --
   render the school report HTML: the display name, the student count, the
   per-student attention lines, the class NAMES (never the raw ids), and only
   the roles the `okul` report may show.
3. Refusals are typed and leave no half-built document behind: an empty row set
   (`insufficient_rows`), an unserved kind or a payload that breaks the contract
   (`bad_request`), a package failure (`internal`), an over-cap document
   (`document_too_large`) -- never a truncated HTML file.
"""

from __future__ import annotations

import re
import time
import unittest
from typing import Any
from unittest.mock import patch

from src import capabilities, handlers, protocol
from src.compute import clock
from src.compute.model import (
    Audience,
    Confidence,
    Recommendation,
    StudentSegmentProfile,
    StudentSummary,
)
from src.protocol import CapabilityError
from src.store import profile_rows, recommendation_rows, run_row, summary_rows

SCHOOL = "demo-okul"
DISPLAY = "Demo Anadolu Lisesi"
NOW = int(time.time() * 1000)
DAY = clock.DAY_MS
RUN_DAY = clock.tr_date_key(NOW)

FACT_A = "Son 30 günde 4 ödev teslim edilmedi"
FACT_B = "Not eğilimi son üç sınavda düştü"

#: Şube KİMLİKLERİ (satırlarda `marks.classes` olarak giden şey) ve GÖRÜNEN
#: adları (payload'ın `classes` haritasından gelen şey). İkisinin sırası
#: KASITLI olarak farklıdır (kimlikte A<B, adda "10-B"<"9-A"): tablonun
#: kimliğe göre değil ADA göre sıralandığı böyle görünür.
CLASS_A_ID = "01a0b1a6-f984-7483-94ee-7643d137fe08"
CLASS_B_ID = "01a0b1a6-f984-7483-94ee-7643d137fe09"
CLASS_A_NAME = "9-A"
CLASS_B_NAME = "10-B"
CLASS_LABEL_UNKNOWN = "Adı bilinmeyen şube"


def _marks(course: str, title: str, band: str, class_id: str) -> dict[str, Any]:
    """One course's evidence block, in the shape `marks.py` writes."""
    return {
        "classes": [class_id],
        "courses": {
            course: {
                "course": course,
                "course_title": title,
                "n_marks": 6,
                "average": 42.5,
                "trend": {"available": True, "dropped": True, "rising": False},
                "placement": {
                    "band": band,
                    "confidence": "stable",
                    "z": -1.8,
                    "class_average": 68.0,
                    "class_sd": 9.0,
                    "cohort_n": 12,
                },
            }
        },
    }


def _attention(trigger: str, fact: str) -> dict[str, Any]:
    """One attention item, in the shape `attention.py` writes."""
    return {
        "trigger": trigger,
        "course": "course-1",
        "fact": fact,
        "window_from": NOW - 30 * DAY,
        "window_to": NOW,
        "evidence": {"missing": 4, "cohort_median": 1},
    }


def summaries() -> list[dict[str, Any]]:
    """`zeka_student_summary` rows, exactly as ZEKA writes them (no `school`)."""
    return summary_rows(
        [
            StudentSummary(
                school=SCHOOL,
                student="ogrenci-a",
                computed_at=NOW,
                marks=_marks("course-1", "Matematik", "review", CLASS_A_ID),
                attendance={"overall": {"rate": 0.82}, "courses": {}},
                submission={"overall": {"n": 12, "n_submitted": 9, "n_missing": 3}},
                study={"recent_28d": {"n_stints": 11, "active_days": 7}},
                attention=[_attention("homework", FACT_A)],
                confidence=Confidence.STABLE,
            ),
            StudentSummary(
                school=SCHOOL,
                student="ogrenci-b",
                computed_at=NOW,
                marks=_marks("course-2", "Fen Bilimleri", "on_track", CLASS_B_ID),
                attendance={"overall": {"rate": 0.95}, "courses": {}},
                submission={"overall": {"n": 11, "n_submitted": 11, "n_missing": 0}},
                study={"recent_28d": {"n_stints": 15, "active_days": 9}},
                attention=[_attention("mark_trend", FACT_B)],
                confidence=Confidence.STABLE,
            ),
            StudentSummary(
                school=SCHOOL,
                student="ogrenci-c",
                computed_at=NOW,
                marks=_marks("course-1", "Matematik", "insufficient_data", CLASS_A_ID),
                attendance={"overall": {"rate": 1.0}, "courses": {}},
                submission={"overall": {"n": 10, "n_submitted": 10, "n_missing": 0}},
                study={"recent_28d": {"n_stints": 8, "active_days": 6}},
                confidence=Confidence.EXPLORATORY,
            ),
        ]
    )


def recommendations() -> list[dict[str, Any]]:
    """`zeka_recommendation` rows: teacher, student and parent cards.

    The parent card is the gate witness: `allowed_roles("okul")` is
    `STAFF_ROLES | STUDENT_FACING_ROLES` (`report/gate.py`), so teacher and
    student cards show in the school report and the parent card must not.
    """
    rows, rejected = recommendation_rows(
        [
            Recommendation(
                school=SCHOOL,
                audience="ogretmen-1",
                audience_role=Audience.TEACHER,
                product="T4",
                rule_id="T4.homework",
                about="ogrenci-a",
                course="course-1",
                evidence={"missing": 4, "cohort_median": 1},
                limitation="Teslim anı bilinmiyor.",
                confidence=Confidence.STABLE,
                computed_at=NOW,
                expires_at=NOW + 7 * DAY,
            ),
            Recommendation(
                school=SCHOOL,
                audience="ogrenci-a",
                audience_role=Audience.STUDENT,
                product="O1",
                rule_id="O1.review_band",
                course="course-1",
                evidence={"student_average": 42.5, "class_average": 68.0},
                limitation="Konu kırılımı yok.",
                confidence=Confidence.STABLE,
                computed_at=NOW,
                expires_at=NOW + 7 * DAY,
            ),
            Recommendation(
                school=SCHOOL,
                audience="veli-1",
                audience_role=Audience.PARENT,
                product="V1",
                rule_id="V1.parent_only",
                about="ogrenci-a",
                evidence={"n": 3},
                limitation="Veli kartı okul raporunda gösterilmez.",
                confidence=Confidence.STABLE,
                computed_at=NOW,
                expires_at=NOW + 7 * DAY,
            ),
        ]
    )
    assert rejected == 0, "fixture rows must carry evidence"
    return rows


def profiles() -> list[dict[str, Any]]:
    """`zeka_student_segment_profile` rows."""
    return profile_rows(
        [
            StudentSegmentProfile(
                school=SCHOOL,
                student="ogrenci-a",
                dimension="bilissel_talep",
                label="analiz",
                n_answers=120,
                n_correct=60,
                overall_n_answers=400,
                overall_accuracy=0.61,
                computed_at=NOW,
                confidence=Confidence.STABLE,
            ),
            StudentSegmentProfile(
                school=SCHOOL,
                student="ogrenci-b",
                dimension="dikkat_tuzagi",
                label="var",
                n_answers=150,
                n_correct=90,
                overall_n_answers=400,
                overall_accuracy=0.61,
                computed_at=NOW,
                confidence=Confidence.EXPLORATORY,
            ),
        ]
    )


def runs() -> list[dict[str, Any]]:
    """`zeka_run` rows, keyed the way the store writes them."""
    return [
        run_row(
            {
                "started_at": NOW - 3600_000,
                "finished_at": NOW,
                "status": "ok",
                "students_total": 3,
                "students_ok": 3,
                "students_failed": 0,
                "students_skipped": 0,
                "rows_written": 9,
                "budget_exceeded": False,
                "budget_ms": 60_000,
                "pending_students": [],
                "failed_modules": [],
            },
            f"{SCHOOL}_{RUN_DAY}",
        )
    ]


def payload(**over: Any) -> dict[str, Any]:
    """The request exactly as the backend builds it (`## insight.report`)."""
    sent: dict[str, Any] = {
        "kind": "okul",
        "run_day": RUN_DAY,
        "requested_by": "mudur-1",
        "school": {"id": "01990000-0000-7000-8000-000000000001", "name": DISPLAY},
        # Sibling key, read whole from the school's own class table: the rows
        # carry class IDS, and the document must print NAMES.
        "classes": [
            {"id": CLASS_A_ID, "name": CLASS_A_NAME},
            {"id": CLASS_B_ID, "name": CLASS_B_NAME},
        ],
        "summaries": summaries(),
        "recommendations": recommendations(),
        "profiles": profiles(),
        "runs": runs(),
    }
    sent.update(over)
    return sent


class ReportCase(unittest.IsolatedAsyncioTestCase):
    """Wired table, one school, and the payload the backend will send."""

    def setUp(self) -> None:
        handlers.wire()

    def tearDown(self) -> None:
        capabilities._handlers.clear()

    async def dispatch(self, sent: dict[str, Any]) -> dict[str, Any]:
        return await capabilities.dispatch("insight.report", SCHOOL, sent)


class DispatchTests(ReportCase):
    async def test_report_is_unknown_until_wire_registers_it(self) -> None:
        capabilities._handlers.clear()
        with self.assertRaises(CapabilityError) as caught:
            await self.dispatch(payload())
        self.assertEqual(caught.exception.code, "unknown_capability")

        handlers.wire()
        answer = await self.dispatch(payload())
        self.assertEqual(answer["format"], "html")

    def test_the_boot_self_check_counts_it_dispatchable(self) -> None:
        self.assertIn("insight.report", capabilities.dispatchable_names())
        capabilities.verify_dispatchable()  # a clean bill: no raise

        capabilities._handlers.pop("insight.report")
        with self.assertRaises(capabilities.RegistrationError) as caught:
            capabilities.verify_dispatchable()
        self.assertIn("insight.report", str(caught.exception))


class DocumentTests(ReportCase):
    async def test_the_html_carries_name_count_and_per_student_lines(self) -> None:
        answer = await self.dispatch(payload())
        html = answer["html"]

        # 1) a self-contained HTML document, not an error page
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        # 2) the DISPLAY name the payload carried is the title
        self.assertIn(DISPLAY, html)
        # 3) the student count is the number of summaries the backend sent --
        #    rows carry no `school`, so this also proves the frame's stamp
        self.assertIn('<td>Öğrenci</td><td class="num">3</td>', html)
        # 3b) the Şube cells print the MAPPED NAMES, never the raw ids, and the
        #     class count is unchanged by the labelling
        self.assertIn('<td>Şube</td><td class="num">2</td>', html)
        self.assertIn(f"<td>{CLASS_A_NAME}</td>", html)
        self.assertIn(f"<td>{CLASS_B_NAME}</td>", html)
        self.assertNotIn(CLASS_A_ID, html)
        self.assertNotIn(CLASS_B_ID, html)
        #     ...and the tables read in NAME order, not id order (the fixture's
        #     names sort the other way round from its ids on purpose)
        pairs = [
            (label, course)
            for label, course in re.findall(r"<tr><td>([^<]+)</td><td>([^<]+)</td>", html)
            if label in (CLASS_A_NAME, CLASS_B_NAME, CLASS_LABEL_UNKNOWN)
        ]
        self.assertEqual(pairs, sorted(pairs))
        # 4) one line per student's attention item, with the student's id and
        #    the student's class NAME in the same row
        self.assertIn("<td>ogrenci-a</td>", html)
        self.assertIn(f"<td>ogrenci-a</td><td>{CLASS_A_NAME}</td>", html)
        self.assertIn(FACT_A, html)
        self.assertIn("<td>ogrenci-b</td>", html)
        self.assertIn(FACT_B, html)
        # 5) the role gate ran: teacher and student cards show (the `okul`
        #    report allows both), the parent card does not
        self.assertIn("T4.homework", html)
        self.assertIn("O1.review_band", html)
        self.assertNotIn("V1.parent_only", html)

        # The answer's own contract
        self.assertEqual(answer["kind"], "okul")
        self.assertEqual(answer["format"], "html")
        self.assertEqual(answer["run_day"], RUN_DAY)
        self.assertIs(answer["truncated"], False)
        self.assertEqual(answer["byte_size"], len(html.encode("utf-8")))
        self.assertEqual(
            answer["coverage"]["rows"],
            {"summaries": 3, "recommendations": 3, "profiles": 2, "runs": 1},
        )
        self.assertIs(answer["coverage"]["empty"], False)
        # The limitation notes are the package's own sentences, not invented ones
        self.assertTrue(answer["notes"])
        self.assertTrue(
            all(isinstance(note, str) and note for note in answer["notes"])
        )
        self.assertTrue(any("sıralama yoktur" in note for note in answer["notes"]))

    async def test_run_day_falls_back_to_the_newest_run_row(self) -> None:
        sent = payload()
        del sent["run_day"]
        answer = await self.dispatch(sent)
        self.assertEqual(answer["run_day"], RUN_DAY)

    async def test_class_names_mapping_shape_labels_too(self) -> None:
        """The `class_names: {<id>: name}` fallback shape works as well."""
        sent = payload()
        sent.pop("classes")
        sent["class_names"] = {CLASS_A_ID: CLASS_A_NAME, CLASS_B_ID: CLASS_B_NAME}
        html = (await self.dispatch(sent))["html"]
        self.assertIn(f"<td>{CLASS_A_NAME}</td>", html)
        self.assertIn(f"<td>{CLASS_B_NAME}</td>", html)
        self.assertNotIn(CLASS_A_ID, html)
        self.assertNotIn(CLASS_B_ID, html)

    async def test_an_unmapped_class_gets_the_label_never_the_id(self) -> None:
        """A class the map lacks is a label, and the numbers do not move."""
        sent = payload(classes=[{"id": CLASS_A_ID, "name": CLASS_A_NAME}])
        answer = await self.dispatch(sent)
        html = answer["html"]
        self.assertIn(f"<td>{CLASS_A_NAME}</td>", html)
        self.assertIn(CLASS_LABEL_UNKNOWN, html)
        self.assertNotIn(CLASS_B_ID, html)
        # Labelling is not counting: 2 classes, 3 students, both unchanged.
        self.assertIn('<td>Şube</td><td class="num">2</td>', html)
        self.assertIn('<td>Öğrenci</td><td class="num">3</td>', html)

    async def test_a_backend_without_a_class_map_still_builds(self) -> None:
        """An older backend sends no map: the document builds, labelled."""
        sent = payload()
        sent.pop("classes")
        answer = await self.dispatch(sent)
        html = answer["html"]
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn(CLASS_LABEL_UNKNOWN, html)
        self.assertNotIn(CLASS_A_ID, html)
        self.assertNotIn(CLASS_B_ID, html)
        self.assertIn('<td>Öğrenci</td><td class="num">3</td>', html)
        self.assertIn('<td>Şube</td><td class="num">2</td>', html)


class RefusalTests(ReportCase):
    async def test_an_empty_row_set_is_refused_not_rendered(self) -> None:
        for sent in (
            payload(summaries=[], recommendations=[], profiles=[], runs=[]),
            {"kind": "okul"},  # no row lists at all
        ):
            with self.assertRaises(CapabilityError) as caught:
                await self.dispatch(sent)
            self.assertEqual(caught.exception.code, "insufficient_rows")

    async def test_a_kind_this_capability_does_not_serve_is_refused(self) -> None:
        for kind in ("ogrenci", "ogretmen", "ham", "rapor", ""):
            with self.assertRaises(CapabilityError) as caught:
                await self.dispatch(payload(kind=kind))
            self.assertEqual(caught.exception.code, "bad_request")

    async def test_a_row_claiming_another_school_is_refused(self) -> None:
        sent = payload()
        sent["summaries"] = [{**sent["summaries"][0], "school": "baska-okul"}]
        with self.assertRaises(CapabilityError) as caught:
            await self.dispatch(sent)
        self.assertEqual(caught.exception.code, "bad_request")
        self.assertIn("baska-okul", str(caught.exception))

    async def test_a_stray_school_slug_is_ignored(self) -> None:
        # Backend dropped ReportSchool.slug. A leftover key must not refuse
        # and must not become a second identity.
        answer = await self.dispatch(
            payload(school={"id": "x", "slug": "baska-okul", "name": "Başka"})
        )
        self.assertIn("Başka", answer["html"])

    async def test_a_malformed_row_list_is_refused(self) -> None:
        with self.assertRaises(CapabilityError) as caught:
            await self.dispatch(payload(profiles={"student": "ogrenci-a"}))
        self.assertEqual(caught.exception.code, "bad_request")

    async def test_a_malformed_class_list_is_refused(self) -> None:
        # A container that is not a list, and an entry with no usable id
        # (an id is what the mapping keys on; swallowing it would strip every
        # label silently).
        for bad in ({"id": CLASS_A_ID}, ["9-A"], [{"name": CLASS_A_NAME}]):
            with self.assertRaises(CapabilityError) as caught:
                await self.dispatch(payload(classes=bad))
            self.assertEqual(caught.exception.code, "bad_request")

    async def test_a_render_failure_is_a_typed_refusal(self) -> None:
        with patch.object(
            handlers.report_render, "to_html", side_effect=RuntimeError("çizim düştü")
        ):
            with self.assertRaises(CapabilityError) as caught:
                await self.dispatch(payload())
        self.assertEqual(caught.exception.code, "internal")
        self.assertIn("çizim düştü", str(caught.exception))

    async def test_an_oversize_document_is_refused_not_truncated(self) -> None:
        cap = protocol.AI_MAX_FRAME_BYTES // 2
        with patch.object(
            handlers.report_render, "to_html", return_value="x" * (cap + 1)
        ):
            with self.assertRaises(CapabilityError) as caught:
                await self.dispatch(payload())
        self.assertEqual(caught.exception.code, "document_too_large")

    def test_the_html_cap_is_half_the_frame_cap(self) -> None:
        # The document rides INSIDE the JSON frame: half the cap is the room
        # the rest of the frame (and JSON escaping) needs.
        self.assertEqual(handlers._MAX_HTML_BYTES * 2, protocol.AI_MAX_FRAME_BYTES)


if __name__ == "__main__":
    unittest.main()
