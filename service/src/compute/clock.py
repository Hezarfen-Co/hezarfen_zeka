"""UTC milisaniyeyi TR (UTC+3) gününe/saatine çeviren saf yardımcılar.

Kaynak: `spec/MODULLER.md` §2.0 `insight::clock` künyesi.

**Neden gerekli:** `[S]` `time_and_value_formats.timestamps` — tüm damgalar
`i64 unix MILLISECONDS, UTC` ve gün sınırı UTC gece yarısıdır. TR'de
00:00–03:00 arasında yapılan çalışma, UTC gününe göre **önceki güne** yazılır.
Tohumda bu dilimin payı %7,57 (`[M]` D17) — yani her 13 oturumdan biri yanlış
güne düşer (`MODULLER.md` §2.6 adım 2).

**Sabit ofset neden yeterli:** Türkiye 2016'dan beri kalıcı UTC+3, yaz saati
uygulaması yok (`MODULLER.md` §2.0: `(doğrulanmadı: mevzuat teyidi yapılmadı)`).
"""

from __future__ import annotations

import datetime as _dt

# `MODULLER.md` §2.0 sabiti.
TR_OFFSET_MS = 3 * 3_600_000

DAY_MS = 86_400_000
WEEK_MS = 7 * DAY_MS


def tr_day(ms: int) -> int:
    """TR yerel gününün gün numarası (unix epoch'tan itibaren tam gün)."""
    return (ms + TR_OFFSET_MS) // DAY_MS


def tr_hour(ms: int) -> int:
    """TR yerel saati, 0–23."""
    return int(((ms + TR_OFFSET_MS) % DAY_MS) // 3_600_000)


def tr_weekday(ms: int) -> int:
    """TR yerel haftagünü: 0 = Pazartesi … 6 = Pazar."""
    # 1970-01-01 bir Perşembe'dir (indeks 3).
    return int((tr_day(ms) + 3) % 7)


def tr_date_key(ms: int) -> str:
    """`YYYY-MM-DD` — `insight_run` kayıt anahtarının TR tarih bölümü.

    `MODULLER.md` §4.4: kayıt anahtarı TR tarihi, 10 karakter sabit.
    """
    local = _dt.datetime.fromtimestamp((ms + TR_OFFSET_MS) / 1000.0, tz=_dt.UTC)
    return local.strftime("%Y-%m-%d")


def tr_week_start(ms: int) -> int:
    """İçinde bulunulan TR haftasının Pazartesi 00:00'ının UTC-ms karşılığı."""
    day = tr_day(ms) - tr_weekday(ms)
    return day * DAY_MS - TR_OFFSET_MS


def window(now_ms: int, days: int) -> tuple[int, int]:
    """`[now − days, now)` penceresi, TR gün sınırına hizalı.

    `MODULLER.md` §2.5 adım 2 deseni: pencere sınırları TR gününe hizalanır,
    aksi halde "son 30 gün" okulun saatine göre kayar.
    """
    end_day = tr_day(now_ms) + 1  # bugünü tam kapsa
    start_day = end_day - days
    return (start_day * DAY_MS - TR_OFFSET_MS, end_day * DAY_MS - TR_OFFSET_MS)


def previous_window(now_ms: int, days: int) -> tuple[int, int]:
    """`[now − 2·days, now − days)` — karşılaştırma penceresi (`W0`)."""
    from_ms, _ = window(now_ms, days)
    return (from_ms - days * DAY_MS, from_ms)


def in_window(ms: int, bounds: tuple[int, int]) -> bool:
    """Yarı açık aralık kontrolü: `[from, to)`."""
    return bounds[0] <= ms < bounds[1]
