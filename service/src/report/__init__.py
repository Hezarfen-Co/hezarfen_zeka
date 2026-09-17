"""Rapor katmanı — ZEKA'nın ürettiği satırları **okunabilir** hale getirir.

ZEKA sonuç üretiyor ama frontend değişmeyeceği için teslim biçimi rapordur.
Bu paket ZEKA'nın ürettiği satırları okur; köprüye ve veritabanına
gitmez, hiçbir şeye yazmaz. Canlı bir dağıtımın satırlarını okumak
backend'in `/insights` uçlarının işidir.

Dört rapor: `okul` (yönetim), `ogretmen`, `ogrenci` (öğrenci/veli), `ham`
(teknik ekip). Üç biçim: JSON, HTML (tek dosya, basılabilir), CSV.

Belge: `docs/RAPORLAR.md`. Sözleşme: `docs/CIKTI-SOZLESMESI.md`.
"""

from .build import BUILDERS
from .build import build as build_report
from .capture import CapturingCaller
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
from .reader import MemoryReader
from .writer import write

__all__ = [
    "BUILDERS",
    "CapturingCaller",
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
