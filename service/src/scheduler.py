"""Gece işi zamanlayıcısı — kendi takvimiyle koşar.

Kaynak: `spec/MODULLER.md` §2.12 `insight::scheduler`.

---------------------------------------------------------------------------
TETİKLEME NEDEN İÇERİDEN GELİYOR
---------------------------------------------------------------------------
ZEKA ayrı bir süreçtir ve backend ile arasındaki tek yol **köprüdür**;
köprüyü **ZEKA açar**, backend'e istek gönderir, cevabı alır. Ters yön yoktur:
backend'in ZEKA'ya ulaşacağı bir adresi, bir kuyruğu veya bir webhook'u
**yok** — ve olmaması bilinçli. Bir HTTP sunucusu açmak, tam da denetimde
risk olarak işaretlenen deseni (üretim imajında duran geliştirme sunucusu)
tekrarlamak olurdu.

Sonuç: "gece 03:00'te çalış" kararını **ZEKA kendi içinden** verir. Bu dosya o
karardır: `asyncio` tabanlı bir tik döngüsü, TR saatine göre bir pencere ve
okulları sırayla dolaşan bir tur.

---------------------------------------------------------------------------
Tasarım kararları (`MODULLER.md` §2.12)
---------------------------------------------------------------------------
* **Pencere 03:00–05:00 TR** (`[T§5.3]`). Tik 15 dakikada bir; pencere
  dışındaysa hiçbir şey yapılmaz.
* **Kaçan tik birikmez.** `asyncio.sleep` ile sabit aralık; bir tur uzun
  sürerse aradaki tikler atlanır, kuyruğa girmez (`MissedTickBehavior::Delay`
  muadili).
* **Okullar sıralı işlenir**, sabit sırada. Sabit sıra önemlidir: "hep son
  sıradaki okul bütçesiz kalır" durumu **görünür** olur; dönüşümlü sıra bunu
  gizlerdi. Tek istisna: geçen gece `partial` biten okullar **öne alınır**
  (`MODULLER.md` §3.4).
* **Günde bir kez.** Bir okul için o TR gününde koşu yapıldıysa tekrar
  yapılmaz.
* **Tek koşu güvencesi.** Süreç içi `asyncio.Lock`; tek süreç olduğu için
  yeterli. İkinci savunma `insight_run` satırının varlığıdır.
* **Bir okul düşerse diğerleri etkilenmez** — `catch` + `warn` + sonraki okul.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from typing import Any

from .compute import clock
from .pipeline import DEFAULT_BUDGET_MS, RunResult, run_school
from .store import Store

log = logging.getLogger(__name__)

# `[T§5.3]` gece penceresi, TR saati.
WINDOW_START_HOUR = 3
WINDOW_END_HOUR = 5

# Tik aralığı: 15 dakika (`MODULLER.md` §2.12 adım 2).
TICK_SECONDS = 15 * 60


def now_ms() -> int:
    """Duvar saati, unix milisaniye UTC."""
    return int(time.time() * 1000)


def in_window(ms: int) -> bool:
    """TR saatine göre gece penceresinde miyiz?"""
    return WINDOW_START_HOUR <= clock.tr_hour(ms) < WINDOW_END_HOUR


class Scheduler:
    """Okulları gece penceresinde sırayla dolaşan koşucu."""

    def __init__(
        self,
        source_factory: Callable[[str], Any],
        store: Store,
        schools: list[str],
        *,
        budget_ms: int = DEFAULT_BUDGET_MS,
        budgets: dict[str, int] | None = None,
        term_start_ms: int | None = None,
        clock_fn: Callable[[], int] = now_ms,
        monotonic_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        # Sabit sıra: slug alfabetik (`MODULLER.md` §2.12 adım 3).
        self._schools = sorted(schools)
        self._source_factory = source_factory
        self._store = store
        self._budget_ms = budget_ms
        # Okul başına bütçe. Bir okulun öğrenci sayısı çok farklıysa ortak
        # bütçe ya küçük okula savurgan ya büyük okula cimri davranır; bu
        # sözlük istisnayı **adıyla** yazmayı sağlar. Sözlükte olmayan okul
        # varsayılan bütçeyi kullanır.
        self._budgets = dict(budgets or {})
        self._term_start_ms = term_start_ms
        self._now = clock_fn
        self._monotonic = monotonic_fn
        self._lock = asyncio.Lock()
        # okul → en son koşulan TR tarihi (`YYYY-MM-DD`)
        self._last_run_day: dict[str, str] = {}
        # geçen gece `partial` biten okullar — bir sonraki turda öne alınır
        self._priority: list[str] = []
        # okul → bütçe yüzünden işlenemeyen öğrenciler. Bir sonraki koşu
        # bunları listenin başına alır (`MODULLER.md` §3.4).
        self._pending: dict[str, list[str]] = {}
        # Son turda düşen okullar — izolasyonun kanıtı testte buradan okunur.
        self._failures: list[str] = []

    def budget_for(self, school: str) -> int:
        """Bu okulun süre bütçesi (ms)."""
        return self._budgets.get(school, self._budget_ms)

    def pending_for(self, school: str) -> list[str]:
        """Bu okulda bir sonraki koşuya devredilen öğrenciler."""
        return list(self._pending.get(school, []))

    def _order(self) -> list[str]:
        """Sabit sıra + `partial` önceliği (`MODULLER.md` §2.12 adım 3 uyarısı)."""
        rest = [s for s in self._schools if s not in self._priority]
        return [s for s in self._priority if s in self._schools] + rest

    async def run_once(self, at_ms: int | None = None) -> list[RunResult]:
        """Bir tur: bugün henüz koşmamış tüm okullar, sırayla.

        Pencere kontrolü **yapmaz** — `--once` ile elle çalıştırmak ve testler
        için. Pencereyi `serve()` uygular.
        """
        stamp = at_ms if at_ms is not None else self._now()
        day = clock.tr_date_key(stamp)
        results: list[RunResult] = []
        self._failures = []
        async with self._lock:
            partial_now: list[str] = []
            for school in self._order():
                if self._last_run_day.get(school) == day:
                    continue
                # Süreç yeniden başladıysa bellek içi `pending` boştur;
                # devreden liste `insight_run` satırından okunur.
                if school not in self._pending:
                    carried = await self._store.last_pending(school)
                    if carried:
                        self._pending[school] = carried
                        log.info(
                            "önceki koşudan devralındı: okul=%s bekleyen=%d",
                            school,
                            len(carried),
                        )
                try:
                    source = self._source_factory(school)
                    result = await run_school(
                        source,
                        self._store,
                        school,
                        now_ms=stamp,
                        term_start_ms=self._term_start_ms,
                        budget_ms=self.budget_for(school),
                        resume_students=self._pending.get(school),
                        monotonic_fn=self._monotonic,
                    )
                except Exception as exc:  # noqa: BLE001 — okul izolasyonu
                    # Bir okulun düşmesi turu bitirmez: sıradaki okul koşar.
                    # `_last_run_day` GÜNCELLENMEZ, böylece aynı gece içinde
                    # yeni bir tik gelirse okul yeniden denenir.
                    log.warning("okul düştü, tur devam ediyor (%s): %s", school, exc)
                    self._failures.append(school)
                    continue
                self._last_run_day[school] = day
                results.append(result)
                # Bütçe aşan okul ertelenir: kalan öğrenciler saklanır.
                if result.pending_students:
                    self._pending[school] = list(result.pending_students)
                else:
                    self._pending.pop(school, None)
                if result.status == "partial":
                    partial_now.append(school)
                log.info(
                    "okul bitti: %s status=%s öğrenci=%d/%d satır=%d süre=%sms",
                    school,
                    result.status,
                    result.students_ok,
                    result.students_total,
                    result.rows_written,
                    result.duration_ms,
                )
            self._priority = partial_now
        return results

    async def serve(
        self,
        *,
        stop: asyncio.Event | None = None,
        tick_seconds: float = TICK_SECONDS,
        ignore_window: bool = False,
        max_ticks: int | None = None,
    ) -> int:
        """Tik döngüsü. Pencerede ve bugün koşmamışsa turu başlatır.

        **Test kipi** (`ignore_window=True`, küçük `tick_seconds`, `max_ticks`):
        gerçek gece penceresini ve 15 dakikalık tiki beklemeden tam çevrim
        koşturur. Üretim yolu varsayılanlarla aynıdır; test kipi ayrı bir kod
        yolu değil, aynı döngünün parametrelenmiş halidir — ayrı yol olsaydı
        test edilen şey üretimde koşan şey olmazdı.

        Döndürdüğü sayı: kaç tik atıldı.
        """
        stop = stop or asyncio.Event()
        ticks = 0
        log.info(
            "zamanlayıcı açıldı: pencere %02d:00–%02d:00 TR, tik %ds, okul=%d",
            WINDOW_START_HOUR,
            WINDOW_END_HOUR,
            TICK_SECONDS,
            len(self._schools),
        )
        while not stop.is_set():
            stamp = self._now()
            if ignore_window or in_window(stamp):
                await self.run_once(stamp)
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                break
            # Kaçan tik birikmez: her turdan sonra sabit aralık beklenir.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=tick_seconds)
        log.info("zamanlayıcı kapandı (tik=%d)", ticks)
        return ticks

