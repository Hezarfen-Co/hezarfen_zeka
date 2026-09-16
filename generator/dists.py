"""Dağılım yardımcıları — yalnız standart kütüphane (`random.Random`) kullanır."""

from __future__ import annotations

import math
import random


def clip(value, low, high):
    return low if value < low else (high if value > high else value)


def normal(rng: random.Random, mu: float, sigma: float) -> float:
    return rng.gauss(mu, sigma)


def clipped_normal(rng, mu, sigma, low, high) -> float:
    return clip(rng.gauss(mu, sigma), low, high)


def lognormal_median(rng: random.Random, median: float, sigma_log: float) -> float:
    """Medyanı verilen log-normal çekim."""
    return median * math.exp(rng.gauss(0.0, sigma_log))


def exponential(rng: random.Random, mean: float) -> float:
    return rng.expovariate(1.0 / mean) if mean > 0 else 0.0


def beta(rng: random.Random, a: float, b: float) -> float:
    return rng.betavariate(a, b)


def poisson(rng: random.Random, lam: float) -> int:
    """Knuth yöntemi; büyük lambda için normal yaklaşımı."""
    if lam <= 0:
        return 0
    if lam < 30:
        limit = math.exp(-lam)
        k = 0
        p = 1.0
        while True:
            p *= rng.random()
            if p <= limit:
                return k
            k += 1
            if k > 200:
                return k
    value = int(round(rng.gauss(lam, math.sqrt(lam))))
    return max(0, value)


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    ex = math.exp(x)
    return ex / (1.0 + ex)


def pick_weighted(rng: random.Random, pairs):
    """[(değer, ağırlık), ...] listesinden tek çekim."""
    total = sum(w for _, w in pairs)
    r = rng.random() * total
    acc = 0.0
    for value, weight in pairs:
        acc += weight
        if r <= acc:
            return value
    return pairs[-1][0]


def largest_remainder(total: int, weights):
    """Toplamı tam `total` olan tamsayı dağıtımı (en büyük kalan yöntemi)."""
    s = sum(weights)
    if s <= 0:
        return [0] * len(weights)
    raw = [total * w / s for w in weights]
    base = [int(x) for x in raw]
    rest = total - sum(base)
    order = sorted(range(len(weights)), key=lambda i: raw[i] - base[i], reverse=True)
    for i in range(rest):
        base[order[i % len(order)]] += 1
    return base


def take_share(rng: random.Random, items, share: float):
    """Listenin belirlenimci biçimde karıştırılmış `share` oranlık ön dilimi."""
    pool = list(items)
    rng.shuffle(pool)
    n = int(round(len(pool) * share))
    return pool[:n]
