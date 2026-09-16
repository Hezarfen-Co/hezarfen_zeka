"""Etiketleyici varyantlari: taban cizgi ve cok ajanli kurgular.

MIMARI SIRASI (bulgu 7, 9, 10, 11):
  Asama 1 — `BaselineLabeler`: tek iyi istem, TEK CAGRI. Bu ZORUNLU KONTROL
    GRUBUDUR. Bulgu 7: "cok ajanli mimarinin kazanci asgari duzeydedir; cok
    ajanli mimari OTOMATIK kazanc getirmez."
  Asama 2 — cok ajanli varyantlar, ESIT TOKEN BUTCESINDE:
    * `SelfConsistencyLabeler`  : ayni istem k kez + cogunluk oylamasi.
      Bulgu 7: MAD, esit hesaplama butcesinde self-consistency cogunluk
      oylamasinin GERISINDE kaliyor -> bu varyant tartismadan once denenir.
    * `HeterogeneousRolesLabeler`: rolleri AYRISTIRILMIS ajanlar + birlestirici.
      Bulgu 10: homojen tartisma sikofantik uyum uretiyor (modal benimseme
      %85,5'e kadar) -> HOMOJEN TARTISMA KURULMADI. Ajanlar birbirinin
      gerekcesini GORMEZ; birlestirici yalnizca etiketleri gorur.
    * `GeneratorCriticLabeler` (istege bagli): bulgu 8 geregi dogrulayici
      katmanin KENDISI olculur — kac karari duzeltti, kac karari BOZDU
      (`critic_changed` sayaci) raporlanir, varsayilmaz.

ESIT BUTCE: `cfg.equal_budget_calls` (varsayilan 4) hem self_consistency'nin k
degeri hem de heterogeneous_roles'un (3 rol + 1 birlestirici) cagri sayisidir.
Boylece iki cok ajanli varyant AYNI cagri sayisiyla kosar. Taban cizgi 1 cagri
yapar ve zaten "ucuz kontrol"dur; `validate.compare()` her varyantin gercek
token orani ile butce esitligini DOGRULAR.
"""

from __future__ import annotations

import json
import threading
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from . import prompts
from .config import SegmentConfig, log
from .provider import BaseProvider, BudgetExceeded, parallel_map
from .rubric import DIMENSION_ORDER, DIMENSIONS
from .schema import (
    CallUsage,
    DimensionResult,
    ItemSegmentation,
    SchemaError,
    parse_label_json,
)


@dataclass
class LabelBatch:
    """Bir varyantin bir madde kumesi uzerindeki tam ciktisi."""

    variant: str
    prompt_version: str
    model: str
    results: dict[str, ItemSegmentation] = field(default_factory=dict)
    usage: CallUsage = field(default_factory=CallUsage)
    #: Sema dogrulamasini gecemeyen maddeler (SESSIZCE KABUL EDILMEZ).
    failures: dict[str, str] = field(default_factory=dict)
    #: Yalnizca generator_critic: elestirmenin degistirdigi karar sayisi.
    critic_changed: int = 0
    critic_total: int = 0
    #: Butce durdu mu.
    budget_stopped: bool = False

    @property
    def n(self) -> int:
        return len(self.results)

    def tokens_per_item(self) -> float:
        return self.usage.tokens_total / self.n if self.n else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant": self.variant,
            "prompt_version": self.prompt_version,
            "model": self.model,
            "n": self.n,
            "usage": self.usage.to_dict(),
            "tokens_per_item": round(self.tokens_per_item(), 1),
            "failures": len(self.failures),
            "critic_changed": self.critic_changed,
            "critic_total": self.critic_total,
            "budget_stopped": self.budget_stopped,
        }


def _usage_of(res) -> CallUsage:
    return CallUsage(tokens_in=res.usage.input_total, tokens_out=res.usage.output,
                     tokens_reasoning=res.usage.reasoning,
                     cost_usd=res.cost, calls=1, cached=1 if res.cached else 0)


