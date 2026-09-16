#!/usr/bin/env python3
"""Tohum verisinde BILISSEL DESENIN gercekten olustugunu olcer.

Neden bu betik var: tohum yeniden uretilirken uc zincir kuruldu —
  A) soru metni  <- bilissel etiketler
  B) madde zorlugu <- bilissel talep
  C) ogrenci yetenegi <- boyut bazinda sapma
Bu zincirlerin CIKTIDA gorunur olup olmadigi varsayimla degil, uretilen
`.surql` dosyalari uzerinden olculur. Altin etiketler `_seed_manifest.json`
icindedir (DB'ye yazilmaz).

Bes olcum:
  1. bilissel_talep x ampirik p-degeri
  2. dikkat tuzagi olan maddelerde tuzak sikkin cekiciligi
  3. okuma yuku x ampirik p-degeri
  4. arketip x boyut kesisim tablosu (boyut sapmasi olan arketipler)
  5. kontrol: sapmasi olmayan arketiplerde fark ~0

Kullanim:
    python tools/measure_pattern.py [--seed-dir seed] [--json cikti.json]
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import re
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Bir maddenin p-degerinin anlamli sayilmasi icin en az bu kadar gozlem.
MIN_RESPONSES = 30

_ID = re.compile(r"(\w+):⟨([^⟩]+)⟩")


def _field(line: str, name: str) -> str | None:
    """Satir icindeki `name: deger` alanini ham metin olarak dondurur."""
    i = line.find(" %s: " % name)
    if i < 0:
        return None
    i += len(name) + 3
    if line[i] == "'":
        j = line.find("'", i + 1)
        return line[i + 1:j]
    j = i
    while j < len(line) and line[j] not in ",}":
        j += 1
    return line[i:j].strip()


def _rid(raw: str | None) -> str | None:
    if not raw:
        return None
    m = _ID.match(raw)
    return "%s:%s" % (m.group(1), m.group(2)) if m else None


# ---------------------------------------------------------------------------
# Istatistik yardimcilari (ek bagimlilik yok)
# ---------------------------------------------------------------------------

def _norm_sf(z: float) -> float:
    """Standart normal ust kuyruk olasiligi."""
    return 0.5 * math.erfc(abs(z) / math.sqrt(2.0))


def welch(a: list[float], b: list[float]) -> dict:
    """Iki bagimsiz orneklem icin Welch t sinamasi + Cohen d."""
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return {"n_a": na, "n_b": nb, "t": None, "p": None, "d": None}
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    va, vb = statistics.variance(a), statistics.variance(b)
    se = math.sqrt(va / na + vb / nb)
    t = (ma - mb) / se if se else 0.0
    pooled = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))
    return {
        "n_a": na, "n_b": nb,
        "ort_a": round(ma, 4), "ort_b": round(mb, 4),
        "fark": round(ma - mb, 4),
        "t": round(t, 3),
        "p": _fmt_p(2.0 * _norm_sf(t)),
        "d": round((ma - mb) / pooled, 3) if pooled else None,
    }


def two_prop(k1: int, n1: int, k2: int, n2: int) -> dict:
    """Iki oran farki icin z sinamasi (arketip x boyut kesisimi)."""
    if n1 == 0 or n2 == 0:
        return {"oran_1": None, "oran_2": None, "fark": None, "z": None, "p": None}
    p1, p2 = k1 / n1, k2 / n2
    pool = (k1 + k2) / (n1 + n2)
    se = math.sqrt(pool * (1 - pool) * (1 / n1 + 1 / n2))
    z = (p1 - p2) / se if se else 0.0
    return {"oran_1": round(p1, 4), "oran_2": round(p2, 4),
            "fark": round(p1 - p2, 4), "n_1": n1, "n_2": n2,
            "z": round(z, 2), "p": _fmt_p(2.0 * _norm_sf(z))}


def _fmt_p(p: float) -> float | str:
    return "<1e-12" if p < 1e-12 else round(p, 6)


# ---------------------------------------------------------------------------
# Veri okuma
# ---------------------------------------------------------------------------

def load(seed_dir: pathlib.Path) -> dict:
    man = json.loads((seed_dir / "_seed_manifest.json").read_text(encoding="utf-8"))
    items = {i["question"]: i for i in man["items"]}
    students = {s["user"]: s for s in man["students"]}

    # exam_question: emit edilen GERCEK cevap anahtari (K8 duzenlemeleri dahil)
    correct: dict[str, str] = {}
    for line in (seed_dir / "09_sorular.surql").open(encoding="utf-8"):
        if not line.startswith("{ id: exam_question:"):
            continue
        qid = _rid(_field(line, "id"))
        key = _field(line, "correct")
        if qid and key and key != "NONE":
            correct[qid] = key

    # exam_answer: madde basina secim dagilimi + ogrenci x boyut dogrulugu
    per_item: dict[str, dict] = {}
    per_student: dict[str, dict] = {}
    for line in (seed_dir / "11_exam_answer.surql").open(encoding="utf-8"):
        if not line.startswith("{ id: exam_answer:"):
            continue
        sel = _field(line, "selected")
        if not sel or sel == "NONE":
            continue
        qid = _rid(_field(line, "question"))
        uid = _rid(_field(line, "user"))
        if qid not in correct:
            continue
        row = per_item.setdefault(qid, {"n": 0, "sec": {}})
        row["n"] += 1
        row["sec"][sel] = row["sec"].get(sel, 0) + 1
        dims = (items.get(qid) or {}).get("dims")
        if not dims or uid is None:
            continue
        ok = 1 if sel == correct[qid] else 0
        st = per_student.setdefault(uid, {})
        for dim, label in dims.items():
            cell = st.setdefault((dim, label), [0, 0])
            cell[0] += 1
            cell[1] += ok
    return {"items": items, "students": students, "correct": correct,
            "per_item": per_item, "per_student": per_student}


def item_rows(data: dict) -> list[dict]:
    """Gozlem sayisi esigini gecen maddeler: p-degeri, etiketler, tuzak payi."""
    out = []
    for qid, row in data["per_item"].items():
        if row["n"] < MIN_RESPONSES:
            continue
        gold = data["items"].get(qid)
        if not gold or not gold.get("dims"):
            continue
        key = data["correct"][qid]
        n = row["n"]
        n_ok = row["sec"].get(key, 0)
        dist = {c: k for c, k in row["sec"].items() if c != key}
        trap = gold.get("trap_choice")
        out.append({
            "question": qid,
            "dims": gold["dims"],
            "n": n,
            "p": n_ok / n,
            "tuzak_pay": (row["sec"].get(trap, 0) / n) if trap else None,
            "en_cekici_celdirici_pay": (max(dist.values()) / n) if dist else 0.0,
        })
    return out


# ---------------------------------------------------------------------------
# Bes olcum
# ---------------------------------------------------------------------------

def measure(data: dict) -> dict:
    rows = item_rows(data)
    by = lambda dim, label: [r["p"] for r in rows if r["dims"][dim] == label]  # noqa: E731

    # 1) bilissel talep x p
    lv = {l: by("bilissel_talep", l) for l in ("hatirlama", "uygulama", "analiz")}
    m1 = {
        "madde_sayisi": {l: len(v) for l, v in lv.items()},
        "ortalama_p": {l: round(statistics.fmean(v), 4) for l, v in lv.items() if v},
        "analiz_vs_hatirlama": welch(lv["analiz"], lv["hatirlama"]),
        "analiz_vs_uygulama": welch(lv["analiz"], lv["uygulama"]),
        "uygulama_vs_hatirlama": welch(lv["uygulama"], lv["hatirlama"]),
    }

    # 2) dikkat tuzagi: tuzak sikkin cekiciligi
    trap_rows = [r for r in rows if r["dims"]["dikkat_tuzagi"] == "var"
                 and r["tuzak_pay"] is not None]
    plain_rows = [r for r in rows if r["dims"]["dikkat_tuzagi"] == "yok"]
    trap_share = [r["tuzak_pay"] for r in trap_rows]
    plain_best = [r["en_cekici_celdirici_pay"] for r in plain_rows]
    m2 = {
        "tuzakli_madde": len(trap_rows),
        "tuzaksiz_madde": len(plain_rows),
        "tuzak_sik_ortalama_pay": round(statistics.fmean(trap_share), 4) if trap_share else None,
        "tuzaksizda_en_cekici_celdirici_ortalama_pay":
            round(statistics.fmean(plain_best), 4) if plain_best else None,
        "karsilastirma": welch(trap_share, plain_best),
        "tuzak_sik_en_cekici_oldugu_madde_pct": round(100.0 * sum(
            1 for r in trap_rows
            if r["tuzak_pay"] >= r["en_cekici_celdirici_pay"]) / max(1, len(trap_rows)), 2),
    }

    # 3) okuma yuku x p
    ry = {l: by("okuma_yuku", l) for l in ("dusuk", "yuksek")}
    m3 = {
        "madde_sayisi": {l: len(v) for l, v in ry.items()},
        "ortalama_p": {l: round(statistics.fmean(v), 4) for l, v in ry.items() if v},
        "yuksek_vs_dusuk": welch(ry["yuksek"], ry["dusuk"]),
    }
    # bonus: adim sayisi
    ad = {l: by("adim_sayisi", l) for l in ("tek_adim", "cok_adim")}
    m3["adim_sayisi_ortalama_p"] = {l: round(statistics.fmean(v), 4)
                                    for l, v in ad.items() if v}
    m3["cok_adim_vs_tek_adim"] = welch(ad["cok_adim"], ad["tek_adim"])

    # 4/5) arketip x boyut
    per_arch: dict[str, dict] = {}
    for uid, cells in data["per_student"].items():
        arch = (data["students"].get(uid) or {}).get("archetype")
        if not arch:
            continue
        tgt = per_arch.setdefault(arch, {})
        for key, (n, k) in cells.items():
            cell = tgt.setdefault(key, [0, 0])
            cell[0] += n
            cell[1] += k

    contrasts = [
        ("bilissel_talep", "hatirlama", "analiz"),
        ("dikkat_tuzagi", "var", "yok"),
        ("okuma_yuku", "yuksek", "dusuk"),
    ]
    table = {}
    for arch in sorted(per_arch):
        cells = per_arch[arch]
        rowd = {"profil": "sapma yok (kontrol)"}
        prof = ARCH_PROFILE.get(arch)
        if prof:
            rowd["profil"] = prof
        for dim, a, b in contrasts:
            na, ka = cells.get((dim, a), [0, 0])
            nb, kb = cells.get((dim, b), [0, 0])
            rowd["%s: %s - %s" % (dim, a, b)] = two_prop(ka, na, kb, nb)
        table[arch] = rowd

    kontrol = [a for a in table if a in CONTROL_ARCHETYPES]
    sapmali = [a for a in table if a not in CONTROL_ARCHETYPES]
    # Ham kontrast MADDE zorlugunu da tasir (analiz maddesi herkes icin zordur).
    # Ogrenci tarafindaki sapmayi yalitmak icin her arketipin kontrasti,
    # KONTROL GRUBUNUN ortalama kontrastindan cikarilir (fark-farklari).
    ozet = {}
    for dim, a, b in contrasts:
        key = "%s: %s - %s" % (dim, a, b)
        ks = [table[x][key]["fark"] for x in kontrol if table[x][key]["fark"] is not None]
        base = statistics.fmean(ks) if ks else None
        ozet[key] = {
            "kontrol_ortalama_fark": round(base, 4) if base is not None else None,
            "kontrol_azami_mutlak_sapma": round(
                max(abs(v - base) for v in ks), 4) if ks else None,
        }
        if base is None:
            continue
        for arch in table:
            cell = table[arch][key]
            if cell["fark"] is not None:
                cell["kontrole_gore_sapma"] = round(cell["fark"] - base, 4)

    return {
        "olcum_1_bilissel_talep_p": m1,
        "olcum_2_dikkat_tuzagi": m2,
        "olcum_3_okuma_yuku_p": m3,
        "olcum_4_arketip_boyut": {"tablo": table, "sapmali": sapmali},
        "olcum_5_kontrol": {"kontrol_arketipler": kontrol, "ozet": ozet},
        "kapsam": {"madde_esigi": MIN_RESPONSES, "olculen_madde": len(rows),
                   "toplam_madde": len(data["per_item"])},
    }


ARCH_PROFILE = {
    "A4": "aceleci: analizde guclu, dikkat tuzagina yakalanan",
    "A7": "okuma guclugu: yuksek okuma yukunde dusen",
    "A8": "ezberci: hatirlamada guclu, analizde zayif",
}
CONTROL_ARCHETYPES = {"A1", "A2", "A3", "A5", "A6"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-dir", default=str(ROOT / "seed"))
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)

    data = load(pathlib.Path(args.seed_dir))
    out = measure(data)
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if args.json:
        pathlib.Path(args.json).write_text(text, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
