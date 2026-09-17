"""Geliştirme aracı — köprüsüz hattı koşturur.

    python -m src.cli run --school X --fixtures ... --dry-run
    python -m src.cli run --school X --fixtures ... --out sonuc.json
    python -m src.cli rules
    python -m src.cli report --school X --type okul --format html --out DIZIN \
        --fixtures ...
    python -m src.cli sweep --school X
    python -m src.cli schedule --fixtures ...

---------------------------------------------------------------------------
BURADA HTTP SUNUCUSU YOKTUR VE OLMAYACAKTIR
---------------------------------------------------------------------------
Çelebi'nin geliştirme amaçlı HTTP sunucusu üretim imajında durdu ve denetimde
risk olarak işaretlendi. Aynı hatayı tekrarlamıyoruz: bu dosya bir CLI'dır,
bir servis değil. `serve` alt komutu **yoktur**; gece işi `scheduler.py`
tarafından süreç içinden tetiklenir.

---------------------------------------------------------------------------
VERİTABANI DA YOKTUR
---------------------------------------------------------------------------
ZEKA'nın kendi veritabanı yoktur (değişmez kural: bir AI servisi uygulama
veritabanına asla doğrudan erişmez). Bu yüzden burada `--db-url`, DSN ya da
şema yükleme bayrağı BULUNMAZ:

* `--dry-run` çağrıları **sayar** (`store.RecordingCaller`), hiçbir şey yazmaz.
* `sweep` ve `schedule` canlı bir köprü bağlantısı gerektirir ve onu kendileri
  kurar (`bridge.one_shot` → `BridgeProtocol.call_capability`). Okul listesi
  backend'den gelir (`insight.schools.list`).
* `report` yalnız fikstür yolundan üretir; canlı bir dağıtımı okumak
  backend'in `/insights` uçlarının işidir, bu aracın değil.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

from .compute import recommend as recommend_mod
from .compute.attention import unavailable_triggers
from .config import Config
from .pipeline import DEFAULT_BUDGET_MS, run_school
from .scheduler import Scheduler
from .store import (
    RETENTION_DAYS,
    BridgeStore,
    ProtocolCaller,
    RecordingCaller,
    SWEEP_TABLES,
)


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
    from .source import FileSource  # type: ignore[attr-defined]

    return FileSource(Path(fixtures))


async def _cmd_run(args: argparse.Namespace) -> int:
    """Hattı koştur.

    `--dry-run` verilirse çağrılar toplanır ve **hiç gönderilmez**; verilmezse
    depo gerçek köprüdür ve çağrılar backend'e gider. Yazmanın gerçekten
    yapıldığını bilmeden "yazdım" demek bu aracın kaçındığı şeydir.
    """
    source = _build_source(args.source, args.fixtures)
    now_ms = args.now or int(time.time() * 1000)
    students = args.students.split(",") if args.students else None
    settings = Config(require_token=False)

    if args.dry_run:
        caller = RecordingCaller()
        store = BridgeStore(caller)
        result = await run_school(
            source,
            store.store_for(args.school),
            args.school,
            now_ms=now_ms,
            student_ids=students,
            term_start_ms=args.term_start,
            budget_ms=args.budget_ms,
        )
        payload = {
            "run": dataclasses.asdict(result),
            "dry_run": True,
            "cagri_sayisi": len(caller.calls),
        }
        if args.verbose:
            payload["cagrilar"] = [
                {"yetenek": capability, "okul": school, "payload": body}
                for capability, school, body in caller.calls
            ]
    else:
        async def work(proto: Any) -> dict[str, Any]:
            store = BridgeStore(
                ProtocolCaller(proto, timeout_secs=settings.api_timeout_secs)
            )
            result = await run_school(
                source,
                store.store_for(args.school),
                args.school,
                now_ms=now_ms,
                student_ids=students,
                term_start_ms=args.term_start,
                budget_ms=args.budget_ms,
            )
            return dataclasses.asdict(result)

        from . import bridge

        run = await bridge.one_shot(settings, work)
        if run is None:
            raise SystemExit("köprü bağlanamadı; hiçbir şey yazılmadı")
        payload = {"run": run, "dry_run": False}

    payload["unavailable_triggers"] = unavailable_triggers()
    payload["unavailable_rules"] = recommend_mod.unavailable_rules()
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"yazıldı: {args.out}")
    else:
        print(text)
    status = payload["run"].get("status", "failed")
    return 0 if status in ("ok", "partial") else 1


# ---------------------------------------------------------------------------
# DEPOLAMA / ZAMANLAYICI KOMUTLARI — hepsi KÖPRÜDEN
# ---------------------------------------------------------------------------
# Bağlantı `bridge.one_shot` ile kurulur: bağlan, kaydol, işi koştur, kapat.
# Veritabanı bayrağı YOKTUR; okul backend'in kendi dizininden gelir.


async def _cmd_sweep(args: argparse.Namespace) -> int:
    """Saklama süresi süpürmesini koştur (backend'de, o okulun veritabanında).

    `--now` yalnız çıktı içindir: saati backend damgalar, iki saatli bir
    süpürme "hangi gün" sorusuna iki cevap verirdi.
    """
    settings = Config(require_token=True)

    async def work(proto: Any) -> dict[str, bool]:
        store = BridgeStore(
            ProtocolCaller(proto, timeout_secs=settings.api_timeout_secs)
        )
        return await store.store_for(args.school).sweep(args.now or int(time.time() * 1000))

    from . import bridge

    tables = await bridge.one_shot(settings, work)
    if tables is None:
        raise SystemExit("köprü bağlanamadı; süpürme koşmadı")
    print(
        json.dumps(
            {
                "okul": args.school,
                "saklama_gun": RETENTION_DAYS,
                "tablolar": tables,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if all(tables.get(table) for table in SWEEP_TABLES) else 1


async def _cmd_schedule(args: argparse.Namespace) -> int:
    """Zamanlayıcıyı elle tetikle — gece penceresini BEKLEMEDEN.

    Okul listesi **backend'den** gelir (`insight.schools.list`); `--schools`
    yalnızca bir FİLTREDİR: daraltır, üretmez. `--ticks` verilirse tam
    `serve()` döngüsü koşar (test kipi), verilmezse tek tur (`run_once`).
    İkisi de üretimdeki aynı kodu kullanır.
    """
    settings = Config(require_token=False)
    schools = [s.strip() for s in (args.schools or "").split(",") if s.strip()]
    budgets: dict[str, int] = {}
    for pair in (args.budget or "").split(","):
        if "=" in pair:
            name, value = pair.split("=", 1)
            budgets[name.strip()] = int(value)
    root = Path(args.fixtures)
    stamp = args.now or int(time.time() * 1000)

    async def work(proto: Any) -> dict[str, Any]:
        store = BridgeStore(
            ProtocolCaller(proto, timeout_secs=settings.api_timeout_secs)
        )
        scheduler = Scheduler(
            lambda _school: _build_source("file", str(root)),
            store,
            only=schools or None,
            budget_ms=args.budget_ms,
            budgets=budgets,
            term_start_ms=args.term_start,
            clock_fn=lambda: stamp,
        )
        if args.ticks:
            await scheduler.serve(
                tick_seconds=args.tick_seconds, ignore_window=True, max_ticks=args.ticks
            )
            results: list[Any] = []
        else:
            results = await scheduler.run_once(stamp)
        return {
            "kosulan_okullar": [r.school for r in results],
            "sonuclar": [dataclasses.asdict(r) for r in results],
            "dusen_okullar": scheduler.failures(),
        }

    from . import bridge

    payload = await bridge.one_shot(settings, work)
    if payload is None:
        raise SystemExit("köprü bağlanamadı; tur koşmadı")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


async def _cmd_report(args: argparse.Namespace) -> int:
    """Rapor üretir — hattı fikstürden koşturup yazılan satırları yakalayarak.

        python -m src.cli report --school X --type okul --format html --out DIZIN --fixtures ...

    Canlı bir dağıtımın satırlarını okumak bu aracın işi DEĞİLDİR: ZEKA
    veritabanı okumaz, o satırlar backend'in `/insights` uçlarından okunur.
    """
    from .report import load as load_mod
    from .report import writer as writer_mod
    from .report.build import build as build_report
    from .report.capture import CapturingCaller
    from .report.gate import REPORT_TYPES

    if args.type not in REPORT_TYPES:
        raise SystemExit(f"bilinmeyen rapor tipi: {args.type}")
    if not args.fixtures:
        raise SystemExit(
            "--fixtures zorunlu: rapor, hattın fikstürden koşup yakaladığı "
            "satırlardan üretilir (ZEKA veritabanı okumaz)."
        )

    now_ms = args.now or int(time.time() * 1000)
    source = _build_source(args.source, args.fixtures)
    caller = CapturingCaller()
    await run_school(
        source,
        BridgeStore(caller).store_for(args.school),
        args.school,
        now_ms=now_ms,
        term_start_ms=args.term_start,
        budget_ms=args.budget_ms,
    )
    reader = caller.as_reader()

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
        description="ZEKA geliştirme aracı — köprü/veritabanı bağlamadan hat koşturucu.",
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
        help="köprüye hiçbir şey gönderme; çağrıları say ve sonucu bas",
    )
    run.set_defaults(func=_cmd_run, is_async=True)

    sweep = sub.add_parser("sweep", help="saklama süresi süpürmesini koştur (köprüden)")
    sweep.add_argument("--school", required=True, help="okul slug'ı")
    sweep.add_argument("--now", type=int, help="unix ms; yalnız çıktı içindir")
    sweep.set_defaults(func=_cmd_sweep, is_async=True)

    schedule = sub.add_parser(
        "schedule", help="zamanlayıcıyı elle tetikle (gece penceresini beklemeden)"
    )
    schedule.add_argument(
        "--schools",
        help="virgülle ayrılmış slug listesi — backend'in verdiği listenin "
        "FİLTRESİ. Verilmezse bütün aktif okullar koşar.",
    )
    schedule.add_argument("--fixtures", required=True)
    schedule.add_argument("--now", type=int)
    schedule.add_argument("--term-start", type=int)
    schedule.add_argument("--budget-ms", type=int, default=DEFAULT_BUDGET_MS)
    schedule.add_argument(
        "--budget", help="okul başına bütçe: 'okul-a=1000,okul-b=60000'"
    )
    schedule.add_argument("--ticks", type=int, help="test kipi: kaç tik atılsın")
    schedule.add_argument("--tick-seconds", type=float, default=0.01)
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
        "--fixtures", required=True, help="JSON fikstür dizini (rapor bu yoldan üretilir)"
    )
    report.add_argument("--source", default="file", choices=["file"])
    report.add_argument("--term-start", type=int)
    report.add_argument("--budget-ms", type=int, default=DEFAULT_BUDGET_MS)
    report.set_defaults(func=_cmd_report, is_async=True)

    rules = sub.add_parser("rules", help="kural kataloğunu bas")
    rules.set_defaults(func=_cmd_rules, is_async=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    if getattr(args, "is_async", False):
        return asyncio.run(args.func(args))
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
