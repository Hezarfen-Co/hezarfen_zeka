"""Etiketleyici varyantlari ve MockProvider ile UCTAN UCA kosu (anahtarsiz)."""

import json
import tempfile
import unittest
from pathlib import Path

from src.segment import prompts
from src.segment.cache import NullCache, ResponseCache
from src.segment.config import SegmentConfig
from src.segment.labelers import (
    BaseLabeler,
    BaselineLabeler,
    GeneratorCriticLabeler,
    HeterogeneousRolesLabeler,
    SelfConsistencyLabeler,
    build_labeler,
)
from src.segment.provider import BudgetExceeded, BudgetGuard, MockProvider
from src.segment.runner import (
    SegmentRunner,
    load_answers,
    load_items,
    load_student_gold,
    stratified_subset,
)
from src.segment.schema import SchemaError
from src.segment.validate import build_gold_set

REPO = Path(__file__).resolve().parents[2]

# URETILMIS tohum artefaktlari: depoda YOK, `.gitignore`'lu (`work/`,
# `seed/*.surql`); depoda yalnizca ureticisi var. Bunlara bagli testler
# dosya eksikken ATLANIR, artefakt uretilmisken kosar ve olcer.
ITEMS_ENRICHED = REPO / "work" / "items_enriched.json"
SEED_ANSWERS = REPO / "seed" / "11_exam_answer.surql"

ITEMS = [
    {"question_id": "q1", "course_name": "Biyoloji", "subject_name": "Kalıtım",
     "text": "Cekinik fenotip hangi kosulda gorulur?",
     "choices": ["Çekinik fenotip yalnız aa genotipinde görülür",
                 "Aa genotipinde de çekinik fenotip görülür", "(12, 5)", "(7, -3)"],
     "correct_choice_id": "c0", "p_value": 0.4,
     "gold": {"misconception_choice_text": "Aa genotipinde de çekinik fenotip görülür"}},
    {"question_id": "q2", "course_name": "Matematik", "subject_name": "Islemler",
     "text": "12 + 12 kactir?", "choices": ["24", "18", "36", "12"],
     "correct_choice_id": "c1", "p_value": 0.8,
     "gold": {"misconception_choice_text": "18"}},
    {"question_id": "q3", "course_name": "Tarih", "subject_name": "Kurulus",
     "text": "Hangisi soylenemez?", "choices": ["aaa bbb", "ccc ddd", "eee fff"],
     "correct_choice_id": "c2", "p_value": 0.6,
     "gold": {"misconception_choice_text": "ccc ddd"}},
]


def cfg(**over):
    c = SegmentConfig()
    c.cache_enabled = False
    c.rpm = 10 ** 6
    c.temperature = 0.0
    for k, v in over.items():
        setattr(c, k, v)
    return c


def mock(c=None):
    c = c or cfg()
    return MockProvider(c, budget=BudgetGuard(c.budget_usd))


class TestLabelers(unittest.TestCase):

    def test_baseline_tek_cagri(self):
        c = cfg()
        p = mock(c)
        b = BaselineLabeler(p, c).run(ITEMS)
        self.assertEqual(b.n, 3)
        self.assertEqual(b.usage.calls, 3)          # madde basina 1 cagri
        self.assertEqual(b.failures, {})

    def test_self_consistency_esit_butce_cagrisi(self):
        """Bulgu 7: k = equal_budget_calls."""
        c = cfg(equal_budget_calls=4)
        b = SelfConsistencyLabeler(mock(c), c).run(ITEMS)
        self.assertEqual(b.usage.calls, 3 * 4)
        for seg in b.results.values():
            self.assertEqual(len(seg.agent_labels), 4)

    def test_heterojen_roller_esit_butce_cagrisi(self):
        """3 rol + 1 birlestirici = 4 cagri -> self_consistency ile ESIT."""
        c = cfg(equal_budget_calls=4)
        lab = HeterogeneousRolesLabeler(mock(c), c)
        self.assertEqual(len(lab.roles), 3)
        b = lab.run(ITEMS)
        self.assertEqual(b.usage.calls, 3 * 4)
        for seg in b.results.values():
            self.assertEqual(len(seg.agent_labels), 3)
            # Bulgu 10: birlestirici ajanlarin GEREKCESINI gormez.
            self.assertTrue(all("gerekce" not in a for a in seg.agent_labels))

    def test_heterojen_rollerde_tartisma_turu_yok(self):
        """Ajanlar birbirinin ciktisini GORMEZ (bulgu 10: sikofantik uyum)."""
        c = cfg()
        seen = []

        class Spy(MockProvider):
            def _call(self, prompt, system, temperature, model, **kw):
                seen.append((system or "") + prompt)
                return super()._call(prompt, system, temperature, model, **kw)

        lab = HeterogeneousRolesLabeler(Spy(c, budget=BudgetGuard(5.0)), c)
        lab.label_item(ITEMS[0])
        role_prompts = seen[:3]
        for text in role_prompts:
            self.assertNotIn("DEGERLENDIRICI ETIKETLERI", text)

    def test_generator_critic_elestirmen_olculur(self):
        """Bulgu 8: dogrulayicinin etkisi VARSAYILMAZ, SAYILIR."""
        c = cfg()
        b = GeneratorCriticLabeler(mock(c), c).run(ITEMS)
        self.assertEqual(b.critic_total, 3)
        self.assertGreaterEqual(b.critic_changed, 0)
        self.assertLessEqual(b.critic_changed, b.critic_total)

    def test_sema_hatasi_sessizce_yutulmaz(self):
        class Broken(MockProvider):
            def _call(self, prompt, system, temperature, model, **kw):
                res = super()._call(prompt, system, temperature, model, **kw)
                res.text = "bu json degil"
                return res

        c = cfg()
        b = BaselineLabeler(Broken(c, budget=BudgetGuard(5.0)), c).run(ITEMS)
        self.assertEqual(b.n, 0)
        self.assertEqual(len(b.failures), 3)
        self.assertTrue(all(v.startswith("sema:") for v in b.failures.values()))

    def test_butce_asilinca_kosu_durur(self):
        c = cfg()
        c.model_ids["flash"] = "deepseek-flash"

        class Pricey(MockProvider):
            def model_for(self, role=None):
                return "deepseek-flash"    # gercek tarife -> maliyet olusur

        p = Pricey(c, budget=BudgetGuard(1e-6))
        b = BaselineLabeler(p, c).run(ITEMS)
        self.assertTrue(b.budget_stopped)
        self.assertLess(b.n, len(ITEMS))

    def test_bilinmeyen_varyant(self):
        with self.assertRaises(KeyError):
            build_labeler("yok_boyle", mock(), cfg())


