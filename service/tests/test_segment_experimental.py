"""URETIM / DENEYSEL boyut ayrimi.

`adim_sayisi` 2026-09-14'te deneysel katmana indirildi. Sozlesme:
  1. Etiket URETILMEYE DEVAM EDER (sema degismez, dort boyut da doldurulur).
  2. Asama 0 kapisini BLOKE ETMEZ.
  3. Asagi akisa (ogrenci profili / tavsiye) GIRMEZ.
  4. Ciktida `deneysel_boyutlar` altinda AYRICA raporlanir — sessizce gizlenmez.
Bu dosya dordunu de sinar.
"""

import json
import tempfile
import unittest
from pathlib import Path

from src.segment.cache import NullCache
from src.segment.config import SegmentConfig
from src.segment.rubric import (
    DIMENSION_ORDER,
    DIMENSIONS,
    EXPERIMENTAL_DIMENSIONS,
    PRODUCTION_DIMENSIONS,
    experimental_report,
)
from src.segment.runner import SegmentRunner
from src.segment.stability import build_report

ITEMS = [
    {"question_id": f"exam_question:q{i}", "course_name": "Matematik",
     "subject_name": "Konu",
     "text": f"{i} sayisi icin hangisi dogrudur?",
     "choices": ["birinci secenek metni", "ikinci secenek metni",
                 "ucuncu secenek metni", "dorduncu secenek metni"],
     "correct_choice_id": "c0", "p_value": 0.5,
     "gold": {"misconception_choice_text": None}}
    for i in range(12)
]


def cfg(**over):
    c = SegmentConfig()
    c.cache_enabled = False
    c.rpm = 10 ** 6
    c.temperature = 0.0
    for k, v in over.items():
        setattr(c, k, v)
    return c


class TestDimensionPartition(unittest.TestCase):

    def test_uretim_ve_deneysel_kumeler(self):
        self.assertEqual(PRODUCTION_DIMENSIONS,
                         ("bilissel_talep", "dikkat_tuzagi", "okuma_yuku"))
        self.assertEqual(EXPERIMENTAL_DIMENSIONS, ("adim_sayisi",))

    def test_iki_kume_birlikte_tum_boyutlari_kapsar(self):
        self.assertEqual(set(PRODUCTION_DIMENSIONS) | set(EXPERIMENTAL_DIMENSIONS),
                         set(DIMENSION_ORDER))
        self.assertFalse(set(PRODUCTION_DIMENSIONS) & set(EXPERIMENTAL_DIMENSIONS))

    def test_deneysel_boyut_gerekcesini_tasiyor(self):
        """Indirilen her boyut NEDEN indirildigini yazmak zorunda."""
        for d in EXPERIMENTAL_DIMENSIONS:
            note = DIMENSIONS[d].downgrade_note
            self.assertTrue(note.strip())
            self.assertIn("0,607", note)        # olculen alpha
            self.assertIn("63,3", note)         # olculen dogruluk
            self.assertIn("GERI ALMA KOSULU", note)
            self.assertIn("0,70", note)         # geri alma esigi

    def test_experimental_report_gerekceyi_dondurur(self):
        rap = experimental_report()
        self.assertEqual(set(rap), set(EXPERIMENTAL_DIMENSIONS))
        self.assertIn("DENEYSEL", rap["adim_sayisi"])

    def test_deneysel_boyut_hala_semada(self):
        """Etiket uretimi DURMAZ — yalnizca kullanimi daralir."""
        self.assertIn("adim_sayisi", DIMENSION_ORDER)
        self.assertIn("adim_sayisi", DIMENSIONS)


class TestGateIgnoresExperimental(unittest.TestCase):

    def _labels(self, mapping):
        return {r: {q: dict(v) for q, v in rows.items()}
                for r, rows in mapping.items()}

    def test_deneysel_boyut_kapiyi_bloke_etmez(self):
        """adim_sayisi tam uyumsuz, uretim boyutlari tam uyumlu -> KAPI ACIK."""
        r0, r1 = {}, {}
        for i in range(10):
            ortak = {"bilissel_talep": "analiz" if i % 2 else "hatirlama",
                     "dikkat_tuzagi": "var" if i % 2 else "yok",
                     "okuma_yuku": "yuksek" if i % 2 else "dusuk"}
            r0[f"q{i}"] = {**ortak, "adim_sayisi": "tek_adim"}
            r1[f"q{i}"] = {**ortak, "adim_sayisi": "cok_adim"}
        rep = build_report("intra", "v1", self._labels({"r0": r0, "r1": r1}))
        self.assertTrue(rep.gate_passed)
        self.assertEqual(rep.failing_dimensions(), [])
        # ...ama alpha'si HESAPLANMIS ve esigin altinda oldugu YAZILMIS olmali.
        self.assertIn("adim_sayisi", rep.experimental_alpha)
        self.assertLess(rep.experimental_alpha["adim_sayisi"], 0.70)
        self.assertEqual(rep.experimental_below_gate(), ["adim_sayisi"])

    def test_uretim_boyutu_kapiyi_hala_kapatir(self):
        r0, r1 = {}, {}
        for i in range(10):
            r0[f"q{i}"] = {"bilissel_talep": "analiz", "dikkat_tuzagi": "var",
                           "okuma_yuku": "dusuk", "adim_sayisi": "tek_adim"}
            r1[f"q{i}"] = {"bilissel_talep": "hatirlama", "dikkat_tuzagi": "yok",
                           "okuma_yuku": "yuksek", "adim_sayisi": "tek_adim"}
        rep = build_report("intra", "v1", self._labels({"r0": r0, "r1": r1}))
        self.assertFalse(rep.gate_passed)
        self.assertTrue(set(rep.failing_dimensions()) <= set(PRODUCTION_DIMENSIONS))

    def test_min_alpha_yalniz_uretim_boyutlarindan(self):
        r0, r1 = {}, {}
        for i in range(10):
            ortak = {"bilissel_talep": "analiz" if i % 2 else "hatirlama",
                     "dikkat_tuzagi": "var" if i % 2 else "yok",
                     "okuma_yuku": "yuksek" if i % 2 else "dusuk"}
            r0[f"q{i}"] = {**ortak, "adim_sayisi": "tek_adim"}
            r1[f"q{i}"] = {**ortak, "adim_sayisi": "cok_adim"}
        rep = build_report("intra", "v1", self._labels({"r0": r0, "r1": r1}))
        self.assertAlmostEqual(rep.min_alpha, 1.0, places=6)
        self.assertLess(rep.alpha["adim_sayisi"], rep.min_alpha)

    def test_rapor_deneysel_boyutu_ACIKCA_yaziyor(self):
        """Sessiz gizleme YOK: cikti sozlugunde ayri bir alan olmali."""
        r0, r1 = {}, {}
        for i in range(6):
            r0[f"q{i}"] = {d: DIMENSIONS[d].labels[i % len(DIMENSIONS[d].labels)]
                           for d in DIMENSION_ORDER}
            r1[f"q{i}"] = dict(r0[f"q{i}"])
        d = build_report("intra", "v1", self._labels({"r0": r0, "r1": r1})).to_dict()
        self.assertIn("deneysel_boyutlar", d)
        self.assertEqual(d["deneysel_boyutlar"]["boyutlar"], ["adim_sayisi"])
        self.assertFalse(d["deneysel_boyutlar"]["kapiyi_bloke_eder"])
        self.assertIn("adim_sayisi", d["deneysel_boyutlar"]["alpha"])
        self.assertEqual(d["gate_dimensions"], list(PRODUCTION_DIMENSIONS))


