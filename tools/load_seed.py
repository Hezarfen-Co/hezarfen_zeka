#!/usr/bin/env python3
"""Tohum verisini SurrealDB'ye yükler.

Neden bu betik var: `surreal sql` aracı standart girdiden gelen büyük dosyaları
ortadan kesiyor ("Unexpected end of file"), bu yüzden dosyanın yalnızca bir kısmı
yükleniyor ve gerisi sessizce kayboluyor. Bu betik dosyaları ifade sınırlarında
parçalayıp HTTP /sql ucuna gönderir ve her parçanın sonucunu ayrı ayrı raporlar.

Ayrıştırma dize-farkındadır: tek ve çift tırnaklı dizelerin içindeki noktalı virgül
ifade sonu sayılmaz.

Kullanım:
    python load_seed.py --endpoint http://hzk-surreal:8000 --db zeka --seed-dir /seed
"""

from __future__ import annotations

import argparse
import base64
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

# Bir istekte gönderilecek azami bayt. Araç sınırının çok altında tutuldu.
CHUNK_BYTES = 512 * 1024


def split_statements(text: str) -> list[str]:
    """Metni ifadelere böler. Dize içindeki noktalı virgülü yok sayar."""
    out: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if quote:
            buf.append(c)
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
            buf.append(c)
        elif c == "-" and text.startswith("--", i):
            # yorum: satır sonuna kadar at
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        elif c == ";":
            buf.append(c)
            stmt = "".join(buf).strip()
            if stmt and stmt != ";":
                out.append(stmt)
            buf = []
        else:
            buf.append(c)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def chunks(statements: list[str], limit: int = CHUNK_BYTES):
    """İfadeleri, hiçbirini bölmeden, bayt sınırına göre gruplar."""
    cur: list[str] = []
    size = 0
    for s in statements:
        b = len(s.encode("utf-8")) + 1
        if cur and size + b > limit:
            yield cur
            cur, size = [], 0
        cur.append(s)
        size += b
    if cur:
        yield cur


def post(endpoint: str, ns: str, db: str, user: str, pw: str, sql: str) -> list:
    req = urllib.request.Request(endpoint.rstrip("/") + "/sql", data=sql.encode("utf-8"))
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "text/plain; charset=utf-8")
    req.add_header("surreal-ns", ns)
    req.add_header("surreal-db", db)
    token = base64.b64encode(f"{user}:{pw}".encode()).decode()
    req.add_header("Authorization", "Basic " + token)
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode("utf-8"))


def load_file(path: pathlib.Path, args, db: str) -> tuple[int, int, list[str]]:
    text = path.read_text(encoding="utf-8")
    statements = split_statements(text)
    ok = 0
    errs: list[str] = []
    for group in chunks(statements):
        sql = "\n".join(group)
        try:
            results = post(args.endpoint, args.ns, db, args.user, args.password, sql)
        except urllib.error.HTTPError as e:
            errs.append(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}")
            continue
        except Exception as e:  # ağ / zaman aşımı
            errs.append(f"{type(e).__name__}: {e}")
            continue
        for r in results:
            if r.get("status") == "OK":
                ok += 1
            else:
                errs.append(str(r.get("result"))[:200])
    return len(statements), ok, errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="http://hzk-surreal:8000")
    ap.add_argument("--ns", default="hezarfen")
    ap.add_argument("--db", default="zeka", help="okul veritabanı adı")
    ap.add_argument("--control-db", default="control")
    ap.add_argument("--user", default="root")
    ap.add_argument("--password", default="root")
    ap.add_argument("--seed-dir", default="/seed")
    ap.add_argument("--only", default=None, help="yalnız bu dosya adı")
    args = ap.parse_args()

    seed = pathlib.Path(args.seed_dir)
    files = sorted(p for p in seed.glob("*.surql") if not p.name.startswith("99_"))
    if args.only:
        files = [p for p in files if p.name == args.only]

    total_ok = total_st = 0
    failed: list[str] = []
    t_all = time.time()

    for p in files:
        # 00_* kontrol veritabanına, gerisi okul veritabanına gider.
        db = args.control_db if p.name.startswith("00_") else args.db
        t0 = time.time()
        st, ok, errs = load_file(p, args, db)
        dt = time.time() - t0
        total_ok += ok
        total_st += st
        flag = "TAMAM" if not errs else f"HATA({len(errs)})"
        print(f"{p.name:<28} {st:>6} ifade  {ok:>6} ok  {dt:>6.1f}s  {flag}", flush=True)
        for e in errs[:3]:
            print(f"    ! {e}", flush=True)
        if errs:
            failed.append(p.name)

    print(f"\nTOPLAM: {total_st} ifade, {total_ok} basarili, "
          f"{time.time() - t_all:.1f} saniye")
    if failed:
        print("HATALI DOSYALAR: " + ", ".join(failed))
        return 1
    print("TUM DOSYALAR HATASIZ YUKLENDI")
    return 0


if __name__ == "__main__":
    sys.exit(main())
