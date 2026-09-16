# ZEKA -- Backend Gereksinimleri

Bu belge backend ekibine iletilecek **somut** istek listesidir. Her madde
`hezarfen_backend-main` deposunda bir degisiklik ister ve her maddede uc sey
vardir: **ne isteniyor**, **neden**, **olmadiginda ne kaybediliyor**.

Hicbiri ZEKA tarafinda cozulemez. ZEKA'nin backend'e giden tek kanali QUIC
koprusudur ve o kanal:

- yalnizca **GET** dagitir (`src/ai/server.rs:719-726` -> `method_not_allowed`),
- yalnizca **19 yollu, reddet-varsayilan** bir izin listesine bakar
  (`src/constant.rs:656-676`, eslesme `src/ai/api.rs:39-60`),
- ve yalnizca backend'in **tanidigi yetenek adlarina** is gonderir
  (`src/ai/protocol.rs:91-94`, tam eslesme).

Yani asagidaki uc madde ZEKA'nin nelerin **disinda** kaldigini tarif eder.

---

## Madde 1 -- ZEKA'nin yetenekleri backend'de tanimli degil

### Ne isteniyor

`src/constant.rs` icine yeni yetenek sabitleri ve onlari cagiran dagitim kodu:

```rust
/// ZEKA -- tek ogrenci icin analiz/tavsiye.
pub const AI_INSIGHT_STUDENT_CAPABILITY: &str = "insight.student";
/// ZEKA -- bir ders/sinif icin toplu analiz.
pub const AI_INSIGHT_CLASS_CAPABILITY: &str = "insight.class";
/// ZEKA -- bir okulun hesaplarini yeniden kosturma (parti isi).
pub const AI_INSIGHT_REFRESH_CAPABILITY: &str = "insight.refresh";
```

ve bunlari `AiRegistry` uzerinden cagiran bir yol -- `chat.reply` icin
`src/ai/chat.rs`'in, `rag.index` icin `src/ai/rag.rs`'in yaptigi seyin esi.

Payload sozlesmeleri `service/src/capabilities.py` icinde tip olarak tanimlidir
(`StudentRequest` / `StudentResponse`, `ClassRequest` / `ClassResponse`,
`RefreshRequest` / `RefreshResponse`).

### Neden

Backend'in bugun tanidigi yetenek adlari **yalnizca ikidir**:

| Sabit | Deger | Kaynak |
|---|---|---|
| `AI_CHAT_CAPABILITY` | `chat.reply` | `src/constant.rs:568` |
| `AI_RAG_INDEX_CAPABILITY` | `rag.index` | `src/constant.rs:574` |

Yonlendirme **tam eslesmedir** (`src/ai/protocol.rs:91-94`): yaklasik eslesme,
on-ek eslesmesi ya da geri dusme yoktur. ZEKA baglanip `insight.student` ilan
etse bile, o adi arayan bir `Request` ureten kod backend'de **yoktur**.

Bu, podcast servisinin yasadigi sorunun aynisidir: `podcast.submit`,
`podcast.status`, `podcast.result`, `podcast.cancel` adlarinin hicbiri backend
kaynaginda gecmez (`grep -rni "podcast" src/` -> 0 sonuc), bu yuzden podcast
protokol surumunu duzeltip **baglansa bile** hicbir is almaz.

### Olmadiginda ne kaybediliyor

Backend ZEKA'yi **hic cagiramaz**. Senkron her senaryo duser:

- Ogretmen bir ogrencinin karnesini acar ve "ZEKA analizi" ister -> backend'in
  bu istegi koprude karsilayacak bir yolu yoktur.
- Bir sinav notlandirildiktan hemen sonra sinif analizinin tazelenmesi -> olay
  aninda tetiklenemez.
- Frontend'den gelen "simdi hesapla" -> hicbir sey olmaz.

