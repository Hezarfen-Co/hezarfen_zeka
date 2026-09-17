"""Okul cozumlemesi: slug'dan o okulun veritabanina, ve okul basina havuz.

---------------------------------------------------------------------------
NEDEN VAR
---------------------------------------------------------------------------
`ZEKA_PG_DSN` artik **KONTROL** veritabanini adlandirir. Okulun verisi her
okulun KENDI veritabanindadir ve adi backend'in kendi kuralindan turer
(`hezarfen_backend/src/tenant.rs:111-112`):

    {kontrol_db}_school_{okul_uuid, tiresiz}

Ad **desenden tahmin edilmez**; slug'i uuid'ye yalnizca kontrol
veritabanindaki `school` satiri cevirir. Satir yoksa istek reddedilir
(`unknown_school`), desene uyan bir veritabani var olsa bile: kutukte olmayan
bir veritabanina yazmak, "hangi okulun verisi bu" sorusunu cevapsiz birakirdi
(`paket/apply_zeka_tables.sh` de tam bu yuzden okullari control'den cozer).

---------------------------------------------------------------------------
SINIR NEDEN VAR
---------------------------------------------------------------------------
Okul sayisi sinirsiz buyur; her okul icin bir baglanti acik tutmak, okul
sayisiyla birlikte Postgres'in baglanti tavanini yakardı. Bu yuzden okul
havuzlari **sinirli** bir onbellekte tutulur: en fazla `max_pools` havuz
(varsayilan 8), her havuz en son kullanimdan `ttl_secs` sonra kapatilir.
Sinir asilinca **en eski kullanilan** havuz kapatilir (LRU). Tavan ve TTL
`ZEKA_MAX_SCHOOL_POOLS` / `ZEKA_SCHOOL_POOL_TTL_SECS` ile ayarlanir.

---------------------------------------------------------------------------
HATA SINIFLARI AYRIDIR
---------------------------------------------------------------------------
`unknown_school` (kutukte yok) ile `school_suspended` (kapatilmis) ve
`school_not_migrated` (veritabani var, `zeka_*` tablolari yok) uc ayri
durumdur ve ayri kodlarla doner: birincisinde yeniden denemek anlamsizdir,
ikincisinde sabretmek gerekir, ucuncusunde operatorun bir sey yapmasi
gerekir. Hicbiri `internal` degildir -- hepsi beklenen redlerdir.

Kontrol veritabani okunamazsa (ulasilamaz ya da `school` tablosu yok) bu
`TenantError` olarak yukari cikar ve ZAMANLAYICI onu o tik icin "okul yok"
sayar: acilis cokmez, sonraki tik yeniden dener.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid as uuid_mod
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, NamedTuple, Protocol

log = logging.getLogger(__name__)

#: Okul veritabaninda bulunmasi ZORUNLU tablolar. Tek kaynak:
#: `service/schema/postgres/school/20260916000001_zeka.sql` (backend'de
#: `migrations/school/20260917000002_zeka.sql`). `tests/test_tenants.py` bu
#: listeyi DDL dosyasiyla KARSILASTIRIR; biri digerinden kopamaz.
REQUIRED_TABLES: tuple[str, ...] = (
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

#: Kontrol okuma: butun kutuk tek sorguda. Okul sayisi binler olsa bile bu
#: tablo kucuktur; `resolve` icin okul basina sorgu atmak N+1 olurdu.
CONTROL_SQL = "SELECT slug, id::text, status FROM school ORDER BY created_at"

#: Okul veritabaninda hangi zeka tablolari var? `pg_class` uzerinden, cunku
#: SQLSTATE ile "tablo yok" ayrimi tek tabloda kalirdi: 9 tablodan 3'u olan
#: yarim uygulanmis bir veritabani da "migrate edilmemis" sayilmalidir.
SCHOOL_TABLES_SQL = """
SELECT c.relname
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname = ANY(%s)
"""


class TenantError(Exception):
    """Okul cozumlemesi reddi.

    `code` alanlari backend'in `ApiErrorCode` sozluguyle ayni adlari kullanir
    (`ai/server.rs:75-99`); `school` cerceveden gelen slug'dir.
    """

    code = "unavailable"

    def __init__(self, message: str, *, school: str = "") -> None:
        super().__init__(message)
        self.school = school


class UnknownSchool(TenantError):
    """Kutukte boyle bir okul yok. Kapali kume: yeniden denemek ogretmez."""

    code = "unknown_school"


class SchoolSuspended(TenantError):
    """Okul var ama kapatilmis. Sonradan acilabilir; yeniden denenebilir."""

    code = "school_suspended"


class SchoolDatabaseGone(TenantError):
    """Okul kutukte var, veritabani yok ya da baglanilamiyor."""

    code = "unavailable"


class SchoolNotMigrated(TenantError):
    """Okul veritabani var ama `zeka_*` tablolarini tasimiyor."""

    code = "school_not_migrated"


@dataclass(frozen=True)
class SchoolRef:
    """Kontrol satirinin cozulmus hali: slug, uuid ve durum."""

    slug: str
    id: uuid_mod.UUID
    status: str


def database_name(control_db: str, school: uuid_mod.UUID | str) -> str:
    """`{kontrol}_school_{uuid tiresiz}` -- backend `tenant.rs:111-112`.

    `uuid.simple()` ile ayni bicim: 32 karakter kucuk hex, tiresiz. Gecersiz
    bir metin `ValueError` verir; ad UYDURULMAZ.
    """
    uid = school if isinstance(school, uuid_mod.UUID) else uuid_mod.UUID(str(school))
    return f"{control_db}_school_{uid.hex}"


class SchoolRegistry:
    """slug -> [`SchoolRef`]. Kontrol veritabanindan, TTL'li tek sorgu.

    TTL `0` ise her cagri taze okur (testler bunu kullanir); `30s` varsayilan,
    cunku yeni okul acmak seyrek bir olaydir ama bayat bir kutukle bir okulu
    hic gormemek daha pahalidir.
    """

    def __init__(
        self,
        client: Any,
        *,
        ttl_secs: float = 30.0,
        clock_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._ttl = float(ttl_secs)
        self._clock = clock_fn
        self._by_slug: dict[str, SchoolRef] = {}
        self._loaded_at: float | None = None
        self._queries = 0

    @property
    def queries(self) -> int:
        """Kaca kere kontrol veritabani okundu (onbellek kaniti)."""
        return self._queries

    def _stale(self) -> bool:
        if self._loaded_at is None or self._ttl <= 0:
            return True
        return (self._clock() - self._loaded_at) > self._ttl

    async def _load(self) -> None:
        try:
            rows = await self._client.fetch(CONTROL_SQL)
        except Exception as exc:  # noqa: BLE001 -- yukariya tek tip hata
            raise TenantError(
                "kontrol veritabani okunamadi (school tablosu var mi?): %s" % exc
            ) from exc
        table: dict[str, SchoolRef] = {}
        for slug, ident, status in rows:
            try:
                uid = uuid_mod.UUID(str(ident))
            except ValueError:
                # Bozuk bir satir butun kutugu dusurmez; ama sessiz de kalmaz.
                log.warning("okul satirinin uuid'si cozulemedi, atlandi: %r", slug)
                continue
            table[str(slug)] = SchoolRef(str(slug), uid, str(status))
        self._by_slug = table
        self._loaded_at = self._clock()
        self._queries += 1

    async def _fresh_table(self) -> dict[str, SchoolRef]:
        if self._stale():
            await self._load()
        return self._by_slug

    async def all_schools(self) -> dict[str, SchoolRef]:
        return dict(await self._fresh_table())

    async def active_schools(self) -> list[str]:
        """Islenmeye hazir okullar: durumu `active`, slug sirali."""
        table = await self._fresh_table()
        return sorted(slug for slug, ref in table.items() if ref.status == "active")

    async def resolve(self, slug: str) -> SchoolRef:
        """Slug'i okula cevir; yoksa/kapatilmissa reddet."""
        table = await self._fresh_table()
        ref = table.get(slug)
        if ref is None:
            raise UnknownSchool(
                "bu dagitimda '%s' okulu yok" % slug, school=slug
            )
        if ref.status != "active":
            raise SchoolSuspended(
                "'%s' okulu kapatilmis (durum: %s)" % (slug, ref.status), school=slug
            )
        return ref


