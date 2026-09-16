"""Asama 0 — Istem kararliligi: Krippendorff alpha ve Prompt Stability Score.

NEDEN ZORUNLU ON KOSUL (bulgu 5 ve 6):
  Bulgu 5: LLM etiketleri anlamca ESDEGER istem varyasyonlarina karsi
  kirilgandir (etiket dagiliminda 8,38-28,10 yuzde puani kayma). Tum bankayi tek
  bir istem surumuyle etiketlemek tekrarlanabilirligi dogrudan tehdit eder.
  Bulgu 6: altin kume OLMADAN hesaplanabilen tek hazir arac PSS'tir:
    * intra-PSS: AYNI istem N kez -> Krippendorff alpha
    * inter-PSS: anlamca esdeger istem varyantlari -> alpha
  ve "tam etiketleme oncesi 150-500 soruluk alt kumede istem basina PSS olc;
  alpha < 0,70 ise istemi revize et" der. Bu kapi `gate_passed` alaninda
  KODDA UYGULANIR ve `runner.py` gecemezse Asama 1'e ILERLEMEZ.

  KAYIT: PSS KARARLILIGI olcer, GECERLILIGI DEGIL. alpha=0,95 "etiketler dogru"
  demek degildir; "model kendine tutarli" demektir.

NEDEN HARICI PAKET YOK:
  `promptstability` paketi Python >=3.8,<3.11 istiyor; bu depo Python 3.12+
  uzerinde kosuyor. Alpha bu dosyada sifirdan yazildi ve birim testlerle elle
  hesaplanmis degerlere karsi dogrulandi (`tests/test_segment_stability.py`).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from .rubric import DIMENSION_ORDER, EXPERIMENTAL_DIMENSIONS, PRODUCTION_DIMENSIONS

Value = Any
Distance = Callable[[Value, Value], float]


# --------------------------------------------------------------------------
# Uzaklik olcutleri (delta^2)
# --------------------------------------------------------------------------

def nominal_distance(a: Value, b: Value) -> float:
    """Nominal: farkliysa 1, aynysa 0."""
    return 0.0 if a == b else 1.0


def masi_distance(a: Value, b: Value) -> float:
    """Cok etiketli (kume degerli) veri icin MASI uzakligi.

    MASI = 1 - J * M ; J = Jaccard, M = monotonluk katsayisi
    (esit 1; biri digerinin alt kumesi 0,67; kesisiyor ama alt kume degil 0,33;
    ayrik 0). Kaynak: Passonneau (2006), Krippendorff'un kume metrigi olarak
    kullanilir. Boyutlarimiz tek etiketli oldugu icin VARSAYILAN DEGIL; cok
    etiketli bir boyut eklenirse hazir dursun diye vardir.
    """
    sa, sb = frozenset(a), frozenset(b)
    if not sa and not sb:
        return 0.0
    union = sa | sb
    inter = sa & sb
    j = len(inter) / len(union) if union else 1.0
    if sa == sb:
        m = 1.0
    elif sa <= sb or sb <= sa:
        m = 0.67
    elif inter:
        m = 0.33
    else:
        m = 0.0
    return 1.0 - j * m


METRICS: dict[str, Distance] = {"nominal": nominal_distance, "masi": masi_distance}


# --------------------------------------------------------------------------
# Krippendorff alpha
# --------------------------------------------------------------------------

def krippendorff_alpha(units: Iterable[Sequence[Value]], *,
                       metric: str | Distance = "nominal") -> float:
    """Krippendorff alpha — eksik veriye dayanikli genel bicim.

    `units`: her ogesi BIR BIRIMIN (soru) tum degerlendiricilerden (tekrar /
    istem varyanti / ajan) aldigi degerler dizisi. `None` = eksik.

    Formul (genel bicim, Krippendorff 2011):
        o_ck  : tesaduf (coincidence) matrisi
                o_ck = SUM_u [ n_uc * (n_uk - [c==k]) / (m_u - 1) ]
        n_c   = SUM_k o_ck ;  n = SUM_c n_c
        D_o   = (1/n)        * SUM_c SUM_k o_ck * delta^2(c,k)
        D_e   = (1/(n(n-1))) * SUM_c SUM_k n_c * n_k * delta^2(c,k)
        alpha = 1 - D_o / D_e

    Nominal veri icin delta^2(c,k) = [c != k]; bu, yaygin "D_o = kosegen disi
    toplam" bicimine INDIRGENIR. Genel bicim yazildi ki MASI gibi baska
    uzakliklar ayni kodla calissin.

    Ozel durumlar:
      * Hicbir birimde >=2 deger yoksa -> `float('nan')` (alpha tanimsiz).
      * Tek bir deger kategorisi varsa (D_e = 0) -> 1,0 dondurulur; tam uyum
        vardir ama alpha'nin sans duzeltmesi tanimsizdir. Cagiran taraf bu
        durumu ayrica raporlamalidir (`alpha_degenerate`).
    """
    dist: Distance = METRICS[metric] if isinstance(metric, str) else metric

    coincidence: Counter = Counter()
    for unit in units:
        vals = [v for v in unit if v is not None]
        m_u = len(vals)
        if m_u < 2:
            continue  # tek degerlendiricili birim alpha'ya katkida bulunmaz
        counts = Counter(vals)
        for c, n_uc in counts.items():
            for k, n_uk in counts.items():
                pairs = n_uc * (n_uk - (1 if c == k else 0))
                if pairs:
                    coincidence[(c, k)] += pairs / (m_u - 1)

    if not coincidence:
        return float("nan")

    n_c: Counter = Counter()
    for (c, _k), v in coincidence.items():
        n_c[c] += v
    n = sum(n_c.values())
    if n <= 1:
        return float("nan")

    categories = sorted(n_c, key=str)
    d_o = sum(coincidence.get((c, k), 0.0) * dist(c, k)
              for c in categories for k in categories) / n
    d_e = sum(n_c[c] * n_c[k] * dist(c, k)
              for c in categories for k in categories) / (n * (n - 1))

    if d_e == 0:
        # Tek kategori: beklenen uyumsuzluk sifir -> alpha tanimsiz.
        # Gozlenen uyumsuzluk da sifir oldugundan tam uyum kabul edilir.
        return 1.0
    return 1.0 - d_o / d_e


def alpha_is_degenerate(units: Iterable[Sequence[Value]]) -> bool:
    """Tum degerlendiriciler tek bir kategoriyi kullanmis mi?

    Bu durumda alpha 1,0 dondurulur ama bu "mukemmel kararlilik" degil, "boyut
    hic ayirim yapmiyor" anlamina gelebilir — raporda AYRI gosterilmelidir.
    """
    seen = set()
    for unit in units:
        for v in unit:
            if v is not None:
                seen.add(v)
                if len(seen) > 1:
                    return False
    return True


def pairwise_agreement(units: Iterable[Sequence[Value]]) -> float:
    """Ham (sans duzeltmesiz) ikili uyum orani.

    Bulgu 10'un "uzlasma yanilsamasi" gostergesi icin gerekir: ajanlar arasi
    uyum YUKSEK ama dogruluk DUSUK ise bu homojenlik gostergesidir, dogruluk
    degil. Ham oran kasitlidir — alpha ile karistirilmamali.
    """
    agree = 0
    total = 0
    for unit in units:
        vals = [v for v in unit if v is not None]
        for i in range(len(vals)):
            for j in range(i + 1, len(vals)):
                total += 1
                if vals[i] == vals[j]:
                    agree += 1
    return agree / total if total else float("nan")


# --------------------------------------------------------------------------
# PSS raporu
# --------------------------------------------------------------------------

@dataclass
class StabilityReport:
    """Bir istem surumunun kararlilik raporu."""

    kind: str                       # "intra" | "inter"
    prompt_version: str
    n_items: int
    n_raters: int
    #: boyut -> alpha
    alpha: dict[str, float] = field(default_factory=dict)
    #: boyut -> ham ikili uyum
    raw_agreement: dict[str, float] = field(default_factory=dict)
    #: boyut -> tek kategoriye cokmus mu
    degenerate: dict[str, bool] = field(default_factory=dict)
    gate: float = 0.70
    #: Bulgu 6: "PSS >= 0,80 saglam kabul edilir" — bilgi amacli ikinci esik.
    solid_threshold: float = 0.80
    #: KAPIYA GIREN boyutlar. Deneysel boyutlarin alpha'si hesaplanir ve
    #: raporlanir ama kapiyi BLOKE ETMEZ (bkz. `rubric.EXPERIMENTAL_DIMENSIONS`).
    gate_dimensions: tuple[str, ...] = PRODUCTION_DIMENSIONS
    notes: list[str] = field(default_factory=list)

    @property
    def min_alpha(self) -> float:
        """YALNIZCA uretim (kapiya giren) boyutlarinin en dusuk alpha'si."""
        vals = [a for d, a in self.alpha.items()
                if d in self.gate_dimensions and a == a]  # NaN ele
        return min(vals) if vals else float("nan")

    @property
    def experimental_alpha(self) -> dict[str, float]:
        """Kapiya girmeyen boyutlarin alpha'lari — gizlenmez, ayri raporlanir."""
        return {d: a for d, a in self.alpha.items() if d not in self.gate_dimensions}

    @property
    def gate_passed(self) -> bool:
        """Bulgu 6: alpha < 0,70 ise istem revize edilir, tam kosuya GECILMEZ.

        Karar YALNIZCA uretim boyutlarina bakar. NaN (tanimsiz alpha) da
        BASARISIZ sayilir — bilinmezlik gecis sebebi degildir.
        """
        m = self.min_alpha
        return m == m and m >= self.gate

    def failing_dimensions(self) -> list[str]:
        """Kapiyi gecemeyen URETIM boyutlari."""
        return [d for d, a in self.alpha.items()
                if d in self.gate_dimensions and not (a == a and a >= self.gate)]

    def experimental_below_gate(self) -> list[str]:
        """Esigin altinda kalan DENEYSEL boyutlar — bilgi amacli."""
        return [d for d, a in self.experimental_alpha.items()
                if not (a == a and a >= self.gate)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "prompt_version": self.prompt_version,
            "n_items": self.n_items,
            "n_raters": self.n_raters,
            "alpha": {k: (None if v != v else round(v, 4))
                      for k, v in self.alpha.items()},
            "raw_agreement": {k: (None if v != v else round(v, 4))
                              for k, v in self.raw_agreement.items()},
            "degenerate": self.degenerate,
            "min_alpha": (None if self.min_alpha != self.min_alpha
                          else round(self.min_alpha, 4)),
            "gate": self.gate,
            "gate_dimensions": list(self.gate_dimensions),
            "gate_passed": self.gate_passed,
            "failing_dimensions": self.failing_dimensions(),
            # Deneysel boyutlar SESSIZCE GIZLENMEZ: alpha'lari burada durur ve
            # esigin altindaysa bu da acikca yazilir.
            "deneysel_boyutlar": {
                "boyutlar": list(EXPERIMENTAL_DIMENSIONS),
                "alpha": {k: (None if v != v else round(v, 4))
                          for k, v in self.experimental_alpha.items()},
                "esik_altinda": self.experimental_below_gate(),
                "kapiyi_bloke_eder": False,
            },
            "notes": self.notes,
        }


