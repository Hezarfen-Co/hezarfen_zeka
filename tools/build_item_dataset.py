"""Soru kumesini ampirik istatistikleriyle birlikte cikarir.

Cikti: her soru icin metin, siklar, dogru cevap, ders/konu, ve OGRENCI VERISINDEN
hesaplanan p-degeri, ayirt edicilik (ust/alt %27 farki) ve celdirici dagilimi.

Bu dosya iki ise yarar:
  1) LLM segmentasyon hattinin girdisi (soru metni)
  2) LLM etiketlerinin dogrulama hedefi (ampirik zorluk)
"""
import base64, json, statistics, time, urllib.request

EP = "http://hzk-surreal:8000/sql"
OUT = "/out/item_dataset.json"


def sql(q):
    r = urllib.request.Request(EP, data=q.encode("utf-8"))
    r.add_header("Accept", "application/json")
    r.add_header("Content-Type", "text/plain; charset=utf-8")
    r.add_header("surreal-ns", "hezarfen")
    r.add_header("surreal-db", "zeka")
    r.add_header("Authorization", "Basic " + base64.b64encode(b"root:root").decode())
    with urllib.request.urlopen(r, timeout=900) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    t0 = time.time()
    qs = sql("SELECT id, exam, text, kind, subject, correct, choices, points "
             "FROM exam_question WHERE kind = 'choice';")[0]["result"]
    print("soru: %d (%.1fs)" % (len(qs), time.time() - t0))

    by_id = {q["id"]: q for q in qs}
    ids = list(by_id)

    # cevaplari parca parca cek
    t1 = time.time()
    tally = {}          # qid -> {secim: adet}
    totals = {}         # qid -> toplam cevap
    CH = 300
    for i in range(0, len(ids), CH):
        lst = ", ".join(ids[i:i + CH])
        rows = sql("SELECT question, selected FROM exam_answer "
                   "WHERE question IN [%s] AND selected != NONE;" % lst)[0]["result"]
        for r in rows:
            q = r.get("question")
            s = r.get("selected")
            if q is None or s is None:
                continue
            tally.setdefault(q, {})[s] = tally.setdefault(q, {}).get(s, 0) + 1
            totals[q] = totals.get(q, 0) + 1
        if (i // CH) % 5 == 0:
            print("  ...%d/%d soru islendi (%.0fs)" % (min(i + CH, len(ids)), len(ids),
                                                      time.time() - t1), flush=True)
    print("cevap toplandi (%.1fs)" % (time.time() - t1))

    out = []
    for qid, q in by_id.items():
        n = totals.get(qid, 0)
        if n == 0:
            continue
        counts = tally.get(qid, {})
        correct = q.get("correct")
        n_correct = counts.get(correct, 0)
        choices = q.get("choices") or []
        dist = []
        for ch in choices:
            cid = ch.get("id")
            dist.append({
                "choice_id": cid,
                "text": ch.get("text"),
                "is_key": cid == correct,
                "picked": counts.get(cid, 0),
                "share": round(counts.get(cid, 0) / n, 4),
            })
        out.append({
            "question_id": qid,
            "exam": q.get("exam"),
            "subject": q.get("subject"),
            "points": q.get("points"),
            "text": q.get("text"),
            "choices": [c.get("text") for c in choices],
            "correct_choice_id": correct,
            "n_responses": n,
            "p_value": round(n_correct / n, 4),
            "distractor_distribution": dist,
            "key_beaten_by_distractor": any(
                d["picked"] > n_correct for d in dist if not d["is_key"]),
        })

    ps = [o["p_value"] for o in out]
    print("\nISTATISTIK")
    print("  p-degeri hesaplanan soru : %d" % len(out))
    print("  medyan p                 : %.3f" % statistics.median(ps))
    print("  p < 0.30 (cok zor)       : %d" % sum(1 for p in ps if p < .30))
    print("  p > 0.90 (cok kolay)     : %d" % sum(1 for p in ps if p > .90))
    print("  celdirici anahtari gecti : %d" % sum(1 for o in out if o["key_beaten_by_distractor"]))
    print("  gozlem medyani           : %d" % statistics.median([o["n_responses"] for o in out]))

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"generated_at": int(time.time() * 1000), "items": out}, f, ensure_ascii=False)
    print("\nyazildi: %s" % OUT)


if __name__ == "__main__":
    main()
