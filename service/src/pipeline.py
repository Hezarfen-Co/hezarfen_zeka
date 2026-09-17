"""Bir okul için uçtan uca hat: veri çek → hesapla → tavsiye üret → yaz.

Kaynak: `spec/MODULLER.md` §3 (gece işi hattı), §3.4 (kısmi başarısızlık),
§3.6 (süre bütçesi).

Akış:

```
öğrenci listesi
  └─ 1. geçiş: her öğrenci için Source'tan veri çek, ders/devam sayımlarını çıkar
  └─ kohort kur (şube × ders)          ← [L-6]: okul geneli havuz KULLANILMAZ
  └─ 2. geçiş: bant, teslim, çalışma, dikkat maddeleri, tavsiyeler
  └─ toplu yaz (student_summary + recommendation)
  └─ süpürme + insight_run kaydı
```

**Neden iki geçiş:** kohort dağılımı, o şube-dersteki *tüm* öğrencilerin
ortalamasına ihtiyaç duyar. Tek geçişte bant üretmek, kohortu bilmeden bant
üretmek demektir — `MODULLER.md` §0 kural 2'nin yasakladığı şey.

**Kısmi başarısızlık (`MODULLER.md` §3.4):** bir öğrenci düşerse hat devam
eder, sayaç artar; yazılmış satırlar geçerli kalır çünkü her satır kendi
başına tutarlıdır. **Bayat veri, yanlış veriden iyidir.**

**Bütçe:** okul başına süre bütçesi (`[T§5.3]`: 60 sn). Aşımda hat durur,
işlenmemiş öğrenciler `insight_run.pending_students`'a yazılır ve bir sonraki
koşu **oradan devam eder**.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from collections.abc import Callable
from typing import Any

from .compute import attendance as attendance_mod
from .compute import attention as attention_mod
from .compute import clock
from .compute import marks as marks_mod
from .compute import recommend as recommend_mod
from .compute import study as study_mod
from .compute import submission as submission_mod
from .compute.model import Confidence, Recommendation, StudentSummary
from .store import SchoolStore

log = logging.getLogger(__name__)

# `[T§5.3]` / `MODULLER.md` §3.6: okul başına 60 saniye.
DEFAULT_BUDGET_MS = 60_000


@dataclasses.dataclass(slots=True)
class RunResult:
    """`insight_run` satırının bellek karşılığı (`schema/zeka.surql` §3)."""

    school: str
    started_at: int
    finished_at: int | None = None
    status: str = "running"
    duration_ms: int | None = None
    students_total: int = 0
    students_ok: int = 0
    students_failed: int = 0
    students_skipped: int = 0
    rows_written: int = 0
    pending_students: list[str] = dataclasses.field(default_factory=list)
    failed_modules: list[str] = dataclasses.field(default_factory=list)
    budget_exceeded: bool = False
    budget_ms: int = DEFAULT_BUDGET_MS

    def run_key(self) -> str:
        """`{school}_{YYYY-MM-DD}` — TR tarihi (`MODULLER.md` §4.4)."""
        return f"{self.school}_{clock.tr_date_key(self.started_at)}"

    @property
    def write_failed(self) -> bool:
        """Depo yazması düştü mü?

        `pipeline.run_school` bir grup yazmayı atladığında `store` işaretini
        `failed_modules`'a koyar (bkz. aşağıda, yazma bölümü). Zamanlayıcı bu
        işarete bakarak o okulun GÜNÜNÜ KAPATMAZ: aksi halde köprü arızası,
        yazılmamış bir geceyi kalıcı bir boşluğa çevirirdi.

        Kalıcı kayıt bu işaretin kendisidir: `failed_modules` koşu defteri
        satırıyla birlikte backend'e yazılır (`insight.run.upsert`) ve bir
        sonraki tur/operatör oradan okur.
        """
        return "store" in self.failed_modules

    def as_row(self) -> dict[str, Any]:
        row = dataclasses.asdict(self)
        row.pop("school", None)
        return {"school": self.school, **row}


async def discover_students(source: Any, school: str) -> list[str]:
    """Okulun öğrenci kimliklerini türetir.

    ⚠️ **Bu bir geçici çözümdür.** `Source` arayüzünde öğrenci listesi
    döndüren bir metot **yok** (`MODULLER.md` §2.1'deki `students()` karşılığı
    izin listesinde bulunmuyor). Elimizdeki tek okul-geneli uç
    `homework_list(school)`; `HomeworkResponse.assigned` alanı hedef
    öğrencilerin kimliklerini taşıyor.

    **Sınırı açıkça:** `assigned` boşsa (NONE) hedef "dersin tamamı"dır ve o
    ödevden hiçbir kimlik çıkmaz. Yani bu yöntem, **hiç adrese özel ödev
    almamış** öğrencileri kaçırır. Üretimde listenin dışarıdan verilmesi
    gerekir; `run_school(student_ids=...)` bunun için var.
    """
    rows = await source.homework_list(school)
    if isinstance(rows, dict):
        rows = rows.get("items") or []
    found: list[str] = []
    seen: set[str] = set()
    for hw in rows or []:
        if not isinstance(hw, dict):
            continue
        for uid in hw.get("assigned") or []:
            key = str(uid)
            if key not in seen:
                seen.add(key)
                found.append(key)
    return found


@dataclasses.dataclass(slots=True)
class _Fetched:
    """Bir öğrencinin ham verisi + 1. geçiş sayımları."""

    profile: dict[str, Any] | None
    marks_raw: Any
    attendance_raw: Any
    pomodoro_raw: Any
    report_raw: Any
    homework_raw: Any
    class_ids: list[str]
    course_stats: dict[str, dict[str, Any]]
    attendance_stats: dict[str, dict[str, Any]]


async def _fetch_student(source: Any, school: str, student: str) -> _Fetched:
    """Tek öğrencinin verisini çeker. Yasaklı alan çağrısı **yoktur**."""
    profile = await source.profile(school, student)
    marks_raw = await source.marks(school, student)
    attendance_raw = await source.attendance(school, student)
    pomodoro_raw = await source.pomodoro(school, student)
    report_raw = await source.homework_report(school, student)
    homework_raw = await source.homework_list(school, student)
    return _Fetched(
        profile=profile,
        marks_raw=marks_raw,
        attendance_raw=attendance_raw,
        pomodoro_raw=pomodoro_raw,
        report_raw=report_raw,
        homework_raw=homework_raw,
        class_ids=marks_mod.class_ids_of(profile),
        course_stats=marks_mod.student_course_stats(marks_raw),
        attendance_stats=attendance_mod.course_stats(attendance_raw),
    )


def _due_dates(report_raw: Any) -> list[int]:
    return [
        int(i["due_at"])
        for i in submission_mod.normalize_items(report_raw)
        if i.get("due_at") is not None
    ]


def _summary_confidence(marks_profile: dict[str, Any]) -> Confidence:
    """Özetin güven kademesi: en az bir derste bant üretilebildiyse 'ön bulgu'."""
    for cstat in (marks_profile.get("courses") or {}).values():
        placement = cstat.get("placement") or {}
        conf = placement.get("confidence")
        if conf == Confidence.STABLE:
            return Confidence.STABLE
        if conf == Confidence.EXPLORATORY:
            return Confidence.EXPLORATORY
    return Confidence.NONE


async def run_school(
    source: Any,
    store: SchoolStore,
    school: str,
    *,
    now_ms: int,
    student_ids: list[str] | None = None,
    term_start_ms: int | None = None,
    budget_ms: int = DEFAULT_BUDGET_MS,
    resume_students: list[str] | None = None,
    monotonic_fn: Callable[[], float] = time.monotonic,
) -> RunResult:
    """Bir okul için hattı uçtan uca koşturur.

    `source` yalnız `Source` protokolündeki sekiz metodu uygular; bu fonksiyon
    başka hiçbir şey çağırmaz.

    `resume_students`: geçen koşuda bütçe yüzünden işlenemeyenler. Bunlar
    listenin **başına** alınır — "bir sonraki koşu oradan devam eder"
    (`MODULLER.md` §3.4) cümlesinin uygulaması budur. Sıra dışında hiçbir şey
    değişmez; liste dışında kalmış bir kimlik buradan eklenmez.

    `monotonic_fn`: bütçe sayacının saati. Üretimde `time.monotonic`;
    testlerde sahte saat verilerek bütçe aşımı **deterministik** kurulur —
    aksi halde "60 sn'yi aş" testi makinenin hızına bağlı olurdu.
    """
    started_wall = now_ms
    started_mono = monotonic_fn()
    result = RunResult(
        school=school, started_at=started_wall, budget_ms=budget_ms
    )

    def elapsed_ms() -> int:
        return int((monotonic_fn() - started_mono) * 1000)

    # Koşu defterine "running" satırı — süreç yeniden başlarsa bayat koşu
    # buradan görülür (`MODULLER.md` §3.4).
    await store.write_run(result.as_row(), result.run_key())

    if student_ids is None:
        try:
            student_ids = await discover_students(source, school)
        except Exception as exc:  # noqa: BLE001
            log.warning("öğrenci listesi çıkarılamadı (okul=%s): %s", school, exc)
            result.status = "failed"
            result.failed_modules.append("discover_students")
            result.finished_at = now_ms
            result.duration_ms = elapsed_ms()
            await store.write_run(result.as_row(), result.run_key())
            return result

    if resume_students:
        head = [s for s in resume_students if s in set(student_ids)]
        tail = [s for s in student_ids if s not in set(head)]
        student_ids = head + tail
        log.info(
            "kaldigi yerden devam: okul=%s bekleyen=%d/%d",
            school,
            len(head),
            len(student_ids),
        )

    result.students_total = len(student_ids)

    # ---------------- 1. geçiş: veri çek + sayımlar ------------------------
    fetched: dict[str, _Fetched] = {}
    pending: list[str] = []
    for index, student in enumerate(student_ids):
        if elapsed_ms() > budget_ms:
            # Bütçe aşıldı: kalanlar bir sonraki koşuya. Yarım bırakmak yerine
            # hiç başlamamak (`MODULLER.md` §3.4).
            result.budget_exceeded = True
            pending = list(student_ids[index:])
            break
        try:
            fetched[student] = await _fetch_student(source, school, student)
        except Exception as exc:  # noqa: BLE001 — kısmi başarısızlıkta devam
            log.warning("öğrenci atlandı (okul=%s, id=%s): %s", school, student, exc)
            result.students_failed += 1
            if "fetch" not in result.failed_modules:
                result.failed_modules.append("fetch")

    # ---------------- kohort kurulumu --------------------------------------
    #
    # Referans dağılımı **şube × ders** düzeyinde (`MODULLER.md` §0 kural 2).
    mark_inputs = {
        sid: (f.class_ids, f.course_stats) for sid, f in fetched.items()
    }
    distributions = marks_mod.cohort_distributions(
        marks_mod.collect_cohort_samples(mark_inputs)
    )
    attendance_inputs = {
        sid: (f.class_ids, f.attendance_stats) for sid, f in fetched.items()
    }
    medians = attendance_mod.cohort_medians(
        attendance_mod.collect_cohort_samples(attendance_inputs)
    )

    # ---------------- 2. geçiş: hesap + tavsiye ----------------------------
    summaries: list[StudentSummary] = []
    recommendations: list[Recommendation] = []
    for student, data in fetched.items():
        if elapsed_ms() > budget_ms:
            result.budget_exceeded = True
            pending.append(student)
            continue
        try:
            marks_profile = marks_mod.student_profile(
                data.marks_raw, data.profile, distributions
            )
            attendance_profile = attendance_mod.student_profile(
                data.attendance_raw, data.class_ids, medians
            )
            submission_profile = submission_mod.student_profile(
                data.report_raw, data.homework_raw, now_ms
            )
            study_profile = study_mod.student_profile(
                data.pomodoro_raw, now_ms, _due_dates(data.report_raw)
            )
            items = attention_mod.order_items(
                attention_mod.evaluate(
                    student,
                    attendance_profile=attendance_profile,
                    submission_profile=submission_profile,
                    marks_profile=marks_profile,
                    now_ms=now_ms,
                    term_start_ms=term_start_ms,
                )
            )
            recommendations.extend(
                recommend_mod.for_student(
                    school,
                    student,
                    marks_profile=marks_profile,
                    attendance_profile=attendance_profile,
                    submission_profile=submission_profile,
                    study_profile=study_profile,
                    attention_items=items,
                    course_teachers=marks_mod.course_teachers(data.marks_raw),
                    now_ms=now_ms,
                )
            )
            summaries.append(
                StudentSummary(
                    school=school,
                    student=student,
                    computed_at=now_ms,
                    marks=marks_profile,
                    attendance=attendance_profile,
                    submission=submission_profile,
                    study=study_profile,
                    attention=[
                        {
                            "trigger": i.trigger.value,
                            "fact": i.fact,
                            "evidence": i.evidence,
                            "window_from": i.window_from,
                            "window_to": i.window_to,
                        }
                        for i in items
                    ],
                    confidence=_summary_confidence(marks_profile),
                )
            )
            result.students_ok += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("hesap düştü (okul=%s, id=%s): %s", school, student, exc)
            result.students_failed += 1
            if "compute" not in result.failed_modules:
                result.failed_modules.append("compute")

    # ---------------- yazma ------------------------------------------------
    summary_report = await store.write_summaries(summaries)
    rec_report = await store.write_recommendations(recommendations)
    result.rows_written = summary_report.written + rec_report.written
    if summary_report.skipped_batches or rec_report.skipped_batches:
        result.failed_modules.append("store")

    # Mezuniyet/ayrılma temizliği: listede olmayanın **profili kalmamalıdır**.
    if not result.budget_exceeded and student_ids:
        await store.purge_departed(school, list(student_ids))

    await store.sweep(now_ms)

    result.students_skipped = len(pending)
    result.pending_students = pending
    result.finished_at = now_ms + elapsed_ms()
    result.duration_ms = elapsed_ms()
    if result.budget_exceeded or pending:
        result.status = "partial"
    elif result.students_failed and not result.students_ok:
        result.status = "failed"
    else:
        result.status = "ok"
    # Yazma düştüyse koşu "ok" DEĞİLDİR: hesaplanan satırların bir kısmı
    # yazılamadı ve bu, deftere bakan birinin görebilmesi gereken bir eksik.
    # Durum `partial`'a iner; asıl kalıcı işaret `failed_modules`'tadır ve
    # zamanlayıcı onu görünce o okulun GÜNÜNÜ KAPATMAZ (`write_failed`).
    if result.write_failed and result.status == "ok":
        result.status = "partial"

    await store.write_run(result.as_row(), result.run_key())
    return result
