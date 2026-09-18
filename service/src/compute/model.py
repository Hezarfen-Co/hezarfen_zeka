"""Hesap modüllerinin paylaştığı çıktı tipleri. Hiçbir I/O yapmaz.

Kaynak: `spec/MODULLER.md` §2.0 `insight::model` künyesi.

Üç yapısal karar burada, tip düzeyinde sabitlenir:

1. **"zayıf" kelimesi tip düzeyinde yoktur.** `Band.REVIEW` ("tekrar önerilir")
   vardır. `MODULLER.md` §2.0 kararı, `[T§3 Ö1]` sınırlaması.
2. **Tek bir risk skoru alanı yoktur.** `AttentionItem` tek bir tetikleyici
   taşır; toplam, ağırlık, sıra numarası alanı **bulunmaz**
   (`MODULLER.md` §2.8, `[T§6.6]` madde 2).
3. **Kanıtsız tavsiye kurulamaz.** `Recommendation` `evidence`'ı zorunlu alır ve
   boşsa `ValueError` atar — bu bir assert değil, bir **tip kısıtıdır**
   (`MODULLER.md` §2.10 yapısal kural 1, `[T§6.3]`).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

# Kural kataloğunun sürümü. Artırıldığında kullanıcıya "bu bölümün hesaplama
# yöntemi güncellendi" gösterilir — sessiz değişiklik yasak
# (`MODULLER.md` §2.10 yapısal kural 5, `[T§6.4]` madde 3).
RULE_VERSION = 1


class Band(enum.StrEnum):
    """Konum bandı. Üç bant + veri yok (`[T§3 Ö1]`, `MODULLER.md` §2.3 adım 4).

    Sayısal skor, yüzdelik dilim ve sıralama **üretilmez**.
    """

    REVIEW = "review"  # "tekrar önerilir" — "zayıf" DEĞİL
    ON_TRACK = "on_track"  # "sınıf düzeyinde"
    STRONG = "strong"  # "güçlü"
    INSUFFICIENT_DATA = "insufficient_data"  # "yeterli veri yok"


class Confidence(enum.StrEnum):
    """Güven kademesi (`MODULLER.md` §0 kural 3, `[L-5]` Linacre 1994).

    `EXPLORATORY` = ön bulgu, `STABLE` = kararlı. Eşikler ölçüye göre değişir;
    her modül kendi eşiğini kendi künyesinden alır.
    """

    NONE = "none"
    EXPLORATORY = "exploratory"
    STABLE = "stable"


class TriggerKind(enum.StrEnum):
    """Dikkat listesi tetikleyicileri (`MODULLER.md` §2.8 tablosu).

    `EXAM_MISSED` bu sürümde **hiç ateşlenemez**: `Source` arayüzünde sınav
    takvimi ve `exam_attempt` yok. Sabit, belgeyle hizayı korumak ve
    "unutuldu mu" sorusunu kapatmak için duruyor; `attention.py` onu
    üretmediğini açıkça raporlar.
    """

    ATTENDANCE = "attendance"
    HOMEWORK = "homework"
    MARK_TREND = "mark_trend"
    EXAM_MISSED = "exam_missed"


class Audience(enum.StrEnum):
    """Tavsiyenin hangi rol tarafından görülebileceği (`[T§6.8]` tablosu).

    T4 maddeleri **yalnız** `TEACHER` taşır: dikkat listesi öğrenciye ve veliye
    gösterilmez.
    """

    STUDENT = "student"
    TEACHER = "teacher"
    PARENT = "parent"
    MANAGER = "manager"


@dataclass(frozen=True, slots=True)
class AttentionItem:
    """Dikkat listesinin **tek** maddesi — tek tetikleyici, tek olgu.

    Bilerek **yok olan alanlar**: `score`, `weight`, `rank`, `severity`.
    Bir madde diğerinden "daha acil" değildir; liste sıralanmaz
    (`[T§6.6]` madde 2: sıralama damgalama doğurur).
    """

    student: str
    trigger: TriggerKind
    # Olgu cümlesi. Yargı değil, olgu: "son 30 günde 4 ödev teslim edilmedi".
    # "risk" kelimesi üründe geçmez (`[T§6.6]` madde 1).
    fact: str
    evidence: dict[str, Any]
    window_from: int
    window_to: int

    def __post_init__(self) -> None:
        if not self.evidence:
            raise ValueError("kanıtsız dikkat maddesi üretilemez (T§6.6 madde 4)")


@dataclass(frozen=True, slots=True)
class Recommendation:
    """Üretilmiş tek tavsiye. Kanıtsız kurulamaz.

    Zorunlu alanlar (`MODULLER.md` §2.10 çıktı künyesi):
    kime (`audience`), kim hakkında (`about`), hangi ürün (`product`),
    hangi kural (`rule_id` + `rule_version`), hangi olgu (`evidence`),
    ne zaman hesaplandı (`computed_at`), ne zaman düşer (`expires_at`).
    """

    school: str
    audience: str
    audience_role: Audience
    product: str
    rule_id: str
    evidence: dict[str, Any]
    computed_at: int
    expires_at: int
    about: str | None = None
    course: str | None = None
    confidence: Confidence = Confidence.EXPLORATORY
    rule_version: int = RULE_VERSION
    # Kayıt anahtarının ayırt edici son parçası. `course`/`about` yetmediğinde
    # kullanılır: bir kural aynı kişi için birden çok **kapsamda** ateşleyebilir
    # (örn. "analiz segmenti" ve "yüksek okuma yükü segmenti" ayrı satırlardır).
    # Şemadaki anahtar deseni zaten `..._{rule_id}[_{scope}]` diyor.
    # SATIRA YAZILMAZ: yalnız anahtar bileşenidir, içeriği `evidence`'ta durur.
    scope: str | None = None
    # Beş bölümlü "Neden?" metninin `Sınır` satırı: neyin dahil OLMADIĞI.
    # Bu satır olmadan ürün, olduğundan çok şey bildiğini ima eder
    # (`MODULLER.md` §2.10 yapısal kural 2, `[T§6.3]`).
    limitation: str = ""

    def __post_init__(self) -> None:
        if not self.evidence:
            raise ValueError(
                f"kanıtsız tavsiye üretilemez: rule_id={self.rule_id} "
                "(MODULLER.md §2.10 yapısal kural 1)"
            )
        if not self.rule_id:
            raise ValueError("rule_id zorunlu (T§6.4 madde 3)")
        if not self.limitation:
            raise ValueError(
                f"'Sınır' satırı zorunlu: rule_id={self.rule_id} (T§6.3)"
            )

    def record_key(self) -> str:
        """Kompozit kayıt anahtarı → yazma idempotenttir, çoğaltma olmaz.

        `MODULLER.md` §2.11 adım 1: kompozit anahtar tekilliği yapısal kılar.

        ⚠️ `about` anahtarın **ayrı bir parçasıdır** ve bu süs değildir.
        Öğretmene giden kurallar (T3, T4) öğrenci başına bir kez ateşler:
        bir öğretmen, bir kural, bir ders altında otuz öğrenci. Anahtar
        `scope or course or about` biçiminde tek bir yuvaya sıkıştırıldığında
        otuzu da aynı anahtarı üretiyordu; son yazılan tutuluyor, öğretmen
        **tek öğrenci** görüyor ve yirmi dokuzu hiçbir yerde hata vermeden
        kayboluyordu. Ölçüldü: beş öğrenci → bir anahtar.

        Kapsam (`scope`) kuralın kendi ayrımıdır — segment etiketi gibi —
        ve öğrencinin yerine geçemez.
        """
        scope = self.scope or self.course or "-"
        about = self.about or "-"
        return (
            f"{self.school}_{self.audience}_{self.product}_{self.rule_id}"
            f"_{about}_{scope}"
        )


@dataclass(slots=True)
class StudentSummary:
    """Bir öğrencinin gecelik özeti — `student_summary` tablosunun karşılığı."""

    school: str
    student: str
    computed_at: int
    #: Dört modül `None` OLABİLİR: `sections` ile istenmeyen modül hesaplanmaz
    #: ve satıra `null` gider ("hesaplanmadı"), boş sözlük ise "okundu, kaynak
    #: satır yok" demektir (backend `db/insight.rs` `SummaryRow` sözleşmesi).
    marks: dict[str, Any] | None = field(default_factory=dict)
    attendance: dict[str, Any] | None = field(default_factory=dict)
    submission: dict[str, Any] | None = field(default_factory=dict)
    study: dict[str, Any] | None = field(default_factory=dict)
    attention: list[dict[str, Any]] = field(default_factory=list)
    confidence: Confidence = Confidence.NONE

    def record_key(self) -> str:
        return f"{self.school}_{self.student}"


# ---------------------------------------------------------------------------
# Segmentasyon çıktısının tipleri
# ---------------------------------------------------------------------------
#
# Bu iki tip `service/src/segment/` hattının ürettiği etiketleri ZEKA'nın kendi
# veritabanına taşınabilir hale getirir (`schema/zeka.surql` §4 ve §5).
# `segment/` paketi bu dosyayı **içe aktarmaz**: dönüşümü yapan tek yer
# `segment/persist.py` köprüsüdür, yön tek taraflıdır.


@dataclass(frozen=True, slots=True)
class QuestionSegment:
    """Bir sorunun bilişsel segment etiketi — `question_segment` karşılığı.

    Kişisel veri **değildir**: satır bir soru hakkındadır.
    `labels` ve `confidences` boyut adına göre anahtarlanır; boyut kümesi
    `segment/rubric.py`'den gelir ve burada sabitlenmez — rubrik bir boyutu
    deneysele indirdiğinde bu tipin değişmesi gerekmesin diye.
    """

    school: str
    question: str
    labels: dict[str, str]
    confidences: dict[str, float]
    rationale: str
    model: str
    prompt_version: str
    computed_at: int
    exam: str | None = None
    course: str | None = None
    subject: str | None = None
    trap_choice: str | None = None
    variant: str | None = None
    #: Aşağı akışta (öğrenci profili, tavsiye) KULLANILAN boyutlar.
    downstream_dimensions: tuple[str, ...] = ()
    #: Etiketlenen ama aşağı akışa GİRMEYEN boyutlar. İkisi de satıra yazılır:
    #: "bu boyut kullanılmıyor" bilgisi veriden okunabilsin diye.
    experimental_dimensions: tuple[str, ...] = ()
    confidence: Confidence = Confidence.EXPLORATORY

    def __post_init__(self) -> None:
        if not self.labels:
            raise ValueError("etiketsiz question_segment üretilemez")
        missing = set(self.labels) - set(self.confidences)
        if missing:
            raise ValueError(
                f"boyut başına güven zorunlu; eksik: {sorted(missing)}"
            )
        if not self.rationale:
            # `segment/schema.py` zaten boş gerekçeyi reddediyor; burada ikinci
            # kez kontrol edilir çünkü satır sözlükten de kurulabilir.
            raise ValueError("gerekçesiz question_segment üretilemez")

    def record_key(self) -> str:
        return f"{self.school}_{self.question}"


@dataclass(frozen=True, slots=True)
class StudentSegmentProfile:
    """Öğrenci × boyut × etiket performansı — `student_segment_profile`.

    **`contrast` bu tipin var olma sebebidir.** Ham `accuracy` öğrencinin genel
    yeteneğini yansıtır ve ayrım gücü yoktur: iyi öğrenci her segmentte yüksek
    çıkar. `contrast = accuracy - overall_accuracy` genel düzeyi sadeleştirir;
    geriye segmentin kendisine özgü sapma kalır. Kurallar **yalnız** kontrastı
    okur (`recommend.py` SEG.* kuralları).
    """

    school: str
    student: str
    dimension: str
    label: str
    n_answers: int
    n_correct: int
    overall_n_answers: int
    overall_accuracy: float
    computed_at: int
    confidence: Confidence = Confidence.EXPLORATORY

    def __post_init__(self) -> None:
        if self.n_answers <= 0:
            raise ValueError("n_answers pozitif olmalı (bölme tanımsız olurdu)")
        if not 0 <= self.n_correct <= self.n_answers:
            raise ValueError("n_correct, n_answers aralığının dışında")

    @property
    def accuracy(self) -> float:
        return self.n_correct / self.n_answers

    @property
    def contrast(self) -> float:
        """Dürüst ölçü: segment doğruluğu − öğrencinin kendi genel doğruluğu."""
        return self.accuracy - self.overall_accuracy

    def record_key(self) -> str:
        return f"{self.school}_{self.student}_{self.dimension}_{self.label}"


# --- Crockford base32 ULID zaman çözümü -------------------------------------
#
# `spec/schema.json` → `id_rules.exam` ve `id_rules.homework`:
# "ulid_monotonic — ms-monotonic ULID, 26 chars Crockford base32".
# ULID'in ilk 10 karakteri 48 bitlik unix-ms damgasıdır. Bu, `MarkEntry`'de
# **hiç zaman damgası olmaması** sorununun tek dürüst çözümüdür.
#
# ⚠️ SINIR: çözülen damga sınavın/ödevin **oluşturulma** anıdır; öğrencinin
# sınava girme anı değildir. `MODULLER.md` §2.8 "zaman çapası" bölümü aynı
# ayrımı yapıyor ve not eğilimi için oturum sırasının yeterli olduğunu
# söylüyor. Eğilim hesabı bu sıralamaya dayanır, mutlak tarihe değil.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_CROCKFORD_INDEX = {c: i for i, c in enumerate(_CROCKFORD)}


def ulid_ms(record_id: str) -> int | None:
    """ULID'in zaman bölümünü unix-ms olarak çözer; ULID değilse `None`.

    Kimlik `table:key` biçiminde gelebilir — ayrıştırılır.
    """
    if not record_id:
        return None
    key = record_id.split(":", 1)[-1]
    if len(key) != 26:
        return None
    ts = 0
    for ch in key[:10].upper():
        idx = _CROCKFORD_INDEX.get(ch)
        if idx is None:
            return None
        ts = ts * 32 + idx
    return ts
