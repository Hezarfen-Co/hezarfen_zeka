# Kopru Kaniti -- `hab/2` istemcisinin ilk gercek kosusu

Bu belge tek bir soruya cevap verir: **`src/bridge.py` gercekten calisiyor mu?**

Onceki durum: `aioquer` katmani hic kosulmamisti. `aioquic` ortamda KURULU BILE
DEGILDI, dolayisiyla `src/bridge.py` bir kez bile `import` edilememisti. Butun
kopru kodu yalnizca okunarak dogru sayilmisti.

Simdiki durum: `tests/fake_bridge/` altinda backend'in protokolunu birebir
konusan bir QUIC sunucusu var ve `tests/test_bridge_live.py` icindeki **35 canli
test** gercek soketler, gercek TLS 1.3 el sikismasi ve gercek `hab/2`
cerceveleriyle kosuyor.

> **EN ONEMLI UYARI**
> Sahte sunucu **GERCEK BACKEND DEGILDIR**. Bu belgedeki hicbir madde
> "backend'e karsi dogrulandi" anlamina gelmez. Gercek `hezarfen_backend`
> ornegine karsi dogrulama **HALA YAPILMAMISTIR**.

---

## 1. `aioquic` kurulumu

```
pip install aioquic==1.3.0
```

Windows 10 / Python 3.14.3 uzerinde **hazir tekerlek (wheel) ile kuruldu,
derleyici gerekmedi**: `aioquic-1.3.0-cp310-abi3-win_amd64.whl`.

Birlikte gelen dolayli bagimliliklar (hepsi tekerlek):

| Paket | Surum |
|---|---|
| `aioquic` | 1.3.0 |
| `cryptography` | 50.0.1 |
| `pylsqpack` | 0.3.24 |
| `pyOpenSSL` | 26.4.0 |
| `service-identity` | 26.1.0 |
| `certifi` | 2026.4.22 |

Hepsi `requirements.txt` icinde **pinlendi**. Dolayli olanlarin da pinlenmesi
kasitli: `aioquic` bunlari acik araliklarla ister (`cryptography>=42` gibi), yani
ayni `Containerfile` bugun ve yarin farkli bir TLS yigini uretebilir ve QUIC el
sikismasi dogrudan bu kutuphanelerin davranisina bagli.

---

## 2. `bridge.py` / `protocol.py` icinde BULUNAN ve DUZELTILEN kusurlar

Bu ilk gercek kosu oldugu icin hata cikmasi bekleniyordu. Cikanlar:

### K1 -- TLS sertifikasi hicbir zaman yuklenemezdi *(agir)*

`build_quic_configuration()` sertifikayi `load_verify_locations(cadata=cert_pem)`
ile veriyordu; `cert_pem` bir **metin**. aioquic `cadata`'yi dogrudan
`load_pem_x509_certificates()`'e verir ve orada `bytes.split(...)` cagrilir
(`aioquic/tls.py:211`).

Sonuc: **her baglanti denemesi** TLS el sikismasi sirasinda
`TypeError: must be str or None, not bytes` ile duserdi. Bu, istemcinin gercek
backend'e de **hicbir zaman baglanamayacagi** anlamina gelir.

Duzeltme: `cadata=cert_pem.encode("ascii")`.

Bu kusur, kopru istemcisinin bir kez bile calistirilmadiginin en dogrudan
kanitidir: tek bir baglanti denemesi bunu gosterirdi.

### K2 -- El sikisma zaman asimi yakalayicisi ERISILEMEZDI *(orta)*

`run_forever()` icinde sira soyleydi:

```python
except (urllib.error.URLError, ConnectionError, OSError): ...
except HandshakeRejected: ...
except asyncio.TimeoutError: ...        # <- hic calismaz
```

Python 3.11'den beri `asyncio.TimeoutError` yerlesik `TimeoutError`'dir ve o da
`OSError`'in alt sinifidir. Proje Python 3.12+ hedefledigi icin bu clause
**olu koddu**: el sikisma zaman asimi "backend'e ulasilamadi" diye loglanir,
operator yanlis yere bakardi.

