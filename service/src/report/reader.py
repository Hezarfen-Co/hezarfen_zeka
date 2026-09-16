"""Rapor katmanının **okuma** yüzeyi — ZEKA'nın kendi beş tablosu.

Köprüye gidilmez, okul veritabanına dokunulmaz: rapor yalnız gece koşusunun
ZEKA veritabanına yazdığı satırları okur (`docs/CIKTI-SOZLESMESI.md` §0).

Sorgu kalıpları sözleşmenin §6'sındandır. Oradaki **en önemli tuzak** burada
da geçerlidir: iki nokta taşıyan her kimlik karşılaştırması `type::string()`
ile sarılır, yoksa SurrealDB 3 metni uçta `record`'a çevirir ve sorgu
**sessizce sıfır satır** döndürür.

İki uygulama vardır:

* `DbReader`  — gerçek SurrealDB (`store.SurrealHttpClient` ya da `DbClient`).
* `MemoryReader` — sözlükten okuyan sahte; testler ve fikstür yolu için.
  Sütun izdüşümünü (`columns`) **gerçekten uygular**; böylece dikkat listesi
  kapısı testte de veri düzeyinde sınanır.
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


def _rows(result: Any) -> list[dict[str, Any]]:
    """SurrealDB `/rpc` cevabından satır listesini çıkarır.

    Cevap iki katmanlıdır: ifade listesi → `result` listesi → satır.
    Sahte istemciler düz liste döndürebilir; o da kabul edilir.
    """
    if not isinstance(result, list):
        return []
    out: list[dict[str, Any]] = []
    for item in result:
        if isinstance(item, dict) and "result" in item:
            inner = item.get("result")
            if isinstance(inner, list):
                out.extend(r for r in inner if isinstance(r, dict))
        elif isinstance(item, dict):
            out.append(item)
    return out


class DbReader:
    """Gerçek ZEKA veritabanından okur. Yazma yolu **yoktur**."""

    def __init__(self, client: Any) -> None:
        self._client = client
        #: Çalıştırılan SurrealQL ifadeleri — kapı testinin kanıtı.
        self.statements: list[str] = []

    async def _query(self, sql: str, variables: dict[str, Any]) -> list[dict[str, Any]]:
        self.statements.append(sql)
        return _rows(await self._client.query(sql, variables))

    async def summaries(
        self, school: str, *, columns: tuple[str, ...], student: str | None = None
    ) -> list[dict[str, Any]]:
        """`student_summary` — **sütun listesi çağırandan gelir**.

        Öğrenci raporunda `attention` bu listede yoktur; satır veritabanından
        dikkat listesi taşımadan çıkar (`gate.py` başı).
        """
        select = ", ".join(columns)
        sql = f"SELECT {select} FROM student_summary WHERE school = $school"
        variables: dict[str, Any] = {"school": school}
        if student is not None:
            sql += " AND student = type::string($student)"
            variables["student"] = student
        return await self._query(sql + ";", variables)

    async def recommendations(
        self,
        school: str,
        *,
        audience: str | None = None,
        audience_role: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM recommendation WHERE school = $school"
        variables: dict[str, Any] = {"school": school}
        if audience is not None:
            sql += " AND audience = type::string($audience)"
            variables["audience"] = audience
        if audience_role is not None:
            sql += " AND audience_role = $role"
            variables["role"] = audience_role
        return await self._query(sql + ";", variables)

    async def segment_profiles(
        self, school: str, *, student: str | None = None
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT school, student, dimension, label, n_answers, contrast, "
            "confidence, computed_at FROM student_segment_profile "
            "WHERE school = $school"
        )
        variables: dict[str, Any] = {"school": school}
        if student is not None:
            sql += " AND student = type::string($student)"
            variables["student"] = student
        return await self._query(sql + ";", variables)

    async def runs(self, school: str, *, limit: int = 5) -> list[dict[str, Any]]:
        sql = (
            "SELECT * FROM insight_run WHERE school = $school "
            f"ORDER BY started_at DESC LIMIT {int(limit)};"
        )
        return await self._query(sql, {"school": school})

    async def question_segments(self, school: str) -> list[dict[str, Any]]:
        select = ", ".join(
            (
                "question",
                "exam",
                "course",
                "subject",
                "bilissel_talep",
                "dikkat_tuzagi",
                "okuma_yuku",
                "adim_sayisi",
                "confidence",
                "downstream_dimensions",
                "experimental_dimensions",
                "computed_at",
            )
        )
        sql = f"SELECT {select} FROM question_segment WHERE school = $school;"
        return await self._query(sql, {"school": school})


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
