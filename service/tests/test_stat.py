"""`compute.stat` birim testleri — beklenen sayısal sonuçlarla."""

from __future__ import annotations

import unittest

from src.compute import stat


class TestCentralTendency(unittest.TestCase):
    def test_mean(self) -> None:
        self.assertEqual(stat.mean([1, 2, 3, 4]), 2.5)
        self.assertIsNone(stat.mean([]))

    def test_median_odd_and_even(self) -> None:
        self.assertEqual(stat.median([3, 1, 2]), 2)
        self.assertEqual(stat.median([1, 2, 3, 4]), 2.5)
        self.assertIsNone(stat.median([]))

    def test_stdev_pop_known_series(self) -> None:
        # Klasik örnek: popülasyon σ = 2,0
        self.assertAlmostEqual(stat.stdev_pop([2, 4, 4, 4, 5, 5, 7, 9]), 2.0)

    def test_mean_sd_pair(self) -> None:
        result = stat.mean_sd([2, 4, 4, 4, 5, 5, 7, 9])
        assert result is not None
        mu, sd = result
        self.assertAlmostEqual(mu, 5.0)
        self.assertAlmostEqual(sd, 2.0)


class TestZScore(unittest.TestCase):
    def test_plain(self) -> None:
        self.assertAlmostEqual(stat.z_score(6.0, 4.0, 2.0), 1.0)

    def test_sd_floor_prevents_explosion(self) -> None:
        """σ = 0 olduğunda z patlamaz; taban 0,05 devreye girer.

        `MODULLER.md` §2.0: homojen bir şubede 1 puanlık fark 'çok güçlü'
        görünmemeli.
        """
        self.assertAlmostEqual(stat.z_score(4.01, 4.0, 0.0), 0.2)
        # Taban olmasaydı sonsuz olurdu.
        self.assertLess(abs(stat.z_score(4.01, 4.0, 0.0)), 1.0)


class TestWilson(unittest.TestCase):
    def test_symmetric_case(self) -> None:
        result = stat.wilson_interval(5, 10)
        assert result is not None
        lo, hi = result
        self.assertAlmostEqual(lo, 0.236587, places=5)
        self.assertAlmostEqual(hi, 0.763413, places=5)

    def test_bounds_are_clamped(self) -> None:
        result = stat.wilson_interval(0, 5)
        assert result is not None
        self.assertGreaterEqual(result[0], 0.0)
        result = stat.wilson_interval(5, 5)
        assert result is not None
        self.assertLessEqual(result[1], 1.0)

    def test_invalid_inputs(self) -> None:
        self.assertIsNone(stat.wilson_interval(1, 0))
        self.assertIsNone(stat.wilson_interval(6, 5))


class TestTrend(unittest.TestCase):
    def test_perfect_line(self) -> None:
        self.assertAlmostEqual(stat.trend_slope([(0, 0), (1, 2), (2, 4)]), 2.0)

    def test_negative_slope(self) -> None:
        self.assertAlmostEqual(stat.trend_slope([(0, 10), (1, 8), (2, 6)]), -2.0)

    def test_needs_x_variance(self) -> None:
        self.assertIsNone(stat.trend_slope([(1, 5), (1, 7)]))
        self.assertIsNone(stat.trend_slope([(1, 5)]))


class TestRates(unittest.TestCase):
    def test_rate_returns_none_on_zero_denominator(self) -> None:
        """'Oran yok' ile 'oran sıfır' aynı şey değildir (`MODULLER.md` §2.5)."""
        self.assertIsNone(stat.rate(3, 0))
        self.assertEqual(stat.rate(0, 4), 0.0)

    def test_share_within(self) -> None:
        self.assertEqual(stat.share_within([0.1, 0.4, 0.5, 0.95], 0.30, 0.80), 0.5)
        self.assertIsNone(stat.share_within([], 0.0, 1.0))


if __name__ == "__main__":
    unittest.main()
