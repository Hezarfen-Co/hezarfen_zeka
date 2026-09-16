"""Es zamanlilik, hiz siniri ve butce tavaninin BIRLIKTE dogru calistigi.

BU DOSYANIN VARLIK SEBEBI (olculmus hata):
    `SEGMENT_CONCURRENCY` ayari veriliyor ama UYGULANMIYORDU. Saglayicida
    `threading.Semaphore(cfg.concurrency)` vardi, fakat `BaseLabeler.run()` duz
    bir `for` dongusuydu; tek is parcasi semafora asla takilmaz. Olcum (yapay
    0,30 sn gecikmeli mock, 12 madde):

        baseline             concurrency=1 -> 3,61 sn | tepe es zamanli cagri 1
        baseline             concurrency=6 -> 3,61 sn | tepe es zamanli cagri 1
        self_consistency     concurrency=1 -> 14,44 sn | tepe 1
        self_consistency     concurrency=6 -> 14,44 sn | tepe 1

    Yani ayarin sureye ETKISI SIFIRDI. Duzeltmeden sonra ayni olcum:

        baseline             concurrency=6 -> 0,61 sn  (6,0x) | tepe 6
        self_consistency     concurrency=6 -> 2,41 sn  (6,0x) | tepe 6
        heterogeneous_roles  concurrency=6 -> 2,41 sn  (6,0x) | tepe 6

Buradaki testler o olcumun REGRESYON KILIDIDIR. Gecikmeler kasitli olarak
kucuktur (0,04-0,06 sn) ki tum takim hizli kossun; esikler makine gurultusune
dayanikli olacak kadar genis, fakat "seri kosu" ile "es zamanli kosu" arasini
ayiramayacak kadar genis DEGIL.

AG'A CIKILMAZ: tum cagrilar yapay gecikmeli sahte saglayicidan gelir.
"""

from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from src.segment.cache import NullCache, ResponseCache
from src.segment.config import SegmentConfig
from src.segment.labelers import build_labeler
from src.segment.provider import (
    BaseProvider,
    BudgetExceeded,
    BudgetGuard,
    ChatResult,
    RateLimiter,
    Usage,
    parallel_map,
)
from src.segment.rubric import DIMENSION_ORDER, DIMENSIONS

# --------------------------------------------------------------------------
# Yardimcilar
# --------------------------------------------------------------------------

#: Semaya uyan, SABIT etiket JSON'u. Icerik onemsiz; olculen sey zamanlama.
LABEL_JSON = json.dumps({
    "boyutlar": {d: {"etiket": DIMENSIONS[d].labels[0], "guven": 0.9}
                 for d in DIMENSION_ORDER},
    "tuzak_sik_index": 0,
    "gerekce": "Sabit test yaniti.",
}, ensure_ascii=False)


def cfg(**over) -> SegmentConfig:
    c = SegmentConfig()
    c.cache_enabled = False
    c.rpm = 10 ** 6          # hiz siniri testleri disinda YOLDAN CEKILIR
    c.concurrency = 4
    c.budget_usd = 1000.0
    for k, v in over.items():
        setattr(c, k, v)
    return c


def items(n: int) -> list[dict]:
    return [{"question_id": f"q{i:03d}",
             "text": f"Soru {i}: asagidakilerden hangisi dogrudur?",
             "choices": [f"A{i}", f"B{i}", f"C{i}", f"D{i}"],
             "course_name": "Biyoloji"} for i in range(n)]


