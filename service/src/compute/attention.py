"""Dikkat listesi — dört bağımsız tetikleyici, **tek skor YOK**.

Kaynak: `spec/MODULLER.md` §2.8 `insight::attention`,
`_analiz_raporlari/20_tavsiye_sistemi_tasarim.md` §3 T4 ve §6.6.

> **Bu, katalogdaki en yüksek riskli üründür.** `[L-8]`: erken uyarı
> sistemlerinin **etkisi** konusunda doğrulanmış nedensel kanıt yok (incelenen
> kaynak 5 pilot + 48 karşılaştırma okulluk, düşük güçlü bir fark-içinde-fark
> değerlendirmesi). Yani "erken uyarı işe yarar" iddiası kurulamaz; bu modülün
> tek başarı ölçüsü kendi yanlışlık oranıdır (`[T§7]` faz kapısı: ≤ %25).
> `[T§8.3 S1]` bu ürünün **hiç yapılmaması** seçeneğini açık bırakıyor.

**Kod düzeyinde uygulanan sınırlamalar (`[T§6.6]` + `MODULLER.md` §2.8):**

| # | Sınırlama | Nerede uygulanıyor |
|---|---|---|
| 1 | "risk" kelimesi üründe geçmez; madde bir **olgu cümlesidir** | `_fact_*` metinleri + `test_attention` taraması |
| 2 | **Sıralama yok** — alfabetik sabit | `order_items()`; `AttentionItem`'da `score`/`rank` alanı **yok** |
| 3 | Tek skor üretilmez | `model.AttentionItem` tek tetikleyici taşır |
| 4 | Her madde kanıta iner | `AttentionItem.__post_init__` boş kanıtı reddeder |
| 5 | **30 günde düşer** | `EXPIRY_DAYS`; `recommend.py` `expires_at` yazar |
| 6 | Öğrenciye/veliye gösterilmez | `recommend.py` → `Audience.TEACHER` |
| 7 | Dışa aktarma yok | bu pakette dışa aktarma fonksiyonu **yoktur** |
| 8 | Dönem başı ilk 4 hafta kapalı | `COLD_START_WEEKS` |
| 9 | Yeni gelen öğrenci işaretlenemez | `_has_history()` önceki pencere kapısı |
| 10 | Kolektif olay bireysel uyarı üretmez | kohort göreliliği (`attendance.relative_gap`, `attention.MISSING_COHORT_FACTOR`) |
| 11 | **Mutlak eşik yok** — her eşik kohorta görelidir | `_homework_item()` şube medyanına böler; kohort yoksa ateşlemez |
| 12 | İyiye giden öğrenci seviye kuralıyla listelenmez | `_is_improving()` + `_suppress_rising()` |
"""

from __future__ import annotations

from typing import Any

from . import attendance as attendance_mod
from . import clock
from . import stat
from . import submission as submission_mod
from .model import AttentionItem, TriggerKind

# `[T§6.6]` madde 5 / `MODULLER.md` §2.8: liste maddesi 30 gün sonra otomatik
# düşer. Kalıcı etiket yok.
EXPIRY_DAYS = 30

# `MODULLER.md` §2.8 / `[T§3 T4]`: dönem başlangıcından itibaren ilk 4 hafta
# ürün **kapalıdır**. "Değişim" kuralları önceki pencereye ihtiyaç duyar;
# onsuz mutlak eşiğe düşmek yeni öğrencileri haksız işaretler.
COLD_START_WEEKS = 4

# `MODULLER.md` §2.8 "Önceki pencere gözlemi" kapısı: geçmişi olmayan öğrenci
# hiçbir tetikleyiciye giremez (`[N§7.5]` P25 = 0).
MIN_HISTORY_ITEMS = 5

WINDOW_DAYS = 30

