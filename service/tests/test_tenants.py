"""Okul cozumlemesi (`tenants.py`) testleri.

Iki katman vardir ve ikisi AYRI isler:

1. **Birim** (bu dosyanin cogu, bagimliliksiz): ad kurali, kayit onbellegi,
   havuz tavani/TTL'i, bilinmeyen okulun reddi. Sahte kontrol istemcisi ve
   sahte `opener` ile kosar -- gercek veritabani gerekmez, CI'da da kosar.
2. **Entegrasyon** (`ZEKA_TEST_PG_DSN` verilirse): gercek Postgres'te iki
   okul veritabani acar, satirlarin birbirine SIZMADIGINI, eksik veritabani
   ve migrate edilmemis veritabani hatalarinin AYRI oldugunu olcer. Degisken
   yoksa atlanir; birim testleri etkilenmez.

`ZEKA_TEST_PG_DSN` BILEREK ayri bir degiskendir: `ZEKA_PG_DSN` uretim
kontrol veritabanini gosterebilir ve bu testler veritabani ACAR/SILER.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
import uuid
from pathlib import Path

from src import capabilities, tenants
from src.tenants import (
    OneDatabase,
    OpenedSchool,
    SchoolNotMigrated,
    SchoolRegistry,
    SchoolSuspended,
    TenantError,
    TenantStores,
    UnknownSchool,
    database_name,
)

REPO = Path(__file__).resolve().parents[2]
DDL = REPO / "service" / "schema" / "postgres" / "school" / "20260916000001_zeka.sql"

#: Sabit uuid'ler: hangi okulun hangi veritabani oldugu hata ciktisinda belli
#: olsun (`backend tenant.rs:111-112` deseninin bekledigi bicim).
SCHOOL_A = "01930000-0000-7000-8000-0000000000a1"
SCHOOL_B = "01930000-0000-7000-8000-0000000000b2"
SCHOOL_C = "01930000-0000-7000-8000-0000000000c3"
STUDENT_A = "01930000-0000-7000-8000-0000000000d1"
STUDENT_B = "01930000-0000-7000-8000-0000000000d2"
CONTROL = "hezarfen_control"


class _Clock:
    """Deterministik saat: TTL sinirlari duvar saatine bagli kalmasin."""

    def __init__(self, value: float = 1000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class _FakeControl:
    """`school` tablosunun tek sorgusunu (CONTROL_SQL) taklit eder."""

    def __init__(self, rows: list[tuple[str, str, str]] | None = None) -> None:
        self.rows = list(rows or [])
        self.queries = 0

    async def fetch(self, sql: str, params: tuple = ()) -> list[tuple]:
        if sql != tenants.CONTROL_SQL:
            raise AssertionError("beklenmeyen sorgu: %s" % sql)
        self.queries += 1
        return list(self.rows)


class _FakeStore:
    def __init__(self, name: str) -> None:
        self.name = name


class NamingTests(unittest.TestCase):
    def test_database_name_follows_the_backend_convention(self) -> None:
        # `tenant.rs:111-112` ile ayni: {kontrol}_school_{uuid tiresiz}.
        self.assertEqual(
            database_name(CONTROL, SCHOOL_A),
            "hezarfen_control_school_019300000000700080000000000000a1",
        )
        self.assertEqual(
            database_name(CONTROL, uuid.UUID(SCHOOL_A)),
            "hezarfen_control_school_019300000000700080000000000000a1",
        )

    def test_the_name_never_carries_dashes_or_uppercase(self) -> None:
        name = database_name(CONTROL, uuid.UUID(SCHOOL_B.upper()))
        self.assertNotIn("-", name)
        self.assertEqual(name, name.lower())

    def test_garbage_is_refused_not_mangled(self) -> None:
        with self.assertRaises(ValueError):
            database_name(CONTROL, "kadikoy-lisesi")


class RegistryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.clock = _Clock()

    def _registry(self, rows, ttl: float = 60.0) -> SchoolRegistry:
        return SchoolRegistry(_FakeControl(rows), ttl_secs=ttl, clock_fn=self.clock)

    async def test_the_control_query_is_shared_until_the_ttl_expires(self) -> None:
        registry = self._registry(
            [("a-okul", SCHOOL_A, "active"), ("b-okul", SCHOOL_B, "active")]
        )
        client = registry._client
        for _ in range(3):
            await registry.resolve("a-okul")
        await registry.active_schools()
        self.assertEqual(client.queries, 1, "kutuk her cagride yeniden okunmamali")

        self.clock.advance(61)
        await registry.resolve("a-okul")
        self.assertEqual(client.queries, 2)

    async def test_only_active_schools_are_listed_and_the_order_is_stable(self) -> None:
        registry = self._registry(
            [
                ("kadikoy-lisesi", SCHOOL_A, "active"),
                ("kapatilan-lise", SCHOOL_B, "suspended"),
                ("ataturk-lisesi", SCHOOL_A, "active"),
            ]
        )
        self.assertEqual(
            await registry.active_schools(), ["ataturk-lisesi", "kadikoy-lisesi"]
        )

    async def test_unknown_and_suspended_are_distinguishable(self) -> None:
        registry = self._registry([("kapali-lise", SCHOOL_A, "suspended")])
        with self.assertRaises(UnknownSchool) as unknown:
            await registry.resolve("yok-boyle-okul")
        self.assertEqual(unknown.exception.code, "unknown_school")

        with self.assertRaises(SchoolSuspended) as suspended:
            await registry.resolve("kapali-lise")
        self.assertEqual(suspended.exception.code, "school_suspended")

    async def test_a_broken_control_row_does_not_sink_the_catalogue(self) -> None:
        registry = self._registry(
            [("bozuk", "uuid-degil", "active"), ("saglam", SCHOOL_A, "active")]
        )
        self.assertEqual(await registry.active_schools(), ["saglam"])

    async def test_an_unreadable_control_database_is_a_typed_error(self) -> None:
        class Broken:
            async def fetch(self, sql, params=()):
                raise RuntimeError('relation "school" does not exist')

        registry = SchoolRegistry(Broken(), ttl_secs=0)
        with self.assertRaises(TenantError) as caught:
            await registry.active_schools()
        self.assertEqual(caught.exception.code, "unavailable")
        self.assertIn("school", str(caught.exception))


class PoolTests(unittest.IsolatedAsyncioTestCase):
    """Sinirli havuz onbellegi: tavani ve TTL'i sahte opener ile olculur."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.rows = [
            ("a-okul", SCHOOL_A, "active"),
            ("b-okul", SCHOOL_B, "active"),
            ("c-okul", SCHOOL_C, "active"),
        ]
        self.control = _FakeControl(self.rows)
        self.opened: list[str] = []
        self.closed: list[str] = []

    def _stores(self, *, max_pools: int = 8, ttl: float = 900.0) -> TenantStores:
        self.registry = SchoolRegistry(self.control, ttl_secs=60.0, clock_fn=self.clock)

        async def opener(ref):
            self.opened.append(ref.slug)

            async def close() -> None:
                self.closed.append(ref.slug)

            return OpenedSchool(_FakeStore(ref.slug), close)

        return TenantStores(
            self.registry,
            opener,
            max_pools=max_pools,
            ttl_secs=ttl,
            clock_fn=self.clock,
        )

    async def test_each_school_gets_its_own_store(self) -> None:
        stores = self._stores()
        a = await stores.store_for("a-okul")
        b = await stores.store_for("b-okul")
        self.assertEqual((a.name, b.name), ("a-okul", "b-okul"))
        self.assertIsNot(a, b)
        # Ikinci cagri onbellegi kullanir: yeniden ACILMAZ.
        self.assertIs(await stores.store_for("a-okul"), a)
        self.assertEqual(self.opened, ["a-okul", "b-okul"])

    async def test_an_unknown_school_is_refused_and_nothing_falls_back(self) -> None:
        stores = self._stores()
        with self.assertRaises(UnknownSchool) as caught:
            await stores.store_for("yok-boyle-okul")
        self.assertEqual(caught.exception.code, "unknown_school")
        self.assertEqual(self.opened, [], "bilinmeyen okul icin havuz ACILMAMALI")
        self.assertEqual(stores.stats()["reddedilen"], 1)

    async def test_the_ceiling_evicts_the_least_recently_used_pool(self) -> None:
        stores = self._stores(max_pools=2)
        await stores.store_for("a-okul")
        self.clock.advance(1)
        b_store = await stores.store_for("b-okul")
        self.clock.advance(1)
        await stores.store_for("a-okul")  # a artik en yeni kullanilan
        self.clock.advance(1)
        await stores.store_for("b-okul")  # b de oyle; simdi bir yer lazim

        # Ucuncu okul icin yer acilmali: en eski kullanilan kapanir.
        self.clock.advance(1)
        await stores.store_for("c-okul")

        self.assertEqual(stores.stats()["acik"], 2)
        self.assertEqual(stores.stats()["atilan"], 1)
        self.assertEqual(self.closed, ["a-okul"])
        # Kapatilan okul yeniden istendiginde yeniden ACILIR (bayat depo yok).
        self.clock.advance(1)
        again = await stores.store_for("a-okul")
        self.assertEqual(again.name, "a-okul")
        self.assertEqual(self.opened.count("a-okul"), 2)
        self.assertEqual(b_store.name, "b-okul")

    async def test_a_pool_expires_after_its_ttl(self) -> None:
        stores = self._stores(ttl=10.0)
        first = await stores.store_for("a-okul")
        self.clock.advance(11)
        second = await stores.store_for("a-okul")
        self.assertIsNot(first, second)
        self.assertEqual(self.closed, ["a-okul"])
        self.assertEqual(stores.stats()["atilan"], 1)

    async def test_zero_schools_boot_cleanly_and_serve_nothing(self) -> None:
        self.control.rows.clear()
        stores = self._stores()
        self.assertEqual(await stores.active_schools(), [])
        with self.assertRaises(UnknownSchool):
            await stores.store_for("a-okul")
        self.assertEqual(stores.stats()["acik"], 0)
        await stores.close()

    async def test_close_releases_every_pool(self) -> None:
        stores = self._stores()
        await stores.store_for("a-okul")
        await stores.store_for("b-okul")
        await stores.close()
        self.assertEqual(sorted(self.closed), ["a-okul", "b-okul"])
        self.assertEqual(stores.stats()["acik"], 0)

    async def test_a_failing_opener_is_reported_as_an_unavailable_school(self) -> None:
        registry = SchoolRegistry(self.control, ttl_secs=60.0, clock_fn=self.clock)

        async def opener(ref):
            raise RuntimeError('connection failed: FATAL: database "yok" does not exist')

        stores = TenantStores(registry, opener, clock_fn=self.clock)
        with self.assertRaises(TenantError) as caught:
            await stores.store_for("a-okul")
        self.assertEqual(caught.exception.code, "unavailable")


