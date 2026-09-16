"""Devam oranı ve kohorta göre göreli konum.

Kaynak: `spec/MODULLER.md` §2.5 `insight::attendance`.

**Ne üretiliyor:** ders bazında ve okul bazında devam oranı, statü dağılımı,
şube × ders kohortunun medyanına göre **göreli fark**.

**Ne ÜRETİLEMİYOR ve neden (sahte sayı yazmıyoruz, `[T§3 Y1]` ilkesi):**

* **Haftanın günü deseni.** `MODULLER.md` §2.5 adım 5 bunu
  `clock.tr_weekday(course_session.starts_at)` üzerinden kuruyor. Köprünün
  öğrenci devam ucu (`GET /attendance/{user}`) **yalnız sayaç** döndürüyor:
  `present/absent/late/excused/custom/total/rate`. Satır yok, oturum kimliği
  yok, tarih yok. Satır düzeyindeki `SessionAttendanceResponse` bile zaman
  damgası taşımıyor — `[S]` `session_attendance.fields` = `session, course,
  user, status, marked_by` ve kayıt anahtarı kompozit
  (`{course_session_key}_{user_key}`), yani kimlikten de türetilemez.
  Gereken: oturum başına `starts_at`, yani `course_session` erişimi.

* **İki pencere karşılaştırması (son 30 gün ↔ önceki 30 gün) ve `delta`.**
  Aynı sebep: zaman ekseni yok. `MODULLER.md` §2.5 adım 3–4 bu modülün "asıl
  katkısı" dediği **kolektif olaydan ayrıştırma**yı `delta` üzerinden kuruyor.

**Bunun yerine ne yapılıyor:** göreli ölçü korunur, ama **düşüş farkı** yerine
**seviye farkı** üzerinden: `relative_gap = rate(öğrenci) − medyan(kohort)`.
Gerekçe `[L-6]` aynen geçerli — mutlak eşik, kolektif olayda (tohumdaki grip
haftası: devamsızlık normalin **2,40 katı**, `[N§7.4]` D7) onlarca yanlış
pozitif üretir; kohort medyanına göre ölçmek bunu emer. Ama şu farkla:
seviye farkı, düşüş farkından **daha zayıf** bir sinyaldir — sürekli düşük
devamlı bir öğrenciyi "değişti" sananlardan ayıramaz. Bu sınır çıktıda
`trend.available = False` olarak taşınır ve dikkat listesi maddesinin
metninde yazılır.
"""

from __future__ import annotations

from typing import Any

from . import stat

# `MODULLER.md` §2.5 güven kapısı: `n_obs_30 >= 10` altında oran gösterilmez.
MIN_OBS = 10

# `MODULLER.md` §2.3 / §2.5 kohort kapısı: 8 kişiden küçük kohortta göreli
# ölçü üretilmez ve **mutlak değere düşülmez**.
COHORT_MIN = 8

# `MODULLER.md` §2.8 tetikleyici 1: `rate_30 < 0,80`.
ATTENTION_RATE = 0.80

# `MODULLER.md` §2.8 tetikleyici 1: kohort medyanına göre ≤ −0,10.
ATTENTION_RELATIVE_GAP = -0.10

# `[S]` çekirdek statüler. Okul `settings.attendance_statuses` ile
# genişletebilir; **tanınmayan statü paydaya girmez** (`MODULLER.md` §2.5
# adım 1, `web/attendance.rs` `custom =>` kolu).
CORE_STATUSES = ("present", "absent", "late", "excused")


def normalize_rows(raw: Any) -> list[dict[str, Any]]:
    """`attendance()` çıktısını ders satırları listesine indirger."""
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = raw.get("courses") or raw.get("items") or []
    return [r for r in raw if isinstance(r, dict)]


def _counts_of(row: dict[str, Any]) -> dict[str, Any]:
    counts = row.get("counts")
    return counts if isinstance(counts, dict) else {}


def _course_id(row: dict[str, Any]) -> str | None:
    course = row.get("course")
    if isinstance(course, dict):
        cid = course.get("id")
        return str(cid) if cid else None
    return str(course) if course else None


def rate_of(counts: dict[str, Any]) -> tuple[float | None, int]:
    """`(present + late) / (present + absent + late)` ve payda.

    `MODULLER.md` §2.5 adım 1, `web/attendance.rs:69-72` formülünün birebir
    karşılığı. **`excused` pay/paydaya girmez** — raporlu devamsızlık bir
    disiplin sinyali değildir. Tanınmayan (`custom`) statüler de paydaya
    girmez; ayrı sayılır.
    """
    present = int(counts.get("present") or 0)
    absent = int(counts.get("absent") or 0)
    late = int(counts.get("late") or 0)
    denom = present + absent + late
    return (stat.rate(present + late, denom), denom)


