"""Depolama katmanini SECEN tek yer.

ZEKA iki depoya yazabilir:

* **PostgreSQL** (`store_pg.PgStore`) — okulun kendi veritabani. Backend
  SurrealDB'den Postgres'e gectiginden beri dogru olan bu.
* **SurrealDB** (`store.Store`) — eski kurulum. Hala calisiyor ve testleri
  geciyor; gecis tamamlanana kadar duruyor.

Secim TEK bir degiskene bakar: `ZEKA_PG_DSN` doluysa Postgres, bossa SurrealDB.
Iki ayri "mod" bayragi yok, cunku bayrakla DSN birbirine ters dustugunde hangi
tarafin kazandigi tahmin isine doner.

---------------------------------------------------------------------------
Neden ayni arayuz
---------------------------------------------------------------------------
`pipeline.py` ve `scheduler.py` hangi depoya yazdiklarini BILMEZ. Ikisi de
ayni sekiz yontemi cagirir (`write_summaries`, `write_recommendations`,
`write_question_segments`, `write_segment_profiles`, `write_run`,
`last_pending`, `sweep`, `purge_departed`). Gecisin hattaki maliyeti bu yuzden
sifir: depo degisti, hesap kodu degismedi.
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)


def is_postgres() -> bool:
    """Postgres'e mi yazilacak? Tek olcut `ZEKA_PG_DSN`."""
    return bool(os.environ.get("ZEKA_PG_DSN", "").strip())


async def open_store(dsn: str | None = None) -> tuple[Any, Any]:
    """Yapilandirmaya gore depoyu acar.

    `(store, client)` doner; cagiran taraf isi bitince `client.close()`
    cagirmalidir.
    """
    target = (dsn or os.environ.get("ZEKA_PG_DSN", "")).strip()
    if target:
        from .pg_client import PsycopgClient
        from .store_pg import PgStore

        client = await PsycopgClient.connect(target)
        return PgStore(client), client

    from .store import Store, SurrealHttpClient

    url = os.environ.get("ZEKA_DB_HTTP_URL", "").strip()
    if not url:
        raise RuntimeError(
            "Ne ZEKA_PG_DSN ne ZEKA_DB_HTTP_URL tanimli — nereye yazilacagi "
            "belli degil. Postgres icin ZEKA_PG_DSN verin."
        )
    log.warning(
        "SurrealDB deposu kullaniliyor (ZEKA_PG_DSN bos). Backend Postgres'e "
        "gecti; uretimde ZEKA_PG_DSN verilmelidir."
    )
    client = SurrealHttpClient(
        url,
        namespace=os.environ.get("ZEKA_DB_NS", "hezarfen"),
        database=os.environ.get("ZEKA_DB_NAME", "zeka"),
        user=os.environ.get("ZEKA_DB_USER", "root"),
        password=os.environ.get("ZEKA_DB_PASSWORD", "root"),
    )
    return Store(client), client


def describe() -> str:
    """Acilista loglanacak tek satir. DSN'in kendisi ASLA loglanmaz."""
    if not is_postgres():
        return "depo: SurrealDB (eski kurulum)"
    from .pg_client import _describe

    return "depo: PostgreSQL (%s)" % _describe(os.environ["ZEKA_PG_DSN"])