class BaseLabeler:
    """Ortak akis: madde listesini dolas, hata yonetimi, butce durdurma."""

    variant = "base"

    def __init__(self, provider: BaseProvider, cfg: SegmentConfig, *,
                 prompt_version: str = prompts.BASELINE_VERSION):
        self.provider = provider
        self.cfg = cfg
        self.prompt_version = prompt_version

    # -- alt siniflar bunu doldurur ---------------------------------------
    def label_item(self, item: dict) -> ItemSegmentation:
        raise NotImplementedError

    def run(self, items: list[dict]) -> LabelBatch:
        """Madde listesini `cfg.concurrency` is parcasiyla ES ZAMANLI etiketler.

        ES ZAMANLILIK BURADA: eskiden bu dongu duz `for` idi, dolayisiyla
        `SEGMENT_CONCURRENCY` ayari saglayicidaki semaforda DURUYOR ama hicbir
        zaman ZORLANMIYORDU (tek is parcasi semafora asla takilmaz). Olculdu:
        12 madde, concurrency=1 ve concurrency=6 icin sure AYNI, tepe es zamanli
        cagri sayisi 1. Duzeltme madde duzeyinde paralellik getirir.

        Neden madde duzeyi (ic ice havuz YOK): gercek kosularda madde sayisi
        es zamanlilik sinirindan cok buyuktur, bu yuzden duz madde paralelligi
        zaten tum kanallari doldurur. Ic ice havuz ise klasik acliga/kilitlenmeye
        acik olurdu (dis isler tum isciyi tutup ic isleri beklerdi).

        BELIRLENIMCILIK KORUNUR: sonuclar GIRIS SIRASINDA toplanir, hata ve
        butce durdurma kararlari yalnizca toplayan (ana) is parcasinda islenir.
        """
        batch = LabelBatch(variant=self.variant, prompt_version=self.prompt_version,
                           model=self.provider.model_for())

        def on_error(_i: int, item: dict, exc: BaseException) -> bool:
            qid = item["question_id"]
            if isinstance(exc, BudgetExceeded):
                # Gorev sarti: USD tavani asilirsa KOSU DURUR. `True` donunce
                # `parallel_map` henuz baslamamis isleri IPTAL eder.
                batch.budget_stopped = True
                log("warn", f"butce durdurdu ({self.variant}): {exc}")
                return True
            if isinstance(exc, SchemaError):
                # Dogrulanamayan yanit SESSIZCE KABUL EDILMEZ.
                batch.failures[qid] = f"sema: {exc}"
                return False
            if isinstance(exc, Exception):
                batch.failures[qid] = f"{type(exc).__name__}: {exc}"
                return False
            raise exc  # KeyboardInterrupt / SystemExit yutulmaz

        pairs = parallel_map(self.label_item, items, self.cfg.concurrency,
                             on_error=on_error)
        for idx, seg in pairs:
            qid = items[idx]["question_id"]
            batch.results[qid] = seg
            batch.usage.add(seg.usage)
        if isinstance(self, GeneratorCriticLabeler):
            batch.critic_changed = self._critic_changed
            batch.critic_total = self._critic_total
        return batch

    # -- yardimcilar -------------------------------------------------------
    def _one_call(self, item: dict, *, prompt_version: str | None = None,
                  nonce: str = "", temperature: float | None = None,
                  system: str | None = None, user: str | None = None,
                  retry_on_schema: int = 1) -> ItemSegmentation:
        """Tek LLM cagrisi + KATI sema dogrulamasi (+ sinirli yeniden deneme).

        Sema hatasinda en fazla `retry_on_schema` kez farkli nonce ile tekrar
        denenir; yine olmazsa `SchemaError` yukselir ve madde "etiketlenemedi"
        sayilir.
        """
        pv = prompt_version or self.prompt_version
        if user is None:
            user = prompts.get(pv).render(item, course_name=item.get("course_name"))
        if system is None:
            system = prompts.get(pv).system
        usage = CallUsage()
        last: SchemaError | None = None
        for attempt in range(retry_on_schema + 1):
            res = self.provider.chat(
                user, system=system, temperature=temperature,
                cache_key_extra=f"{nonce}|{attempt}", nonce=f"{nonce}|{attempt}")
            usage.add(_usage_of(res))
            try:
                seg = parse_label_json(
                    res.text, question_id=item["question_id"],
                    choices=item.get("choices") or [], prompt_version=pv,
                    model=res.model, variant=self.variant)
            except SchemaError as exc:
                last = exc
                continue
            seg.usage = usage
            # Dusunce izi AYRI alanda tasinir; `rationale` modelin kendi yazdigi
            # gerekcedir ve dokunulmaz.
            seg.reasoning_content = res.reasoning_content
            return seg
        raise SchemaError(str(last))