Duzeltme: zaman asimi yakalayicisi `OSError`'dan **once** tasindi.
Test: `BackoffOrderingTest.test_a_handshake_timeout_is_reported_as_a_timeout`.

### K3 -- Terk edilen okuma akislari sizdiriliyordu *(orta)*

`api_get()` / `blob_get()` zaman asimina ugrayinca `self._streams`'ten kaydi
siliyordu. Ama `quic_event_received()`, kaydi olmayan bir **istemci baslatimli**
akis icin YENI bir `FrameStream` kurup sozluge koyuyordu. Gec gelen cevap,
kimsenin okumayacagi bir tamponu baglantinin omru boyunca hafizada tutuyordu --
uzun omurlu bir baglantida her zaman asimi bir sizinti.

Duzeltme iki parcali:
* `quic_event_received()` artik yalnizca **sunucu baslatimli** (`sid % 4 == 1`)
  bilinmeyen akislar icin okuyucu kurar. Istemci baslatimli bir akisi yalnizca
  biz aciyoruz; kaydi yoksa o akis terk edilmistir ve baytlari duser.
* Yeni `_abandon()`: kaydi silmenin yaninda **STOP_SENDING** de gonderir.
  Onemli, cunku backend blob govdesini yazarken karsi tarafin okumasini bekler ve
  okunmayan bir akis orada bir acik dosyayi ve bir gorevi bagli tutar
  (`ai/server.rs:558-586`, `constant.rs:563`).

Testler: `StreamLifecycleTest` (4 test).

### K4 -- Senkron yetenek kancasi olay dongusunu blokluyordu *(orta)*

`_handle()`'in docstring'i "es zamanli kanca varsayilan executor'a atilir"
diyordu. Kod bunu **yapmiyordu**; kancayi olay dongusunde dogrudan cagiriyordu.

ZEKA'nin yetenekleri ogrenci verisi uzerinde islemci yogun senkron hesaplar.
Olay dongusunde kostuklarinda `keepalive()` PING'leri de durur. Backend'in bosta
kalma penceresi 30 s (`constant.rs:554`), PING araligi 10 s (`constant.rs:555`):
30 saniyeden uzun suren **tek bir** senkron yetenek, cevabini yazamadan
baglantinin dusurulmesine yol acardi.

Duzeltme: senkron kancalar `run_in_executor` ile is parcacigina veriliyor;
`async def` kancalar eskisi gibi dogrudan bekleniyor.
Test: `test_a_slow_synchronous_capability_does_not_block_the_event_loop`.

### K5 -- `next_backoff()` docstring'i yaniltiyordu *(kucuk)*

"ustune jitter ekle" diyordu; jitter'i cagiran taraf ekliyor. Docstring
duzeltildi ve jitter'in neden orada olmasi gerektigi (rastgeleligin birikip
gercek tavani asmamasi icin) yazildi.

### Ek not -- kod dizesi tuzagi

Bos yetenek listesinin tel uzerindeki kodu **`no_capabilities`**'tir
(`protocol.rs:123-130`, `serde(rename_all = "snake_case")`).
`ai/server.rs:976`'da gecen `"bad_capabilities"` bir **metrik etiketidir**, tel
kodu degildir. `protocol.py` zaten dogru degeri tasiyordu; sahte sunucu da dogru
olani uretiyor ve test bunu pinliyor.

---

## 3. Sahte sunucunun TAKLIT ETTIGI davranislar

`tests/fake_bridge/server.py`, backend'in su dosyalarindan tureyen davranislari
uretir. **Kasitli bagimsizlik:** cerceveleme, izin listesi eslesmesi ve kod
dizeleri `src/protocol.py`'den ithal EDILMEZ, elle yeniden yazilmistir -- ayni
modulu iki tarafta kullanmak bir alan adi hatasini gorunmez kilardi.

