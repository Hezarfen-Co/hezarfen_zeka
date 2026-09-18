"""The three served capabilities, end to end over a fake bridge.

What is proven here, in the order it matters:

1. The fail-pre-fix fact. With an empty handler table `dispatch` answers
   `unknown_capability` -- that was the live production answer even though the
   `Hello` frame announced the name in the same breath. After
   `handlers.wire()` the same call reaches a real handler.
2. Each capability answers the fields the backend's contract reads
   (`hezarfen_backend/src/ai/insight.rs`), through the real store layer
   (`BridgeStore` + `RecordingCaller`) and a `FakeSource`.
3. The boot self-check refuses to advertise a name with no handler.

The fixture data is built relative to the *real* now: `fakes.NOW` is 2023, and
with it the 28-day study window would be empty and `O3.pattern` would never
fire.
"""

from __future__ import annotations

import time
import unittest
from datetime import datetime

from src import capabilities, handlers
from src.compute import clock
from src.protocol import CapabilityError
from src.store import (
    CAP_PURGE,
    CAP_RECOMMENDATION,
    CAP_RUN,
    CAP_SUMMARY,
    CAP_SWEEP,
    BridgeStore,
    RecordingCaller,
)

from .fakes import FakeSource, dataset

SCHOOL = "okul-a"
#: Real "now" -- see the module docstring.
NOW = int(time.time() * 1000)


def _rows(caller: RecordingCaller, capability: str) -> list[dict]:
    rows: list[dict] = []
    for kind, _, payload in caller.calls:
        if kind == capability:
            rows.extend(payload.get("rows") or [])
    return rows


class HandlerTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.data = dataset(12, now_ms=NOW)
        self.caller = RecordingCaller()
        capabilities.bind_store(BridgeStore(self.caller))
        handlers.bind_source(lambda school: FakeSource(self.data))
        handlers.wire()

    async def asyncTearDown(self) -> None:
        capabilities._handlers.clear()

    async def dispatch(self, capability: str, payload: dict) -> dict:
        return await capabilities.dispatch(capability, SCHOOL, payload)

    def kinds(self) -> list[str]:
        return [kind for kind, _, _ in self.caller.calls]


class FailPreFixTests(HandlerTestCase):
    async def test_student_is_unknown_until_wire_registers_it(self) -> None:
        capabilities._handlers.clear()
        with self.assertRaises(CapabilityError) as caught:
            await self.dispatch("insight.student", {"user_id": "student-00"})
        self.assertEqual(caught.exception.code, "unknown_capability")

        handlers.wire()
        answer = await self.dispatch("insight.student", {"user_id": "student-00"})
        self.assertEqual(answer["user_id"], "student-00")

    async def test_a_wired_name_refuses_a_bad_payload_typed(self) -> None:
        """After wiring, a malformed call is a `bad_request`, not a miss:
        the handler ran and judged the payload."""
        with self.assertRaises(CapabilityError) as caught:
            await self.dispatch("insight.student", {})
        self.assertEqual(caught.exception.code, "bad_request")

    async def test_boot_self_check_refuses_a_name_without_a_handler(self) -> None:
        capabilities._handlers.pop("insight.class")
        with self.assertRaises(capabilities.RegistrationError) as caught:
            capabilities.verify_dispatchable()
        self.assertIn("insight.class", str(caught.exception))
        self.assertEqual(
            capabilities.dispatchable_names(), ["insight.student", "insight.refresh"]
        )

        handlers.wire()
        capabilities.verify_dispatchable()  # and back to a clean bill


class StudentCapabilityTests(HandlerTestCase):
    async def test_answer_carries_the_contract_and_writes_only_rows(self) -> None:
        answer = await self.dispatch(
            "insight.student", {"user_id": "student-00", "since": "2023-06-01"}
        )
        self.assertEqual(
            set(answer),
            {"user_id", "generated_at", "signals", "recommendations", "coverage"},
        )
        self.assertEqual(answer["user_id"], "student-00")
        self.assertGreater(datetime.fromisoformat(answer["generated_at"]).year, 2024)
        self.assertIsInstance(answer["signals"], list)

        # `O3.pattern` fires on the fixture's study sessions; the card is the
        # student's own, carries evidence, and is not storage bookkeeping.
        self.assertTrue(answer["recommendations"])
        card = answer["recommendations"][0]
        self.assertEqual(card["audience"], "student-00")
        self.assertEqual(card["audience_role"], "student")
        self.assertTrue(card["evidence"])
        self.assertNotIn("retain_until", card)
        # The answer's cards are exactly the ones the store accepted.
        self.assertEqual(
            [item["rule_id"] for item in answer["recommendations"]],
            [
                row["rule_id"]
                for row in _rows(self.caller, CAP_RECOMMENDATION)
                if row["audience"] == "student-00"
            ],
        )

        written = _rows(self.caller, CAP_SUMMARY)
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0]["student"], "student-00")

        # The night run owns the ledger, the purge and the sweep. A
        # single-student compute that wrote any of them would clobber the
        # day's record with a one-student one.
        self.assertEqual(
            [kind for kind in self.kinds() if kind in (CAP_RUN, CAP_PURGE, CAP_SWEEP)],
            [],
        )
        self.assertEqual(answer["coverage"]["sections"], "all")
        self.assertEqual(answer["coverage"]["reads"]["marks"], 1)
        self.assertEqual(answer["coverage"]["reads"]["homework_report"], 6)

    async def test_sections_narrow_the_reads_and_null_the_row(self) -> None:
        answer = await self.dispatch(
            "insight.student", {"user_id": "student-00", "sections": ["marks"]}
        )
        self.assertEqual(answer["coverage"]["sections"], ["marks"])
        self.assertEqual(set(answer["coverage"]["reads"]), {"profile", "marks"})
        row = _rows(self.caller, CAP_SUMMARY)[0]
        self.assertIsInstance(row["marks"], dict)
        # Unrequested modules are "not computed" (`null`), which the backend's
        # `SummaryRow` keeps apart from the empty-object "read, nothing there".
        self.assertIsNone(row["attendance"])
        self.assertIsNone(row["submission"])
        self.assertIsNone(row["study"])

    async def test_bad_inputs_are_refused_by_name(self) -> None:
        with self.assertRaises(CapabilityError) as caught:
            await self.dispatch(
                "insight.student", {"user_id": "student-00", "sections": ["speech"]}
            )
        self.assertEqual(caught.exception.code, "bad_request")
        with self.assertRaises(CapabilityError) as caught:
            await self.dispatch(
                "insight.student", {"user_id": "student-00", "since": "dun"}
            )
        self.assertEqual(caught.exception.code, "bad_request")

    async def test_a_failed_fetch_is_a_refusal_not_an_empty_answer(self) -> None:
        handlers.bind_source(
            lambda school: FakeSource(self.data, fail={"student-05"})
        )
        with self.assertRaises(CapabilityError) as caught:
            await self.dispatch("insight.student", {"user_id": "student-05"})
        self.assertEqual(caught.exception.code, "unavailable")