# --- Ödev tetikleyicisinin kohort kalibrasyonu (kusur K1/K2 düzeltmesi) ------
#
# **Neden mutlak eşik kaldırıldı.** Eski kural `submission.MISSING_TRIGGER = 3`
# idi: "son 30 günde 3 ödev teslim edilmedi". Bu sayı bir **okul sabiti** gibi
# davranıyor ama aslında o okulun ödev yoğunluğuna bağlı. 250 öğrencilik altın
# kümede ölçüldü: 30 günlük pencerede öğrenci başına medyan **20 ödev** ve
# medyan **4 eksik** var — yani eşik okul medyanının ALTINDA. Sonuç: 250
# öğrencinin 192'sinde ödev maddesi ateşliyor, liste 193/250'ye çıkıyor
# (`SENARYO.md` §7.5 P21 bandı 32–48). Haftada iki ödev veren başka bir okulda
# aynı sabit hiç ateşlemezdi. Bir eşiğin okuldan okula anlam değiştirmesi,
# eşiğin yanlış eksende olduğunun kanıtıdır.
#
# **Yerine ne kondu.** Ölçü artık sayı değil **oran** (`missing_rate`) ve
# referansı öğrencinin **kendi şubesinin medyanı**. `MODULLER.md` §0 kural 2 ve
# `attendance.py`'nin `relative_gap`'i zaten bu ilkeyi uyguluyordu; ödev
# tetikleyicisi bu ilkenin dışında kalmış tek tetikleyiciydi.
#
# **Çarpan neden 2,0.** Eşik "kohort medyanının iki katı eksik oran"dır; mutlak
# bir puan değil, katsayıdır — okul değişince birlikte kayar. Değer altın küme
# üzerinde taranarak doğrulandı: 1,75 / 2,00 / 2,25 / 2,50 / 3,00 çarpanlarının
# **tamamı** P21 bandının (32–48) içinde kalıyor — liste sırasıyla 46, 46, 44,
# 44, 44 kişi; A5 yanlış pozitifi hepsinde 0, A6 yakalaması hepsinde ≥ 20.
# (1,5'te liste 57'ye çıkıp bandı taşıyor, bant kenarı orada.) 2,0 bu geniş
# düzlüğün ortasında ve "iki katı" olarak tek cümlede açıklanabiliyor
# (`[T§6.3]` açıklanabilirlik zorunluluğu). Eşik sonucu güzelleştirmek için
# oynatılmadı; düzlüğün genişliği zaten oynatmayı gereksiz kılıyor.
MISSING_COHORT_FACTOR = 2.0

# Kohort kapısı — `marks.COHORT_MIN` / `attendance.COHORT_MIN` ile aynı sayı ve
# aynı gerekçe (`[L-6]`): 8 kişiden küçük kohortta göreli ölçü üretilmez ve
# **mutlak değere düşülmez**. Kohort yoksa ödev tetikleyicisi ateşlemez.
COHORT_MIN = 8

# Bir maddenin dayandığı kural türü. Kanıt objesine `rule_basis` olarak yazılır
# ve `_suppress_rising()` bunu okur.
BASIS_LEVEL = "level"  # "şu an kötü" — seviye ölçüsü
BASIS_CHANGE = "change"  # "kötüleşti" — değişim ölçüsü


def _has_history(submission_profile: dict[str, Any]) -> bool:
    """Öğrencinin işaretlenebilmesi için asgari geçmiş."""
    overall = submission_profile.get("overall") or {}
    return int(overall.get("n") or 0) >= MIN_HISTORY_ITEMS


def _cold_start(now_ms: int, term_start_ms: int | None) -> bool:
    if term_start_ms is None:
        # Dönem başlangıcı bilinmiyorsa **fail-closed**: ürün kapalı.
        # (RAG'in `subject_map.py:98-108` fail-closed deseni, `[T§4 Ş13]`.)
        return True
    return (now_ms - term_start_ms) < COLD_START_WEEKS * clock.WEEK_MS


