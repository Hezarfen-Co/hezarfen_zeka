"""Rapor katmanının **okuma** yüzeyi.

Köprü okumaları ve zeka veritabanı BURADA YOKTUR: ZEKA'nın kendi veritabanı
yok (değişmez kural: bir AI servisi uygulama veritabanına asla doğrudan
erişmez), o yüzden rapor katmanı yalnız bir `Reader` protokolü tanımlar ve
bellek içi bir uygulama verir:

* `MemoryReader` — sözlükten okuyan uygulama; fikstür yolu ve testler bunu
  kullanır. Sütun izdüşümünü (`columns`) **gerçekten uygular**; böylece
  dikkat listesi kapısı testte de veri düzeyinde sınanır.

Canlı bir dağıtımın satırlarını okumak backend'in `/insights` uçlarının
işidir; buradan geçen bir okuma yolu yoktur ve olmayacaktır.
"""

from __future__ import annotations

from typing import Any, Protocol

#: `question_segment` satırından rapora **hiç** çıkmayan alanlar.
#: `CIKTI-SOZLESMESI.md` §5: `rationale` modelin gerekçesi (hatalıdır ve
#: sorunun çözüm yapısını anlatır), `trap_choice` doğrudan cevap ipucudur.
#: Ham çıktı teknik ekibe gider ve oradan bir öğrenci ekranına bağlanabilir;
#: bu yüzden ihracın kendisinden çıkarılırlar.
QUESTION_SEGMENT_HIDDEN = ("rationale", "trap_choice")


class Reader(Protocol):
    """Rapor kurucularının gördüğü tek okuma yüzeyi."""

    async def summaries(
        self, school: str, *, columns: tuple[str, ...], student: str | None = None
    ) -> list[dict[str, Any]]: ...

    async def recommendations(
        self,
        school: str,
        *,
        audience: str | None = None,
        audience_role: str | None = None,
    ) -> list[dict[str, Any]]: ...

    async def segment_profiles(
        self, school: str, *, student: str | None = None
    ) -> list[dict[str, Any]]: ...

    async def runs(self, school: str, *, limit: int = 5) -> list[dict[str, Any]]: ...

    async def question_segments(self, school: str) -> list[dict[str, Any]]: ...


class MemoryReader:
    """Sözlükten okuyan `Reader` — testler ve fikstür yolu.

    `tables` anahtarları beş tablonun adıdır; değerler satır listesidir.
    Eksik tablo boş sayılır: **boş veri bir hata değildir**, boş rapor üretir.
    """

    def __init__(self, tables: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.tables = {name: list(rows) for name, rows in (tables or {}).items()}

    def _table(self, name: str) -> list[dict[str, Any]]:
        return [r for r in self.tables.get(name, []) if isinstance(r, dict)]

    async def summaries(
        self, school: str, *, columns: tuple[str, ...], student: str | None = None
    ) -> list[dict[str, Any]]:
        out = []
        for row in self._table("student_summary"):
            if row.get("school") != school:
                continue
            if student is not None and row.get("student") != student:
                continue
            # İzdüşüm gerçekten uygulanır: listede olmayan alan dönmez.
            out.append({k: row[k] for k in columns if k in row})
        return out

    async def recommendations(
        self,
        school: str,
        *,
        audience: str | None = None,
        audience_role: str | None = None,
    ) -> list[dict[str, Any]]:
        out = []
        for row in self._table("recommendation"):
            if row.get("school") != school:
                continue
            if audience is not None and row.get("audience") != audience:
                continue
            if audience_role is not None and row.get("audience_role") != audience_role:
                continue
            out.append(dict(row))
        return out

    async def segment_profiles(
        self, school: str, *, student: str | None = None
    ) -> list[dict[str, Any]]:
        out = []
        for row in self._table("student_segment_profile"):
            if row.get("school") != school:
                continue
            if student is not None and row.get("student") != student:
                continue
            out.append(dict(row))
        return out

    async def runs(self, school: str, *, limit: int = 5) -> list[dict[str, Any]]:
        rows = [r for r in self._table("insight_run") if r.get("school") == school]
        rows.sort(key=lambda r: int(r.get("started_at") or 0), reverse=True)
        return [dict(r) for r in rows[:limit]]

    async def question_segments(self, school: str) -> list[dict[str, Any]]:
        return [
            {k: v for k, v in row.items() if k not in QUESTION_SEGMENT_HIDDEN}
            for row in self._table("question_segment")
            if row.get("school") == school
        ]