# --------------------------------------------------------------------------
# Asama 1 — taban cizgi (ZORUNLU KONTROL GRUBU, bulgu 7)
# --------------------------------------------------------------------------

class BaselineLabeler(BaseLabeler):
    """Tek iyi istem, tek cagri. Her cok ajanli varyant BUNA karsi olculur."""

    variant = "baseline"

    def label_item(self, item: dict) -> ItemSegmentation:
        return self._one_call(item)


# --------------------------------------------------------------------------
# Asama 2a — self-consistency (bulgu 7: tartismayi geciyor)
# --------------------------------------------------------------------------

def _majority(values: list[str], fallback: str) -> tuple[str, float]:
    """Cogunluk etiketi ve uyum orani. Beraberlikte alfabetik olarak KARARLI."""
    if not values:
        return fallback, 0.0
    counts = Counter(values)
    top = max(counts.items(), key=lambda kv: (kv[1], -ord(kv[0][0])))
    best = sorted([k for k, v in counts.items() if v == top[1]])[0]
    return best, counts[best] / len(values)


class SelfConsistencyLabeler(BaseLabeler):
    """Ayni istem k kez, boyut basina cogunluk oylamasi.

    Bulgu 7: bagimsiz cok-veri-kumeli dogrulamada MAD (cok ajanli tartisma) esit
    hesaplama butcesinde self-consistency cogunluk oylamasinin GERISINDE kalmis.
    Bu yuzden ilk cok ajanli varyant budur.

    KAYIT: cogunluk oylamasinin havuzdaki dogru cevaplari eleyebilecegi
    ("consensus collapse", oracle gap 32,3 puan) iddiasi arastirma turunda 0-3
    ile DUSTU — yani ne dogrulandi ne curutuldu. `validate.py` bu riski
    `oracle_gap` olarak AYRICA olcer.
    """

    variant = "self_consistency"

    def __init__(self, provider, cfg, *, k: int | None = None, **kw):
        super().__init__(provider, cfg, **kw)
        self.k = k or cfg.equal_budget_calls

    def label_item(self, item: dict) -> ItemSegmentation:
        samples: list[ItemSegmentation] = []
        usage = CallUsage()
        for i in range(self.k):
            # Her ornek farkli nonce -> onbellekte ayri satir, mock'ta ayri tohum.
            # Sicaklik taban cizgiden YUKSEK: ornekleme cesitliligi olmadan
            # self-consistency anlamsizdir.
            seg = self._one_call(item, nonce=f"sc{i}",
                                 temperature=max(self.cfg.temperature, 0.6))
            usage.add(seg.usage)
            samples.append(seg)
        if not samples:
            raise SchemaError("hicbir ornek dogrulanamadi")

        labels: dict[str, DimensionResult] = {}
        agent_labels: list[dict[str, str]] = []
        for i, s in enumerate(samples):
            row = {d: s.label(d) for d in DIMENSION_ORDER}
            row["_rol"] = f"ornek{i}"
            if s.trap_choice_index is not None:
                row["tuzak_sik_index"] = str(s.trap_choice_index)
            agent_labels.append(row)

        for dim in DIMENSION_ORDER:
            vals = [s.label(dim) for s in samples]
            best, share = _majority(vals, DIMENSIONS[dim].labels[0])
            # Guven = oy payi x ortalama ic guven. Bulgu 10: yuksek uyum tek
            # basina dogruluk demek degil; bu yuzden guven ic guvenle carpilir.
            inner = sum(s.labels[dim].confidence for s in samples
                        if s.label(dim) == best) / max(1, vals.count(best))
            labels[dim] = DimensionResult(best, round(share * inner, 4))

        trap_index = None
        trap_text = None
        if labels["dikkat_tuzagi"].label == "var":
            idxs = [s.trap_choice_index for s in samples
                    if s.trap_choice_index is not None]
            if idxs:
                trap_index = Counter(idxs).most_common(1)[0][0]
                trap_text = (item.get("choices") or [None] * (trap_index + 1))[trap_index]
            else:
                # Cogunluk "var" dedi ama hicbiri sik gostermedi -> tutarsiz;
                # sessizce "var" birakma, "yok"a dusur ve guveni kir.
                labels["dikkat_tuzagi"] = DimensionResult("yok", 0.1)

        return ItemSegmentation(
            question_id=item["question_id"], labels=labels,
            trap_choice_index=trap_index, trap_choice_text=trap_text,
            rationale=samples[0].rationale, prompt_version=self.prompt_version,
            model=samples[0].model, variant=self.variant, usage=usage,
            agent_labels=agent_labels)


