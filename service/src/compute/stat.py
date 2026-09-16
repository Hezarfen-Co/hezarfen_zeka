"""Saf istatistik ilkelleri — hiçbir veri kaynağı, hiçbir yan etki.

Kaynak: `spec/MODULLER.md` §2.0 `insight::stat` künyesi.
Bu modül `Source`'u, veritabanını, ağı **görmez**; yalnız sayı listesi alır.

`MODULLER.md` §2.0'daki `discrimination_27` ve `point_biserial` fonksiyonları
bu sürümde **yoktur**: ham sınav cevapları köprü izin listesinde bulunmadığı için
madde analizi yapılamıyor (bkz. `compute/README.md` → "Bu sürümde yapılamayanlar").
Var olmayan bir veriyi hesaplayan ölü kod yazmıyoruz.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

# `MODULLER.md` §2.0: z hesabında σ tabanı 0,05.
# Gerekçe: sıfıra yakın σ'da z patlamasın; homojen bir şubede 1 puanlık fark
# "çok güçlü" görünmesin. Belge bunu açıkça bir **mühendislik kararı** olarak
# işaretliyor, literatürden gelmiyor (doğrulanmadı).
SD_FLOOR = 0.05

# Wilson aralığı için %95 z katsayısı (`MODULLER.md` §2.0 formülü).
WILSON_Z = 1.96


def mean(values: Sequence[float]) -> float | None:
    """Aritmetik ortalama. Boş dizide `None` — 0 değil (0 bir ölçümdür, yokluk değil)."""
    if not values:
        return None
    return sum(values) / len(values)


def median(values: Sequence[float]) -> float | None:
    """Medyan. Çift sayıda gözlemde iki ortancanın ortalaması."""
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def stdev_pop(values: Sequence[float]) -> float | None:
    """Popülasyon standart sapması (n bölen).

    `MODULLER.md` §2.0 `mean_sd` ile aynı tanım: kohort **tam olarak gözlenen**
    gruptur, ondan örneklem çekmiyoruz; bu yüzden n−1 değil n.
    """
    if not values:
        return None
    mu = sum(values) / len(values)
    var = sum((v - mu) ** 2 for v in values) / len(values)
    return math.sqrt(var)


def mean_sd(values: Sequence[float]) -> tuple[float, float] | None:
    """(ortalama, popülasyon standart sapması) ikilisi."""
    mu = mean(values)
    if mu is None:
        return None
    sd = stdev_pop(values)
    assert sd is not None
    return (mu, sd)


def z_score(x: float, mu: float, sd: float, sd_floor: float = SD_FLOOR) -> float:
    """z = (x − μ) / max(σ, σ_taban).

    `MODULLER.md` §2.0: σ tabanı 0,05 (bkz. `SD_FLOOR`).
    """
    return (x - mu) / max(sd, sd_floor)


def wilson_interval(k: int, n: int, z: float = WILSON_Z) -> tuple[float, float] | None:
    """Wilson skor aralığı: (k + z²/2)/(n + z²) ± (z/(n+z²))·√(k·q + z²/4).

    `MODULLER.md` §2.0 formülünün birebir karşılığı; `q = n − k`.
    Küçük örneklemde normal yaklaşımın verdiği saçma aralıkları (negatif alt
    sınır gibi) üretmediği için tercih edildi.
    """
    if n <= 0 or k < 0 or k > n:
        return None
    q = n - k
    denom = n + z * z
    center = (k + z * z / 2.0) / denom
    spread = (z / denom) * math.sqrt(k * q / n + z * z / 4.0)
    return (max(0.0, center - spread), min(1.0, center + spread))


def trend_slope(points: Sequence[tuple[float, float]]) -> float | None:
    """Basit doğrusal regresyon eğimi (en küçük kareler).

    `points` = [(x, y), ...]. Dönen değer **birim x başına y değişimi**.
    En az 2 nokta ve x'te varyans gerekir; yoksa `None`.

    Neden regresyon, neden model değil: `MODULLER.md` §0 kural 1 — bu ölçekte
    eğitilmiş model gerekmiyor; eğilim doğrudan gözlenen bir eğimdir ve
    tek cümleyle açıklanabilir (`[T§6.3]` açıklanabilirlik zorunluluğu).
    """
    if len(points) < 2:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0.0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    return sxy / sxx


def rate(numerator: int, denominator: int) -> float | None:
    """Oran; payda 0 ise `None`.

    `MODULLER.md` §2.5 adım 1'deki "payda 0 ise None" sözleşmesi:
    "oran yok" ile "oran sıfır" **aynı şey değildir**.
    """
    if denominator <= 0:
        return None
    return numerator / denominator


def share_within(values: Sequence[float], lo: float, hi: float) -> float | None:
    """`[lo, hi)` aralığına düşen değerlerin payı. Boş dizide `None`."""
    if not values:
        return None
    hits = sum(1 for v in values if lo <= v < hi)
    return hits / len(values)
