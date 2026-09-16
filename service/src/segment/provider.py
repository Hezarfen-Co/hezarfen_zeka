"""LLM saglayici katmani: DeepSeek (OpenAI-uyumlu) + belirlenimci MockProvider.

Desen `hezarfen_rag-main/src/providers/deepseek.py` ve `src/pricing.py`
dosyalarindan OKUNDU; kod kopyalanmadi, burada yeniden yazildi. Farklar:
  * maliyet tavani (`BudgetGuard`) ve kosuyu DURDURAN `BudgetExceeded`,
  * hiz siniri (token kovasi) + es zamanlilik siniri,
  * ustel geri cekilmeli yeniden deneme,
  * onbellek entegrasyonu (`cache.py`),
  * anahtarsiz uctan uca kosuyu saglayan `MockProvider`.

ONEMLI: `MockProvider` gercek bir dil modeli DEGILDIR. Ciktilari kaba metin
sezgilerinden ve tohumlu gurultuden gelir. Mock ile olculen F1/alpha degerleri
BORU HATTININ CALISTIGINI gosterir; DeepSeek'in etiketleme kalitesi hakkinda
HICBIR SEY SOYLEMEZ. Rapor bunu boyle yazmak zorundadir.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence, TypeVar

from .config import SegmentConfig, log

# --------------------------------------------------------------------------
# Fiyatlandirma — USD / 1M token.
#
# MODEL ADLARI UCTAN DOGRULANDI (2026-09-14, GET /models): katalogda TAM OLARAK
# iki model var -> `deepseek-flash` ve `deepseek-v4-pro`. Onceki surumde tablo
# `deepseek-v4-flash` anahtarini kullaniyordu; bu ad ARTIK YOK, dolayisiyla her
# cagri "bilinmeyen model" dalina dusup EN PAHALI tarifeyle ucretleniyordu ve
# butce tavani yanlis calisiyordu. Duzeltildi.
#
# FIYATLAR DOGRULANMADI: rakamlar `hezarfen_rag-main/src/pricing.py` icindeki
# 2026-08-28 tarihli kopyadan geliyor; bu turda YALNIZCA MODEL ADLARI uctan
# dogrulandi, tarifeler dogrulanmadi. Gercek koşu oncesi resmi fiyat sayfasindan
# teyit edilmeli (kosu raporunda `caveats` icinde de yaziyor).
# --------------------------------------------------------------------------
PRICING_UPDATED = "2026-08-28"
PRICING_VERIFIED = False
PRICING_SOURCE = "https://api-docs.deepseek.com/quick_start/pricing"
PRICING: dict[str, dict[str, float]] = {
    "deepseek-flash": {"in_hit": 0.014, "in_miss": 0.44, "out": 1.32},
    "deepseek-v4-pro": {"in_hit": 0.044, "in_miss": 1.32, "out": 3.96},
    "mock": {"in_hit": 0.0, "in_miss": 0.0, "out": 0.0},
}
#: Uctaki gercek model adlari (GET /models, 2026-09-14).
LIVE_MODELS = ("deepseek-flash", "deepseek-v4-pro")

#: Artik takma ad YOK: uctaki adlar dogrudan fiyat tablosunun anahtarlaridir.
#: Sozluk, tablo ile uc arasinda ileride ayrisma olursa tek bir yer kalsin diye
#: duruyor; olu adlar (`deepseek-chat`, `deepseek-reasoner`, `deepseek-v4-flash`)
#: TEMIZLENDI.
MODEL_ALIASES: dict[str, str] = {
    "deepseek-flash": "deepseek-flash",
    "deepseek-v4-pro": "deepseek-v4-pro",
    "mock": "mock",
}

assert all(m in PRICING for m in LIVE_MODELS), \
    "Uctaki her model icin fiyat satiri bulunmali."


class BudgetExceeded(RuntimeError):
    """USD tavani asildi — kosu DURUR (gorev sarti)."""


class ProviderError(RuntimeError):
    """Saglayici cagrisi kalici olarak basarisiz."""


@dataclass
class Usage:
    """Bir cagrinin token kullanimi (OpenAI-uyumlu `usage` alanindan)."""

    input_cache_hit: int = 0
    input_cache_miss: int = 0
    output: int = 0
    #: Bilgi amacli: dusunce token'lari. `output` (completion_tokens) bunu ZATEN
    #: ICERIR — maliyette IKI KEZ SAYILMAZ.
    reasoning: int = 0

    @property
    def input_total(self) -> int:
        return self.input_cache_hit + self.input_cache_miss

    @property
    def total(self) -> int:
        return self.input_total + self.output

    @classmethod
    def from_api(cls, usage: dict) -> "Usage":
        """Gercek `usage` alanlarindan olcum — TAHMIN YOK.

        UCTAN DOGRULANDI (2026-09-14): DeepSeek yanitlari `usage` icinde
        `prompt_cache_hit_tokens` ve `prompt_cache_miss_tokens` dondururuyor;
        ikisi ayri tarifelidir ve maliyet bunlardan hesaplanir.
        Alanlar gelmezse TUM prompt cache-miss sayilir (temkinli taraf).
        """
        hit = usage.get("prompt_cache_hit_tokens")
        miss = usage.get("prompt_cache_miss_tokens")
        if hit is None and miss is None:
            miss = int(usage.get("prompt_tokens", 0) or 0)
            hit = 0
        details = usage.get("completion_tokens_details") or {}
        return cls(int(hit or 0), int(miss or 0),
                   int(usage.get("completion_tokens", 0) or 0),
                   int(details.get("reasoning_tokens", 0) or 0))


def cost_usd(model: str, usage: Usage) -> float:
    """Modelin fiyat tablosundaki karsiligiyla USD maliyet."""
    key = MODEL_ALIASES.get(model, model)
    price = PRICING.get(key)
    if price is None:
        # Bilinmeyen model: SIFIR sayma — en pahali tarifeyi uygula (temkinli).
        price = max(PRICING.values(), key=lambda p: p["out"])
    return (usage.input_cache_hit * price["in_hit"]
            + usage.input_cache_miss * price["in_miss"]
            + usage.output * price["out"]) / 1_000_000


@dataclass
class ChatResult:
    #: Modelin `message.content` alani — SEMA DOGRULAMASI YALNIZ BUNA UYGULANIR.
    text: str
    usage: Usage
    model: str
    latency_s: float = 0.0
    cost: float = 0.0
    cached: bool = False
    #: `message.reasoning_content` — dusunce izi. Etiketin gerekcesi DEGILDIR
    #: ve semaya sokulmaz; ayri alan olarak tasinir ve ayri raporlanir.
    reasoning_content: str = ""
    raw: dict = field(default_factory=dict)


# --------------------------------------------------------------------------
# Butce ve hiz denetimi
# --------------------------------------------------------------------------

class BudgetGuard:
    """Kumulatif USD maliyeti izler; tavan asilirsa `BudgetExceeded` atar."""

    def __init__(self, cap_usd: float):
        self.cap_usd = float(cap_usd)
        self.spent = 0.0
        self.calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self._lock = threading.Lock()
        # ES ZAMANLILIK: tavan bir kez asildiginda bu olay KALICI olarak
        # kurulur. Ucus halindeki her is parcasi bir sonraki `check()`te
        # aninda durur; "once oku sonra yaz" yarisi kalmaz cunku hem okuma
        # hem yazma AYNI kilit altinda ve tek bir atomik blokta yapilir.
        self._stopped = threading.Event()

    @property
    def stopped(self) -> bool:
        """Tavan asildi mi (es zamanli kosuda hizli durdurma bayragi)."""
        return self._stopped.is_set()

    def _message(self, suffix: str = "") -> str:
        return (f"USD tavani asildi: harcanan {self.spent:.4f} >= "
                f"tavan {self.cap_usd:.4f}{suffix}")

    def check(self) -> None:
        """Cagri ONCESI kapi. Tavan zaten asildiysa yeni cagri YAPILMAZ."""
        # Kilitsiz hizli yol: bayrak kuruluysa kilide hic girme (es zamanli
        # kosuda onlarca is parcasi ayni kilitte sirayla beklemesin).
        if self._stopped.is_set():
            raise BudgetExceeded(self._message())
        with self._lock:
            if self.spent >= self.cap_usd:
                self._stopped.set()
                raise BudgetExceeded(self._message())

    def charge(self, usage: Usage, usd: float) -> None:
        """Cagri SONRASI kayit; tavan asildiysa hemen durdurur.

        Toplama ve tavan karsilastirmasi TEK kilit altinda yapilir: N is
        parcasi ayni anda ucretlense de hicbir harcama kaybolmaz ve tavan
        yalnizca gercek toplam uzerinden degerlendirilir.
        """
        with self._lock:
            self.spent += usd
            self.calls += 1
            self.tokens_in += usage.input_total
            self.tokens_out += usage.output
            over = self.spent >= self.cap_usd
            if over:
                self._stopped.set()
                msg = self._message(f" ({self.calls} cagri sonrasi)")
        if over:
            raise BudgetExceeded(msg)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"spent_usd": round(self.spent, 6), "cap_usd": self.cap_usd,
                    "calls": self.calls, "tokens_in": self.tokens_in,
                    "tokens_out": self.tokens_out,
                    "stopped": self._stopped.is_set()}


class RateLimiter:
    """Basit token kovasi: dakikada en fazla `rpm` istek."""

    def __init__(self, rpm: int, *, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.rpm = max(1, int(rpm))
        self._interval = 60.0 / self.rpm
        self._clock = clock
        self._sleep = sleep
        self._next = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = self._clock()
            wait = self._next - now
            if wait <= 0:
                self._next = now + self._interval
                wait = 0.0
            else:
                self._next += self._interval
        if wait > 0:
            self._sleep(wait)


T = TypeVar("T")
R = TypeVar("R")


def parallel_map(fn: Callable[[T], R], items: Sequence[T], workers: int,
                 *, on_error: Callable[[int, T, BaseException], bool] | None = None,
                 thread_prefix: str = "segment") -> list[tuple[int, R]]:
    """`items` uzerinde `fn`i en fazla `workers` is parcasiyla kosar.

    NEDEN IS PARCASI (thread), `asyncio` DEGIL:
      * Cagri yolu bastan sona SENKRON (`urllib.request.urlopen`). asyncio'ya
        gecmek ya yeni bir HTTP bagimliligi (aiohttp/httpx) ister — bagimlilik
        eklemek YASAK — ya da zaten `run_in_executor` ile is parcasi havuzuna
        dusmek demektir. Yani asyncio burada fazladan katman, ek hiz DEGIL.
      * Darbogaz ag beklemesi; `urlopen` beklerken GIL birakilir, dolayisiyla
        is parcaciklari G/C'de gercekten paralel ilerler (CPU-bagli degiliz).
      * Mevcut es zamanlilik/hiz/butce denetimleri (`threading.Semaphore`,
        `threading.Lock`) zaten is parcasi tabanli; korunuyorlar.

    Sonuclar GIRIS SIRASINDA (indeksli) dondurulur — es zamanlilik belirlenimi
    bozmaz. `on_error` verilirse hata yutulur ve `True` dondurursek kalan isler
    IPTAL edilir (butce tavaninda hizli durdurma icin).
    """
    n = len(items)
    if n == 0:
        return []
    workers = max(1, min(int(workers), n))
    if workers == 1:
        # Tek is parcasi: havuz kurma masrafi olmadan, ayni semantik.
        out: list[tuple[int, R]] = []
        for i, it in enumerate(items):
            try:
                out.append((i, fn(it)))
            except BaseException as exc:  # noqa: BLE001
                if on_error is None:
                    raise
                if on_error(i, it, exc):
                    break
        return out

    results: list[tuple[int, R]] = []
    with ThreadPoolExecutor(max_workers=workers,
                            thread_name_prefix=thread_prefix) as pool:
        futures = [pool.submit(fn, it) for it in items]
        for i, fut in enumerate(futures):
            try:
                results.append((i, fut.result()))
            except BaseException as exc:  # noqa: BLE001
                if on_error is None:
                    for rest in futures[i + 1:]:
                        rest.cancel()
                    raise
                if on_error(i, items[i], exc):
                    # Hizli durdurma: henuz baslamamis isleri IPTAL et.
                    for rest in futures[i + 1:]:
                        rest.cancel()
                    break
    return results


# --------------------------------------------------------------------------
# Ortak taban
# --------------------------------------------------------------------------

class BaseProvider:
    """Onbellek + hiz siniri + butce + yeniden deneme sarmalayicisi."""

    name = "base"

    def __init__(self, cfg: SegmentConfig, *, cache=None, budget: BudgetGuard | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.cfg = cfg
        self.cache = cache
        self.budget = budget or BudgetGuard(cfg.budget_usd)
        self.limiter = RateLimiter(cfg.rpm, sleep=sleep)
        self._sem = threading.Semaphore(cfg.concurrency)
        self._sleep = sleep

    # -- alt siniflar bunu doldurur ---------------------------------------
    def _call(self, prompt: str, system: str | None, temperature: float,
              model: str, **kw) -> ChatResult:
        raise NotImplementedError

    def model_for(self, role: str | None = None) -> str:
        return self.cfg.model_id(role)

    def chat(self, prompt: str, system: str | None = None, *,
             temperature: float | None = None, role: str | None = None,
             cache_key_extra: str = "", kind: str = "label",
             **kw) -> ChatResult:
        """Tek cagri. Onbellek -> hiz siniri -> butce -> yeniden deneme.

        Onbellek anahtari: model + sistem + istem (istem surumu ve soru zaten
        istemin ICINDE) + sicaklik + `cache_key_extra` (tekrar indeksi). Bulgu 5
        geregi istem surumu anahtarin ayrilmaz parcasidir.
        """
        temperature = self.cfg.temperature if temperature is None else temperature
        model = self.model_for(role)
        # Akil yurutme ayari ciktiyi degistirir -> onbellek anahtarinin parcasi.
        mode = f"{self.cfg.thinking_for(role) or '-'}|{self.cfg.reasoning_effort or '-'}"
        key = cache_key(model, system, prompt, temperature,
                        f"{cache_key_extra}|{mode}")

        if self.cache is not None and self.cfg.cache_enabled:
            hit = self.cache.get(key)
            if hit is not None:
                usage = Usage(**hit["usage"])
                return ChatResult(text=hit["text"], usage=usage, model=model,
                                  cost=0.0, cached=True,
                                  reasoning_content=hit.get("reasoning_content", ""))

        self.budget.check()
        last: Exception | None = None
        for attempt in range(self.cfg.max_retry):
            self.limiter.acquire()
            with self._sem:
                try:
                    res = self._call(prompt, system, temperature, model,
                                     kind=kind, role=role, **kw)
                except BudgetExceeded:
                    raise
                except Exception as exc:  # noqa: BLE001
                    last = exc
                    # Ustel geri cekilme: 0.5s, 1s, 2s, 4s ...
                    delay = self.cfg.retry_base_s * (2 ** attempt)
                    log("warn", f"cagri hatasi ({attempt + 1}/{self.cfg.max_retry}): "
                                f"{type(exc).__name__}: {exc} -> {delay:.1f}s bekle")
                    self._sleep(delay)
                    continue
            res.cost = cost_usd(model, res.usage)
            # Onbellege ucretlendirmeden ONCE yaz: tavani tetikleyen cagri da
            # zaten yapilmis ve odenmis bir istir; sonraki kosuda bedava
            # kullanilabilsin diye kaybedilmez.
            if self.cache is not None and self.cfg.cache_enabled:
                self.cache.put(key, {"text": res.text,
                                     "usage": res.usage.__dict__,
                                     "reasoning_content": res.reasoning_content,
                                     "model": model})
            self.budget.charge(res.usage, res.cost)
            return res
        raise ProviderError(f"{self.cfg.max_retry} denemede basarisiz: {last}")


def cache_key(model: str, system: str | None, prompt: str, temperature: float,
              extra: str) -> str:
    h = hashlib.sha256()
    for part in (model, system or "", prompt, f"{temperature:.3f}", extra):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


# --------------------------------------------------------------------------
# Gercek saglayici — TESTLERDE CAGRILMAZ
# --------------------------------------------------------------------------

class DeepSeekProvider(BaseProvider):
    """OpenAI-uyumlu `/chat/completions` istemcisi.

    Anahtar ortamdan (`DEEPSEEK_API_KEY`). Anahtar yokken de ORNEKLENEBILIR;
    hata yalnizca gercek cagri aninda yukselir — boylece tum boru hatti
    anahtarsiz ithal edilebilir.
    """

    name = "deepseek"

    def build_payload(self, prompt: str, system: str | None, temperature: float,
                      model: str, *, kind: str = "label",
                      role: str | None = None) -> dict[str, Any]:
        """Istek govdesini uretir (test edilebilir olsun diye ayri).

        AKIL YURUTME — UCTAN DOGRULANDI (2026-09-14):
          * `thinking` alani METIN DEGIL NESNE bekler. `"max"`, `"high"`,
            `"enabled"` gibi duz metinler `400 invalid type: string, expected
            struct ThinkingOptions` verir.
          * Calisan bicim: `thinking: {"type": "enabled"}` /
            `{"type": "disabled"}`.
          * `reasoning_effort` ayrica kabul ediliyor: minimal|low|medium|high.
          * `deepseek-v4-pro` akil yurutmeyi VARSAYILAN olarak yapar; "disabled"
            denmedikce dusunce uretir ve dusunce token'lari CIKTI olarak
            faturalanir.
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict[str, Any] = {
            "model": model, "messages": messages,
            "temperature": temperature, "stream": False,
        }
        thinking = self.cfg.thinking_for(role)
        if thinking:
            payload["thinking"] = {"type": thinking}
        if self.cfg.reasoning_effort:
            payload["reasoning_effort"] = self.cfg.reasoning_effort
        if kind == "label":
            # Yapilandirilmis cikti: sunucu tarafinda da JSON zorla. Sema
            # dogrulamasi yine de `schema.parse_label_json` ile YAPILIR.
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _call(self, prompt: str, system: str | None, temperature: float,
              model: str, *, kind: str = "label", role: str | None = None,
              **kw) -> ChatResult:
        if not self.cfg.api_key:
            raise ProviderError(
                "DEEPSEEK_API_KEY tanimsiz. Gercek kosu icin ortama anahtari yaz "
                "ya da MockProvider kullan.")
        payload = self.build_payload(prompt, system, temperature, model,
                                     kind=kind, role=role)
        req = urllib.request.Request(
            f"{self.cfg.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8",
                     "Authorization": f"Bearer {self.cfg.api_key}"},
            method="POST")
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:300]
            raise ProviderError(f"HTTP {exc.code}: {body}") from exc
        latency = time.time() - t0
        choices = data.get("choices") or [{}]
        message = choices[0].get("message", {}) or {}
        # `content` sema dogrulamasina girer; `reasoning_content` GIRMEZ.
        text = message.get("content") or ""
        reasoning = message.get("reasoning_content") or ""
        return ChatResult(text=text, usage=Usage.from_api(data.get("usage", {})),
                          model=model, latency_s=latency,
                          reasoning_content=reasoning, raw=data)


