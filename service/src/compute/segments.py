"""Segment profili hesabı: etiketli sorular × öğrenci cevapları → kontrast.

Kaynak: `service/docs/SEGMENT-CIKTI.md` (ölçüm), `schema/zeka.surql` §5.

Bu modül `compute/` sözleşmesine uyar: **ağ yok, veritabanı yok, dosya yok.**
Girdi bellekteki sözlükler, çıktı `model` tipleri ve sözlükler.

---------------------------------------------------------------------------
ÜÇ ÖLÇÜ, ÜÇÜ DE FARKLI ŞEY SÖYLER
---------------------------------------------------------------------------

1. **`accuracy`** — öğrencinin bu segmentteki doğruluk oranı.
   *Ayrım gücü yoktur.* İyi öğrenci her segmentte yüksek, zayıf öğrenci her
   segmentte düşük çıkar. Tek başına **hiçbir kural ateşlemez**.

2. **`contrast = accuracy − overall_accuracy`** — öğrencinin bu segmentteki
   doğruluğu eksi kendi genel doğruluğu. Öğrencinin genel düzeyi bu farkta
   sadeleşir. Satıra yazılan ölçü budur.

3. **`relative = contrast − reference_contrast`** — kontrastın **kohort
   ortalamasından** sapması. Kural eşikleri **buna** bakar, ham kontrasta
   değil, çünkü kontrast hâlâ **madde zorluğunu** taşır: analiz soruları
   herkes için zordur, dolayısıyla neredeyse her öğrencinin `analiz`
   kontrastı negatiftir. Referansı çıkarmak madde etkisini siler; geriye
   öğrenciye özgü sapma kalır.

   Bu tam olarak `docs/DESEN-DOGRULAMA.md` §5'teki "kontrole göre" sütununun
   hesabıdır (fark-farkları). Orada referans kontrol grubuydu; üretimde kimin
   kontrol olduğu bilinmediği için **kohortun tamamı** referans alınır.

Eşikler uydurulmadı: `docs/SEGMENT-CIKTI.md` §3'te tohum verisinde ölçülen
kontrol dağılımından türetildi.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

from .model import Confidence, StudentSegmentProfile

# ---------------------------------------------------------------------------
# Boyut kümesi
# ---------------------------------------------------------------------------
#
# `segment/rubric.py` ile birebir aynı olmak ZORUNDA, ama bu paket onu **içe
# aktarmaz**: `compute/` bağımsız kalır (README: "hiçbir modül ağ çağrısı
# yapmaz, veritabanı görmez"). Sapma sessiz kalmasın diye
# `tests/test_segments.py::TestRubricUyumu` iki tarafı karşılaştırır ve
# ayrıldıkları anda testi düşürür.

#: Aşağı akışta kullanılan boyutlar → izinli etiketler.
PRODUCTION_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "bilissel_talep": ("hatirlama", "uygulama", "analiz"),
    "dikkat_tuzagi": ("var", "yok"),
    "okuma_yuku": ("dusuk", "yuksek"),
}

#: Etiketlenen ama öğrenci profiline **girmeyen** boyutlar (rubric.py'de
#: `experimental=True`). Burada yalnızca "neden yok" sorusunu kapatmak için
#: listelenir.
EXPERIMENTAL_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "adim_sayisi": ("tek_adim", "cok_adim"),
}

# ---------------------------------------------------------------------------
# Güven kapısı ve eşikler — hepsi ÖLÇÜLMÜŞ
# ---------------------------------------------------------------------------

#: Bir segmentte kural ateşlenebilmesi için gereken **asgari cevap sayısı**.
#:
#: 100, `[L-5]` Linacre'ın "stable" eşiğiyle aynı sayıdır — projede
#: `question_stat` için de aynı sınır kullanılıyor. Tohum verisinde ölçülen
#: (`docs/SEGMENT-CIKTI.md` §3 kapı taraması):
#:   * n >= 200 yapılırsa `bilissel_talep=analiz` segmenti **hiç** ateşlemez
#:     (analiz maddesi azdır, medyan n = 178) — yani kural ölür.
#:   * n >= 150 yapılırsa okuma güçlüğü arketipi tümüyle kaybolur: o öğrenciler
#:     zor maddeleri **boş bırakır**, boş madde paydaya girmez, n düşer.
#: 100 bu iki duvarın arasında ölçülerek seçildi.
MIN_ANSWERS_PER_SEGMENT = 100

#: Güven kademesi eşikleri ([L-5] Linacre 1994 deseni: `question_stat`
#: n>=30 'exploratory', n>=100 'stable'). Segment profili aynı sözlüğü
#: kullanır; ama **kural ateşlemesi** için `MIN_ANSWERS_PER_SEGMENT` gerekir,
#: yani 'exploratory' bir satır depoda durur, kural üretmez.
CONFIDENCE_EXPLORATORY_N = 30
CONFIDENCE_STABLE_N = 100

#: Göreli kontrast eşikleri (boyut başına, negatif yön = öğrenci geride).
#:
#: KURAL: eşik = kontrol grubunun **ortalaması − 2·SD**, o boyutun en geniş
#: dağılımlı etiketi üzerinden (muhafazakâr taraf). Ölçülen değerler
#: (`docs/SEGMENT-CIKTI.md` §3, n = 182 kontrol öğrencisi):
#:   bilissel_talep / analiz : ort −0,0012  SD 0,0392 → −0,0797
#:   dikkat_tuzagi  / var    : ort +0,0076  SD 0,0199 → −0,0322
#:   okuma_yuku     / yuksek : ort +0,0026  SD 0,0315 → −0,0604
#:
#: Katsayı 2 **önceden seçildi**, veriye bakılarak ayarlanmadı: tek yönlü 2·SD
#: kuyruğu segment başına ~%2,3 yanlış pozitif bekletir. Ölçülen yanlış pozitif
#: bu beklentiyle uyumludur (§4). Katsayıyı 2,5'e çıkarmak yanlış pozitifi
#: 10 satırdan 1'e indiriyor ama ezberci arketibinin duyarlılığını 0,72'den
#: 0,39'a düşürüyordu; seçim ölçülerek yapıldı ve iki yön de §4'te yazılıdır.
RELATIVE_CONTRAST_GATE: dict[str, float] = {
    "bilissel_talep": -0.080,
    "dikkat_tuzagi": -0.032,
    "okuma_yuku": -0.060,
}

#: Sınıf düzeyi kuralın eşiği. Öğrenci eşiğiyle **aynı yöntem, farklı katsayı**:
#: sınıf ortalaması bireysel gürültüyü zaten küçülttüğü için dağılım dardır
#: (ölçülen sınıf-arası SD, en geniş segmentte 0,0127 — `SEGMENT-CIKTI.md` §5)
#: ve katsayı 2 yerine **3** alınır. Gerekçe ölçüm değil, maliyet: bu madde bir
#: öğretmene bütün bir sınıf hakkında bir şey söyler; yanlış olmasının bedeli
#: tek bir öğrenci kartından büyüktür.
#:   ortalama 0,0006 − 3 × 0,0127 = −0,0375 → dışa yuvarlanarak −0,040.
CLASS_RELATIVE_CONTRAST_GATE = -0.040
#: Sınıf kuralının kohort kapısı — `marks.py::CLASS_GAP` ile aynı ruh:
#: küçük kohortta ortalama anlamsızdır.
MIN_CLASS_STUDENTS = 8

#: "Kim aşağı akışta?" sorusunun tek cevabı.
DOWNSTREAM_DIMENSIONS: tuple[str, ...] = tuple(PRODUCTION_DIMENSIONS)

LIMITATION = (
    "Segment etiketleri sorunun METNİNDEN üretilir; öğrencinin neden yanlış "
    "yaptığı ölçülmez. Boş bırakılan maddeler paydaya girmez. Etiket bir dil "
    "modelinin çıktısıdır ve hatalıdır (ölçülen isabet: "
    "docs/SEGMENT-CIKTI.md §2)."
)


def confidence_for(n_answers: int) -> Confidence:
    """Cevap sayısından güven kademesi ([L-5] eşikleri)."""
    if n_answers >= CONFIDENCE_STABLE_N:
        return Confidence.STABLE
    if n_answers >= CONFIDENCE_EXPLORATORY_N:
        return Confidence.EXPLORATORY
    return Confidence.NONE


# ---------------------------------------------------------------------------
# Öğrenci profili
# ---------------------------------------------------------------------------


def student_profiles(
    school: str,
    student: str,
    answers: Sequence[tuple[str, int]],
    labels: dict[str, dict[str, str]],
    now_ms: int,
    *,
    dimensions: dict[str, tuple[str, ...]] | None = None,
) -> list[StudentSegmentProfile]:
    """Bir öğrencinin segment profilini üretir.

    `answers`: `(question_id, correct)` çiftleri; `correct` 0 veya 1.
    `labels`: `question_id -> {boyut: etiket}`.

    Etiketi olmayan soru **tümüyle atlanır** — hem segment paydasından hem de
    `overall` paydasından. Aksi halde kontrast, etiketlenmemiş soruların
    zorluğunu taşırdı ve karşılaştırma bozulurdu.
    """
    dims = dimensions or PRODUCTION_DIMENSIONS
    counts: dict[tuple[str, str], list[int]] = {}
    overall_n = 0
    overall_correct = 0
    for question, correct in answers:
        row = labels.get(question)
        if not row:
            continue
        marked = 0
        for dimension in dims:
            label = row.get(dimension)
            if label is None:
                continue
            bucket = counts.setdefault((dimension, label), [0, 0])
            bucket[0] += 1
            bucket[1] += int(bool(correct))
            marked += 1
        if marked:
            overall_n += 1
            overall_correct += int(bool(correct))

    if overall_n == 0:
        return []
    overall_accuracy = overall_correct / overall_n

    out: list[StudentSegmentProfile] = []
    for (dimension, label), (n, ok) in sorted(counts.items()):
        out.append(
            StudentSegmentProfile(
                school=school,
                student=student,
                dimension=dimension,
                label=label,
                n_answers=n,
                n_correct=ok,
                overall_n_answers=overall_n,
                overall_accuracy=overall_accuracy,
                computed_at=now_ms,
                confidence=confidence_for(n),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Referans (kohort) kontrastları
# ---------------------------------------------------------------------------


def reference_contrasts(
    profiles: Iterable[StudentSegmentProfile],
    *,
    min_answers: int = CONFIDENCE_EXPLORATORY_N,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Kohortun segment başına ortalama kontrastı ve saçılımı.

    Neden gerekli: `analiz` kontrastı **herkeste** negatiftir, çünkü analiz
    maddeleri herkes için zordur. Referans çıkarılmadan kurulan bir eşik tüm
    öğrencilerde ateşlerdi — yani hiçbir şey söylemezdi.

    `min_answers` altındaki satırlar referansa **girmez**: gürültüleri
    ortalamayı kaydırır.
    """
    buckets: dict[str, dict[str, list[float]]] = {}
    for profile in profiles:
        if profile.n_answers < min_answers:
            continue
        buckets.setdefault(profile.dimension, {}).setdefault(
            profile.label, []
        ).append(profile.contrast)

    out: dict[str, dict[str, dict[str, Any]]] = {}
    for dimension, labels in buckets.items():
        for label, values in labels.items():
            mean = sum(values) / len(values)
            sd = _sd(values, mean)
            out.setdefault(dimension, {})[label] = {
                "mean_contrast": round(mean, 4),
                "sd_contrast": round(sd, 4),
                "n_students": len(values),
            }
    return out


