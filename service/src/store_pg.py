"""ZEKA'nın okul veritabanına (PostgreSQL) yazma katmanı.

`src/store.py`'nin SurrealDB karşılığı. İkisi **yan yana** durur: mevcut
SurrealDB kurulumu çalışmaya devam ederken Postgres tarafı ayrı ayrı
sınanabilsin diye. Hattın gördüğü yüzey aynı olduğu için `pipeline.py` ve
`scheduler.py` değişmez.

Şema: `schema/postgres/school/20260916000001_zeka.sql`.

---------------------------------------------------------------------------
TEK VE MUTLAK KURAL — değişmedi
---------------------------------------------------------------------------
**Okul tablolarına asla yazılmaz.** Bu modülün dokunduğu her tablo `zeka_`
önekini taşır. Okul verisi yalnız `Source` arayüzü üzerinden, köprüden okunur.
`TABLES` listesi bu kuralın makine tarafından okunabilir hâlidir ve
`test_guard.py` her ifadenin hedefinin o listede olduğunu tarar.

---------------------------------------------------------------------------
SurrealDB sürümünden üç yapısal fark
---------------------------------------------------------------------------
1. **`school` alanı yok.** Her okul kendi veritabanında; kiracı veritabanının
   kendisidir. `school` parametresi imzalarda duruyor ama kullanılmıyor —
   çağıran taraf değişmesin diye.

2. **Diziler çocuk tabloda.** `attention`, `pending_students`,
   `failed_modules`, `downstream/experimental_dimensions` artık ayrı
   satırlardır. Bu yüzden yazma "üzerine yaz" değil, **sil-ve-yaz**: önce o
   sahibin çocuk satırları silinir, sonra yenileri yazılır. Yalnız eklemek,
   artık üretilmeyen bir dikkat maddesinin ekranda sonsuza kadar kalması
   demek olurdu.

3. **Yabancı anahtarlar gerçekten zorlanıyor.** Hepsi `ON DELETE NO ACTION`,
   yani bir üst satır çocukları dururken silinemez. Süpürme ve mezuniyet
   temizliği bu yüzden **önce çocuğu** siler. Ters sıra sessiz değil gürültülü
   düşerdi, ama yine de düşerdi.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Protocol, Sequence, runtime_checkable

from .compute.model import (
    QuestionSegment,
    Recommendation,
    StudentSegmentProfile,
    StudentSummary,
)
from .ids import uuid7
from .store import (
    BATCH_SIZE,
    MAX_ATTEMPTS,
    RETENTION_DAYS,
    WriteReport,
    _retain_until,
)

log = logging.getLogger(__name__)

#: Bu modulun yazabilecegi TEK tablo kumesi. `test_guard.py` bunu okur.
TABLES = (
    "zeka_student_summary",
    "zeka_attention_item",
    "zeka_recommendation",
    "zeka_run",
    "zeka_run_pending",
    "zeka_run_failed_module",
    "zeka_question_segment",
    "zeka_question_segment_dimension",
    "zeka_student_segment_profile",
)

#: Supurme sirasi: once cocuk, sonra ebeveyn. FK'ler NO ACTION oldugu icin
#: ters sira FK ihlaliyle duser.
SWEEP_ORDER = (
    ("zeka_attention_item", "zeka_student_summary", "student"),
    ("zeka_question_segment_dimension", "zeka_question_segment", "question"),
    ("zeka_run_pending", "zeka_run", "run"),
    ("zeka_run_failed_module", "zeka_run", "run"),
)


@runtime_checkable
class PgClient(Protocol):
    """Postgres istemcisinin ihtiyac duyulan tek yuzeyi.

    Surucu bagimsizligi `store.py` ile ayni gerekcede: bu modul bir Postgres
    surucusu import etmez, testler ve `--dry-run` gercek veritabani olmadan
    kosar.
    """

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> None: ...

    async def executemany(
        self, sql: str, rows: Sequence[Sequence[Any]]
    ) -> None: ...

    async def fetch(
        self, sql: str, params: Sequence[Any] = ()
    ) -> list[tuple[Any, ...]]: ...

    def transaction(self) -> Any: ...


class CollectingPgClient:
    """Gercek veritabani yerine ifadeleri toplayan istemci (`--dry-run`)."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, Any]] = []

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        self.statements.append((sql, list(params)))

    async def executemany(
        self, sql: str, rows: Sequence[Sequence[Any]]
    ) -> None:
        self.statements.append((sql, [list(r) for r in rows]))

    async def fetch(
        self, sql: str, params: Sequence[Any] = ()
    ) -> list[tuple[Any, ...]]:
        self.statements.append((sql, list(params)))
        return []

    def transaction(self) -> Any:
        return _NullTransaction()


