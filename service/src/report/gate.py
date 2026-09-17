"""Rapor tipleri ve **yapısal kapı**.

---------------------------------------------------------------------------
NEDEN AYRI BİR MODÜL
---------------------------------------------------------------------------
`docs/CIKTI-SOZLESMESI.md` §5: `student_summary.attention[]` bir **öğretmen
aracıdır**; öğrenciye ve veliye gösterilmez (`[T§6.6]`). Aynı bölüm
`recommendation.audience_role = teacher` satırları için de aynı şeyi söyler.

Bu kural bir "sonradan filtre" olarak yazılsaydı — önce her şeyi oku, sonra
öğrenci raporunda ayıkla — kapının tutması **bir if satırının doğru yerde
kalmasına** bağlı olurdu. Bir refaktör, bir kopyala-yapıştır, yeni bir bölüm:
üçü de sızıntı üretir.

Burada kapı **tip düzeyindedir**:

1. Öğrenci raporunun okuduğu veri `StudentFacingSummary` tipindedir ve bu
   tipin `attention` diye bir **alanı yoktur**. Alan yoksa sızdırılamaz.
2. `StudentFacingSummary` ile `StaffSummary` arasında **kalıtım yoktur**.
   Kalıtım olsaydı `isinstance(staff, StudentFacing)` doğru dönerdi ve kapı
   kağıt üstünde kalırdı. İki bağımsız tip, tek yönlü dönüşüm.
3. Veri **okunurken** de kapı uygulanır: öğrenci raporu için üretilen satır izdüşümü
   ifadesinde `attention` sütunu **hiç geçmez** (`SUMMARY_COLUMNS_STUDENT`).
   Yani satır veritabanından bile çıkmaz.
4. `build_student_report` yalnız `StudentFacingBundle` kabul eder; personel
   demeti verilirse `TypeError` atar — çalışma anında da sessizce geçmez.

Testi: `tests/test_report.py::DikkatListesiKapisi`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any

#: CLI'nin kabul ettiği dört rapor tipi.
REPORT_TYPES: tuple[str, ...] = ("okul", "ogretmen", "ogrenci", "ham")

#: Öğrenciye/veliye giden tipler. Dikkat listesi bunlara **hiç yüklenmez**.
STUDENT_FACING_TYPES = frozenset({"ogrenci"})

#: Okul personeline (yönetim, öğretmen, teknik ekip) giden tipler.
STAFF_TYPES = frozenset({"okul", "ogretmen", "ham"})

#: Öğrenci raporunun okuduğu `student_summary` sütunları — `attention` YOK.
SUMMARY_COLUMNS_STUDENT: tuple[str, ...] = (
    "school",
    "student",
    "marks",
    "attendance",
    "submission",
    "study",
    "confidence",
    "computed_at",
)

#: Personel raporlarının okuduğu sütunlar — dikkat listesi burada.
SUMMARY_COLUMNS_STAFF: tuple[str, ...] = SUMMARY_COLUMNS_STUDENT + ("attention",)

#: Öğrenci raporunda gösterilebilecek `audience_role` değerleri.
STUDENT_FACING_ROLES = frozenset({"student"})

#: Personel raporlarında gösterilebilecek roller.
STAFF_ROLES = frozenset({"teacher", "manager"})


class ReportGateError(TypeError):
    """Kapıyı aşmaya çalışan bir çağrı — yapısal hata, veri hatası değil."""


# ---------------------------------------------------------------------------
# İki bağımsız özet tipi
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StudentFacingSummary:
    """Öğrenciye/veliye gösterilebilen özet. **`attention` alanı yoktur.**"""

    school: str
    student: str
    marks: dict[str, Any] = field(default_factory=dict)
    attendance: dict[str, Any] = field(default_factory=dict)
    submission: dict[str, Any] = field(default_factory=dict)
    study: dict[str, Any] = field(default_factory=dict)
    confidence: str = "none"
    computed_at: int = 0


@dataclass(frozen=True, slots=True)
class StaffSummary:
    """Personel özeti. Dikkat listesi **yalnız** burada taşınır.

    `StudentFacingSummary`'den türemez: kalıtım, kapının `isinstance`
    denetiminden sessizce geçmesine yol açardı.
    """

    school: str
    student: str
    marks: dict[str, Any] = field(default_factory=dict)
    attendance: dict[str, Any] = field(default_factory=dict)
    submission: dict[str, Any] = field(default_factory=dict)
    study: dict[str, Any] = field(default_factory=dict)
    attention: list[dict[str, Any]] = field(default_factory=list)
    confidence: str = "none"
    computed_at: int = 0


def _dict_field(row: dict[str, Any], key: str) -> dict[str, Any]:
    value = row.get(key)
    return value if isinstance(value, dict) else {}


def student_facing_summary(row: dict[str, Any]) -> StudentFacingSummary:
    """Ham satırdan öğrenciye gösterilebilir özet kurar.

    `row` içinde `attention` **olsa bile** taşınmaz: bu fonksiyon alanı
    okumaz, hedef tipte öyle bir alan da yoktur.
    """
    return StudentFacingSummary(
        school=str(row.get("school") or ""),
        student=str(row.get("student") or ""),
        marks=_dict_field(row, "marks"),
        attendance=_dict_field(row, "attendance"),
        submission=_dict_field(row, "submission"),
        study=_dict_field(row, "study"),
        confidence=str(row.get("confidence") or "none"),
        computed_at=int(row.get("computed_at") or 0),
    )


def staff_summary(row: dict[str, Any]) -> StaffSummary:
    """Ham satırdan personel özeti kurar."""
    attention = row.get("attention")
    return StaffSummary(
        school=str(row.get("school") or ""),
        student=str(row.get("student") or ""),
        marks=_dict_field(row, "marks"),
        attendance=_dict_field(row, "attendance"),
        submission=_dict_field(row, "submission"),
        study=_dict_field(row, "study"),
        attention=[i for i in (attention or []) if isinstance(i, dict)],
        confidence=str(row.get("confidence") or "none"),
        computed_at=int(row.get("computed_at") or 0),
    )


# ---------------------------------------------------------------------------
# İki bağımsız demet tipi
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StudentFacingBundle:
    """Öğrenci raporunun **tek** girdisi."""

    school: str
    student: str
    generated_at: int
    summary: StudentFacingSummary | None = None
    recommendations: list[dict[str, Any]] = field(default_factory=list)
    segment_profiles: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class StaffBundle:
    """Yönetim / öğretmen / teknik rapor girdisi."""

    school: str
    kind: str
    generated_at: int
    summaries: list[StaffSummary] = field(default_factory=list)
    recommendations: list[dict[str, Any]] = field(default_factory=list)
    segment_profiles: list[dict[str, Any]] = field(default_factory=list)
    runs: list[dict[str, Any]] = field(default_factory=list)
    question_segments: list[dict[str, Any]] = field(default_factory=list)
    #: Öğretmen raporunda kim için üretildiği; diğerlerinde `None`.
    teacher: str | None = None


def require_student_facing(bundle: Any) -> StudentFacingBundle:
    """Öğrenci raporu kurucularının ilk satırı. Personel demetini reddeder."""
    if not isinstance(bundle, StudentFacingBundle):
        raise ReportGateError(
            "öğrenci raporu yalnız StudentFacingBundle ile kurulur; "
            f"gelen: {type(bundle).__name__}. Dikkat listesi öğrenciye "
            "gösterilmez (CIKTI-SOZLESMESI.md §5)"
        )
    return bundle


def require_staff(bundle: Any) -> StaffBundle:
    """Personel raporu kurucularının ilk satırı."""
    if not isinstance(bundle, StaffBundle):
        raise ReportGateError(
            "personel raporu yalnız StaffBundle ile kurulur; "
            f"gelen: {type(bundle).__name__}"
        )
    return bundle


def summary_columns(kind: str) -> tuple[str, ...]:
    """Rapor tipine göre okunacak `student_summary` sütunları."""
    if kind in STUDENT_FACING_TYPES:
        return SUMMARY_COLUMNS_STUDENT
    if kind in STAFF_TYPES:
        return SUMMARY_COLUMNS_STAFF
    raise ValueError(f"bilinmeyen rapor tipi: {kind!r}")


def allowed_roles(kind: str) -> frozenset[str]:
    """Rapor tipine göre gösterilebilir `audience_role` kümesi."""
    if kind in STUDENT_FACING_TYPES:
        return STUDENT_FACING_ROLES
    if kind == "okul" or kind == "ham":
        return STAFF_ROLES | STUDENT_FACING_ROLES
    if kind == "ogretmen":
        return STAFF_ROLES
    raise ValueError(f"bilinmeyen rapor tipi: {kind!r}")


def has_attention_field(tipe: type) -> bool:
    """Bir tipte `attention` alanı var mı — kapı testinin okuduğu yardımcı."""
    return any(f.name == "attention" for f in fields(tipe))