class DispatchTests(unittest.IsolatedAsyncioTestCase):
    """Cercevenin `school` alani -> o okulun deposu: istek yolunun dikişi."""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.control = _FakeControl(
            [("a-okul", SCHOOL_A, "active"), ("b-okul", SCHOOL_B, "active")]
        )
        self.seen: dict[str, list[str]] = {}

    def tearDown(self) -> None:
        capabilities._handlers.clear()
        capabilities.bind_directory(None)

    def _stores(self) -> TenantStores:
        registry = SchoolRegistry(self.control, ttl_secs=60.0, clock_fn=self.clock)

        async def opener(ref):
            store = _FakeStore(ref.slug)
            store.written = []
            self.seen[ref.slug] = store.written

            async def close() -> None:
                return None

            return OpenedSchool(store, close)

        return TenantStores(registry, opener, clock_fn=self.clock)

    async def test_the_handler_resolves_the_frame_s_school_and_never_another(self) -> None:
        capabilities.bind_directory(self._stores())

        async def handler(school, payload):
            store = await capabilities.directory().store_for(school)
            store.written.append(payload["mark"])
            return {"seen": list(store.written), "store": store.name}

        capabilities.register(capabilities.INSIGHT_REFRESH, handler)

        a = await capabilities.dispatch(capabilities.INSIGHT_REFRESH, "a-okul", {"mark": "run-a"})
        b = await capabilities.dispatch(capabilities.INSIGHT_REFRESH, "b-okul", {"mark": "run-b"})

        self.assertEqual(a, {"seen": ["run-a"], "store": "a-okul"})
        self.assertEqual(b, {"seen": ["run-b"], "store": "b-okul"})
        self.assertEqual(self.seen["a-okul"], ["run-a"])
        self.assertEqual(self.seen["b-okul"], ["run-b"])

    async def test_an_unknown_school_refuses_with_its_own_code(self) -> None:
        capabilities.bind_directory(self._stores())

        async def handler(school, payload):
            store = await capabilities.directory().store_for(school)
            return {"store": store.name}

        capabilities.register(capabilities.INSIGHT_STUDENT, handler)
        with self.assertRaises(UnknownSchool) as caught:
            await capabilities.dispatch(capabilities.INSIGHT_STUDENT, "yok", {})
        # Kod kabloya AYNEN gider (bridge.py: CapabilityError/TenantError).
        self.assertEqual(caught.exception.code, "unknown_school")

    async def test_without_a_bound_directory_the_request_is_refused(self) -> None:
        with self.assertRaises(capabilities.CapabilityError) as caught:
            capabilities.directory()
        self.assertEqual(caught.exception.code, "unavailable")


