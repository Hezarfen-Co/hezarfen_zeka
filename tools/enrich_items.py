"""item_dataset.json'a ders/konu ADLARINI ve altin etiketleri ekler.

Girdi : /out/item_dataset.json  (ampirik istatistikli sorular)
        /seed/_seed_manifest.json (uretici altin etiketleri)
Cikti : /out/items_enriched.json

Altin etiketler NEDEN eklenir: soru metni bu etiketlerden URETILDI (zincir A)
ve madde zorlugu da ayni etiketlerden turedi (zincir B). Bu yuzden hem kavram
yanilgisi celdiricisi hem de dort boyut etiketi (`gold.dims`) LLM ciktisiyla
DOGRUDAN karsilastirilabilir; `difficulty_band` artik metinden bagimsiz degil,
etiketlerin sonucudur.
"""
import base64, json, urllib.request

def sql(q):
    r = urllib.request.Request("http://hzk-surreal:8000/sql", data=q.encode("utf-8"))
    r.add_header("Accept", "application/json")
    r.add_header("Content-Type", "text/plain; charset=utf-8")
    r.add_header("surreal-ns", "hezarfen"); r.add_header("surreal-db", "zeka")
    r.add_header("Authorization", "Basic " + base64.b64encode(b"root:root").decode())
    with urllib.request.urlopen(r, timeout=900) as resp:
        return json.loads(resp.read().decode("utf-8"))

subs = {s["id"]: s for s in sql("SELECT id, name, course FROM subject;")[0]["result"]}
crs = {c["id"]: c.get("name") for c in sql("SELECT id, name FROM course;")[0]["result"]}
print("konu: %d | ders: %d" % (len(subs), len(crs)))

man = json.load(open("/seed/_seed_manifest.json", encoding="utf-8"))
gold = {i["question"]: i for i in man["items"]}

d = json.load(open("/out/item_dataset.json", encoding="utf-8"))
out, miss = [], 0
for it in d["items"]:
    s = subs.get(it.get("subject"))
    g = gold.get(it["question_id"], {})
    if not s:
        miss += 1
    mc = g.get("misconception_choice")
    trap = g.get("trap_choice")
    # altin celdirici SIK KIMLIGI'dir; metnini dagilimdan cozeriz
    mc_text, mc_share, mc_is_key = None, None, None
    if isinstance(mc, str):
        for dd in it.get("distractor_distribution") or []:
            if dd.get("choice_id") == mc:
                mc_text = dd.get("text")
                mc_share = dd.get("share")
                mc_is_key = dd.get("is_key")
                break
    it2 = dict(it)
    it2["subject_name"] = (s or {}).get("name")
    it2["course_name"] = crs.get((s or {}).get("course"))
    it2["gold"] = {
        "misconception_choice_id": mc if isinstance(mc, str) else None,
        "misconception_choice_text": mc_text,
        "misconception_pick_share": mc_share,
        "misconception_is_key": mc_is_key,
        "difficulty_band": g.get("difficulty_band"),
        "quality_band": g.get("quality_band"),
        "irt_a": g.get("a"), "irt_b": g.get("b"),
        # ALTIN BOYUT ETIKETLERI: metin bu etiketlerden URETILDI, zorluk da
        # bunlardan turedi. Artik `difficulty_band` metinden BAGIMSIZ degil;
        # LLM etiketleri bu dort alanla dogrudan karsilastirilabilir.
        "dims": g.get("dims"),
        "trap_choice_id": trap if isinstance(trap, str) else None,
    }
    out.append(it2)

print("konu adi coazulemeyen: %d" % miss)
with open("/out/items_enriched.json", "w", encoding="utf-8") as f:
    json.dump({"items": out}, f, ensure_ascii=False)
print("yazildi: /out/items_enriched.json  (%d madde)" % len(out))
has_mc = sum(1 for o in out if o["gold"]["misconception_choice_text"])
print("altin celdirici metni cozulen: %d" % has_mc)