class _NullTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: Any) -> bool:
        return False


# --- satir donusturuculer ---------------------------------------------------
#
# `store.py`'deki `*_row` fonksiyonlari SurrealDB sekli uretir: `school` tasir,
# diziler gomuludur ve kimlikler metindir. Asagidakiler Postgres kolon
# sirasina gore DUZ demetler uretir; sozluk degil demet, cunku `executemany`
# pozisyonel parametre alir ve kolon sirasi tek bir yerde — INSERT ifadesinde —
# yazili olsun istiyoruz.


def summary_tuple(s: StudentSummary) -> tuple[Any, ...]:
    return (
        s.student,
        _json(s.marks),
        _json(s.attendance),
        _json(s.submission),
        _json(s.study),
        str(s.confidence),
        s.computed_at,
        _retain_until("student_summary", s.computed_at),
    )


def attention_tuples(s: StudentSummary) -> list[tuple[Any, ...]]:
    """Dikkat maddeleri. Sira **alfabetiktir, siddete gore degil**.

    `ord` yazanin sirasini korur; okuyan taraf yeniden siralamasin diye var,
    bir onem derecesi tasidigi icin degil.
    """
    out: list[tuple[Any, ...]] = []
    for index, item in enumerate(s.attention or []):
        evidence = item.get("evidence") if isinstance(item, dict) else None
        if not evidence:
            # Kanitsiz madde yazilmaz. `Recommendation` icin gecerli olan kural
            # dikkat maddesi icin de gecerli: aciklanamayan sey gosterilmez.
            log.warning(
                "kanitsiz dikkat maddesi atlandi (ogrenci=%s, tetik=%s)",
                s.student,
                item.get("trigger") if isinstance(item, dict) else "?",
            )
            continue
        out.append(
            (
                s.student,
                str(item.get("trigger")),
                # Ders yalnizca not-egilimi maddesinde var ve kanitin icinde
                # tasiniyor; ust duzeyde bir `course` alani yok.
                evidence.get("course"),
                str(item.get("fact") or ""),
                int(item.get("window_from") or 0),
                int(item.get("window_to") or 0),
                _json(evidence),
                index,
            )
        )
    return out


def recommendation_tuple(rec: Recommendation) -> tuple[Any, ...]:
    """`retain_until = min(expires_at, created_at + 90 gun)`."""
    ninety = _retain_until("recommendation", rec.computed_at)
    return (
        str(uuid7(rec.computed_at)),
        rec.audience,
        rec.product,
        rec.rule_id,
        rec.rule_version,
        # Kapsam: kuralin kendi ayrimi (segment etiketi gibi) ya da ders.
        # `about` BURAYA KONMAZ; dogal anahtarda KENDI kolonu var. Ayni
        # kuralin otuz ogrenci icin urettigi otuz madde birbirinden `about`
        # ile ayrilir — kapsamdan degil.
        rec.scope or rec.course,
        rec.about,
        str(rec.audience_role),
        rec.course,
        _json({**rec.evidence, "limitation": rec.limitation}),
        str(rec.confidence),
        rec.computed_at,
        rec.expires_at,
        min(rec.expires_at, ninety),
    )