# --------------------------------------------------------------------------
# Asama 2b — heterojen roller (bulgu 10: HOMOJEN TARTISMA YOK)
# --------------------------------------------------------------------------

class HeterogeneousRolesLabeler(BaseLabeler):
    """Rolleri ayristirilmis ajanlar + birlestirici.

    Tasarim kisitlari (bulgu 10):
      * Ajanlar birbirinin CIKTISINI GORMEZ -> akran gerekcesiyle bulasma yok.
      * Birlestirici yalnizca ETIKETLERI gorur, gerekceleri GORMEZ -> sikofantik
        uyumun ana kanali kapali.
      * Tartisma turu YOKTUR; tek atim + birlestirme.
    Cagri sayisi = len(roles) + 1 (varsayilan 3 + 1 = 4) -> self_consistency
    k=4 ile ESIT BUTCE.
    """

    variant = "heterogeneous_roles"
    DEFAULT_ROLES = ("konu_uzmani", "ogrenci_hatasi", "olcme")

    def __init__(self, provider, cfg, *, roles: tuple[str, ...] | None = None, **kw):
        super().__init__(provider, cfg, **kw)
        n = max(2, cfg.equal_budget_calls - 1)
        self.roles = roles or self.DEFAULT_ROLES[:n]

    def label_item(self, item: dict) -> ItemSegmentation:
        usage = CallUsage()
        agent_segs: list[tuple[str, ItemSegmentation]] = []
        for role in self.roles:
            system, user = prompts.render_role(
                role, self.prompt_version, item, item.get("course_name"))
            seg = self._one_call(item, system=system, user=user, nonce=f"role:{role}")
            usage.add(seg.usage)
            agent_segs.append((role, seg))

        agent_labels: list[dict[str, str]] = []
        for role, seg in agent_segs:
            row = {d: seg.label(d) for d in DIMENSION_ORDER}
            row["_rol"] = role
            if seg.trap_choice_index is not None:
                row["tuzak_sik_index"] = str(seg.trap_choice_index)
            agent_labels.append(row)

        system, user = prompts.render_merger(item, agent_labels)
        merged = self._one_call(item, system=system, user=user, nonce="merge")
        usage.add(merged.usage)
        merged.usage = usage
        merged.variant = self.variant
        merged.agent_labels = agent_labels
        return merged


# --------------------------------------------------------------------------
# Istege bagli — generator/critic (bulgu 8: dogrulayiciyi OLC, varsayma)
# --------------------------------------------------------------------------

