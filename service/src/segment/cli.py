"""Segmentasyon alt sisteminin komut satiri arayuzu.

Mevcut `service/src/cli.py` DOKUNULMAMISTIR; bu ayri bir giris noktasidir:

    python -m src.segment.cli rubric
    python -m src.segment.cli stability --mock --n 120
    python -m src.segment.cli run --mock --negatives 300
    python -m src.segment.cli run --mock --students --max-answers 60000
    python -m src.segment.cli cache --clear
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import prompts
from .cache import ResponseCache
from .config import SegmentConfig, SegmentConfigError, set_log_level
from .rubric import DIMENSION_ORDER, render_full_rubric
from .runner import MULTI_AGENT_VARIANTS, SegmentRunner, load_items, stratified_subset
from .validate import build_gold_set, load_misconception_pairs, write_report

REPO_ROOT = Path(__file__).resolve().parents[3]


def _cfg(args) -> SegmentConfig:
    cfg = SegmentConfig.from_env(root=REPO_ROOT)
    if args.budget is not None:
        cfg.budget_usd = args.budget
    if getattr(args, "seed", None) is not None:
        cfg.seed = args.seed
    if getattr(args, "no_cache", False):
        cfg.cache_enabled = False
    cfg.validate()
    return cfg


def cmd_rubric(args) -> int:
    print(render_full_rubric(args.course))
    print()
    print("CIKTI SEMASI")
    from .schema import response_template
    print(response_template())
    return 0


def cmd_prompts(args) -> int:
    for name, pv in sorted(prompts.ALL_VERSIONS.items()):
        tag = f" (parafraz: {pv.paraphrase_of})" if pv.paraphrase_of else ""
        print(f"{name}{tag} — {pv.note}")
    return 0


def cmd_gold(args) -> int:
    cfg = _cfg(args)
    items = load_items(cfg.items_path)
    pairs = load_misconception_pairs(REPO_ROOT / "generator" / "content_tr.py")
    gold = build_gold_set(items, pairs=pairs, n_negative=args.negatives,
                          seed=cfg.seed)
    print(json.dumps({"toplam_madde": len(items), **gold.to_dict(),
                      "konu_cifti_sayisi": len(pairs)},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_stability(args) -> int:
    cfg = _cfg(args)
    if args.n:
        cfg.stability_n = args.n
    runner = SegmentRunner(cfg, mock=args.mock)
    items = load_items(cfg.items_path)
    intra, inter = runner.stage0_stability(items)
    ok = runner.gate_stage0(intra, inter)
    print(json.dumps({"intra": intra.to_dict(), "inter": inter.to_dict(),
                      "kapi_gecti": ok, "butce": runner.budget.snapshot()},
                     ensure_ascii=False, indent=2))
    return 0 if ok else 3


def _store_for(args):
    """`--persist` için KÖPRÜ deposu.

    ZEKA'nın kendi veritabanı YOKTUR (değişmez kural: bir AI servisi
    uygulama veritabanına asla doğrudan erişmez): etiketler ve profiller
    `insight.*` yetenek çağrılarıyla backend'e yazılır. Bu yüzden burada
    bir DSN bayrağı yoktur; köprü ayarları ortamdan gelir.

    `--persist` verilmezse `None` döner: dönüşüm yapılır, satırlar SAYILIR,
    ama hiçbir şey yazılmaz. "Yazdım" demeden önce gerçekten yazabildiğini
    bilmek gerekir; sessizce boş bir depoya yazmak bunun tersidir.
    """
    if not args.persist:
        return None
    if not args.school:
        raise SystemExit("--persist için --school zorunlu (satırların yazılacağı okul)")
    from .. import bridge
    from ..config import Config, ConfigError
    from ..store import BridgeStore

    try:
        settings = Config(require_token=True)
    except ConfigError as exc:
        raise SystemExit(f"--persist için köprü ayarı eksik: {exc}") from exc
    return BridgeStore(
        bridge.OneShotCaller(settings), timeout_secs=settings.api_timeout_secs
    )


def cmd_run(args) -> int:
    cfg = _cfg(args)
    if args.stability_n:
        cfg.stability_n = args.stability_n
    runner = SegmentRunner(cfg, mock=args.mock)
    res = runner.run(n_items=args.n, negatives=args.negatives,
                     variants=tuple(args.variants or MULTI_AGENT_VARIANTS),
                     skip_stage0=args.skip_stage0, students=args.students,
                     max_answers=args.max_answers,
                     persist=args.persist, store=_store_for(args),
                     school=args.school)
    payload = res.to_dict()
    out = cfg.out_dir / "segment_run.json"
    write_report(out, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\n[segment] rapor: {out}", file=sys.stderr)
    return 0 if res.stopped_at is None else 3


def cmd_cache(args) -> int:
    cfg = _cfg(args)
    cache = ResponseCache(cfg.cache_dir, enabled=True)
    if args.clear:
        n = cache.clear()
        print(f"silinen onbellek dosyasi: {n}")
    else:
        n = sum(1 for _ in cfg.cache_dir.rglob("*.json")) if cfg.cache_dir.exists() else 0
        print(f"onbellek dizini: {cfg.cache_dir}\ngirdi sayisi: {n}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="segment",
        description="LLM tabanli soru segmentasyonu (hezarfen-ZEKA)")
    p.add_argument("--log-level", default="info")
    p.add_argument("--budget", type=float, default=None,
                   help="USD tavani (asilirsa kosu durur)")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--no-cache", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("rubric", help="boyutlari ve yonergeyi yazdir")
    s.add_argument("--course", default=None)
    s.set_defaults(func=cmd_rubric)

    s = sub.add_parser("prompts", help="istem surumlerini listele")
    s.set_defaults(func=cmd_prompts)

    s = sub.add_parser("gold", help="altin kume sayilarini goster")
    s.add_argument("--negatives", type=int, default=None)
    s.set_defaults(func=cmd_gold)

    s = sub.add_parser("stability", help="Asama 0: intra/inter-PSS + kapi")
    s.add_argument("--mock", action="store_true")
    s.add_argument("--n", type=int, default=None, help="alt kume buyuklugu")
    s.set_defaults(func=cmd_stability)

    s = sub.add_parser("run", help="tam akis (Asama 0-4)")
    s.add_argument("--mock", action="store_true")
    s.add_argument("--n", type=int, default=None, help="degerlendirilecek madde")
    s.add_argument("--negatives", type=int, default=400)
    s.add_argument("--stability-n", type=int, default=None)
    s.add_argument("--variants", nargs="*", default=None)
    s.add_argument("--skip-stage0", action="store_true",
                   help="UYARI: bulgu 5/6 ihlali, yalnizca hata ayiklama icin")
    s.add_argument("--students", action="store_true", help="Asama 4'u de kos")
    s.add_argument("--max-answers", type=int, default=None)
    # --- Asama 5: depoya yazim. VARSAYILAN KAPALI. --------------------------
    s.add_argument("--persist", action="store_true",
                   help="etiketleri ve ogrenci profillerini KOPRUDEN yaz: "
                        "--school ve AI_SHARED_TOKEN yoksa kuru kosu")
    s.add_argument("--school", default=None,
                   help="okul slug'i; verilmezse tohum manifestosundan okunur")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("cache", help="onbellek durumu / temizleme")
    s.add_argument("--clear", action="store_true")
    s.set_defaults(func=cmd_cache)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        set_log_level(args.log_level)
        return args.func(args)
    except SegmentConfigError as exc:
        print(f"[segment] yapilandirma hatasi: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
