"""ZEKA'nın **kendi** SurrealDB veritabanına yazma katmanı.

Kaynak: `spec/MODULLER.md` §2.11 `insight::store`, §4 depolama şeması.
Şema DDL'i: `service/schema/zeka.surql`.

---------------------------------------------------------------------------
TEK VE MUTLAK KURAL
---------------------------------------------------------------------------
**Okul veritabanına asla yazılmaz.** ZEKA okul verisini yalnız `Source`
arayüzü üzerinden **okur**; yazma yolu diye bir şey yoktur. Bu modülün
dokunduğu tek yer ZEKA'nın kendi veritabanıdır ve orada yalnız beş tablo
vardır: `student_summary`, `recommendation`, `insight_run`,
`question_segment`, `student_segment_profile`.

`MODULLER.md` §2.10 yapısal kural 3 ("otomatik eylem yok") bu sayede şema
düzeyinde garantidir: bu tablolar yalnız gösterilecek metni ve kanıtı tutar,
hiçbir yazma yolu buradan okuyup başka bir tabloyu güncellemez.

---------------------------------------------------------------------------
Sürücü bağımsızlığı
---------------------------------------------------------------------------
Bu modül bir SurrealDB sürücüsü **import etmez**. `DbClient` protokolünü
uygular; gerçek istemciyi hattı kuran taraf verir. Böylece testler ve
`cli.py --dry-run` gerçek bir veritabanı olmadan çalışır.
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import logging
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .compute import clock
from .compute.model import (
    QuestionSegment,
    Recommendation,
    StudentSegmentProfile,
    StudentSummary,
)

log = logging.getLogger(__name__)

#: `schema/zeka.surql` — ZEKA veritabaninin DDL kaynagi.
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "zeka.surql"

# `MODULLER.md` §2.11 adım 1: 500 satırlık gruplar halinde toplu UPSERT.
BATCH_SIZE = 500

# `MODULLER.md` §2.11 hata davranışı: bir grup düşerse yeniden denenir;
# **ikinci düşüşte** grup atlanır, `warn` loglanır, hat devam eder.
MAX_ATTEMPTS = 2

# --- Saklama süreleri (`[T§6.7]` tablosu, `MODULLER.md` §2.11 adım 2) --------
#
# `question_stat` bu sürümde üretilmiyor. Üretilen beş tablodan dördü kişisel
# veriye bağlanabilir; `question_segment` bağlanamaz ama o da sonlu süre alır
# (gerekçesi aşağıda). Süresi olmayan tablo YOKTUR: süpürme bu sözlüğü gezer,
# listede olmayan tablo hiç süpürülmez ve sessizce sonsuza kadar kalırdı.
RETENTION_DAYS = {
    # "Dönem + 1 yıl" — türetilmiş veri, ham veriden yeniden üretilebilir.
    "student_summary": 400,
    # "expires_at veya 90 gün — hangisi önce." Bayat tavsiye zararlıdır.
    "recommendation": 90,
    # Koşu defteri.
    "insight_run": 90,
    # Soru hakkında, kişiye bağlanamaz → `[T§6.7]` "süresiz" satırı. Yine de
    # SONLU: etiket bir model ve bir istem sürümünün çıktısıdır, sürüm
    # değişince bayatlar. 3 yıl = ~üç müfredat döngüsü.
    "question_segment": 1095,
    # Türetilmiş öğrenci profili — `student_summary` ile aynı süre.
    "student_segment_profile": 400,
}


@runtime_checkable
class DbClient(Protocol):
    """ZEKA veritabanı istemcisinin ihtiyaç duyulan tek yüzeyi."""

    async def query(self, sql: str, variables: dict[str, Any]) -> Any: ...


class CollectingClient:
    """Gerçek veritabanı yerine ifadeleri toplayan istemci.

    `cli.py --dry-run` ve testler için. Üretimde kullanılmaz.
    """

    def __init__(self) -> None:
        self.statements: list[tuple[str, dict[str, Any]]] = []
        self.fail_times = 0

    async def query(self, sql: str, variables: dict[str, Any]) -> Any:
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("sahte yazma hatası")
        self.statements.append((sql, variables))
        return []


# ===========================================================================
# GERCEK SurrealDB istemcisi -- yalnizca standart kutuphane
# ===========================================================================
#
# NEDEN HTTP `/rpc`, NEDEN `surreal sql` DEGIL:
#   * `surreal sql` araci standart girdiden gelen buyuk govdeyi **sessizce
#     keser** ve cok satirli ifadeleri satir satir ayristirir; tohum yukleme
#     deneyiminde yarim yuklenen dosyalar buradan cikti (bkz.
#     `tools/load_seed.py` bas aciklamasi).
#   * HTTP `/sql` ucu degisken (`$v`) tasiyamaz -- govde duz metindir. Toplu
#     UPSERT'in icerigi ic ice sozluklerdir; bunlari SurrealQL metnine gomulu
#     yazmak kacis hatasina acik olurdu.
#   * `/rpc` ucu JSON-RPC'dir: `query` yontemi `[sql, variables]` alir.
#     Degiskenler tip korunarak gider, kacis sorunu **yapisal olarak** yoktur.
#
# EN ONEMLI DAVRANIS: SurrealDB basarisiz ifade icin de **HTTP 200** doner;
# hata, sonuc dizisindeki `status: "ERR"` alanindadir. Bu yuzden asagidaki
# istemci her ifadenin durumunu tek tek denetler ve ilk `ERR`'de patlar.
# Denetlemeyen bir istemci "yazdim" der ve hicbir sey yazilmamis olur.
#
# SURUM NOTU: `type::thing()` SurrealDB 3'te **YOKTUR**, karsiligi
# `type::record()`. Bu modulun onceki hali `type::thing` kullaniyordu ve hicbir
# zaman gercek bir veritabanina karsi kosmadigi icin fark edilmemisti.

SURREAL_TIMEOUT_SECS = 60.0


class SurrealError(RuntimeError):
    """Bir SurrealQL ifadesi `status: ERR` dondurdu ya da tasima dustu."""

    def __init__(self, message: str, *, statement: str = "") -> None:
        super().__init__(message)
        self.statement = statement


class SurrealHttpClient:
    """`DbClient` protokolunun gercek uygulamasi -- stdlib `urllib` + `/rpc`.

    Ek bagimlilik **yoktur**: ne `requests`, ne `surrealdb` surucusu. Senkron
    `urllib` cagrisi `asyncio.to_thread` ile olay dongusunden cikarilir.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        namespace: str,
        database: str,
        user: str = "root",
        password: str = "root",
        timeout: float = SURREAL_TIMEOUT_SECS,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.namespace = namespace
        self.database = database
        self._timeout = timeout
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self._auth = "Basic " + token
        #: Kac SurrealQL ifadesi calisti -- kanit sayaci.
        self.statement_count = 0

    # -- tasima -------------------------------------------------------------

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        request = urllib.request.Request(self.endpoint + "/rpc", data=body)
        request.add_header("Accept", "application/json")
        request.add_header("Content-Type", "application/json")
        request.add_header("surreal-ns", self.namespace)
        request.add_header("surreal-db", self.database)
        request.add_header("Authorization", self._auth)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # 4xx / 5xx
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise SurrealError(f"HTTP {exc.code}: {detail}") from exc

    def query_sync(self, sql: str, variables: dict[str, Any] | None = None) -> list:
        """Tek istek; **her** ifadenin `status` alani denetlenir."""
        envelope = self._post(
            {"id": 1, "method": "query", "params": [sql, variables or {}]}
        )
        if envelope.get("error"):
            message = envelope["error"].get("message", str(envelope["error"]))
            raise SurrealError(f"ayristirma/RPC hatasi: {message}", statement=sql)
        results = envelope.get("result") or []
        for item in results:
            if isinstance(item, dict) and item.get("status") not in (None, "OK"):
                raise SurrealError(
                    f"ifade reddedildi: {str(item.get('result'))[:400]}",
                    statement=sql,
                )
        self.statement_count += len(results)
        return results

    async def query(self, sql: str, variables: dict[str, Any]) -> Any:
        return await asyncio.to_thread(self.query_sync, sql, variables)

    # -- kurulum ------------------------------------------------------------

    def ensure_namespace(self) -> None:
        """ns/db yoksa yaratir. Tekrar edilebilir, zararsiz.

        Ilk `DEFINE NAMESPACE` istegi, namespace henuz yokken `NotFound`
        dondurebilir (baglanti basligi var olmayan ns'i isaret ediyor); bu
        yuzden sonucu denetlenmeden gonderilir. Ikinci istek gercek denetimi
        yapar.
        """
        self._post(
            {
                "id": 1,
                "method": "query",
                "params": [f"DEFINE NAMESPACE IF NOT EXISTS {self.namespace};", {}],
            }
        )
        self.query_sync(f"DEFINE DATABASE IF NOT EXISTS {self.database};")

    def close(self) -> None:  # simetri icin; urllib kalici baglanti tutmaz
        return None


