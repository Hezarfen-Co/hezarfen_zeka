"""Segmentasyon alt sisteminin yapilandirma katmani.

Desen `service/src/config.py` ile ayni felsefede: ortamdan okuyan kucuk
yardimcilar, tek bir dataclass, hatali yapilandirmada acik hata. Ancak o dosya
ICE AKTARILMAZ — bu alt sistem bagimsiz durur.

Sir hijyeni: API anahtari HICBIR ZAMAN loglanmaz; `summary()` yalnizca
"tanimli / TANIMSIZ" yazar.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# --- gunlukleme ------------------------------------------------------------
# Windows konsolu ASCII disini bozabiliyor; bu yuzden log satirlari ASCII-Turkce.

_LEVELS = {"debug": 10, "info": 20, "warn": 30, "error": 40}
_active = _LEVELS["info"]


class SegmentConfigError(Exception):
    """Yapilandirma hatasi."""


def set_log_level(name: str) -> None:
    lvl = _LEVELS.get(name.strip().lower())
    if lvl is None:
        raise SegmentConfigError(f"LOG_LEVEL gecersiz: {name!r}")
    global _active
    _active = lvl


def log(level: str, message: str) -> None:
    """Gunluk satiri — DAIMA stderr'e.

    stdout yalnizca makine tarafindan okunacak JSON'u tasir; gunluk satirlari
    oraya karisirsa `python -m src.segment.cli run ... > rapor.json` ciktisi
    ayristirilamaz hale gelir (olculdu: `work/stab.json` bozuldu).
    """
    if _LEVELS.get(level, 20) >= _active:
        print(f"[segment] {message}", file=sys.stderr, flush=True)


def _env(name: str) -> str | None:
    val = os.environ.get(name)
    return val.strip() if val and val.strip() else None


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:  # noqa: PERF203
        raise SegmentConfigError(f"{name} sayi olmali: {raw!r}") from exc


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise SegmentConfigError(f"{name} tamsayi olmali: {raw!r}") from exc


# Model rolleri. Gorev tanimi "pro / flash / reasoner" adlarini yapilandirmadan
# ister; API model id'leri ortamdan degistirilebilir.
#
# UCTAN OLCULDU (2026-09-14, GET https://api.deepseek.com/models): katalogda
# TAM OLARAK IKI model var -> `deepseek-flash` ve `deepseek-v4-pro`.
# `deepseek-chat`, `deepseek-reasoner`, `deepseek-v4-flash` ADLARI ARTIK YOK.
#
# `reasoner` rolu bu yuzden AYRI BIR MODEL DEGILDIR: ayni `deepseek-v4-pro`
# modelinin akil yurutme KIPIDIR (`thinking={"type":"enabled"}`). Ayrimi
# `THINKING_BY_ROLE` tasir.
DEFAULT_MODEL_IDS = {
    "flash": "deepseek-flash",
    "pro": "deepseek-v4-pro",
    "reasoner": "deepseek-v4-pro",
}

#: Rol basina varsayilan akil yurutme kipi (`SEGMENT_THINKING` bunu ezer).
#: UCTAN OLCULDU: `deepseek-v4-pro` akil yurutmeyi VARSAYILAN olarak yapar;
#: "disabled" denmedikce dusunce uretir ve dusunce token'lari CIKTI olarak
#: faturalanir (pahali taraf). Bu yuzden `pro` rolu acikca "disabled" alir,
#: `reasoner` rolu acikca "enabled".
THINKING_BY_ROLE: dict[str, str | None] = {
    "flash": None,          # uca gonderilmez (modelin kendi varsayilani)
    "pro": "disabled",      # maliyet kontrolu: dusunce kapali
    "reasoner": "enabled",  # "pro max thinking" istegi bu rol
}

#: Uctan dogrulanmis gecerli degerler.
THINKING_VALUES = ("enabled", "disabled")
REASONING_EFFORTS = ("minimal", "low", "medium", "high")


@dataclass
class SegmentConfig:
    """Segmentasyon kosusunun tum ayarlari."""

    # --- saglayici ---------------------------------------------------------
    base_url: str = "https://api.deepseek.com"
    api_key: str | None = None
    model_ids: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_MODEL_IDS))
    #: Taban cizgi ve varyantlarin varsayilan model rolu.
    model_role: str = "flash"
    timeout_s: float = 120.0
    #: Akil yurutme kipi. None = rol varsayilani (`THINKING_BY_ROLE`),
    #: "" (bos) = uca HIC gonderme, "enabled"/"disabled" = acikca gonder.
    #: Govdeye METIN degil NESNE olarak konur: {"type": "enabled"}.
    #: UCTAN OLCULDU: metin gonderilirse 400 "invalid type: string, expected
    #: struct ThinkingOptions".
    thinking: str | None = None
    #: `minimal|low|medium|high`; None = uca gonderme.
    reasoning_effort: str | None = None

    # --- maliyet / hiz -----------------------------------------------------
    #: USD tavani. Asilirsa kosu `BudgetExceeded` ile DURUR (gorev sartı).
    budget_usd: float = 5.0
    #: Dakikada azami istek (hiz siniri). `provider.RateLimiter` ile UYGULANIR;
    #: is parcaciklari arasinda paylasilir, es zamanlilik onu EZMEZ.
    rpm: int = 60
    #: Es zamanli istek siniri. IKI yerde birden baglayicidir:
    #:   * `labelers.BaseLabeler.run()` madde havuzunun isci sayisi,
    #:   * `provider.BaseProvider._sem` semaforu (bagimsiz guvenlik kemeri).
    concurrency: int = 4
    #: Ustel geri cekilmeli yeniden deneme sayisi.
    max_retry: int = 4
    retry_base_s: float = 0.5

    # --- onbellek ----------------------------------------------------------
    cache_dir: Path = Path("work/segment_cache")
    cache_enabled: bool = True

    # --- Asama 0: kararlilik kapisi ---------------------------------------
    #: Bulgu 6: "alpha < 0,70 ise istemi revize et". Kapi kodda uygulanir.
    alpha_gate: float = 0.70
    #: Bulgu 6: "PSS >= 0,80 saglam kabul edilir" — bilgi amacli ikinci esik.
    alpha_solid: float = 0.80
    #: Bulgu 11: 300-500 soruluk alt kume (KANITLANMIS DEGIL, pratik tahmin).
    stability_n: int = 300
    #: Bulgu 6'da intra-PSS 30 tekrarla olculuyor; maliyet nedeniyle varsayilan
    #: dusuk tutuldu, gercek kosuda 10+ onerilir.
    intra_replicates: int = 5
    #: Inter-PSS icin anlamca esdegerli istem varyanti sayisi.
    inter_variants: int = 3

    # --- Asama 2: esit token butcesi --------------------------------------
    #: Bulgu 7/9: cok ajanli varyantlar ESIT butcede karsilastirilir. Her cok
    #: ajanli varyant tam olarak bu kadar LLM cagrisi yapar.
    equal_budget_calls: int = 4
    #: Butce esitligi toleransi (token orani |1 - r| <= tol).
    budget_tolerance: float = 0.15

    # --- Asama 3: karar kurali --------------------------------------------
    #: Cok ajanli varyantin taban cizgiyi gecmesi icin gereken asgari F1 farki.
    min_effect: float = 0.03
    #: McNemar testi anlamlilik esigi.
    alpha_significance: float = 0.05
    #: Bulgu 10: ajanlar arasi uyum bu esigin ustunde ama dogruluk taban
    #: cizginin altindaysa "uzlasma yanilsamasi" bayragi kalkar.
    consensus_illusion_agreement: float = 0.80

    # --- veri --------------------------------------------------------------
    items_path: Path = Path("work/items_enriched.json")
    manifest_path: Path = Path("seed/_seed_manifest.json")
    answers_path: Path = Path("seed/11_exam_answer.surql")
    out_dir: Path = Path("work/segment_out")

    #: Belirlenimcilik tohumu (MockProvider + orneklem + permutasyon).
    seed: int = 20260913
    #: Ornekleme/etiketleme sicakligi. MockProvider bunu "kararsizlik" olarak
    #: kullanir; gercek saglayicida API'ye gider.
    temperature: float = 0.2

    @classmethod
    def from_env(cls, root: Path | None = None) -> "SegmentConfig":
        """Ortam degiskenlerinden yapilandirma uretir.

        `root` verilirse tum goreli yollar onun altinda cozulur (depo koku).
        """
        cfg = cls()
        cfg.base_url = (_env("SEGMENT_BASE_URL") or _env("LLM_BASE_URL")
                        or cfg.base_url).rstrip("/")
        # Anahtar arama sirasi: rag servisindeki desenle ayni (oku, kopyalama).
        cfg.api_key = (_env("DEEPSEEK_API_KEY") or _env("LLM_API_KEY")
                       or _env("SEGMENT_API_KEY"))
        for role in ("flash", "pro", "reasoner"):
            override = _env(f"SEGMENT_MODEL_{role.upper()}")
            if override:
                cfg.model_ids[role] = override
        role = _env("SEGMENT_MODEL_ROLE")
        if role:
            if role not in cfg.model_ids:
                raise SegmentConfigError(
                    f"SEGMENT_MODEL_ROLE gecersiz: {role!r} "
                    f"(beklenen: {', '.join(sorted(cfg.model_ids))})")
            cfg.model_role = role

        # Akil yurutme: BOS STRING ile "hic gonderme" ayrimi korunur, bu yuzden
        # `_env` degil dogrudan `os.environ` okunur.
        if "SEGMENT_THINKING" in os.environ:
            cfg.thinking = os.environ["SEGMENT_THINKING"].strip().lower()
        if "SEGMENT_REASONING_EFFORT" in os.environ:
            raw = os.environ["SEGMENT_REASONING_EFFORT"].strip().lower()
            cfg.reasoning_effort = raw or None

        cfg.budget_usd = _env_float("SEGMENT_BUDGET_USD", cfg.budget_usd)
        cfg.rpm = _env_int("SEGMENT_RPM", cfg.rpm)
        cfg.concurrency = _env_int("SEGMENT_CONCURRENCY", cfg.concurrency)
        cfg.max_retry = _env_int("SEGMENT_MAX_RETRY", cfg.max_retry)
        cfg.timeout_s = _env_float("SEGMENT_TIMEOUT_S", cfg.timeout_s)

        cfg.alpha_gate = _env_float("SEGMENT_ALPHA_GATE", cfg.alpha_gate)
        cfg.stability_n = _env_int("SEGMENT_STABILITY_N", cfg.stability_n)
        cfg.intra_replicates = _env_int("SEGMENT_INTRA_REPLICATES",
                                        cfg.intra_replicates)
        cfg.inter_variants = _env_int("SEGMENT_INTER_VARIANTS", cfg.inter_variants)
        cfg.equal_budget_calls = _env_int("SEGMENT_EQUAL_BUDGET_CALLS",
                                          cfg.equal_budget_calls)
        cfg.min_effect = _env_float("SEGMENT_MIN_EFFECT", cfg.min_effect)
        cfg.seed = _env_int("SEGMENT_SEED", cfg.seed)
        cfg.temperature = _env_float("SEGMENT_TEMPERATURE", cfg.temperature)
        cfg.cache_enabled = (_env("SEGMENT_CACHE") or "1") not in ("0", "off", "no")

        cache = _env("SEGMENT_CACHE_DIR")
        if cache:
            cfg.cache_dir = Path(cache)
        items = _env("SEGMENT_ITEMS")
        if items:
            cfg.items_path = Path(items)
        out = _env("SEGMENT_OUT_DIR")
        if out:
            cfg.out_dir = Path(out)

        if root is not None:
            cfg.resolve_under(root)
        cfg.validate()
        return cfg

    def resolve_under(self, root: Path) -> None:
        """Goreli yollari depo koku altinda coz."""
        root = Path(root)
        for name in ("cache_dir", "items_path", "manifest_path", "answers_path",
                     "out_dir"):
            p = Path(getattr(self, name))
            if not p.is_absolute():
                setattr(self, name, root / p)

    def validate(self) -> None:
        if self.budget_usd <= 0:
            raise SegmentConfigError("SEGMENT_BUDGET_USD pozitif olmali.")
        if not 0.0 <= self.alpha_gate <= 1.0:
            raise SegmentConfigError("SEGMENT_ALPHA_GATE [0,1] araliginda olmali.")
        if self.intra_replicates < 2:
            raise SegmentConfigError(
                "intra-PSS icin en az 2 tekrar gerekir (alpha tanimsiz olur).")
        if self.equal_budget_calls < 2:
            raise SegmentConfigError("equal_budget_calls en az 2 olmali.")
        if self.concurrency < 1:
            raise SegmentConfigError("concurrency en az 1 olmali.")
        # RPM sessizce kirpilmasin: `RateLimiter` 1'in altini 1'e cekerdi,
        # yani hatali ayar fark edilmeden kosuyu dakikada 1 istege dusururdu.
        if self.rpm < 1:
            raise SegmentConfigError("SEGMENT_RPM en az 1 olmali.")
        if self.thinking not in (None, "") and self.thinking not in THINKING_VALUES:
            raise SegmentConfigError(
                f"SEGMENT_THINKING gecersiz: {self.thinking!r} "
                f"(beklenen: {', '.join(THINKING_VALUES)} ya da bos)")
        if self.reasoning_effort is not None and \
                self.reasoning_effort not in REASONING_EFFORTS:
            raise SegmentConfigError(
                f"SEGMENT_REASONING_EFFORT gecersiz: {self.reasoning_effort!r} "
                f"(beklenen: {', '.join(REASONING_EFFORTS)})")

    def model_id(self, role: str | None = None) -> str:
        role = role or self.model_role
        try:
            return self.model_ids[role]
        except KeyError as exc:
            raise SegmentConfigError(f"Bilinmeyen model rolu: {role!r}") from exc

    def thinking_for(self, role: str | None = None) -> str | None:
        """Bu rol icin uca gonderilecek akil yurutme kipi.

        Oncelik: acik `SEGMENT_THINKING` > rol varsayilani. `""` (bos) verilirse
        uca HIC gonderilmez ve modelin kendi varsayilani gecerli olur.
        """
        if self.thinking is not None:
            return self.thinking or None
        return THINKING_BY_ROLE.get(role or self.model_role)

    def summary(self) -> str:
        key = "tanimli" if self.api_key else "TANIMSIZ"
        think = self.thinking_for() or "(uca gonderilmiyor)"
        effort = self.reasoning_effort or "(uca gonderilmiyor)"
        return (
            f"base_url={self.base_url} api_key={key} rol={self.model_role} "
            f"model={self.model_id()} thinking={think} reasoning_effort={effort} "
            f"butce={self.budget_usd:.2f} USD "
            f"alpha_kapi={self.alpha_gate} esit_butce_cagri={self.equal_budget_calls} "
            f"onbellek={'acik' if self.cache_enabled else 'kapali'}"
        )