def _sd(values: Sequence[float], mean: float) -> float:
    if len(values) < 2:
        return 0.0
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var)


def relative_contrast(
    profile: StudentSegmentProfile,
    reference: dict[str, dict[str, dict[str, Any]]],
) -> float | None:
    """`contrast − kohort ortalaması`. Referans yoksa `None` (kural ateşlemez)."""
    row = (reference.get(profile.dimension) or {}).get(profile.label)
    if not row:
        return None
    return profile.contrast - float(row["mean_contrast"])


# ---------------------------------------------------------------------------
# Sınıf düzeyi toplama
# ---------------------------------------------------------------------------


def class_contrasts(
    profiles_by_class: dict[str, list[StudentSegmentProfile]],
    reference: dict[str, dict[str, dict[str, Any]]],
    *,
    min_answers: int = MIN_ANSWERS_PER_SEGMENT,
) -> dict[str, dict[str, dict[str, dict[str, Any]]]]:
    """`sınıf -> boyut -> etiket -> {n_students, mean_relative, ...}`.

    Sınıfın **topluca** bir segmentte geride olup olmadığı buradan okunur.
    Öğrenci başına göreli kontrast alınır, sonra sınıf içinde ortalanır: önce
    referans çıkarılmazsa madde zorluğu sınıf ortalamasında da kalırdı.
    """
    out: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
    for class_id, profiles in profiles_by_class.items():
        buckets: dict[tuple[str, str], list[float]] = {}
        for profile in profiles:
            if profile.n_answers < min_answers:
                continue
            rel = relative_contrast(profile, reference)
            if rel is None:
                continue
            buckets.setdefault((profile.dimension, profile.label), []).append(rel)
        for (dimension, label), values in sorted(buckets.items()):
            mean = sum(values) / len(values)
            out.setdefault(class_id, {}).setdefault(dimension, {})[label] = {
                "n_students": len(values),
                "mean_relative_contrast": round(mean, 4),
                "sd_relative_contrast": round(_sd(values, mean), 4),
            }
    return out


