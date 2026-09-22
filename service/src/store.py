"""ZEKA'nın yazma **ve** okuma katmanı — hepsi köprüden.

---------------------------------------------------------------------------
DEĞİŞMEZ KURAL (2026-09-17, kullanıcı)
---------------------------------------------------------------------------
**Bir AI servisi uygulama veritabanına asla doğrudan erişmez. Şimdi değil,
gelecekte de.** Bu bir parti kararı değil, sürekli bir kuraldır.

ZEKA'nın **kendi** deposu yoktur. Hesapladığı her satır, okuduğu her liste
backend'in QUIC köprüsü üzerinden gider ve gelir: `insight.*` yetenek
çağrıları. Bu modülde tek bir bağlantı açılmaz, tek bir SQL/SurrealQL dizesi
yoktur, hiçbir veritabanı sürücüsü **import edilmez**. Silinen yol budur —
`pg_client.py`, `store_pg.py`, `tenants.py`, `store_factory.py` ve
`schema/` artık yok; geri gelmeleri de yasaktır.

`zeka_*` tabloları OKULUN veritabanında durur ve DDL'i backend deposundadır
(`hezarfen_backend/migrations/school/20260917000002_zeka.sql`). Sahibi
backend'dir; ZEKA yalnız "şu satırları yaz" der.

---------------------------------------------------------------------------
TEL (kablo) SÖZLEŞMESİ
---------------------------------------------------------------------------
Çağrı, `BridgeProtocol.call_capability()` ile, servisin AÇTIĞI taze bir
istemci-başlatımlı akışta gider (tıpkı `ApiRequest` gibi):

    { "id": "<ulid>", "capability": "insight.<noun>[.<verb>]",
      "school": "<uuid>", "payload": { ... } }

    { "status": "ok",  "id": ..., "school": ..., "payload": { ... } }
    { "status": "err", "id": ..., "school": ..., "code": ..., "message": ... }

`status` ÖNCE okunur; `err` asla başarı sayılmaz. Reddin kodu tiplidir
(`malformed`, `unknown_capability`, `unknown_school`, `school_suspended`,
`not_permitted`, `invalid_payload`, `unavailable`, `timed_out`, `internal`,
`too_many_rows`) ve `CapabilityRefused` olarak yükselir.

Okul **çerçevededir**, payload'da değil: `school` tireli okul uuid'sidir; backend onu çözer ve her ifadeyi
o okulun kendi veritabanında koşturur. Tek istisna `insight.schools.list`
(deployment ölçekli): çerçevede `school: ""` gider.

---------------------------------------------------------------------------
HATA DAVRANIŞI (`MODULLER.md` §2.11)
---------------------------------------------------------------------------
* Yazma: grup (500 satır) `MAX_ATTEMPTS` kez denenir; **ikinci düşüşte**
  grup atlanır, `warn` loglanır ve hat devam eder — `WriteReport.status`
  `partial` olur, `pipeline` bunu koşu defterine `store` olarak yazar.
  Sessiz başarı YOKTUR: yazılamayan satır sayısı rapordadır.
* Okuma (`pending`): okunamazsa boş liste. Devretmemek, yanlış listeyle
  koşmaktan iyidir.
* Süpürme/mezuniyet: tablo başına `False` / `False` döner; hata yutulmaz,
  raporlanır.
* Köprü kapalıyken (`caller` yok) OKUMA çağrıları `BridgeUnavailable`
  yükseltir; YAZMA ise sessizce yutulmaz ama yükseltmez de: grup
  `MAX_ATTEMPTS` kez denenir, atlanır ve raporda `partial` olarak görünür.
  İkisi de sessiz başarı DEĞİLDİR. Açılış bunları yakalamaz, çünkü açılışta
  hiçbir şey açılmaz.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

from .compute import clock
from .compute.model import (
    QuestionSegment,
    Recommendation,
    StudentSegmentProfile,
    StudentSummary,
)

log = logging.getLogger(__name__)

# `MODULLER.md` §2.11 adım 1: 500 satırlık gruplar. Backend'in tavanı da
# `MAX_INSIGHT_BATCH_ROWS = 500`; ikisi aynı sayıdır, biri değişirse diğeri
# `too_many_rows` reddiyle söyler.
BATCH_SIZE = 500

# Bir grup düşerse yeniden denenir; **ikinci düşüşte** atlanır.
MAX_ATTEMPTS = 2

# --- yetenek adları ---------------------------------------------------------
# Ad alanı backend'in ilan ettiği operasyon listesidir; burada TEK bir yerde
# yazılır ki bir yeniden adlandırma tek satırda kalsın.

CAP_SUMMARY = "insight.summary.upsert"
CAP_RECOMMENDATION = "insight.recommendation.upsert"
CAP_SEGMENT = "insight.segment.upsert"
CAP_PROFILE = "insight.profile.upsert"
CAP_RUN = "insight.run.upsert"
CAP_PENDING = "insight.pending.list"
CAP_SWEEP = "insight.retention.sweep"
CAP_PURGE = "insight.departed.purge"
CAP_SCHOOLS = "insight.schools.list"

#: Deployment ölçekli tek çağrı: okul çerçevede BOŞ gider.
DEPLOYMENT_SCOPED = (CAP_SCHOOLS,)

#: Sunucu tavanları (istemci tarafında da bilinir: boşuna tur atmayalım).
#: Aşılırsa sunucu `too_many_rows` döner; istemci listeyi kırpmaz, bekler.
MAX_LIST_ROWS = 20000

# --- saklama süreleri ([T§6.7], MODULLER.md §2.11 adım 2) -------------------
#
# Süpürme artık backend'de koşar; süreler yine burada hesaplanır çünkü satırı
# yazan taraf `retain_until` alanını üretir. Süresi olmayan tablo YOKTUR.
RETENTION_DAYS = {
    # "Dönem + 1 yıl" — türetilmiş veri, ham veriden yeniden üretilebilir.
    "student_summary": 400,
    # "expires_at veya 90 gün — hangisi önce." Bayat tavsiye zararlıdır.
    "recommendation": 90,
    # Koşu defteri.
    "insight_run": 90,
    # Soru hakkında, kişiye bağlanamaz → `[T§6.7]` "süresiz" satırı. Yine de
    # SONLU: etiket bir model ve bir istem sürümünün çıktısıdır.
    "question_segment": 1095,
    # Türetilmiş öğrenci profili — `student_summary` ile aynı süre.
    "student_segment_profile": 400,
}

#: Süpürmenin dokunduğu dokuz tablo, backend'in cevap anahtarlarıyla aynı
#: sırada: önce çocuk, sonra ebeveyn (FK'ler `NO ACTION`).
SWEEP_TABLES = (
    "zeka_attention_item",
    "zeka_run_pending",
    "zeka_run_failed_module",
    "zeka_question_segment_dimension",
    "zeka_student_summary",
    "zeka_recommendation",
    "zeka_run",
    "zeka_question_segment",
    "zeka_student_segment_profile",
)

#: Mezuniyet temizliğinin dokunduğu beş tablo.
PURGE_TABLES = (
    "zeka_attention_item",
    "zeka_student_summary",
    "zeka_student_segment_profile",
    "zeka_recommendation",
    "zeka_run_pending",
)


class BridgeUnavailable(RuntimeError):
    """Köprü henüz bağlı değil; çağrı yapılabilecek bir taşıma yok."""


class CapabilityRefused(Exception):
    """Sunucu `status: "err"` döndü. Kod makine okunabilir, kararlıdır."""

    def __init__(self, code: str, message: str, *, capability: str, school: str) -> None:
        super().__init__(f"{capability} reddedildi ({code}): {message}")
        self.code = code
        self.message = message
        self.capability = capability
        self.school = school


@runtime_checkable
class BridgeCaller(Protocol):
    """Deponun ihtiyaç duyduğu TEK taşıma yüzeyi."""

    async def call(
        self, capability: str, school: str, payload: dict[str, Any]
    ) -> dict[str, Any]: ...


class ProtocolCaller:
    """`BridgeProtocol`'u deponun gördüğü yüzeye çeviren ince adaptör.

    Taşıma TEKTİR (`BridgeProtocol.call_capability`); depo ise yalnız
    `call(capability, school, payload)` bilir. İkisini birbirine bağlayan
    yer burasıdır — ikinci bir taşıma yazılmaz.
    """

    def __init__(self, protocol: Any, *, timeout_secs: float | None = None) -> None:
        self._protocol = protocol
        self._timeout = timeout_secs

    async def call(
        self, capability: str, school: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._protocol.call_capability(
            capability, school, payload, timeout=self._timeout
        )


@dataclass(slots=True)
class WriteReport:
    """Yazma muhasebesi; `insight_run` satırını besler ve hata görünür kalır."""

    table: str = ""
    written: int = 0
    rejected: int = 0
    skipped_batches: int = 0

    @property
    def status(self) -> str:
        return "partial" if self.skipped_batches else "ok"


@dataclass(slots=True)
class RecordingCaller:
    """Gerçek köprü yerine çağrıları toplayan istemci (`--dry-run`, testler).

    Üretimde kullanılmaz. Cevap şekilleri sunucununkinin aynısıdır; böylece
    hat (`pipeline` → `store`) baştan sona koşar, yalnız taşıma değişir.
    """

    calls: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    fail_times: int = 0
    fail_capabilities: set[str] = field(default_factory=set)

    async def call(
        self, capability: str, school: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if self.fail_times > 0 or capability in self.fail_capabilities:
            if self.fail_times > 0:
                self.fail_times -= 1
            raise CapabilityRefused(
                "internal", "sahte köprü hatası", capability=capability, school=school
            )
        self.calls.append((capability, school, payload))
        if capability == CAP_SCHOOLS:
            return {"schools": []}
        if capability == CAP_PENDING:
            return {"students": []}
        if capability == CAP_SWEEP:
            return {"tables": {table: True for table in SWEEP_TABLES}}
        if capability == CAP_PURGE:
            return {"tables": {table: True for table in PURGE_TABLES}}
        rows = payload.get("rows")
        if isinstance(rows, list):
            written = len(rows)
        else:
            written = 1
        reply: dict[str, Any] = {"written": written}
        if capability == CAP_RECOMMENDATION:
            reply["rejected"] = 0
        return reply


# ===========================================================================
# Payload kurucuları — hesap tipleri → kablo sözlükleri
# ===========================================================================
#
# Alan adları backend'in `zeka_*` kolon adlarıyla aynıdır; iki taraf tek
# sözlüğü konuşur. `school` GÖNDERİLMEZ: okul çerçevededir ve satırda ikinci
# bir kopya, çelişebilecek ikinci bir yer olurdu.


def _retain_until(table: str, base_ms: int) -> int:
    return base_ms + RETENTION_DAYS[table] * clock.DAY_MS


def attention_items(summary: StudentSummary) -> list[dict[str, Any]]:
    """Dikkat maddeleri. Sıra **yazanın sırasıdır**, şiddete göre değil.

    Kanıtsız madde **yazılmaz**: `Recommendation` için geçerli olan kural
    dikkat maddesi için de geçerlidir — açıklanamayan şey gösterilmez.
    (Sunucu da aynı kuralı uygular; buradaki kontrol turu boşa çevirir.)
    """
    out: list[dict[str, Any]] = []
    for item in summary.attention or []:
        evidence = item.get("evidence") if isinstance(item, dict) else None
        if not evidence:
            log.warning(
                "kanıtsız dikkat maddesi atlandı (öğrenci=%s, tetik=%s)",
                summary.student,
                item.get("trigger") if isinstance(item, dict) else "?",
            )
            continue
        out.append(
            {
                "trigger": str(item.get("trigger")),
                # Ders yalnız not-eğilimi maddesinde vardır ve kanıtın
                # içindedir; üst düzeyde ayrı bir alan YOK.
                "course": evidence.get("course"),
                "fact": str(item.get("fact") or ""),
                "window_from": int(item.get("window_from") or 0),
                "window_to": int(item.get("window_to") or 0),
                "evidence": evidence,
            }
        )
    return out


def summary_rows(summaries: list[StudentSummary]) -> list[dict[str, Any]]:
    """`insight.summary.upsert` satırları — özet + dikkat maddeleri."""
    return [
        {
            "student": s.student,
            "marks": s.marks,
            "attendance": s.attendance,
            "submission": s.submission,
            "study": s.study,
            "confidence": str(s.confidence),
            "computed_at": s.computed_at,
            "retain_until": _retain_until("student_summary", s.computed_at),
            "attention": attention_items(s),
        }
        for s in summaries
    ]


def recommendation_rows(recs: list[Recommendation]) -> tuple[list[dict[str, Any]], int]:
    """`insight.recommendation.upsert` satırları + reddedilen sayısı.

    **Kanıtsız satır reddedilir** (`MODULLER.md` §2.10 yapısal kural 1):
    `limitation` dışında hiç kanıt yoksa satır yazılmaz.

    Kimlik GÖNDERİLMEZ: uuid7'yi yazan taraf —backend— üretir (depo kuralı:
    kimliği yazan üretir). `limitation` de `evidence`'a BURADA katılmaz;
    sunucu ekler.
    """
    rows: list[dict[str, Any]] = []
    rejected = 0
    for rec in recs:
        if not {k: v for k, v in rec.evidence.items() if k != "limitation"}:
            log.warning("kanıtsız tavsiye reddedildi: %s", rec.rule_id)
            rejected += 1
            continue
        ninety = _retain_until("recommendation", rec.computed_at)
        rows.append(
            {
                "audience": rec.audience,
                "product": rec.product,
                "rule_id": rec.rule_id,
                "rule_version": rec.rule_version,
                # Kapsam: kuralın kendi ayrımı (segment etiketi gibi) ya da
                # ders. `about` BURAYA KONMAZ; kendi alanı vardır.
                "scope": rec.scope or rec.course,
                "about": rec.about,
                "audience_role": str(rec.audience_role),
                "course": rec.course,
                "evidence": rec.evidence,
                "limitation": rec.limitation,
                "confidence": str(rec.confidence),
                "computed_at": rec.computed_at,
                "expires_at": rec.expires_at,
                "retain_until": min(rec.expires_at, ninety),
            }
        )
    return rows, rejected


def segment_rows(segments: list[QuestionSegment]) -> list[dict[str, Any]]:
    """`insight.segment.upsert` satırları — etiketler iç içe gider."""
    rows: list[dict[str, Any]] = []
    for seg in segments:
        rows.append(
            {
                "question": seg.question,
                "exam": seg.exam,
                "course": seg.course,
                "subject": seg.subject,
                "labels": {str(k): str(v) for k, v in seg.labels.items()},
                "confidences": {str(k): float(v) for k, v in seg.confidences.items()},
                "confidence": str(seg.confidence),
                "trap_choice": seg.trap_choice,
                "rationale": seg.rationale,
                "model": seg.model,
                "prompt_version": seg.prompt_version,
                "variant": seg.variant,
                "computed_at": seg.computed_at,
                "retain_until": _retain_until("question_segment", seg.computed_at),
                "downstream_dimensions": list(seg.downstream_dimensions),
                "experimental_dimensions": list(seg.experimental_dimensions),
            }
        )
    return rows


def profile_rows(profiles: list[StudentSegmentProfile]) -> list[dict[str, Any]]:
    """`insight.profile.upsert` satırları.

    Güven kapısının **altındaki** satırlar da yazılır: depo ham olguyu tutar,
    gösterme kararını `recommend.py` verir.
    """
    return [
        {
            "student": p.student,
            "dimension": p.dimension,
            "label": p.label,
            "n_answers": p.n_answers,
            "n_correct": p.n_correct,
            "accuracy": round(p.accuracy, 6),
            "overall_n_answers": p.overall_n_answers,
            "overall_accuracy": round(p.overall_accuracy, 6),
            "contrast": round(p.contrast, 6),
            "confidence": str(p.confidence),
            "computed_at": p.computed_at,
            "retain_until": _retain_until("student_segment_profile", p.computed_at),
        }
        for p in profiles
    ]


#: `insight.run.upsert` payload'ının kabul ettiği alanlar. Fazlası
#: gönderilmez: sözleşmede olmayan bir alan `invalid_payload` üretirdi.
RUN_FIELDS = (
    "run_day",
    "started_at",
    "finished_at",
    "status",
    "duration_ms",
    "students_total",
    "students_ok",
    "students_failed",
    "students_skipped",
    "rows_written",
    "budget_exceeded",
    "budget_ms",
    "retain_until",
    "pending_students",
    "failed_modules",
)


def run_row(run_row: dict[str, Any], key: str) -> dict[str, Any]:
    """Koşu defteri satırı + `run_day` + varsayılan `retain_until`.

    Gün backend'de YENİDEN TÜRETİLMEZ: TR gününü bilen taraf bu taraf, o
    yüzden `key`'in son on karakteri (`YYYY-MM-DD`) açıkça gönderilir.
    """
    row = {name: run_row.get(name) for name in RUN_FIELDS if name in run_row}
    row.setdefault("run_day", key[-10:])
    started = int(run_row.get("started_at") or 0)
    if row.get("retain_until") is None:
        row["retain_until"] = _retain_until("insight_run", started)
    row.setdefault("pending_students", [])
    row.setdefault("failed_modules", [])
    return row


# ===========================================================================
# Depo
# ===========================================================================


class BridgeStore:
    """Okul dizini + okul başına depo — hepsi köprüden.

    Zamanlayıcı `store_for(school)` ile o okulun deposunu ister; dönen nesne
    `pipeline`'ın beklediği sekiz metodu taşır. Paylaşılan bir depo YOKTUR ve
    olmamalıdır: yanlış okula yazmanın en kolay yolu paylaşılan bir
    nesnenin okul alanını unutmaktır; burada okul nesnenin kimliğindedir.
    """

    def __init__(
        self,
        caller: BridgeCaller | Callable[[], BridgeCaller | None],
        *,
        batch_size: int = BATCH_SIZE,
        attempts: int = MAX_ATTEMPTS,
        timeout_secs: float | None = None,
    ) -> None:
        self._caller = caller
        self._batch_size = batch_size
        self._attempts = attempts
        #: Okuma çağrıları için zaman aşımı (yazma grupları için de aynısı).
        self._timeout = timeout_secs

    # -- taşıma -------------------------------------------------------------

    def caller(self) -> BridgeCaller:
        """Şu an bağlı taşıma. Yoksa `BridgeUnavailable` — sessizce yutulmaz."""
        target = self._caller() if callable(self._caller) else self._caller
        if target is None:
            raise BridgeUnavailable(
                "köprü henüz bağlı değil; insight.* çağrısı yapılamaz"
            )
        return target

    async def _call(self, capability: str, school: str, payload: dict[str, Any]) -> dict[str, Any]:
        target = self.caller()
        if capability in DEPLOYMENT_SCOPED:
            school = ""
        call = target.call
        try:
            reply = call(capability, school, payload)
            if self._timeout is None:
                return await reply
            import asyncio

            return await asyncio.wait_for(reply, timeout=self._timeout)
        except CapabilityRefused:
            raise
        except Exception as exc:  # noqa: BLE001 — taşıma hatası aynı sözleşmeye bağlanır
            raise CapabilityRefused(
                "unavailable", str(exc), capability=capability, school=school
            ) from exc

    async def _attempt(
        self,
        capability: str,
        payload: dict[str, Any],
        *,
        school: str,
        table: str,
        count: int,
    ) -> dict[str, Any] | None:
        """Bir grubu `MAX_ATTEMPTS` kez dener; ikinci düşüşte `None` döner."""
        for attempt in range(1, self._attempts + 1):
            try:
                return await self._call(capability, school, payload)
            except Exception as exc:  # noqa: BLE001 — hat devam etmeli
                log.warning(
                    "köprü yazması düştü (tablo=%s, deneme=%d/%d): %s",
                    table,
                    attempt,
                    self._attempts,
                    exc,
                )
        log.warning("grup atlandı (tablo=%s, satır=%d)", table, count)
        return None

    # -- okuma --------------------------------------------------------------

    async def active_schools(self) -> list[str]:
        """Bu dağıtımdaki **aktif** okullar (`insight.schools.list`).

        Okul listesi artık yapılandırmadan DEĞİL backend'den gelir. Okunamazsa
        hata yükselir; zamanlayıcı bunu yakalar ve turu okulsuz koşar
        (`scheduler._listing`), yani açılış da bir tik de düşmez.
        """
        reply = await self._call(CAP_SCHOOLS, "", {})
        schools = reply.get("schools")
        if not isinstance(schools, list):
            raise CapabilityRefused(
                "invalid_payload",
                f"okul listesi beklenen biçimde değil: {reply!r}",
                capability=CAP_SCHOOLS,
                school="",
            )
        return sorted({str(s) for s in schools if str(s).strip()})

    def store_for(self, school: str) -> "SchoolStore":
        """Okula bağlı depo. Ağ beklemez: nesne kurmak bir çağrı değildir."""
        return SchoolStore(self, school)

    async def close(self) -> None:
        """Simetri için: kapatılacak bağlantı YOKTUR."""
        return None


class SchoolStore:
    """Tek okulun deposu. Okul nesnenin kimliğidir, çağrının argümanı değil."""

    def __init__(self, parent: BridgeStore, school: str) -> None:
        self._parent = parent
        self._school = school

    @property
    def school(self) -> str:
        return self._school

    async def _send(self, capability: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._parent._call(capability, self._school, payload)

    # -- yazma --------------------------------------------------------------

    async def _chunked(self, capability: str, rows: list[dict[str, Any]], *, table: str) -> WriteReport:
        """Grup grup yaz. Düşen grup raporda GÖRÜNÜR kalır."""
        report = WriteReport(table=table)
        for start in range(0, len(rows), self._parent._batch_size):
            chunk = rows[start : start + self._parent._batch_size]
            reply = await self._parent._attempt(
                capability,
                {"rows": chunk},
                school=self._school,
                table=table,
                count=len(chunk),
            )
            if reply is None:
                report.skipped_batches += 1
                continue
            report.written += int(reply.get("written", len(chunk)))
            if reply.get("rejected"):
                report.rejected += int(reply["rejected"])
        return report

    async def write_summaries(self, summaries: list[StudentSummary]) -> WriteReport:
        """Özetleri ve dikkat maddelerini yazar (dikkat: sil-ve-yaz, sunucuda)."""
        return await self._chunked(CAP_SUMMARY, summary_rows(summaries), table="zeka_student_summary")

    async def write_recommendations(self, recs: list[Recommendation]) -> WriteReport:
        """Tavsiyeleri yazar. **Kanıtsız satır reddedilir.**"""
        rows, rejected = recommendation_rows(recs)
        report = await self._chunked(CAP_RECOMMENDATION, rows, table="zeka_recommendation")
        report.rejected += rejected
        return report

    async def write_question_segments(self, segments: list[QuestionSegment]) -> WriteReport:
        """Soru segment etiketlerini ve boyut ayrımını yazar."""
        return await self._chunked(CAP_SEGMENT, segment_rows(segments), table="zeka_question_segment")

    async def write_segment_profiles(self, profiles: list[StudentSegmentProfile]) -> WriteReport:
        """Öğrenci segment profillerini yazar."""
        return await self._chunked(CAP_PROFILE, profile_rows(profiles), table="zeka_student_segment_profile")

    async def write_run(self, row: dict[str, Any], key: str) -> bool:
        """Koşu defteri satırını yazar (koşu başında ve sonunda birer kez).

        Gün `key`'den burada çözülür (TR günü), `retain_until` burada
        varsayılanlanır. `False` = yazılamadı; çağıran bunu başarı saymaz.
        """
        payload = {"run": run_row(row, key)}
        reply = await self._parent._attempt(
            CAP_RUN, payload, school=self._school, table="zeka_run", count=1
        )
        return reply is not None

    # -- okuma --------------------------------------------------------------

    async def last_pending(self, school: str = "") -> list[str]:
        """Bu okulun son koşusundan devreden öğrenci kimlikleri.

        `school` KULLANILMIYOR: okul çerçevededir, nesnenin kimliğindedir.
        Parametre, çağrı yerlerini değiştirmemek için duruyor.

        Okunamazsa boş liste döner: devretmemek, yanlış listeyle koşmaktan
        iyidir.
        """
        try:
            reply = await self._send(CAP_PENDING, {})
        except Exception as exc:  # noqa: BLE001
            log.warning("bekleyen liste okunamadı (okul=%s): %s", self._school, exc)
            return []
        students = reply.get("students")
        if not isinstance(students, list):
            log.warning("bekleyen liste beklenen biçimde değil (okul=%s)", self._school)
            return []
        return [str(s) for s in students]

    # -- süpürme ------------------------------------------------------------

    async def sweep(self, now_ms: int) -> dict[str, bool]:
        """Saklama süresi dolmuş satırları sildirir.

        `now_ms` GÖNDERİLMEZ: saati backend kendi damgalar — iki saatli bir
        süpürme, "hangi gün" sorusuna iki cevap verirdi. Parametre çağrı
        yerlerini değiştirmemek için duruyor.

        Dönen sözlük tablo başına karardır; düşen tablo `False` olur ve CLI
        sıfırdan farklı çıkar.
        """
        try:
            reply = await self._send(CAP_SWEEP, {})
        except Exception as exc:  # noqa: BLE001
            log.warning("süpürme düştü (okul=%s): %s", self._school, exc)
            return {table: False for table in SWEEP_TABLES}
        tables = reply.get("tables")
        if not isinstance(tables, dict):
            log.warning("süpürme cevabı beklenen biçimde değil (okul=%s)", self._school)
            return {table: False for table in SWEEP_TABLES}
        return {table: bool(tables.get(table)) for table in SWEEP_TABLES}

    async def purge_departed(self, school: str, active_students: list[str]) -> bool:
        """Artık öğrenci olmayanların türetilmiş verisini sildirir.

        `MODULLER.md` §2.11 adım 3: "mezunun ham verisi arşivde kalabilir;
        **profili kalmamalıdır**." `question_segment` buraya girmez: o satır
        bir soru hakkındadır, kişiye bağlanamaz.

        **Boş liste çağrı YAPMAZ**: boş liste "okulda kimse yok" değil,
        "liste çekilemedi" demektir ve herkesin verisini silerdi. Sunucu da
        boş listeyi `invalid_payload` ile reddeder; buradaki kapı ondan önce
        durur.
        """
        if not active_students:
            log.warning("mezuniyet temizliği atlandı (okul=%s): aktif liste boş", self._school)
            return False
        try:
            reply = await self._send(CAP_PURGE, {"students": [str(s) for s in active_students]})
        except Exception as exc:  # noqa: BLE001
            log.warning("mezuniyet temizliği düştü (okul=%s): %s", self._school, exc)
            return False
        tables = reply.get("tables")
        if not isinstance(tables, dict):
            return False
        return all(bool(tables.get(table)) for table in PURGE_TABLES)


__all__ = [
    "BATCH_SIZE",
    "MAX_ATTEMPTS",
    "CAP_SUMMARY",
    "CAP_RECOMMENDATION",
    "CAP_SEGMENT",
    "CAP_PROFILE",
    "CAP_RUN",
    "CAP_PENDING",
    "CAP_SWEEP",
    "CAP_PURGE",
    "CAP_SCHOOLS",
    "BridgeStore",
    "SchoolStore",
    "BridgeCaller",
    "ProtocolCaller",
    "BridgeUnavailable",
    "CapabilityRefused",
    "RecordingCaller",
    "WriteReport",
    "RETENTION_DAYS",
    "SWEEP_TABLES",
    "PURGE_TABLES",
    "MAX_LIST_ROWS",
    "attention_items",
    "summary_rows",
    "recommendation_rows",
    "segment_rows",
    "profile_rows",
    "run_row",
    "rows_or_err",
]
