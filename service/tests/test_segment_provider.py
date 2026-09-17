"""Saglayici katmani: butce tavani, onbellek, hiz siniri, yeniden deneme, Mock.

Gercek `DeepSeekProvider` BU TESTLERDE CAGRILMAZ; yalnizca anahtarsizken dogru
hatayi verdigi kontrol edilir (ag'a cikilmaz).
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.segment.cache import NullCache, ResponseCache
from src.segment.config import (
    DEFAULT_MODEL_IDS,
    SegmentConfig,
    SegmentConfigError,
)
from src.segment.provider import (
    LIVE_MODELS,
    MODEL_ALIASES,
    PRICING,
    BaseProvider,
    BudgetExceeded,
    BudgetGuard,
    ChatResult,
    DeepSeekProvider,
    MockProvider,
    ProviderError,
    RateLimiter,
    Usage,
    build_provider,
    cost_usd,
    parse_item_from_prompt,
)
from src.segment import provider as provider_mod
from src.segment.schema import parse_label_json

# Gercek altin ciftlerden biri (Kalitim) — sozel ikiz sik ornegi.
ITEM = {
    "question_id": "q1",
    "text": "Kalitim konusunda cekinik fenotipin gorulme kosulu hangisidir?",
    "choices": ["Çekinik fenotip yalnız aa genotipinde görülür",
                "Aa genotipinde de çekinik fenotip görülür",
                "(12, 5)", "(7, -3)"],
    "subject_name": "Kalıtım",
    "course_name": "Biyoloji",
}


def cfg(**over):
    c = SegmentConfig()
    c.cache_enabled = False
    c.rpm = 10 ** 6
    for k, v in over.items():
        setattr(c, k, v)
    return c


class TestUsageAndCost(unittest.TestCase):

    def test_cache_alani_yoksa_hepsi_miss_sayilir(self):
        u = Usage.from_api({"prompt_tokens": 100, "completion_tokens": 20})
        self.assertEqual((u.input_cache_hit, u.input_cache_miss, u.output),
                         (0, 100, 20))

    def test_maliyet_hesabi(self):
        u = Usage(input_cache_hit=0, input_cache_miss=1_000_000, output=1_000_000)
        # Uctaki gercek ad (2026-09-14): deepseek-flash.
        self.assertAlmostEqual(cost_usd("deepseek-flash", u), 0.44 + 1.32, places=9)
        self.assertAlmostEqual(cost_usd("deepseek-v4-pro", u), 1.32 + 3.96, places=9)

    def test_bilinmeyen_model_en_pahali_tarifeyle_ucretlenir(self):
        u = Usage(input_cache_miss=1_000_000, output=0)
        self.assertGreater(cost_usd("bilinmeyen-model", u), 0.0)


class TestModelCatalogRegression(unittest.TestCase):
    """Model adlari ile fiyat tablosunun AYRISMASINI yakalayan regresyon testi.

    NEDEN: 2026-09-14'te uctan olculdu ki `GET /models` TAM OLARAK iki model
    donduruyor (`deepseek-flash`, `deepseek-v4-pro`); koddaki tablo ise artik
    var olmayan `deepseek-v4-flash` / `deepseek-chat` / `deepseek-reasoner`
    adlarini kullaniyordu. Sonuc: her cagri "bilinmeyen model" dalina dusup EN
    PAHALI tarifeyle ucretleniyor, yani USD tavani YANLIS calisiyordu. Bu test
    o zaman VAR OLSAYDI kirilma ilk anda yakalanirdi — asil degeri budur.
    """

    def test_her_rol_modelinin_fiyat_satiri_var(self):
        for role, model in DEFAULT_MODEL_IDS.items():
            with self.subTest(role=role, model=model):
                key = MODEL_ALIASES.get(model, model)
                self.assertIn(key, PRICING,
                              f"'{role}' rolunun modeli {model!r} fiyat "
                              "tablosunda yok -> en pahali tarifeye duser.")

    def test_uctaki_modellerin_fiyat_satiri_var(self):
        for model in LIVE_MODELS:
            self.assertIn(MODEL_ALIASES.get(model, model), PRICING)

    def test_olu_model_adlari_temizlendi(self):
        for dead in ("deepseek-chat", "deepseek-reasoner", "deepseek-v4-flash"):
            self.assertNotIn(dead, PRICING)
            self.assertNotIn(dead, MODEL_ALIASES)
            self.assertNotIn(dead, DEFAULT_MODEL_IDS.values())

    def test_rol_modelleri_uctaki_katalogun_icinde(self):
        self.assertTrue(set(DEFAULT_MODEL_IDS.values()) <= set(LIVE_MODELS))

    def test_bilinmeyen_model_hala_en_pahali_tarifeye_duser(self):
        """Temkinli davranis KORUNDU (ama artik tetiklenmemeli)."""
        u = Usage(input_cache_miss=1_000_000)
        worst = max(PRICING.values(), key=lambda p: p["out"])["in_miss"]
        self.assertAlmostEqual(cost_usd("uydurma-model", u), worst, places=9)
        self.assertGreater(cost_usd("uydurma-model", u),
                           cost_usd("deepseek-flash", u))


class TestThinking(unittest.TestCase):
    """Akil yurutme parametreleri — govdeye DOGRU BICIMDE konuyor mu.

    UCTAN OLCULDU: `thinking` METIN degil NESNE bekler; duz metin gonderilirse
    `400 invalid type: string, expected struct ThinkingOptions` doner.
    """

    def _payload(self, **over):
        c = cfg(api_key="sahte", **over)
        p = DeepSeekProvider(c, budget=BudgetGuard(10.0), sleep=lambda _s: None)
        return p, c

    def test_thinking_nesne_olarak_konur_metin_degil(self):
        p, c = self._payload(thinking="enabled")
        body = p.build_payload("soru", None, 0.0, "deepseek-v4-pro")
        self.assertEqual(body["thinking"], {"type": "enabled"})
        self.assertNotIsInstance(body["thinking"], str)

    def test_disabled_da_nesne(self):
        p, _ = self._payload(thinking="disabled")
        body = p.build_payload("soru", None, 0.0, "deepseek-v4-pro")
        self.assertEqual(body["thinking"], {"type": "disabled"})

    def test_bos_deger_uca_hic_gonderilmez(self):
        p, _ = self._payload(thinking="")
        body = p.build_payload("soru", None, 0.0, "deepseek-v4-pro")
        self.assertNotIn("thinking", body)

    def test_rol_varsayilanlari(self):
        """`reasoner` = pro + thinking enabled; `pro` = dusunce kapali."""
        p, _ = self._payload()
        self.assertEqual(
            p.build_payload("s", None, 0.0, "deepseek-v4-pro",
                            role="reasoner")["thinking"], {"type": "enabled"})
        self.assertEqual(
            p.build_payload("s", None, 0.0, "deepseek-v4-pro",
                            role="pro")["thinking"], {"type": "disabled"})
        self.assertNotIn("thinking",
                         p.build_payload("s", None, 0.0, "deepseek-flash",
                                         role="flash"))

    def test_reasoning_effort(self):
        p, _ = self._payload(reasoning_effort="high")
        body = p.build_payload("s", None, 0.0, "deepseek-v4-pro")
        self.assertEqual(body["reasoning_effort"], "high")
        p2, _ = self._payload()
        self.assertNotIn("reasoning_effort",
                         p2.build_payload("s", None, 0.0, "deepseek-flash"))

    def test_gecersiz_degerler_reddedilir(self):
        for bad in ("max", "high", "on"):        # uctan olculdu: 400 verir
            with self.assertRaises(SegmentConfigError):
                cfg(thinking=bad).validate()
        with self.assertRaises(SegmentConfigError):
            cfg(reasoning_effort="asiri").validate()

    def test_json_zorlamasi_yalniz_etiket_cagrilarinda(self):
        p, _ = self._payload()
        self.assertIn("response_format",
                      p.build_payload("s", None, 0.0, "deepseek-flash", kind="label"))
        self.assertNotIn("response_format",
                         p.build_payload("s", None, 0.0, "deepseek-flash",
                                         kind="paraphrase"))

    def test_reasoning_content_semaya_girmez(self):
        """Dusunce izi AYRI alanda; sema dogrulamasi yalniz `content` uzerinde."""
        from src.segment.labelers import BaselineLabeler

        class Thinker(MockProvider):
            def _call(self, prompt, system, temperature, model, **kw):
                res = super()._call(prompt, system, temperature, model, **kw)
                res.reasoning_content = "once sunu dusundum, sonra bunu"
                return res

        c = cfg()
        seg = BaselineLabeler(Thinker(c, budget=BudgetGuard(5.0)), c).label_item(ITEM)
        self.assertEqual(seg.reasoning_content, "once sunu dusundum, sonra bunu")
        self.assertNotIn("dusundum", seg.rationale)
        self.assertEqual(seg.to_dict()["reasoning_chars"],
                         len("once sunu dusundum, sonra bunu"))

    def test_thinking_onbellek_anahtarinin_parcasi(self):
        """Ayni istem, farkli akil yurutme kipi -> AYRI onbellek satiri."""
        with tempfile.TemporaryDirectory() as td:
            cache = ResponseCache(Path(td))
            c1 = cfg(thinking="enabled")
            c1.cache_enabled = True
            MockProvider(c1, cache=cache, budget=BudgetGuard(10.0)).chat("ayni istem")
            c2 = cfg(thinking="disabled")
            c2.cache_enabled = True
            r = MockProvider(c2, cache=cache, budget=BudgetGuard(10.0)).chat("ayni istem")
            self.assertFalse(r.cached)


class TestUsageFromApi(unittest.TestCase):
    """Maliyet GERCEK `usage` alanlarindan — tahmin yok."""

    def test_cache_hit_miss_ayri_tarifelenir(self):
        u = Usage.from_api({"prompt_tokens": 1_000_000,
                            "prompt_cache_hit_tokens": 900_000,
                            "prompt_cache_miss_tokens": 100_000,
                            "completion_tokens": 500,
                            "completion_tokens_details": {"reasoning_tokens": 300}})
        self.assertEqual(u.input_cache_hit, 900_000)
        self.assertEqual(u.input_cache_miss, 100_000)
        self.assertEqual(u.reasoning, 300)
        # 0,9M * 0,014 + 0,1M * 0,44 + 500 * 1,32 -> hepsi /1M
        beklenen = (900_000 * 0.014 + 100_000 * 0.44 + 500 * 1.32) / 1_000_000
        self.assertAlmostEqual(cost_usd("deepseek-flash", u), beklenen, places=12)

    def test_dusunce_token_i_iki_kez_sayilmaz(self):
        """`reasoning`, `output` icindedir; maliyet yalniz `output`tan gelir."""
        a = Usage(output=1000, reasoning=800)
        b = Usage(output=1000, reasoning=0)
        self.assertEqual(cost_usd("deepseek-v4-pro", a),
                         cost_usd("deepseek-v4-pro", b))

    def test_cache_alani_yoksa_hepsi_miss(self):
        u = Usage.from_api({"prompt_tokens": 1000, "completion_tokens": 10})
        self.assertEqual((u.input_cache_hit, u.input_cache_miss), (0, 1000))


class TestBudgetGuard(unittest.TestCase):

    def test_tavan_asilinca_durdurur(self):
        g = BudgetGuard(0.001)
        g.charge(Usage(input_cache_miss=10), 0.0005)
        with self.assertRaises(BudgetExceeded):
            g.charge(Usage(input_cache_miss=10), 0.0006)
        # Tavan asildiktan sonra YENI CAGRI YAPILAMAZ.
        with self.assertRaises(BudgetExceeded):
            g.check()

    def test_saglayici_butce_tavaninda_durur(self):
        """USD tavani asilirsa kosu DURUR (gorev sarti).

        MockProvider'in tarifesi 0 USD oldugundan tavan mock ile tetiklenmez;
        bu yuzden test gercek tarifeli bir model kimligi kullanan sahte
        saglayiciyla yapilir (ag'a cikilmaz).
        """
        c = cfg()
        c.model_ids["flash"] = "deepseek-flash"

        class Fake(BaseProvider):
            name = "fake"

            def _call(self, prompt, system, temperature, model, **kw):
                # 1M giris token (cache-miss) -> 0,44 USD
                return ChatResult(text="{}", usage=Usage(input_cache_miss=1_000_000),
                                  model=model)

        p = Fake(c, budget=BudgetGuard(0.5), sleep=lambda _s: None)
        p.chat("ilk")                       # 0,44 -> tavan altinda
        with self.assertRaises(BudgetExceeded):
            p.chat("ikinci")                # 0,88 -> tavan asildi, DURUR
        with self.assertRaises(BudgetExceeded):
            p.chat("ucuncu")                # yeni cagri hic yapilmaz

    def test_butce_gercekten_ucretlenir(self):
        c = cfg()
        c.model_ids["flash"] = "deepseek-flash"

        class Fake(BaseProvider):
            name = "fake"

            def _call(self, prompt, system, temperature, model, **kw):
                return ChatResult(text="{}", usage=Usage(input_cache_miss=1_000_000,
                                                         output=0), model=model)

        p = Fake(c, budget=BudgetGuard(10.0), sleep=lambda _s: None)
        res = p.chat("x")
        self.assertAlmostEqual(res.cost, 0.44, places=6)
        self.assertAlmostEqual(p.budget.spent, 0.44, places=6)


class TestRateLimiterAndRetry(unittest.TestCase):

    def test_hiz_siniri_bekletir(self):
        now = [0.0]
        slept = []
        rl = RateLimiter(60, clock=lambda: now[0], sleep=slept.append)
        rl.acquire()   # ilk cagri beklemez
        rl.acquire()   # ikincisi 1 sn bekler
        self.assertEqual(slept, [1.0])

    def test_ustel_geri_cekilme(self):
        slept = []
        calls = []

        class Flaky(BaseProvider):
            name = "flaky"

            def _call(self, prompt, system, temperature, model, **kw):
                calls.append(1)
                if len(calls) < 3:
                    raise OSError("gecici ag hatasi")
                return ChatResult(text="ok", usage=Usage(), model=model)

        p = Flaky(cfg(max_retry=4, retry_base_s=0.5), budget=BudgetGuard(1.0),
                  sleep=slept.append)
        res = p.chat("x")
        self.assertEqual(res.text, "ok")
        # Hiz siniri de ayni `sleep`'i kullaniyor; yalnizca geri cekilme
        # beklemelerine bakilir (>= 0,1 sn).
        self.assertEqual([s for s in slept if s >= 0.1], [0.5, 1.0])

    def test_kalici_hata_provider_error(self):
        class Dead(BaseProvider):
            name = "dead"

            def _call(self, *a, **kw):
                raise OSError("kapali")

        p = Dead(cfg(max_retry=2), budget=BudgetGuard(1.0), sleep=lambda _s: None)
        with self.assertRaises(ProviderError):
            p.chat("x")


class TestCache(unittest.TestCase):

    def test_yazma_okuma_ve_atomikligi(self):
        with tempfile.TemporaryDirectory() as td:
            c = ResponseCache(Path(td))
            c.put("abcdef", {"text": "merhaba", "usage": {}})
            self.assertEqual(c.get("abcdef")["text"], "merhaba")
            # Diskten taze okuma (bellek onbellegi devre disi)
            c2 = ResponseCache(Path(td))
            self.assertEqual(c2.get("abcdef")["text"], "merhaba")
            self.assertIsNone(c2.get("yokboyle"))
            self.assertEqual(c2.stats()["hits"], 1)
            self.assertEqual(c2.stats()["misses"], 1)

    def test_bozuk_girdi_yok_sayilir(self):
        with tempfile.TemporaryDirectory() as td:
            c = ResponseCache(Path(td))
            c.put("ffeedd", {"text": "x", "usage": {}})
            p = Path(td) / "ff" / "ffeedd.json"
            p.write_text("{bozuk", encoding="utf-8")
            self.assertIsNone(ResponseCache(Path(td)).get("ffeedd"))

    def test_onbellek_ikinci_cagriyi_bedava_yapar(self):
        with tempfile.TemporaryDirectory() as td:
            c = SegmentConfig()
            c.cache_enabled = True
            c.rpm = 10 ** 6
            cache = ResponseCache(Path(td))
            p = MockProvider(c, cache=cache, budget=BudgetGuard(10.0))
            prompt = ("Ders: Matematik\nKonu: x\nSoru kokü: 2+2 kactir?\n"
                      "Siklar (0-tabanli indeksli):\n  [0] 4\n  [1] 5\n\n")
            r1 = p.chat(prompt)
            r2 = p.chat(prompt)
            self.assertFalse(r1.cached)
            self.assertTrue(r2.cached)
            self.assertEqual(r1.text, r2.text)
            self.assertEqual(r2.cost, 0.0)
            self.assertEqual(p.budget.calls, 1)   # ikinci cagri ucretlenmedi

    def test_farkli_istem_surumu_farkli_anahtar(self):
        """Bulgu 5: istem surumu onbellek anahtarinin ayrilmaz parcasidir."""
        with tempfile.TemporaryDirectory() as td:
            c = SegmentConfig()
            c.cache_enabled = True
            c.rpm = 10 ** 6
            p = MockProvider(c, cache=ResponseCache(Path(td)), budget=BudgetGuard(10.0))
            p.chat("istem A")
            r = p.chat("istem B")
            self.assertFalse(r.cached)
            self.assertEqual(p.budget.calls, 2)

    def test_null_cache(self):
        c = NullCache()
        c.put("x", {"a": 1})
        self.assertIsNone(c.get("x"))


class TestMockProvider(unittest.TestCase):

    def _prompt(self, item=ITEM):
        from src.segment import prompts
        return prompts.get("v1").render(item, course_name=item.get("course_name"))

    def test_istemden_madde_geri_cikarilir(self):
        stem, choices = parse_item_from_prompt(self._prompt())
        self.assertIn("Kalitim", stem)
        self.assertEqual(choices, ITEM["choices"])

    def test_belirlenimci(self):
        p = MockProvider(cfg(), budget=BudgetGuard(10.0))
        a = p.chat(self._prompt(), temperature=0.3).text
        q = MockProvider(cfg(), budget=BudgetGuard(10.0))
        b = q.chat(self._prompt(), temperature=0.3).text
        self.assertEqual(a, b)

    def test_sema_uyumlu_cikti_uretir(self):
        p = MockProvider(cfg(), budget=BudgetGuard(10.0))
        seg = parse_label_json(p.chat(self._prompt()).text, question_id="q1",
                               choices=ITEM["choices"], prompt_version="v1",
                               model="mock", variant="baseline")
        self.assertIn(seg.label("dikkat_tuzagi"), ("var", "yok"))

    def test_sicaklik_sifir_tam_belirlenimci(self):
        """temperature=0 -> farkli nonce'larda bile ETIKETLER ayni.

        (Guven degerleri tohumla degisir; kararlilik ETIKET duzeyinde tanimlidir,
        intra-PSS de etiketler uzerinden hesaplanir.)
        """
        p = MockProvider(cfg(), budget=BudgetGuard(10.0))
        outs = set()
        for i in range(5):
            data = json.loads(p.chat(self._prompt(), temperature=0.0,
                                     cache_key_extra=str(i), nonce=str(i)).text)
            outs.add(tuple(sorted((k, v["etiket"])
                                  for k, v in data["boyutlar"].items())))
        self.assertEqual(len(outs), 1)

    def test_ikiz_sik_tuzak_olarak_isaretlenir(self):
        """Sozel ikiz cift -> dikkat_tuzagi = var (kaba ama gercek sezgi)."""
        p = MockProvider(cfg(), budget=BudgetGuard(10.0))
        data = json.loads(p.chat(self._prompt(), temperature=0.0).text)
        self.assertEqual(data["boyutlar"]["dikkat_tuzagi"]["etiket"], "var")
        self.assertIn(data["tuzak_sik_index"], (0, 1))

    def test_yalnizca_sayisal_siklarda_tuzak_yok(self):
        item = dict(ITEM, choices=["24", "18", "36", "12"],
                    text="12 + 12 kactir?")
        p = MockProvider(cfg(), budget=BudgetGuard(10.0))
        data = json.loads(p.chat(self._prompt(item), temperature=0.0).text)
        self.assertEqual(data["boyutlar"]["dikkat_tuzagi"]["etiket"], "yok")
        self.assertIsNone(data["tuzak_sik_index"])


class TestDeepSeekProvider(unittest.TestCase):

    def test_anahtarsiz_cagri_hata_verir_ag_a_cikilmaz(self):
        c = cfg(api_key=None, max_retry=1)
        p = DeepSeekProvider(c, budget=BudgetGuard(10.0), sleep=lambda _s: None)
        with self.assertRaises(ProviderError) as ctx:
            p.chat("x")
        self.assertIn("LLM_API_KEY", str(ctx.exception))

    def test_anahtar_yoksa_build_provider_mocka_duser(self):
        p = build_provider(cfg(api_key=None), mock=False)
        self.assertEqual(p.name, "mock")

    def test_anahtar_varsa_deepseek_secilir(self):
        p = build_provider(cfg(api_key="sahte-anahtar"), mock=False)
        self.assertEqual(p.name, "deepseek")


def _yanit(payload):
    """2xx govdeli `urlopen` taklidi."""
    class _R:
        def read(self_inner):
            return json.dumps(payload).encode()

        def __enter__(self_inner):
            return self_inner

        def __exit__(self_inner, *a):
            return False

    return _R()


class TestGatewayBodyError(unittest.TestCase):
    """GECIT 2xx GOVDESINDE HATA DONDUREBILIR (Kilo/OpenRouter tipi gecitler yuk
    altinda HTTP 200 + `{"error":{"code":503,...}}` dondurur).

    Durum koduna bakan istemci bunu basari sayar; `choices` bos gelince sema
    dogrulamasi ANLASILMAZ bir hatayla duser ve yeniden deneme HIC olmaz --
    gecici bir yuk, kosuyu aciklanamayan bir hatayla bitirir.
    """

    _SECENEK = {"choices": [{"message": {"content": "{\"etiket\": \"dogru\"}"}}],
                "usage": {}}

    def _provider(self, yanitlar, **over):
        cagri = {"n": 0}

        def _say(req, timeout=None):
            cagri["n"] += 1
            yanit = yanitlar[cagri["n"] - 1]
            if isinstance(yanit, BaseException):
                raise yanit
            return yanit

        c = cfg(api_key="sahte-anahtar", **over)
        p = DeepSeekProvider(c, budget=BudgetGuard(10.0), sleep=lambda _s: None)
        return p, cagri, mock.patch("src.segment.provider.urllib.request.urlopen",
                                    side_effect=_say)

    def test_govdede_gecici_hata_yeniden_denenir(self):
        """503 = yuk; ilk yanit 200 ama govdede hata -> ikinci deneme basarili."""
        yanitlar = [_yanit({"error": {"message": "Upstream error from Nvidia: "
                                                 "Service temporarily overloaded",
                                      "code": 503}}),
                    _yanit(self._SECENEK)]
        p, cagri, yama = self._provider(yanitlar)
        with yama:
            res = p.chat("x")
        self.assertEqual(cagri["n"], 2)
        self.assertIn("dogru", res.text)

    def test_govdede_kalici_hata_ilk_denemede_saglayicinin_mesajiyla_biter(self):
        """400 = istek yanlis; tekrar denemek yalniz kota yakar."""
        yanitlar = [_yanit({"error": {"message": "model bulunamadi", "code": 400}})]
        p, cagri, yama = self._provider(yanitlar, max_retry=4)
        # `ProviderRejection` duzeltmeyle geldi; duzeltme ONCESI dosyada yoktur,
        # yani fail-pre-fix kaniti DAVRANISSAL olsun (ImportError degil).
        beklenen = getattr(provider_mod, "ProviderRejection", ProviderError)
        with yama:
            with self.assertRaises(beklenen) as ctx:
                p.chat("x")
        self.assertEqual(cagri["n"], 1)
        self.assertIn("model bulunamadi", str(ctx.exception))

    def test_govdede_dizge_bicimi_hata_gecici_sayilir(self):
        yanitlar = [_yanit({"error": "temporary upstream failure"}),
                    _yanit(self._SECENEK)]
        p, cagri, yama = self._provider(yanitlar)
        with yama:
            p.chat("x")
        self.assertEqual(cagri["n"], 2)

    def test_gercek_http_5xx_hala_yeniden_denenir(self):
        """Govde denetimi eklenirken tasima yolu BOZULMAMALI."""
        import urllib.error
        yanitlar = [urllib.error.HTTPError("u", 503, "m", {}, None),
                    _yanit(self._SECENEK)]
        p, cagri, yama = self._provider(yanitlar)
        with yama:
            p.chat("x")
        self.assertEqual(cagri["n"], 2)


class TestConfig(unittest.TestCase):

    def test_gecersiz_butce_reddedilir(self):
        with self.assertRaises(SegmentConfigError):
            cfg(budget_usd=0).validate()

    def test_tek_tekrar_reddedilir(self):
        with self.assertRaises(SegmentConfigError):
            cfg(intra_replicates=1).validate()

    def test_model_rolleri(self):
        c = SegmentConfig()
        self.assertEqual(set(c.model_ids), {"pro", "flash", "reasoner"})
        # `reasoner` ARTIK AYRI BIR MODEL DEGIL: uctaki katalogda yalnizca
        # `deepseek-flash` ve `deepseek-v4-pro` var. Rol, ayni pro modelinin
        # akil yurutme KIPIDIR.
        self.assertEqual(c.model_id("reasoner"), "deepseek-v4-pro")
        self.assertEqual(c.model_id("flash"), "deepseek-flash")
        self.assertEqual(c.thinking_for("reasoner"), "enabled")
        self.assertEqual(c.thinking_for("pro"), "disabled")

    def test_ozet_anahtari_sizdirmaz(self):
        c = cfg(api_key="cok-gizli-anahtar")
        self.assertNotIn("cok-gizli", c.summary())
        self.assertIn("tanimli", c.summary())


if __name__ == "__main__":
    unittest.main()