# ---------------------------------------------------------------------------
# Kural motorunun okuduğu biçim
# ---------------------------------------------------------------------------


def profile_payload(
    profiles: Sequence[StudentSegmentProfile],
    reference: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    """`recommend.py`'nin beklediği sözlük.

    `recommend` ham tablo okumaz, `Source` çağırmaz; bellekteki bu sözlüğü
    okur (`MODULLER.md` §2.10 girdi künyesi).
    """
    if not profiles:
        return {
            "dimensions": {},
            "overall": None,
            "limitation": LIMITATION,
            "gate": MIN_ANSWERS_PER_SEGMENT,
        }
    rows: dict[str, dict[str, Any]] = {}
    for profile in profiles:
        rel = relative_contrast(profile, reference)
        ref = (reference.get(profile.dimension) or {}).get(profile.label) or {}
        rows.setdefault(profile.dimension, {})[profile.label] = {
            "n_answers": profile.n_answers,
            "n_correct": profile.n_correct,
            "accuracy": round(profile.accuracy, 4),
            "contrast": round(profile.contrast, 4),
            "relative_contrast": None if rel is None else round(rel, 4),
            "reference_mean_contrast": ref.get("mean_contrast"),
            "reference_n_students": ref.get("n_students"),
            "confidence": str(profile.confidence),
            # Kapıyı geçiyor mu — kural motoru bunu tek tek yeniden hesaplamasın.
            "gate_passed": profile.n_answers >= MIN_ANSWERS_PER_SEGMENT,
        }
    first = profiles[0]
    return {
        "dimensions": rows,
        "overall": {
            "n_answers": first.overall_n_answers,
            "accuracy": round(first.overall_accuracy, 4),
        },
        "limitation": LIMITATION,
        "gate": MIN_ANSWERS_PER_SEGMENT,
        "experimental_dimensions": sorted(EXPERIMENTAL_DIMENSIONS),
    }