class TestPrompts(unittest.TestCase):

    def test_surumler_versiyonlu(self):
        self.assertIn("v1", prompts.ALL_VERSIONS)
        for v in prompts.MANUAL_VARIANTS:
            self.assertEqual(prompts.get(v).paraphrase_of, "v1")

    def test_cikti_surumu_kaydeder(self):
        c = cfg()
        b = BaselineLabeler(mock(c), c, prompt_version="v1-p2").run(ITEMS[:1])
        self.assertEqual(b.results["q1"].prompt_version, "v1-p2")

    def test_parafraz_dogrulamasi_yer_tutucu_ister(self):
        with self.assertRaises(ValueError):
            prompts.validate_paraphrase("a {rubric} b", "a b")
        with self.assertRaises(ValueError):
            prompts.validate_paraphrase("a {rubric}", "a {rubric} {uydurma}")
        prompts.validate_paraphrase("a {rubric}", "{rubric} a")

    def test_bozuk_parafraz_elle_yazilana_duser(self):
        """Dogrulanamayan parafraz SESSIZCE kabul edilmez."""
        c = cfg()

        class BadParaphrase(MockProvider):
            def _call(self, prompt, system, temperature, model, **kw):
                res = super()._call(prompt, system, temperature, model, **kw)
                res.text = "yer tutucusu olmayan metin"
                return res

        out = prompts.generate_paraphrase_variants(
            BadParaphrase(c, budget=BudgetGuard(5.0)), "v1", n=2)
        self.assertEqual([p.version for p in out],
                         list(prompts.MANUAL_VARIANTS[:2]))