ZEKA yine de **kendi zamanlayicisiyla** (`ZEKA_REFRESH_INTERVAL_SECS`) hesap
kosar ve ciktilarini kendi veritabanina yazar; yani urun tamamen olmez, ama
**istege bagli (on-demand) her sey** kaybedilir ve her sonuc en kotu ihtimalle
bir tazeleme periyodu kadar bayattir.

---

## Madde 2 -- Izin listesine sinav yollarinin eklenmesi

### Ne isteniyor

`AI_API_ALLOWLIST` (`src/constant.rs:656-676`) icine asagidaki yollar. Hepsi
`GET`, hepsi JSON, hicbiri bayt servis etmiyor:

| Yol | Ne verir | Mevcut rota kaynagi |
|---|---|---|
| `/exams` | Okulun sinav listesi | `src/web/exams/mod.rs:247` |
| `/exams/{id}` | Tek sinavin tanimi | `src/web/exams/mod.rs:303` |
| `/exams/{id}/questions` | Sinavin sorulari, siklariyla | `src/web/exams/questions.rs:212` |
| `/exams/{id}/statistics` | Sinavin ozet istatistigi | `src/web/exams/mod.rs:680` |
| `/exams/{id}/results` | Sinavin sonuc listesi | `src/web/exams/mod.rs:502` |
| `/exams/{id}/review/questions` | Soru bazinda inceleme verisi | `src/web/exams/review.rs:335` |
| `/exams/{id}/review/attempts` | Deneme bazinda inceleme verisi | `src/web/exams/review.rs:290` |
| `/exams/{id}/review/attempts/{seq}/answers` | **Tek tek verilen cevaplar** | `src/web/exams/review.rs:372` |
| `/exams/{id}/students/{user}/marks` | Bir ogrencinin sinav not gecmisi | `src/web/exams/review.rs:138` |

Ikincil oncelikli (sinif/ders baglami icin):

| Yol | Ne verir | Kaynak |
|---|---|---|
| `/classes/{id}/members` | Sinif mevcudu | `src/web/classes.rs:727` |
| `/classes/{id}/courses` | Sinifin dersleri | `src/web/classes.rs:857` |
| `/courses` ve `/courses/{id}` | Ders tanimlari | `src/web/courses.rs` |

### Neden -- somut ornek: madde analizi

Madde analizi (item analysis), bir sinav sorusunun **ayirt ediciligini** ve
**celdiricilerinin davranisini** olcer. Hesabin girdisi sudur:

> her ogrenci, her soru icin, **hangi sikki isaretledi**.

Bu tablo olmadan madde analizi tanim geregi yapilamaz.

Bugun ZEKA'nin okuyabildigi **tek** not kaynagi `/marks/{user}`'dir
(`src/constant.rs:670`). O uctan gelen sey bir **toplam nottur**: "Ayse
matematik sinavindan 72". Bu veriyle sunlari soyleyebiliriz:

- Ayse'nin notu dusuyor mu,
- sinifin ortalamasi nedir.

Soyleyemedigimiz sey:

- **7. soru bozuk mu?** Ustteki %27'lik dilim ile alttaki %27'lik dilim o soruyu
  ayni oranda yanlis yapiyorsa sorunun ayirt ediciligi sifira yakindir --
  soruyu bilen de bilmeyen de kaciriyor demektir. Bunu hesaplamak icin
  **soru bazinda dogru/yanlis** gerekir; toplam not bunu icermez.
- **Hangi yanlis secenek nereye isaret ediyor?** "Ogrencilerin %58'i 7. soruda
  C sikkini isaretledi" cumlesi bir **kavram yanilgisinin** parmak izidir; C
  sikkinin ardindaki hata (orn. isaret hatasi, birim karisikligi) tum sinifta
  ayni sekilde isliyor demektir. Ogretmene "su konuyu su acidan tekrar edin"
  diyebilmek icin **secenek dagilimi** gerekir. Bu veri yalnizca
  `/exams/{id}/review/attempts/{seq}/answers` ve
  `/exams/{id}/review/questions` uclarinda vardir.
