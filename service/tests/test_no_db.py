"""ZEKA'nın veritabanına doğrudan erişmediğinin yapısal kanıtı.

DEĞİŞMEZ KURAL (2026-09-17, kullanıcı): **bir AI servisi uygulama
veritabanına asla doğrudan erişmez.** ZEKA'nın kendi deposu yoktur: yazdığı
her satır `hezarfen_backend`'e bir `insight.*` yetenek çağrısıyla gider.
`pg_client.py`, `store_pg.py`, `tenants.py`, `store_factory.py` ve `schema/`
silindi ve geri gelmeleri yasaktır.

Bu dosya kuralı davranışta değil **metinde** arar; çünkü asıl tehlike sessizce
geri sızan bir erişim yoludur ve o yol tek bir import'la başlar.

Sınır: yalnız **yürütülebilir kod** taranır. Docstring ve yorum taranmaz —
kuralı ANLATAN cümle yasağın kendisi değildir. Taranan şey `ast` ile
çıkarılan import adları, adlar ve docstring olmayan metin sabitleridir.

İkinci sınır: aranan dizeler burada PARÇALARDAN kurulur. Depoda düz metin
olarak duran bir yasaklı dize, `scripts/ci-sir-tara.py` gibi bir taramayı
gereksiz yere kırmızıya çevirirdi; yasağı arayan test de yasağa benzemek
zorunda değil.
"""

from __future__ import annotations

import ast
import importlib.util
import unittest
from pathlib import Path

SERVICE = Path(__file__).resolve().parent.parent
SRC = SERVICE / "src"

#: Sürücü adı: `import <sürücü>` biçiminde geçen şey erişim yolunun ta
#: kendisidir.
DRIVER = "psyco" + "pg"

#: Bağlantı dizesi şemaları ve servisin artık kullanmadığı ayar adları.
SCHEMES = ("post" + "gres://", "post" + "gresql://")
DSN_KEYS = ("ZEKA_PG" + "_DSN", "ZEKA_DB" + "_")

FORBIDDEN_TEXT = (DRIVER, *SCHEMES, *DSN_KEYS)

#: SQL deyim başlangıçları. Bu kod tabanında SQL büyük harfle yazılır; tek
#: bir tanesi bile kendi sorgumuzu yazdığımız anlamına gelir.
FORBIDDEN_SQL = (
    "SELECT ",
    "INSERT ",
    "UPDATE ",
    "DELETE FROM",
    "UPSERT ",
    "CREATE TABLE",
)

#: Silinen modüller: dosyaları da import edilebilirlikleri de yasak.
REMOVED_MODULES = ("pg_client", "store_pg", "tenants", "store_factory")


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """Modül/sınıf/fonksiyon docstring'i olan `Constant` düğümlerinin kimliği."""
    found: set[int] = set()
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, holders) or not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            found.add(id(first.value))
    return found


def _code_texts(tree: ast.AST) -> list[tuple[int, str]]:
    """Kod metinleri: docstring olmayan metin sabitleri + tanımlayıcı adlar.

    Dönen çiftler `(satır, metin)`; bağlantı dizeleri ve SQL metin sabitinde,
    sürücü adı hem import adı hem metin olarak yakalanır.
    """
    docstrings = _docstring_nodes(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                found.append((node.lineno, node.value))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (alias.name for alias in node.names)
            module = getattr(node, "module", None)
            if module:
                found.append((node.lineno, module))
            found.extend((node.lineno, name) for name in names)
    return found


def _hits(texts: list[tuple[int, str]]) -> list[str]:
    """Verilen kod metinlerinde yasağın geçtiği yerler."""
    found: list[str] = []
    for line, text in texts:
        lowered = text.lower()
        for token in FORBIDDEN_TEXT:
            if token.lower() in lowered:
                found.append(f"{line}: {token!r} geçiyor: {text[:60]!r}")
        for token in FORBIDDEN_SQL:
            if token in text:
                found.append(f"{line}: SQL deyimi {token!r}: {text[:60]!r}")
    return found


def _scan(path: Path) -> list[str]:
    """Bir dosyada yasağın geçtiği yerler; boş liste = temiz."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [f"{path}:{hit}" for hit in _hits(_code_texts(tree))]


class SourceScanTests(unittest.TestCase):
    def test_source_tree_has_no_database_access(self) -> None:
        self.assertTrue(SRC.is_dir(), f"kaynak ağacı yok: {SRC}")
        files = sorted(SRC.rglob("*.py"))
        self.assertGreater(len(files), 10, "kaynak ağacı beklenenden küçük")
        hits: list[str] = []
        for path in files:
            hits.extend(_scan(path))
        self.assertEqual(hits, [], "\n".join(hits))

    def test_the_scan_would_catch_a_real_offence(self) -> None:
        """Tarama gerçekten bakıyor mu: gömülü bir suç yakalanmalı."""
        offence = "\n".join(
            (
                f"import {DRIVER}",
                f"DSN = {SCHEMES[1]!r}",
                f"KEY = {DSN_KEYS[0]!r}",
                "Q = 'SELECT 1'",
            )
        )
        tree = ast.parse(offence)
        hits = _hits(_code_texts(tree))
        self.assertEqual(len(hits), 4, hits)
        # Ve docstring'deki anlatım suç sayılmaz.
        polite = f'def f():\n    """{DRIVER} import edilmez; UPSERT yok."""\n'
        self.assertEqual(_hits(_code_texts(ast.parse(polite))), [])

    def test_the_test_files_themselves_stay_clean(self) -> None:
        """Test dosyaları da kurala uyar: yasaklı dize düz metin durmaz."""
        for path in sorted((SERVICE / "tests").rglob("*.py")):
            with self.subTest(path=path.name):
                raw = path.read_text(encoding="utf-8")
                for token in FORBIDDEN_TEXT:
                    self.assertNotIn(token, raw, f"{path}: {token!r}")


class RemovedModuleTests(unittest.TestCase):
    def test_removed_modules_are_not_importable(self) -> None:
        for name in REMOVED_MODULES:
            with self.subTest(module=name):
                self.assertIsNone(importlib.util.find_spec(f"src.{name}"))

    def test_removed_module_files_do_not_exist(self) -> None:
        for name in REMOVED_MODULES:
            with self.subTest(module=name):
                self.assertEqual(list(SERVICE.rglob(f"{name}.py")), [])

    def test_no_surql_schema_or_sql_bundle_remains(self) -> None:
        self.assertEqual(list(SERVICE.rglob("*.surql")), [])
        self.assertEqual(list(SERVICE.rglob("*.sql")), [])


if __name__ == "__main__":
    unittest.main()