class ClassCapabilityTests(HandlerTestCase):
    async def test_answer_carries_cohort_and_attention_list(self) -> None:
        answer = await self.dispatch(
            "insight.class",
            {"course_id": "course-1", "term": "2023-06-01", "top_n": 2},
        )
        self.assertEqual(set(answer), set(capabilities.SCHEMAS["insight.class"][1].__annotations__))
        self.assertEqual(answer["course_id"], "course-1")
        self.assertEqual(answer["cohort_size"], 12)
        self.assertEqual(answer["topic_gaps"], [])  # not producible; says so below
        self.assertTrue(answer["coverage"]["unavailable"]["topic_gaps"])

        self.assertTrue(answer["attention_list"])
        item = answer["attention_list"][0]
        self.assertEqual(
            set(item),
            {"user_id", "trigger", "course", "fact", "window_from", "window_to", "evidence"},
        )
        # The output contract has no ranking field anywhere, the wire included.
        self.assertNotIn("score", item)
        self.assertEqual(answer["coverage"]["attention"]["total"], 1)
        self.assertEqual(answer["coverage"]["attention"]["returned"], 1)
        self.assertEqual(answer["coverage"]["roster"]["course_rows"], 1)


class RefreshCapabilityTests(HandlerTestCase):
    async def test_school_refresh_writes_the_run_ledger_and_counts(self) -> None:
        answer = await self.dispatch("insight.refresh", {})
        self.assertEqual(answer["requested"], 12)
        self.assertEqual(answer["computed"], 12)
        self.assertEqual(answer["skipped"], 0)
        self.assertEqual(answer["failed"], [])
        self.assertEqual(answer["status"], "ok")

        runs = [
            payload["run"] for kind, _, payload in self.caller.calls if kind == CAP_RUN
        ]
        self.assertEqual(len(runs), 2)  # "running" first, the verdict last
        started = int(
            datetime.fromisoformat(answer["started_at"]).timestamp() * 1000
        )
        self.assertEqual(runs[-1]["run_day"], clock.tr_date_key(started))
        self.assertEqual(runs[-1]["status"], "ok")
        self.assertEqual(runs[-1]["students_total"], 12)
        # The whole-school sweep keeps the night run's cleanup steps.
        self.assertEqual(self.kinds().count(CAP_PURGE), 1)
        self.assertEqual(self.kinds().count(CAP_SWEEP), 1)

    async def test_scoped_refresh_never_purges(self) -> None:
        """`user_ids` is a subset, not the roster: obeying it through
        `insight.departed.purge` would delete everyone it does not name."""
        answer = await self.dispatch(
            "insight.refresh", {"user_ids": ["student-00", "student-01"]}
        )
        self.assertEqual(answer["requested"], 2)
        self.assertEqual(answer["computed"], 2)
        self.assertNotIn(CAP_PURGE, self.kinds())
        # Its ledger row is still written: that is the trace a reader polls.
        self.assertIn(CAP_RUN, self.kinds())

    async def test_failed_students_are_named_in_the_answer(self) -> None:
        handlers.bind_source(
            lambda school: FakeSource(self.data, fail={"student-05"})
        )
        answer = await self.dispatch(
            "insight.refresh", {"user_ids": ["student-05", "student-00"]}
        )
        self.assertEqual(answer["requested"], 2)
        self.assertEqual(answer["computed"], 1)
        self.assertEqual([entry["user_id"] for entry in answer["failed"]], ["student-05"])
        self.assertEqual(answer["failed"][0]["code"], "unavailable")
        self.assertTrue(answer["failed"][0]["message"])


if __name__ == "__main__":
    unittest.main()