class TestDownstreamExcludesExperimental(unittest.TestCase):

    def test_ogrenci_profili_deneysel_boyutu_kullanmaz(self):
        """Asama 4 kovalarinda `adim_sayisi=` anahtari HIC olmamali."""
        with tempfile.TemporaryDirectory() as td:
            items_path = Path(td) / "items.json"
            items_path.write_text(json.dumps({"items": ITEMS}, ensure_ascii=False),
                                  encoding="utf-8")
            answers = Path(td) / "ans.surql"
            # `load_answers` ile ayni bicim (tohum .surql satirlari)
            satirlar = [
                "{ question: exam_question:⟨q%d⟩, user: user:⟨u%d⟩, "
                "selected: 'c0', text: NONE }" % (i, u)
                for i in range(12) for u in range(8)]
            answers.write_text("\n".join(satirlar), encoding="utf-8")

            c = cfg(items_path=items_path, answers_path=answers,
                    manifest_path=Path(td) / "yok.json",
                    out_dir=Path(td) / "out", stability_n=6, intra_replicates=2)
            runner = SegmentRunner(c, mock=True, cache=NullCache())
            batch = runner.run_variant("baseline", ITEMS)
            out = runner.stage4_students(batch, ITEMS)

            self.assertEqual(out["durum"], "tamam")
            anahtarlar = set(out["segment_dogruluk_ortalamasi"])
            self.assertTrue(anahtarlar, "profil bos cikmamali")
            for k in anahtarlar:
                self.assertFalse(k.startswith("adim_sayisi="),
                                 f"deneysel boyut asagi akisa sizdi: {k}")
            for k in out["segment_karsitliklari"]:
                self.assertFalse(k.startswith("adim_sayisi:"),
                                 f"deneysel boyut karsitliklara sizdi: {k}")

    def test_etiket_yine_de_uretiliyor(self):
        """Asagi akisa girmemesi, etiketlenmedigi anlamina GELMEZ."""
        c = cfg()
        runner = SegmentRunner(c, mock=True, cache=NullCache())
        batch = runner.run_variant("baseline", ITEMS[:3])
        for seg in batch.results.values():
            self.assertIn("adim_sayisi", seg.labels)
            self.assertIn(seg.label("adim_sayisi"),
                          DIMENSIONS["adim_sayisi"].labels)
            self.assertIn("adim_sayisi", seg.to_dict()["labels"])


class TestRunnerReportsExperimental(unittest.TestCase):

    def test_stage0_ciktisinda_deneysel_alan_var(self):
        with tempfile.TemporaryDirectory() as td:
            items_path = Path(td) / "items.json"
            items_path.write_text(json.dumps({"items": ITEMS}, ensure_ascii=False),
                                  encoding="utf-8")
            c = cfg(items_path=items_path, stability_n=6, intra_replicates=2,
                    inter_variants=1, out_dir=Path(td) / "out")
            runner = SegmentRunner(c, mock=True, cache=NullCache())
            runner.stage0_stability(ITEMS)
            dn = runner.result.stage0["deneysel_boyutlar"]
            self.assertEqual(dn["boyutlar"], ["adim_sayisi"])
            self.assertFalse(dn["kapiyi_bloke_eder"])
            self.assertFalse(dn["asagi_akista_kullanilir"])
            self.assertIn("adim_sayisi", dn["intra_alpha"])
            self.assertIn("DENEYSEL", dn["gerekce"]["adim_sayisi"])
            self.assertEqual(runner.result.stage0["gate_dimensions"],
                             list(PRODUCTION_DIMENSIONS))


if __name__ == "__main__":
    unittest.main()