class OpenedSchool(NamedTuple):
    """Bir okul havuzunun acilmis hali: depo + onu kapatan kanca."""

    store: Any
    close: Callable[[], Awaitable[None]]


#: Okul -> acilmis havuz. `TenantStores` bunu enjekte edilebilir tutar:
#: birim testleri gercek Postgres olmadan tavan/TTL davranisini kosturur.
Opener = Callable[[SchoolRef], Awaitable[OpenedSchool]]


class _Held:
    """Onbellekteki tek kayit: depo, kapaticisi ve son kullanim damgasi."""

    __slots__ = ("store", "close", "last_used")

    def __init__(self, store: Any, close: Callable[[], Awaitable[None]], at: float) -> None:
        self.store = store
        self.close = close
        self.last_used = at


class Directory(Protocol):
    """Servisin okul dizini: hangi okullar var, her birinin deposu hangisi."""

    async def active_schools(self) -> list[str]: ...

    async def store_for(self, slug: str) -> Any: ...

    async def close(self) -> None: ...

    def describe(self) -> str: ...


class TenantStores:
    """Sinirli, TTL'li okul havuzu onbellegi.

    `store_for` TEK yol: her okul istegi buradan kendi veritabanini alir. Geri
    dusme yoktur -- kontrol veritabaninin kendisi ya da baska bir okul asla
    cevap vermez (`unknown_school` doner).
    """

    def __init__(
        self,
        registry: SchoolRegistry,
        opener: Opener,
        *,
        max_pools: int = 8,
        ttl_secs: float = 900.0,
        clock_fn: Callable[[], float] = time.monotonic,
        teardown: Sequence[Callable[[], Awaitable[None]]] = (),
    ) -> None:
        self._registry = registry
        self._opener = opener
        self._max_pools = max(1, int(max_pools))
        self._ttl = float(ttl_secs)
        self._clock = clock_fn
        self._teardown = list(teardown)
        self._entries: dict[str, _Held] = {}
        self._lock = asyncio.Lock()
        self._opened = 0
        self._evicted = 0
        self._refused = 0

    def describe(self) -> str:
        return (
            "okul dizini: kontrol veritabani (ZEKA_PG_DSN), adlar "
            "{kontrol}_school_{uuid}; havuz tavani=%d, havuz TTL=%.0fs, "
            "kayit TTL=%.0fs" % (self._max_pools, self._ttl, self._registry._ttl)
        )

    def stats(self) -> dict[str, int]:
        """Sayaclar. `atilan`, tavani ve TTL'i asan havuzlarin sayisidir."""
        return {
            "acik": len(self._entries),
            "tavan": self._max_pools,
            "acilan": self._opened,
            "atilan": self._evicted,
            "reddedilen": self._refused,
        }

    async def active_schools(self) -> list[str]:
        return await self._registry.active_schools()

    def _expired(self, held: _Held) -> bool:
        return self._ttl > 0 and (self._clock() - held.last_used) > self._ttl

    async def _drop(self, slug: str, reason: str) -> None:
        held = self._entries.pop(slug, None)
        if held is None:
            return
        self._evicted += 1
        log.info("okul havuzu kapatildi (okul=%s, sebep=%s)", slug, reason)
        try:
            await held.close()
        except Exception as exc:  # noqa: BLE001 -- kapatma hatasi turu durdurmaz
            log.warning("okul havuzu kapatilamadi (okul=%s): %s", slug, exc)

    async def _make_room(self) -> None:
        while len(self._entries) >= self._max_pools:
            oldest = min(self._entries.items(), key=lambda item: item[1].last_used)
            await self._drop(oldest[0], "tavan")

    async def _open(self, ref: SchoolRef) -> _Held:
        try:
            opened = await self._opener(ref)
        except TenantError:
            self._refused += 1
            raise
        except Exception as exc:  # noqa: BLE001 -- surucu hatasi tek tipe baglanir
            self._refused += 1
            raise SchoolDatabaseGone(
                "'%s' okulunun veritabani acilamadi: %s" % (ref.slug, exc),
                school=ref.slug,
            ) from exc
        self._opened += 1
        log.info("okul havuzu acildi (okul=%s)", ref.slug)
        return _Held(opened.store, opened.close, self._clock())

    async def store_for(self, slug: str) -> Any:
        """Okulun deposu. Kapanmis/taze degilse yeniden acilir.

        Bilinmeyen ya da kapatilmis okul burada reddedilir; acilista degil,
        cunku acilisin okul satirina ihtiyaci YOKTUR (kutuk bos olabilir).
        """
        held = self._entries.get(slug)
        if held is not None:
            if not self._expired(held):
                held.last_used = self._clock()
                return held.store
            await self._drop(slug, "ttl")

        try:
            ref = await self._registry.resolve(slug)
        except TenantError:
            # Bilinmeyen/kapatilmis okul da bir reddir; sayaci burada artir.
            self._refused += 1
            raise

        async with self._lock:
            # Kilidi beklerken baska bir gorev ayni okulu acmis olabilir.
            held = self._entries.get(slug)
            if held is not None:
                held.last_used = self._clock()
                return held.store
            await self._make_room()
            self._entries[slug] = await self._open(ref)
        return self._entries[slug].store

    async def close(self) -> None:
        """Butun havuzlari ve bu nesnenin sahibi oldugu kaynaklari kapatir."""
        for slug in list(self._entries):
            await self._drop(slug, "kapanis")
        for closer in self._teardown:
            try:
                await closer()
            except Exception as exc:  # noqa: BLE001
                log.warning("dizin kaynagi kapatilamadi: %s", exc)


