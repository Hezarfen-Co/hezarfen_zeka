"""Çalışma oturumu deseni: hacim, düzenlilik, kendi geçmişiyle karşılaştırma.

Kaynak: `spec/MODULLER.md` §2.6 `insight::study`, `[T§3 Ö3]`.

**Üç kural bu modülde tip düzeyinde uygulanır:**

1. **Ders bağı YOK ve iddia edilmez.** `[S]` `pomodoro_session.fields` =
   `user, started_at, finished_at, counted`; `course` alanı yok. Ürün metni
   "Matematiğe 4 saat çalıştın" **diyemez**. `MODULLER.md` §2.6 adım 6 bunu bir
   metin kuralı değil **DTO kuralı** yapıyor: bu modülün çıktı sözlüğünde
   `course` anahtarı **bulunmaz**.
2. **Sayaçlar okunmaz, ham log okunur.** `user.pomodoro_finished_total` ve
   `study_streak_current` `Source.profile()` → `stats` içinde mevcut ama
   **kullanılmaz**: `[M]` K1 tohumda **230 kullanıcıda kasıtlı sayaç şişmesi**
   olduğunu, `[S]` `day_numbers` ise serinin **UTC gününden** türetildiğini ve
   TR gecesinde kaydığını söylüyor (`[T§1.3]` kural 3).
3. **Akranla kıyaslanmaz, değer yargısı üretilmez.** Bu modülün çıktısında
   kohort, z-skoru veya bant **yoktur**; yalnız öğrencinin kendi geçmişi.

**Bu sürümde üretilemeyen:** sınav öncesi yığılma (`MODULLER.md` §2.6 adım 5).
`Source` arayüzünde sınav takvimi yok — `exam.starts_at` erişilemiyor. Yerine
**ödev teslim tarihi** öncesi yığılma hesaplanıyor; ayrı bir ölçüdür ve adı
(`pre_deadline_share`) bunu söyler. Sınavla karıştırılmaması için ayrı anahtar.
"""

from __future__ import annotations

from typing import Any

from . import clock, stat

# `MODULLER.md` §2.6 çıktısı: 28 günlük pencere (`n_stints_28`, `active_days_28`).
WINDOW_DAYS = 28

# `MODULLER.md` §2.6 güven kapısı: ısı haritası için `n_stints >= 5`.
MIN_STINTS_FOR_HEATMAP = 5

# `MODULLER.md` §2.6 güven kapısı: düzenlilik ölçüsü için `active_days_28 >= 3`.
MIN_ACTIVE_DAYS = 3

# `MODULLER.md` §2.6 adım 4 `burstiness >= 3` bayrağı **KALDIRILDI** (kusur K5).
#
# Ölçü şudur: `max(gün başına oturum) / ortalama(gün başına oturum)`, yani
# **gün-arası** yığılma. Ama `SENARYO.md` §3.7'nin "düzensiz çalışan" (A4)
# arketipi **olay-öncesi** yığılmayla tanımlıdır ("stintlerinin %70'i sınavdan
# önceki 48 saatte"). Bu iki desen aynı sayıya düşmez ve ölçüm bunu doğruladı:
# 250 öğrencilik altın kümede A4'ün medyan `burstiness`'i 2,14, okul medyanı
# 2,18 — fark 0,04. `pre_deadline_share` ile de ayrılmıyor (A4 0,714 ↔ okul
# 0,700). Olay ekseni (sınav takvimi) `Source` arayüzünde olmadığı sürece
# "düzensiz çalışıyor" **ölçülemiyor**; ölçülemeyen şey bayrağa dönüşmez
# (`[T§3 Y1]`). Sayının kendisi (`burstiness`) betimleyici olarak kalır,
# yanında ne ölçmediğini söyleyen `burstiness_limitation` ile birlikte.

# Gece dilimi: `SENARYO.md` gece penceresini **22:00–02:00** diye tanımlıyor;
# eski `(0, 1, 2)` değeri bu pencerenin yalnız son üçte birini görüyordu
# (kusur K5b). Aralık yarı açıktır: [22:00, 02:00) → 22, 23, 00, 01.
# ⚠️ ÖLÇÜLDÜ, AYIRMIYOR: pencere düzeltildikten sonra da `night_share` medyanı
# A4 için 0,228, A2 için 0,250 — arketip ayrımı yok. Düzeltme **tanım
# doğruluğu** içindir, yeni bir ayırt etme gücü iddiası taşımaz.
NIGHT_HOURS = (22, 23, 0, 1)

