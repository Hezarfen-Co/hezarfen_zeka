"""Not (mark) düzeyinde ders karnesi: ortalama, kohorttaki konum, eğilim.

Kaynak: `spec/MODULLER.md` §2.3 `insight::subject_mastery`, `[T§3 Ö1]`.

**Uyarlama — bu modül konu (subject) düzeyinde DEĞİL, not düzeyinde çalışır.**
`MODULLER.md` §2.3 (öğrenci × konu doğruluk oranı) ham `exam_answer` +
`exam_question.subject` gerektirir. `Source` arayüzünde sınav cevabı yok, konu
kırılımı yok; yalnız ders bazında verilmiş notlar var. Dolayısıyla:

* konu (`subject`) kırılımı **üretilemez** — ders (`course`) kırılımı üretilir;
* `p_öğrenci` (doğruluk oranı) yerine **ağırlıklı not ortalaması** kullanılır;
* bant mantığı (`z`, üç bant, `n` kapısı) **aynen korunur**.

**Kohort — `MODULLER.md` §0 kural 2 aynen geçerli.** Referans dağılımı
şube × ders (`class_course`) düzeyinde kurulur, okul geneli havuz
**kullanılmaz**. `[L-6]` (Gašević ve ark. 2016, n=4.134/9 ders): bağlam
gözetmeden havuzlanan katsayılar sistematik olarak sapar. Şube kimliği
`Source.profile()` → `classes[*].id` alanından gelir.
"""

from __future__ import annotations

from typing import Any

from . import stat
from .model import Band, Confidence, ulid_ms

# --- Eşikler ----------------------------------------------------------------

# `MODULLER.md` §2.3 güven kapısı: öğrenci gözlem sayısı `n_answered >= 8`.
# O eşik **cevap** düzeyindedir ve `[T§3 Ö1]`'in "zarar eşiği" gerekçesine
# dayanır: "bu kapı olmadan 2 soruluk bir konudan 'zayıfsın' çıkarılır".
# Belgedeki değeri kaynağıyla birlikte burada tutuyoruz; ama uygulanamıyor,
# çünkü cevap verisi bu sürümde yok.
MASTERY_ANSWER_GATE_DOC = 8

# Not düzeyindeki karşılığı. `MODULLER.md` bu düzey için eşik VERMİYOR, bu
# yüzden bu bir **ürün kararıdır** `(doğrulanmadı)`. Gerekçe aritmetiktir:
# tohumda 11.795 `exam_result` / 250 öğrenci ≈ 47 not, ~10–12 ders başına
# ≈ 4 not düşer (`[M]` tablo satır sayıları). 8'i ders başına uygulamak
# **hiçbir öğrenciye bant göstermemek** demektir; 1–2 not ise "zarar eşiği"nin
# altındadır. 3, iki ucun arasındaki en küçük savunulabilir sayıdır.
MIN_MARKS_FOR_BAND = 3

# Eğilim için: `MODULLER.md` §2.8 tetikleyici 3 "son 3 oturum ortalaması,
# önceki 3'ten ≥ 15 puan düşük" diyor → iki pencere için en az 6 not gerekir.
MIN_MARKS_FOR_TREND = 6

# `MODULLER.md` §2.3 güven kapısı: kohort büyüklüğü `cohort_n >= 8`.
# Altında **bir üst kırılıma çıkılmaz** — çıkmak tam olarak `[L-6]`'nın
# uyardığı havuzlamadır; `band = InsufficientData` yazılır.
COHORT_MIN = 8

# `MODULLER.md` §2.3 adım 4 / `[T§3 Ö1]`: üç bant sınırı.
BAND_Z = 0.8

# `MODULLER.md` §2.3 güven kapısı: kohort dağılımı σ < 0,05 ise z hesaplanır
# ama güven "ön bulgu"ya düşer ("sınıf bu derste homojen").
# Not ölçeği 0–100 olduğu için oran ölçeğindeki 0,05 burada 0,5 puandır.
HOMOGENEOUS_SD = 0.5

