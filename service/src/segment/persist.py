"""Segmentasyon çıktısını ZEKA deposuna taşıyan **tek** köprü.

---------------------------------------------------------------------------
NEDEN BU DOSYA BİR İSTİSNA
---------------------------------------------------------------------------
`src/segment/` paketi, `src/` altındaki ZEKA borusundan bilinçli olarak
ayrıdır (bkz. `segment/__init__.py`). Bu dosya o kuralın **tek** istisnasıdır
ve istisna olduğu için ayrı bir modüldür: `runner.py`, `labelers.py`,
`validate.py` hâlâ hiçbir şey bilmez. Yön de tek taraflıdır — `compute/` ve
`store/` bu paketten hiçbir şey içe aktarmaz.

Köprünün yaptığı dört şey:
  1. `LabelBatch` → `QuestionSegment` (soru başına etiket satırı),
  2. etiket + ham cevap → `StudentSegmentProfile` (öğrenci × boyut × etiket),
  3. profil + kohort referansı → segment tabanlı `Recommendation` satırları,
  4. üçünü de `Store` üzerinden UPSERT.

Kural motorunun burada çağrılmasının sebebi ölçüsel: segment kuralları kohort
ortalamasına göre ateşler ve o ortalama ancak BÜTÜN öğrenciler hesaplandıktan
sonra bilinir. Tek öğrenci işleyen gece koşusu (`pipeline.run_school`) bu sayıyı
üretemez; bu yüzden `for_student(segment_profile=...)` yüzeyi de açık durur ama
referansı hazır elde olan taraf burasıdır.

Yazım **isteğe bağlıdır**: `runner.run(..., persist=True)` ya da CLI'da
`--persist`. Varsayılan davranış değişmez; bayrak verilmezse tek bir SurrealQL
ifadesi bile çalışmaz.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from ..compute.model import (
    Confidence,
    QuestionSegment,
    StudentSegmentProfile,
)
from ..compute.recommend import for_student_segments
from ..compute.segments import (
    CONFIDENCE_STABLE_N,
    PRODUCTION_DIMENSIONS,
    profile_payload,
    reference_contrasts,
    student_profiles,
)
from ..store import Store, SurrealHttpClient
from .config import SegmentConfig, log
from .labelers import LabelBatch
from .rubric import DIMENSION_ORDER, EXPERIMENTAL_DIMENSIONS
from .schema import ItemSegmentation

#: Etiket güveni bu değerin altındaysa satır 'exploratory' kalır. Ölçüm değil,
#: `schema.py`'nin [0,1] sözleşmesi üzerinde muhafazakâr bir bölme: modelin
#: kendi güveni kalibre EDİLMEMİŞTİR, bu yüzden yalnız iki kademe üretilir ve
#: 'stable' için yüksek bir eşik istenir.
QUESTION_CONFIDENCE_STABLE = 0.85


@dataclass
class PersistReport:
    """Yazım muhasebesi — koşu raporuna aynen basılır."""

    school: str = ""
    question_rows: int = 0
    question_written: int = 0
    profile_rows: int = 0
    profile_written: int = 0
    recommendation_rows: int = 0
    recommendation_written: int = 0
    recommendation_rejected: int = 0
    students: int = 0
    answers_matched: int = 0
    skipped_batches: int = 0
    dry_run: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "okul": self.school,
            "question_segment_satir": self.question_rows,
            "question_segment_yazilan": self.question_written,
            "student_segment_profile_satir": self.profile_rows,
            "student_segment_profile_yazilan": self.profile_written,
            "recommendation_satir": self.recommendation_rows,
            "recommendation_yazilan": self.recommendation_written,
            "recommendation_reddedilen": self.recommendation_rejected,
            "ogrenci": self.students,
            "eslesen_cevap": self.answers_matched,
            "atlanan_grup": self.skipped_batches,
            "kuru_kosu": self.dry_run,
            "notlar": self.notes,
        }


# ---------------------------------------------------------------------------
# Dönüşüm
# ---------------------------------------------------------------------------


def _row_confidence(seg: ItemSegmentation) -> Confidence:
    """Satır düzeyi güven kademesi — ÜRETİM boyutlarının en düşük güveni.

    Deneysel boyut (`adim_sayisi`) kademeye girmez: aşağı akışta
    kullanılmadığı için onun belirsizliği satırın kullanılabilirliğini
    etkilemez.
    """
    values = [
        seg.labels[d].confidence for d in PRODUCTION_DIMENSIONS if d in seg.labels
    ]
    if not values:
        return Confidence.NONE
    return (
        Confidence.STABLE
        if min(values) >= QUESTION_CONFIDENCE_STABLE
        else Confidence.EXPLORATORY
    )


def question_segments(
    batch: LabelBatch,
    items: Sequence[dict],
    *,
    school: str,
    now_ms: int,
) -> list[QuestionSegment]:
    """`LabelBatch` → `QuestionSegment` listesi.

    Etiketlenemeyen madde (`batch.failures`) satır ÜRETMEZ: doğrulanamayan
    yanıt sessizce kabul edilmez kuralı depoda da geçerlidir.
    """
    meta = {i["question_id"]: i for i in items}
    out: list[QuestionSegment] = []
    for question_id, seg in sorted(batch.results.items()):
        item = meta.get(question_id) or {}
        trap = None
        if seg.trap_choice_index is not None:
            # Şık kimliği varsa o, yoksa metin. `items_enriched.json` şık
            # kimliklerini `distractor_distribution` içinde taşır.
            choices = item.get("distractor_distribution") or []
            if 0 <= seg.trap_choice_index < len(choices):
                trap = choices[seg.trap_choice_index].get("choice_id")
            trap = trap or seg.trap_choice_text
        out.append(
            QuestionSegment(
                school=school,
                question=question_id,
                exam=item.get("exam"),
                course=item.get("course"),
                subject=item.get("subject"),
                labels={d: seg.labels[d].label for d in DIMENSION_ORDER},
                confidences={
                    d: seg.labels[d].confidence for d in DIMENSION_ORDER
                },
                rationale=seg.rationale,
                model=seg.model or batch.model,
                prompt_version=seg.prompt_version or batch.prompt_version,
                variant=seg.variant or batch.variant,
                trap_choice=trap,
                downstream_dimensions=tuple(PRODUCTION_DIMENSIONS),
                experimental_dimensions=tuple(EXPERIMENTAL_DIMENSIONS),
                computed_at=now_ms,
                confidence=_row_confidence(seg),
            )
        )
    return out


def segment_profiles(
    batch: LabelBatch,
    answers: Sequence[tuple[str, str, str | None]],
    items: Sequence[dict],
    *,
    school: str,
    now_ms: int,
) -> tuple[list[StudentSegmentProfile], int]:
    """Etiket × cevap → öğrenci profilleri. `(profiller, eşleşen_cevap)`.

    Yalnız ÜRETİM boyutları profile girer (`PRODUCTION_DIMENSIONS`); deneysel
    boyut `question_segment` satırında kalır.
    """
    labels = {
        qid: {d: seg.labels[d].label for d in PRODUCTION_DIMENSIONS}
        for qid, seg in batch.results.items()
    }
    key_by_question = {
        i["question_id"]: i.get("correct_choice_id") for i in items
    }

    by_student: dict[str, list[tuple[str, int]]] = {}
    matched = 0
    for question, student, selected in answers:
        if selected is None or question not in labels:
            continue
        key = key_by_question.get(question)
        if not key:
            continue
        by_student.setdefault(student, []).append(
            (question, 1 if selected == key else 0)
        )
        matched += 1

    out: list[StudentSegmentProfile] = []
    for student, rows in sorted(by_student.items()):
        out.extend(student_profiles(school, student, rows, labels, now_ms))
    return out, matched


# ---------------------------------------------------------------------------
# Yazım
# ---------------------------------------------------------------------------


def school_slug(cfg: SegmentConfig, override: str | None = None) -> str:
    """Okul slug'ı: açık değer > tohum manifestosu > 'bilinmeyen'.

    Slug yanlışsa satırlar başka bir kiracının altına düşerdi; bu yüzden
    uydurulmaz, manifestodan okunur.
    """
    if override:
        return override
    path = Path(cfg.manifest_path)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        slug = data.get("school_slug")
        if slug:
            return str(slug)
    return "bilinmeyen"


def build_client(
    url: str, *, namespace: str, database: str, user: str, password: str
) -> SurrealHttpClient:
    """Depo istemcisi. `store.py` ile aynı istemci — ikinci bir yol yok."""
    client = SurrealHttpClient(
        url, namespace=namespace, database=database, user=user, password=password
    )
    client.ensure_namespace()
    return client


async def persist(
    batch: LabelBatch,
    items: Sequence[dict],
    answers: Sequence[tuple[str, str, str | None]],
    *,
    school: str,
    now_ms: int,
    store: Store | None,
) -> PersistReport:
    """Dönüştür ve yaz. `store=None` ise yalnız sayar (kuru koşu)."""
    report = PersistReport(school=school, dry_run=store is None)
    questions = question_segments(batch, items, school=school, now_ms=now_ms)
    profiles, matched = segment_profiles(
        batch, answers, items, school=school, now_ms=now_ms
    )
    report.question_rows = len(questions)
    report.profile_rows = len(profiles)
    report.answers_matched = matched
    report.students = len({p.student for p in profiles})

    # Referans kontrastları yazıma GİRMEZ: satır öğrencinin kendi ölçüsünü
    # taşır, kohort ortalaması her koşuda yeniden hesaplanır. Yine de rapora
    # yazılır ki eşiklerin hangi zemine oturduğu görülsün.
    reference = reference_contrasts(profiles)
    report.notes.append(
        "referans kontrastlar (kohort ortalamasi): "
        + json.dumps(reference, ensure_ascii=False)
    )
    stable = sum(1 for p in profiles if p.n_answers >= CONFIDENCE_STABLE_N)
    report.notes.append(
        f"n>={CONFIDENCE_STABLE_N} olan profil satiri: {stable}/{len(profiles)}"
    )

    # --- Segment tabanli tavsiyeler ---------------------------------------
    # Kural motoru buradan cagrilir, cunku profilin kohort referansi ancak
    # BUTUN ogrenciler hesaplandiktan sonra bilinir; tek ogrenci isleyen gece
    # kosusu bu sayiyi uretemez.
    #
    # SINIF KURALI (`T3.segment_class_gap`) BURADA URETILMEZ: sube uyeligi ve
    # ders ogretmeni `Source` arayuzunden gelir, segmentasyon hattinin elinde
    # yoktur. Ogretmeni cozulemeyen bir madde uretilmez ([T§5.3]); uydurmak
    # yerine uretilmiyor. Cagiran taraf bu veriye sahipse
    # `compute.recommend.for_class_segments` dogrudan kullanilabilir.
    recommendations = []
    by_student: dict[str, list[StudentSegmentProfile]] = {}
    for profile in profiles:
        by_student.setdefault(profile.student, []).append(profile)
    for student, rows in sorted(by_student.items()):
        recommendations.extend(
            for_student_segments(
                school, student, profile_payload(rows, reference), now_ms
            )
        )
    report.recommendation_rows = len(recommendations)

    if store is None:
        log("info", "kuru kosu: hicbir sey yazilmadi "
                    f"({report.question_rows} soru, {report.profile_rows} profil)")
        return report

    q_report = await store.write_question_segments(questions)
    p_report = await store.write_segment_profiles(profiles)
    r_report = await store.write_recommendations(recommendations)
    report.question_written = q_report.written
    report.profile_written = p_report.written
    report.recommendation_written = r_report.written
    report.recommendation_rejected = r_report.rejected
    report.skipped_batches = (
        q_report.skipped_batches
        + p_report.skipped_batches
        + r_report.skipped_batches
    )
    log("info", f"depo: question_segment={report.question_written} "
                f"student_segment_profile={report.profile_written} "
                f"recommendation={report.recommendation_written} "
                f"atlanan_grup={report.skipped_batches}")
    return report
