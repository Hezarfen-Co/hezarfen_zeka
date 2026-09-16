"""Ampirik madde zorlugunu (p-degeri) hesaplayabiliyor muyuz? Kucuk olcekli sinama."""
import base64, json, time, urllib.request

def sql(q, db="zeka"):
    r = urllib.request.Request("http://hzk-surreal:8000/sql", data=q.encode("utf-8"))
    r.add_header("Accept", "application/json")
    r.add_header("Content-Type", "text/plain; charset=utf-8")
    r.add_header("surreal-ns", "hezarfen"); r.add_header("surreal-db", db)
    r.add_header("Authorization", "Basic " + base64.b64encode(b"root:root").decode())
    with urllib.request.urlopen(r, timeout=600) as resp:
        return json.loads(resp.read().decode("utf-8"))

t0 = time.time()
qs = sql("SELECT id, correct, subject, text FROM exam_question WHERE kind = 'choice' LIMIT 400;")[0]["result"]
key = {q["id"]: q.get("correct") for q in qs}
ids = list(key)
print("soru cekildi: %d  (%.1fs)" % (len(ids), time.time() - t0))

t1 = time.time()
rows = []
CH = 100
for i in range(0, len(ids), CH):
    part = ids[i:i + CH]
    lst = ", ".join(part)
    res = sql("SELECT question, selected FROM exam_answer WHERE question IN [%s];" % lst)
    rows.extend(res[0]["result"])
print("cevap cekildi: %d  (%.1fs)" % (len(rows), time.time() - t1))

agg = {}
for r in rows:
    q = r.get("question")
    if q is None:
        continue
    n, c = agg.get(q, (0, 0))
    ok = 1 if r.get("selected") is not None and r.get("selected") == key.get(q) else 0
    agg[q] = (n + 1, c + ok)

ps = sorted((c / n) for n, c in agg.values() if n >= 10)
if ps:
    import statistics
    print("p-degeri hesaplanan soru: %d" % len(ps))
    print("  min %.2f | %%25 %.2f | medyan %.2f | %%75 %.2f | max %.2f"
          % (ps[0], ps[len(ps)//4], statistics.median(ps), ps[3*len(ps)//4], ps[-1]))
    print("  cok zor (p<0.30): %d | cok kolay (p>0.90): %d"
          % (sum(1 for p in ps if p < .30), sum(1 for p in ps if p > .90)))
    n_per = [n for n, _ in agg.values()]
    print("  soru basina gozlem: min %d medyan %d max %d"
          % (min(n_per), statistics.median(n_per), max(n_per)))