class GeneratorCriticLabeler(BaseLabeler):
    """Uretici + elestirmen. Elestirmenin etkisi SAYILIR.

    Bulgu 8: MAS hatalarinin ~%21'i 'gorev dogrulama' ekseninden gelir (yanlis
    dogrulama, eksik dogrulama, erken sonlandirma). Bu yuzden burada elestirmen
    "iyilestirme" VARSAYILMAZ: `critic_changed` / `critic_total` raporlanir ve
    `validate.py` elestirmenin dikkat_tuzagi kararlarini kac kez DUZELTTIGINI ve
    kac kez BOZDUGUNU ayri ayri hesaplar.

    Cagri sayisi 2'dir; esit butce hedefi 4 ise `validate.compare()` bu varyanti
    'butce_esit=False' olarak isaretler ve karar kuralinda KAZANAMAZ.
    """

    variant = "generator_critic"

    def __init__(self, provider, cfg, **kw):
        super().__init__(provider, cfg, **kw)
        self._critic_changed = 0
        self._critic_total = 0
        # Sayaclar es zamanli `run()` icinde birden fazla is parcasindan
        # artirilir; `+=` atomik DEGILDIR, kilit sart.
        self._counter_lock = threading.Lock()

    def label_item(self, item: dict) -> ItemSegmentation:
        gen = self._one_call(item, nonce="gen")
        usage = CallUsage()
        usage.add(gen.usage)

        proposal = json.dumps({
            "boyutlar": {d: gen.labels[d].to_dict() for d in DIMENSION_ORDER},
            "tuzak_sik_index": gen.trap_choice_index,
            "gerekce": gen.rationale,
        }, ensure_ascii=False)
        # Sema uyumlu bir onerinin anahtarlari "label/confidence" degil
        # "etiket/guven" olmali — elestirmene sunulan bicim de ayni olsun.
        proposal = proposal.replace('"label"', '"etiket"').replace(
            '"confidence"', '"guven"')

        system, user = prompts.render_critic(item, proposal, item.get("course_name"))
        try:
            crit = self._one_call(item, system=system, user=user, nonce="critic")
        except SchemaError:
            # Elestirmen bozuk yanit verdi -> BULGU 8'in tam ornegi. Ureticinin
            # ciktisi korunur ama bu bir dogrulayici HATASI olarak sayilir.
            with self._counter_lock:
                self._critic_total += 1
            gen.usage = usage
            gen.variant = self.variant
            return gen
        usage.add(crit.usage)
        with self._counter_lock:
            self._critic_total += 1
            if crit.label_tuple() != gen.label_tuple():
                self._critic_changed += 1
        crit.usage = usage
        crit.variant = self.variant
        crit.agent_labels = [
            {**{d: gen.label(d) for d in DIMENSION_ORDER}, "_rol": "uretici"},
            {**{d: crit.label(d) for d in DIMENSION_ORDER}, "_rol": "elestirmen"},
        ]
        return crit


LABELERS: dict[str, type[BaseLabeler]] = {
    "baseline": BaselineLabeler,
    "self_consistency": SelfConsistencyLabeler,
    "heterogeneous_roles": HeterogeneousRolesLabeler,
    "generator_critic": GeneratorCriticLabeler,
}
#: Cok ajanli varyantlarin nominal cagri sayisi (esit butce denetimi icin).
VARIANT_CALLS: dict[str, str] = {
    "baseline": "1",
    "self_consistency": "k (= equal_budget_calls)",
    "heterogeneous_roles": "roller + 1 (= equal_budget_calls)",
    "generator_critic": "2 (esit butce DISI)",
}


def build_labeler(name: str, provider: BaseProvider, cfg: SegmentConfig,
                  **kw) -> BaseLabeler:
    try:
        cls = LABELERS[name]
    except KeyError as exc:
        raise KeyError(f"Bilinmeyen varyant: {name!r}; "
                       f"mevcut: {', '.join(LABELERS)}") from exc
    return cls(provider, cfg, **kw)