def question_segment_tuple(seg: QuestionSegment) -> tuple[Any, ...]:
    labels = {name: str(label) for name, label in seg.labels.items()}
    conf = {name: float(v) for name, v in seg.confidences.items()}
    return (
        seg.question,
        seg.exam,
        seg.course,
        seg.subject,
        labels.get("bilissel_talep"),
        labels.get("dikkat_tuzagi"),
        labels.get("okuma_yuku"),
        labels.get("adim_sayisi"),
        conf.get("bilissel_talep"),
        conf.get("dikkat_tuzagi"),
        conf.get("okuma_yuku"),
        conf.get("adim_sayisi"),
        str(seg.confidence),
        seg.trap_choice,
        seg.rationale,
        seg.model,
        seg.prompt_version,
        seg.variant,
        seg.computed_at,
        _retain_until("question_segment", seg.computed_at),
    )


def segment_dimension_tuples(seg: QuestionSegment) -> list[tuple[Any, ...]]:
    """Hangi boyut asagi akista kullaniliyor, hangisi deneysel.

    Satir basina tutulur: `rubric.py` bir boyutu deneysele indirdiginde bunun
    satirdan okunabilmesi icin. Belgeye bakmak gerekmesin.
    """
    out: list[tuple[Any, ...]] = []
    order = 0
    for role, names in (
        ("downstream", seg.downstream_dimensions),
        ("experimental", seg.experimental_dimensions),
    ):
        for name in names:
            out.append((seg.question, str(name), role, order))
            order += 1
    return out


def segment_profile_tuple(p: StudentSegmentProfile) -> tuple[Any, ...]:
    return (
        p.student,
        p.dimension,
        p.label,
        p.n_answers,
        p.n_correct,
        round(p.accuracy, 6),
        p.overall_n_answers,
        round(p.overall_accuracy, 6),
        round(p.contrast, 6),
        str(p.confidence),
        p.computed_at,
        _retain_until("student_segment_profile", p.computed_at),
    )


def _json(value: Any) -> str | None:
    """JSONB kolonuna gidecek degeri metne cevirir; None ise NULL birakir."""
    if value is None:
        return None
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


# --- SQL --------------------------------------------------------------------
#
# Her UPSERT'in `DO UPDATE SET` listesi ACIKCA yazilir. `EXCLUDED.*` diye bir
# toplu yazim yok ve olmayacak: `zeka_recommendation`da uc kolon (`dismissed_at`,
# `dismissed_by`, `dismiss_reason`) insan mudahalesi izidir (KVKK m.11) ve
# hesap hatti onlari hic uretmez. Toplu bir SET, her gece kosusunun
# kullanicinin "bu tavsiye faydali degil" kaydini sessizce silmesi demekti.

SQL_SUMMARY = """
INSERT INTO zeka_student_summary
  (student, marks, attendance, submission, study, confidence,
   computed_at, retain_until)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (student) DO UPDATE SET
  marks        = EXCLUDED.marks,
  attendance   = EXCLUDED.attendance,
  submission   = EXCLUDED.submission,
  study        = EXCLUDED.study,
  confidence   = EXCLUDED.confidence,
  computed_at  = EXCLUDED.computed_at,
  retain_until = EXCLUDED.retain_until
"""

SQL_ATTENTION = """
INSERT INTO zeka_attention_item
  (student, trigger, course, fact, window_from, window_to, evidence, ord)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""

SQL_RECOMMENDATION = """
INSERT INTO zeka_recommendation
  (id, audience, product, rule_id, rule_version, scope, about, audience_role,
   course, evidence, confidence, created_at, expires_at, retain_until)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (audience, product, rule_id, about, scope) DO UPDATE SET
  rule_version = EXCLUDED.rule_version,
  audience_role = EXCLUDED.audience_role,
  course       = EXCLUDED.course,
  evidence     = EXCLUDED.evidence,
  confidence   = EXCLUDED.confidence,
  created_at   = EXCLUDED.created_at,
  expires_at   = EXCLUDED.expires_at,
  retain_until = EXCLUDED.retain_until
