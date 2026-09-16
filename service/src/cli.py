"""Geliştirme aracı — köprü olmadan hattı koşturur.

    python -m src.cli run --school ataturk-anadolu --source file \
        --fixtures service/fixtures --out sonuc.json
    python -m src.cli run --school X --source file --fixtures ... --dry-run
    python -m src.cli schema
    python -m src.cli rules
    python -m src.cli report --school X --type okul --format html --out DIZIN

---------------------------------------------------------------------------
BURADA HTTP SUNUCUSU YOKTUR VE OLMAYACAKTIR
---------------------------------------------------------------------------
Çelebi'nin geliştirme amaçlı HTTP sunucusu üretim imajında durdu ve denetimde
risk olarak işaretlendi. Aynı hatayı tekrarlamıyoruz: bu dosya bir CLI'dır,
bir servis değil. `serve` alt komutu **yoktur**; gece işi `scheduler.py`
tarafından süreç içinden tetiklenir.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from .compute import recommend as recommend_mod
from .compute.attention import unavailable_triggers
from .pipeline import DEFAULT_BUDGET_MS, run_school
from .scheduler import Scheduler
from .store import (
    RETENTION_DAYS,
    CollectingClient,
    Store,
    SurrealHttpClient,
    apply_schema,
    schema_field_types,
    schema_tables,
)

from .store import SCHEMA_PATH  # noqa: E402  (tek kaynak: store.py)


def _build_source(kind: str, fixtures: str | None) -> Any:
    """Kaynak nesnesini kurar.

    `file` → `FileSource` (JSON dosyalarından okur). `FileSource` ayrı bir
    ajanın yazdığı `src/source.py` içindedir; bu yüzden import **tembel**
    yapılır ve yoksa anlaşılır bir hata verilir.
    """
    if kind != "file":
        raise SystemExit(
            f"bilinmeyen kaynak: {kind}. Bu araç yalnız 'file' destekler; "
            "köprü kaynağı üretimde scheduler tarafından kurulur."
        )
    if not fixtures:
        raise SystemExit("--fixtures zorunlu (JSON fikstür dizini)")
    try:
        from .source import FileSource  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "FileSource bulunamadı (src/source.py). Bu dosya köprü ajanının "
            f"sorumluluğundadır. Ayrıntı: {exc}"
        ) from exc
    return FileSource(Path(fixtures))


async def _cmd_run(args: argparse.Namespace) -> int:
    source = _build_source(args.source, args.fixtures)
    # `--dry-run` ifadeleri toplar, `--db-url` gercekten yazar. Ikisi de
    # verilmezse hicbir sey yazilmaz ve kullanici bunu bilmelidir.
    client: Any
    if args.dry_run:
        client = CollectingClient()
    else:
        client = _build_client(args)
        client.ensure_namespace()
    store = Store(client)
    now_ms = args.now or int(time.time() * 1000)
    students = args.students.split(",") if args.students else None

    result = await run_school(
        source,
        store,
        args.school,
        now_ms=now_ms,
        student_ids=students,
        term_start_ms=args.term_start,
        budget_ms=args.budget_ms,
    )

    payload = {
        "run": dataclasses.asdict(result),
        "written_statements": (
            len(client.statements)
            if isinstance(client, CollectingClient)
            else client.statement_count
        ),
        "unavailable_triggers": unavailable_triggers(),
        "unavailable_rules": recommend_mod.unavailable_rules(),
    }
    if args.verbose and isinstance(client, CollectingClient):
        payload["statements"] = [
            {"sql": sql, "variables": variables}
            for sql, variables in client.statements
        ]
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"yazıldı: {args.out}")
    else:
        print(text)
    return 0 if result.status in ("ok", "partial") else 1


# ---------------------------------------------------------------------------
# DEPOLAMA / ZAMANLAYICI KOMUTLARI
# ---------------------------------------------------------------------------
# Buradaki komutlar GERCEK bir SurrealDB ornegine baglanir. Baglanti kurulumu
# tek bir yerde (`_build_client`) toplanir; parola asla basilmaz.


def _add_db_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db-url",
        help="SurrealDB HTTP adresi, orn. http://hzk-zeka:8000 "
        "(verilmezse ZEKA_DB_HTTP_URL ortam degiskeni)",
    )
    parser.add_argument("--db-ns", default=None, help="namespace (vars: hezarfen)")
    parser.add_argument("--db-name", default=None, help="veritabani (vars: zeka)")
    parser.add_argument("--db-user", default=None, help="kullanici (vars: root)")
    parser.add_argument("--db-pass", default=None, help="parola (vars: root)")


def _build_client(args: argparse.Namespace) -> SurrealHttpClient:
    """Gercek veritabani istemcisini kurar; adres yoksa anlasilir hata verir."""
    url = args.db_url or os.environ.get("ZEKA_DB_HTTP_URL", "")
    if not url:
        raise SystemExit(
            "--db-url verilmedi (ya da ZEKA_DB_HTTP_URL bos). Ornek: "
            "--db-url http://hzk-zeka:8000"
        )
    return SurrealHttpClient(
        url,
        namespace=args.db_ns or os.environ.get("ZEKA_DB_NS", "hezarfen"),
        database=args.db_name or os.environ.get("ZEKA_DB_NAME", "zeka"),
        user=args.db_user or os.environ.get("ZEKA_DB_USER", "root"),
        password=args.db_pass or os.environ.get("ZEKA_DB_PASSWORD", "root"),
    )


def _cmd_schema(args: argparse.Namespace) -> int:
    """Semayi basar; `--apply` verilirse gercekten yukler ve DOGRULAR."""
    if not getattr(args, "apply", False):
        print(SCHEMA_PATH.read_text(encoding="utf-8"))
        return 0
    client = _build_client(args)
    client.ensure_namespace()
    report = apply_schema(client)
    payload: dict[str, Any] = {
        "ifade_toplam": report.total,
        "uygulanan": report.applied,
        "hatalar": report.errors,
    }
    # Yuklendi demek yetmez: alanlarin gercekten var oldugunu OKUYARAK gosteriyoruz.
    if report.ok:
        payload["tablolar"] = sorted(schema_tables(client))
        payload["alanlar"] = {
            table: sorted(schema_field_types(client, table))
            for table in (
                "student_summary",
                "recommendation",
                "insight_run",
                "question_segment",
                "student_segment_profile",
            )
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if report.ok else 1


def _cmd_sweep(args: argparse.Namespace) -> int:
    """Saklama suresi supurmesi. Once/sonra satir sayilarini basar."""
    client = _build_client(args)
    now = args.now or int(time.time() * 1000)

    def counts() -> dict[str, int]:
        out: dict[str, int] = {}
        for table in RETENTION_DAYS:
            rows = client.query_sync(f"SELECT count() FROM {table} GROUP ALL;")
            result = rows[0].get("result") or []
            out[table] = int(result[0]["count"]) if result else 0
        return out

    before = counts()
    store = Store(client)
    results = asyncio.run(store.sweep(now))
    after = counts()
    print(
        json.dumps(
            {
                "now_ms": now,
                "once": before,
                "sonra": after,
                "silinen": {t: before[t] - after[t] for t in before},
                "tablo_sonuclari": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if all(results.values()) else 1


async def _cmd_schedule(args: argparse.Namespace) -> int:
    """Zamanlayiciyi elle tetikler -- gece penceresini BEKLEMEDEN.

    `--ticks` verilirse tam `serve()` dongusu kosar (test kipi); verilmezse
    tek tur (`run_once`) kosar. Ikisi de ayni kod yolunu kullanir.
    """
    client = _build_client(args)
    store = Store(client)
    schools = [s.strip() for s in args.schools.split(",") if s.strip()]
    budgets: dict[str, int] = {}
    for pair in (args.budget or "").split(","):
        if "=" in pair:
            name, value = pair.split("=", 1)
            budgets[name.strip()] = int(value)
    root = Path(args.fixtures) if args.fixtures else None
    if root is None:
        raise SystemExit("--fixtures zorunlu (her okul icin bir alt dizin)")
    from .source import FileSource  # type: ignore[attr-defined]

    stamp = args.now or int(time.time() * 1000)
    scheduler = Scheduler(
        lambda school: FileSource(root),
        store,
        schools,
        budget_ms=args.budget_ms,
        budgets=budgets,
        term_start_ms=args.term_start,
        clock_fn=lambda: stamp,
    )
    if args.ticks:
        await scheduler.serve(
            tick_seconds=args.tick_seconds, ignore_window=True, max_ticks=args.ticks
        )
        results = []
    else:
        results = await scheduler.run_once(stamp)
    print(
        json.dumps(
            {
                "kosulan_okullar": [r.school for r in results],
                "sonuclar": [dataclasses.asdict(r) for r in results],
                "dusen_okullar": scheduler._failures,
                "bekleyen": {s: scheduler.pending_for(s) for s in schools},
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 0


async def _cmd_report(args: argparse.Namespace) -> int:
    """Rapor üretir — ZEKA'nın **kendi** veritabanından okuyarak.

        python -m src.cli report --school X --type okul --format html --out DIZIN

    İki okuma yolu vardır ve ikisi de aynı rapor kodunu besler:

    * `--db-url` (ya da `ZEKA_DB_HTTP_URL`): gerçek ZEKA veritabanı.
    * `--fixtures`: veritabanı yoksa hattı fikstürden koşturur, yazılan
      satırları bellekte yakalar (`report/capture.py`) ve raporu onlardan
      üretir. Konteyner ayakta olmayan makinede de uçtan uca çalışır.
    """
    from .report import load as load_mod
    from .report import reader as reader_mod
    from .report import writer as writer_mod
    from .report.build import build as build_report
    from .report.capture import CapturingClient
    from .report.gate import REPORT_TYPES

    if args.type not in REPORT_TYPES:
        raise SystemExit(f"bilinmeyen rapor tipi: {args.type}")

    now_ms = args.now or int(time.time() * 1000)

    reader: Any
    if args.fixtures:
        # Fikstür yolu: hattı koştur, yazılan satırları yakala.
        source = _build_source(args.source, args.fixtures)
        client = CapturingClient()
        await run_school(
            source,
            Store(client),
            args.school,
            now_ms=now_ms,
            term_start_ms=args.term_start,
            budget_ms=args.budget_ms,
        )
        reader = client.as_reader()
    else:
        reader = reader_mod.DbReader(_build_client(args))

    try:
        bundle = await load_mod.load_bundle(
            reader,
            args.school,
            args.type,
            now_ms=now_ms,
            student=args.about,
            teacher=args.teacher,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    report = build_report(args.type, bundle)
    paths = writer_mod.write(report, args.out, args.format)
    print(
        json.dumps(
            {
                "tip": report.kind,
                "bicim": args.format,
                "okul": report.school,
                "kim": report.subject,
                "bos": report.empty,
                "dosyalar": [str(p) for p in paths],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _cmd_rules(_args: argparse.Namespace) -> int:
    """Kural kataloğunu ve üretilemeyen kuralları basar."""
    payload = {
        "produced": recommend_mod.RULE_CATALOG,
        "unavailable": recommend_mod.unavailable_rules(),
        "unavailable_triggers": unavailable_triggers(),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.cli",
        description="ZEKA geliştirme aracı — köprüsüz hat koşturucu.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="bir okul için hattı koştur")
    run.add_argument("--school", required=True)
    run.add_argument("--source", default="file", choices=["file"])
    run.add_argument("--fixtures", help="JSON fikstür dizini")
    run.add_argument("--students", help="virgülle ayrılmış öğrenci kimlikleri")
    run.add_argument("--now", type=int, help="unix ms; varsayılan şimdi")
    run.add_argument(
        "--term-start", type=int, help="dönem başlangıcı unix ms (soğuk başlangıç)"
    )
    run.add_argument("--budget-ms", type=int, default=DEFAULT_BUDGET_MS)
    run.add_argument("--out", help="sonucu bu JSON dosyasına yaz")
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="veritabanına yazma; ifadeleri say ve sonucu bas",
    )
    run.set_defaults(func=_cmd_run, is_async=True)

    _add_db_flags(run)

    schema = sub.add_parser("schema", help="ZEKA şema DDL'ini bas ya da yükle")
    schema.add_argument(
        "--apply",
        action="store_true",
        help="DDL'i gerçekten veritabanına yükle ve INFO ile doğrula",
    )
    _add_db_flags(schema)
    schema.set_defaults(func=_cmd_schema, is_async=False)

    sweep = sub.add_parser("sweep", help="saklama süresi süpürmesini koştur")
    sweep.add_argument("--now", type=int, help="unix ms; varsayılan şimdi")
    _add_db_flags(sweep)
    sweep.set_defaults(func=_cmd_sweep, is_async=False)

    schedule = sub.add_parser(
        "schedule", help="zamanlayıcıyı elle tetikle (gece penceresini beklemeden)"
    )
    schedule.add_argument("--schools", required=True, help="virgülle ayrılmış slug")
    schedule.add_argument("--fixtures", required=True)
    schedule.add_argument("--now", type=int)
    schedule.add_argument("--term-start", type=int)
    schedule.add_argument("--budget-ms", type=int, default=DEFAULT_BUDGET_MS)
    schedule.add_argument(
        "--budget", help="okul başına bütçe: 'okul-a=1000,okul-b=60000'"
    )
    schedule.add_argument("--ticks", type=int, help="test kipi: kaç tik atılsın")
    schedule.add_argument("--tick-seconds", type=float, default=0.01)
    _add_db_flags(schedule)
    schedule.set_defaults(func=_cmd_schedule, is_async=True)

    report = sub.add_parser(
        "report", help="rapor üret (okul|ogretmen|ogrenci|ham × json|html|csv)"
    )
    report.add_argument("--school", required=True)
    report.add_argument(
        "--type", required=True, choices=["okul", "ogretmen", "ogrenci", "ham"]
    )
    report.add_argument("--format", required=True, choices=["json", "html", "csv"])
    report.add_argument("--out", required=True, help="çıktı dizini")
    report.add_argument("--about", help="öğrenci kimliği (öğrenci raporu için)")
    report.add_argument("--teacher", help="öğretmen kimliği (öğretmen raporu için)")
    report.add_argument("--now", type=int, help="unix ms; varsayılan şimdi")
    report.add_argument(
        "--fixtures",
        help="veritabanı yerine fikstürden koş (JSON fikstür dizini)",
    )
    report.add_argument("--source", default="file", choices=["file"])
    report.add_argument("--term-start", type=int)
    report.add_argument("--budget-ms", type=int, default=DEFAULT_BUDGET_MS)
    _add_db_flags(report)
    report.set_defaults(func=_cmd_report, is_async=True)

    rules = sub.add_parser("rules", help="kural kataloğunu bas")
    rules.set_defaults(func=_cmd_rules, is_async=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if getattr(args, "is_async", False):
        return asyncio.run(args.func(args))
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