def _attendance_item(
    student: str,
    profile: dict[str, Any],
    bounds: tuple[int, int],
) -> AttentionItem | None:
    """Tetikleyici 1 — devamsızlık.

    `MODULLER.md` §2.8 tablosu: `rate < 0,80` **ve** kohort medyanına göre
    `relative_gap <= −0,10`. İkinci koşul olmadan grip haftası (tohumda
    devamsızlık normalin 2,40 katı) onlarca yanlış pozitif üretir — `[N§7.5]`
    P26 bu sayının **sıfır** olmasını istiyor.

    ⚠️ `MODULLER.md` göreli ölçüyü iki pencerenin **düşüş farkı** üzerine
    kuruyor; bizde zaman ekseni olmadığı için **seviye farkı** kullanılıyor
    (bkz. `attendance.py` başlığı). Olgu cümlesi bunu söyler.
    """
    overall = profile.get("overall") or {}
    rate = overall.get("rate")
    gap = overall.get("relative_gap")
    if rate is None or gap is None:
        return None
    if not (
        rate < attendance_mod.ATTENTION_RATE
        and gap <= attendance_mod.ATTENTION_RELATIVE_GAP
    ):
        return None
    return AttentionItem(
        student=student,
        trigger=TriggerKind.ATTENDANCE,
        fact=(
            f"Derslere katılım oranı %{rate * 100:.0f}; aynı şubedeki "
            f"arkadaşlarının ortancasından {abs(gap) * 100:.0f} puan düşük."
        ),
        evidence={
            "rate": rate,
            "relative_gap": gap,
            "n_obs": overall.get("n_obs"),
            "rule_basis": BASIS_LEVEL,
            "measure": "level_vs_cohort_median",
            "limitation": "Dönem kümülatifi; son 30 gün penceresi yok.",
        },
        window_from=bounds[0],
        window_to=bounds[1],
    )


def submission_cohort_medians(
    per_student: dict[str, tuple[list[str], dict[str, Any]]],
) -> dict[str, float]:
    """Şube başına **medyan eksik ödev oranı** (son 30 gün).

    `per_student`: `{student_id: (class_ids, submission_profile)}` — aynı
    biçim `marks.collect_cohort_samples()` ve
    `attendance.collect_cohort_samples()` ile tutarlıdır; çağıran taraf
    (pipeline / ölçüm betiği) tek geçişte doldurur.

    Kova anahtarı **yalnız şube**dir, şube × ders değil: eksik ödev oranı
    öğrencinin bütün derslerinden gelen tek bir davranış ölçüsüdür ve ders
    başına kırıldığında payda 5 gözlem kapısının
    (`submission.MIN_OBSERVATIONS`) altına düşüyor.

    `COHORT_MIN` altındaki şubeler dönmez — üst kırılıma (okul geneli havuz)
    **çıkılmaz** (`[L-6]`, `MODULLER.md` §0 kural 2).
    """
    buckets: dict[str, list[float]] = {}
    for class_ids, profile in per_student.values():
        recent = (profile or {}).get("recent_30d") or {}
        missing_rate = recent.get("missing_rate")
        if missing_rate is None:
            continue
        for class_id in class_ids:
            buckets.setdefault(str(class_id), []).append(float(missing_rate))
    out: dict[str, float] = {}
    for class_id, values in buckets.items():
        if len(values) < COHORT_MIN:
            continue
        median = stat.median(values)
        if median is not None:
            out[class_id] = median
    return out


def _cohort_missing_median(
    class_ids: list[str],
    cohort: dict[str, float] | None,
) -> float | None:
    """Öğrencinin şube(ler)inin medyan eksik oranı; kohort yoksa `None`."""
    if not cohort or not class_ids:
        return None
    values = [cohort[str(c)] for c in class_ids if str(c) in cohort]
    return stat.median(values) if values else None


def _is_improving(
    recent: dict[str, Any],
    previous: dict[str, Any],
) -> bool:
    """**Koruyucu değişim kuralı**: öğrenci iyiye mi gidiyor?

    İki işaretten biri yeterlidir, çünkü ikisi aynı şeyi farklı yönden söyler:
      * eksik ödev oranı önceki 30 güne göre **düştü**, ya da
      * zamanında teslim oranı önceki 30 güne göre **yükseldi**.

    Önceki pencere yoksa "iyileşiyor" denemez — bilinmeyen bir değişimden
    koruma türetmek, bilinmeyen bir değişimden suçlama türetmek kadar
    yanlıştır.
    """
    missing_now = recent.get("missing_rate")
    missing_was = previous.get("missing_rate")
    if (
        missing_now is not None
        and missing_was is not None
        and missing_now < missing_was
    ):
        return True
    on_time_now = recent.get("on_time_rate_by_last_touch")
    on_time_was = previous.get("on_time_rate_by_last_touch")
    if (
        on_time_now is not None
        and on_time_was is not None
        and on_time_now > on_time_was
    ):
        return True
    return False