# `MODULLER.md` §2.8 tetikleyici 3: aynı derste ≥ 15 puan düşüş.
MARK_DROP_POINTS = 15.0

# --- Yükselen sınıfı (kusur K6 düzeltmesi) ----------------------------------
#
# `course_trend()` bugüne kadar yalnız `dropped` üretiyordu; `SENARYO.md`
# §3.2 Ö1'in istediği "T1 düşük → T2 güçlü" (A5) ürünü tüketiciye bırakılmıştı.
# İki koşul **birlikte** aranır, çünkü ikisi farklı şeyi yakalar:
#
#   * `MARK_RISE_POINTS` — `MARK_DROP_POINTS`'un simetriği: son 3 notun
#     ortalaması önceki 3'ten ≥ 15 puan yüksek. Sıçramayı görür.
#   * `RISING_SLOPE_PER_30D` — dönem boyunca **süregelen** eğim. Tek bir iyi
#     sınavın ürettiği sahte sıçramayı eler.
#
# Eşik ÖLÇÜLDÜ, seçilmedi: 250 öğrencilik altın kümede öğrenci başına medyan
# `slope_per_30d` A5 arketipinde **+7,11 puan/30 gün** (en düşüğü +3,73),
# diğer yedi arketipte **+0,16 … +0,98** (A6'da −5,94). 3,0 bu iki kümenin
# arasındaki geniş boşluğa düşer ve kenarlara yapışık değildir. Ders düzeyinde
# iki koşul birlikte uygulanıp öğrenci düzeyinde "derslerinin çoğu yükseliyor"
# diye toplandığında A5 için kesinlik 0,79 / duyarlılık 0,76 ölçüldü.
RISING_SLOPE_PER_30D = 3.0
MARK_RISE_POINTS = 15.0

# --- Öğrenci-içi ders kontrastı (kusur K7 düzeltmesi) -----------------------
#
# `place_in_cohort()` öğrenciyi **kohorta göre** yerleştirir: "bu ders bu
# şubede zayıf". Ama `SENARYO.md` §3.5'in konu boşluğu arketipi (A3) "genel
# olarak iyi, TEK bir derste çukur" demek. Kohort-dışı z bu ayrımı yapamaz ve
# ölçümde `Band.REVIEW` ile boşluk dersini yakalamanın kesinliği 0,056 çıktı
# (556 ders-öğrenci çiftinde 31 doğru).
#
# Öğrenci-**içi** kontrast aynı çıktıdan türetilir ve ölçümde çok daha keskin:
# en düşük z'li ders ile o öğrencinin diğer derslerinin **medyan z**'si
# arasındaki fark ≤ −1,5 → altın kümede kesinlik **1,00**, duyarlılık **0,857**
# (30 tahminin 30'u doğru, üstelik 30'unda da hangi ders olduğu doğru).
# Eşik bu ölçümden gelir; −1,0'de kesinlik düşer, −2,0'de duyarlılık düşer.
WITHIN_STUDENT_CONTRAST = -1.5

# Kontrast için en az kaç derste z gerekir. 3'ün altında "diğer derslerin
# medyanı" tek bir dersten oluşur ve medyan olmaktan çıkar.
MIN_COURSES_FOR_CONTRAST = 3

# `[T§3 T3]` / `MODULLER.md` §2.10 `T3.class_gap`: sınıf ortalaması bu değerin
# altındaysa "konu sınıf için sorun" ayrımı. Oran ölçeğinde 0,50 → 100'lük
# not ölçeğinde 50.
CLASS_GAP_AVERAGE = 50.0