- **Konu karnesi.** "Ayse turev konusunda %40, integralde %85" demek, her
  sorunun hangi konuya bagli oldugunu (`/exams/{id}/questions`) ve o soruya ne
  cevap verildigini (`.../answers`) birlestirmeyi gerektirir.

ZEKA'nin tohum verisi (`hezarfen-ZEKA/seed/`) tam da bunun icin uretildi:
217.498 sinav cevabi, kasitli olarak **dusuk ayirt edicilikli ve negatif
maddeler**, **sistematik olarak cekici celdiriciler** ve **gercek kavram
yanilgilarini tasiyan siklar** icerir. Yani bulunacak sey vardir; bugun
bulunacak yol yoktur.

### Olmadiginda ne kaybediliyor

Somut olarak su urunler **hic uretilemez**:

- Madde analizi (ayirt edicilik, guclugu, celdirici etkinligi).
- Ogrenci basina **konu karnesi** -- hangi konuda zayif, hangisinde guclu.
- Sinif **konu isi haritasi** -- "bu sinif turevde toplu halde dusuyor".
- "Bu soru bozuk, sinavdan cikarin" onerisi.

Geriye kalan, yalnizca toplam nottan turetilebilen kaba sinyallerdir: "notu
dusuyor", "ortalamanin altinda". Bunlar ogretmenin zaten gordugu seylerdir;
ZEKA'nin kattigi deger degildir.

> **Not:** `/exams/.../answers/{qid}/image` gibi **bayt servis eden** uclarin
> eklenmesi istenmemektedir. Izin listesi bilincli olarak JSON-only'dir
> (`src/constant.rs:650-655`); bayt gerekirse dogru kanal `BlobRequest`'tir.

---

## Madde 3 -- Okul ve kullanici listeleme yolu yok

### Ne isteniyor

Iki uc, izin listesine:

1. **Okul listesi.** Bugun boyle bir REST ucu **hic yoktur** -- okullar kontrol
   veritabanindadir ve `Tenants` uzerinden cozulur (`src/ai/server.rs:82-99`).
   Servisin gordugu tek sey, bir slug verip `unknown_school` /
   `school_suspended` yemektir. Istek: baglanmis bir AI servisinin **aktif okul
   sluglarini** listeleyebilecegi bir yol (yeni bir uc, orn.
   `GET /ai/schools`, ya da kopruye bir `SchoolsRequest` cercevesi).
2. **Kullanici listesi.** Rotalar **vardir** ama izin listesinde **degildir**:
   - `GET /users` -- sayfali kullanici listesi (`src/web/users.rs:260`),
   - `GET /users/search` -- role gore arama (`src/web/users.rs:210`),
   - `GET /classes/{id}/members` -- sinif mevcudu (`src/web/classes.rs:727`).

   Bunlardan en az biri (tercihen `GET /users/search`, cunku ciktisi zaten
   yalnizca id/kullanici adi/gorunen ad tasir, **iletisim bilgisi tasimaz**)
   `AI_API_ALLOWLIST`'e eklenmelidir.

### Neden

ZEKA'nin butun is birimi "bir okulun bir ogrencisi icin hesap kos"tur. Ama
`Hello` cercevesi **kasitli olarak okul tasimaz** (`src/ai/protocol.rs:82-84`):
filo paylasimlidir, tek baglanti dagitimdaki her okula hizmet eder ve her frame
kendi okulunu adlandirir. Bu tasarim dogrudur.

Sonucu sudur: servis, **hangi okullarin var oldugunu ve o okullarda kimlerin
bulundugunu ogrenebilecegi hicbir yola sahip degildir**. Backend ZEKA'ya is
gonderseydi okul ve kullanici `Request` cercevesinde gelirdi -- ama Madde 1
yuzunden backend ZEKA'ya is gondermiyor. Yani ZEKA'nin kendi kendine kosmasi
gerekiyor ve kendi kendine kosmak icin bir liste gerekiyor.