# --------------------------------------------------------------------------
# MockProvider — belirlenimci, tohum tabanli
# --------------------------------------------------------------------------

_ITEM_RE = re.compile(r"Soru kokü: (.*?)\nSiklar \(0-tabanli indeksli\):\n(.*?)(?:\n\n|\Z)",
                      re.DOTALL)
_CHOICE_RE = re.compile(r"^\s*\[(\d+)\] (.*)$", re.MULTILINE)
_WORD_RE = re.compile(r"[0-9a-zA-ZçğıöşüÇĞİÖŞÜ∘²·×]+")

# Kaba, GENEL asiri-genelleme belirtecleri. Bu liste `content_tr.py`
# MISCONCEPTIONS tablosundan TUREMEZ; dilbilimsel olarak yaygin "mutlaklastirma"
# sozcukleridir. Mock'un tek sezgisi budur ve zayiftir — kasitli olarak.
_OVERGEN = ("ayni", "aynidir", "her ", "hep", "yalniz", "tek ", "daima",
            "hicbir", "olsa da", "bile", "tumu")

_ANALIZ_CUES = ("hangisi yanlis", "soylenemez", "karsilastir", "nedeni",
                "cikarim", "yorumla", "degerlendir")
_UYGULAMA_CUES = ("hesapla", "kactir", "kac ", "bul", "coz", "uygula",
                  "yerine", "turev", "integral")