class OneDatabase:
    """Eski tek veritabani modu (SurrealDB): butun okullar ayni depoyu paylasir.

    Cozumleme yine kapali kumedir: listede olmayan slug reddedilir -- eski
    modda da "bilinmeyen okul" diye bir sey vardir, yalnizca kaynagi kontrol
    veritabani degil, yapilandirmadir (`ZEKA_SCHOOLS`).
    """

    def __init__(
        self,
        store: Any,
        schools: Sequence[str],
        *,
        teardown: Sequence[Callable[[], Awaitable[None]]] = (),
    ) -> None:
        self._store = store
        self._schools = sorted({str(s) for s in schools if str(s).strip()})
        self._teardown = list(teardown)

    def describe(self) -> str:
        return (
            "okul dizini: tek veritabani (eski SurrealDB modu), okullar "
            "ZEKA_SCHOOLS'ten (%d)" % len(self._schools)
        )

    async def active_schools(self) -> list[str]:
        return list(self._schools)

    async def store_for(self, slug: str) -> Any:
        if slug not in self._schools:
            raise UnknownSchool(
                "bu servis '%s' okulunu islemiyor (ZEKA_SCHOOLS)" % slug, school=slug
            )
        return self._store

    async def close(self) -> None:
        for closer in self._teardown:
            try:
                await closer()
            except Exception as exc:  # noqa: BLE001
                log.warning("dizin kaynagi kapatilamadi: %s", exc)