class ProbeProvider(BaseProvider):
    """Yapay gecikmeli, sayacli sahte saglayici.

    Olctugu seyler:
      * `peak`      — AYNI ANDA ucusta olan cagri sayisinin tepe degeri,
      * `calls`     — toplam cagri sayisi,
      * `starts`    — her cagrinin baslama ani (hiz siniri denetimi icin).
    """

    name = "probe"

    def __init__(self, cfg_, *, delay: float = 0.0, cost_model: str = "mock", **kw):
        super().__init__(cfg_, **kw)
        self.delay = delay
        self._cost_model = cost_model
        self.inflight = 0
        self.peak = 0
        self.calls = 0
        self.starts: list[float] = []
        self._probe_lock = threading.Lock()

    def model_for(self, role: str | None = None) -> str:
        # "mock" 0 USD'dir; butce testleri icin ucretli bir model secilir.
        return self._cost_model

    def _call(self, prompt, system, temperature, model, **kw) -> ChatResult:
        with self._probe_lock:
            self.inflight += 1
            self.calls += 1
            self.peak = max(self.peak, self.inflight)
            self.starts.append(time.monotonic())
        try:
            if self.delay:
                time.sleep(self.delay)
            # Sabit `usage` -> cagri basina maliyet SABIT ve ONGORULEBILIR.
            return ChatResult(text=LABEL_JSON,
                              usage=Usage(input_cache_miss=1000, output=1000),
                              model=model)
        finally:
            with self._probe_lock:
                self.inflight -= 1


#: `deepseek-flash` tarifesiyle 1000 miss + 1000 cikti token'inin USD maliyeti.
UNIT_COST = (1000 * 0.44 + 1000 * 1.32) / 1_000_000


# --------------------------------------------------------------------------
# 1) Es zamanlilik ayari GERCEKTEN uygulaniyor mu
# --------------------------------------------------------------------------

class TestEsZamanlilikUygulaniyor(unittest.TestCase):

    def test_N_cagri_K_es_zamanlilikla_yaklasik_N_bolu_K_surer(self):
        """N gecikmeli cagri, es zamanlilik K -> sure ~ (N/K) x gecikme."""
        n, k, delay = 12, 6, 0.06
        p = ProbeProvider(cfg(concurrency=k), delay=delay, cache=NullCache(),
                          budget=BudgetGuard(1000.0))
        t0 = time.monotonic()
        out = parallel_map(lambda i: p.chat(f"istem {i}"), list(range(n)), k)
        dt = time.monotonic() - t0

        self.assertEqual(len(out), n)
        ideal = (n / k) * delay          # 2 dalga x 0,06 = 0,12 sn
        serial = n * delay               # 0,72 sn
        # Ust sinir: ideal'in 2,5 kati bile seri kosunun COK altinda kalir.
        self.assertLess(dt, ideal * 2.5,
                        f"es zamanlilik uygulanmiyor gibi: {dt:.2f} sn")
        self.assertLess(dt, serial / 2.0)
        # Alt sinir: isin gercekten yapildigini dogrular (bedava hizlanma yok).
        self.assertGreaterEqual(dt, ideal * 0.8)

    def test_labeler_run_es_zamanli_kosuyor(self):
        """Regresyon kilidi: `BaseLabeler.run()` duz `for` dongusune DONMESIN."""
        n, k, delay = 12, 6, 0.05
        c = cfg(concurrency=k)
        p = ProbeProvider(c, delay=delay, cache=NullCache(), budget=BudgetGuard(1000.0))
        lab = build_labeler("baseline", p, c)

        t0 = time.monotonic()
        batch = lab.run(items(n))
        dt = time.monotonic() - t0

        self.assertEqual(batch.n, n)
        self.assertEqual(p.calls, n)
        self.assertEqual(p.peak, k, "tepe es zamanli cagri K'ya ULASMALI")
        self.assertLess(dt, (n * delay) / 2.0,
                        f"seri kosuya cok yakin: {dt:.2f} sn")

    def test_concurrency_1_seri_kalir(self):
        """Ayar 1 ise davranis SERI olmali (ayar iki yonde de baglayici)."""
        n, delay = 6, 0.04
        c = cfg(concurrency=1)
        p = ProbeProvider(c, delay=delay, cache=NullCache(), budget=BudgetGuard(1000.0))
        t0 = time.monotonic()
        build_labeler("baseline", p, c).run(items(n))
        dt = time.monotonic() - t0
        self.assertEqual(p.peak, 1)
        self.assertGreaterEqual(dt, n * delay * 0.8)

    def test_cok_ajanli_varyantlar_da_hizlanir(self):
        """self_consistency: madde basina k cagri, yine madde duzeyinde paralel."""
        n, k, delay = 8, 4, 0.04
        c = cfg(concurrency=k, equal_budget_calls=3)
        p = ProbeProvider(c, delay=delay, cache=NullCache(), budget=BudgetGuard(1000.0))
        t0 = time.monotonic()
        batch = build_labeler("self_consistency", p, c).run(items(n))
        dt = time.monotonic() - t0
        self.assertEqual(batch.n, n)
        self.assertEqual(p.calls, n * 3)
        self.assertLess(dt, (p.calls * delay) / 2.0)