# --- DDL yukleyici ---------------------------------------------------------


def split_statements(text: str) -> list[str]:
    """SurrealQL metnini ifadelere boler.

    Dize farkindadir: tirnak icindeki `;` ifade sonu **sayilmaz**. `--` yorum
    satirlari atilir. Desen `tools/load_seed.py` ile aynidir; oradaki aci
    `surreal sql`'in cok satirli ifadeyi satir satir ayristirmasiydi.
    """
    out: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    index = 0
    size = len(text)
    while index < size:
        ch = text[index]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch == "'" or ch == '"':
            quote = ch
            buf.append(ch)
        elif ch == "-" and text.startswith("--", index):
            end = text.find("\n", index)
            index = size if end < 0 else end
            continue
        elif ch == ";":
            statement = ("".join(buf) + ";").strip()
            if statement and statement != ";":
                out.append(statement)
            buf = []
        else:
            buf.append(ch)
        index += 1
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


@dataclasses.dataclass(slots=True)
class SchemaReport:
    """`apply_schema` muhasebesi -- kac ifade gonderildi, kaci gecti."""

    total: int = 0
    applied: int = 0
    errors: list[str] = dataclasses.field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and self.total == self.applied


def load_schema_text(path: Any = None) -> str:
    """`schema/zeka.surql` metnini okur."""
    target = Path(path) if path else SCHEMA_PATH
    return target.read_text(encoding="utf-8")


