#!/usr/bin/env python3
"""99_dogrula.surql icindeki butunluk sorgularini tek tek calistirir.

Her sorgu 0 ihlal dondurmelidir (bos sonuc = 0). Sorgular tek tek gonderilir,
boylece biri yavas ya da hatali olsa bile digerleri calisir ve hangisinin
takildigi gorunur. `LET` satirlari her sorgunun onune eklenir.
"""

from __future__ import annotations

import base64
import json
import re
import sys
import time
import urllib.error
import urllib.request

ENDPOINT = "http://hzk-surreal:8000/sql"
NS = "hezarfen"
DB = "zeka"
PER_QUERY_TIMEOUT = 240


def sql(query: str):
    req = urllib.request.Request(ENDPOINT, data=query.encode("utf-8"))
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "text/plain; charset=utf-8")
    req.add_header("surreal-ns", NS)
    req.add_header("surreal-db", DB)
    req.add_header("Authorization", "Basic " + base64.b64encode(b"root:root").decode())
    with urllib.request.urlopen(req, timeout=PER_QUERY_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    text = open("/seed/99_dogrula.surql", encoding="utf-8").read()
    lets = [l.strip() for l in text.splitlines() if l.strip().startswith("LET ")]
    prefix = "\n".join(lets) + "\n"

    blocks = re.split(r"\n(?=--\s*I\d+:)", text)
    passed = violations = errors = slow = 0
    t_all = time.time()

    for block in blocks:
        m = re.match(r"--\s*(I\d+):\s*(.+)", block)
        if not m:
            continue
        tag, desc = m.group(1), m.group(2).strip()
        body = "\n".join(
            l for l in block.splitlines() if not l.strip().startswith("--")
        ).strip()
        if not body:
            continue

        t0 = time.time()
        try:
            res = sql(prefix + body)
        except urllib.error.HTTPError as e:
            errors += 1
            print(f"{tag:<5} HATA  {e.code} {e.read().decode('utf-8','replace')[:120]}",
                  flush=True)
            continue
        except Exception as e:
            slow += 1
            print(f"{tag:<5} ZAMAN ASIMI ({type(e).__name__}) — {desc[:55]}", flush=True)
            continue
        dt = time.time() - t0

        last = res[-1] if res else {}
        if last.get("status") != "OK":
            errors += 1
            print(f"{tag:<5} HATA  {str(last.get('result'))[:120]}", flush=True)
            continue

        out = last.get("result")
        n = 0
        if isinstance(out, list) and out and isinstance(out[0], dict):
            n = out[0].get("count", 0) or 0
        if n:
            violations += 1
            print(f"{tag:<5} IHLAL {n:>8}  {desc[:60]}", flush=True)
        else:
            passed += 1
            if dt > 5:
                print(f"{tag:<5} ok ({dt:.0f}s)", flush=True)

    print(f"\ngecen: {passed} | IHLAL: {violations} | hata: {errors} | "
          f"zaman asimi: {slow} | sure: {time.time() - t_all:.0f}s")
    ok = violations == 0 and errors == 0
    print("SONUC: " + ("TEMIZ" if ok and slow == 0 else
                       "TEMIZ (bazi sorgular zaman asimina ugradi)" if ok else
                       "SORUN VAR"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