# --------------------------------------------------------------------------
# 2) Es zamanlilik tavani ASILMIYOR mu (sayacla)
# --------------------------------------------------------------------------

class TestEsZamanlilikTavani(unittest.TestCase):

    def test_ayni_anda_calisan_cagri_sayisi_K_yi_asmaz(self):
        for k in (1, 2, 5):
            with self.subTest(concurrency=k):
                p = ProbeProvider(cfg(concurrency=k), delay=0.02,
                                  cache=NullCache(), budget=BudgetGuard(1000.0))
                parallel_map(lambda i: p.chat(f"istem {i}"), list(range(20)), k)
                self.assertLessEqual(p.peak, k,
                                     f"tepe {p.peak} > tavan {k}")
                self.assertEqual(p.peak, k)

    def test_semafor_havuzdan_daha_fazla_is_parcasi_gelse_de_tutar(self):
        """Saglayici semaforu BAGIMSIZ bir guvenlik kemeridir.

        Havuz K isci ile kurulsa bile, disaridan daha fazla is parcasi
        `chat()` cagirirsa tavan yine `cfg.concurrency` olmalidir.
        """
        k = 3
        p = ProbeProvider(cfg(concurrency=k), delay=0.03, cache=NullCache(),
                          budget=BudgetGuard(1000.0))
        threads = [threading.Thread(target=p.chat, args=(f"istem {i}",))
                   for i in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(p.calls, 12)
        self.assertLessEqual(p.peak, k)


# --------------------------------------------------------------------------
# 3) Hiz siniri (SEGMENT_RPM) es zamanli kosuda da tutuyor mu
# --------------------------------------------------------------------------

class TestHizSiniri(unittest.TestCase):

    def test_rate_limiter_es_zamanli_cagrilarda_slot_paylastirmaz(self):
        """Belirlenimci: 24 is parcasi, DONMUS saat -> her biri AYRI slot alir.

        Iki is parcasi ayni slotu alirsa dakikalik tavan asilir. Saat donuk
        oldugu icin beklenen bekleme suresi kumesi TAM olarak
        {0, i, 2i, ...} olmalidir.
        """
        rpm = 60
        interval = 60.0 / rpm
        waits: list[float] = []
        wlock = threading.Lock()
        lim = RateLimiter(rpm, clock=lambda: 1000.0,
                          sleep=lambda s: waits.append(s))

        def worker():
            lim.acquire()

        ts = [threading.Thread(target=worker) for _ in range(24)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()

        with wlock:
            got = sorted(round(w, 6) for w in waits)
        # Ilk cagri beklemez (`sleep` cagrilmaz) -> 23 bekleme kaydi.
        self.assertEqual(len(got), 23)
        expected = [round(interval * i, 6) for i in range(1, 24)]
        self.assertEqual(got, expected, "slotlar cakisti -> RPM asilir")

    def test_rpm_tavani_es_zamanli_kosuda_asilmaz(self):
        """Gercek saatle: 12 cagri, K=6, rpm=1200 -> gozlenen hiz <= tavan."""
        n, k, rpm = 12, 6, 1200          # 1200 rpm -> 0,05 sn araliK
        interval = 60.0 / rpm
        c = cfg(concurrency=k, rpm=rpm)
        p = ProbeProvider(c, delay=0.0, cache=NullCache(), budget=BudgetGuard(1000.0))

        t0 = time.monotonic()
        parallel_map(lambda i: p.chat(f"istem {i}"), list(range(n)), k)
        dt = time.monotonic() - t0

        self.assertEqual(p.calls, n)
        # Es zamanlilik hiz sinirini EZMEMELI: n cagri en az (n-1)*aralik surer.
        self.assertGreaterEqual(dt, (n - 1) * interval * 0.85,
                                f"hiz siniri es zamanli kosuda delinmis: {dt:.3f} sn")
        # Gozlenen dakikalik hiz tavani asmasin (%15 olcum payi).
        observed_rpm = n / dt * 60.0
        self.assertLessEqual(observed_rpm, rpm * 1.15)

    def test_hiz_siniri_ve_es_zamanlilik_birlikte_calisir(self):
        """RPM bol olunca es zamanlilik baglayici olmali (ikisi cakismasin)."""
        n, k = 12, 6
        c = cfg(concurrency=k, rpm=10 ** 6)
        p = ProbeProvider(c, delay=0.05, cache=NullCache(), budget=BudgetGuard(1000.0))
        t0 = time.monotonic()
        parallel_map(lambda i: p.chat(f"istem {i}"), list(range(n)), k)
        dt = time.monotonic() - t0
        self.assertEqual(p.peak, k)
        self.assertLess(dt, n * 0.05 / 2.0)


# --------------------------------------------------------------------------
# 4) Butce tavani — es zamanli kosuda yarissiz ve asilmaz
# --------------------------------------------------------------------------

class TestButceEsZamanli(unittest.TestCase):

    def test_es_zamanli_ucretlendirmede_hicbir_harcama_kaybolmaz(self):
        """Yarissiz muhasebe: 200 es zamanli `charge` -> toplam TAM."""
        g = BudgetGuard(10 ** 9)
        usage = Usage(input_cache_miss=1000, output=1000)

        def worker():
            for _ in range(50):
                g.charge(usage, 0.001)

        ts = [threading.Thread(target=worker) for _ in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()

        self.assertEqual(g.calls, 400)
        self.assertAlmostEqual(g.spent, 0.4, places=9)
        self.assertEqual(g.tokens_in, 400 * 1000)
        self.assertEqual(g.tokens_out, 400 * 1000)
        self.assertFalse(g.stopped)

    def test_tavan_asilinca_tam_bir_kez_bayrak_kurulur_ve_hemen_durur(self):
        """Tavan asildiginda bayrak KALICI: sonraki `check()` aninda patlar."""
        g = BudgetGuard(0.0025)
        usage = Usage(input_cache_miss=1, output=1)
        g.charge(usage, 0.001)
        g.charge(usage, 0.001)
        self.assertFalse(g.stopped)
        with self.assertRaises(BudgetExceeded):
            g.charge(usage, 0.001)
        self.assertTrue(g.stopped)
        # Hizli durdurma: kapi artik HER ZAMAN kapali.
        for _ in range(3):
            with self.assertRaises(BudgetExceeded):
                g.check()
        self.assertTrue(g.snapshot()["stopped"])

    def test_es_zamanli_kosuda_tavan_asilmaz_ve_kosu_durur(self):
        """Tavan: 10 cagrilik butce, 60 madde, K=8 -> kosu DURUR, asim sinirli.

        Es zamanli kosuda ucusta olan `K` cagri tavani birkac cagri asabilir
        (istek zaten gonderilmistir); kabul edilen asim TAM OLARAK bir
        es zamanlilik penceresidir, daha fazlasi degil.
        """
        cap_calls = 10
        k = 8
        c = cfg(concurrency=k, budget_usd=UNIT_COST * cap_calls)
        p = ProbeProvider(c, delay=0.01, cost_model="deepseek-flash",
                          cache=NullCache(), budget=BudgetGuard(c.budget_usd))
        batch = build_labeler("baseline", p, c).run(items(60))

        self.assertTrue(batch.budget_stopped, "butce tavani kosuyu DURDURMALI")
        self.assertLess(batch.n, 60)
        # Muhasebe tutarli: harcanan = yapilan cagri sayisi x birim maliyet.
        self.assertEqual(p.budget.calls, p.calls)
        self.assertAlmostEqual(p.budget.spent, p.calls * UNIT_COST, places=9)
        # Asim en fazla bir es zamanlilik penceresi kadar.
        self.assertLessEqual(p.calls, cap_calls + k,
                             f"tavan cok asildi: {p.calls} cagri")
        self.assertTrue(p.budget.stopped)

    def test_butce_durdurunca_kalan_maddeler_baslatilmaz(self):
        """Hizli durdurma: tavan asildiktan sonra YENI cagri yapilmaz."""
        cap_calls = 4
        c = cfg(concurrency=2, budget_usd=UNIT_COST * cap_calls)
        p = ProbeProvider(c, delay=0.0, cost_model="deepseek-flash",
                          cache=NullCache(), budget=BudgetGuard(c.budget_usd))
        build_labeler("baseline", p, c).run(items(200))
        # 200 madde vardi; tavan 4 cagrida doldu -> 200'e yakin cagri OLMAMALI.
        self.assertLess(p.calls, 20)
        self.assertGreaterEqual(p.calls, cap_calls)


# --------------------------------------------------------------------------
# 5) Onbellek es zamanli yazimda bozulmuyor mu
# --------------------------------------------------------------------------

class TestOnbellekEsZamanli(unittest.TestCase):

    def test_es_zamanli_yazimda_onbellek_bozulmaz(self):
        n, k = 24, 8
        with tempfile.TemporaryDirectory() as td:
            cache = ResponseCache(Path(td))
            c = cfg(concurrency=k, cache_enabled=True)
            p1 = ProbeProvider(c, delay=0.0, cache=cache,
                               budget=BudgetGuard(1000.0))
            b1 = build_labeler("baseline", p1, c).run(items(n))
            self.assertEqual(b1.n, n)
            self.assertEqual(p1.calls, n)

            # Her onbellek dosyasi TAM ve okunabilir JSON olmali (yarim dosya yok).
            files = sorted(Path(td).rglob("*.json"))
            self.assertEqual(len(files), n)
            for f in files:
                data = json.loads(f.read_text(encoding="utf-8"))
                self.assertEqual(data["text"], LABEL_JSON)
                self.assertIn("usage", data)
            # Gecici dosya artigi kalmamali.
            self.assertEqual(list(Path(td).rglob("*.tmp")), [])

            # Ikinci kosu TAMAMEN onbellekten: HIC yeni cagri yok.
            p2 = ProbeProvider(c, delay=0.0, cache=cache,
                               budget=BudgetGuard(1000.0))
            b2 = build_labeler("baseline", p2, c).run(items(n))
            self.assertEqual(p2.calls, 0, "es zamanli yazilan onbellek okunamadi")
            self.assertEqual(b2.n, n)
            self.assertEqual(sorted(b1.results), sorted(b2.results))

    def test_ayni_anahtara_es_zamanli_yazim_sayaclari_bozmaz(self):
        """Ayni anahtara N is parcasi yazsa da bellek ici sayac tutarli kalir."""
        with tempfile.TemporaryDirectory() as td:
            cache = ResponseCache(Path(td))

            def worker(i: int):
                for j in range(20):
                    cache.put(f"{i:02d}{j:02d}" + "a" * 60, {"text": f"{i}-{j}"})

            ts = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            st = cache.stats()
            self.assertEqual(st["writes"], 160)
            self.assertEqual(st["mem"], 160)
            self.assertEqual(len(list(Path(td).rglob("*.json"))), 160)


# --------------------------------------------------------------------------
# 6) Belirlenimcilik — es zamanlilik sonucu DEGISTIRMEMELI
# --------------------------------------------------------------------------

class TestBelirlenimcilik(unittest.TestCase):

    def test_sonuclar_es_zamanlilik_seviyesinden_bagimsiz(self):
        c1, c6 = cfg(concurrency=1), cfg(concurrency=6)
        p1 = ProbeProvider(c1, cache=NullCache(), budget=BudgetGuard(1000.0))
        p6 = ProbeProvider(c6, cache=NullCache(), budget=BudgetGuard(1000.0))
        b1 = build_labeler("baseline", p1, c1).run(items(20))
        b6 = build_labeler("baseline", p6, c6).run(items(20))
        self.assertEqual(list(b1.results), list(b6.results), "madde SIRASI degisti")
        self.assertEqual(b1.usage.to_dict(), b6.usage.to_dict())
        self.assertEqual([s.label_tuple() for s in b1.results.values()],
                         [s.label_tuple() for s in b6.results.values()])

    def test_hatalar_es_zamanli_kosuda_dogru_maddeye_yazilir(self):
        """Bozuk yanit veren maddeler KARISMADAN `failures`a dusmeli."""

        import re as _re

        class Patchy(ProbeProvider):
            def _call(self, prompt, system, temperature, model, **kw):
                res = super()._call(prompt, system, temperature, model, **kw)
                # Tek indeksli maddeler bozuk yanit alir (istemden okunur).
                m = _re.search(r"Soru (\d+):", prompt)
                if m and int(m.group(1)) % 2 == 1:
                    res.text = "{bozuk"
                return res

        c = cfg(concurrency=5)
        p = Patchy(c, cache=NullCache(), budget=BudgetGuard(1000.0))
        batch = build_labeler("baseline", p, c).run(items(10))
        self.assertEqual(sorted(batch.failures),
                         ["q001", "q003", "q005", "q007", "q009"])
        self.assertEqual(sorted(batch.results),
                         ["q000", "q002", "q004", "q006", "q008"])

    def test_generator_critic_sayaclari_es_zamanli_kosuda_yarissiz(self):
        """`critic_total` madde sayisina TAM esit olmali (kayip artirim yok)."""
        c = cfg(concurrency=8)
        p = ProbeProvider(c, cache=NullCache(), budget=BudgetGuard(1000.0))
        batch = build_labeler("generator_critic", p, c).run(items(40))
        self.assertEqual(batch.n, 40)
        self.assertEqual(batch.critic_total, 40)
        self.assertEqual(p.calls, 80)


# --------------------------------------------------------------------------
# 7) `parallel_map` sozlesmesi
# --------------------------------------------------------------------------

class TestParallelMap(unittest.TestCase):

    def test_sonuclar_giris_sirasinda_doner(self):
        import random as _r
        out = parallel_map(lambda x: (time.sleep(_r.random() * 0.01), x * 2)[1],
                           list(range(30)), 8)
        self.assertEqual([i for i, _ in out], list(range(30)))
        self.assertEqual([v for _, v in out], [i * 2 for i in range(30)])

    def test_bos_giris(self):
        self.assertEqual(parallel_map(lambda x: x, [], 4), [])

    def test_isci_sayisi_madde_sayisini_asamaz(self):
        p = ProbeProvider(cfg(concurrency=50), delay=0.02, cache=NullCache(),
                          budget=BudgetGuard(1000.0))
        parallel_map(lambda i: p.chat(f"istem {i}"), list(range(3)), 50)
        self.assertLessEqual(p.peak, 3)

    def test_on_error_yoksa_hata_yukselir(self):
        def boom(x):
            if x == 5:
                raise ValueError("patlak")
            return x

        with self.assertRaises(ValueError):
            parallel_map(boom, list(range(10)), 4)

    def test_on_error_true_donerse_kalan_isler_iptal_edilir(self):
        seen: list[int] = []
        lock = threading.Lock()

        def work(x):
            with lock:
                seen.append(x)
            time.sleep(0.01)
            if x == 2:
                raise ValueError("dur")
            return x

        out = parallel_map(work, list(range(100)), 2,
                           on_error=lambda i, it, e: True)
        self.assertEqual([i for i, _ in out], [0, 1])
        self.assertLess(len(seen), 100, "kalan isler iptal edilmedi")


if __name__ == "__main__":
    unittest.main()