"""

SQL_QUESTION_SEGMENT = """
INSERT INTO zeka_question_segment
  (question, exam, course, subject, bilissel_talep, dikkat_tuzagi, okuma_yuku,
   adim_sayisi, confidence_bilissel_talep, confidence_dikkat_tuzagi,
   confidence_okuma_yuku, confidence_adim_sayisi, confidence, trap_choice,
   rationale, model, prompt_version, variant, computed_at, retain_until)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (question) DO UPDATE SET
  exam = EXCLUDED.exam, course = EXCLUDED.course, subject = EXCLUDED.subject,
  bilissel_talep = EXCLUDED.bilissel_talep,
  dikkat_tuzagi  = EXCLUDED.dikkat_tuzagi,
  okuma_yuku     = EXCLUDED.okuma_yuku,
  adim_sayisi    = EXCLUDED.adim_sayisi,
  confidence_bilissel_talep = EXCLUDED.confidence_bilissel_talep,
  confidence_dikkat_tuzagi  = EXCLUDED.confidence_dikkat_tuzagi,
  confidence_okuma_yuku     = EXCLUDED.confidence_okuma_yuku,
  confidence_adim_sayisi    = EXCLUDED.confidence_adim_sayisi,
  confidence = EXCLUDED.confidence, trap_choice = EXCLUDED.trap_choice,
  rationale = EXCLUDED.rationale, model = EXCLUDED.model,
  prompt_version = EXCLUDED.prompt_version, variant = EXCLUDED.variant,
  computed_at = EXCLUDED.computed_at, retain_until = EXCLUDED.retain_until
"""

SQL_SEGMENT_DIMENSION = """
INSERT INTO zeka_question_segment_dimension (question, dimension, role, ord)
VALUES (%s, %s, %s, %s)
ON CONFLICT (question, dimension) DO UPDATE SET
  role = EXCLUDED.role, ord = EXCLUDED.ord
"""

SQL_SEGMENT_PROFILE = """
INSERT INTO zeka_student_segment_profile
  (student, dimension, label, n_answers, n_correct, accuracy,
   overall_n_answers, overall_accuracy, contrast, confidence,
   computed_at, retain_until)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (student, dimension, label) DO UPDATE SET
  n_answers = EXCLUDED.n_answers, n_correct = EXCLUDED.n_correct,
  accuracy  = EXCLUDED.accuracy,
  overall_n_answers = EXCLUDED.overall_n_answers,
  overall_accuracy  = EXCLUDED.overall_accuracy,
  contrast = EXCLUDED.contrast, confidence = EXCLUDED.confidence,
  computed_at = EXCLUDED.computed_at, retain_until = EXCLUDED.retain_until
"""

SQL_RUN = """
INSERT INTO zeka_run
  (run_day, started_at, finished_at, status, duration_ms, students_total,
   students_ok, students_failed, students_skipped, rows_written,
   budget_exceeded, budget_ms, retain_until)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (run_day) DO UPDATE SET
  started_at = EXCLUDED.started_at, finished_at = EXCLUDED.finished_at,
  status = EXCLUDED.status, duration_ms = EXCLUDED.duration_ms,
  students_total = EXCLUDED.students_total, students_ok = EXCLUDED.students_ok,
  students_failed = EXCLUDED.students_failed,
  students_skipped = EXCLUDED.students_skipped,
  rows_written = EXCLUDED.rows_written,
  budget_exceeded = EXCLUDED.budget_exceeded, budget_ms = EXCLUDED.budget_ms,
  retain_until = EXCLUDED.retain_until