def _homework_item(
    student: str,
    profile: dict[str, Any],
    bounds: tuple[int, int],
    cohort_median: float | None,
) -> AttentionItem | None:
    """Tetikleyici 2 — ödev. **Kohort-göreli seviye VE koruyucu değişim.**

    `MODULLER.md` §2.8 tablosu iki kuralı `VEYA` ile bağlıyordu: "son 30 günde
    `missing >= 3`" (**seviye**) **veya** "zamanında teslim oranı %60'tan
    %50'nin altına düştü" (**değişim**). Ölçüm bu bağlacın kendisini kusur
    olarak gösterdi (K2): `VEYA` altında değişim kuralının hiçbir koruyucu
    etkisi kalmıyor, çünkü seviye kuralı zaten neredeyse herkeste ateşliyor.
    Yükselen arketip A5'in 25 öğrencisinden 20'si listeye tam olarak bu yoldan
    giriyordu — teslim oranları **iyileşirken**.

    Yeni mantık — iki kapı, `VEYA` değil `VE`:

        ateşler  ⇔  ¬iyileşiyor  ∧  ( kohort-göreli seviye  ∨  kötüleşme )

    1. **Koruyucu kapı (dıştaki VE).** Öğrenci iyiye gidiyorsa
       (`_is_improving`) ödev maddesi **hiç** üretilmez. Değişim kuralı artık
       ikinci bir suçlama yolu değil, birinci yolun **önündeki filtre**.
    2. **İçeride kalan iki yolun ikisi de kohort-göreli**, ikisi de mutlak
       sayı kullanmaz:
         * *kronik yol*: eksik oran ≥ `MISSING_COHORT_FACTOR` × şube medyanı.
           "Şubesinin iki katı ödevini teslim etmemiş."
         * *kötüleşme yolu*: §2.8'in değişim kuralı (%60 → %50 altı) **artı**
           eksik oranın en az şube medyanı kadar olması. Kötüleşme tek başına
           yeterli sayılmaz; şubesinden hâlâ iyi durumdaki bir öğrenci
           listelenmez. Bar burada 1,0× medyandır (2,0× değil), çünkü
           kötüleşmenin kendisi ikinci bir kanıttır.

    Kohort bilinmiyorsa (küçük şube, ya da çağıran taraf kohort vermediyse)
    madde **üretilmez** — mutlak eşiğe düşmek tam olarak düzeltilen kusurdur.
    """
    recent = profile.get("recent_30d") or {}
    previous = profile.get("previous_30d") or {}
    missing_rate = recent.get("missing_rate")
    if missing_rate is None or cohort_median is None:
        return None
    if _is_improving(recent, previous):
        return None

    rate_now = recent.get("on_time_rate_by_last_touch")
    rate_was = previous.get("on_time_rate_by_last_touch")
    worsened = (
        rate_was is not None
        and rate_now is not None
        and rate_was >= submission_mod.ON_TIME_WAS
        and rate_now < submission_mod.ON_TIME_NOW
        and missing_rate >= cohort_median
    )
    chronic = missing_rate >= MISSING_COHORT_FACTOR * cohort_median

    if worsened:
        basis = BASIS_CHANGE
        fact = (
            f"Zamanında teslim oranı önceki 30 günde %{rate_was * 100:.0f} iken "
            f"son 30 günde %{rate_now * 100:.0f}; eksik ödev oranı "
            f"%{missing_rate * 100:.0f}, şube ortancası "
            f"%{cohort_median * 100:.0f}."
        )
    elif chronic:
        basis = BASIS_LEVEL
        fact = (
            f"Son 30 günde verilen ödevlerin %{missing_rate * 100:.0f} kadarı "
            f"teslim edilmedi; aynı şubenin ortancası "
            f"%{cohort_median * 100:.0f}."
        )
    else:
        return None

    return AttentionItem(
        student=student,
        trigger=TriggerKind.HOMEWORK,
        fact=fact,
        evidence={
            "n_missing_30d": recent.get("n_missing"),
            "missing_rate_30d": missing_rate,
            "cohort_missing_rate_median": cohort_median,
            "cohort_factor": MISSING_COHORT_FACTOR,
            "on_time_rate_30d": rate_now,
            "on_time_rate_prev_30d": rate_was,
            "missing_rate_prev_30d": previous.get("missing_rate"),
            "n_30d": recent.get("n"),
            "n_prev_30d": previous.get("n"),
            "rule_basis": basis,
            "measure": "missing_rate_vs_cohort_median",
            "limitation": (
                "Eşik mutlak değil kohort-görelidir: referans öğrencinin kendi "
                "şubesinin medyan eksik ödev oranıdır. Zamanında teslim ölçüsü "
                "son dokunuş zamanına dayanır; dondurulmuş counted_on_time "
                "alanı köprüde yok."
            ),
        },
        window_from=bounds[0],
        window_to=bounds[1],
    )


