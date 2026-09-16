"""Fikstür yolu: veritabanı olmadan rapor üretebilmek.

Konteyner her yerde ayakta değildir (CI'ın bir kısmında, geliştiricinin
makinesinde, bu testlerin koştuğu ortamda). Raporun "veri yoksa çöker mi,
fikstürle çalışır mı" sorusu ayakta bir SurrealDB'ye bağlı olmamalıdır.

`CapturingClient`, `store.Store`'un ürettiği **gerçek** UPSERT ifadelerini
yakalar ve satırları bellekte tutar. Yani hat baştan sona koşar (`pipeline`
→ `store`), yalnız taşıma değişir. Böylece rapor, gerçek koşunun yazdığı
satırlarla sınanır — elle kurulmuş sahte satırlarla değil.

Sınır: bu istemci bir veritabanı **değildir**. Sorguları (SELECT) boş
döndürür; süpürme ve mezuniyet temizliği (DELETE) yok sayılır. Raporun
okuma yolu bu satırlar üzerinde `MemoryReader` ile koşar.
"""

from __future__ import annotations

import re
from typing import Any

from .reader import MemoryReader

_UPSERT = re.compile(r"UPSERT type::record\('([A-Za-z_][A-Za-z0-9_]*)', \$k(\d+)\)")


class CapturingClient:
    """`store.DbClient` protokolünü karşılayan bellek içi yazma hedefi."""

    def __init__(self) -> None:
        #: tablo → kayıt anahtarı → satır
        self.tables: dict[str, dict[str, dict[str, Any]]] = {}
        self.statement_count = 0

    async def query(self, sql: str, variables: dict[str, Any]) -> Any:
        self.statement_count += 1
        for table, index in _UPSERT.findall(sql):
            key = str(variables.get(f"k{index}"))
            row = variables.get(f"v{index}")
            if not isinstance(row, dict):
                continue
            bucket = self.tables.setdefault(table, {})
            # MERGE ve CONTENT ayrımı burada önemsizdir: tek koşuda aynı
            # anahtar bir kez yazılır. Yine de birleştirme yapılır ki iki
            # koşuluk bir senaryo satırı sıfırlamasın.
            bucket.setdefault(key, {}).update(row)
        return []

    def as_tables(self) -> dict[str, list[dict[str, Any]]]:
        return {name: list(rows.values()) for name, rows in self.tables.items()}

    def as_reader(self) -> MemoryReader:
        """Yakalanan satırları rapor katmanının okuyabileceği hâle getirir."""
        return MemoryReader(self.as_tables())
