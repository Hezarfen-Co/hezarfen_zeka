"""Segment tabanli tavsiye kurallarinin olcumu.

NE OLCULUYOR (ve ne OLCULMUYOR)
-------------------------------
Varsayilan kipte etiketler tohum manifestosundaki **ALTIN** etiketlerdir
(`work/items_enriched.json` -> `gold.dims`). Yani bu betik sunu olcer:

    "Kurallar, etiketler DOGRUYKEN, tasarlanmis arketipleri buluyor mu?"

Sunu OLCMEZ:

    "LLM soruyu dogru etiketliyor mu?"

Ikinci soru ayri bir olcumdur (`service/docs/DESEN-DOGRULAMA.md` ve
segmentasyon kosu raporu). `--noise` kipi, olculmus LLM isabet oranlarini
altin etiketlere uygulayarak kurallarin etiket gurultusune dayanikliligini
MODELLER; bu bir simulasyondur, gercek bir LLM kosusu DEGILDIR ve ciktida
oyle isaretlenir.

Veritabani GEREKMEZ, ag cagrisi YOKTUR, USD harcamaz.

Kosum:
    python tools/measure_segment_rules.py --json work/segment_kural.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "service"))

from src.compute import segments as seg  # noqa: E402
from src.compute.recommend import (  # noqa: E402
    STUDENT_SEGMENT_DIMENSIONS,
    for_class_segments,
    for_student_segments,
)
from src.segment.runner import load_answers  # noqa: E402

NOW_MS = 1_776_000_000_000

#: Altin pozitif esigi: tasarimda bu boyutta **en az** bu kadar logit dusus
#: olan ogrenci, o segmentte gercekten geridedir. 0,5 logit ~ orta buyuklukte
#: bir etki; `ARCHETYPE_DIM_DELTA` degerleri -0,93 ... -1,05 araligindadir,
#: yani uc arketip de bu esigin acik ara ustundedir.
GOLD_DELTA = -0.5
#: Belirsiz bolge: ne pozitif sayilir ne de yanlis pozitif. A4'un
#: `bilissel_talep=hatirlama` sapmasi (-0,29) buraya duser.
GREY_DELTA = -0.15

#: Olculmus LLM etiket isabetleri (bkz. gorev kunyesi / kosu raporu).
#: `--noise` kipi bunlari kullanir.
MEASURED_LABEL_ACCURACY = {
    "okuma_yuku": 0.983,
    "dikkat_tuzagi": 0.975,
    "bilissel_talep": 0.917,
}


# ---------------------------------------------------------------------------
# Veri
# ---------------------------------------------------------------------------


def load_gold_labels(path: Path) -> dict[str, dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data["items"] if isinstance(data, dict) else data
    out: dict[str, dict[str, str]] = {}
    for item in items:
        dims = (item.get("gold") or {}).get("dims") or {}
        if not dims:
            continue
        out[item["question_id"]] = {
            d: dims[d] for d in seg.PRODUCTION_DIMENSIONS if d in dims
        }
    return out


def load_keys(path: Path) -> dict[str, str | None]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data["items"] if isinstance(data, dict) else data
    return {i["question_id"]: i.get("correct_choice_id") for i in items}


def load_students(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {s["user"]: s for s in data.get("students", [])}


def perturb(
    labels: dict[str, dict[str, str]], seed: int
) -> dict[str, dict[str, str]]:
    """Altin etiketlere OLCULMUS LLM hata oranlarini uygular (MODELLEME).

    `bilissel_talep` hatalari olculdugu gibi **sistematik olarak yukari**
    (analiz yonunde) verilir; digerlerinde hata rastgele bir baska etikete
    gider. Bu bir simulasyondur: gercek LLM hatalari bagimsiz ve esit dagilmis
    OLMAYABILIR.
    """
    rng = random.Random(seed)
    order = ("hatirlama", "uygulama", "analiz")
    out: dict[str, dict[str, str]] = {}
    for question, row in labels.items():
        new: dict[str, str] = {}
        for dimension, label in row.items():
            accuracy = MEASURED_LABEL_ACCURACY.get(dimension, 1.0)
            if rng.random() < accuracy:
                new[dimension] = label
                continue
            if dimension == "bilissel_talep":
                idx = min(order.index(label) + 1, len(order) - 1)
                new[dimension] = order[idx]
            else:
                options = [
                    x for x in seg.PRODUCTION_DIMENSIONS[dimension] if x != label
                ]
                new[dimension] = rng.choice(options)
        out[question] = new
    return out


# ---------------------------------------------------------------------------
# Profil uretimi
# ---------------------------------------------------------------------------


def build_profiles(
    answers: list[tuple[str, str, str | None]],
    labels: dict[str, dict[str, str]],
    keys: dict[str, str | None],
    school: str,
) -> dict[str, list]:
    by_student: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for question, student, selected in answers:
        if selected is None:
            continue
        key = keys.get(question)
        if not key or question not in labels:
            continue
        by_student[student].append((question, 1 if selected == key else 0))
    return {
        student: seg.student_profiles(school, student, rows, labels, NOW_MS)
        for student, rows in by_student.items()
    }


def gold_targets(student: dict[str, Any]) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """(altin pozitifler, gri bolge) — `dim_delta` uzerinden."""
    positives: set[tuple[str, str]] = set()
    grey: set[tuple[str, str]] = set()
    for dimension, labels in (student.get("dim_delta") or {}).items():
        for label, delta in labels.items():
            if delta <= GOLD_DELTA:
                positives.add((dimension, label))
            elif delta <= GREY_DELTA:
                grey.add((dimension, label))
    return positives, grey


# ---------------------------------------------------------------------------
# Kalibrasyon
# ---------------------------------------------------------------------------


def calibrate(
    profiles: dict[str, list], students: dict[str, dict[str, Any]], reference
) -> dict[str, Any]:
    """Kontrol grubunun goreli kontrast dagilimi + n'e gore yanlis pozitif."""
    control = [
        uid for uid, s in students.items() if not (s.get("dim_delta") or {})
    ]
    buckets: dict[str, list[float]] = defaultdict(list)
    n_values: dict[str, list[int]] = defaultdict(list)
    for uid in control:
        for profile in profiles.get(uid, []):
            rel = seg.relative_contrast(profile, reference)
            if rel is None:
                continue
            key = f"{profile.dimension}={profile.label}"
            buckets[key].append(rel)
            n_values[key].append(profile.n_answers)

    out: dict[str, Any] = {"kontrol_ogrenci": len(control), "segmentler": {}}
    for key, values in sorted(buckets.items()):
        mean = sum(values) / len(values)
        sd = seg._sd(values, mean)
        out["segmentler"][key] = {
            "n_ogrenci": len(values),
            "ortalama_goreli_kontrast": round(mean, 4),
            "sd": round(sd, 4),
            "en_dusuk": round(min(values), 4),
            "mean_eksi_3sd": round(mean - 3 * sd, 4),
            "segment_basina_cevap_medyani": sorted(n_values[key])[
                len(n_values[key]) // 2
            ],
        }
    return out