| # | Taklit edilen davranis | Kaynak |
|---|---|---|
| 1 | ALPN `hab/2` surum kapisi; baska ALPN TLS'te reddedilir | `ai/tls.rs:80-83` |
| 2 | Kendi kendine imzali sertifika (`localhost` + `127.0.0.1` SAN, CA degil) | `ai/tls.rs:139-148` |
| 3 | Parmak izi = leaf DER'in SHA-256'si, kucuk harf hex | `ai/tls.rs:150-153` |
| 4 | `GET /ai/certificate` -> `certificate_pem` + `fingerprint_sha256` | `web/ai.rs:76-83` |
| 5 | Ilk istemci baslatimli akis kontrol akisidir; `Hello` okunur | `ai/protocol.rs:11-14` |
| 6 | Red sirasi: once surum, sonra token, sonra yetenekler | `ai/server.rs:949-991` |
| 7 | `unsupported_protocol` / `unauthorized` / `no_capabilities` / `malformed` | `ai/protocol.rs:123-130` |
| 8 | `Greeting{type:"welcome", worker_id, protocol}`; kontrol akisi ACIK kalir | `ai/server.rs:1000-1008` |
| 9 | Kayit, hosgeldin tele CIKTIKTAN SONRA yapilir | `ai/server.rs:1010-1017` |
| 10 | Red sonrasi cerceveye pay birakilip baglanti kapatilir | `ai/server.rs:1030-1046` |
| 11 | Kontrol akisinin olumu = kayittan dusme (heartbeat cercevesi yok) | `ai/protocol.rs:12-14` |
| 12 | `max_concurrent` 1..=64 kirpmasi (yoksa 8) | `constant.rs:547-548` |
| 13 | Sonraki istemci akislari `path` / `file` ZORUNLU alanlariyla ayirt edilir; `path` kazanir | `ai/server.rs:484-497` |
| 14 | Red cercevesi `id` ve `school`'u OLDUGU GIBI yankilar | `ai/server.rs:477-482` |
| 15 | Izin listesi: segment segment, on-ek YOK, kuyruk joker'i YOK, `{x}` = bir bos olmayan segment | `ai/api.rs:20-61` + `constant.rs:656-676` |
| 16 | Denetim sirasi: once yontem (`method_not_allowed`), sonra yol (`path_not_allowed`) | `ai/server.rs:715-733` |
| 17 | Reddedilen yol router'a HIC verilmez | `ai/server.rs:717-718` |
| 18 | Okul cozumlemesi: `malformed` / `unknown_school` / `school_suspended` | `ai/server.rs:80-100` |
| 19 | HTTP 404 bir `ok`'tur ve `status` alaninda tasinir; `outcome` etiketi ayridir | `ai/protocol.rs:196-221` |
| 20 | `BlobResponse` etiketi `status`, `ApiResponse` etiketi `outcome` | `ai/protocol.rs:200,246` |
| 21 | Blob: baslik cercevesi + tam `size` HAM bayt + FIN; govde cerceve DEGILDIR | `ai/protocol.rs:25-31` |
| 22 | Govde 64 KiB'lik parcalar halinde akar | `ai/server.rs:558-586` |
| 23 | `size` diskteki dosyadan alinir, satirdan degil | `ai/server.rs:640-650` |
| 24 | `on_behalf_of` yoksa `ai` rolu -> `forbidden` | `ai/protocol.rs:236-239` |
| 25 | Olmayan blob -> `not_found` | `ai/server.rs:614-618` |
| 26 | Sunucu baslatimli akis: bir `Request` + FIN, sonra bir `Response` | `ai/server.rs:258-283` |
| 27 | Cerceveleme: u32 big-endian uzunluk + JSON; sinir 8 MiB | `ai/protocol.rs:54-59`, `constant.rs:536` |
| 28 | `Hello` KASITLI olarak okul tasimaz | `ai/protocol.rs:39-43` |
| 29 | Korelasyon kimligi yok; eslesmeyi QUIC akis kimlikleri yapar | `ai/protocol.rs:48-52` |