def course_stats(raw_attendance: Any) -> dict[str, dict[str, Any]]:
    """Ders bazında devam profili. Kohort **gerektirmez**."""
    out: dict[str, dict[str, Any]] = {}
    for row in normalize_rows(raw_attendance):
        cid = _course_id(row)
        if cid is None:
            continue
        counts = _counts_of(row)
        rate, n_obs = rate_of(counts)
        custom = counts.get("custom") or {}
        out[cid] = {
            "course": cid,
            "present": int(counts.get("present") or 0),
            "absent": int(counts.get("absent") or 0),
            "late": int(counts.get("late") or 0),
            "excused": int(counts.get("excused") or 0),
            "custom_total": sum(int(v or 0) for v in custom.values())
            if isinstance(custom, dict)
            else 0,
            "n_obs": n_obs,
            # Güven kapısı: paydası 10'dan küçükse oran **gösterilmez**.
            "rate": rate if n_obs >= MIN_OBS else None,
            "rate_suppressed": n_obs < MIN_OBS,
        }
    return out


def overall(course_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Tüm derslerin birleşik devam oranı."""
    present = sum(c["present"] for c in course_map.values())
    absent = sum(c["absent"] for c in course_map.values())
    late = sum(c["late"] for c in course_map.values())
    excused = sum(c["excused"] for c in course_map.values())
    denom = present + absent + late
    rate = stat.rate(present + late, denom)
    return {
        "present": present,
        "absent": absent,
        "late": late,
        "excused": excused,
        "n_obs": denom,
        "rate": rate if denom >= MIN_OBS else None,
        "rate_suppressed": denom < MIN_OBS,
    }


# --- Kohort -----------------------------------------------------------------


def cohort_key(class_id: str, course_id: str) -> str:
    """Şube × ders — `MODULLER.md` §0 kural 2 (`[L-6]`)."""
    return f"{class_id}|{course_id}"


def collect_cohort_samples(
    per_student: dict[str, tuple[list[str], dict[str, dict[str, Any]]]],
) -> dict[str, list[float]]:
    """Kohort kovalarına ders bazlı devam oranlarını dağıtır."""
    buckets: dict[str, list[float]] = {}
    for class_ids, courses in per_student.values():
        for cid, cstat in courses.items():
            rate = cstat.get("rate")
            if rate is None:
                continue
            for class_id in class_ids:
                buckets.setdefault(cohort_key(class_id, cid), []).append(float(rate))
    return buckets


def cohort_medians(buckets: dict[str, list[float]]) -> dict[str, dict[str, Any]]:
    """Kohort başına medyan devam oranı ve kullanılabilirlik bayrağı.

    Medyan, ortalama değil: `MODULLER.md` §2.5 adım 4 kolektif olayı emmek için
    açıkça **medyan** istiyor (bir grip haftası ortalamayı çeker, medyanı değil).
    """
    out: dict[str, dict[str, Any]] = {}
    for key, values in buckets.items():
        med = stat.median(values)
        if med is None:
            continue
        out[key] = {
            "median": med,
            "n": len(values),
            "usable": len(values) >= COHORT_MIN,
        }
    return out


def student_profile(
    raw_attendance: Any,
    class_ids: list[str],
    medians: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Bir öğrencinin tam devam profili.

    `relative_gap`: öğrencinin oranı eksi kohort medyanı. Kohort 8 kişiden
    küçükse `None` — **mutlak eşiğe düşülmez** (`MODULLER.md` §2.5 kohort
    kapısı).
    """
    courses = course_stats(raw_attendance)
    meds = medians or {}
    gaps: list[float] = []
    for cid, cstat in courses.items():
        rate = cstat.get("rate")
        best: dict[str, Any] | None = None
        for class_id in class_ids:
            cand = meds.get(cohort_key(class_id, cid))
            if cand and cand.get("usable") and (best is None or cand["n"] > best["n"]):
                best = cand
        if rate is None or best is None:
            cstat["cohort_median"] = None
            cstat["cohort_n"] = int(best["n"]) if best else 0
            cstat["relative_gap"] = None
        else:
            cstat["cohort_median"] = float(best["median"])
            cstat["cohort_n"] = int(best["n"])
            cstat["relative_gap"] = float(rate) - float(best["median"])
            gaps.append(cstat["relative_gap"])

    summary = overall(courses)
    summary["relative_gap"] = stat.median(gaps) if gaps else None
    return {
        "overall": summary,
        "courses": courses,
        # `MODULLER.md` §2.5 adım 5 — bu sürümde üretilemez.
        "weekday_pattern": None,
        "weekday_pattern_reason": (
            "Devam ucu yalnız sayaç döndürüyor; oturum tarihi yok. "
            "Haftanın günü deseni için course_session.starts_at gerekir."
        ),
        # `MODULLER.md` §2.5 adım 2–3 — bu sürümde üretilemez.
        "trend": {
            "available": False,
            "reason": (
                "İki pencere karşılaştırması için satır düzeyinde zaman damgası "
                "gerekir; devam verisinde tarih yok."
            ),
            "delta": None,
        },
        "limitation": (
            "Devam oranı dönem başından bugüne kümülatiftir, son 30 gün değildir; "
            "raporlu (excused) devamsızlık orana girmez."
        ),
    }
