"""Dogrulama katmani: altin kume, olcutler, McNemar, karar kurali, gecersiz olcum."""

import unittest
from pathlib import Path

from src.segment.labelers import LabelBatch
from src.segment.schema import CallUsage, DimensionResult, ItemSegmentation
from src.segment.validate import (
    MISCONCEPTION_PAIRS,
    PRF,
    VariantScore,
    build_gold_set,
    compare,
    load_misconception_pairs,
    mcnemar_exact,
    pvalue_probe,
    score_variant,
    wrong_texts,
)

REPO = Path(__file__).resolve().parents[2]

# URETILMIS tohum artefakti: depoda YOK, `.gitignore`'lu (`work/`). Temiz bir
# kopyada (CI) bulunmaz; eksikken asagidaki test ATLANIR, artefakt
# uretilmisken kosar ve olcer.
ITEMS_ENRICHED = REPO / "work" / "items_enriched.json"


def item(qid, choices, gold_text=None, p_value=0.5):
    return {"question_id": qid, "choices": choices, "text": f"{qid} kokü",
            "p_value": p_value,
            "gold": {"misconception_choice_text": gold_text}}


def seg(qid, trap_index=None, choices=None, talep="uygulama", agents=None):
    labels = {
        "bilissel_talep": DimensionResult(talep, 0.8),
        "adim_sayisi": DimensionResult("tek_adim", 0.8),
        "dikkat_tuzagi": DimensionResult("var" if trap_index is not None else "yok", 0.8),
        "okuma_yuku": DimensionResult("dusuk", 0.8),
    }
    return ItemSegmentation(
        question_id=qid, labels=labels, trap_choice_index=trap_index,
        trap_choice_text=(choices[trap_index] if trap_index is not None else None),
        rationale="x", prompt_version="v1", model="mock", variant="t",
        usage=CallUsage(tokens_in=100, tokens_out=20, calls=1),
        agent_labels=agents or [])


def batch(variant, segs):
    b = LabelBatch(variant=variant, prompt_version="v1", model="mock")
    for s in segs:
        b.results[s.question_id] = s
        b.usage.add(s.usage)
    return b


class TestGoldSet(unittest.TestCase):

    @unittest.skipUnless(
        ITEMS_ENRICHED.exists(),
        "work/items_enriched.json yok (gitignore'lu uretim ciktisi); generator/main.py --scale full",
    )
    def test_gercek_veride_741_pozitif(self):
        """OLCULEN sayi: 741 gercek anlamsal yanilgi celdiricisi.

        Onceki deger 196 idi; tohum bilissel desenle yeniden uretilirken
        `content_tr.MISCONCEPTIONS` 14 konudan 92 konuya genisletildi ve
        `dikkat_tuzagi = var` etiketi maddelerin ~%45'ine dagitildi.
        """
        import json
        items = json.loads(ITEMS_ENRICHED.read_text(encoding="utf-8"))["items"]
        gold = build_gold_set([i for i in items if len(i.get("choices") or []) >= 3])
        self.assertEqual(len(gold.positives), 741)
        self.assertEqual(len(gold.expected_trap), 741)
        # Her pozitifin altin etiketi TABLODAKI yanilgi metnidir.
        wrongs = wrong_texts(MISCONCEPTION_PAIRS)
        self.assertTrue(all(t in wrongs for t in gold.expected_trap.values()))

    def test_uretecteki_tablo_ile_ayni(self):
        """`generator/content_tr.py` degistiyse sessiz sapma olmasin."""
        live = load_misconception_pairs(REPO / "generator" / "content_tr.py")
        self.assertEqual(set(live), set(MISCONCEPTION_PAIRS))
        self.assertEqual(wrong_texts(live), wrong_texts(MISCONCEPTION_PAIRS))

    def test_negatif_ornekleme_belirlenimci(self):
        items = [item(f"q{i}", [f"a{i}", f"b{i}", f"c{i}"]) for i in range(50)]
        g1 = build_gold_set(items, n_negative=10, seed=7)
        g2 = build_gold_set(items, n_negative=10, seed=7)
        self.assertEqual([i["question_id"] for i in g1.negatives],
                         [i["question_id"] for i in g2.negatives])

    def test_belirsiz_madde_ne_pozitif_ne_negatif(self):
        """Sikta yanilgi var ama altin etiket baska sikki gosteriyorsa ATILIR."""
        w = sorted(wrong_texts(MISCONCEPTION_PAIRS))[0]
        items = [item("q1", [w, "x", "y"], gold_text="x")]
        g = build_gold_set(items)
        self.assertEqual(len(g.positives), 0)
        self.assertEqual(len(g.negatives), 0)


