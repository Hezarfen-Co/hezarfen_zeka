"""Rapor katmanı — ZEKA'nın ürettiği satırları **okunabilir** hale getirir.

ZEKA sonuç üretiyor ama frontend değişmeyeceği için teslim biçimi rapordur.
Bu paket yalnız ZEKA'nın kendi beş tablosunu **okur**; köprüye gitmez, okul
veritabanına dokunmaz, hiçbir şeye yazmaz.

Dört rapor: `okul` (yönetim), `ogretmen`, `ogrenci` (öğrenci/veli), `ham`
(teknik ekip). Üç biçim: JSON, HTML (tek dosya, basılabilir), CSV.

Belge: `docs/RAPORLAR.md`. Sözleşme: `docs/CIKTI-SOZLESMESI.md`.
"""

from .build import BUILDERS
from .build import build as build_report
from .capture import CapturingClient
from .document import Report
from .gate import (
    REPORT_TYPES,
    STAFF_TYPES,
    STUDENT_FACING_TYPES,
    ReportGateError,
    StaffBundle,
    StudentFacingBundle,
)
from .load import load_bundle
from .reader import DbReader, MemoryReader
from .writer import write

__all__ = [
    "BUILDERS",
    "CapturingClient",
    "DbReader",
    "MemoryReader",
    "REPORT_TYPES",
    "Report",
    "ReportGateError",
    "STAFF_TYPES",
    "STUDENT_FACING_TYPES",
    "StaffBundle",
    "StudentFacingBundle",
    "build_report",
    "load_bundle",
    "write",
]