def _mark_trend_items(
    student: str,
    marks_profile: dict[str, Any],
    bounds: tuple[int, int],
) -> list[AttentionItem]:
    """Tetikleyici 3 — not eğilimi.

    `MODULLER.md` §2.8 tablosu: aynı derste son 3 oturum ortalaması, önceki
    3'ten **≥ 15 puan** düşük. Zaman çapası sınav kimliğinin ULID damgasıdır
    (bkz. `marks._ordered_marks`).
    """
    items: list[AttentionItem] = []
    for course_id, cstat in (marks_profile.get("courses") or {}).items():
        trend = cstat.get("trend") or {}
        if not trend.get("available") or not trend.get("dropped"):
            continue
        items.append(
            AttentionItem(
                student=student,
                trigger=TriggerKind.MARK_TREND,
                fact=(
                    f"{cstat.get('course_title') or course_id} dersinde son 3 not "
                    f"ortalaması {trend['recent_mean']:.0f}; önceki 3 notun "
                    f"ortalaması {trend['previous_mean']:.0f}."
                ),
                evidence={
                    "course": course_id,
                    "recent_mean": trend["recent_mean"],
                    "previous_mean": trend["previous_mean"],
                    "delta": trend["delta"],
                    "n_marks": trend["n"],
                    "rule_basis": BASIS_CHANGE,
                    "time_anchor": "exam_ulid_created_at",
                    "limitation": (
                        "Sıralama sınavın oluşturulma anına göredir; "
                        "öğrencinin sınava girme anı bilinmiyor."
                    ),
                },
                window_from=bounds[0],
                window_to=bounds[1],
            )
        )
    return items


def unavailable_triggers() -> dict[str, str]:
    """Bu sürümde **hiç ateşlenemeyen** tetikleyiciler ve sebepleri.

    Yarım bir liste sessizce gösterilmez: eksik listeden "bu öğrenci iyi
    durumda" çıkarımı yapılır ki bu yanlış negatiftir (`MODULLER.md` §2.8 hata
    davranışı). Bu sözlük çıktıyla birlikte taşınır ve UI'da yazılır.
    """
    return {
        TriggerKind.EXAM_MISSED.value: (
            "Sınav takvimi ve exam_attempt kaydı Source arayüzünde yok; "
            "'penceresi kapanmış sınava hiç girilmedi' tespiti yapılamıyor."
        )
    }


def is_rising(marks_profile: dict[str, Any]) -> bool:
    """Öğrenci **genelinde** yükselen eğilimde mi?

    `marks.course_trend()` artık ders başına `rising` üretiyor (kusur K6).
    Burada ders düzeyindeki sınıf öğrenci düzeyine toplanır; kural üç parçalı:

      * eğilim hesaplanabilen en az bir ders olmalı (aksi halde `False` —
        bilinmeyen eğilimden koruma türetilmez);
      * **hiçbir** derste `dropped` olmamalı — bir derste 15 puan düşerken
        "bu öğrenci yükseliyor" denemez;
      * derslerin **çoğunluğu** (yarıdan fazlası) `rising` olmalı. "Herhangi
        bir dersi yükseliyor" çok gevşek: altın kümede 250 öğrencinin 96'sını
        yükselen sayıyor (kesinlik 0,24). Çoğunluk kuralı 24 kişi buluyor ve
        bunların 19'u gerçekten A5 (kesinlik 0,79 / duyarlılık 0,76).
    """
    trends = [
        c.get("trend") or {}
        for c in (marks_profile.get("courses") or {}).values()
    ]
    usable = [t for t in trends if t.get("available")]
    if not usable:
        return False
    if any(t.get("dropped") for t in usable):
        return False
    rising = sum(1 for t in usable if t.get("rising"))
    return rising * 2 > len(usable)


