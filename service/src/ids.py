"""UUID v7 üretimi ve ULID → UUID v7 çevirisi.

Backend'in tek kimlik sözleşmesi uygulama tarafından basılan **uuid v7**'dir
(`domain/monotonic_id.rs`: "Every id this crate mints is a v7 uuid from
`next_uuid` — there is no second convention"). ZEKA'nın yazdığı satırlar da
buna uyar.

`uuid.uuid7()` Python 3.14'te geldi; konteyner 3.12 üstünde koşuyor. Bu yüzden
RFC 9562 §5.7 düzeni burada elle kuruluyor:

    48 bit  unix_ts_ms
     4 bit  sürüm (0111)
    12 bit  rand_a
     2 bit  varyant (10)
    62 bit  rand_b

---------------------------------------------------------------------------
ULID → UUID v7: neden düz bir bit kopyası DEĞİL
---------------------------------------------------------------------------
ULID 48 bit zaman + 80 bit rastgelelik taşır; UUID v7'de rastgeleliğe 74 bit
yer var. Yani 6 bit atmak gerekiyor ve **hangi 6 bit** sorusu masum değildir.

Tohum verisi `ulid_monotonic` ile üretildi: aynı milisaniyedeki kimlikler
rastgele alanın **düşük** bitlerinde birbirinden ayrılır. Üst 74 biti alıp
alttaki 6 biti atmak, tam da ayrımın yaşadığı yeri atmak olurdu — aynı
milisaniyede üretilmiş 64 kimlik tek bir UUID'ye çökerdi. 569.808 satırlık
tohumda bu, sessizce kaybolan satırlar demektir.

Bunun yerine:

* `rand_a` (12 bit) ← ULID rastgeleliğinin **düşük 12 biti**. Monotonik
  sayaç orada yaşadığı için milisaniye içi sıralama korunur (4096 kimliğe
  kadar; tohumda milisaniye başına en çok birkaç kimlik var).
* `rand_b` (62 bit) ← ULID metninin blake2b özeti. Özet, monotonik artışla
  ilintisiz olduğu için çakışma olasılığını rastgele dağılıma indirir.

Çeviri **deterministiktir**: aynı ULID her makinede aynı UUID'yi verir. Tohumun
"başka lokalde de aynı veri" hedefi buna bağlı.

Çakışma olasılığı 570 bin kimlik için ~1e-11 mertebesinde, ama olasılığa
güvenilmiyor: `to_uuid7_map` çevirinin tekilliğini **fiilen doğrular** ve
çakışma bulursa hata fırlatır.
"""

from __future__ import annotations

import hashlib
import os
import threading
import uuid

# Crockford base32, ULID'in alfabesi. I, L, O, U yok (okuma karışıklığı).
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_CROCKFORD_INDEX = {ch: i for i, ch in enumerate(_CROCKFORD)}

_lock = threading.Lock()
_last_ms = -1
_counter = 0