# `MODULLER.md` §2.6 adım 5 ile aynı genişlik: son 48 saat.
PRE_DEADLINE_HOURS = 48


def normalize_rows(raw: Any) -> list[dict[str, Any]]:
    """`pomodoro()` çıktısını oturum listesine indirger."""
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = raw.get("items") or []
    return [r for r in raw if isinstance(r, dict)]


def countable(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sayılan oturumlar.

    `MODULLER.md` §2.6 adım 1: `counted` alanı canlı kuralın sonucudur
    (`>= 300000 ms` ve günde en çok 16) ve modül onu **olduğu gibi** okur,
    kendi eşiğini uydurmaz.
    §2.6 hata davranışı: `finished_at` NONE (açık/terk edilmiş oturum, tohumda
    %5,84 — `[M]` D16) hem süreden hem sayımdan **düşülür**; `open_` önekli
    satır canlı bir oturumdur, veri değil.
    """
    out = []
    for r in rows:
        if r.get("finished_at") is None:
            continue
        if r.get("counted") is not True:
            continue
        out.append(r)
    return out


def duration_ms(row: dict[str, Any]) -> int:
    """Oturum süresi; negatif süreye karşı savunmacı `max(0, …)`."""
    d = row.get("duration_ms")
    if d is None:
        started = row.get("started_at")
        finished = row.get("finished_at")
        if started is None or finished is None:
            return 0
        d = int(finished) - int(started)
    return max(0, int(d))


def heatmap(rows: list[dict[str, Any]]) -> list[list[int]]:
    """TR haftagünü × TR saat ısı haritası, 7×24.

    `MODULLER.md` §2.6 adım 2: yerel saat düzeltmesi **zorunlu**. Aksi halde
    TR 00:00–03:00 çalışması önceki güne düşer — tohumda her 13 oturumdan biri.
    """
    grid = [[0] * 24 for _ in range(7)]
    for r in rows:
        started = r.get("started_at")
        if started is None:
            continue
        grid[clock.tr_weekday(int(started))][clock.tr_hour(int(started))] += 1
    return grid


def _daily_counts(rows: list[dict[str, Any]]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for r in rows:
        started = r.get("started_at")
        if started is None:
            continue
        day = clock.tr_day(int(started))
        counts[day] = counts.get(day, 0) + 1
    return counts


def local_streak(rows: list[dict[str, Any]], now_ms: int) -> int:
    """TR gününe göre yeniden hesaplanan seri.

    `MODULLER.md` §2.6 adım 3: `user.study_streak_current` **okunmaz**, çünkü
    UTC gününden türetilmiştir ve TR gecesinde kayar. Bu, ürünün gösterdiği
    seri ile profil ekranındaki rozet sayacının farklı sayı göstermesine yol
    açar — `[T§8.1 R10]`'un kabul ettiği görünür tutarsızlık. Ürün metninde
    "yerel güne göre" notu zorunludur.
    """
    days = set(_daily_counts(rows))
    if not days:
        return 0
    today = clock.tr_day(now_ms)
    # Bugün henüz çalışılmamış olabilir; seri dünden de sayılabilir.
    cursor = today if today in days else today - 1
    if cursor not in days:
        return 0
    streak = 0
    while cursor in days:
        streak += 1
        cursor -= 1
    return streak


def _window_stats(rows: list[dict[str, Any]], days: int) -> dict[str, Any]:
    daily = _daily_counts(rows)
    n_stints = len(rows)
    active_days = len(daily)
    durations = [float(duration_ms(r)) for r in rows]
    counts = list(daily.values())
    mean_daily = stat.mean([float(c) for c in counts])
    burstiness = None
    if mean_daily and mean_daily > 0:
        burstiness = max(counts) / mean_daily
    night = sum(
        1
        for r in rows
        if r.get("started_at") is not None
        and clock.tr_hour(int(r["started_at"])) in NIGHT_HOURS
    )
    return {
        "n_stints": n_stints,
        "active_days": active_days,
        "total_focus_ms": int(sum(durations)),
        "median_stint_ms": stat.median(durations),
        # `MODULLER.md` §2.6 adım 4: "28 günün 12'sinde çalıştın" — anlatılabilir
        # bir ölçü. Kapı altında `None`.
        "regularity": (active_days / days) if active_days >= MIN_ACTIVE_DAYS else None,
        "regularity_suppressed": active_days < MIN_ACTIVE_DAYS,
        "burstiness": burstiness,
        # Bayrak yok — bkz. `NIGHT_HOURS` üstündeki K5 notu. Sayı betimleyici.
        "burstiness_limitation": (
            "Gün-arası yığılmayı ölçer; sınav/ödev öncesi yığılmayı ÖLÇMEZ. "
            "Olay ekseni Source arayüzünde yok, bu yüzden 'düzensiz çalışıyor' "
            "yargısı bu sayıdan kurulamaz."
        ),
        "night_share": stat.rate(night, n_stints),
        "night_window_tr": "[22:00, 02:00)",
    }


def pre_deadline_share(
    rows: list[dict[str, Any]],
    due_ats: list[int],
    hours: int = PRE_DEADLINE_HOURS,
) -> float | None:
    """Oturumların, bir ödev teslim tarihinden önceki `hours` saate düşen payı.

    ⚠️ Bu, `MODULLER.md` §2.6 adım 5'teki **sınav öncesi** yığılma DEĞİLDİR.
    `Source` arayüzünde sınav takvimi yok. Ölçü betimleyicidir, tetikleyici
    değildir — hiçbir dikkat maddesi buna bağlanmaz.
    """
    if not rows or not due_ats:
        return None
    span = hours * 3_600_000
    windows = sorted((int(d) - span, int(d)) for d in due_ats)
    hits = 0
    for r in rows:
        started = r.get("started_at")
        if started is None:
            continue
        s = int(started)
        if any(lo <= s < hi for lo, hi in windows):
            hits += 1
    return stat.rate(hits, len(rows))


def student_profile(
    raw_pomodoro: Any,
    now_ms: int,
    due_ats: list[int] | None = None,
) -> dict[str, Any]:
    """Bir öğrencinin çalışma profili: son 28 gün + önceki 28 günle kıyas."""
    rows = countable(normalize_rows(raw_pomodoro))
    recent_bounds = clock.window(now_ms, WINDOW_DAYS)
    previous_bounds = clock.previous_window(now_ms, WINDOW_DAYS)

    def scoped(bounds: tuple[int, int]) -> list[dict[str, Any]]:
        return [
            r
            for r in rows
            if r.get("started_at") is not None
            and clock.in_window(int(r["started_at"]), bounds)
        ]

    recent_rows = scoped(recent_bounds)
    previous_rows = scoped(previous_bounds)
    recent = _window_stats(recent_rows, WINDOW_DAYS)
    previous = _window_stats(previous_rows, WINDOW_DAYS)

    show_heatmap = recent["n_stints"] >= MIN_STINTS_FOR_HEATMAP
    return {
        "recent_28d": recent,
        "previous_28d": previous,
        "change": {
            "active_days_delta": recent["active_days"] - previous["active_days"],
            "stints_delta": recent["n_stints"] - previous["n_stints"],
            "focus_ms_delta": recent["total_focus_ms"] - previous["total_focus_ms"],
        },
        "streak_local": local_streak(rows, now_ms),
        # Güven kapısı: 5 oturumun altında harita **yok**
        # ("3 çalışma seansı daha yap, düzenini görelim" — `[T§3 Ö3]`).
        "heatmap": heatmap(recent_rows) if show_heatmap else None,
        "heatmap_progress": None
        if show_heatmap
        else f"{recent['n_stints']}/{MIN_STINTS_FOR_HEATMAP}",
        "pre_deadline_share": pre_deadline_share(recent_rows, due_ats or []),
        # `MODULLER.md` §2.6 adım 5 — bu sürümde üretilemez.
        "pre_exam_share": None,
        "pre_exam_reason": (
            "Sınav takvimi Source arayüzünde yok; sınav öncesi yığılma "
            "hesaplanamaz. pre_deadline_share ödev teslim tarihine göredir."
        ),
        "limitation": (
            "Çalışma oturumlarının ders bağı yoktur; hangi derse çalışıldığı "
            "bilinmiyor. Gün/saat deseni yerel (TR) güne göre hesaplanır, bu "
            "yüzden profil ekranındaki rozet sayacından farklı olabilir."
        ),
    }
