# Tohum kullanıcılarının parolası

## Karar

Tüm tohum kullanıcıları **aynı parolayı** kullanır, ama **her kullanıcının salt'ı farklıdır**.
Aynı hash'i 300 kullanıcıya kopyalamak gerçekçi değildir ve test sırasında yanıltır.

| | |
|---|---|
| Parola (düz metin) | `Hezarfen2026!` |
| Algoritma | argon2id |
| Sürüm | 19 |
| Bellek maliyeti | 19456 KiB |
| Tur sayısı | 2 |
| Paralellik | 1 |
| Hash uzunluğu | 32 bayt |
| Salt | kullanıcı başına 16 bayt, tohum değerinden türetilir |

## Neden bu parametreler

Backend `Argon2::default()` çağırıyor (`src/domain/user.rs:100`) ve argon2 crate 0.5'in
varsayılanı yukarıdaki değerlerdir. Depoda hazır bir hash literali **yok**; tüm testler
`password_hash = 'x'` yazıyor ve o kullanıcılar giriş yapamıyor
(`src/database.rs:568` ve benzeri onlarca yer).

## Beklenen biçim

```
$argon2id$v=19$m=19456,t=2,p=1$<22 karakter salt>$<43 karakter hash>
```

Doğrulanmış örnek (salt `0123456789abcdef`):

```
$argon2id$v=19$m=19456,t=2,p=1$MDEyMzQ1Njc4OWFiY2RlZg$odQ9y25bFJuqymOoKTkMbbkTlhp4ko91bSJ0EgHLh7c
```

## Üretim

`argon2-cffi` ile (ortamda 25.1.0 kurulu, doğrulandı):

```python
from argon2.low_level import hash_secret, Type

hash_secret(
    b"Hezarfen2026!", salt_16_bytes,
    time_cost=2, memory_cost=19456, parallelism=1,
    hash_len=32, type=Type.ID,
).decode()
```

Hash başına ~26 ms. 300 kullanıcı ≈ 8 saniye, üretim sırasında bir kez.

## Doğrulama adımı

Python tarafında üretilen hash'in Rust tarafında kabul edildiği **çalışan sistemde
sınanmalıdır**: tohum yüklendikten sonra bir öğrenci hesabıyla giriş denenir.
İki taraf da standart PHC dizgisi kullandığı için uyumlu olması beklenir, ancak
bu beklenti bu belgede test edilmemiştir.

## Uyarı

Bu parola herkese açık bir test parolasıdır. Tohum verisi **asla üretim
ortamına yüklenmemelidir**; yükleyici betiği bunu bir onay sorusuyla engeller.