def apply_schema(
    client: SurrealHttpClient, ddl_text: str | None = None
) -> SchemaReport:
    """Semayi **ifade ifade** yukler ve her birinin sonucunu dogrular.

    Toplu gonderim KASITLI OLARAK yapilmaz: bir ifade duserse hangisinin
    dustugunu bilmek gerekir. Tek parca gondermek, tam da bu projede yasanan
    "yari yuklenmis sema" durumunu ureten desendi.
    """
    report = SchemaReport()
    for statement in split_statements(ddl_text or load_schema_text()):
        report.total += 1
        try:
            client.query_sync(statement)
            report.applied += 1
        except SurrealError as exc:
            report.errors.append(f"{statement.splitlines()[0][:90]} -> {exc}")
    return report


def schema_field_types(client: SurrealHttpClient, table: str) -> dict[str, str]:
    """`INFO FOR TABLE` ciktisindan alan -> DDL metni sozlugu uretir."""
    rows = client.query_sync(f"INFO FOR TABLE {table};")
    info = rows[0].get("result") if rows else None
    if not isinstance(info, dict):
        raise SurrealError(f"INFO FOR TABLE {table} beklenen bicimde degil")
    return dict(info.get("fields") or {})


def schema_tables(client: SurrealHttpClient) -> dict[str, str]:
    """`INFO FOR DB` ciktisindan tablo -> DDL metni sozlugu uretir."""
    rows = client.query_sync("INFO FOR DB;")
    info = rows[0].get("result") if rows else None
    if not isinstance(info, dict):
        raise SurrealError("INFO FOR DB beklenen bicimde degil")
    return dict(info.get("tables") or {})


