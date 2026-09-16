"""Ödev teslim profili: teslim/geç/eksik oranları ve yaklaşan teslimler.

Kaynak: `spec/MODULLER.md` §2.4 `insight::submission`, `[T§3 Ö4]`.

---------------------------------------------------------------------------
İKİ CİDDİ VERİ SINIRI — ikisi de sahte sayıyla kapatılmadı
---------------------------------------------------------------------------

**1) `submitted_at` yok → erteleme profili hesaplanamaz.**
`MODULLER.md` §2.4 adım 2–3'ün tamamı `lead = due_at − submitted_at` üzerine
kurulu: medyan teslim payı, "son dakika" profili (`median_lead < 6 saat`),
hatırlatma zamanı (`remind_at = due_at − max(24sa, 2×|median_lead|)`) ve
son 24 saate yığılma oranı. Köprünün öğrenci ucu
(`GET /homework/report/{user}` → `HomeworkReportEntry`) şu alanları veriyor:
`course, homework, title, subject, due_at, submitted, late, missing, result`.
**`submitted_at` yok.** O alan yalnız öğretmen ucundaki
`HomeworkRosterSubmission` üzerinde var (`homework.rs:1067`) ve izin
listesinde değil. Dolayısıyla:
  * `median_lead_ms` → **üretilmez**
  * "son dakika" etiketi → **üretilmez**
  * son 24 saate yığılma oranı → **üretilmez**
  * `remind_at` → dinamik değil, **sabit 24 saat** kullanılır. Bu tam olarak
    `MODULLER.md` §2.4 güven kapısının "altında" kolonudur: "davranışsal yorum
    yok; sabit 24 saat öncesi hatırlatma".

**2) `counted_on_time` yok → geç teslim ölçüsü `late` üzerinden, yani
   `MODULLER.md` §2.4 adım 1'in AÇIKÇA YANLIŞ dediği alandan geliyor.**
`[S]` `homework_submission.counted_on_time`: "frozen bool — `submitted_at <=
due_at`, teslim anında bir kez karar verilir". `HomeworkReportEntry.late` ise
`homework.rs:1178` yorumuyla "teslim **en son** `due_at` sonrasında
dokunuldu mu". `MODULLER.md` §2.4: davranış analizi için doğru olan
birincisidir ve tohumda **1.025 satır** `counted_on_time = true` ama
`updated_at > due_at` (`[M]` D14) — bu satırlar `late` ile ölçüldüğünde
**yanlış tarafa düşer** ve A1 arketipinin %97'lik oranı aşağı iner.

Bu modül sayıyı yine de üretir (başka ölçü yok) ama:
  * alan adı `on_time_rate_by_last_touch` — adı ne ölçtüğünü söyler,
  * her çıktı `counted_on_time_available = False` bayrağı taşır,
  * kanıt objesine `measure = "last_touch"` yazılır; `[N§7.5]` A11/A12
    doğrulamaları bu bayrak açıkken **geçersizdir**.
"""

from __future__ import annotations

from typing import Any

from . import clock, stat

# `MODULLER.md` §2.4 güven kapısı: `n_submissions >= 5` altında oran
# gösterilmez, davranışsal yorum yapılmaz.
MIN_OBSERVATIONS = 5

# `MODULLER.md` §2.4 adım 3: erteleme profili yokken sabit 24 saat.
REMIND_LEAD_MS = 24 * 3_600_000

# `MODULLER.md` §2.4 adım 4 — yüksek öncelik rozeti eşiği.
HIGH_PRIORITY_ON_TIME = 0.60

# `MODULLER.md` §2.8 tetikleyici 2: son 30 günde `missing >= 3`.
MISSING_TRIGGER = 3

# `MODULLER.md` §2.8 tetikleyici 2: zamanında teslim oranı %60'tan %50'nin
# altına düştü.
ON_TIME_WAS = 0.60
ON_TIME_NOW = 0.50

# `MODULLER.md` §2.5 adım 2 ile aynı pencere genişliği.
WINDOW_DAYS = 30


def normalize_items(raw: Any) -> list[dict[str, Any]]:
    """`homework_report()` çıktısını satır listesine indirger.

    Uç bir sayfa zarfı döndürür (`Page<HomeworkReportEntry>`):
    `{items, total, limit, offset}`.
    """
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = raw.get("items") or []
    return [r for r in raw if isinstance(r, dict)]


