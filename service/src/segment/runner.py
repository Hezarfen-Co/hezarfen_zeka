"""Asama akisi: kapilar, butce, A/B ve ogrenci tarafi.

SIRA (bulgu 11'in cikarimsal protokolu — bu bir CALISMA BULGUSU DEGIL, uc
dogrulanmis bulgunun birlestirilmesinden turetilmis operasyonel protokoldur):
  Asama 0  kararlilik (intra/inter-PSS)  -> KAPI: min alpha < 0,70 ise DUR
  Asama 1  tek modelli taban cizgi       -> zorunlu kontrol grubu (bulgu 7)
  Asama 2  cok ajanli varyantlar         -> ESIT TOKEN BUTCESINDE (bulgu 7, 9)
  Asama 3  A/B + acik karar kurali       -> gecemezse taban cizgi
  Asama 4  ogrenci tarafi                -> ayri ve DURUST

Butce: tek bir `BudgetGuard` tum asamalarda paylasilir; USD tavani asilirsa
`BudgetExceeded` yukselir ve kosu o noktada DURUR (kismi sonuclar yazilir).
"""

from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from . import prompts
from .cache import ResponseCache
from .config import SegmentConfig, log
from .labelers import LabelBatch, build_labeler
from .provider import BudgetExceeded, BudgetGuard, build_provider
from .rubric import (
    DIMENSION_ORDER,
    EXPERIMENTAL_DIMENSIONS,
    PRODUCTION_DIMENSIONS,
    experimental_report,
)
from .stability import StabilityReport, build_report, is_solid
from .validate import (
    Decision,
    GoldSet,
    VariantScore,
    build_gold_set,
    compare,
    load_misconception_pairs,
    pvalue_probe,
    score_variant,
    write_report,
)

MULTI_AGENT_VARIANTS = ("self_consistency", "heterogeneous_roles")


# --------------------------------------------------------------------------
# Veri yukleme
# --------------------------------------------------------------------------

def load_items(path: Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data["items"] if isinstance(data, dict) else data
    # Yalnizca coktan secmeli ve en az 3 sikli maddeler etiketlenir.
    return [i for i in items if len(i.get("choices") or []) >= 3]


def stratified_subset(items: Sequence[dict], n: int, *, seed: int) -> list[dict]:
    """Katmanli alt kume: ders/konu ve pozitiflik dengeli, BELIRLENIMCI.

    Bulgu 11: kararlilik olcumu 300-500 soruluk alt kumede yapilir (bu buyukluk
    KANITLANMIS DEGIL, pratik bir tahmindir). Katmanlama konu adina gore yapilir
    ki tek bir dersin istem davranisi tum alpha'yi belirlemesin.
    """
    if n >= len(items):
        return list(items)
    rng = random.Random(seed)
    buckets: dict[str, list[dict]] = {}
    for it in sorted(items, key=lambda x: x["question_id"]):
        buckets.setdefault(it.get("subject_name") or "?", []).append(it)
    keys = sorted(buckets)
    for k in keys:
        rng.shuffle(buckets[k])
    out: list[dict] = []
    idx = 0
    while len(out) < n:
        added = False
        for k in keys:
            if idx < len(buckets[k]):
                out.append(buckets[k][idx])
                added = True
                if len(out) >= n:
                    break
        if not added:
            break
        idx += 1
    return out[:n]


# --------------------------------------------------------------------------
# Kosu sonucu
# --------------------------------------------------------------------------

@dataclass
class RunResult:
    config: dict[str, Any] = field(default_factory=dict)
    stage0: dict[str, Any] = field(default_factory=dict)
    stage1: dict[str, Any] = field(default_factory=dict)
    stage2: dict[str, Any] = field(default_factory=dict)
    stage3: dict[str, Any] = field(default_factory=dict)
    stage4: dict[str, Any] = field(default_factory=dict)
    #: Asama 5 — depoya yazim. `--persist` verilmediyse BOS kalir.
    stage5: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    cache: dict[str, Any] = field(default_factory=dict)
    stopped_at: str | None = None
    caveats: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config, "stage0_stability": self.stage0,
            "stage1_baseline": self.stage1, "stage2_variants": self.stage2,
            "stage3_decision": self.stage3, "stage4_students": self.stage4,
            "stage5_persist": self.stage5,
            "budget": self.budget, "cache": self.cache,
            "stopped_at": self.stopped_at, "caveats": self.caveats,
            "elapsed_s": round(self.elapsed_s, 2),
        }


