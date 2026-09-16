"""Krippendorff alpha dogrulugu — ELLE HESAPLANMIS degerlere karsi.

Harici paket kullanilmadigi icin (`promptstability` Python <3.11 istiyor, depo
3.12+ uzerinde) alpha'nin dogrulugu burada kanitlanir. Her testin ustunde elle
yapilmis hesap adim adim yazilidir.
"""

import math
import unittest

from src.segment.stability import (
    alpha_is_degenerate,
    build_report,
    is_solid,
    krippendorff_alpha,
    masi_distance,
    pairwise_agreement,
)


class TestKrippendorffAlpha(unittest.TestCase):

    def test_mukemmel_uyum(self):
        units = [["a", "a"], ["b", "b"], ["a", "a"], ["b", "b"]]
        self.assertAlmostEqual(krippendorff_alpha(units), 1.0, places=10)

    def test_elle_hesaplanmis_ornek_binary(self):
        """4 birim, 2 kodlayici, ikili etiket -> alpha = 0,125.

        Birimler: (a,a) (b,b) (a,b) (b,a)
        Tesaduf matrisi (m_u = 2, payda m_u - 1 = 1):
          birim1: o_aa += 2*(2-1)/1 = 2
          birim2: o_bb += 2
          birim3: o_ab += 1, o_ba += 1, o_aa += 1*(1-1) = 0
          birim4: o_ab += 1, o_ba += 1
        Toplam: o_aa=2, o_bb=2, o_ab=2, o_ba=2 -> n_a = 4, n_b = 4, n = 8
        D_o = (o_ab + o_ba)/n = 4/8 = 0,5
        D_e = (n_a*n_b + n_b*n_a)/(n*(n-1)) = (16+16)/56 = 0,571428...
        alpha = 1 - 0,5/0,571428 = 1 - 0,875 = 0,125
        """
        units = [["a", "a"], ["b", "b"], ["a", "b"], ["b", "a"]]
        self.assertAlmostEqual(krippendorff_alpha(units), 0.125, places=10)

    def test_elle_hesaplanmis_ornek_sistematik_ters(self):
        """Tam sistematik uyumsuzluk -> alpha negatif.

        Birimler: (a,b) (a,b) (b,a) (b,a)
        Her birim: o_ab += 1, o_ba += 1  -> o_ab = o_ba = 4, o_aa = o_bb = 0
        n_a = 4, n_b = 4, n = 8
        D_o = 8/8 = 1,0
        D_e = 32/56 = 0,571428...
        alpha = 1 - 1/0,571428 = 1 - 1,75 = -0,75
        """
        units = [["a", "b"], ["a", "b"], ["b", "a"], ["b", "a"]]
        self.assertAlmostEqual(krippendorff_alpha(units), -0.75, places=10)

    def test_elle_hesaplanmis_uc_kodlayici_eksik_veriyle(self):
        """3 kodlayici, eksik veri, 2 kategori -> alpha = 0,28.

        Birimler:
          u1: a, a, a        (m=3)
          u2: b, b, None     (m=2)
          u3: a, b, b        (m=3)
          u4: None, a, b     (m=2)
        u1: n_a=3 -> o_aa += 3*2/2 = 3
        u2: n_b=2 -> o_bb += 2*1/1 = 2
        u3: n_a=1, n_b=2 -> o_aa += 0 ; o_bb += 2*1/2 = 1 ;
            o_ab += 1*2/2 = 1 ; o_ba += 1
        u4: n_a=1, n_b=1 -> o_ab += 1 ; o_ba += 1
        Toplam: o_aa = 3, o_bb = 3, o_ab = 2, o_ba = 2
        n_a = 3+2 = 5, n_b = 3+2 = 5, n = 10
        D_o = (2+2)/10 = 0,4
        D_e = (5*5 + 5*5)/(10*9) = 50/90 = 0,5555...
        alpha = 1 - 0,4/0,55555 = 1 - 0,72 = 0,28
        """
        units = [["a", "a", "a"], ["b", "b", None], ["a", "b", "b"],
                 [None, "a", "b"]]
        self.assertAlmostEqual(krippendorff_alpha(units), 0.28, places=10)

    def test_uc_kategori_elle(self):
        """3 kategori, 2 kodlayici.

        Birimler: (a,a) (b,b) (c,c) (a,b)
        o_aa = 2 + 0 = 2 ; o_bb = 2 ; o_cc = 2 ; o_ab = 1 ; o_ba = 1
        n_a = 3, n_b = 3, n_c = 2, n = 8
        D_o = 2/8 = 0,25
        D_e = (n^2 - sum n_c^2)/(n(n-1)) = (64 - (9+9+4))/56 = 42/56 = 0,75
        alpha = 1 - 0,25/0,75 = 0,666666...
        """
        units = [["a", "a"], ["b", "b"], ["c", "c"], ["a", "b"]]
        self.assertAlmostEqual(krippendorff_alpha(units), 2 / 3, places=10)

    def test_tek_degerlendiricili_birimler_atlanir(self):
        units = [["a"], ["b"], ["a", "a"], ["b", "b"]]
        self.assertAlmostEqual(krippendorff_alpha(units), 1.0, places=10)

    def test_yeterli_veri_yoksa_nan(self):
        self.assertTrue(math.isnan(krippendorff_alpha([["a"], ["b"]])))
        self.assertTrue(math.isnan(krippendorff_alpha([])))

    def test_tek_kategori_dejenere(self):
        units = [["a", "a"], ["a", "a"]]
        self.assertEqual(krippendorff_alpha(units), 1.0)
        self.assertTrue(alpha_is_degenerate(units))
        self.assertFalse(alpha_is_degenerate([["a", "b"]]))

    def test_masi_uzakligi(self):
        """Kume degerli (cok etiketli) veri icin MASI."""
        self.assertEqual(masi_distance({"a"}, {"a"}), 0.0)
        self.assertEqual(masi_distance({"a"}, {"b"}), 1.0)          # ayrik
        # {a} subset {a,b}: J = 1/2, M = 0,67 -> 1 - 0,335 = 0,665
        self.assertAlmostEqual(masi_distance({"a"}, {"a", "b"}), 0.665, places=10)

    def test_masi_ile_alpha_calisir(self):
        units = [[frozenset({"a"}), frozenset({"a"})],
                 [frozenset({"b"}), frozenset({"a", "b"})]]
        a = krippendorff_alpha(units, metric="masi")
        self.assertTrue(-1.0 <= a <= 1.0)

    def test_ham_uyum(self):
        units = [["a", "a", "b"]]  # 3 cift: aa (uyum), ab, ab
        self.assertAlmostEqual(pairwise_agreement(units), 1 / 3, places=10)


