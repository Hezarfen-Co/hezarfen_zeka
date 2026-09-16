"""Takvim yardımcıları: yerel saat -> unix-ms, öğretim haftaları, gün numarası.

Tüm zaman alanları `int` unix-ms'tir (E2). İki istisna — `user.study_streak_last_day`
ve `user.pomodoro_counted_day` — gün numarasıdır: floor(ms / 86400000) + 719163.

`--date-shift-days` tüm damgalara sabit eklenir; bu modüldeki her üretici fonksiyon
kaydırmayı kendisi uygular, böylece ULID zaman önekleri de kayar.
"""

from __future__ import annotations

import datetime as _dt

import config as C

_EPOCH = _dt.date(1970, 1, 1)

SHIFT_MS = 0
T_NOW = C.T_NOW_MS


def configure(shift_days: int) -> None:
    global SHIFT_MS, T_NOW
    SHIFT_MS = shift_days * C.DAY_MS
    T_NOW = C.T_NOW_MS + SHIFT_MS


def date_utc_midnight(d: _dt.date) -> int:
    """Takvim gününün UTC gece yarısı (kaydırmasız)."""
    return (d - _EPOCH).days * C.DAY_MS


def local_ms(d: _dt.date, minute: int) -> int:
    """Yerel (UTC+3) tarih + dakika -> kaydırılmış unix-ms."""
    return date_utc_midnight(d) - C.TZ_OFFSET_MS + minute * C.MIN_MS + SHIFT_MS


def shifted(ms: int) -> int:
    return int(ms) + SHIFT_MS


def day_number(ms: int) -> int:
    """E2: gün numarası = floor(unix_ms / 86400000) + 719163."""
    return ms // C.DAY_MS + C.DAY_NUMBER_EPOCH


def date_text(d: _dt.date) -> str:
    """menu.date — tam 10 karakter (E20). Kaydırma uygulanır."""
    return (d + _dt.timedelta(days=SHIFT_MS // C.DAY_MS)).isoformat()


# ---------------------------------------------------------------------------
# Okul takvimi
# ---------------------------------------------------------------------------

def _in_range(d: _dt.date, pair) -> bool:
    return pair[0] <= d <= pair[1]


def is_break(d: _dt.date) -> bool:
    return any(_in_range(d, b) for b in C.BREAKS)


def break_kind(d: _dt.date):
    """Pomodoro çarpanı için tatil türü."""
    if _in_range(d, C.BREAKS[1]):
        return "semester"
    if _in_range(d, C.BREAKS[0]) or _in_range(d, C.BREAKS[2]):
        return "short"
    if d in C.HOLIDAYS or d in C.FUTURE_HOLIDAYS:
        return "holiday"
    return None


def is_school_day(d: _dt.date) -> bool:
    """Ders yapılan gün: hafta içi, tatil haftası değil, resmi tatil değil."""
    if d.weekday() > 4:
        return False
    if d < C.T1_START or d > C.T2_END:
        return False
    if C.T1_END < d < C.T2_START:
        return False
    if is_break(d):
        return False
    if d in C.HOLIDAYS or d in C.FUTURE_HOLIDAYS:
        return False
    return True


def teaching_weeks(until: _dt.date | None = None):
    """Öğretim haftalarının Pazartesi tarihleri (tatil haftaları hariç)."""
    weeks = []
    for start, end in ((C.T1_START, C.T1_END), (C.T2_START, C.T2_END)):
        d = start
        while d <= end:
            if until is not None and d > until:
                break
            if not is_break(d):
                weeks.append(d)
            d += _dt.timedelta(days=7)
    return weeks


def past_teaching_weeks():
    """T_NOW'a kadar tamamlanmış öğretim haftaları (27 hafta)."""
    limit = _dt.date(2026, 4, 12)
    return teaching_weeks(until=limit)


def all_teaching_weeks():
    return teaching_weeks()


def school_days(start: _dt.date, end: _dt.date):
    out = []
    d = start
    while d <= end:
        if is_school_day(d):
            out.append(d)
        d += _dt.timedelta(days=1)
    return out


def past_school_days():
    return [d for d in school_days(C.T1_START, C.T2_END)
            if local_ms(d, C.BLOCK_MINUTES[0]) <= T_NOW]


def is_flu_week(d: _dt.date) -> bool:
    return _in_range(d, C.FLU_WEEK)


def near_break(d: _dt.date) -> float:
    """Tatilden önceki son / sonraki ilk iş günü çarpanı."""
    nxt = d + _dt.timedelta(days=1)
    while nxt.weekday() > 4:
        nxt += _dt.timedelta(days=1)
    prv = d - _dt.timedelta(days=1)
    while prv.weekday() > 4:
        prv -= _dt.timedelta(days=1)
    if is_break(nxt) or nxt in C.HOLIDAYS:
        return C.ABSENCE_BEFORE_BREAK_MULT
    if is_break(prv) or prv in C.HOLIDAYS:
        return C.ABSENCE_AFTER_BREAK_MULT
    return 1.0


_PROGRESS_DAYS = None


def progress(ms: int) -> float:
    """0 = 2025-09-08, 1 = T_NOW. Arketip zaman trendleri bunu kullanır."""
    global _PROGRESS_DAYS
    if _PROGRESS_DAYS is None:
        _PROGRESS_DAYS = past_school_days()
    start = local_ms(C.T1_START, 0)
    span = T_NOW - start
    if span <= 0:
        return 1.0
    value = (ms - start) / span
    return 0.0 if value < 0 else (1.0 if value > 1 else value)