class LegacyDirectoryTests(unittest.IsolatedAsyncioTestCase):
    """Eski tek veritabani modu da kapali kume olmali."""

    async def test_the_configured_schools_are_the_only_ones_served(self) -> None:
        store = _FakeStore("tek")
        directory = OneDatabase(store, ["a-okul", "b-okul"])
        self.assertEqual(await directory.active_schools(), ["a-okul", "b-okul"])
        self.assertIs(await directory.store_for("a-okul"), store)
        with self.assertRaises(UnknownSchool):
            await directory.store_for("yok")


class MigrationListTests(unittest.TestCase):
    """`REQUIRED_TABLES` ile okul DDL'i birbirinden kopmasin."""

    def test_required_tables_match_the_school_migration(self) -> None:
        import re

        sql = DDL.read_text(encoding="utf-8")
        created = set(re.findall(r"^CREATE TABLE\s+(\w+)", sql, flags=re.MULTILINE))
        self.assertEqual(
            created,
            set(tenants.REQUIRED_TABLES),
            "zeka okul semasi degistiyse REQUIRED_TABLES'i da guncelleyin "
            "(`tenants.py`)",
        )


# ===========================================================================
# ENTEGRASYON -- gercek Postgres, iki okul
# ===========================================================================

ADMIN_DSN = os.environ.get("ZEKA_TEST_PG_DSN", "").strip()