class TestScoring(unittest.TestCase):

    def setUp(self):
        w = sorted(wrong_texts(MISCONCEPTION_PAIRS))[0]
        self.pos = item("p1", ["dogru", w, "z"], gold_text=w)
        self.neg = item("n1", ["a", "b", "c"])
        self.gold = build_gold_set([self.pos, self.neg])

    def test_tam_dogru_etiketleme(self):
        b = batch("x", [seg("p1", trap_index=1, choices=self.pos["choices"]),
                        seg("n1")])
        sc = score_variant(b, self.gold)
        self.assertEqual(sc.localized.to_dict()["f1"], 1.0)
        self.assertEqual(sc.localized.tn, 1)

    def test_yanlis_sik_kati_olcutte_kacirma_sayilir(self):
        """'var' dedi ama YANLIS sikki gosterdi: detection TP, localized FN."""
        b = batch("x", [seg("p1", trap_index=0, choices=self.pos["choices"]),
                        seg("n1")])
        sc = score_variant(b, self.gold)
        self.assertEqual(sc.detection.tp, 1)
        self.assertEqual(sc.localized.tp, 0)
        self.assertEqual(sc.localized.fn, 1)

    def test_yanlis_pozitif(self):
        b = batch("x", [seg("p1", trap_index=1, choices=self.pos["choices"]),
                        seg("n1", trap_index=0, choices=self.neg["choices"])])
        sc = score_variant(b, self.gold)
        self.assertEqual(sc.localized.fp, 1)
        self.assertAlmostEqual(sc.localized.precision, 0.5)

    def test_etiketlenemeyen_pozitif_kacirma_sayilir(self):
        """Sema dogrulamasini gecemeyen madde SESSIZCE atlanmaz."""
        b = batch("x", [seg("n1")])
        sc = score_variant(b, self.gold)
        self.assertEqual(sc.localized.fn, 1)
        self.assertFalse(sc.per_item["p1"])

    def test_uzlasma_yanilsamasi_bayragi(self):
        """Bulgu 10: uyum yuksek + dogruluk taban cizgi alti -> bayrak."""
        agents = [{"bilissel_talep": "uygulama", "adim_sayisi": "tek_adim",
                   "dikkat_tuzagi": "yok", "okuma_yuku": "dusuk"} for _ in range(3)]
        b = batch("hetero", [seg("p1", agents=agents), seg("n1", agents=agents)])
        sc = score_variant(b, self.gold, baseline_localized_f1=0.9)
        self.assertTrue(sc.consensus_illusion)
        self.assertTrue(any("UZLASMA YANILSAMASI" in n for n in sc.notes))

    def test_yuksek_uyum_ama_dogruluk_iyiyse_bayrak_yok(self):
        agents = [{"bilissel_talep": "uygulama", "adim_sayisi": "tek_adim",
                   "dikkat_tuzagi": "var", "okuma_yuku": "dusuk"} for _ in range(3)]
        b = batch("hetero", [seg("p1", trap_index=1, choices=self.pos["choices"],
                                 agents=agents), seg("n1")])
        sc = score_variant(b, self.gold, baseline_localized_f1=0.1)
        self.assertFalse(sc.consensus_illusion)


