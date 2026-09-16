"""Varyansli sinama kumesi (`fixtures/probe_tr`) ve gunluk yonlendirmesi.

NEDEN BU FIKSTUR VAR: tohum verisinde (`work/items_enriched.json`) iki boyutun
VARYANSI YOK — sablon sorularin hicbiri gercekten cok adimli degil ve hicbirinin
okuma yuku yuksek degil. Canli kosuda model bu yuzden `adim_sayisi` icin %100
"tek_adim", `okuma_yuku` icin %98,7 "dusuk" dedi. Bu bir istem kusuru DEGIL,
veri kusurudur. Bu fikstur, hattin VARYANS OLDUGUNDA ayirim yapip yapmadigini
sinamak icin elle yazilmistir.
"""

import io
import json
import re
import sys
import unittest
from collections import Counter
from pathlib import Path

from src.segment.config import log, set_log_level
from src.segment.rubric import DIMENSIONS, DIMENSION_ORDER
from src.segment.runner import load_items

FIXTURE = (Path(__file__).resolve().parents[1] / "fixtures" / "probe_tr"
           / "probe_items.json")


def _payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class TestProbeFixture(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.payload = _payload()
        cls.items = cls.payload["items"]

    def test_otuz_madde(self):
        self.assertEqual(len(self.items), 30)

    def test_tasarim_dagilimi_tam_dengeli(self):
        """Dort boyutta da kasitli denge — dejenere boyut sinanamazdi."""
        beklenen = {
            "bilissel_talep": {"hatirlama": 10, "uygulama": 10, "analiz": 10},
            "adim_sayisi": {"tek_adim": 15, "cok_adim": 15},
            "okuma_yuku": {"dusuk": 15, "yuksek": 15},
            "dikkat_tuzagi": {"var": 15, "yok": 15},
        }
        for dim, hedef in beklenen.items():
            with self.subTest(dim=dim):
                sayim = Counter(i["gold_segment"][dim] for i in self.items)
                self.assertEqual(dict(sayim), hedef)

    def test_altin_etiketler_izinli_kumede(self):
        for it in self.items:
            for dim in DIMENSION_ORDER:
                self.assertIn(it["gold_segment"][dim], DIMENSIONS[dim].labels)

    def test_tuzak_indeksi_tutarli(self):
        for it in self.items:
            g = it["gold_segment"]
            idx = g["tuzak_sik_index"]
            if g["dikkat_tuzagi"] == "var":
                self.assertIsNotNone(idx)
                self.assertTrue(0 <= idx < len(it["choices"]))
                self.assertNotEqual(idx, g["dogru_sik_index"])
                # `gold` blogu da ayni sikki gostermeli
                self.assertEqual(it["gold"]["misconception_choice_text"],
                                 it["choices"][idx])
            else:
                self.assertIsNone(idx)
                self.assertIsNone(it["gold"]["misconception_choice_text"])

    def test_tuzaklar_ONERME_biciminde_yonergeye_uygun(self):
        """Rubric siniri: sayisal celdirici TEK BASINA 'var' yapmaz.

        YONERGE BELIRSIZLIGI (bu fikstur yazilirken ortaya cikti, KAYDA GECIRILDI):
        `rubric.py` sinir durumu "yanilgi SOZEL olarak ifade edilmis olmali" diyor.
        Bu ifade duz okundugunda `(a+b)^n = a^n + b^n` gibi SEMBOLIK bir yanlis
        ozdesligi de disarida birakir — oysa tohum verisindeki 741 altin
        pozitifin bir kismi (`content_tr.py::MISCONCEPTIONS`) tam olarak bu
        bicimdedir. Yani kural harfi harfine uygulanirsa KENDI ALTIN KUMEMIZI
        eler.

        Yonergenin AMACI "yanlis bir KURAL one suruluyor mu" ayrimidir; disarida
        birakmak istedigi sey ciplak sayidir (24/18/36/12). Bu yuzden olcut
        burada ONERME olarak isletilir: tuzak sik ya en az uc harfli sozcuk
        icerir ya da bir bagintl isareti (=, <, >, ≠) tasiyan bir ozdesliktir.
        Ciplak sayi ya da kume yine gecemez.

        `rubric.py` bir sonraki revizyonda bu ifadeyi netlestirmelidir; uretim
        mantigina bu turda dokunulmadi.
        """
        BAGINTI = ("=", "<", ">", "≠", "≤", "≥")
        for it in self.items:
            g = it["gold_segment"]
            if g["dikkat_tuzagi"] != "var":
                continue
            metin = it["choices"][g["tuzak_sik_index"]]
            # Noktalama ayiklanarak harf belirtecleri sayilir ("yarisidir." -> ok)
            sozcukler = [w for w in re.findall(r"[^\W\d_]{3,}", metin, re.UNICODE)]
            onerme = len(sozcukler) >= 3 or any(b in metin for b in BAGINTI)
            self.assertTrue(
                onerme,
                f"{it['question_id']}: tuzak sik bir onerme degil -> {metin!r}")

    def test_tuzak_ciplak_sayi_olamaz(self):
        """Ciplak sayi/kume tuzak sayilmaz — yonergenin asil disladigi sey."""
        for it in self.items:
            g = it["gold_segment"]
            if g["dikkat_tuzagi"] != "var":
                continue
            metin = it["choices"][g["tuzak_sik_index"]]
            ciplak = metin.replace(",", "").replace(".", "").replace("-", "")
            self.assertFalse(ciplak.isdigit(),
                             f"{it['question_id']}: tuzak ciplak sayi -> {metin!r}")

    def test_sayisal_celdiricili_maddeler_yok_etiketli(self):
        """Siklari yalnizca sayi olan maddeler 'yok' olmali (rubric siniri)."""
        for it in self.items:
            sayisal = all(
                c.replace(",", "").replace(".", "").replace("-", "").isdigit()
                for c in it["choices"])
            if sayisal:
                self.assertEqual(it["gold_segment"]["dikkat_tuzagi"], "yok",
                                 it["question_id"])

    def test_okuma_yuku_gercekten_ayrisiyor(self):
        uzun = [len(i["text"]) + sum(len(c) for c in i["choices"])
                for i in self.items if i["gold_segment"]["okuma_yuku"] == "yuksek"]
        kisa = [len(i["text"]) + sum(len(c) for c in i["choices"])
                for i in self.items if i["gold_segment"]["okuma_yuku"] == "dusuk"]
        self.assertGreater(sum(uzun) / len(uzun), 2 * sum(kisa) / len(kisa) * 0.9)

    def test_dersler_karisik(self):
        dersler = {i["course_name"] for i in self.items}
        self.assertGreaterEqual(len(dersler), 6)

    def test_ampirik_alanlarin_sahte_oldugu_yazili(self):
        """`p_value`/`n_responses` yer tutucudur — dosyada acikca belirtilmeli."""
        self.assertIn("GERCEK OGRENCI VERISI DEGILDIR", self.payload["_not"])
        self.assertIn("YER TUTUCULARDIR", self.payload["_not"])

    def test_hat_fiksturu_degisiklik_olmadan_okuyor(self):
        """Sema `work/items_enriched.json` ile ayni -> `load_items` calisir."""
        yuklu = load_items(FIXTURE)
        self.assertEqual(len(yuklu), 30)
        for it in yuklu:
            for alan in ("question_id", "text", "choices", "subject_name",
                         "course_name", "gold", "correct_choice_id",
                         "distractor_distribution"):
                self.assertIn(alan, it)

    def test_istem_fiksturden_uretilebiliyor(self):
        from src.segment import prompts
        it = self.items[0]
        metin = prompts.get("v1").render(it, course_name=it["course_name"])
        self.assertIn(it["text"][:40], metin)
        self.assertIn("[0]", metin)


class TestLogToStderr(unittest.TestCase):
    """Gunlukler stdout'u kirletmemeli: stdout yalnizca JSON tasir."""

    def test_log_stdout_a_yazmaz(self):
        set_log_level("info")
        out, err = io.StringIO(), io.StringIO()
        eski_out, eski_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out, err
        try:
            log("info", "deneme satiri")
        finally:
            sys.stdout, sys.stderr = eski_out, eski_err
        self.assertEqual(out.getvalue(), "")
        self.assertIn("deneme satiri", err.getvalue())
        self.assertIn("[segment]", err.getvalue())

    def test_seviye_altindaki_satir_hic_yazilmaz(self):
        set_log_level("error")
        err = io.StringIO()
        eski = sys.stderr
        sys.stderr = err
        try:
            log("debug", "gorunmemeli")
        finally:
            sys.stderr = eski
            set_log_level("info")
        self.assertEqual(err.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