# --- Postgres tarafi -------------------------------------------------------


def school_dsn(control_dsn: str, database: str) -> str:
    """Kontrol DSN'inin AYNI sunucusunda, veritabani adi degistirilmis DSN.

    Backend de boyle yapar (`database.rs:130` `school_pool`): kontrol ile okul
    veritabanlari ayni Postgres sunucusundadir, degisen tek sey `dbname`dir.
    Kullanici/parola kontrol DSN'inden gelir; okul basina sir TUTULMAZ.
    """
    import psycopg.conninfo

    parts = psycopg.conninfo.conninfo_to_dict(control_dsn)
    parts["dbname"] = database
    return psycopg.conninfo.make_conninfo(**parts)


async def control_database(client: Any) -> str:
    """Kontrol veritabaninin GERCEK adi.

    DSN'i elle ayristirmak yerine sunucuya sorulur: URL bicimi de anahtar=deger
    bicimi de ayni cevabi verir, `dbname` yazilmamissa da dogru kalir.
    """
    rows = await client.fetch("SELECT current_database()")
    if not rows:
        raise TenantError("kontrol veritabaninin adi ogrenilemedi")
    return str(rows[0][0])


async def verify_school_schema(client: Any, ref: SchoolRef) -> None:
    """Okul veritabani `zeka_*` tablolarini tasiyor mu?

    Ayri bir hata tipiyle reddedilir (`school_not_migrated`): veritabani
    vardir, baglanti kurulmustur, eksik olan YALNIZCA semadir. Eksikler
    adiyla soylenir; hangi DDL'in uygulanacagi da mesajdadir.
    """
    rows = await client.fetch(SCHOOL_TABLES_SQL, [list(REQUIRED_TABLES)])
    found = {str(row[0]) for row in rows}
    missing = [name for name in REQUIRED_TABLES if name not in found]
    if missing:
        raise SchoolNotMigrated(
            "'%s' okulunun veritabani zeka tablolarini tasimiyor: %d/%d eksik "
            "(%s). Veritabanina "
            "service/schema/postgres/school/20260916000001_zeka.sql "
            "uygulanmalidir." % (ref.slug, len(missing), len(REQUIRED_TABLES), ", ".join(missing)),
            school=ref.slug,
        )


