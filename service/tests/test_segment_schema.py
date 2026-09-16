"""Cikti sozlesmesi dogrulamasi — dogrulanamayan yanit SESSIZCE KABUL EDILMEZ."""

import json
import unittest

from src.segment.rubric import DIMENSION_ORDER, DIMENSIONS, course_verbs, render_full_rubric
from src.segment.schema import SchemaError, extract_json, parse_label_json

CHOICES = ["birinci sik", "ikinci sik", "ucuncu sik", "dorduncu sik"]


def payload(**over):
    base = {
        "boyutlar": {
            "bilissel_talep": {"etiket": "uygulama", "guven": 0.8},
            "adim_sayisi": {"etiket": "tek_adim", "guven": 0.7},
            "dikkat_tuzagi": {"etiket": "yok", "guven": 0.9},
            "okuma_yuku": {"etiket": "dusuk", "guven": 0.6},
        },
        "tuzak_sik_index": None,
        "gerekce": "Tek formullu duz hesap.",
    }
    base.update(over)
    return json.dumps(base, ensure_ascii=False)


def parse(text):
    return parse_label_json(text, question_id="q1", choices=CHOICES,
                            prompt_version="v1", model="mock", variant="baseline")


class TestSchema(unittest.TestCase):

    def test_gecerli_yanit(self):
        seg = parse(payload())
        self.assertEqual(seg.label("bilissel_talep"), "uygulama")
        self.assertEqual(seg.labels["okuma_yuku"].confidence, 0.6)
        self.assertIsNone(seg.trap_choice_index)
        self.assertEqual(seg.label_tuple(),
                         ("uygulama", "tek_adim", "yok", "dusuk"))

    def test_markdown_citasi_icindeki_json_cikarilir(self):
        seg = parse("```json\n" + payload() + "\n```")
        self.assertEqual(seg.label("adim_sayisi"), "tek_adim")

    def test_bos_yanit_reddedilir(self):
        with self.assertRaises(SchemaError):
            parse("")

    def test_json_olmayan_yanit_reddedilir(self):
        with self.assertRaises(SchemaError):
            parse("Bu soru bence uygulama duzeyindedir.")

    def test_eksik_boyut_reddedilir(self):
        data = json.loads(payload())
        del data["boyutlar"]["okuma_yuku"]
        with self.assertRaises(SchemaError) as ctx:
            parse(json.dumps(data))
        self.assertIn("okuma_yuku", str(ctx.exception))

    def test_izinsiz_etiket_reddedilir(self):
        with self.assertRaises(SchemaError):
            parse(payload(boyutlar={
                **json.loads(payload())["boyutlar"],
                "bilissel_talep": {"etiket": "sentez", "guven": 0.9}}))

    def test_guven_yoksa_reddedilir(self):
        b = json.loads(payload())["boyutlar"]
        b["adim_sayisi"] = {"etiket": "tek_adim"}
        with self.assertRaises(SchemaError):
            parse(payload(boyutlar=b))

    def test_yalnizca_etiket_metni_reddedilir(self):
        b = json.loads(payload())["boyutlar"]
        b["adim_sayisi"] = "tek_adim"
        with self.assertRaises(SchemaError):
            parse(payload(boyutlar=b))

    def test_aralik_disi_guven_reddedilir(self):
        b = json.loads(payload())["boyutlar"]
        b["okuma_yuku"] = {"etiket": "dusuk", "guven": 1.4}
        with self.assertRaises(SchemaError):
            parse(payload(boyutlar=b))

    def test_tuzak_var_ama_index_yok_reddedilir(self):
        b = json.loads(payload())["boyutlar"]
        b["dikkat_tuzagi"] = {"etiket": "var", "guven": 0.8}
        with self.assertRaises(SchemaError):
            parse(payload(boyutlar=b))

    def test_tuzak_index_aralik_disi_reddedilir(self):
        b = json.loads(payload())["boyutlar"]
        b["dikkat_tuzagi"] = {"etiket": "var", "guven": 0.8}
        with self.assertRaises(SchemaError):
            parse(payload(boyutlar=b, tuzak_sik_index=9))

    def test_tuzak_yok_iken_index_verilemez(self):
        with self.assertRaises(SchemaError):
            parse(payload(tuzak_sik_index=2))

    def test_tuzak_var_metni_dogru_esler(self):
        b = json.loads(payload())["boyutlar"]
        b["dikkat_tuzagi"] = {"etiket": "var", "guven": 0.8}
        seg = parse(payload(boyutlar=b, tuzak_sik_index=2))
        self.assertEqual(seg.trap_choice_index, 2)
        self.assertEqual(seg.trap_choice_text, "ucuncu sik")

    def test_bos_gerekce_reddedilir(self):
        with self.assertRaises(SchemaError):
            parse(payload(gerekce="   "))

    def test_extract_json_kok_liste_reddedilir(self):
        with self.assertRaises(SchemaError):
            extract_json("[1, 2, 3]")


class TestRubric(unittest.TestCase):

    def test_dort_boyut_ve_kategori_sayisi(self):
        """Bulgu 4: kategori sayisini azalt (6 Bloom duzeyi degil)."""
        self.assertEqual(len(DIMENSION_ORDER), 4)
        self.assertLessEqual(max(len(DIMENSIONS[d].labels) for d in DIMENSION_ORDER), 3)

    def test_yalnizca_dikkat_tuzagi_dis_dogrulamali(self):
        externally = [d for d in DIMENSION_ORDER if DIMENSIONS[d].externally_validated]
        self.assertEqual(externally, ["dikkat_tuzagi"])

    def test_her_boyutun_her_etiketi_icin_olcut_var(self):
        for name in DIMENSION_ORDER:
            spec = DIMENSIONS[name]
            for label in spec.labels:
                self.assertIn(label, spec.criteria)
                self.assertTrue(spec.criteria[label].strip())

    def test_derse_ozgu_fiiller(self):
        """Bulgu 3: derse ozgu eylem fiili listesi."""
        self.assertTrue(course_verbs("Matematik"))
        self.assertEqual(course_verbs("Yok Boyle Ders"), {})
        text = render_full_rubric("Matematik")
        self.assertIn("turevini al", text)
        self.assertIn("EYLEM FIILLERI", text)


if __name__ == "__main__":
    unittest.main()