def is_solid(report: StabilityReport) -> bool:
    """Bulgu 6: PSS >= 0,80 'saglam' kabul edilir (kabul esigi DEGIL, bilgi)."""
    m = report.min_alpha
    return m == m and m >= report.solid_threshold


def build_report(kind: str, prompt_version: str,
                 labels_by_rater: dict[str, dict[str, dict[str, str]]],
                 *, gate: float = 0.70, solid: float = 0.80,
                 dimensions: Sequence[str] = DIMENSION_ORDER,
                 gate_dimensions: Sequence[str] | None = None) -> StabilityReport:
    """Degerlendirici -> soru -> boyut -> etiket yapisindan PSS raporu uretir.

    `kind`:
      "intra" -> degerlendiriciler AYNI istemin tekrarlaridir
      "inter" -> degerlendiriciler anlamca ESDEGER istem varyantlaridir
    """
    raters = sorted(labels_by_rater)
    item_ids: list[str] = sorted({qid for r in raters for qid in labels_by_rater[r]})
    # Kapiya giren boyutlar: acikca verilmediyse uretim kumesi, ama yalnizca
    # gercekten olculen boyutlarla kesistirilir (cagiran alt kume verebilir).
    gd = tuple(gate_dimensions) if gate_dimensions is not None else PRODUCTION_DIMENSIONS
    gd = tuple(d for d in gd if d in dimensions)
    rep = StabilityReport(kind=kind, prompt_version=prompt_version,
                          n_items=len(item_ids), n_raters=len(raters),
                          gate=gate, solid_threshold=solid, gate_dimensions=gd)
    for dim in dimensions:
        units = []
        for qid in item_ids:
            row = [labels_by_rater[r].get(qid, {}).get(dim) for r in raters]
            units.append(row)
        rep.alpha[dim] = krippendorff_alpha(units)
        rep.raw_agreement[dim] = pairwise_agreement(units)
        rep.degenerate[dim] = alpha_is_degenerate(units)
        if rep.degenerate[dim]:
            rep.notes.append(
                f"{dim}: tum degerlendiriciler tek etiket kullandi; alpha 1,0 "
                "dondu ama bu 'boyut ayirim yapmiyor' anlamina da gelebilir.")
        # YAYGINLIK (prevalence) PARADOKSU: cok carpik bir etiket dagiliminda
        # ham uyum yuksek kalirken alpha sifira hatta eksiye duser. Bulgu 4 bunu
        # dolayli olarak uyarir ("%54,1 sans-duzeltmesiz ham yuzde, kappa ile
        # kiyaslanamaz"). Kapi yine de alpha'ya bakar — ama rapor bu durumu
        # AYRICA gostermek zorundadir, yoksa "istem bozuk" diye yanlis yorumlanir.
        a, ra = rep.alpha[dim], rep.raw_agreement[dim]
        if (not rep.degenerate[dim] and a == a and ra == ra
                and ra >= 0.90 and a < gate):
            rep.notes.append(
                f"{dim}: ham uyum {ra:.2f} yuksek fakat alpha {a:.2f} dusuk — "
                "YAYGINLIK PARADOKSU (etiket dagilimi cok carpik). Kapi yine de "
                "kapalidir; cozum istemi revize etmek ya da bu boyutun "
                "kategorilerini yeniden tanimlamaktir.")
    return rep