def postgres_opener(
    control_dsn: str,
    control_db: str,
    *,
    connect_timeout_secs: float = 10.0,
) -> Opener:
    """Okul havuzlarini acan kanca: DSN turetir, semayi dogrular."""

    async def open_school(ref: SchoolRef) -> OpenedSchool:
        from .pg_client import PsycopgClient
        from .store_pg import PgStore

        dsn = school_dsn(control_dsn, database_name(control_db, ref.id))
        client = await PsycopgClient.connect(dsn, connect_timeout=connect_timeout_secs)
        try:
            await verify_school_schema(client, ref)
        except Exception:
            await client.close()
            raise
        log.info(
            "okul veritabanina baglanildi (okul=%s, veritabani=%s)",
            ref.slug,
            database_name(control_db, ref.id),
        )
        return OpenedSchool(PgStore(client), client.close)

    return open_school


async def open_postgres(
    dsn: str,
    *,
    max_pools: int = 8,
    pool_ttl_secs: float = 900.0,
    registry_ttl_secs: float = 30.0,
    connect_timeout_secs: float = 10.0,
    clock_fn: Callable[[], float] = time.monotonic,
) -> TenantStores:
    """Kontrol veritabanina baglan ve sinirli okul dizinini kur.

    Acilista kutuk OKUNMAZ: kontrol baglantisi kurulur, veritabaninin kendi
    adi ogrenilir ve biter. Okul satiri olmayan bir kurulum bu yuzden SORUNSUZ
    acilir; eksik okul veritabani da acilisi degil, o okulun istegini dusurur.
    """
    from .pg_client import PsycopgClient

    client = await PsycopgClient.connect(dsn, connect_timeout=connect_timeout_secs)
    try:
        control_db = await control_database(client)
    except Exception:
        await client.close()
        raise
    registry = SchoolRegistry(client, ttl_secs=registry_ttl_secs, clock_fn=clock_fn)
    return TenantStores(
        registry,
        postgres_opener(dsn, control_db, connect_timeout_secs=connect_timeout_secs),
        max_pools=max_pools,
        ttl_secs=pool_ttl_secs,
        clock_fn=clock_fn,
        teardown=[client.close],
    )


async def open_directory(settings: Any) -> Directory:
    """Acilista servisin okul dizinini kurar.

    `ZEKA_PG_DSN` doluysa kontrol tabanli sinirli havuzlar; bos ise eski tek
    veritabani modu (okul listesi `ZEKA_SCHOOLS`).
    """
    from . import store_factory

    if store_factory.is_postgres():
        import os

        return await open_postgres(
            os.environ.get("ZEKA_PG_DSN", "").strip(),
            max_pools=settings.max_school_pools,
            pool_ttl_secs=settings.school_pool_ttl_secs,
            registry_ttl_secs=settings.school_registry_ttl_secs,
            connect_timeout_secs=settings.school_connect_timeout_secs,
        )
    store, client = await store_factory.open_store()
    return OneDatabase(store, settings.schools, teardown=[client.close])
