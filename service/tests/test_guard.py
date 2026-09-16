"""KORUMA TESTİ — yasaklı veri alanlarına atıf yapılmadığını kaynak tarayarak doğrular.

Kaynak: `20_tavsiye_sistemi_tasarim.md` §6.5 **Kapı 2**
(`tests/insight_forbidden_tables.rs` / `tests/telemetry.rs` deseninin Python
karşılığı), `MODULLER.md` §2.1 kapanış notu.

**Neden var:** Kapı 1 (tip düzeyinde erişim daraltması) birincil savunmadır —
`Source` arayüzünde yemek/ödeme/diyet metodu **yoktur**, dolayısıyla çağrılamaz.
Bu test ikincil savunmadır: sapmayı yakalar. Birisi ileride bu alanlara
ulaşmaya çalışırsa derleme değil, **test** düşer.

**Politika yazıyla korunmaz.** Bu dosya, KVKK/etik analizinin sonucunu kod
düzeyinde kilitler.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"

# `20_tavsiye_sistemi_tasarim.md` §1.2-C / §6.5 yasaklı küme + `MODULLER.md`
# §1 grafiğindeki KIRMIZI tablolar.
FORBIDDEN_TABLES = (
    "dietary_profile",
    "meal_ledger",
    "meal_booking",
    "meal_attendance",
    "menu",
    "menu_dish",
    "payment_ledger",
    "fee_plan",
    "fee_plan_assignment",
    "work_entry",
)

# Köprü izin listesine sızabilecek yol önekleri (`[T§6.5]` Kapı 3'ün karşılığı).
FORBIDDEN_PATHS = ("/meals", "/payments", "/dietary", "/work", "/menus")

# Serbest metin ve mahremiyet sınırındaki kaynaklar: motor bunları okumaz
# (`[T§1.1]` 🟡 kuralı, `[T§6.8]` "chatbot türevi sinyal" satırı).
FORBIDDEN_TEXT_SOURCES = ("chatbot_message", "chatbot_thread", "board_stroke")


def _python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


class TestForbiddenDataFields(unittest.TestCase):
    """`compute/` paketinin tamamı taranır — asıl koruma noktası burasıdır."""

    def _scan(self, files: list[Path], needles: tuple[str, ...]) -> list[str]:
        hits: list[str] = []
        for path in files:
            text = path.read_text(encoding="utf-8")
            for needle in needles:
                # Kelime sınırı: "menu" bir başka kelimenin içinde geçerse
                # yanlış alarm vermesin.
                pattern = rf"\b{re.escape(needle)}\b"
                for match in re.finditer(pattern, text):
                    line = text.count("\n", 0, match.start()) + 1
                    hits.append(f"{path.name}:{line} → {needle}")
        return hits

    def test_compute_package_has_no_forbidden_table_names(self) -> None:
        files = _python_files(SRC / "compute")
        self.assertTrue(files, "compute paketinde taranacak dosya yok")
        hits = self._scan(files, FORBIDDEN_TABLES)
        self.assertEqual(
            hits,
            [],
            "compute/ altında yasaklı tablo adı geçiyor (etik kapı ihlali): "
            + ", ".join(hits),
        )

    def test_compute_package_has_no_forbidden_paths(self) -> None:
        hits = self._scan(_python_files(SRC / "compute"), FORBIDDEN_PATHS)
        self.assertEqual(hits, [], ", ".join(hits))

    def test_compute_package_does_not_touch_free_text_sources(self) -> None:
        hits = self._scan(_python_files(SRC / "compute"), FORBIDDEN_TEXT_SOURCES)
        self.assertEqual(hits, [], ", ".join(hits))

    def test_owned_modules_are_clean_too(self) -> None:
        """Hesap paketinin dışındaki kendi dosyalarımız da taranır."""
        owned = [
            SRC / name
            for name in ("store.py", "pipeline.py", "scheduler.py", "cli.py")
            if (SRC / name).exists()
        ]
        self.assertTrue(owned, "taranacak modül bulunamadı")
        hits = self._scan(owned, FORBIDDEN_TABLES + FORBIDDEN_PATHS)
        self.assertEqual(hits, [], ", ".join(hits))


class TestComputePurity(unittest.TestCase):
    """Hesap modülleri saf kalmalı: ağ yok, veritabanı yok, dosya yazma yok."""

    IMPURE_IMPORTS = (
        "import socket",
        "import http",
        "import urllib",
        "import requests",
        "import httpx",
        "import aiohttp",
        "import sqlite3",
        "import surrealdb",
        "from surrealdb",
    )

    def test_no_io_imports_in_compute(self) -> None:
        for path in _python_files(SRC / "compute"):
            text = path.read_text(encoding="utf-8")
            for needle in self.IMPURE_IMPORTS:
                self.assertNotIn(needle, text, f"{path.name}: {needle}")

    def test_compute_does_not_import_store_or_pipeline(self) -> None:
        """Bağımlılık yönü tek yönlüdür: pipeline → compute, tersi değil."""
        for path in _python_files(SRC / "compute"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("from ..store", text, path.name)
            self.assertNotIn("from ..pipeline", text, path.name)
            self.assertNotIn("from ..source", text, path.name)


class TestSourceContractIsNotWidened(unittest.TestCase):
    """`Source` protokolüne yeni bir veri yüzeyi eklenmediğini doğrular."""

    ALLOWED = {
        "profile",
        "marks",
        "attendance",
        "pomodoro",
        "homework_report",
        "homework_list",
        "notes",
        "course_notes",
    }

    def test_pipeline_calls_only_allowed_source_methods(self) -> None:
        text = (SRC / "pipeline.py").read_text(encoding="utf-8")
        called = set(re.findall(r"\bsource\.(\w+)\(", text))
        self.assertTrue(called)
        self.assertEqual(
            called - self.ALLOWED,
            set(),
            "pipeline Source arayüzünün dışına çıkıyor: "
            + ", ".join(sorted(called - self.ALLOWED)),
        )


if __name__ == "__main__":
    unittest.main()