# --- Girdi normalleştirme ---------------------------------------------------
#
# `Source.marks()` bir liste döndürür: her öğe backend'in `CourseMarks`
# nesnesidir — `{course: {...}, results: [...], average, average_grade}`.
# Köprü uygulaması listeyi `MarksReport` zarfı içinde verirse de çalışsın diye
# tek bir yerde toleranslı çözüyoruz; başka hiçbir yerde şekil tahmini yok.


def normalize_rows(raw: Any) -> list[dict[str, Any]]:
    """`marks()` çıktısını ders satırları listesine indirger."""
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = raw.get("courses") or raw.get("items") or []
    return [r for r in raw if isinstance(r, dict)]


def course_id_of(row: dict[str, Any]) -> str | None:
    """Ders kimliği; `course` alanı ya nesne ya düz kimliktir."""
    course = row.get("course")
    if isinstance(course, dict):
        cid = course.get("id")
        return str(cid) if cid else None
    return str(course) if course else None


def course_title_of(row: dict[str, Any]) -> str:
    course = row.get("course")
    if isinstance(course, dict):
        return str(course.get("title") or "")
    return ""


# --- Tek öğrenci, tek ders --------------------------------------------------


def course_average(results: list[dict[str, Any]]) -> float | None:
    """Ağırlıklı ders ortalaması: Σ(mark × weight) / Σ(weight).

    Backend aynı hesabı `CourseMarks.average` içinde zaten yapıyor; biz yine de
    ham `results` üzerinden yeniden hesaplıyoruz. Gerekçe `[T§1.3]` kural 3 ve
    `MODULLER.md` §2.6: **sayaç/türev alan okunmaz, ham kayıt okunur** — ağırlık
    okul ayarlarından istek anında çözülüyor ve sonradan değişebiliyor.
    """
    total_w = 0
    total = 0.0
    for r in results:
        mark = r.get("mark")
        if mark is None:
            continue
        weight = r.get("weight")
        weight = 1 if weight is None else int(weight)
        if weight <= 0:
            continue
        total += float(mark) * weight
        total_w += weight
    if total_w == 0:
        return None
    return total / total_w


def _ordered_marks(results: list[dict[str, Any]]) -> list[tuple[int, float]]:
    """(zaman, not) çiftleri, zamana göre artan.

    Zaman çapası: `exam` kimliği ms-monotonic ULID'dir
    (`spec/schema.json` → `id_rules.exam`), ilk 10 karakteri unix-ms damgasıdır.
    `MarkEntry` üzerinde **hiçbir zaman damgası yok** (`web/marks.rs:32`), bu
    yüzden sıralamanın tek dürüst kaynağı budur.

    ⚠️ SINIR: bu damga sınavın **oluşturulma** anıdır, öğrencinin sınava girme
    anı değildir. Eğilim hesabı sıralamaya dayanır, mutlak tarihe değil
    (`MODULLER.md` §2.8 "zaman çapası" ile aynı kabul).
    """
    pairs: list[tuple[int, float]] = []
    for r in results:
        mark = r.get("mark")
        if mark is None:
            continue
        ts = ulid_ms(str(r.get("exam") or ""))
        if ts is None:
            continue
        pairs.append((ts, float(mark)))
    pairs.sort(key=lambda p: p[0])
    return pairs