Ayrica testin isteyerek urettigi, **backend'in yapmadigi** bir davranis var:
sinirdan buyuk bir uzunluk oneki yazmak. Backend `write_frame` icinde boyutu
yazmadan once denetler (`ai/protocol.rs:275-277`); bu, istemcinin okuma
tarafindaki kapagini (`ai/protocol.rs:286-289`) zorlamak icin kotu/bozuk bir es
taklididir.

---

## 4. KANITLANANLAR (35 canli test)

Her madde `tests/test_bridge_live.py` icinde en az bir testle karsilanir.

**El sikisma (3)**
- Gercek QUIC + TLS 1.3 el sikismasi kuruluyor, `Hello` yaziliyor, `Greeting`
  okunuyor, `worker_id` aliniyor.
- Yetenekler (`capabilities.names()`) tel uzerinde birebir kaydoluyor.
- `Hello` alanlari dogru: `protocol="hab/2"`, `token`, `max_concurrent=4`,
  **`school` alani YOK**.
- Kontrol akisi baglanti boyunca acik kaliyor; worker kayitli kaliyor.

**API okumasi (8)**
- Izinli yoldan veri geliyor, govde dogru cozumleniyor (UTF-8 Turkce dahil),
  `on_behalf_of` tele ciktigi gibi sunucuya ulasiyor.
- Query **kendi alaninda** gidiyor, yola gomulmuyor.
- HTTP 404 bir `ok` olarak geliyor, red olarak degil.
- Izinsiz yol (`/settings`) `path_not_allowed` ile reddediliyor; **sessizce bos
  donmuyor**, istisna atiliyor ve istek **tele hic cikmiyor**.
- Istemcinin on denetimi atlanip ham cerceve yollandiginda **sunucu tarafi da
  bagimsiz olarak** `path_not_allowed` donuyor (`/course-notes/{id}/files/{f}`).
- `school` eksikse istek **gonderilmeden** reddediliyor.
- Bilinmeyen okul -> `unknown_school` (yeniden denemeye degmez).
- Askidaki okul -> `school_suspended` (yeniden denemeye deger).

**Blob okumasi (5)**
- 200 000 baytlik govde **eksiksiz** geliyor; baslik `size` ile okunan bayt sayisi
  ve icerigin kendisi birebir tutuyor (64 KiB parcalama gercekten tetikleniyor).
- `size: 0` asilma degil, aninda biten bir okuma.
- Olmayan dosya -> `not_found`.
- `on_behalf_of` yoksa -> `forbidden`.
- Okulsuz blob istegi tele cikmiyor.

**Sunucu baslatimli is akisi (4)**
- `Request` -> `Response{status:"ok"}` gidis-donusu; `id` ve `school` yankilaniyor,
  `deadline_ms` isleyiciye ulasiyor.
- `CapabilityError` -> `Response{status:"err", code}`; akis dusmuyor.
- Islemci yogun senkron bir yetenek olay dongusunu **bloke etmiyor** (K4).
- Ilan edilen es zamanlilik asilinca acik `busy` donuyor.

**Cerceve boyut kapagi (3)**
- Sinirdan buyuk bir uzunluk oneki, **tek bir govde bayti beklenmeden**
  reddediliyor ve istemci akisi asili birakmak yerine hata cercevesi yaziyor.
- Kapak yazarken de uygulaniyor.
- Kapagi asan bir yetenek cevabi sessizce dusurulmuyor, kucuk bir hata
  cercevesine donuyor.

**Red ve dayaniklilik (6)**
- Yanlis protokol surumunde reddediliyor ve istemci **CIKMIYOR**; ustel geri
  cekilmeyle yeniden deniyor (en az iki deneme gozlendi).