def _suppress_rising(
    items: list[AttentionItem],
    marks_profile: dict[str, Any],
) -> list[AttentionItem]:
    """A5 koruması: yükselen öğrenci **tek bir seviye maddesiyle** listelenmez.

    `MODULLER.md` §2.8'in ruhu "bir şey değişti, bak" demektir; "şu an kötü"
    ise ancak başka bir kanıtla birlikte anlam taşır. Bu yüzden koruma dar
    tutuldu ve üç koşulu birden ister:

      1. üretilen madde sayısı **tam olarak bir** — iki bağımsız tetikleyici
         ateşlediyse bu artık tek bir eşiğin gürültüsü değildir;
      2. o tek maddenin dayanağı **seviye** (`rule_basis == BASIS_LEVEL`) —
         bir *değişim* maddesi (not düşüşü, teslim çöküşü) asla bastırılmaz;
      3. öğrencinin not eğilimi `is_rising()` ile yükselen.

    Koruma **liste büyüklüğü için** konmadı: ölçümde kohort-göreli eşikle A5
    yanlış pozitifi bu kapı olmadan da 0'a iniyor (48 kişilik listede A5 = 0);
    kapı onu 0'da **yapısal olarak** tutar. Altın kümede toplam 2 öğrenciyi
    bastırıyor (1 A1, 1 A7) ve liste 48 → 46 oluyor.
    """
    if len(items) != 1:
        return items
    if items[0].evidence.get("rule_basis") != BASIS_LEVEL:
        return items
    if not is_rising(marks_profile):
        return items
    return []


def evaluate(
    student: str,
    *,
    attendance_profile: dict[str, Any],
    submission_profile: dict[str, Any],
    marks_profile: dict[str, Any],
    now_ms: int,
    term_start_ms: int | None,
    submission_cohort: dict[str, float] | None = None,
) -> list[AttentionItem]:
    """Bir öğrenci için dikkat maddelerini üretir.

    **Tek bir skor döndürmez.** Dönen liste, her biri kendi kanıtını taşıyan
    bağımsız maddelerden oluşur; boş liste "sorun yok" demek DEĞİLDİR —
    `unavailable_triggers()` neyin ölçülemediğini söyler.

    `submission_cohort` — `submission_cohort_medians()` çıktısı, şube → medyan
    eksik ödev oranı. **Verilmezse ödev tetikleyicisi hiç ateşlemez** (bkz.
    `_homework_item`). Bu bilinçli bir fail-closed'dır: kohortu bilinmeyen bir
    okulda mutlak bir eşiğe düşmek, düzeltilen kusurun ta kendisidir. Çağıran
    taraf kohortu tek geçişte kurabilir; şube kimlikleri `marks_profile`
    içindeki `classes` alanından okunur.
    """
    if _cold_start(now_ms, term_start_ms):
        return []
    if not _has_history(submission_profile):
        return []

    bounds = clock.window(now_ms, WINDOW_DAYS)
    class_ids = [str(c) for c in (marks_profile.get("classes") or [])]
    cohort_median = _cohort_missing_median(class_ids, submission_cohort)

    items: list[AttentionItem] = []
    item = _attendance_item(student, attendance_profile, bounds)
    if item:
        items.append(item)
    item = _homework_item(student, submission_profile, bounds, cohort_median)
    if item:
        items.append(item)
    items.extend(_mark_trend_items(student, marks_profile, bounds))
    return _suppress_rising(items, marks_profile)


def order_items(items: list[AttentionItem]) -> list[AttentionItem]:
    """Listeyi **alfabetik** sıraya koyar — şiddete/skora göre DEĞİL.

    `[T§6.6]` madde 2: sıralama damgalama doğurur. Sabit alfabetik sıra, bir
    maddenin diğerinden "daha acil" olduğu izlenimini yapısal olarak engeller.
    """
    return sorted(items, key=lambda i: (i.student, i.trigger.value))


def expires_at(now_ms: int) -> int:
    """Maddenin düşme anı: `now + 30 gün` (`[T§6.6]` madde 5)."""
    return now_ms + EXPIRY_DAYS * clock.DAY_MS
