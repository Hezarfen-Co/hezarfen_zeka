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
from collections.abc import Callable, Sequence
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


#: The `sections` vocabulary (`capabilities.SECTIONS`), as a set the pipeline
#: can test against. Validation lives at the edge (`handlers._sections`); the
#: pipeline only applies the filter a caller hands it.
SECTION_NAMES: tuple[str, ...] = ("marks", "attendance", "submission", "study")


@dataclasses.dataclass(slots=True)
class StudentOutcome:
    """One student's result, for the capability handlers.

    `RunResult` is bookkeeping only: it says how many students were counted,
    not what any of them produced. A dispatched compute answers with a
    payload per student, and this is where the per-student truth travels --
    which modules were read (`coverage`, empty when the fetch failed), what
    was computed, and how it failed if it did.

    Only filled when the caller passes an `outcomes` list; the night run
    collects none.
    """

    student: str
    #: Source name -> records read. An EMPTY dict means the fetch failed, which
    #: is a different claim from "read, and it was empty".
    coverage: dict[str, int] = dataclasses.field(default_factory=dict)
    summary: StudentSummary | None = None
    recommendations: list[Recommendation] = dataclasses.field(default_factory=list)
    error: str | None = None
    #: `fetch` (the data could not be read) or `compute` (the arithmetic fell
    #: over). `handlers._ERROR_CODES` maps it to the refusal code.
    error_kind: str | None = None
    #: A structured refusal, when the read failed at a known endpoint: the
    #: `SourceError`'s code (`not_permitted` for HTTP 401/403), the path it
    #: touched, and the status. Empty when the failure carried none (a compute
    #: break, or a source that raises a plain exception). `handlers` turns
    #: these into the answer's `failed[]` / `coverage.unavailable` instead of a
    #: bare exception, so a reader can tell "the requester may not read this"
    #: from "the service broke".
    error_code: str = ""
    error_path: str = ""
    error_status: int = 0

    def refusal(self) -> dict[str, Any] | None:
        """The structured refusal, or `None` when the failure carried none."""
        if not self.error_code:
            return None
        row: dict[str, Any] = {"code": self.error_code}
        if self.error_path:
            row["path"] = self.error_path
        if self.error_status:
            row["status"] = self.error_status
        return row


def _section_filter(sections: Sequence[str] | None) -> frozenset[str] | None:
    """`None` = every module (the night run). Otherwise the requested subset."""
    if sections is None:
        return None
    return frozenset(str(name) for name in sections)


