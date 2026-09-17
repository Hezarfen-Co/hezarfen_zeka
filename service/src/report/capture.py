"""Fikstür yolu: veritabanı olmadan rapor üretebilmek.

Konteyner her yerde ayakta değildir (CI'ın bir kısmında, geliştiricinin
makinesinde, bu testlerin koştuğu ortamda). Raporun "veri yoksa çöker mi,
fikstürle çalışır mı" sorusu bir veritabanına bağlı olmamalıdır — zaten
ZEKA'nın veritabanı YOKTUR.

`CapturingCaller`, `BridgeStore`'un gönderdiği **gerçek** `insight.*`
çağrılarını yakalar ve satırları bellekte tutar. Yani hat baştan sona koşar
(`pipeline` → `store`), yalnız taşıma değişir: köprüye bir tek bayt gitmez.
Böylece rapor, gerçek koşunun ürettiği satırlarla sınanır — elle kurulmuş
sahte satırlarla değil.

Sınır: bu bir köprü **değildir**. Süpürme ve mezuniyet temizliği başarılı
sayılır (silmeleri yok sayılır), okuma yolu bu satırlar üzerinde
`MemoryReader` ile koşar.
"""

from __future__ import annotations

from typing import Any

from ..store import (
    CAP_PROFILE,
    CAP_PURGE,
    CAP_RECOMMENDATION,
    CAP_RUN,
    CAP_SEGMENT,
    CAP_SCHOOLS,
    CAP_SUMMARY,
    CAP_SWEEP,
    PURGE_TABLES,
    SWEEP_TABLES,
)
from .reader import MemoryReader


class CapturingCaller:
    """`BridgeCaller` şeklini karşılayan bellek içi yazma hedefi."""

    def __init__(self) -> None:
        #: tablo → kayıt anahtarı → satır (okuyucunun beklediği adlarla;
        #: köprünün `zeka_*` tablo adları DEĞİL, raporun gördüğü adlar).
        self.tables: dict[str, dict[str, dict[str, Any]]] = {}
        #: Gönderilen her çağrı: (yetenek, okul, payload).
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def _put(self, table: str, key: str, row: dict[str, Any]) -> None:
        self.tables.setdefault(table, {})[key] = row

    async def call(
        self, capability: str, school: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append((capability, school, payload))

        if capability == CAP_SCHOOLS:
            return {"schools": [school] if school else []}
        if capability == CAP_SWEEP:
            return {"tables": {table: True for table in SWEEP_TABLES}}
        if capability == CAP_PURGE:
            return {"tables": {table: True for table in PURGE_TABLES}}

        rows = payload.get("rows") or []
        if capability == CAP_SUMMARY:
            for row in rows:
                student = str(row.get("student"))
                self._put("student_summary", student, {**row, "school": school})
                for index, item in enumerate(row.get("attention") or []):
                    self._put(
                        "attention_item",
                        f"{student}_{index}",
                        {**item, "student": student, "school": school, "ord": index},
                    )
            return {"written": len(rows)}
        if capability == CAP_RECOMMENDATION:
            for row in rows:
                key = "_".join(
                    str(row.get(name))
                    for name in ("audience", "product", "rule_id", "about", "scope")
                )
                self._put("recommendation", key, {**row, "school": school})
            return {"written": len(rows), "rejected": 0}
        if capability == CAP_SEGMENT:
            for row in rows:
                self._put(
                    "question_segment",
                    str(row.get("question")),
                    {**row, "school": school},
                )
            return {"written": len(rows)}
        if capability == CAP_PROFILE:
            for row in rows:
                key = "_".join(
                    str(row.get(name)) for name in ("student", "dimension", "label")
                )
                self._put("student_segment_profile", key, {**row, "school": school})
            return {"written": len(rows)}
        if capability == CAP_RUN:
            run = payload.get("run") or {}
            self._put("insight_run", str(run.get("run_day")), {**run, "school": school})
            return {"written": 1}
        # `insight.pending.list` (ve tanınmayan bir yetenek).
        return {"students": []}

    def as_tables(self) -> dict[str, list[dict[str, Any]]]:
        return {name: list(rows.values()) for name, rows in self.tables.items()}

    def as_reader(self) -> MemoryReader:
        """Yakalanan satırları rapor katmanının okuyabileceği hâle getirir."""
        return MemoryReader(self.as_tables())