def gate_sweep(
    profiles: dict[str, list],
    students: dict[str, dict[str, Any]],
    reference,
    n_candidates: tuple[int, ...],
) -> list[dict[str, Any]]:
    """Asgari cevap sayisi esigi degistikce kontrol yanlis pozitifi."""
    rows: list[dict[str, Any]] = []
    for min_n in n_candidates:
        false_positive = 0
        fired_control = 0
        for uid, student in students.items():
            if student.get("dim_delta"):
                continue
            for profile in profiles.get(uid, []):
                if profile.n_answers < min_n:
                    continue
                rel = seg.relative_contrast(profile, reference)
                gate = seg.RELATIVE_CONTRAST_GATE.get(profile.dimension)
                if rel is None or gate is None:
                    continue
                if rel <= gate:
                    false_positive += 1
                    fired_control += 1
        rows.append(
            {
                "min_cevap": min_n,
                "kontrol_yanlis_pozitif_satir": false_positive,
                "kontrol_ateslenen": fired_control,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Kural degerlendirmesi
# ---------------------------------------------------------------------------


def evaluate(
    profiles: dict[str, list],
    students: dict[str, dict[str, Any]],
    reference,
    school: str,
) -> dict[str, Any]:
    """Kurallari GERCEKTEN calistirir ve uretilen tavsiyeleri degerlendirir."""
    fired: dict[str, set[tuple[str, str]]] = defaultdict(set)
    rule_of: dict[tuple[str, str], str] = {}
    evidence_missing = 0
    produced = 0

    for uid, rows in profiles.items():
        payload = seg.profile_payload(rows, reference)
        recs = for_student_segments(school, uid, payload, NOW_MS)
        for rec in recs:
            produced += 1
            payload_evidence = {
                k: v for k, v in rec.evidence.items() if k != "limitation"
            }
            if not payload_evidence:
                evidence_missing += 1
            dimension = rec.evidence["dimension"]
            label = rec.evidence["label"]
            fired[uid].add((dimension, label))
            rule_of[(dimension, label)] = rec.rule_id

    # --- arketip basina kesinlik / duyarlilik -----------------------------
    targets = {
        "A8 (ezberci)": ("bilissel_talep", "analiz"),
        "A4 (aceleci)": ("dikkat_tuzagi", "var"),
        "A7 (okuma guclugu)": ("okuma_yuku", "yuksek"),
    }
    per_target: dict[str, Any] = {}
    for name, target in targets.items():
        tp = fp = fn = 0
        grey_hits = 0
        for uid, student in students.items():
            positives, grey = gold_targets(student)
            hit = target in fired.get(uid, set())
            if target in positives:
                tp += int(hit)
                fn += int(not hit)
            elif target in grey:
                grey_hits += int(hit)
            elif hit:
                fp += 1
        precision = tp / (tp + fp) if (tp + fp) else None
        recall = tp / (tp + fn) if (tp + fn) else None
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision and recall
            else None
        )
        per_target[name] = {
            "segment": f"{target[0]}={target[1]}",
            "kural": rule_of.get(target, "-"),
            "altin_pozitif_ogrenci": tp + fn,
            "dogru_pozitif": tp,
            "yanlis_pozitif": fp,
            "yanlis_negatif": fn,
            "gri_bolge_ateslenen": grey_hits,
            "kesinlik": None if precision is None else round(precision, 4),
            "duyarlilik": None if recall is None else round(recall, 4),
            "f1": None if f1 is None else round(f1, 4),
        }

    # --- kontrol grubu yanlis pozitifleri ---------------------------------
    control_students = [
        uid for uid, s in students.items() if not (s.get("dim_delta") or {})
    ]
    control_fp_rows = 0
    control_fp_students = 0
    control_detail: dict[str, int] = defaultdict(int)
    for uid in control_students:
        hits = fired.get(uid, set())
        if hits:
            control_fp_students += 1
        control_fp_rows += len(hits)
        for dimension, label in hits:
            control_detail[f"{dimension}={label}"] += 1

    return {
        "uretilen_tavsiye": produced,
        "kanitsiz_tavsiye": evidence_missing,
        "arketipler": per_target,
        "kontrol_grubu": {
            "ogrenci": len(control_students),
            "yanlis_pozitif_ogrenci": control_fp_students,
            "yanlis_pozitif_satir": control_fp_rows,
            "segment_dagilimi": dict(sorted(control_detail.items())),
        },
    }


def evaluate_class_rule(
    profiles: dict[str, list],
    students: dict[str, dict[str, Any]],
    reference,
    school: str,
) -> dict[str, Any]:
    """`T3.segment_class_gap` sinif basina kac kez ateslendi."""
    by_class: dict[str, list] = defaultdict(list)
    for uid, rows in profiles.items():
        class_id = (students.get(uid) or {}).get("class")
        if class_id:
            by_class[class_id].extend(rows)
    class_stats = seg.class_contrasts(by_class, reference)

    fired: dict[str, list[str]] = {}
    total = 0
    for class_id, dims in sorted(class_stats.items()):
        recs = for_class_segments(
            school,
            class_id,
            class_segments=dims,
            class_teachers=["ogretmen-ornek"],
            now_ms=NOW_MS,
        )
        total += len(recs)
        if recs:
            fired[class_id] = [
                f"{r.evidence['dimension']}={r.evidence['label']} "
                f"({r.evidence['mean_relative_contrast']}, "
                f"n={r.evidence['n_students']})"
                for r in recs
            ]
    # --- POZITIF KONTROL --------------------------------------------------
    # Tohumda siniflar arketiplere gore kurgulanmadi: her sinifta her arketip
    # var, dolayisiyla hicbir sinif TOPLUCA geride degil ve kuralin
    # atesLEMEMESI beklenen sonuctur. "Ateslemiyor" ile "atesLEYEMIYOR" ayni
    # sey degildir; ayrimi gostermek icin YAPAY bir sinif kurulur: ezberci
    # (A8) ogrencilerin tamami tek bir sinifa konur.
    synthetic = [
        p
        for uid, rows in profiles.items()
        if (students.get(uid) or {}).get("archetype") == "A8"
        for p in rows
    ]
    synth_stats = seg.class_contrasts({"YAPAY-A8": synthetic}, reference)
    synth_recs = for_class_segments(
        school,
        "YAPAY-A8",
        class_segments=synth_stats.get("YAPAY-A8", {}),
        class_teachers=["ogretmen-ornek"],
        now_ms=NOW_MS,
    )

    return {
        "sinif": len(class_stats),
        "uretilen_tavsiye": total,
        "ateslenen_siniflar": fired,
        "pozitif_kontrol": {
            "aciklama": (
                "Yapay sinif: tum A8 (ezberci) ogrenciler tek sinifta. Kural "
                "ATESLEMELI; ateslemezse kural olu demektir."
            ),
            "uretilen_tavsiye": len(synth_recs),
            "maddeler": [
                f"{r.evidence['dimension']}={r.evidence['label']} "
                f"({r.evidence['mean_relative_contrast']}, "
                f"n={r.evidence['n_students']})"
                for r in synth_recs
            ],
        },
        "sinif_ozeti": {
            class_id: {
                f"{d}={lab}": row["mean_relative_contrast"]
                for d, labels in dims.items()
                for lab, row in labels.items()
            }
            for class_id, dims in sorted(class_stats.items())
        },
    }


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", default=str(REPO / "work" / "items_enriched.json"))
    parser.add_argument(
        "--manifest", default=str(REPO / "seed" / "_seed_manifest.json")
    )
    parser.add_argument(
        "--answers", default=str(REPO / "seed" / "11_exam_answer.surql")
    )
    parser.add_argument("--json", default=None, help="raporu bu dosyaya yaz")
    parser.add_argument(
        "--noise",
        action="store_true",
        help="olculmus LLM hata oranlarini altin etiketlere uygula (MODELLEME)",
    )
    parser.add_argument("--seed", type=int, default=20260915)
    args = parser.parse_args(argv)

    items_path = Path(args.items)
    labels = load_gold_labels(items_path)
    keys = load_keys(items_path)
    students = load_students(Path(args.manifest))
    answers = load_answers(Path(args.answers))
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    school = manifest.get("school_slug") or "okul"

    if args.noise:
        labels = perturb(labels, args.seed)

    profiles = build_profiles(answers, labels, keys, school)
    flat = [p for rows in profiles.values() for p in rows]
    reference = seg.reference_contrasts(flat)

    report: dict[str, Any] = {
        "kip": "MODELLENMIS ETIKET GURULTUSU" if args.noise else "ALTIN ETIKET",
        "ne_olculuyor": (
            "Kurallar dogru calisiyor mu (etiketler dogruyken arketipleri "
            "buluyor mu). LLM'in dogru etiketleyip etiketlemedigi OLCULMEZ."
        ),
        "veri": {
            "etiketli_soru": len(labels),
            "cevap_satiri": len(answers),
            "ogrenci": len(profiles),
            "profil_satiri": len(flat),
        },
        "esikler": {
            "min_cevap": seg.MIN_ANSWERS_PER_SEGMENT,
            "goreli_kontrast_kapisi": seg.RELATIVE_CONTRAST_GATE,
            "sinif_kapisi": seg.CLASS_RELATIVE_CONTRAST_GATE,
            "min_sinif_ogrencisi": seg.MIN_CLASS_STUDENTS,
            "bakilan_boyutlar": list(STUDENT_SEGMENT_DIMENSIONS),
        },
        "referans_kontrastlar": reference,
        "kalibrasyon": calibrate(profiles, students, reference),
        "kapi_taramasi": gate_sweep(
            profiles, students, reference, (30, 50, 75, 100, 125, 150, 200, 300)
        ),
        "kural_degerlendirmesi": evaluate(profiles, students, reference, school),
        "sinif_kurali": evaluate_class_rule(
            profiles, students, reference, school
        ),
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json:
        Path(args.json).write_text(text, encoding="utf-8")
        print(f"yazildi: {args.json}", file=sys.stderr)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