- Yanlis token'da `unauthorized`; yine cikilmiyor, yeniden deneniyor.
- Bos yetenek listesinde `no_capabilities`.
- `hab/1` konusan bir istemci **ALPN kapisinda** reddediliyor ("No common ALPN
  protocols"); tek bir `Hello` bile tele cikmiyor. Podcast ve Celebi
  servislerinin bu koprude calisamayacaginin kaniti.
- Istemcinin ALPN'i ve bosta kalma suresi backend sabitleriyle ayni.
- Pinlenen parmak izi tutmazsa **baglanilmiyor**; TOFU'ya geri dusulmuyor.
- Baglanti koparildiginda yeniden baglaniliyor ve **yeniden kaydolunuyor**
  (yeni bir `worker_id` aliniyor).

**Akis yasam dongusu (4)**
- Es zamanli uc okuma kendi akislarinda coklaniyor, cevaplari karismiyor.
- Biten okuma tampon birakmiyor (geriye yalnizca kontrol akisi kaliyor).
- Cevapsiz kalan okuma zaman asimina ugruyor ve akisi terk ediyor.
- Reddedilen okuma da tampon birakmiyor.

**Geri cekilme siralamasi (1)**
- El sikisma zaman asimi dogru yakalayiciya dusuyor (K2).

**Ag kapsami:** hepsi yalnizca `127.0.0.1`, isletim sisteminin verdigi bos
portlarda. **Disariya hicbir baglanti yok**, sabit port isgali yok.

---

## 5. KANITLANMAYANLAR

Bunlarin hicbiri bu calismayla dogrulanmadi. Liste eksiksiz olmaya calisir.

### 5.1 En basta gelen

**Gercek backend'e karsi hicbir sey dogrulanmadi.** Sahte sunucu, backend'in
Rust kaynagini *okuyarak* yazildi. Kaynagi yanlis okuduysam sahte sunucu da
yanlis olur ve test yanlis davranisi dogrular. Bu testler, kodun protokolun
**benim anladigim halini** dogru konustugunu gosterir; protokolun kendisini
dogrulamaz.

### 5.2 TLS ve sertifika

- Gercek backend'in `rcgen` ile urettigi sertifika kullanilmadi; benzeri
  `cryptography` ile uretildi (ECDSA P-256, CA degil, ayni SAN listesi).
- Gercek dagitimda kullanilan **PEM cifti** (muhtemelen RSA, muhtemelen bir
  zincir) hic denenmedi. Zincir uzunlugu > 1 olan bir sertifika hic gorulmedi.
- Gercek `GET /ai/certificate` ucu hic cagrilmadi; yalnizca `web/ai.rs`'den
  okunan alan adlari taklit edildi.
- Sertifikanin her boot'ta yenilenmesi senaryosu (`tls.rs:37-46`) test edilmedi.

### 5.3 Backend'in kendi mantigi

- **Okul slug dogrulama kurallari.** Backend `Slug::try_new` kullanir; sahte
  sunucu kaba bir denetim yapar. `malformed` kodu gercek kurallarla uretilmedi.
- **Kullanici cozumleme.** `on_behalf_of`'un `user:` onekiyle ya da onsuz
  okunmasi, silinmis/rutbesi dusurulmus kullanici, `unknown_user` kodu.
- **Modul yetkilendirmesi.** `module_disabled` kodu (`CourseNotes`, `Chatbot`)
  hic uretilmedi.
- **Veritabani canliligi.** `unavailable` kodu hic uretilmedi.
- **Ders goruntuleme yetkisi** (`can_view_course`) taklit edilmedi; `forbidden`
  yalnizca "`on_behalf_of` yok" durumundan uretildi.
- **Sabit zamanli token karsilastirmasi.** Sahte sunucu duz `!=` kullanir;
  zamanlama davranisi test edilmedi.
- **`too_large` dusurmesi**: backend'in kendi cevabi cerceveye sigmadiginda
  yaptigi dusurme (`ai/server.rs:895-918`) hic tetiklenmedi.
- **Kayit defteri / kiralama.** Backend'in `max_concurrent` vaadine gercekten
  uyup uymadigi, `AiRegistry.pick` davranisi, `IdMismatch` tespiti.
- **Metrikler ve izleme** (span'lar, sayaclar, rota sablonu etiketleri).

### 5.4 Zaman ve ag

- Backend'in **10 saniyelik el sikisma zaman asimi** (`constant.rs:643`) hic
  tetiklenmedi.
- **30 saniyelik bosta kalma zaman asimi** ve 10 saniyelik keepalive uzun
  sureli bir kosuyla dogrulanmadi; testlerin hicbiri 25 saniyeden uzun surmez,
  yani **tek bir keepalive PING'i bile gonderilmedi**.
- **Blob yazma tikanma kapagi** (`AI_BLOB_WRITE_STALL_SECS`, 30 s) test edilmedi.
- Gercek ag kosullari yok: paket kaybi, yeniden siralama, MTU sorunlari, NAT
  ardindan baglanma, IPv6. Hepsi `127.0.0.1` uzerinde, kayipsiz.
- `AI_MAX_FRAME_BYTES` (8 MiB) sinirinin **hemen altindaki** gercek bir cerceve
  hic yollanmadi; yalnizca sinirin ustundeki reddedildi.

### 5.5 Uygulama katmani

- Izin listesindeki yollarin **gercek cevap govdeleri** dogrulanmadi. Sahte
  sunucu testin verdigi govdeyi doner. Govde bicimleri ayri olarak
  `tests/test_source.py` icinde fiksturlere karsi denetlenir; ikisi arasindaki
  bag **kurulmadi**.
- ZEKA'nin yetenekleri (`insight.*`) icin backend'de bir **dagitim kapisi
  yok** (`docs/BACKEND-GEREKSINIMLERI.md` Madde 1; sahibi `InsightDoors`).
  Sunucu baslatimli akis testi bu yuzden sahte bir cagriyla yapildi; kapilar
  gelene kadar bu yol uretimde **kullanilmaz**.
- Coklu okul (filo paylasimi) davranisi tek bir okulla test edildi.
- Ayni backend'e **birden cok ZEKA ornegi** baglanmasi test edilmedi.

### 5.6 Bilinen, duzeltilmemis konular

- **`blob_get` butcesi bir AKTARIM kapagidir, tikanma kapagi degil.**
  `ZEKA_BLOB_TIMEOUT_SECS` (varsayilan 60 s) butun govdeye uygulanir. Backend'in
  tasarimi ise yazma basina tikanma kapagidir (`constant.rs:557-563`): yavas ama
  saglikli bir aktarim backend tarafinda kesilmez, ama bizim tarafimizda 60
  saniyede kesilir. Buyuk bir dosya yavas bir hatta **gereksiz yere** terk
  edilebilir. Bilincli birakildi; degistirmek bir yapilandirma kararidir.
- **`fetch_certificate()` bloke edicidir.** `urllib` ile senkron kosar ve olay
  dongusunu 10 saniyeye kadar durdurabilir. `run_once()` icinde baska bir is
  kosmadigi icin bugun zararsiz, ama bir tasarim borcudur.
- **aioquic, iptal edildiginde UDP soketini kapatmiyor.** `connect()`'in
  `finally` blogu `await protocol.wait_closed()` yapar; gorev iptal edilmisse bu
  await hemen `CancelledError` firlatir ve `transport.close()` **atlanir**.
  Testlerde `ResourceWarning: unclosed socket` olarak gorunur. `run_forever()`
  dongusunde `run_once()` iptal EDILMEZ (normal donus ya da istisna ile biter),
  dolayisiyla yeniden baglanma dongusu soket sizdirmaz; sizinti yalnizca
  kapanis sirasinda ve testlerde olusur. aioquic'in davranisidir, bizim
  kodumuzun degil.

---

## 6. Testleri kosmak

```
cd service
python -m unittest tests.test_bridge_live          # yalnizca canli testler (35)
python -m unittest discover -s tests -t .          # butun paket
```

Canli testler yaklasik 25 saniye surer (gercek ag el sikismalari). `aioquic`
kurulu degilse modul kendini atlar ve geri kalan test paketi bagimliliksiz
calismaya devam eder.