def _norm(s: str) -> str:
    """Turkce harfleri kabaca ASCII'ye indirger (sezgi eslesmesi icin)."""
    table = str.maketrans("çğıöşüÇĞİÖŞÜâîû", "cgiosuCGIOSUaiu")
    return s.translate(table).lower()


def _tokens(s: str) -> set[str]:
    return {t for t in _WORD_RE.findall(_norm(s)) if len(t) > 1}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def parse_item_from_prompt(prompt: str) -> tuple[str, list[str]]:
    """Istem metninden soru kokunu ve siklari geri cikarir.

    MockProvider gercek saglayici ILE AYNI arayuze sahip olsun diye boyle
    yapilir: ikisi de yalnizca bir metin alir.
    """
    m = _ITEM_RE.search(prompt)
    if not m:
        return "", []
    stem = m.group(1).strip()
    choices = [c.strip() for _, c in _CHOICE_RE.findall(m.group(2))]
    return stem, choices


class MockProvider(BaseProvider):
    """Anahtarsiz, belirlenimci sahte model.

    Davranis:
      * `kind="label"`  -> semaya uygun etiket JSON'u
      * `kind="merge"`  -> verilen ajan etiketlerinden cogunluk JSON'u
      * `kind="critic"` -> oneriyi kucuk bir olasilikla degistirir (bulgu 8'in
        "dogrulayici katmanin KENDISI hata kaynagidir" savini OLCULEBILIR kilar)
      * `kind="paraphrase"` -> metni kucuk bicimsel degisikliklerle dondurur

    Belirlenimcilik: tum rastgelelik `SHA256(tohum|istem|sicaklik|extra)`
    uzerinden tohumlanir; ayni girdi daima ayni cikti.
    """

    name = "mock"

    def __init__(self, cfg: SegmentConfig, **kw):
        super().__init__(cfg, **kw)
        # Mock icin fiyat tablosu "mock" (0 USD) ama token sayilari GERCEKCI
        # uretilir ki esit-butce karsilastirmasi anlamli olsun.
        self._mock_model = "mock"
        # Mock ag'a cikmaz: hiz siniri UYGULANMAZ. (Gercek saglayicida
        # `cfg.rpm` aynen gecerlidir; burada onu korumak kosuyu bosuna
        # yavaslatirdi — 540 cagri x 1 sn.)
        self.limiter = RateLimiter(10 ** 6, sleep=lambda _s: None)

    def model_for(self, role: str | None = None) -> str:
        return self._mock_model

    # -- ic sezgiler -------------------------------------------------------
    def _rng(self, *parts: str) -> random.Random:
        h = hashlib.sha256(str(self.cfg.seed).encode())
        for p in parts:
            h.update(b"\x00")
            h.update(p.encode("utf-8"))
        return random.Random(int(h.hexdigest()[:16], 16))

    #: Ikiz sik esigi ve "digerlerinden belirgin sekilde ayrisma" payi.
    TWIN_SIM = 0.30
    TWIN_MARGIN = 0.15

    def _twin_pair(self, choices: list[str]) -> tuple[int, int, float]:
        """Birbirine en cok benzeyen SOZEL sik ciftini bulur.

        Kural: en yuksek benzerlik `TWIN_SIM` esigini gececek VE ikinci en
        yuksek cifti `TWIN_MARGIN` kadar gecerek ayrisacak.

        OLCULMUS SINIR (durustluk kaydi): bu saf SOZCUKSEL sezgi, 741 altin
        pozitif ve ~3.637 negatif uzerinde duyarlilik ~0,68 / kesinlik ~0,13
        verir. Sebep: tohum uretecinde negatif maddelerin celdiricileri de ayni
        konu havuzundan gelir, yani sozcuksel olarak birbirine benzerdir. Yani
        BU GOREV SOZCUKSEL OLARAK COZULEMEZ; anlamsal ayirim tam da LLM'den
        beklenen katkidir. MockProvider'in dusuk kesinligi bir hata degil,
        gorevin zorlugunun olcusudur.
        """
        toks = [_tokens(c) for c in choices]
        sims: list[tuple[float, int, int]] = []
        for i in range(len(choices)):
            for j in range(i + 1, len(choices)):
                # Yalnizca sozel siklar: en az uc harfli belirtec gerekli.
                if len(toks[i]) < 3 or len(toks[j]) < 3:
                    continue
                sims.append((_jaccard(toks[i], toks[j]), i, j))
        if not sims:
            return (-1, -1, 0.0)
        sims.sort(reverse=True)
        top = sims[0]
        second = sims[1][0] if len(sims) > 1 else 0.0
        if top[0] >= self.TWIN_SIM and (top[0] - second) >= self.TWIN_MARGIN:
            return (top[1], top[2], top[0])
        return (-1, -1, 0.0)

    def _label_item(self, stem: str, choices: list[str], rng: random.Random,
                    temperature: float) -> dict:
        n = _norm(stem)
        full_len = len(stem) + sum(len(c) for c in choices)

        if any(c in n for c in _ANALIZ_CUES):
            talep = "analiz"
        elif any(c in n for c in _UYGULAMA_CUES) or re.search(r"\d", stem):
            talep = "uygulama"
        else:
            talep = "hatirlama"

        adim = "cok_adim" if (talep != "hatirlama" and len(stem) > 90) else "tek_adim"
        okuma = "yuksek" if full_len > 220 else "dusuk"

        i, j, sim = self._twin_pair(choices)
        tuzak = "yok"
        idx: int | None = None
        if i >= 0:
            tuzak = "var"
            a, b = _norm(choices[i]), _norm(choices[j])
            sa = sum(1 for w in _OVERGEN if w in a)
            sb = sum(1 for w in _OVERGEN if w in b)
            if sa > sb:
                idx = i
            elif sb > sa:
                idx = j
            else:
                idx = i if rng.random() < 0.5 else j

        labels = {"bilissel_talep": talep, "adim_sayisi": adim,
                  "dikkat_tuzagi": tuzak, "okuma_yuku": okuma}

        # Sicakliga bagli kararsizlik: intra-PSS'in 1,0 cikmamasi icin. Gercek
        # modellerin ornekleme gurultusunun yerini tutar (bulgu 5).
        # temperature = 0 -> TAM belirlenimci (gercek modelde de greedy cozum
        # boyledir); sicaklik arttikca kararsizlik artar.
        flip_p = min(0.35, 0.22 * temperature)
        from .rubric import DIMENSIONS
        for dim in labels:
            if rng.random() < flip_p:
                alts = [x for x in DIMENSIONS[dim].labels if x != labels[dim]]
                labels[dim] = alts[rng.randrange(len(alts))]
        if labels["dikkat_tuzagi"] == "var" and idx is None:
            idx = rng.randrange(len(choices)) if choices else None
            if idx is None:
                labels["dikkat_tuzagi"] = "yok"
        if labels["dikkat_tuzagi"] == "yok":
            idx = None

        conf = {d: round(0.55 + 0.4 * rng.random(), 3) for d in labels}
        return {
            "boyutlar": {d: {"etiket": labels[d], "guven": conf[d]} for d in labels},
            "tuzak_sik_index": idx,
            "gerekce": "Mock saglayici: metin sezgileriyle uretilmis etiket.",
        }

    def _call(self, prompt: str, system: str | None, temperature: float,
              model: str, *, kind: str = "label", **kw) -> ChatResult:
        rng = self._rng(prompt, system or "", f"{temperature:.3f}",
                        str(kw.get("nonce", "")))
        if kind == "paraphrase":
            body = prompt.split("METIN:\n", 1)[-1]
            text = body.replace("KURALLAR", "UYULACAK KURALLAR")
        elif kind == "critic":
            text = self._critic_text(prompt, rng)
        elif kind == "merge":
            text = self._merge_text(prompt, rng)
        else:
            stem, choices = parse_item_from_prompt(prompt)
            text = json.dumps(self._label_item(stem, choices, rng, temperature),
                              ensure_ascii=False)
        # Token sayilari kabaca 3 karakter = 1 token (Turkce icin temkinli).
        usage = Usage(input_cache_hit=0,
                      input_cache_miss=max(1, len(prompt) // 3 + len(system or "") // 3),
                      output=max(1, len(text) // 3))
        return ChatResult(text=text, usage=usage, model=model, latency_s=0.0)

    def _critic_text(self, prompt: str, rng: random.Random) -> str:
        """Oneriyi cogunlukla aynen onaylar, %12 olasilikla DEGISTIRIR.

        Bulgu 8: hatalarin ~%21'i dogrulama katmanindan gelir. Burada degisiklik
        olasiligi bilerek sifir DEGILDIR ki `validate.py` "elestirmen kac karari
        bozdu / kac karari duzeltti" sayisini raporlayabilsin.
        """
        m = re.search(r"ONERILEN ETIKETLER\n(\{.*?\})\n", prompt, re.DOTALL)
        if not m:
            return '{"boyutlar": {}, "gerekce": "bos"}'
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            return m.group(1)
        from .rubric import DIMENSIONS
        if rng.random() < 0.12:
            dim = sorted(data.get("boyutlar", {}))[rng.randrange(
                max(1, len(data.get("boyutlar", {}))))] if data.get("boyutlar") else None
            if dim:
                cur = data["boyutlar"][dim]["etiket"]
                alts = [x for x in DIMENSIONS[dim].labels if x != cur]
                data["boyutlar"][dim]["etiket"] = alts[rng.randrange(len(alts))]
                if dim == "dikkat_tuzagi":
                    data["tuzak_sik_index"] = (
                        None if data["boyutlar"][dim]["etiket"] == "yok" else 0)
                data["gerekce"] = "Elestirmen: yonerge sinir durumu ihlali."
        return json.dumps(data, ensure_ascii=False)

    def _merge_text(self, prompt: str, rng: random.Random) -> str:
        """Ajan etiketlerinden boyut basina cogunluk; beraberlikte ilk ajan."""
        from .rubric import DIMENSION_ORDER, DIMENSIONS
        rows = re.findall(r"^- (\w+): (.*)$", prompt, re.MULTILINE)
        votes: dict[str, list[str]] = {d: [] for d in DIMENSION_ORDER}
        trap: list[int] = []
        for _role, body in rows:
            for kv in body.split(", "):
                if "=" not in kv:
                    continue
                k, v = kv.split("=", 1)
                if k in votes:
                    votes[k].append(v)
                elif k == "tuzak_sik_index" and v not in ("None", "null", ""):
                    try:
                        trap.append(int(v))
                    except ValueError:
                        pass
        out = {}
        for dim in DIMENSION_ORDER:
            vs = votes[dim] or [DIMENSIONS[dim].labels[0]]
            best = max(sorted(set(vs)), key=lambda x: (vs.count(x), -vs.index(x)))
            agree = vs.count(best) / len(vs)
            out[dim] = {"etiket": best, "guven": round(0.45 + 0.5 * agree, 3)}
        idx = None
        if out["dikkat_tuzagi"]["etiket"] == "var":
            idx = max(sorted(set(trap)), key=trap.count) if trap else 0
        return json.dumps({"boyutlar": out, "tuzak_sik_index": idx,
                           "gerekce": "Birlestirici: boyut basina cogunluk."},
                          ensure_ascii=False)


def build_provider(cfg: SegmentConfig, *, mock: bool = False, cache=None,
                   budget: BudgetGuard | None = None) -> BaseProvider:
    """Yapilandirmaya gore saglayici uretir.

    Anahtar yoksa ve `mock` istenmemisse UYARI verip mock'a duser — boylece
    "anahtarsiz uctan uca kosu" garantisi bozulmaz, ama sessizce de olmaz.
    """
    if mock:
        return MockProvider(cfg, cache=cache, budget=budget)
    if not cfg.api_key:
        log("warn", "DEEPSEEK_API_KEY yok -> MockProvider'a dusuluyor. "
                    "Mock ciktilari GERCEK MODEL KALITESI DEGILDIR.")
        return MockProvider(cfg, cache=cache, budget=budget)
    return DeepSeekProvider(cfg, cache=cache, budget=budget)