### Bugun nasil cozuluyor

**Yapilandirmadan.** `service/src/config.py` icinde:

- `ZEKA_SCHOOLS` -- islenecek okul sluglari, virgulle ayrilmis
  (varsayilan: `ataturk-anadolu`),
- `ZEKA_STUDENT_SOURCE` = `config` | `file`,
- `ZEKA_STUDENTS` -- kullanici kimlikleri, virgulle ayrilmis,
- `ZEKA_STUDENT_FILE` -- ayni listenin dosya hali.

Yani kapsam **elle** tutulur.

### Olmadiginda ne kaybediliyor

- **Yeni ogrenci gorunmez.** Donem ortasinda kayit olan bir ogrenci, birisi
  `ZEKA_STUDENTS` degiskenini elle guncelleyip servisi yeniden baslatana kadar
  ZEKA icin yoktur. Tohum verisinde bu kenar durum bilincli olarak vardir.
- **Ayrilan ogrenci silinmez.** Listede kaldigi surece ZEKA onun icin hesap
  kosmaya devam eder ve her seferinde bos/hatali sonuc uretir.
- **Yeni okul gorunmez.** Platforma bir okul eklendiginde ZEKA'nin yapilandirmasi
  guncellenmediyse o okul hic islenmez -- ve bunun hicbir belirtisi olmaz,
  cunku "islenmeyen okul" ile "sorunsuz islenen okul" ayni sessizlikte gorunur.
- **Isletme maliyeti.** Kapsam, kod deposunda degil `compose.yaml` ortam
  degiskeninde yasar; her mevcut degisikligi bir dagitim islemi haline gelir.

---

## Ozet tablo

| # | Istenen | Kaynak dosya | Olmazsa kaybedilen |
|---|---|---|---|
| 1 | `insight.student` / `insight.class` / `insight.refresh` sabitleri + dagitim kodu | `src/constant.rs`, `src/ai/` | Backend ZEKA'yi **hic cagiramaz**; istege bagli her senaryo duser |
| 2 | 9 sinav yolu (+3 sinif/ders yolu) izin listesine | `src/constant.rs:656-676` | **Madde analizi, konu karnesi, sinif isi haritasi** hic uretilemez |
| 3 | Okul listeleme ucu + `GET /users/search` izin listesine | yeni uc; `src/constant.rs:656-676` | Kapsam elle tutulur; yeni ogrenci/okul **sessizce** gorunmez |

---

## Ek: sabit sapma riski

ZEKA, backend'in sabitlerini **kopyalamaz, turetir** ve her birinin kaynak
satirini kodda yazar (`service/src/protocol.py` basi). Ama Python tarafi Rust
tarafini derleme zamaninda goremez, dolayisiyla backend bir sabiti degistirirse
ZEKA **sapar**.

Sapmayi yakalayan sey su testlerdir:

- `tests/test_protocol.py::AllowlistTests::test_allowlist_matches_backend_snapshot`
  -- 19 yollu listenin birebir anlik goruntusu,
- `tests/test_protocol.py::ProtocolVersionTests` -- `hab/2`, cerceve kapagi,
  es zamanlilik siniri, zaman asimlari,
- `tests/test_capabilities.py::test_backend_knows_none_of_them` -- Madde 1
  cozuldugunde **kasitli olarak kirilir** ve guncellenmesi gerekir,
- `service/src/source.py` modul yuklenirken her yol sablonunu izin listesine
  karsi denetler; liste daralirsa servis **import aninda** patlar, calisma
  zamaninda sessizce `path_not_allowed` toplamaz.

**Istek:** yukaridaki sabitlerden biri degistiginde bu depoya haber verilsin.
Daha iyisi, backend `GET /limits` benzeri bir ucta protokol surumunu ve izin
listesini yayimlasin; o zaman sapma calisma zamaninda tespit edilebilir hale
gelir.