def _drop_nulls(row: dict[str, Any]) -> dict[str, Any]:
    """Ust duzey `None` alanlarini satirdan cikarir.

    SurrealDB 3'te `option<string>` gercekte `none | string` demektir ve
    **`NULL` kabul etmez**: Python'un `None` degeri JSON `null` olarak gider,
    veritabani da `Couldn't coerce value ... Expected none | string but found
    NULL` diyerek TUM transaction'i reddeder. Yani tek bir bos `dismiss_reason`
    alani, 500 satirlik grubun tamamini dusururdu.

    Alani hic gondermemek dogru karsiliktir: SCHEMAFULL tabloda tanimli ama
    verilmemis `option<...>` alani `NONE` olur.

    Yalnizca UST DUZEY anahtarlar temizlenir; FLEXIBLE nesnelerin (`marks`,
    `evidence`, dikkat maddeleri) icindeki `null` degerler hesap ciktisinin
    parcasidir ve oldugu gibi saklanir.
    """
    return {key: value for key, value in row.items() if value is not None}


# --- Kimlik biçimli metinler: SurrealDB'nin sessiz `record` dönüşümü ---------
#
# ÖLÇÜLDÜ (SurrealDB 3, HTTP `/rpc`, 2026-09-15): değişken olarak gönderilen
# `"user:01K..."` biçimli bir JSON **metni**, uçta `record` değerine çevrilir.
# `TYPE string` bir alana yazılmak istendiğinde de:
#
#   Couldn't coerce value for field `exam`: Expected `none | string`
#   but found `exam:E1`
#
# diyerek **bütün transaction** reddedilir. Yani tek bir gerçek öğrenci
# kimliği (`user:<ULID>`) 500 satırlık grubun tamamını düşürürdü. Bu, fikstür
# kimlikleri (`student-00`) iki nokta taşımadığı için testlerde hiç görünmeyen
# bir tuzaktı.
#
# Çözüm: satır bir `$v` değişkeni olarak **bütün hâlde** gönderilmez; SurrealQL
# tarafında alan alan bir nesne kurulur ve kimlik biçimli değerler
# `type::string()` ile metne geri çevrilir. Diziler için karşılığı
# `array::map(..., |$x| type::string($x))`. İkisi de uca karşı doğrulandı.
#
# FLEXIBLE nesnelerin (`marks`, `evidence`, dikkat maddeleri) içindeki kimlikler
# dokunulmadan geçer: o alanlar tip denetimine girmez ve okurken yine metin
# olarak dönerler.
_RECORD_LIKE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*:\S+$")
#: Alan adı güvenliği — satır anahtarları koda aittir, yine de SurrealQL metnine
#: gömülmeden önce denetlenir.
_SAFE_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _is_record_like(value: Any) -> bool:
    return isinstance(value, str) and bool(_RECORD_LIKE.match(value))


def _merge_object(var: str, row: dict[str, Any]) -> str:
    """Satırı SurrealQL nesne sözdizimine çevirir (değerler değişkenden gelir).

    Değerlerin kendisi **metne gömülmez**: her alan `$vN.alan` olarak
    başvurulur, yalnız kaçış sorunu olmayan alan adları metne girer.
    """
    parts: list[str] = []
    for key, value in row.items():
        if not _SAFE_FIELD.match(key):
            raise ValueError(f"güvensiz alan adı: {key!r}")
        ref = f"${var}.{key}"
        if _is_record_like(value):
            expr = f"type::string({ref})"
        elif isinstance(value, list) and any(_is_record_like(v) for v in value):
            expr = f"array::map({ref}, |$x| type::string($x))"
        else:
            expr = ref
        parts.append(f"{key}: {expr}")
    return "{ " + ", ".join(parts) + " }"


def _retain_until(table: str, base_ms: int) -> int:
    return base_ms + RETENTION_DAYS[table] * clock.DAY_MS


def summary_row(summary: StudentSummary) -> dict[str, Any]:
    """`student_summary` satırı — `schema/zeka.surql` §1 ile birebir."""
    return {
        "school": summary.school,
        "student": summary.student,
        "marks": summary.marks,
        "attendance": summary.attendance,
        "submission": summary.submission,
        "study": summary.study,
        # Dikkat maddeleri: her öğe tek tetikleyici. Skor/sıra alanı YOK.
        "attention": summary.attention,
        "confidence": str(summary.confidence),
        "computed_at": summary.computed_at,
        "retain_until": _retain_until("student_summary", summary.computed_at),
    }