async def discover_students(
    source: Any, school: str, *, on_behalf_of: str | None = None
) -> list[str]:
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

    `on_behalf_of`: okul geneli liste YALNIZ manager+ için doludur
    (`web/homework.rs::list_homework` `manages_all`); sentetik `ai` rolü hiçbir
    dersi göremediği için kadro bu alan olmadan boş çıkar. Bir yetenek
    gönderiminde çağrı sahibinin (`requested_by`) kimliği buraya gelir.
    """
    rows = await source.homework_list(school, on_behalf_of)
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
    #: Source name -> records read (see `StudentOutcome.coverage`).
    coverage: dict[str, int]


async def _fetch_student(
    source: Any,
    school: str,
    student: str,
    *,
    sections: frozenset[str] | None = None,
    on_behalf_of: str | None = None,
) -> _Fetched:
    """Tek öğrencinin verisini çeker. Yasaklı alan çağrısı **yoktur**.

    `sections` verilirse YALNIZ istenen modüllerin kaynakları okunur: bir
    isteğe iki uç fazladan çağrı yapmak, okunmayan veri için de bir maliyet
    ve bir hata yüzeyi yaratırdı. `profile` her hâlükârda okunur (şube
    kimlikleri oradan gelir), ödev raporu da `submission` ya da `study`
    istenmişse (çalışma profilinin teslim tarihleri ondan çıkar).

    -----------------------------------------------------------------------
    KİM OLARAK OKUNUR (`on_behalf_of`) — BİLİNÇLİ İSTİSNA
    -----------------------------------------------------------------------
    Hedefi `{user}` yol parametresi olan okumalar (profil, not, devam,
    pomodoro, ödev RAPORU) istek sahibi (`on_behalf_of`, yani gönderimin
    `requested_by`'si) olarak koşar: backend bu uçlarda istek sahibinin
    haklarını arar (`web/marks.rs::user_marks` "teacher+, or a parent").
    Sentetik `ai` rolü hiçbir dersi göremediği için bu alan olmadan her okuma
    403 ya da boş dönerdi.

    TEK İSTİSNA: kişisel `/homework` (`homework_list`). Bu uç "BENİM
    ödevlerim" görünümüdür ve KİM olarak okunduğuna göre farklı bir küme
    döndürür — istek sahibi (manager+) olarak okunursa OKULUN tamamı gelir ve
    `upcoming` bloğu o öğrencinin profiline başka öğrencilerin/derslerin
    teslim tarihlerini karıştırır. Doğru küme öğrencinin KENDİSİ olarak
    okumaktır; bu okuma bilerek `student` olarak gider. Bu satırı "düzeltip"
    `on_behalf_of`'a çevirmeyin — o öğrencinin `upcoming` listesi bozulur.
    """
    everything = sections is None

    def want(name: str) -> bool:
        return everything or name in sections

    profile = await source.profile(school, student, on_behalf_of=on_behalf_of)
    marks_raw = (
        await source.marks(school, student, on_behalf_of=on_behalf_of)
        if want("marks")
        else None
    )
    attendance_raw = (
        await source.attendance(school, student, on_behalf_of=on_behalf_of)
        if want("attendance")
        else None
    )
    pomodoro_raw = (
        await source.pomodoro(school, student, on_behalf_of=on_behalf_of)
        if want("study")
        else None
    )
    need_report = want("submission") or want("study")
    report_raw = (
        await source.homework_report(school, student, on_behalf_of=on_behalf_of)
        if need_report
        else None
    )
    homework_raw = (
        await source.homework_list(school, student) if need_report else None
    )
    coverage: dict[str, int] = {"profile": 1 if profile else 0}
    if want("marks"):
        coverage["marks"] = len(marks_mod.normalize_rows(marks_raw))
    if want("attendance"):
        coverage["attendance"] = len(attendance_mod.normalize_rows(attendance_raw))
    if want("study"):
        coverage["pomodoro"] = len(study_mod.normalize_rows(pomodoro_raw))
    if need_report:
        coverage["homework_report"] = len(
            submission_mod.normalize_items(report_raw)
        )
        coverage["homework_list"] = len(homework_raw or [])
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
        coverage=coverage,
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
    nightly: bool = True,
    sections: Sequence[str] | None = None,
    on_behalf_of: str | None = None,
    outcomes: list[StudentOutcome] | None = None,
) -> RunResult:
    """Bir okul için hattı uçtan uca koşturur.

    `source` yalnız `Source` protokolündeki sekiz metodu uygular; bu fonksiyon
    başka hiçbir şey çağırmaz.

    `nightly=False` (yetenek isleyicileri): koşu defteri, mezuniyet temizliği
    ve saklama süpürmesi YAPILMAZ. Bunlar okul geneli gece işinin parçasıdır;
    tek öğrencilik bir hesap günün `zeka_run` satırını (anahtar `run_day`)
    ezmemeli ve bir ALT KÜMEYİ "aktif kadro" diye temizliğe vermemelidir.
    Mezuniyet temizliği zaten yalnız kadro DİZİNDEN çıkarıldığında koşar:
    çağıranın verdiği liste (`refresh user_ids`, `cli --students`) bir alt
    kümedir ve backend'in `insight.departed.purge` kapısı tam bu yüzden
    boş/kısmi listeyi reddeder.

    `sections`: hangi modüllerin hesaplanacağı (`SECTION_NAMES`). İstenmeyen
    modül hesaplanmaz ve `StudentSummary` alanı `None` kalır -- satıra `null`
    gider, backend'in `SummaryRow` sözleşmesindeki "hesaplanmadı". Ad
    doğrulaması kenarda (`handlers._sections`) yapılır; burada bilinmeyen ad
    sessizce "istenmemiş" sayılır.

    `outcomes`: verilirse her öğrenci için bir `StudentOutcome` eklenir
    (başarılı, düşen ve bütçeye takılanlar için birer kayıt). Gece koşusu
    toplamaz; yetenek isleyicileri cevabı oradan kurar.

    `resume_students`: geçen koşuda bütçe yüzünden işlenemeyenler. Bunlar
    listenin **başına** alınır — "bir sonraki koşu oradan devam eder"
    (`MODULLER.md` §3.4) cümlesinin uygulaması budur. Sıra dışında hiçbir şey
    değişmez; liste dışında kalmış bir kimlik buradan eklenmez.

    `monotonic_fn`: bütçe sayacının saati. Üretimde `time.monotonic`;
    testlerde sahte saat verilerek bütçe aşımı **deterministik** kurulur —
    aksi halde "60 sn'yi aş" testi makinenin hızına bağlı olurdu.
    """
    # Was the roster handed in (a subset) or read from the directory (the
    # roster)? The departed purge is only honest for the latter.
    roster_from_directory = student_ids is None
    wanted = _section_filter(sections)

    def want(name: str) -> bool:
        return wanted is None or name in wanted

    started_wall = now_ms
    started_mono = monotonic_fn()
    result = RunResult(
        school=school, started_at=started_wall, budget_ms=budget_ms
    )

    def elapsed_ms() -> int:
        return int((monotonic_fn() - started_mono) * 1000)

    # Koşu defterine "running" satırı — süreç yeniden başlarsa bayat koşu
    # buradan görülür (`MODULLER.md` §3.4).
    if nightly:
        await store.write_run(result.as_row(), result.run_key())

    if student_ids is None:
        try:
            student_ids = await discover_students(
                source, school, on_behalf_of=on_behalf_of
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("öğrenci listesi çıkarılamadı (okul=%s): %s", school, exc)
            result.status = "failed"
            result.failed_modules.append("discover_students")
            result.finished_at = now_ms
            result.duration_ms = elapsed_ms()
            if nightly:
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
            fetched[student] = await _fetch_student(
                source, school, student, sections=wanted, on_behalf_of=on_behalf_of
            )
        except Exception as exc:  # noqa: BLE001 — kısmi başarısızlıkta devam
            log.warning("öğrenci atlandı (okul=%s, id=%s): %s", school, student, exc)
            result.students_failed += 1
            if "fetch" not in result.failed_modules:
                result.failed_modules.append("fetch")
            if outcomes is not None:
                outcomes.append(
                    StudentOutcome(
                        student=student,
                        error=str(exc),
                        error_kind="fetch",
                        error_code=str(getattr(exc, "code", "") or ""),
                        error_path=str(getattr(exc, "path", "") or ""),
                        error_status=int(getattr(exc, "status", 0) or 0),
                    )
                )

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
    #
    # İstenmeyen modül (`sections`) hesaba hiç girmez ve özette `None` kalır.
    # Dikkat ve tavsiye kuralları yine çağrılır: modül profillerinin kapıları
    # kendi içindedir, eksik profil zaten "ateşlemez" demektir.
    summaries: list[StudentSummary] = []
    recommendations: list[Recommendation] = []
    for student, data in fetched.items():
        if elapsed_ms() > budget_ms:
            result.budget_exceeded = True
            pending.append(student)
            continue
        try:
            marks_profile = (
                marks_mod.student_profile(data.marks_raw, data.profile, distributions)
                if want("marks")
                else None
            )
            attendance_profile = (
                attendance_mod.student_profile(
                    data.attendance_raw, data.class_ids, medians
                )
                if want("attendance")
                else None
            )
            submission_profile = (
                submission_mod.student_profile(
                    data.report_raw, data.homework_raw, now_ms
                )
                if want("submission")
                else None
            )
            study_profile = (
                study_mod.student_profile(
                    data.pomodoro_raw, now_ms, _due_dates(data.report_raw)
                )
                if want("study")
                else None
            )
            items = attention_mod.order_items(
                attention_mod.evaluate(
                    student,
                    attendance_profile=attendance_profile or {},
                    submission_profile=submission_profile or {},
                    marks_profile=marks_profile or {},
                    now_ms=now_ms,
                    term_start_ms=term_start_ms,
                )
            )
            recs = recommend_mod.for_student(
                school,
                student,
                marks_profile=marks_profile or {},
                attendance_profile=attendance_profile or {},
                submission_profile=submission_profile or {},
                study_profile=study_profile or {},
                attention_items=items,
                course_teachers=marks_mod.course_teachers(data.marks_raw),
                now_ms=now_ms,
            )
            recommendations.extend(recs)
            summary = StudentSummary(
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
                confidence=_summary_confidence(marks_profile or {}),
            )
            summaries.append(summary)
            result.students_ok += 1
            if outcomes is not None:
                outcomes.append(
                    StudentOutcome(
                        student=student,
                        coverage=dict(data.coverage),
                        summary=summary,
                        recommendations=recs,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("hesap düştü (okul=%s, id=%s): %s", school, student, exc)
            result.students_failed += 1
            if "compute" not in result.failed_modules:
                result.failed_modules.append("compute")
            if outcomes is not None:
                outcomes.append(
                    StudentOutcome(
                        student=student,
                        coverage=dict(data.coverage),
                        error=str(exc),
                        error_kind="compute",
                    )
                )

    # ---------------- yazma ------------------------------------------------
    summary_report = await store.write_summaries(summaries)
    rec_report = await store.write_recommendations(recommendations)
    result.rows_written = summary_report.written + rec_report.written
    if summary_report.skipped_batches or rec_report.skipped_batches:
        result.failed_modules.append("store")

    # Mezuniyet/ayrılma temizliği: listede olmayanın **profili kalmamalıdır**.
    # Yalnız dizinden çıkarılan TAM kadro ve yalnız gece koşusu için: çağıranın
    # verdiği liste bir ALT KÜMEDİR (refresh `user_ids`, `cli --students`) ve
    # onu kadro saymak, adı geçmeyen herkesin türetilmiş verisini sildirirdi.
    if nightly and roster_from_directory and not result.budget_exceeded and student_ids:
        await store.purge_departed(school, list(student_ids))

    if nightly:
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

    if nightly:
        await store.write_run(result.as_row(), result.run_key())
    return result