def _compose(ts_ms: int, rand_a: int, rand_b: int) -> uuid.UUID:
    """RFC 9562 §5.7 düzenini kurar. Alanlar maskelenerek yazılır."""
    if not 0 <= ts_ms < (1 << 48):
        raise ValueError(f"unix_ts_ms 48 bite sigmiyor: {ts_ms}")
    value = (ts_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76                       # surum = 7
    value |= (rand_a & 0xFFF) << 64
    value |= 0b10 << 62                      # varyant = RFC 4122/9562
    value |= rand_b & ((1 << 62) - 1)
    return uuid.UUID(int=value)


def uuid7(ts_ms: int) -> uuid.UUID:
    """Verilen anda yeni bir uuid v7 basar.

    Aynı milisaniye içinde `rand_a` bir sayaçtır, `Uuid::new_v7` yerine
    `ContextV7` kullanan backend ile aynı gerekçe: sayaç yerine her seferinde
    yeniden çekilen rastgele bitler, aynı tik içinde basılan kimliklerin
    `ORDER BY id` sırasını rastgeleye çevirir.
    """
    global _last_ms, _counter
    with _lock:
        if ts_ms == _last_ms:
            _counter = (_counter + 1) & 0xFFF
        else:
            _last_ms = ts_ms
            _counter = int.from_bytes(os.urandom(2), "big") & 0xFFF
        rand_a = _counter
    return _compose(ts_ms, rand_a, int.from_bytes(os.urandom(8), "big"))


def ulid_to_uuid7(value: str) -> uuid.UUID:
    """ULID metnini deterministik olarak bir uuid v7'ye çevirir.

    Gerekçe modül başındaki açıklamada. Girdi 26 karakterlik Crockford base32
    olmalıdır; değilse hata fırlatılır — sessizce bir kimlik uydurmak, yanlış
    satırı yanlış öğrenciye bağlamaktan başka bir şey değildir.
    """
    text = value.strip().upper()
    if len(text) != 26:
        raise ValueError(f"ULID 26 karakter olmali, {len(text)} geldi: {value!r}")
    number = 0
    for ch in text:
        digit = _CROCKFORD_INDEX.get(ch)
        if digit is None:
            raise ValueError(f"ULID alfabesi disi karakter {ch!r}: {value!r}")
        number = number * 32 + digit
    if number >= (1 << 128):
        raise ValueError(f"ULID 128 bite sigmiyor: {value!r}")

    ts_ms = number >> 80
    randomness = number & ((1 << 80) - 1)
    # Monotonik sayacin yasadigi yer: dusuk bitler.
    rand_a = randomness & 0xFFF
    digest = hashlib.blake2b(text.encode("ascii"), digest_size=8).digest()
    rand_b = int.from_bytes(digest, "big") & ((1 << 62) - 1)
    return _compose(ts_ms, rand_a, rand_b)


def mint_uuid7(text: str, ts_ms: int = 0) -> uuid.UUID:
    """Metinden **deterministik** bir uuid v7 uretir. Rastgelelik yok.

    Nerede gerekiyor: SurrealDB'de kompozit metin anahtari olan ama Postgres'te
    `uuid` birincil anahtari olan tablolar. Ornegin `homework_submission`in
    anahtari `{odev}_{ogrenci}` idi; Postgres bir uuid bekliyor ve elde
    cevrilecek bir ULID yok.

    `ts_ms` satirin KENDI zaman damgasidir (varsa). Damgayi kimligin icine
    koymak `ORDER BY id` ile `ORDER BY created_at` sirasini ayni tutar —
    arayuzdeki "en yeni once" listeleri buna dayaniyor. Damga verilmezse sifir
    kalir ve satirlar kimlige gore sirasiz gorunur; bu yuzden damgasi olan her
    tabloda verilmelidir.

    `uuid5` yerine bu: uuid5 v5 damgasi tasir, v7 degildir, ve backend'in tek
    kimlik sozlesmesi v7'dir. Ayni mantik, ayni bicim.
    """
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=10).digest()
    number = int.from_bytes(digest, "big")
    return _compose(int(ts_ms), (number >> 62) & 0xFFF, number & ((1 << 62) - 1))


def to_uuid7_map(ulids: list[str]) -> dict[str, uuid.UUID]:
    """Bir ULID kümesini çevirir ve **tekilliği fiilen doğrular**.

    Çakışma olasılığı ihmal edilebilir; ama "ihmal edilebilir" ile "olmadı"
    arasındaki farkı ölçmek burada bir sözlük karşılaştırması kadar ucuz.
    Çakışma varsa hangi iki ULID'in çakıştığı hatada yazar.
    """
    out: dict[str, uuid.UUID] = {}
    seen: dict[uuid.UUID, str] = {}
    for ulid in ulids:
        if ulid in out:
            continue
        converted = ulid_to_uuid7(ulid)
        clash = seen.get(converted)
        if clash is not None:
            raise ValueError(
                f"ULID cakismasi: {clash!r} ve {ulid!r} ayni UUID'ye dusuyor "
                f"({converted})"
            )
        seen[converted] = ulid
        out[ulid] = converted
    return out