class SegmentRunner:
    """Asamalari sirayla kosan orkestrator."""

    def __init__(self, cfg: SegmentConfig, *, mock: bool = False,
                 provider=None, cache: ResponseCache | None = None):
        self.cfg = cfg
        self.cache = cache if cache is not None else ResponseCache(
            cfg.cache_dir, enabled=cfg.cache_enabled)
        self.budget = BudgetGuard(cfg.budget_usd)
        self.provider = provider or build_provider(
            cfg, mock=mock, cache=self.cache, budget=self.budget)
        self.result = RunResult(config={"summary": cfg.summary(),
                                        "saglayici": self.provider.name,
                                        "tohum": cfg.seed})
        if self.provider.name == "mock":
            self.result.caveats.append(
                "SAGLAYICI = MockProvider. Mock gercek bir dil modeli DEGILDIR; "
                "ciktilari kaba metin sezgilerinden ve tohumlu gurultuden gelir. "
                "Buradaki F1/alpha degerleri BORU HATTININ CALISTIGINI gosterir, "
                "DeepSeek'in etiketleme kalitesi hakkinda HICBIR SEY SOYLEMEZ.")
        if self.provider.name != "mock":
            from .provider import PRICING_SOURCE, PRICING_UPDATED, PRICING_VERIFIED
            if not PRICING_VERIFIED:
                self.result.caveats.append(
                    "FIYATLAR DOGRULANMADI. Model adlari uctan dogrulandi "
                    f"(GET /models, 2026-09-14) ama tarifeler {PRICING_UPDATED} "
                    f"tarihli kopyadan geliyor ({PRICING_SOURCE}). Rapordaki USD "
                    "rakamlari ve butce tavani ancak tarifeler teyit edildikten "
                    "sonra baglayicidir.")
        if cfg.temperature == 0.0:
            self.result.caveats.append(
                "SICAKLIK = 0. Bu ayarda cozum belirlenimcidir; intra-PSS "
                "alpha'sinin 1,0 cikmasi BEKLENEN sonuctur ve 'istem kararli' "
                "kaniti SAYILMAZ. Gercek kararlilik olcumu uretim sicakliginda "
                "(> 0) yapilmalidir (bulgu 5/6).")

    # ----------------------------------------------------------------------
    # Asama 0 — kararlilik kapisi (bulgu 5, 6)
    # ----------------------------------------------------------------------
    def stage0_stability(self, items: Sequence[dict], *,
                         prompt_version: str = prompts.BASELINE_VERSION
                         ) -> tuple[StabilityReport, StabilityReport]:
        """intra-PSS ve inter-PSS olcer. Kapi: min alpha >= cfg.alpha_gate."""
        subset = stratified_subset(items, self.cfg.stability_n, seed=self.cfg.seed)
        log("info", f"Asama 0: kararlilik alt kumesi n={len(subset)} "
                    f"(bulgu 11: 300-500 pratik tahmin)")

        # --- intra-PSS: AYNI istem N kez ---------------------------------
        intra_labels: dict[str, dict[str, dict[str, str]]] = {}
        for rep in range(self.cfg.intra_replicates):
            labeler = build_labeler("baseline", self.provider, self.cfg,
                                    prompt_version=prompt_version)
            rows: dict[str, dict[str, str]] = {}
            for it in subset:
                try:
                    # Her tekrar ayri nonce -> onbellekte ayri satir.
                    # intra-PSS URETIM AYARIYLA olculur: tekrarlar tam olarak
                    # tam kosuda kullanilacak sicaklikta yapilir. Sicakligi
                    # olcum icin yukseltmek kararliligi yapay olarak dusururdu.
                    seg = labeler._one_call(it, nonce=f"intra{rep}",
                                            temperature=self.cfg.temperature)
                except BudgetExceeded:
                    raise
                except Exception:  # noqa: BLE001 — dogrulanamayan yanit atlanir
                    continue
                rows[it["question_id"]] = {d: seg.label(d) for d in DIMENSION_ORDER}
            intra_labels[f"tekrar{rep}"] = rows
        intra = build_report("intra", prompt_version, intra_labels,
                             gate=self.cfg.alpha_gate,
                             solid=self.cfg.alpha_solid)

        # --- inter-PSS: anlamca esdeger istem varyantlari -----------------
        # Bulgu 6 kaydi: parafraz Ingilizce araclarla (PEGASUS) DEGIL, DeepSeek
        # ile TURKCE uretilir. Anahtar yoksa elle yazilmis Turkce varyantlara
        # dusulur (`prompts.MANUAL_VARIANTS`).
        variants = prompts.generate_paraphrase_variants(
            self.provider, prompt_version, n=self.cfg.inter_variants)
        inter_labels: dict[str, dict[str, dict[str, str]]] = {}
        for pv in [prompts.get(prompt_version), *variants]:
            labeler = build_labeler("baseline", self.provider, self.cfg,
                                    prompt_version=pv.version)
            rows = {}
            for it in subset:
                try:
                    seg = labeler._one_call(it, nonce="inter")
                except BudgetExceeded:
                    raise
                except Exception:  # noqa: BLE001
                    continue
                rows[it["question_id"]] = {d: seg.label(d) for d in DIMENSION_ORDER}
            inter_labels[pv.version] = rows
        inter = build_report("inter", prompt_version, inter_labels,
                             gate=self.cfg.alpha_gate, solid=self.cfg.alpha_solid)
        inter.notes.append(
            "Parafrazlar Turkce uretildi (bulgu 6 kaydi: PSS'in PEGASUS adimi "
            "Ingilizce odaklidir, Turkce icin DeepSeek ile ikame edilir).")

        self.result.stage0 = {
            "intra": intra.to_dict(), "inter": inter.to_dict(),
            "gate": self.cfg.alpha_gate,
            "gate_dimensions": list(PRODUCTION_DIMENSIONS),
            "gate_passed": intra.gate_passed and inter.gate_passed,
            "solid_intra": is_solid(intra), "solid_inter": is_solid(inter),
            "aciklama": ("Bulgu 6: alpha < 0,70 ise istem revize edilir ve tam "
                         "kosuya GECILMEZ. PSS kararliligi olcer, GECERLILIGI "
                         "degil. Kapi YALNIZCA uretim boyutlarina bakar."),
            "deneysel_boyutlar": {
                "boyutlar": list(EXPERIMENTAL_DIMENSIONS),
                "intra_alpha": {k: (None if v != v else round(v, 4))
                                for k, v in intra.experimental_alpha.items()},
                "inter_alpha": {k: (None if v != v else round(v, 4))
                                for k, v in inter.experimental_alpha.items()},
                "kapiyi_bloke_eder": False,
                "asagi_akista_kullanilir": False,
                "gerekce": experimental_report(),
            },
        }
        return intra, inter

    def gate_stage0(self, intra: StabilityReport, inter: StabilityReport) -> bool:
        """Kapi kararini KODDA uygular (bulgu 6)."""
        ok = intra.gate_passed and inter.gate_passed
        if not ok:
            failing = sorted(set(intra.failing_dimensions())
                             | set(inter.failing_dimensions()))
            log("warn", f"KAPI KAPALI: alpha < {self.cfg.alpha_gate} "
                        f"(sorunlu boyutlar: {', '.join(failing) or '-'}). "
                        "Istem revize edilmeli; tam kosuya gecilmiyor.")
        return ok

    # ----------------------------------------------------------------------
    # Asama 1 / 2 — etiketleme
    # ----------------------------------------------------------------------
    def run_variant(self, name: str, items: Sequence[dict], **kw) -> LabelBatch:
        labeler = build_labeler(name, self.provider, self.cfg, **kw)
        t0 = time.time()
        batch = labeler.run(list(items))
        log("info", f"{name}: n={batch.n} hata={len(batch.failures)} "
                    f"token/madde={batch.tokens_per_item():.0f} "
                    f"sure={time.time() - t0:.1f}s")
        return batch

    # ----------------------------------------------------------------------
    # Asama 4 — ogrenci tarafi (AYRI ve DURUST)
    # ----------------------------------------------------------------------
    def stage4_students(self, batch: LabelBatch, items: Sequence[dict], *,
                        max_answers: int | None = None) -> dict[str, Any]:
        """Segment etiketleri x ogrenci cevaplari -> ogrenci segment profili.

        DURUSTLUK KAYDI (zorunlu): segmentler METINDEN gelir; tohum verisinde
        zorluk metinden BAGIMSIZ uretilmistir (SENARYO §4.2/§4.4). Bu yuzden
        segment profilinin altin `theta_base` ile korele CIKMAMASI beklenen
        durumdur ve bir KUSUR DEGILDIR. Asagidaki korelasyonlar bu nedenle
        `gecerli_dis_dogrulama: False` ile isaretlenir.
        """
        answers = load_answers(self.cfg.answers_path, max_rows=max_answers)
        if not answers:
            return {"durum": "atlandi",
                    "neden": f"cevap dosyasi okunamadi: {self.cfg.answers_path}"}
        key_by_q = {i["question_id"]: i.get("correct_choice_id") for i in items}

        # ogrenci -> segment -> [dogru mu]
        profile: dict[str, dict[str, list[int]]] = {}
        for qid, uid, selected in answers:
            seg = batch.results.get(qid)
            if seg is None or selected is None:
                continue
            key = key_by_q.get(qid)
            if not key:
                continue
            correct = 1 if selected == key else 0
            # ASAGI AKIS YALNIZCA URETIM BOYUTLARINI KULLANIR. Deneysel boyut
            # (ornegin `adim_sayisi`) etiketlenmeye ve raporlanmaya devam eder,
            # fakat ogrenci profiline GIRMEZ — guvenilirligi kapinin altinda
            # oldugu icin (bkz. rubric.Dimension.downgrade_note).
            buckets = [f"{d}={seg.label(d)}" for d in PRODUCTION_DIMENSIONS]
            row = profile.setdefault(uid, {})
            for b in buckets:
                row.setdefault(b, []).append(correct)

        summary = {u: {k: round(sum(v) / len(v), 4) for k, v in segs.items()
                       if len(v) >= 5}
                   for u, segs in profile.items()}
        gold = load_student_gold(self.cfg.manifest_path)

        # Altin theta ile iliski — GECERSIZ ama hesaplanir.
        from .validate import _pearson
        rels: dict[str, Any] = {}
        for seg_key in sorted({k for s in summary.values() for k in s}):
            xs, ys = [], []
            for uid, segs in summary.items():
                g = gold.get(uid)
                if g is None or seg_key not in segs:
                    continue
                xs.append(segs[seg_key])
                ys.append(g["theta_base"])
            r = _pearson(xs, ys)
            rels[seg_key] = {"n": len(xs), "pearson_r": None if r != r else round(r, 4)}

        # KARSITLIK (contrast) — asil ve DURUST olcum.
        # Yukaridaki ham korelasyonlar YANILTICIDIR: bir ogrencinin herhangi bir
        # segmentteki dogruluk orani buyuk olcude GENEL yetenegini (theta)
        # yansitir, segmentin kendisini degil. Segmentin bilgi tasiyip
        # tasimadigini olcmek icin ayni ogrencinin IKI segment arasindaki FARKINA
        # bakilir; genel duzey bu farkta sadelesir. Tohum verisinde metin ile
        # zorluk bagimsiz uretildigi icin bu farkin theta ile iliskisi ~0
        # cikmalidir — cikarsa da bu bir kusur DEGIL, beklenen sonuctur.
        contrasts: dict[str, Any] = {}
        KARSITLIK_UCLARI = {
            "bilissel_talep": ("analiz", "hatirlama"),
            "adim_sayisi": ("cok_adim", "tek_adim"),
            "dikkat_tuzagi": ("var", "yok"),
            "okuma_yuku": ("yuksek", "dusuk"),
        }
        # Yalnizca uretim boyutlari — deneysel boyut asagi akisa girmez.
        for dim in PRODUCTION_DIMENSIONS:
            a, b = KARSITLIK_UCLARI[dim]
            ka, kb = f"{dim}={a}", f"{dim}={b}"
            xs, ys = [], []
            for uid, segs in summary.items():
                g = gold.get(uid)
                if g is None or ka not in segs or kb not in segs:
                    continue
                xs.append(segs[ka] - segs[kb])
                ys.append(g["theta_base"])
            r = _pearson(xs, ys)
            contrasts[f"{dim}: {a} - {b}"] = {
                "n": len(xs),
                "ortalama_fark": (round(sum(xs) / len(xs), 4) if xs else None),
                "theta_ile_pearson_r": None if r != r else round(r, 4),
            }

        out = {
            "durum": "tamam",
            "n_ogrenci": len(summary),
            "n_cevap_eslesen": sum(len(v) for s in profile.values() for v in s.values()),
            "segment_dogruluk_ortalamasi": _mean_by_segment(summary),
            "altin_theta_ile_iliski": rels,
            "segment_karsitliklari": contrasts,
            "gecerli_dis_dogrulama": False,
            "not": ("Segment etiketleri soru METNINDEN uretilir; tohum verisinde "
                    "zorluk metinden BAGIMSIZ cekilmistir (SENARYO §4.2/§4.4). "
                    "Bu yuzden segment profilinin altin theta_base ile korele "
                    "CIKMAMASI beklenir ve bir kusur degildir. Bu iliski gercek "
                    "veride anlamli olur; burada anlamli DEGILDIR."),
            "not_korelasyon_tuzagi": (
                "`altin_theta_ile_iliski` icindeki YUKSEK r degerleri segmentin "
                "ise yaradigini GOSTERMEZ: bir ogrencinin herhangi bir "
                "segmentteki dogruluk orani zaten genel yetenegini yansitir, "
                "yani her segment theta ile korele cikar. Segmentin bilgi "
                "tasiyip tasimadigi ancak `segment_karsitliklari` (ayni "
                "ogrencinin iki segment arasindaki FARKI) ile gorulur; genel "
                "duzey o farkta sadelesir."),
            "altin_alanlar": ["theta_base", "theta_trend", "gap_subjects",
                              "archetype"],
        }
        self.result.stage4 = out
        return out

    # ----------------------------------------------------------------------
    # Asama 5 — depoya yazim (ISTEGE BAGLI)
    # ----------------------------------------------------------------------
    def stage5_persist(self, batch: LabelBatch, items: Sequence[dict], *,
                       store=None, school: str | None = None,
                       now_ms: int | None = None,
                       max_answers: int | None = None) -> dict[str, Any]:
        """Etiketleri ve ogrenci profillerini ZEKA deposuna yazar.

        VARSAYILAN DAVRANISI DEGISTIRMEZ: bu yontem yalnizca `run(persist=...)`
        ya da CLI'da `--persist` verildiginde cagrilir. `store=None` ise
        donusum yapilir, sayilir, ama TEK BIR IFADE bile calistirilmaz.

        Koprunun kendisi `persist.py` icindedir; `runner` orayi yalnizca burada
        ice aktarir (gec ice aktarma), boylece segmentasyon hatti depo katmani
        olmadan da calismaya devam eder.
        """
        import asyncio
        from . import persist as persist_mod

        answers = load_answers(self.cfg.answers_path, max_rows=max_answers)
        if not answers:
            return {"durum": "atlandi",
                    "neden": f"cevap dosyasi okunamadi: {self.cfg.answers_path}"}
        slug = persist_mod.school_slug(self.cfg, school)
        stamp = now_ms if now_ms is not None else int(time.time() * 1000)
        report = asyncio.run(persist_mod.persist(
            batch, items, answers, school=slug, now_ms=stamp, store=store))
        out = {"durum": "tamam", **report.to_dict()}
        self.result.stage5 = out
        return out

    # ----------------------------------------------------------------------
    # Tam akis
    # ----------------------------------------------------------------------
    def run(self, *, n_items: int | None = None, negatives: int = 400,
            variants: Sequence[str] = MULTI_AGENT_VARIANTS,
            skip_stage0: bool = False, students: bool = False,
            max_answers: int | None = None, persist: bool = False,
            store=None, school: str | None = None,
            now_ms: int | None = None) -> RunResult:
        t0 = time.time()
        items = load_items(self.cfg.items_path)
        pairs = load_misconception_pairs(
            self.cfg.items_path.parent.parent / "generator" / "content_tr.py")
        gold: GoldSet = build_gold_set(items, pairs=pairs, n_negative=negatives,
                                       seed=self.cfg.seed)
        log("info", f"altin kume: {len(gold.positives)} pozitif / "
                    f"{len(gold.negatives)} negatif ornek")
        if n_items is not None and n_items < len(gold.items):
            # Kisitli kosuda POZITIFLER korunur (741 madde zaten kit kaynaktir),
            # negatifler kirpilir. Boylece kucuk kosuda da gercek bir
            # pozitif/negatif dengesi kalir — tn=0 gibi anlamsiz tablo cikmaz.
            keep_pos = gold.positives[:min(len(gold.positives), max(1, n_items // 2))]
            keep_neg = gold.negatives[:max(0, n_items - len(keep_pos))]
            gold = GoldSet(positives=keep_pos, negatives=keep_neg,
                           expected_trap={i["question_id"]: gold.expected_trap[
                               i["question_id"]] for i in keep_pos})
        eval_items = gold.items

        try:
            # --- Asama 0 ---------------------------------------------------
            if not skip_stage0:
                intra, inter = self.stage0_stability(eval_items)
                if not self.gate_stage0(intra, inter):
                    self.result.stopped_at = "stage0_gate"
                    self.result.caveats.append(
                        "Asama 0 kapisi kapali (bulgu 6: alpha < 0,70). Tam "
                        "etiketlemeye GECILMEDI; once istem revize edilmeli.")
                    return self._finish(t0)
            else:
                self.result.stage0 = {"durum": "atlandi",
                                      "uyari": "Kapi atlandi — bulgu 5/6 ihlali."}

            # --- Asama 1: taban cizgi (ZORUNLU KONTROL GRUBU) --------------
            base_batch = self.run_variant("baseline", eval_items)
            base_score = score_variant(base_batch, gold)
            self.result.stage1 = {"batch": base_batch.to_dict(),
                                  "score": base_score.to_dict(),
                                  "rol": "zorunlu kontrol grubu (bulgu 7)"}

            # --- Asama 2: cok ajanli varyantlar, ESIT BUTCE ----------------
            scores: list[VariantScore] = []
            stage2: dict[str, Any] = {"esit_butce_cagri": self.cfg.equal_budget_calls}
            for name in variants:
                b = self.run_variant(name, eval_items)
                s = score_variant(b, gold,
                                  consensus_threshold=self.cfg.consensus_illusion_agreement,
                                  baseline_localized_f1=base_score.localized.f1)
                scores.append(s)
                stage2[name] = {"batch": b.to_dict(), "score": s.to_dict()}
            self.result.stage2 = stage2

            # --- Asama 3: A/B + karar -------------------------------------
            dec: Decision = compare(base_score, scores,
                                    min_effect=self.cfg.min_effect,
                                    alpha=self.cfg.alpha_significance,
                                    budget_tolerance=self.cfg.budget_tolerance,
                                    target_calls=self.cfg.equal_budget_calls)
            self.result.stage3 = {
                "decision": dec.to_dict(),
                "pvalue_probe": pvalue_probe(base_batch, eval_items),
            }

            # --- Asama 4: ogrenci tarafi ----------------------------------
            chosen_batch = base_batch
            if students or persist:
                chosen = dec.chosen
                if chosen != "baseline":
                    chosen_batch = self.run_variant(chosen, eval_items)
            if students:
                self.stage4_students(chosen_batch, items, max_answers=max_answers)

            # --- Asama 5: depoya yazim (ISTEGE BAGLI) ---------------------
            if persist:
                self.stage5_persist(chosen_batch, items, store=store,
                                    school=school, now_ms=now_ms,
                                    max_answers=max_answers)

        except BudgetExceeded as exc:
            self.result.stopped_at = "budget"
            self.result.caveats.append(f"USD tavani asildi, kosu durdu: {exc}")
        return self._finish(t0)

    def _finish(self, t0: float) -> RunResult:
        self.result.budget = self.budget.snapshot()
        self.result.cache = self.cache.stats()
        self.result.elapsed_s = time.time() - t0
        return self.result


def _mean_by_segment(summary: dict[str, dict[str, float]]) -> dict[str, float]:
    agg: dict[str, list[float]] = {}
    for segs in summary.values():
        for k, v in segs.items():
            agg.setdefault(k, []).append(v)
    return {k: round(sum(v) / len(v), 4) for k, v in sorted(agg.items())}


# --------------------------------------------------------------------------
# Tohum verisi okuyuculari (YALNIZCA OKUR)
# --------------------------------------------------------------------------

_ANSWER_RE = re.compile(
    r"question: exam_question:⟨([^⟩]+)⟩.*?"
    r"user: user:⟨([^⟩]+)⟩, selected: (NONE|'[^']*')")


def load_answers(path: Path, *, max_rows: int | None = None
                 ) -> list[tuple[str, str, str | None]]:
    """`seed/11_exam_answer.surql` icinden (soru, ogrenci, secim) uclulerini okur.

    Podman/SurrealDB BASLATILMAZ (gorev kurali): dosya duz metin olarak taranir.
    Bos birakilan maddelerde satir zaten YAZILMAZ (§4.6); `selected: NONE` ise
    metin sorusudur ve `None` dondurulur.
    """
    p = Path(path)
    if not p.exists():
        return []
    out: list[tuple[str, str, str | None]] = []
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            if "exam_question:" not in line:
                continue
            m = _ANSWER_RE.search(line)
            if not m:
                continue
            qid, uid, sel = m.groups()
            out.append((f"exam_question:{qid}", f"user:{uid}",
                        None if sel == "NONE" else sel.strip("'")))
            if max_rows is not None and len(out) >= max_rows:
                break
    return out


def load_student_gold(path: Path) -> dict[str, dict[str, Any]]:
    """`_seed_manifest.json` icindeki ogrenci altin etiketleri."""
    p = Path(path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {s["user"]: s for s in data.get("students", [])}
