"""ULID üretimi, kompozit anahtarlar ve SurrealQL kimlik kaçışlaması.

Kurallar (schema.json -> id_syntax / id_rules):
  * Her ULID 26 karakter Crockford base32'dir; ilk 10 karakter zaman damgasını
    (ms) kodlar, kalan 16 karakter rastgeledir.
  * Kayıt kimliği KENDİ zaman damgasından türetilir; böylece `ORDER BY id` ile
    `ORDER BY created_at` aynı sırayı verir (arayüzdeki "en yeni önce" listeleri).
  * Aynı milisaniyede birden çok kayıt olabileceği için monotonluk garantisi vardır:
    aynı ms'te üretilen sonraki kimliğin rastgele kısmı bir artırılır.
  * SurrealQL'de kimlik daima `table:<U+27E8>key<U+27E9>` biçiminde yazılır; çıplak
    yazım ULID rakamla başladığı için ayrıştırılamaz.
"""

from __future__ import annotations

import hashlib
import random

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

LANGLE = "⟨"  # U+27E8 MATHEMATICAL LEFT ANGLE BRACKET
RANGLE = "⟩"  # U+27E9 MATHEMATICAL RIGHT ANGLE BRACKET


def _b32(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(out))


class UlidFactory:
    """Tablo başına bir örnek kullanılır; monotonluk tablo içinde garanti edilir."""

    __slots__ = ("_rng", "_last_ms", "_last_rand")

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng
        self._last_ms = -1
        self._last_rand = 0

    def make(self, ts_ms: int) -> str:
        ts_ms = int(ts_ms)
        if ts_ms < 0:
            ts_ms = 0
        if ts_ms == self._last_ms:
            # Aynı milisaniyede art arda üretim: rastgele kısım bir artırılır
            # (ULID monotonluk garantisi — domain/monotonic_id.rs).
            self._last_rand = (self._last_rand + 1) & ((1 << 80) - 1)
        else:
            # Zaman öneki DAİMA satırın kendi damgasından gelir; üretim sırası
            # kronolojik olmasa bile kimlikten okunan zaman doğru kalır.
            self._last_ms = ts_ms
            self._last_rand = self._rng.getrandbits(80)
        return _b32(self._last_ms, 10) + _b32(self._last_rand, 16)


def random_ulid(rng: random.Random, ts_ms: int) -> str:
    """Monotonluk gerekmeyen yerler için (ör. exam_question.choices[*].id — E21)."""
    return _b32(int(ts_ms), 10) + _b32(rng.getrandbits(80), 16)


def substream(seed: int, name: str, *parts) -> random.Random:
    """Tohumdan türetilmiş, alan başına bağımsız RNG.

    Bir alandaki değişikliğin diğer alanların çıktısını kaydırmamasını sağlar.
    """
    key = "%d|%s|%s" % (seed, name, "|".join(str(p) for p in parts))
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=16).digest()
    return random.Random(int.from_bytes(digest, "big"))


class Rid(str):
    """SurrealQL'e ham yazılacak kayıt kimliği (`table:<>key<>`)."""

    __slots__ = ("table", "key")

    def __new__(cls, table: str, key: str):
        obj = super().__new__(cls, "%s:%s%s%s" % (table, LANGLE, key, RANGLE))
        obj.table = table
        obj.key = key
        return obj


def rid(table: str, key: str) -> Rid:
    return Rid(table, key)


def seq_key(base: str, seq: int) -> str:
    """E3: seq==1 -> ek yok; seq>1 -> _{seq}."""
    return base if seq <= 1 else "%s_%d" % (base, seq)