"""


class PgStore:
    """Toplu UPSERT + supurme, Postgres uzerinde."""

    def __init__(self, client: PgClient, *, batch_size: int = BATCH_SIZE) -> None:
        self._client = client
        self._batch_size = batch_size

    # -- yardimci -----------------------------------------------------------

    async def _attempt(self, work: Any, *, table: str, rows: int) -> bool:
        """Bir grubu `MAX_ATTEMPTS` kez dener; ikinci dususte atlar.

        `store.py` ile ayni hata davranisi: bir grup dusse de hat devam eder,
        cunku bir okulun bir gecesi ugruna butun kosuyu kaybetmek daha kotu.
        Atlanan grup `warn` loglanir ve `WriteReport.skipped_batches` uzerinden
        kosu defterine yansir — sessizce kaybolmaz.
        """
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                await work()
                return True
            except Exception as exc:  # noqa: BLE001 — hat devam etmeli
                log.warning(
                    "toplu yazma dustu (tablo=%s, deneme=%d/%d): %s",
                    table,
                    attempt,
                    MAX_ATTEMPTS,
                    exc,
                )
        log.warning("grup atlandi (tablo=%s, satir=%d)", table, rows)
        return False

    def _chunks(self, rows: list[Any]) -> list[list[Any]]:
        return [
            rows[i : i + self._batch_size]
            for i in range(0, len(rows), self._batch_size)
        ]

    # -- yazma --------------------------------------------------------------

    async def write_summaries(self, summaries: list[StudentSummary]) -> WriteReport:
        """Ozetleri ve dikkat maddelerini yazar.

        Dikkat maddeleri **sil-ve-yaz**: bir ogrencinin onceki maddeleri
        silinmeden yenileri yazilsaydi, artik uretilmeyen bir madde ekranda
        kalirdi. Ozet ve maddeleri ayni transaction'da gider; yarim bir durum
        (ozet yeni, maddeler eski) ekranda celiskiye donusurdu.
        """
        report = WriteReport()
        for chunk in self._chunks(summaries):
            students = [s.student for s in chunk]
            rows = [summary_tuple(s) for s in chunk]
            items: list[tuple[Any, ...]] = []
            for s in chunk:
                items.extend(attention_tuples(s))

            async def work(
                rows: list = rows, students: list = students, items: list = items
            ) -> None:
                async with self._client.transaction():
                    await self._client.executemany(SQL_SUMMARY, rows)
                    await self._client.execute(
                        "DELETE FROM zeka_attention_item "
                        "WHERE student = ANY(%s)",
                        (students,),
                    )
                    if items:
                        await self._client.executemany(SQL_ATTENTION, items)

            if await self._attempt(
                work, table="zeka_student_summary", rows=len(chunk)
            ):
                report.written += len(chunk)
            else:
                report.skipped_batches += 1
        return report

    async def write_recommendations(
        self, recs: list[Recommendation]
    ) -> WriteReport:
        """Tavsiyeleri yazar. **Kanitsiz satir reddedilir.**"""
        rows: list[tuple[Any, ...]] = []
        rejected = 0
        for rec in recs:
            evidence = {**rec.evidence, "limitation": rec.limitation}
            if not {k: v for k, v in evidence.items() if k != "limitation"}:
                log.warning("kanitsiz tavsiye reddedildi: %s", rec.rule_id)
                rejected += 1
                continue
            rows.append(recommendation_tuple(rec))

        report = WriteReport()
        for chunk in self._chunks(rows):

            async def work(chunk: list = chunk) -> None:
                async with self._client.transaction():
                    await self._client.executemany(SQL_RECOMMENDATION, chunk)

            if await self._attempt(
                work, table="zeka_recommendation", rows=len(chunk)
            ):
                report.written += len(chunk)
            else:
                report.skipped_batches += 1
        report.rejected = rejected
        return report

    async def write_question_segments(
        self, segments: list[QuestionSegment]
    ) -> WriteReport:
        """Soru segment etiketlerini ve boyut ayrimini yazar."""
        report = WriteReport()
        for chunk in self._chunks(segments):
            rows = [question_segment_tuple(s) for s in chunk]
            dims: list[tuple[Any, ...]] = []
            for s in chunk:
                dims.extend(segment_dimension_tuples(s))
            questions = [s.question for s in chunk]

            async def work(
                rows: list = rows, dims: list = dims, questions: list = questions
            ) -> None:
                async with self._client.transaction():
                    await self._client.executemany(SQL_QUESTION_SEGMENT, rows)
                    # Bir boyut deneyselden uretime (ya da tersine) gecerse
                    # eski satir kalmamali; rubrik surumu degistiginde liste
                    # kisalabilir de.
                    await self._client.execute(
                        "DELETE FROM zeka_question_segment_dimension "
                        "WHERE question = ANY(%s)",
                        (questions,),
                    )
                    if dims:
                        await self._client.executemany(
                            SQL_SEGMENT_DIMENSION, dims
                        )

            if await self._attempt(
                work, table="zeka_question_segment", rows=len(chunk)
            ):
                report.written += len(chunk)
            else:
                report.skipped_batches += 1
        return report

    async def write_segment_profiles(
        self, profiles: list[StudentSegmentProfile]
    ) -> WriteReport:
        """Ogrenci segment profillerini yazar.

        Guven kapisinin **altindaki** satirlar da yazilir: depo ham olguyu
        tutar, gosterme karari kuralindir. Esik olcumle degisebildigi icin
        kapinin depoda olmasi, esik her degistiginde veriyi yeniden uretmek
        demek olurdu.
        """
        report = WriteReport()
        rows = [segment_profile_tuple(p) for p in profiles]
        for chunk in self._chunks(rows):

            async def work(chunk: list = chunk) -> None:
                async with self._client.transaction():
                    await self._client.executemany(SQL_SEGMENT_PROFILE, chunk)

            if await self._attempt(
                work, table="zeka_student_segment_profile", rows=len(chunk)
            ):
                report.written += len(chunk)
            else:
                report.skipped_batches += 1
        return report

    async def write_run(self, run_row: dict[str, Any], key: str) -> bool:
        """Kosu defteri satirini yazar. `key` = `YYYY-MM-DD`.

        SurrealDB surumunde anahtar `{school}_{gun}` idi; okul yarisi dustu.
        Cagiran taraf hala okul onekli bir anahtar gonderiyorsa son 10 karakter
        alinir — sessizce yanlis gune yazmaktansa bicimi burada normalize etmek
        daha guvenli.
        """
        day = key[-10:]
        started = int(run_row["started_at"])
        row = (
            day,
            started,
            run_row.get("finished_at"),
            run_row.get("status", "running"),
            run_row.get("duration_ms"),
            int(run_row.get("students_total", 0)),
            int(run_row.get("students_ok", 0)),
            int(run_row.get("students_failed", 0)),
            int(run_row.get("students_skipped", 0)),
            int(run_row.get("rows_written", 0)),
            bool(run_row.get("budget_exceeded", False)),
            int(run_row.get("budget_ms", 0)),
            int(run_row.get("retain_until") or _retain_until("insight_run", started)),
        )
        pending = [
            (day, str(s), i)
            for i, s in enumerate(run_row.get("pending_students") or [])
        ]
        failed = [
            (day, str(m), i)
            for i, m in enumerate(run_row.get("failed_modules") or [])
        ]

        async def work() -> None:
            async with self._client.transaction():
                await self._client.execute(SQL_RUN, row)
                await self._client.execute(
                    "DELETE FROM zeka_run_pending WHERE run = %s", (day,)
                )
                await self._client.execute(
                    "DELETE FROM zeka_run_failed_module WHERE run = %s", (day,)
                )
                if pending:
                    await self._client.executemany(
                        "INSERT INTO zeka_run_pending (run, student, ord) "
                        "VALUES (%s, %s, %s)",
                        pending,
                    )
                if failed:
                    await self._client.executemany(
                        "INSERT INTO zeka_run_failed_module (run, module, ord) "
                        "VALUES (%s, %s, %s)",
                        failed,
                    )

        return await self._attempt(work, table="zeka_run", rows=1)

    # -- okuma --------------------------------------------------------------

    async def last_pending(self, school: str = "") -> list[str]:
        """Son kosudan devreden ogrenci kimlikleri.

        `school` KULLANILMIYOR: veritabaninin kendisi zaten o okul. Parametre
        cagiran tarafi degistirmemek icin duruyor.

        Okunamazsa bos liste doner: devretmemek, yanlis listeyle kosmaktan
        iyidir.
        """
        sql = (
            "SELECT p.student FROM zeka_run_pending p "
            "JOIN zeka_run r ON r.run_day = p.run "
            "WHERE r.run_day = (SELECT run_day FROM zeka_run "
            "                   ORDER BY started_at DESC LIMIT 1) "
            "ORDER BY p.ord"
        )
        try:
            rows = await self._client.fetch(sql)
        except Exception as exc:  # noqa: BLE001
            log.warning("bekleyen liste okunamadi: %s", exc)
            return []
        return [str(r[0]) for r in rows]

    # -- supurme ------------------------------------------------------------

    async def sweep(self, now_ms: int) -> dict[str, bool]:
        """Saklama suresi dolmus satirlari siler.

        **Once cocuk, sonra ebeveyn.** FK'ler `ON DELETE NO ACTION`, yani
        cocugu duran bir ebeveyn silinemez. Cocuk satirin kendi `retain_until`
        alani yok; omru ebeveyninkine bagli, o yuzden silme kosulu ebeveyn
        uzerinden okunur.
        """
        results: dict[str, bool] = {}
        for child, parent, key in SWEEP_ORDER:
            sql = (
                f"DELETE FROM {child} WHERE {key} IN "
                f"(SELECT {'run_day' if parent == 'zeka_run' else key} "
                f"FROM {parent} WHERE retain_until < %s)"
            )
            results[child] = await self._run_sweep(child, sql, now_ms)

        for table in (
            "zeka_student_summary",
            "zeka_recommendation",
            "zeka_run",
            "zeka_question_segment",
            "zeka_student_segment_profile",
        ):
            sql = f"DELETE FROM {table} WHERE retain_until < %s"
            results[table] = await self._run_sweep(table, sql, now_ms)
        return results

    async def _run_sweep(self, table: str, sql: str, now_ms: int) -> bool:
        try:
            await self._client.execute(sql, (now_ms,))
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("supurme dustu (tablo=%s): %s", table, exc)
            return False

    async def purge_departed(
        self, school: str, active_students: list[str]
    ) -> bool:
        """Artik ogrenci olmayanlarin turetilmis verisini siler.

        "Mezunun ham verisi arsivde kalabilir; **profili kalmamalidir**."

        `zeka_question_segment` buraya GIRMEZ: o satir bir soru hakkindadir,
        hicbir ogrenciye baglanamaz.

        `school` KULLANILMIYOR — veritabani zaten o okul.

        Bos `active_students` ile **hicbir sey silinmez**. Bos liste "okulda
        ogrenci kalmadi" degil, neredeyse her zaman "listeyi cekemedik"
        demektir; o hali silme emrine cevirmek butun ogrenci profillerini
        silerdi.
        """
        if not active_students:
            log.warning("aktif ogrenci listesi bos — mezuniyet temizligi atlandi")
            return False

        async def work() -> None:
            async with self._client.transaction():
                await self._client.execute(
                    "DELETE FROM zeka_attention_item WHERE student <> ALL(%s)",
                    (active_students,),
                )
                await self._client.execute(
                    "DELETE FROM zeka_student_summary WHERE student <> ALL(%s)",
                    (active_students,),
                )
                await self._client.execute(
                    "DELETE FROM zeka_student_segment_profile "
                    "WHERE student <> ALL(%s)",
                    (active_students,),
                )
                await self._client.execute(
                    "DELETE FROM zeka_recommendation "
                    "WHERE about IS NOT NULL AND about <> ALL(%s)",
                    (active_students,),
                )
                await self._client.execute(
                    "DELETE FROM zeka_run_pending WHERE student <> ALL(%s)",
                    (active_students,),
                )

        return await self._attempt(work, table="mezuniyet", rows=0)


__all__ = [
    "PgClient",
    "CollectingPgClient",
    "PgStore",
    "WriteReport",
    "TABLES",
    "RETENTION_DAYS",
]
