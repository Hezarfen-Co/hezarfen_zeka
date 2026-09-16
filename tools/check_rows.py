import base64, json, sys, urllib.request
EP = "http://hzk-surreal:8000/sql"
def sql(q, db="zeka"):
    r = urllib.request.Request(EP, data=q.encode("utf-8"))
    r.add_header("Accept", "application/json"); r.add_header("Content-Type", "text/plain; charset=utf-8")
    r.add_header("surreal-ns", "hezarfen"); r.add_header("surreal-db", db)
    r.add_header("Authorization", "Basic " + base64.b64encode(b"root:root").decode())
    with urllib.request.urlopen(r, timeout=600) as resp:
        return json.loads(resp.read().decode("utf-8"))
man = json.load(open("/seed/MANIFEST.json", encoding="utf-8"))["tablo_satir_sayilari"]
q = "\n".join("SELECT count() FROM %s GROUP ALL;" % t for t in sorted(man))
res = sql(q)
bad = []
tot_db = tot_man = 0
for t, r in zip(sorted(man), res):
    got = 0
    if r.get("status") == "OK" and r.get("result"):
        got = r["result"][0].get("count", 0)
    exp = man[t]
    tot_db += got; tot_man += exp
    if got != exp:
        bad.append((t, exp, got))
print("tablo: %d | MANIFEST toplam: %d | DB toplam: %d" % (len(man), tot_man, tot_db))
if bad:
    print("UYUSMAYAN (%d):" % len(bad))
    for t, e, g in bad[:20]:
        print("  %-24s beklenen %7d  bulunan %7d" % (t, e, g))
else:
    print("TUM TABLOLAR BIREBIR UYUSUYOR")