def _tally(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Bir satır kümesinin sayımı. Oran kapısı burada uygulanmaz."""
    n = len(items)
    submitted = sum(1 for i in items if i.get("submitted"))
    late = sum(1 for i in items if i.get("submitted") and i.get("late"))
    missing = sum(1 for i in items if i.get("missing"))
    # Öğretmenin elle işaretlediği durum; `missing` bayrağından bağımsızdır
    # (`[S]` `homework_result.status` enum: done | incomplete | missing).
    marked_missing = sum(
        1
        for i in items
        if isinstance(i.get("result"), dict)
        and i["result"].get("status") == "missing"
    )
    on_time = submitted - late
    return {
        "n": n,
        "n_submitted": submitted,
        "n_on_time": on_time,
        "n_late": late,
        "n_missing": missing,
        "n_marked_missing": marked_missing,
        "on_time_rate_by_last_touch": stat.rate(on_time, submitted)
        if submitted >= MIN_OBSERVATIONS
        else None,
        "late_rate": stat.rate(late, submitted)
        if submitted >= MIN_OBSERVATIONS
        else None,
        "missing_rate": stat.rate(missing, n) if n >= MIN_OBSERVATIONS else None,
        "rates_suppressed": submitted < MIN_OBSERVATIONS,
    }


def window_tally(
    items: list[dict[str, Any]], bounds: tuple[int, int]
) -> dict[str, Any]:
    """Yalnız `due_at`'i pencereye düşen ödevlerin sayımı.

    Zaman ekseni `due_at`'tir; teslim anı değil (bkz. modül başlığı, sınır 1).
    """
    scoped = [
        i
        for i in items
        if i.get("due_at") is not None and clock.in_window(int(i["due_at"]), bounds)
    ]
    out = _tally(scoped)
    out["window_from"] = bounds[0]
    out["window_to"] = bounds[1]
    return out


def upcoming(
    homework_rows: Any,
    report_items: list[dict[str, Any]],
    now_ms: int,
    on_time_rate: float | None,
) -> list[dict[str, Any]]:
    """Yaklaşan teslimler + yüksek öncelik rozeti.

    Rozet kuralı (`MODULLER.md` §2.4 adım 4): teslim yok **ve**
    `now > due_at − 24 saat` **ve** `on_time_rate < 0,60`.
    Oran bilinmiyorsa (kapı altında) rozet **verilmez** — bilinmeyen bir
    davranıştan öncelik türetmek `[T§3 Ö4]`'ün suçlayıcı dil yasağına girer.
    """
    rows = homework_rows or []
    if isinstance(rows, dict):
        rows = rows.get("items") or []
    submitted_ids = {
        str(i.get("homework")) for i in report_items if i.get("submitted")
    }
    out: list[dict[str, Any]] = []
    for hw in rows:
        if not isinstance(hw, dict):
            continue
        due_at = hw.get("due_at")
        if due_at is None:
            continue
        due_at = int(due_at)
        if due_at <= now_ms:
            continue
        hw_id = str(hw.get("id") or "")
        already = hw_id in submitted_ids
        high_priority = (
            not already
            and now_ms > due_at - REMIND_LEAD_MS
            and on_time_rate is not None
            and on_time_rate < HIGH_PRIORITY_ON_TIME
        )
        out.append(
            {
                "homework": hw_id,
                "course": str(hw.get("course") or ""),
                "title": str(hw.get("title") or ""),
                "due_at": due_at,
                "hours_left": (due_at - now_ms) / 3_600_000,
                "submitted": already,
                "remind_at": due_at - REMIND_LEAD_MS,
                "high_priority": high_priority,
            }
        )
    out.sort(key=lambda r: r["due_at"])
    return out


def student_profile(
    raw_report: Any,
    raw_homework_list: Any,
    now_ms: int,
) -> dict[str, Any]:
    """Bir öğrencinin tam teslim profili."""
    items = normalize_items(raw_report)
    overall = _tally(items)
    recent = window_tally(items, clock.window(now_ms, WINDOW_DAYS))
    previous = window_tally(items, clock.previous_window(now_ms, WINDOW_DAYS))

    return {
        "overall": overall,
        "recent_30d": recent,
        "previous_30d": previous,
        "upcoming": upcoming(
            raw_homework_list,
            items,
            now_ms,
            overall.get("on_time_rate_by_last_touch"),
        ),
        # `MODULLER.md` §2.4 adım 2 — bu sürümde üretilemez (bkz. sınır 1).
        "procrastination": {
            "available": False,
            "reason": (
                "Erteleme profili submitted_at gerektirir; öğrenci ödev raporu "
                "teslim anını taşımıyor. median_lead, 'son dakika' etiketi ve "
                "son 24 saate yığılma oranı üretilmedi."
            ),
            "median_lead_ms": None,
            "last_minute": None,
            "last_24h_share": None,
        },
        # Ölçünün hangi alandan geldiğini taşıyan bayrak (bkz. sınır 2).
        "counted_on_time_available": False,
        "measure": "last_touch",
        "limitation": (
            "Zamanında teslim ölçüsü 'son dokunuş due_at'ten önce miydi' "
            "sorusuna dayanır; dondurulmuş counted_on_time alanı köprüde yok. "
            "Teslim saati bilinmediği için erteleme yorumu yapılmaz."
        ),
    }