class TestStabilityReport(unittest.TestCase):

    def _labels(self, mapping):
        return {rater: {qid: dict(dims) for qid, dims in rows.items()}
                for rater, rows in mapping.items()}

    def test_kapi_alpha_esikaltinda_kapanir(self):
        """Bulgu 6: URETIM boyutunda alpha < 0,70 -> kapi KAPALI."""
        data = self._labels({
            "r0": {"q1": {"okuma_yuku": "dusuk"}, "q2": {"okuma_yuku": "dusuk"}},
            "r1": {"q1": {"okuma_yuku": "yuksek"}, "q2": {"okuma_yuku": "yuksek"}},
        })
        rep = build_report("intra", "v1", data, dimensions=["okuma_yuku"])
        self.assertLess(rep.min_alpha, 0.70)
        self.assertFalse(rep.gate_passed)
        self.assertEqual(rep.failing_dimensions(), ["okuma_yuku"])

    def test_kapi_yuksek_alphada_acilir(self):
        data = self._labels({
            "r0": {"q1": {"okuma_yuku": "dusuk"}, "q2": {"okuma_yuku": "yuksek"}},
            "r1": {"q1": {"okuma_yuku": "dusuk"}, "q2": {"okuma_yuku": "yuksek"}},
        })
        rep = build_report("intra", "v1", data, dimensions=["okuma_yuku"])
        self.assertTrue(rep.gate_passed)
        self.assertTrue(is_solid(rep))

    def test_nan_alpha_kapiyi_acmaz(self):
        """Tanimsiz alpha gecis sebebi DEGILDIR."""
        data = self._labels({"r0": {"q1": {"okuma_yuku": "dusuk"}}})
        rep = build_report("intra", "v1", data, dimensions=["okuma_yuku"])
        self.assertTrue(math.isnan(rep.min_alpha))
        self.assertFalse(rep.gate_passed)

    def test_yayginlik_paradoksu_notu(self):
        """Ham uyum yuksek + alpha dusuk -> ayrica raporlanir."""
        rows_a, rows_b = {}, {}
        for i in range(20):
            rows_a[f"q{i}"] = {"okuma_yuku": "dusuk"}
            rows_b[f"q{i}"] = {"okuma_yuku": "dusuk"}
        rows_b["q0"] = {"okuma_yuku": "yuksek"}
        rows_a["q1"] = {"okuma_yuku": "yuksek"}
        rep = build_report("intra", "v1", self._labels({"r0": rows_a, "r1": rows_b}),
                           dimensions=["okuma_yuku"])
        self.assertGreaterEqual(rep.raw_agreement["okuma_yuku"], 0.90)
        self.assertLess(rep.alpha["okuma_yuku"], 0.70)
        self.assertTrue(any("YAYGINLIK PARADOKSU" in n for n in rep.notes))


if __name__ == "__main__":
    unittest.main()