def course_trend(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Dönem içi eğilim: regresyon eğimi + son 3 / önceki 3 farkı.

    Güven kapısı: `MIN_MARKS_FOR_TREND` altında eğilim **hesaplanmaz**;
    `available = False` döner. Yeni gelen öğrenci işaretlenemez
    (`MODULLER.md` §2.8 "Önceki pencere gözlemi" kapısı, `[N§7.5]` P25 = 0).
    """
    pairs = _ordered_marks(results)
    if len(pairs) < MIN_MARKS_FOR_TREND:
        return {
            "available": False,
            "reason": f"eğilim için en az {MIN_MARKS_FOR_TREND} not gerekir",
            "n": len(pairs),
            "slope_per_30d": None,
            "recent_mean": None,
            "previous_mean": None,
            "delta": None,
            "dropped": False,
            "rising": False,
        }
    # Eğim: 30 günlük dilim başına puan değişimi (yorumlanabilir birim).
    slope_ms = stat.trend_slope([(float(t), m) for t, m in pairs])
    slope_30d = None if slope_ms is None else slope_ms * 30 * 86_400_000

    recent = [m for _, m in pairs[-3:]]
    previous = [m for _, m in pairs[-6:-3]]
    recent_mean = stat.mean(recent)
    previous_mean = stat.mean(previous)
    delta = None
    if recent_mean is not None and previous_mean is not None:
        delta = recent_mean - previous_mean
    return {
        "available": True,
        "reason": None,
        "n": len(pairs),
        "slope_per_30d": slope_30d,
        "recent_mean": recent_mean,
        "previous_mean": previous_mean,
        "delta": delta,
        # `MODULLER.md` §2.8 tetikleyici 3: ≥ 15 puan düşüş.
        "dropped": delta is not None and delta <= -MARK_DROP_POINTS,
        # Kusur K6 düzeltmesi — simetrik sıçrama **ve** süregelen eğim.
        # `dropped` ile `rising` aynı anda doğru olamaz (delta'nın işareti tek).
        "rising": (
            delta is not None
            and delta >= MARK_RISE_POINTS
            and slope_30d is not None
            and slope_30d >= RISING_SLOPE_PER_30D
        ),
    }


def student_course_stats(raw_marks: Any) -> dict[str, dict[str, Any]]:
    """Bir öğrencinin ders bazında not özeti. Kohort **gerektirmez**.

    Dönen sözlük: `{course_id: {...}}`.
    """
    out: dict[str, dict[str, Any]] = {}
    for row in normalize_rows(raw_marks):
        cid = course_id_of(row)
        if cid is None:
            continue
        results = [r for r in (row.get("results") or []) if isinstance(r, dict)]
        marks = [float(r["mark"]) for r in results if r.get("mark") is not None]
        out[cid] = {
            "course": cid,
            "course_title": course_title_of(row),
            "n_marks": len(marks),
            "average": course_average(results),
            "mean": stat.mean(marks),
            "median": stat.median(marks),
            "min": min(marks) if marks else None,
            "max": max(marks) if marks else None,
            "trend": course_trend(results),
        }
    return out


# --- Kohort -----------------------------------------------------------------


def class_ids_of(profile: dict[str, Any] | None) -> list[str]:
    """Öğrencinin şubeleri (`ProfileResponse.classes[*].id`)."""
    if not profile:
        return []
    classes = profile.get("classes") or []
    return [str(c["id"]) for c in classes if isinstance(c, dict) and c.get("id")]


def cohort_key(class_id: str, course_id: str) -> str:
    """Referans kohortu = şube × ders (`class_course` düzeyi).

    `MODULLER.md` §0 kural 2 / §2.3 adım 2: okul geneli havuzdan **hiçbir
    yerde** öğrenci bandı üretilmez.
    """
    return f"{class_id}|{course_id}"


def collect_cohort_samples(
    per_student: dict[str, tuple[list[str], dict[str, dict[str, Any]]]],
) -> dict[str, list[float]]:
    """Tüm öğrencilerin ders ortalamalarını kohort kovalarına dağıtır.

    `per_student`: `{student_id: (class_ids, course_stats)}`.
    """
    buckets: dict[str, list[float]] = {}
    for class_ids, courses in per_student.values():
        for cid, cstat in courses.items():
            avg = cstat.get("average")
            if avg is None or cstat.get("n_marks", 0) < MIN_MARKS_FOR_BAND:
                continue
            for class_id in class_ids:
                buckets.setdefault(cohort_key(class_id, cid), []).append(float(avg))
    return buckets


def cohort_distributions(
    buckets: dict[str, list[float]],
) -> dict[str, dict[str, Any]]:
    """Kohort başına (ortalama, σ, n). `n < COHORT_MIN` olanlar da döner ama
    `usable = False` taşır — üst kırılıma **çıkılmaz** (`MODULLER.md` §2.3)."""
    out: dict[str, dict[str, Any]] = {}
    for key, values in buckets.items():
        ms = stat.mean_sd(values)
        if ms is None:
            continue
        mu, sd = ms
        out[key] = {
            "mean": mu,
            "sd": sd,
            "n": len(values),
            "usable": len(values) >= COHORT_MIN,
            "homogeneous": sd < HOMOGENEOUS_SD,
        }
    return out


def place_in_cohort(
    average: float | None,
    n_marks: int,
    dist: dict[str, Any] | None,
) -> dict[str, Any]:
    """Ders ortalamasını kohort dağılımına yerleştirir → (z, bant, güven).

    Güven kapıları (`MODULLER.md` §2.3):
      * `n_marks < MIN_MARKS_FOR_BAND` → bant **hiç** gösterilmez,
        "veri toplanıyor (n/N)" metni üretilir;
      * kohort `n < COHORT_MIN` → `class_average = None`, `z = None`,
        bant `INSUFFICIENT_DATA`;
      * kohort σ çok küçük → z hesaplanır, güven `EXPLORATORY`.
    """
    if average is None or n_marks < MIN_MARKS_FOR_BAND:
        return {
            "band": Band.INSUFFICIENT_DATA,
            "confidence": Confidence.NONE,
            "z": None,
            "class_average": None,
            "class_sd": None,
            "cohort_n": 0,
            "progress": f"{n_marks}/{MIN_MARKS_FOR_BAND}",
            "reason": "veri toplanıyor",
        }
    if dist is None or not dist.get("usable"):
        return {
            "band": Band.INSUFFICIENT_DATA,
            "confidence": Confidence.NONE,
            "z": None,
            "class_average": None,
            "class_sd": None,
            "cohort_n": int(dist["n"]) if dist else 0,
            "progress": None,
            "reason": f"kohort {COHORT_MIN} kişiden küçük; üst kırılıma çıkılmaz",
        }

    z = stat.z_score(float(average), float(dist["mean"]), float(dist["sd"]))
    if z < -BAND_Z:
        band = Band.REVIEW
    elif z > BAND_Z:
        band = Band.STRONG
    else:
        band = Band.ON_TRACK
    confidence = (
        Confidence.EXPLORATORY if dist.get("homogeneous") else Confidence.STABLE
    )
    return {
        "band": band,
        "confidence": confidence,
        "z": z,
        "class_average": float(dist["mean"]),
        "class_sd": float(dist["sd"]),
        "cohort_n": int(dist["n"]),
        "progress": None,
        "reason": "sınıf bu derste homojen" if dist.get("homogeneous") else None,
    }


def within_student_contrast(
    courses: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Öğrencinin **kendi dersleri arasındaki** en derin çukur (kusur K7).

    Kohort-dışı z "bu şubede zayıf" der; bu ölçü "kendi derslerine göre bu
    derste çukur" der. İkisi farklı sorulardır ve A3 (konu boşluğu) ikincisidir.

    Dönen `delta` = z(en düşük ders) − medyan(z(diğer dersler)). Negatif ve
    büyüklükçe `WITHIN_STUDENT_CONTRAST`'ı geçiyorsa `flagged = True`.

    ⚠️ SINIR: bu hâlâ **ders** düzeyidir, konu (subject) düzeyi değil. Ham
    sınav cevabı olmadığı için "hangi konuda boşluk var" sorusu bu sürümde
    cevaplanamaz; ölçü yalnız "hangi derste" der.
    """
    zs = {
        cid: float(c["placement"]["z"])
        for cid, c in courses.items()
        if isinstance(c.get("placement"), dict) and c["placement"].get("z") is not None
    }
    if len(zs) < MIN_COURSES_FOR_CONTRAST:
        return {
            "available": False,
            "reason": (
                f"kontrast için bantlanmış en az {MIN_COURSES_FOR_CONTRAST} "
                "ders gerekir"
            ),
            "n_courses": len(zs),
            "course": None,
            "course_title": None,
            "z": None,
            "others_median_z": None,
            "delta": None,
            "flagged": False,
        }
    worst = min(zs, key=lambda cid: zs[cid])
    others = [v for cid, v in zs.items() if cid != worst]
    others_median = stat.median(others)
    assert others_median is not None
    delta = zs[worst] - others_median
    return {
        "available": True,
        "reason": None,
        "n_courses": len(zs),
        "course": worst,
        "course_title": (courses.get(worst) or {}).get("course_title") or "",
        "z": zs[worst],
        "others_median_z": others_median,
        "delta": delta,
        "flagged": delta <= WITHIN_STUDENT_CONTRAST,
    }


def student_profile(
    raw_marks: Any,
    profile: dict[str, Any] | None,
    distributions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Bir öğrencinin tam not profili: ders bazında ortalama + bant + eğilim.

    `distributions` verilmezse bant üretilmez (kohort bilinmeden bant
    hesaplamak `[L-6]`'nın uyardığı havuzlamadır).
    """
    class_ids = class_ids_of(profile)
    courses = student_course_stats(raw_marks)
    dists = distributions or {}
    for cid, cstat in courses.items():
        best: dict[str, Any] | None = None
        for class_id in class_ids:
            cand = dists.get(cohort_key(class_id, cid))
            if cand and (best is None or cand["n"] > best["n"]):
                best = cand
        cstat["placement"] = place_in_cohort(
            cstat.get("average"), int(cstat.get("n_marks", 0)), best
        )
    return {
        "classes": class_ids,
        "courses": courses,
        # Kusur K7 — öğrenci-içi kontrast. `placement` içine konmadı: bu bir
        # ders özelliği değil, öğrencinin **ders kümesine** ait bir ölçüdür.
        "within_student_contrast": within_student_contrast(courses),
        # Sınır satırı — her üründe gösterilir (`MODULLER.md` §2.10 kural 2).
        "limitation": (
            "Konu (subject) kırılımı bu sürümde yok: köprü ham sınav cevabı "
            "vermiyor. Kırılım ders düzeyindedir ve yalnız notlanmış sınavları "
            "kapsar."
        ),
    }


def course_teachers(raw_marks: Any) -> dict[str, list[str]]:
    """Ders → o dersin öğretmen/oluşturucu kimlikleri.

    `CourseMarks.course` alanı backend'in tam `CourseResponse` nesnesidir ve
    `creator` + `teachers` (`PersonRef` listesi) taşır (`web/dto.rs:211`).
    Öğretmene giden tavsiyelerin alıcısı buradan çözülür.

    **Yetki notu (`[T§5.3]`):** bu eşleme bir yetki genişletmesi değildir —
    dönen kişiler, o öğrencinin o dersteki verisini **bugün de** görebilen
    kişilerdir (`can_manage_course`). Yeni bir rol veya kapsam icat edilmez.
    """
    out: dict[str, list[str]] = {}
    for row in normalize_rows(raw_marks):
        course = row.get("course")
        if not isinstance(course, dict):
            continue
        cid = course.get("id")
        if not cid:
            continue
        ids: list[str] = []
        creator = course.get("creator")
        if isinstance(creator, dict) and creator.get("id"):
            ids.append(str(creator["id"]))
        for t in course.get("teachers") or []:
            if isinstance(t, dict) and t.get("id"):
                ids.append(str(t["id"]))
        # Sıra korunarak tekilleştir.
        seen: set[str] = set()
        out[str(cid)] = [i for i in ids if not (i in seen or seen.add(i))]
    return out