STUB_DDL = """
CREATE TABLE app_user (id uuid PRIMARY KEY);
CREATE TABLE course (id uuid PRIMARY KEY);
CREATE TABLE subject (id uuid PRIMARY KEY);
CREATE TABLE exam_question (exam uuid NOT NULL, id uuid NOT NULL, PRIMARY KEY (exam, id));
"""
"""ZEKA tablolarinin disari bakan FK'leri icin asgari hedefler (bkz.
`service/schema/postgres/school/20260916000001_zeka.sql` satirlari 50, 82,
250, 300). Gercek okul veritabaninda bunlar backend'in semasidir."""


def _pg_available() -> bool:
    if not ADMIN_DSN:
        return False
    try:
        import psycopg

        with psycopg.connect(ADMIN_DSN, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:  # noqa: BLE001
        return False


PG_AVAILABLE = _pg_available()

CONTROL_DDL = """
CREATE TABLE school (
    id         uuid PRIMARY KEY,
    slug       TEXT NOT NULL,
    name       TEXT NOT NULL,
    status     TEXT NOT NULL CONSTRAINT school_status CHECK (status IN ('active', 'suspended')),
    created_at BIGINT NOT NULL,
    CONSTRAINT school_slug UNIQUE (slug)
)
"""
"""Kontrol semasinin YALNIZCA kayit cozumlemesinin okudugu kadari.

Backend'in tam kontrol semasi (`migrations/control/20260912000001_control.sql`)
bir suru tablo daha kurar; zeka yalnizca `school(slug, id, status)` okur, bu
yuzden fikstur o kadardir -- testi backend deposuna baglamak, testi baska bir
deponun surumune baglamak olurdu.
"""


@unittest.skipUnless(
    PG_AVAILABLE, "ZEKA_TEST_PG_DSN yok/erisilemiyor; Postgres entegrasyonu atlandi"
)
class PgMultiSchoolTests(unittest.IsolatedAsyncioTestCase):
    """Iki okul, iki veritabani: sizinti yok, redler ayrilabiliyor."""

    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self) -> None:
        import psycopg

        from src.pg_client import PsycopgClient
        from src.store_pg import PgStore

        self.PsycopgClient = PsycopgClient
        self.PgStore = PgStore
        self.admin = await psycopg.AsyncConnection.connect(ADMIN_DSN, autocommit=True)
        self.tag = uuid.uuid4().hex[:10]
        self.control = "zeka_ms_%s" % self.tag
        self.a_db = database_name(self.control, SCHOOL_A)
        self.b_db = database_name(self.control, SCHOOL_B)
        self.made: list[str] = []

        await self._createdb(self.control)
        self.control_conn = await psycopg.AsyncConnection.connect(
            tenants.school_dsn(ADMIN_DSN, self.control), autocommit=True
        )
        await self.control_conn.execute(CONTROL_DDL)
        await self.control_conn.execute(
            "INSERT INTO school (id, slug, name, status, created_at) VALUES "
            "(%s, 'a-okul', 'A', 'active', 1), (%s, 'b-okul', 'B', 'active', 2), "
            "(%s, 'kapali-okul', 'K', 'suspended', 3)",
            (SCHOOL_A, SCHOOL_B, SCHOOL_C),
        )
        self.dsn = tenants.school_dsn(ADMIN_DSN, self.control)

    async def asyncTearDown(self) -> None:
        control_conn = getattr(self, "control_conn", None)
        if control_conn is not None:
            await control_conn.close()
        for name in reversed(self.made):
            await self.admin.execute('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % name)
        await self.admin.close()

    async def _createdb(self, name: str) -> None:
        await self.admin.execute('CREATE DATABASE "%s"' % name)
        self.made.append(name)

    async def _apply_zeka_ddl(self, name: str) -> None:
        import psycopg

        conn = await psycopg.AsyncConnection.connect(
            tenants.school_dsn(ADMIN_DSN, name), autocommit=True
        )
        try:
            # ZEKA'nin tablolari DISARI bakan FK'ler tasir (app_user, course,
            # subject, exam_question). Okul veritabaninda o tablolar backend'in
            # kendi semasindan gelir; fikstur FK'lerin istedigi ASGARI sutunu
            # kurar, boylece test backend deposuna baglanmaz.
            await conn.execute(STUB_DDL)
            # Ogrenci satirlari da gerekli: `zeka_run_pending.student` ile
            # `zeka_student_summary.student` app_user'a FK verir.
            await conn.execute(
                "INSERT INTO app_user (id) VALUES (%s), (%s)", (STUDENT_A, STUDENT_B)
            )
            await conn.execute(DDL.read_text(encoding="utf-8"))
        finally:
            await conn.close()

    async def _open(self, **kw) -> TenantStores:
        return await tenants.open_postgres(self.dsn, **kw)

    async def test_boot_succeeds_with_zero_schools(self) -> None:
        # Kutugu bosalt: acilis okul satiri istememeli.
        await self.control_conn.execute("DELETE FROM school")
        stores = await self._open()
        self.assertEqual(await stores.active_schools(), [])
        with self.assertRaises(UnknownSchool) as caught:
            await stores.store_for("a-okul")
        self.assertEqual(caught.exception.code, "unknown_school")
        await stores.close()

    async def test_two_schools_never_see_each_other_s_rows(self) -> None:
        for name in (self.a_db, self.b_db):
            await self._createdb(name)
            await self._apply_zeka_ddl(name)

        stores = await self._open()
        a = await stores.store_for("a-okul")
        b = await stores.store_for("b-okul")

        # Hangi veritabanina baglandigimiz ADIYLA dogrulanir: turetme yanlissa
        # butun test yanlis yeri olcerdi.
        self.assertEqual(
            str((await a._client.fetch("SELECT current_database()"))[0][0]), self.a_db
        )
        self.assertEqual(
            str((await b._client.fetch("SELECT current_database()"))[0][0]), self.b_db
        )

        # `zeka_run_pending.student` bir uuid'dir (app_user'a FK): ogrenci
        # kimlikleri de o turden olmali.
        self.assertTrue(
            await a.write_run(
                {"started_at": 1, "status": "running", "pending_students": [STUDENT_A]},
                "2026-09-17",
            )
        )
        self.assertTrue(
            await b.write_run(
                {"started_at": 2, "status": "running", "pending_students": [STUDENT_B]},
                "2026-09-17",
            )
        )

        self.assertEqual(await a.last_pending("a-okul"), [STUDENT_A])
        self.assertEqual(await b.last_pending("b-okul"), [STUDENT_B])
        self.assertEqual(
            int((await a._client.fetch("SELECT count(*) FROM zeka_run"))[0][0]), 1
        )
        self.assertEqual(
            int((await b._client.fetch("SELECT count(*) FROM zeka_run"))[0][0]), 1
        )
        await stores.close()

    async def test_a_school_with_no_database_is_a_per_request_error(self) -> None:
        # Ne a ne b veritabani var: acilis yine de basarili olmali.
        stores = await self._open()
        self.assertEqual(await stores.active_schools(), ["a-okul", "b-okul"])
        with self.assertRaises(TenantError) as caught:
            await stores.store_for("a-okul")
        self.assertEqual(caught.exception.code, "unavailable")
        self.assertNotIsInstance(caught.exception, UnknownSchool)
        await stores.close()

    async def test_an_unmigrated_school_database_is_distinguishable(self) -> None:
        await self._createdb(self.a_db)  # var ama zeka tablolari yok

        stores = await self._open()
        with self.assertRaises(SchoolNotMigrated) as caught:
            await stores.store_for("a-okul")
        message = str(caught.exception)
        self.assertIn("zeka_run", message)
        self.assertIn("20260916000001_zeka.sql", message)
        self.assertEqual(caught.exception.code, "school_not_migrated")
        # Diger okulun veritabani da yok; o BASKA bir hata vermeli.
        with self.assertRaises(TenantError) as other:
            await stores.store_for("b-okul")
        self.assertEqual(other.exception.code, "unavailable")
        await stores.close()

    async def test_a_suspended_school_is_refused_by_the_control_row(self) -> None:
        stores = await self._open()
        with self.assertRaises(SchoolSuspended) as caught:
            await stores.store_for("kapali-okul")
        self.assertEqual(caught.exception.code, "school_suspended")
        await stores.close()

    async def test_the_pool_cache_is_bounded_and_releases_backends(self) -> None:
        for name in (self.a_db, self.b_db):
            await self._createdb(name)
            await self._apply_zeka_ddl(name)

        stores = await self._open(max_pools=1)
        await stores.store_for("a-okul")
        await stores.store_for("b-okul")

        stats = stores.stats()
        self.assertEqual(stats["tavan"], 1)
        self.assertEqual(stats["acik"], 1)
        self.assertGreaterEqual(stats["atilan"], 1)

        # Kapatilan havuzun sunucu tarafinda baglantisi KALMAMALI; acik olan
        # havuzunki durmali. Sayim kontrol baglantisindan yapilir.
        sessions = await self.control_conn.execute(
            "SELECT datname, count(*) FROM pg_stat_activity "
            "WHERE datname IN (%s, %s) GROUP BY datname",
            (self.a_db, self.b_db),
        )
        counts = {str(row[0]): int(row[1]) for row in await sessions.fetchall()}
        self.assertEqual(counts.get(self.a_db, 0), 0, "atilan havuz kapatilmali")
        self.assertEqual(counts.get(self.b_db, 0), 1, "acik havuz yasamali")
        await stores.close()


if __name__ == "__main__":
    unittest.main()
