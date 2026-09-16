"""`compute.study` birim testleri: TR saat düzeltmesi, kapılar, düzenlilik."""

from __future__ import annotations

import unittest

from src.compute import clock, study

from .fakes import pomodoro

DAY = 86_400_000
HOUR = 3_600_000
# 2023-11-14 12:00 UTC → TR 15:00. Pencere aritmetiği bunun etrafında kurulur.
NOW = 1_699_963_200_000


def _at(days_ago: int, tr_hour: int) -> int:
    """`days_ago` gün önce, TR saatiyle `tr_hour`'da başlayan bir oturum anı."""
    day = clock.tr_day(NOW) - days_ago
    return day * DAY + tr_hour * HOUR - clock.TR_OFFSET_MS


class TestLocalTimeCorrection(unittest.TestCase):
    def test_tr_midnight_session_lands_on_correct_local_day(self) -> None:
        """TR 00:30 çalışması UTC'de önceki gündedir; modül TR gününü kullanır.

        `MODULLER.md` §2.6 adım 2 — tohumda bu dilimin payı %7,57.
        """
        started = _at(1, 0) + 30 * 60_000  # TR 00:30
        self.assertEqual(clock.tr_hour(started), 0)
        self.assertEqual(clock.tr_day(started), clock.tr_day(NOW) - 1)
        grid = study.heatmap([pomodoro(started)])
        self.assertEqual(grid[clock.tr_weekday(started)][0], 1)

    def test_night_share_uses_tr_hours(self) -> None:
        rows = [pomodoro(_at(1, 1)), pomodoro(_at(2, 14)), pomodoro(_at(3, 15)),
                pomodoro(_at(4, 16)), pomodoro(_at(5, 17))]
        result = study.student_profile(rows, NOW)
        self.assertAlmostEqual(result["recent_28d"]["night_share"], 0.2)


class TestCountableRows(unittest.TestCase):
    def test_uncounted_and_open_sessions_are_dropped(self) -> None:
        """`counted=False` ve `finished_at=None` satırları sayılmaz."""
        rows = [
            pomodoro(_at(1, 10)),
            pomodoro(_at(2, 10), counted=False),
            {"id": "open_x", "started_at": _at(3, 10), "finished_at": None,
             "duration_ms": None, "counted": None},
        ]
        self.assertEqual(len(study.countable(rows)), 1)

    def test_counters_from_profile_are_never_read(self) -> None:
        """Modülün imzası profil/sayaç almaz — sayaç şişmesinden etkilenmez."""
        result = study.student_profile([], NOW)
        self.assertEqual(result["recent_28d"]["n_stints"], 0)


class TestGates(unittest.TestCase):
    def test_heatmap_gate_at_five_stints(self) -> None:
        """GÜVEN KAPISI: 5 oturumun altında ısı haritası YOK, ilerleme gösterilir."""
        rows = [pomodoro(_at(i + 1, 10)) for i in range(4)]
        result = study.student_profile(rows, NOW)
        self.assertIsNone(result["heatmap"])
        self.assertEqual(result["heatmap_progress"], "4/5")

        rows.append(pomodoro(_at(5, 10)))
        result = study.student_profile(rows, NOW)
        self.assertIsNotNone(result["heatmap"])
        self.assertIsNone(result["heatmap_progress"])

    def test_regularity_gate_at_three_active_days(self) -> None:
        rows = [pomodoro(_at(1, 10)), pomodoro(_at(1, 12))]
        result = study.student_profile(rows, NOW)
        self.assertTrue(result["recent_28d"]["regularity_suppressed"])
        self.assertIsNone(result["recent_28d"]["regularity"])

    def test_regularity_value(self) -> None:
        rows = [pomodoro(_at(i + 1, 10)) for i in range(7)]
        result = study.student_profile(rows, NOW)
        self.assertAlmostEqual(result["recent_28d"]["regularity"], 7 / 28)