class TestRunnerEndToEnd(unittest.TestCase):

    def test_mock_ile_uctan_uca(self):
        """Anahtarsiz tam akis: Asama 0 kapisi -> 1 -> 2 -> 3."""
        with tempfile.TemporaryDirectory() as td:
            items_path = Path(td) / "items.json"
            items_path.write_text(json.dumps({"items": ITEMS * 8}, ensure_ascii=False),
                                  encoding="utf-8")
            c = cfg(items_path=items_path, stability_n=8, intra_replicates=3,
                    out_dir=Path(td) / "out", cache_dir=Path(td) / "cache")
            r = SegmentRunner(c, mock=True, cache=NullCache())
            res = r.run(negatives=10, students=False)
            self.assertIsNone(res.stopped_at)
            self.assertTrue(res.stage0["gate_passed"])
            self.assertIn("score", res.stage1)
            self.assertIn("self_consistency", res.stage2)
            self.assertIn("heterogeneous_roles", res.stage2)
            self.assertIn("decision", res.stage3)
            self.assertIn(res.stage3["decision"]["chosen"],
                          ("baseline", "self_consistency", "heterogeneous_roles"))
            # Mock uyarisi RAPORDA olmak zorunda.
            self.assertTrue(any("MockProvider" in cav for cav in res.caveats))
            # Gecersiz olcum isaretli.
            self.assertFalse(res.stage3["pvalue_probe"]["gecerli"])

    def test_kapi_kapaliysa_asama1e_gecilmez(self):
        """Bulgu 6: alpha < 0,70 -> tam kosuya GECILMEZ."""
        with tempfile.TemporaryDirectory() as td:
            items_path = Path(td) / "items.json"
            items_path.write_text(json.dumps({"items": ITEMS * 8}, ensure_ascii=False),
                                  encoding="utf-8")
            # Yuksek sicaklik -> mock kararsizlasir -> alpha duser.
            c = cfg(items_path=items_path, stability_n=8, intra_replicates=4,
                    temperature=1.0, out_dir=Path(td) / "out")
            res = SegmentRunner(c, mock=True, cache=NullCache()).run(negatives=10)
            self.assertEqual(res.stopped_at, "stage0_gate")
            self.assertFalse(res.stage0["gate_passed"])
            self.assertEqual(res.stage1, {})
            self.assertEqual(res.stage2, {})

    def test_onbellek_tekrar_kosuyu_bedava_yapar(self):
        with tempfile.TemporaryDirectory() as td:
            items_path = Path(td) / "items.json"
            items_path.write_text(json.dumps({"items": ITEMS * 4}, ensure_ascii=False),
                                  encoding="utf-8")
            cache_dir = Path(td) / "cache"
            kw = dict(items_path=items_path, stability_n=4, intra_replicates=2,
                      out_dir=Path(td) / "out", cache_dir=cache_dir)
            c1 = cfg(**kw)
            c1.cache_enabled = True
            r1 = SegmentRunner(c1, mock=True)
            r1.run(negatives=6)
            calls1 = r1.budget.calls

            c2 = cfg(**kw)
            c2.cache_enabled = True
            r2 = SegmentRunner(c2, mock=True)
            r2.run(negatives=6)
            self.assertGreater(calls1, 0)
            self.assertEqual(r2.budget.calls, 0)       # hepsi onbellekten
            self.assertGreater(r2.cache.stats()["hits"], 0)

    def test_katmanli_alt_kume_belirlenimci(self):
        a = stratified_subset(ITEMS * 10, 7, seed=1)
        b = stratified_subset(ITEMS * 10, 7, seed=1)
        self.assertEqual([i["question_id"] for i in a],
                         [i["question_id"] for i in b])
        self.assertEqual(len(a), 7)


class TestRealDataLoaders(unittest.TestCase):
    """Depodaki gercek tohum dosyalarini YALNIZCA OKUR.

    Iki testin okudugu artefakt **.gitignore'ludur** (`work/` ve `seed/*.surql`):
    depoda ureticisi var, ciktisi yok. Temiz bir kopyada (CI) o dosyalar
    bulunmaz, bu yuzden o testler `skipUnless` ile ATLANIR -- ama artefakt
    uretilmisken AYNI sekilde kosar ve olcer. Eksiklik davranisi zaten
    `test_eksik_dosya_bos_liste` ile ayrica pinlidir.
    """

    @unittest.skipUnless(
        ITEMS_ENRICHED.exists(),
        "work/items_enriched.json yok (gitignore'lu uretim ciktisi); generator/main.py --scale full",
    )
    def test_items_enriched_yuklenir(self):
        items = load_items(ITEMS_ENRICHED)
        self.assertGreater(len(items), 3000)
        gold = build_gold_set(items)
        # Tohum bilissel desenle yeniden uretildi: yanilgi tablosu 14'ten 92
        # konuya genisledi ve tuzak maddelerin payi arti; olculen 741.
        self.assertEqual(len(gold.positives), 741)

    def test_ogrenci_altin_etiketleri(self):
        gold = load_student_gold(REPO / "seed" / "_seed_manifest.json")
        self.assertEqual(len(gold), 250)
        sample = next(iter(gold.values()))
        for key in ("theta_base", "theta_trend", "gap_subjects", "archetype"):
            self.assertIn(key, sample)

    @unittest.skipUnless(
        SEED_ANSWERS.exists(),
        "seed/11_exam_answer.surql yok (gitignore'lu uretim ciktisi); generator/main.py --scale full",
    )
    def test_cevaplar_surql_dosyasindan_okunur(self):
        """Podman/SurrealDB BASLATILMADAN duz metin taramasiyla."""
        rows = load_answers(SEED_ANSWERS, max_rows=200)
        self.assertEqual(len(rows), 200)
        qid, uid, sel = rows[0]
        self.assertTrue(qid.startswith("exam_question:"))
        self.assertTrue(uid.startswith("user:"))
        self.assertTrue(sel is None or isinstance(sel, str))

    def test_eksik_dosya_bos_liste(self):
        self.assertEqual(load_answers(REPO / "yok_boyle_dosya.surql"), [])
        self.assertEqual(load_student_gold(REPO / "yok.json"), {})


if __name__ == "__main__":
    unittest.main()
