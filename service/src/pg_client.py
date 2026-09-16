"""`PgClient` protokolunun psycopg 3 uzerindeki uygulamasi.

`store_pg.py` bu modulu **import etmez**; hatti kuran taraf istemciyi disaridan
verir. Boylece birim testleri ve `--dry-run` psycopg kurulu olmadan da kosar —
`store.py`'nin surucu bagimsizligiyla ayni gerekce.

---------------------------------------------------------------------------
Neden psycopg, ve neden yeni bir bagimlilik
---------------------------------------------------------------------------
Servisin bugune kadar tek calisma zamani bagimliligi `aioquic` idi; cerceveleme
`struct`, sertifika `urllib`, ozet `hashlib` ile yapiliyordu. Postgres'te bu
mumkun degil: tel protokolu stdlib'de yok ve elle yazilmasi gereken bir sey de
degil. `psycopg[binary]` hazir tekerlekle gelir, derleyici istemez.

Surum PINLI. Gerekce `requirements.txt`'in basindaki ile ayni: acik araliklar
ayni Containerfile'in bugun ve yarin farkli davranmasina yol acar.

---------------------------------------------------------------------------
Baglanti bilgisi
---------------------------------------------------------------------------
`ZEKA_PG_DSN` ortam degiskeninden gelir. Bu bir **sirdir**: hicbir kosulda
loglanmaz. `PgPool.describe()` yalnizca host/port/veritabani doner, kullanici
adi ve parola asla.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Sequence

log = logging.getLogger(__name__)

#: Havuzun acik tutacagi baglanti sayisi. Gece kosusu tek is parcacigidir;
#: havuz derinligi yeniden baglanma icin var, esazamanlilik icin degil.
DEFAULT_POOL_MIN = 1
DEFAULT_POOL_MAX = 4


class PgError(RuntimeError):
    """Yazma/okuma sirasinda alinan hata; ifade metni ekli."""

    def __init__(self, message: str, *, statement: str = "") -> None:
        super().__init__(message)
        self.statement = statement


class PsycopgClient:
    """`PgClient` protokolunun tek baglanti uzerindeki uygulamasi.

    `transaction()` psycopg'nin kendi transaction baglamini dondurur; ic ice
    cagrilarda psycopg otomatik olarak SAVEPOINT kullanir, yani `PgStore`'un
    grup transaction'lari guvenle ic ice gecebilir.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    @classmethod
    async def connect(cls, dsn: str | None = None) -> "PsycopgClient":
        """`ZEKA_PG_DSN` ile baglanir. DSN loglanmaz."""
        import psycopg

        target = dsn or os.environ.get("ZEKA_PG_DSN", "")
        if not target:
            raise PgError(
                "ZEKA_PG_DSN tanimli degil; okul veritabanina baglanilamaz"
            )
        # autocommit: transaction sinirlarini PgStore belirler, surucu degil.
        conn = await psycopg.AsyncConnection.connect(target, autocommit=True)
        log.info("okul veritabanina baglanildi (%s)", _describe(target))
        return cls(conn)

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        try:
            async with self._conn.cursor() as cur:
                await cur.execute(sql, tuple(params))
        except Exception as exc:
            raise PgError(str(exc), statement=_head(sql)) from exc

    async def executemany(
        self, sql: str, rows: Sequence[Sequence[Any]]
    ) -> None:
        if not rows:
            return
        try:
            async with self._conn.cursor() as cur:
                await cur.executemany(sql, [tuple(r) for r in rows])
        except Exception as exc:
            raise PgError(str(exc), statement=_head(sql)) from exc

    async def fetch(
        self, sql: str, params: Sequence[Any] = ()
    ) -> list[tuple[Any, ...]]:
        try:
            async with self._conn.cursor() as cur:
                await cur.execute(sql, tuple(params))
                return list(await cur.fetchall())
        except Exception as exc:
            raise PgError(str(exc), statement=_head(sql)) from exc

    def transaction(self) -> Any:
        return self._conn.transaction()

    async def close(self) -> None:
        await self._conn.close()


def _head(sql: str) -> str:
    """Ifadenin ilk satiri — hata mesajina konacak kadari.

    Tam ifade YAZILMAZ: toplu yazimda binlerce satirlik parametre tasiyabilir
    ve o parametreler ogrenci verisidir.
    """
    for line in sql.strip().splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:120]
    return ""


def _describe(dsn: str) -> str:
    """DSN'in loglanabilir kismi: host/port/veritabani.

    Kullanici adi ve parola **hicbir kosulda** donmez. Bir baglanti hatasinin
    log satirinda parola gormek, bu servisin sir tarama testinin (`ci-sir-tara.py`)
    tam olarak aradigi sey.
    """
    try:
        import urllib.parse

        parsed = urllib.parse.urlsplit(dsn)
        if parsed.hostname:
            port = f":{parsed.port}" if parsed.port else ""
            return f"{parsed.hostname}{port}{parsed.path}"
    except Exception:  # noqa: BLE001
        pass
    return "<cozumlenemedi>"