class TestBurstiness(unittest.TestCase):
    """Sayı hesaplanır, **bayrak üretilmez** (kusur K5).

    `burstiness` gün-arası yığılmayı ölçer; senaryonun "düzensiz çalışan"
    arketipi ise olay-öncesi yığılmayla tanımlıdır ve olay ekseni (sınav
    takvimi) `Source` arayüzünde yok. Altın kümede A4'ün medyanı 2,14, okul
    medyanı 2,18 — ölçü ayırmıyor. Ölçemediğimiz şeyi bayrağa çevirmiyoruz.
    """

    def test_burstiness_is_computed(self) -> None:
        rows = [pomodoro(_at(1, 9 + i)) for i in range(6)]  # tek günde 6
        rows += [pomodoro(_at(2, 10)), pomodoro(_at(3, 10))]  # iki günde 1'er
        result = study.student_profile(rows, NOW)
        # günlük sayılar: 6, 1, 1 → ortalama 8/3, max 6
        self.assertAlmostEqual(result["recent_28d"]["burstiness"], 6 / (8 / 3))

    def test_extreme_burst_still_produces_no_flag(self) -> None:
        rows = [pomodoro(_at(1, 8 + i)) for i in range(10)]
        rows += [pomodoro(_at(2, 10)), pomodoro(_at(3, 10)), pomodoro(_at(4, 10))]
        result = study.student_profile(rows, NOW)
        # 10, 1, 1, 1 → ortalama 3,25; 10/3,25 = 3,08
        self.assertGreaterEqual(result["recent_28d"]["burstiness"], 3.0)
        self.assertNotIn("bursty", result["recent_28d"])
        self.assertIn("ÖLÇMEZ", result["recent_28d"]["burstiness_limitation"])

    def test_night_window_matches_scenario(self) -> None:
        """K5b: senaryonun gece penceresi 22:00–02:00, yarı açık."""
        self.assertEqual(study.NIGHT_HOURS, (22, 23, 0, 1))
        rows = [pomodoro(_at(1, 22)), pomodoro(_at(2, 1)), pomodoro(_at(3, 3))]
        result = study.student_profile(rows, NOW)
        self.assertAlmostEqual(result["recent_28d"]["night_share"], 2 / 3)
        self.assertEqual(result["recent_28d"]["night_window_tr"], "[22:00, 02:00)")


class TestStreakAndComparison(unittest.TestCase):
    def test_local_streak_counts_consecutive_tr_days(self) -> None:
        rows = [pomodoro(_at(0, 10)), pomodoro(_at(1, 10)), pomodoro(_at(2, 10)),
                pomodoro(_at(4, 10))]
        self.assertEqual(study.local_streak(rows, NOW), 3)

    def test_streak_zero_when_gap(self) -> None:
        rows = [pomodoro(_at(5, 10))]
        self.assertEqual(study.local_streak(rows, NOW), 0)

    def test_self_comparison_uses_previous_window(self) -> None:
        """Akranla değil, kendi geçmişiyle karşılaştırılır."""
        rows = [pomodoro(_at(i + 1, 10)) for i in range(5)]
        rows += [pomodoro(_at(30 + i, 10)) for i in range(10)]
        result = study.student_profile(rows, NOW)
        self.assertEqual(result["recent_28d"]["n_stints"], 5)
        self.assertEqual(result["previous_28d"]["n_stints"], 10)
        self.assertEqual(result["change"]["stints_delta"], -5)


class TestDeclaredLimits(unittest.TestCase):
    def test_no_course_key_anywhere(self) -> None:
        """DTO kuralı: çalışma profilinde `course` alanı BULUNMAZ."""
        result = study.student_profile([pomodoro(_at(1, 10))], NOW)
        self.assertNotIn("course", result)
        self.assertNotIn("course", result["recent_28d"])

    def test_pre_exam_share_is_declared_unavailable(self) -> None:
        result = study.student_profile([], NOW)
        self.assertIsNone(result["pre_exam_share"])
        self.assertIn("Sınav takvimi", result["pre_exam_reason"])

    def test_pre_deadline_share_is_computed_separately(self) -> None:
        due = _at(1, 20)
        rows = [pomodoro(_at(1, 10)), pomodoro(_at(10, 10))]
        result = study.student_profile(rows, NOW, [due])
        self.assertAlmostEqual(result["pre_deadline_share"], 0.5)


if __name__ == "__main__":
    unittest.main()