def recommendation_row(rec: Recommendation) -> dict[str, Any]:
    """`recommendation` satırı — `schema/zeka.surql` §2 ile birebir.

    `retain_until = min(expires_at, created_at + 90 gün)` (`[T§6.7]`).
    """
    ninety = _retain_until("recommendation", rec.computed_at)
    return {
        "school": rec.school,
        "audience": rec.audience,
        "about": rec.about,
        "audience_role": str(rec.audience_role),
        "product": rec.product,
        "course": rec.course,
        "rule_id": rec.rule_id,
        "rule_version": rec.rule_version,
        "evidence": {**rec.evidence, "limitation": rec.limitation},
        "confidence": str(rec.confidence),
        "created_at": rec.computed_at,
        "expires_at": rec.expires_at,
        "retain_until": min(rec.expires_at, ninety),
        "dismissed_at": None,
        "dismissed_by": None,
        "dismiss_reason": None,
    }


def question_segment_row(seg: QuestionSegment) -> dict[str, Any]:
    """`question_segment` satırı — `schema/zeka.surql` §4 ile birebir.

    Boyut adları **doğrudan alan adı** olur (`labels` sözlüğü yayılır). Bu
    bilinçli: `rubric.py` yeni bir boyut eklerse SCHEMAFULL tablo satırı
    reddeder ve hata **gürültülü** olur. Sessizce düşen bir boyut, "etiketledik"
    denip hiçbir yere yazılmamasının ta kendisi olurdu.
    """
    return {
        "school": seg.school,
        "question": seg.question,
        "exam": seg.exam,
        "course": seg.course,
        "subject": seg.subject,
        **{name: str(label) for name, label in seg.labels.items()},
        **{
            f"confidence_{name}": float(value)
            for name, value in seg.confidences.items()
        },
        "confidence": str(seg.confidence),
        "downstream_dimensions": list(seg.downstream_dimensions),
        "experimental_dimensions": list(seg.experimental_dimensions),
        "trap_choice": seg.trap_choice,
        "rationale": seg.rationale,
        "model": seg.model,
        "prompt_version": seg.prompt_version,
        "variant": seg.variant,
        "computed_at": seg.computed_at,
        "retain_until": _retain_until("question_segment", seg.computed_at),
    }


def student_segment_profile_row(profile: StudentSegmentProfile) -> dict[str, Any]:
    """`student_segment_profile` satırı — `schema/zeka.surql` §5 ile birebir.

    `accuracy` ve `contrast` satıra **hesaplanmış** yazılır; okuyan tarafın
    (frontend, backend) bölme yapması gerekmesin ve iki taraf farklı sonuç
    bulmasın diye. `contrast` bu tablonun asıl ölçüsüdür — açıklaması
    `compute/segments.py` baş yorumunda.
    """
    return {
        "school": profile.school,
        "student": profile.student,
        "dimension": profile.dimension,
        "label": profile.label,
        "n_answers": profile.n_answers,
        "n_correct": profile.n_correct,
        "accuracy": round(profile.accuracy, 6),
        "overall_n_answers": profile.overall_n_answers,
        "overall_accuracy": round(profile.overall_accuracy, 6),
        "contrast": round(profile.contrast, 6),
        "confidence": str(profile.confidence),
        "computed_at": profile.computed_at,
        "retain_until": _retain_until(
            "student_segment_profile", profile.computed_at
        ),
    }


@dataclasses.dataclass(slots=True)
class WriteReport:
    """Yazma muhasebesi; `insight_run` satırını besler."""

    written: int = 0
    rejected: int = 0
    skipped_batches: int = 0