class TestMcNemar(unittest.TestCase):

    def test_fark_yoksa_p_bir(self):
        a = {"q1": True, "q2": False}
        self.assertEqual(mcnemar_exact(a, dict(a)), (0, 0, 1.0))

    def test_elle_hesaplanmis_p(self):
        """b=5, c=0 -> p = 2 * C(5,0)/2^5 = 2/32 = 0,0625."""
        a = {f"q{i}": True for i in range(5)}
        bb = {f"q{i}": False for i in range(5)}
        b, c, p = mcnemar_exact(a, bb)
        self.assertEqual((b, c), (5, 0))
        self.assertAlmostEqual(p, 0.0625, places=10)

    def test_p_bir_ile_sinirlidir(self):
        a = {"q1": True, "q2": False}
        bb = {"q1": False, "q2": True}
        self.assertEqual(mcnemar_exact(a, bb)[2], 1.0)


class TestDecisionRule(unittest.TestCase):

    def _score(self, name, f1_correct, n=40, calls=4.0):
        sc = VariantScore(variant=name, calls_per_item=calls)
        for i in range(n):
            ok = i < f1_correct
            sc.per_item[f"q{i}"] = ok
            if ok:
                sc.localized.tp += 1
            else:
                sc.localized.fn += 1
        return sc

    def test_yetersiz_etki_taban_cizgiye_duser(self):
        base = self._score("baseline", 20, calls=1.0)
        v = self._score("self_consistency", 21)
        dec = compare(base, [v], target_calls=4)
        self.assertEqual(dec.chosen, "baseline")
        self.assertIn("asgari etki", dec.reason)

    def test_anlamli_ustunluk_varyanti_secer(self):
        base = self._score("baseline", 10, calls=1.0)
        v = self._score("self_consistency", 30)
        dec = compare(base, [v], target_calls=4)
        self.assertEqual(dec.chosen, "self_consistency")
        self.assertLess(dec.p_value, 0.05)
        self.assertGreaterEqual(dec.delta, 0.03)

    def test_esit_butce_disi_varyant_yarisamaz(self):
        """Bulgu 7: karsilastirma ESIT token butcesinde yapilir."""
        base = self._score("baseline", 10, calls=1.0)
        v = self._score("generator_critic", 35, calls=2.0)   # hedef 4
        dec = compare(base, [v], target_calls=4)
        self.assertEqual(dec.chosen, "baseline")
        self.assertIn("ESIT BUTCE DISI", " ".join(dec.notes))

    def test_butce_toleransi_icinde_kabul(self):
        base = self._score("baseline", 10, calls=1.0)
        v = self._score("self_consistency", 30, calls=3.5)   # 4 * (1 - 0,125)
        dec = compare(base, [v], target_calls=4, budget_tolerance=0.15)
        self.assertEqual(dec.chosen, "self_consistency")


class TestInvalidMeasurement(unittest.TestCase):

    def test_pvalue_probe_daima_gecersiz_isaretlenir(self):
        """Bu veride metin ile zorluk BAGIMSIZ uretildi -> olcum anlamsiz."""
        items = [item(f"q{i}", ["a", "b", "c"], p_value=i / 10) for i in range(10)]
        b = batch("baseline", [seg(f"q{i}", talep="analiz") for i in range(10)])
        out = pvalue_probe(b, items)
        self.assertFalse(out["gecerli"])
        self.assertIn("ANLAMSIZ", out["not"])


class TestPRF(unittest.TestCase):

    def test_bos_sayaclar_sifir_dondurur(self):
        p = PRF()
        self.assertEqual((p.precision, p.recall, p.f1), (0.0, 0.0, 0.0))

    def test_elle_hesap(self):
        p = PRF(tp=3, fp=1, fn=2)
        self.assertAlmostEqual(p.precision, 0.75)
        self.assertAlmostEqual(p.recall, 0.6)
        self.assertAlmostEqual(p.f1, 2 * 0.75 * 0.6 / 1.35)


if __name__ == "__main__":
    unittest.main()
