"""`compute.submission` birim testleri: sayımlar, kapı, yaklaşan teslimler."""

from __future__ import annotations

import unittest

from src.compute import submission

from .fakes import homework, report_entry

NOW = 1_700_000_000_000
DAY = 86_400_000
HOUR = 3_600_000


def _page(items: list[dict]) -> dict:
    return {"items": items, "total": len(items), "limit": None, "offset": 0}


class TestTally(unittest.TestCase):
    def _items(self) -> list[dict]:
        due = NOW - 5 * DAY
        return [
            report_entry("h1", "c1", due, submitted=True),
            report_entry("h2", "c1", due, submitted=True),
            report_entry("h3", "c1", due, submitted=True),
            report_entry("h4", "c1", due, submitted=True),
            report_entry("h5", "c1", due, submitted=True, late=True),
            report_entry("h6", "c1", due, submitted=True, late=True),
            report_entry("h7", "c1", due, missing=True, status="missing"),
            report_entry("h8", "c1", due, missing=True),
            report_entry("h9", "c1", due, missing=True),
            report_entry("h10", "c1", NOW + 5 * DAY),
        ]

    def test_counts_and_rates(self) -> None:
        result = submission.student_profile(_page(self._items()), [], NOW)
        overall = result["overall"]
        self.assertEqual(overall["n"], 10)
        self.assertEqual(overall["n_submitted"], 6)
        self.assertEqual(overall["n_late"], 2)
        self.assertEqual(overall["n_on_time"], 4)
        self.assertEqual(overall["n_missing"], 3)
        self.assertEqual(overall["n_marked_missing"], 1)
        self.assertAlmostEqual(overall["on_time_rate_by_last_touch"], 4 / 6)
        self.assertAlmostEqual(overall["late_rate"], 2 / 6)
        self.assertAlmostEqual(overall["missing_rate"], 0.3)

    def test_gate_suppresses_rates_below_five_submissions(self) -> None:
        """GÜVEN KAPISI: 5 teslimin altında oran ve davranışsal yorum YOK."""
        due = NOW - 5 * DAY
        items = [report_entry(f"h{i}", "c1", due, submitted=True) for i in range(4)]
        result = submission.student_profile(_page(items), [], NOW)
        self.assertTrue(result["overall"]["rates_suppressed"])
        self.assertIsNone(result["overall"]["on_time_rate_by_last_touch"])

    def test_windows_split_by_due_at(self) -> None:
        items = [
            report_entry("a", "c1", NOW - 5 * DAY, missing=True),
            report_entry("b", "c1", NOW - 40 * DAY, submitted=True),
        ]
        result = submission.student_profile(_page(items), [], NOW)
        self.assertEqual(result["recent_30d"]["n"], 1)
        self.assertEqual(result["recent_30d"]["n_missing"], 1)
        self.assertEqual(result["previous_30d"]["n"], 1)
        self.assertEqual(result["previous_30d"]["n_missing"], 0)


class TestUpcoming(unittest.TestCase):
    def test_high_priority_needs_all_three_conditions(self) -> None:
        """`MODULLER.md` §2.4 adım 4: teslim yok + 24 saat içinde + oran < 0,60."""
        due = NOW - 5 * DAY
        items = [report_entry(f"h{i}", "c1", due, submitted=True, late=True) for i in range(4)]
        items += [report_entry("h9", "c1", due, submitted=True)]
        # 5 teslim, 1'i zamanında → oran 0,20 < 0,60
        hw = [homework("upcoming", "c1", NOW + 6 * HOUR)]
        result = submission.student_profile(_page(items), hw, NOW)
        self.assertEqual(len(result["upcoming"]), 1)
        self.assertTrue(result["upcoming"][0]["high_priority"])

    def test_no_badge_when_rate_is_unknown(self) -> None:
        """Bilinmeyen davranıştan öncelik türetilmez (`[T§3 Ö4]`)."""
        hw = [homework("upcoming", "c1", NOW + 6 * HOUR)]
        result = submission.student_profile(_page([]), hw, NOW)
        self.assertFalse(result["upcoming"][0]["high_priority"])

    def test_no_badge_when_far_from_deadline(self) -> None:
        due = NOW - 5 * DAY
        items = [report_entry(f"h{i}", "c1", due, submitted=True, late=True) for i in range(5)]
        hw = [homework("upcoming", "c1", NOW + 10 * DAY)]
        result = submission.student_profile(_page(items), hw, NOW)
        self.assertFalse(result["upcoming"][0]["high_priority"])

    def test_past_deadlines_are_not_upcoming(self) -> None:
        hw = [homework("old", "c1", NOW - DAY)]
        result = submission.student_profile(_page([]), hw, NOW)
        self.assertEqual(result["upcoming"], [])

    def test_already_submitted_marked(self) -> None:
        items = [report_entry("upcoming", "c1", NOW + 6 * HOUR, submitted=True)]
        hw = [homework("upcoming", "c1", NOW + 6 * HOUR)]
        result = submission.student_profile(_page(items), hw, NOW)
        self.assertTrue(result["upcoming"][0]["submitted"])
        self.assertFalse(result["upcoming"][0]["high_priority"])


class TestDeclaredLimits(unittest.TestCase):
    def test_procrastination_is_declared_unavailable(self) -> None:
        """`submitted_at` yok → erteleme profili üretilmez, sahte sayı yazılmaz."""
        result = submission.student_profile(_page([]), [], NOW)
        proc = result["procrastination"]
        self.assertFalse(proc["available"])
        self.assertIsNone(proc["median_lead_ms"])
        self.assertIsNone(proc["last_minute"])
        self.assertIsNone(proc["last_24h_share"])
        self.assertIn("submitted_at", proc["reason"])

    def test_counted_on_time_flag_is_false_and_measure_named(self) -> None:
        """Ölçünün hangi alandan geldiği çıktıda taşınır (`MODULLER.md` §2.4)."""
        result = submission.student_profile(_page([]), [], NOW)
        self.assertFalse(result["counted_on_time_available"])
        self.assertEqual(result["measure"], "last_touch")
        self.assertIn("on_time_rate_by_last_touch", result["overall"])


if __name__ == "__main__":
    unittest.main()