class Store:
    """Toplu UPSERT + süpürme."""

    def __init__(self, client: DbClient, *, batch_size: int = BATCH_SIZE) -> None:
        self._client = client
        self._batch_size = batch_size

    # -- yazma --------------------------------------------------------------

    async def _upsert_batch(
        self,
        table: str,
        rows: list[tuple[str, dict[str, Any]]],
        *,
        mode: str = "CONTENT",
    ) -> bool:
        """Tek transaction içinde bir grup UPSERT. Başarıyı döndürür.

        `mode="CONTENT"` satırı tümüyle değiştirir; `mode="MERGE"` yalnız
        verilen alanları günceller ve dokunulmayanları korur. `recommendation`
        MERGE kullanır: `dismissed_at` / `dismissed_by` / `dismiss_reason`
        alanları **insan müdahalesi izidir** (KVKK m.11) ve hesap hattı onları
        hiç üretmez. CONTENT ile yazılsaydı, her gece koşusu kullanıcının
        "bu tavsiye faydalı değil" kaydını sessizce silerdi.

        Kayıt anahtarları kompozit → tekillik yapısaldır, UNIQUE indekse gerek
        yok ve tekrar çalıştırma zararsızdır (`MODULLER.md` §2.11 adım 1).
        """
        parts = ["BEGIN TRANSACTION;"]
        variables: dict[str, Any] = {}
        for i, (key, row) in enumerate(rows):
            clean = _drop_nulls(row)
            parts.append(
                f"UPSERT type::record('{table}', $k{i}) {mode} "
                f"{_merge_object(f'v{i}', clean)};"
            )
            variables[f"k{i}"] = key
            variables[f"v{i}"] = clean
        parts.append("COMMIT TRANSACTION;")
        sql = "\n".join(parts)

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                await self._client.query(sql, variables)
                return True
            except Exception as exc:  # noqa: BLE001 — hat devam etmeli
                log.warning(
                    "toplu yazma düştü (tablo=%s, deneme=%d/%d): %s",
                    table,
                    attempt,
                    MAX_ATTEMPTS,
                    exc,
                )
        log.warning("grup atlandı (tablo=%s, satır=%d)", table, len(rows))
        return False

    async def _write_rows(
        self,
        table: str,
        rows: list[tuple[str, dict[str, Any]]],
        *,
        mode: str = "CONTENT",
    ) -> WriteReport:
        report = WriteReport()
        for start in range(0, len(rows), self._batch_size):
            chunk = rows[start : start + self._batch_size]
            if await self._upsert_batch(table, chunk, mode=mode):
                report.written += len(chunk)
            else:
                report.skipped_batches += 1
        return report

    async def write_summaries(self, summaries: list[StudentSummary]) -> WriteReport:
        rows = [(s.record_key(), summary_row(s)) for s in summaries]
        return await self._write_rows("student_summary", rows)

    async def write_recommendations(
        self, recs: list[Recommendation]
    ) -> WriteReport:
        """Tavsiyeleri yazar. **Kanıtsız satır reddedilir.**

        `Recommendation` zaten boş kanıtla kurulamaz; buradaki ikinci kontrol,
        sözlükten yeniden kurulan (örn. yeniden oynatılan) satırlar içindir —
        `MODULLER.md` §2.10 yapısal kural 1 depolama katmanında da geçerlidir.
        """
        rows: list[tuple[str, dict[str, Any]]] = []
        rejected = 0
        for rec in recs:
            row = recommendation_row(rec)
            evidence = row.get("evidence") or {}
            # `limitation` dışında hiç kanıt yoksa satır kanıtsızdır.
            if not {k: v for k, v in evidence.items() if k != "limitation"}:
                log.warning("kanıtsız tavsiye reddedildi: %s", rec.rule_id)
                rejected += 1
                continue
            rows.append((rec.record_key(), row))
        # MERGE: insan müdahalesi izi (`dismissed_*`) korunur.
        report = await self._write_rows("recommendation", rows, mode="MERGE")
        report.rejected = rejected
        return report

    async def write_question_segments(
        self, segments: list[QuestionSegment]
    ) -> WriteReport:
        """Soru segment etiketlerini yazar.

        **MERGE**, CONTENT değil: aynı soruya ileride başka bir kaynaktan alan
        eklenebilir (örn. insan doğrulaması) ve gece koşusu onu silmemelidir —
        `recommendation` tablosundaki `dismissed_*` ile aynı gerekçe.
        """
        rows = [(s.record_key(), question_segment_row(s)) for s in segments]
        return await self._write_rows("question_segment", rows, mode="MERGE")

    async def write_segment_profiles(
        self, profiles: list[StudentSegmentProfile]
    ) -> WriteReport:
        """Öğrenci segment profillerini yazar.

        Güven kapısının **altındaki** satırlar da yazılır: depo ham olguyu
        tutar, gösterme/tavsiye kararını `recommend.py` verir. Kapının depoda
        değil kuralda olmasının sebebi, eşiğin ölçümle değişebilmesidir —
        eşik değişince veriyi yeniden üretmek gerekmesin.
        """
        rows = [
            (p.record_key(), student_segment_profile_row(p)) for p in profiles
        ]
        return await self._write_rows("student_segment_profile", rows, mode="MERGE")

    async def write_run(self, run_row: dict[str, Any], key: str) -> bool:
        """`insight_run` satırını yazar (koşu başında ve sonunda birer kez)."""
        row = dict(run_row)
        row.setdefault(
            "retain_until", _retain_until("insight_run", int(row["started_at"]))
        )
        return await self._upsert_batch("insight_run", [(key, row)])

    # -- okuma --------------------------------------------------------------

    async def last_pending(self, school: str) -> list[str]:
        """Bu okulun son koşusundan devreden öğrenci kimlikleri.

        Zamanlayıcının bellek içi `pending` sözlüğü süreç yeniden başlayınca
        kaybolur; "bir sonraki koşu kaldığı yerden devam eder" cümlesinin
        yeniden başlatmaya da dayanması için kaynak **`insight_run` satırıdır**.

        Okunamazsa boş liste döner: devretmemek, yanlış listeyle koşmaktan
        iyidir (`MODULLER.md` §3.4 "bayat veri, yanlış veriden iyidir"in
        tersi yönü: burada eksik bilgi zarar vermez, yanlış bilgi verir).
        """
        sql = (
            "SELECT pending_students FROM insight_run WHERE school = $school "
            "ORDER BY started_at DESC LIMIT 1;"
        )
        try:
            rows = await self._client.query(sql, {"school": school})
        except Exception as exc:  # noqa: BLE001
            log.warning("bekleyen liste okunamadı (okul=%s): %s", school, exc)
            return []
        return _first_pending(rows)

    # -- süpürme ------------------------------------------------------------

    async def sweep(self, now_ms: int) -> dict[str, bool]:
        """Saklama süresi dolmuş satırları siler.

        `MODULLER.md` §2.11 adım 2. Süpürme hattın **en sonunda**, okul bazında
        ve sıralı koşar; büyük silmeyi gündüze taşımamak için gece yapılır.
        """
        results: dict[str, bool] = {}
        for table in RETENTION_DAYS:
            sql = f"DELETE {table} WHERE retain_until < $now;"
            try:
                await self._client.query(sql, {"now": now_ms})
                results[table] = True
            except Exception as exc:  # noqa: BLE001
                log.warning("süpürme düştü (tablo=%s): %s", table, exc)
                results[table] = False
        return results

    async def purge_departed(self, school: str, active_students: list[str]) -> bool:
        """Artık öğrenci olmayanların türetilmiş verisini siler.

        `MODULLER.md` §2.11 adım 3 / `[T§6.7]` mezuniyet adımı 2: "mezunun ham
        verisi arşivde kalabilir; **profili kalmamalıdır**."

        `question_segment` buraya **girmez**: o satır bir soru hakkındadır,
        hiçbir öğrenciye bağlanamaz — mezuniyetle silinecek bir kişisel veri
        değildir. `student_segment_profile` ise kişiseldir ve silinir.
        """
        sql = (
            "DELETE student_summary WHERE school = $school "
            "AND student NOT IN $active;\n"
            "DELETE student_segment_profile WHERE school = $school "
            "AND student NOT IN $active;\n"
            "DELETE recommendation WHERE school = $school "
            "AND about != NONE AND about NOT IN $active;"
        )
        try:
            await self._client.query(
                sql, {"school": school, "active": active_students}
            )
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("mezuniyet temizliği düştü (okul=%s): %s", school, exc)
            return False


def _first_pending(rows: Any) -> list[str]:
    """SurrealDB `/rpc` cevabından `pending_students` listesini çıkarır.

    Cevap iki katmanlı: ifade listesi → `result` listesi → satır. Sahte
    istemciler boş liste döndürür; o da geçerli bir cevaptır.
    """
    if not isinstance(rows, list):
        return []
    for statement in rows:
        result = statement.get("result") if isinstance(statement, dict) else statement
        if not isinstance(result, list):
            continue
        for row in result:
            if isinstance(row, dict):
                values = row.get("pending_students") or []
                if isinstance(values, list):
                    return [str(v) for v in values]
    return []
