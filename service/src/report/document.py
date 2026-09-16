"""Rapor belgesinin biçimden bağımsız gösterimi.

Üç biçim (JSON, HTML, CSV) **aynı** belgeyi işler; biçim başına ayrı bir veri
yolu yoktur. Bir kural (kanıtsız satır girmez, düşük güvende sayı gösterilmez)
belgede uygulanır, üç biçim birden uyar.

Bölüm türleri:

* `Table` — satır/sütun; CSV'ye **bu** dönüşür.
* `Cards`  — kanıtlı tavsiye kartları (beş bölümlü "Neden?").
* `Note`   — sınır ve açıklama metni.
* `Data`   — ham çıktının makine okunabilir gövdesi (yalnız JSON'da içerik,
  HTML'de satır sayısı özeti).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Rapor zarfının sürümü. Alan eklenirse artırılır; tüketicinin
#: "bu ne zamanki biçim" sorusunu cevaplaması için.
FORMAT_VERSION = 1


@dataclass(slots=True)
class Column:
    key: str
    label: str


@dataclass(slots=True)
class Table:
    id: str
    title: str
    columns: list[Column]
    rows: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""

    @property
    def kind(self) -> str:
        return "table"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": "table",
            "title": self.title,
            "note": self.note,
            "columns": [{"key": c.key, "label": c.label} for c in self.columns],
            "rows": self.rows,
        }


@dataclass(slots=True)
class Cards:
    id: str
    title: str
    items: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""

    @property
    def kind(self) -> str:
        return "cards"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": "cards",
            "title": self.title,
            "note": self.note,
            "items": self.items,
        }


@dataclass(slots=True)
class Note:
    id: str
    title: str
    text: str

    @property
    def kind(self) -> str:
        return "note"

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": "note", "title": self.title, "text": self.text}


@dataclass(slots=True)
class Data:
    id: str
    title: str
    data: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    @property
    def kind(self) -> str:
        return "data"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": "data",
            "title": self.title,
            "note": self.note,
            "data": self.data,
        }


Section = Table | Cards | Note | Data


@dataclass(slots=True)
class Report:
    """Tek bir rapor belgesi."""

    kind: str
    school: str
    generated_at: int
    title: str
    sections: list[Section] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: Öğrenci/öğretmen raporunda kimin için üretildiği.
    subject: str | None = None
    #: Hiç veri bulunamadıysa **işaretlenir**: boş rapor üretilir, uydurulmaz.
    empty: bool = False

    def tables(self) -> list[Table]:
        return [s for s in self.sections if isinstance(s, Table)]

    def to_dict(self) -> dict[str, Any]:
        from . import text as text_mod

        return {
            "report": {
                "type": self.kind,
                "title": self.title,
                "school": self.school,
                "subject": self.subject,
                "generated_at": self.generated_at,
                "generated_at_date": text_mod.date_key(self.generated_at),
                "format_version": FORMAT_VERSION,
                "empty": self.empty,
            },
            "notes": self.notes,
            "sections": [s.to_dict() for s in self.sections],
        }
