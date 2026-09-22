# ZEKA -- Backend Gereksinimleri

Bu belge backend ekibine iletilecek **somut** istek listesidir. Her madde
`hezarfen_backend-main` deposunda bir degisiklik ister ve her maddede uc sey
vardir: **ne isteniyor**, **neden**, **olmadiginda ne kaybediliyor**.

Hicbiri ZEKA tarafinda cozulemez. ZEKA'nin backend'e giden tek kanali QUIC
koprusudur ve o kanal bugun:

- okuma icin yalnizca **GET** dagitir (`src/ai/server.rs:719-726` ->
  `method_not_allowed`),
- okuma icin yalnizca **19 yollu, reddet-varsayilan** bir izin listesine bakar
  (`src/constant.rs:656-676`, eslesme `src/ai/api.rs:39-60`),
- ve is dagitimini yalnizca backend'in **tanidigi yetenek adlarina** yapar
  (`src/ai/protocol.rs:91-94`, tam eslesme).

Yazma yolu **hic yoktur**: servisin kendi `zeka_*` satirlarini gonderebilecegi
istemci-baslatimli bir yetenek cercevesi tanimli degildir (Madde 1).

Yani asagidaki uc madde ZEKA'nin nelerin **disinda** kaldigini tarif eder.

> **DURUM (2026-09-18).** Madde 1'in **(a) servisin cagirdigi `insight.*`
> operasyonlari** yonu backend'de **acildi** (`f84c29d`): kapi listesi
> `/api-docs/openapi.json` icinde gorunur ve `insight.schools.list`,
> `insight.pending.list`, `insight.retention.sweep` canli backend'e karsi
> kosturuldu (uclu de basarili dondu). **(b) backend'in ZEKA'yi cagirmasi**
> yonu 2026-09-18'de `insight.student` ve `insight.refresh` icin **acildi**
> (`ai/insight.rs::compute_student/refresh` + `web/insights.rs` kapilari) ve
> servis tarafi ayni gun baglandi (`src/handlers.py`; ilan ile dagitim
> acilista `capabilities.verify_dispatchable()` ile denetlenir).
> `insight.class` ilan edilir ama hala GONDERILMEZ -- kadro listeleme yolu
> yok (Madde 3). `insight.report` icin iki taraf da AYNI GUN LANDEDI
> (2026-09-18): servis ilan eder ve dagitir (`handlers.report`), backend'in
> sabiti (`constant.rs:645`), dagitimi (`ai/insight.rs::report`) ve
> `POST /runs/{run_day}/report` kapisi yerindedir -- bkz. `## insight.report`.
> Asagidaki "yoktur / tanimli degil" ifadeleri bu iki yonu
> ayirmadan okunmamalidir; `src/capabilities.py` modul dokumani ayni ayrimi
> yapar.

---

## Madde 1 -- `insight.*`: depo yolu ACILDI, sunucu-baslatimli yon student+refresh icin ACILDI

**Sahibi: backend'deki `InsightDoors` hatti.** Asagidaki zarf DONMUS'TUR; servis
ona karsi yazildi. (a) yonu 2026-09-17'de acildi (`f84c29d`); (b) yonu
2026-09-18'de `insight.student` + `insight.refresh` icin acildi; `insight.class`
icin hala aciktir (kadro listeleme yolu -- Madde 3).

### Ne isteniyor

Iki yon birden. Ikisi de ayni cerceve bicimini kullanir
(`u32` big-endian uzunluk + UTF-8 JSON, `src/ai/protocol.rs`) ve **okul
cercevededir**, payload'da degil:

```
{ "id": "<ulid>", "capability": "insight.<ad>", "school": "<uuid>", "payload": {...} }

{ "status": "ok",  "id": ..., "school": ..., "payload": {...} }
{ "status": "err", "id": ..., "school": ..., "code": ..., "message": ... }
```

**a) Servisin cagirdigi operasyonlar (istemci-baslatimli akis).** [ACILDI --
2026-09-17, `f84c29d`.] Istenen sekil: istemci-baslatimli bir yetenek
cercevesi. O zaman koprunun istemci-baslatimli iki sekli vardi -- `ApiRequest`
(izin listesindeki GET yollari) ve `BlobRequest` (bayt) -- ve yazma icin bir
yol **yoktu**; oysa ZEKA'nin kendi satirlarini yazmasi ve okumasi gerekiyordu.
Istenen operasyon listesi (`service/src/store.py`):

| Yetenek | Ne yapar |
|---|---|
| `insight.schools.list` | Dagitimdaki **aktif** okullar (okul alani bos gider) |
| `insight.summary.upsert` | Gecelik ogrenci ozeti + dikkat maddeleri |
| `insight.recommendation.upsert` | Tavsiye satirlari (`rejected` sayisi doner) |
| `insight.segment.upsert` | Soru bilissel etiketleri |
| `insight.profile.upsert` | Ogrenci x boyut x etiket profili |
| `insight.run.upsert` | Kosu defteri (+ devreden ogrenciler, dusen moduller) |
| `insight.pending.list` | Onceki kosudan devreden ogrenciler |
| `insight.retention.sweep` | Suresi dolmus satirlarin supurulmesi |
| `insight.departed.purge` | Okuldan ayrilanin satirlarinin silinmesi |

Upsert'ler **500 satirlik gruplar** halinde gelir (`rows`); tavan asilirsa
`too_many_rows` beklenir. Bilinmeyen yetenek `unknown_capability`, bilinmeyen
alan `invalid_payload`, yetki yoksa `not_permitted` donmelidir: reddin kodu
tiplidir ve servis onu `CapabilityRefused` olarak yukseltir, sessizce yutmaz.

`zeka_*` tablolarinin DDL'i backend deposundadir
(`migrations/school/20260917000002_zeka.sql`) ve **okulun kendi
veritabaninda** durur: kiracı, veritabaninin kendisidir, satirda `school`
kolonu yoktur.

**b) Servisin servis ettigi yetenekler (sunucu-baslatimli akis).**
`src/constant.rs` icine yeni yetenek sabitleri ve onlari cagiran dagitim kodu:

> **DURUM (2026-09-18).** Sabitler ve dagitim kodu merged: `insight.student`
> ve `insight.refresh` gonderilir (`ai/insight.rs`, `web/insights.rs`);
> `insight.class` sabiti durur ama onu gonderen bir yol yoktur. Servis tarafi
> ayni gun baglandi: `handlers.wire()` uc adi da kaydeder ve acilista
> `capabilities.verify_dispatchable()` ilan ile dagitimi karsilastirir.

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

Backend'in bugun **cagirabildigi** yetenek adlari **yalnizca ikidir** (yani
ZEKA'ya `Request` gondermek icin kullanabilecegi adlar):

| Sabit | Deger | Kaynak |
|---|---|---|
| `AI_CHAT_CAPABILITY` | `chat.reply` | `src/constant.rs:568` |
| `AI_RAG_INDEX_CAPABILITY` | `rag.index` | `src/constant.rs:574` |

Yonlendirme **tam eslesmedir** (`src/ai/protocol.rs:91-94`): yaklasik eslesme,
on-ek eslesmesi ya da geri dusme yoktur. ZEKA baglanip `insight.student` ilan
etse bile, o adi arayan bir `Request` ureten kod backend'de **yoktur**.
(Servisin backend'i cagirdigi ters yon -- (a) -- 2026-09-17'de acildi; asagidaki
ifade yalnizca bu (b) yonunu anlatir.)

Bu, podcast servisinin yasadigi sorunun aynisidir: `podcast.submit`,
`podcast.status`, `podcast.result`, `podcast.cancel` adlarinin hicbiri backend
kaynaginda gecmez (`grep -rni "podcast" src/` -> 0 sonuc), bu yuzden podcast
protokol surumunu duzeltip **baglansa bile** hicbir is almaz.

### Olmadiginda ne kaybediliyor

Iki taraftan birden:

- Backend ZEKA'yi **hic cagiramaz**. Ogretmen "ZEKA analizi" ister -> koprude o
  istegi karsilayacak bir yol yoktur; "simdi hesapla" hicbir sey yapmaz.
- ZEKA **kendi satirlarini yazamaz** ve devreden ogrenci listesini okuyamaz.
  Kendi zamanlayicisiyla kosar ama cikti veremez: butun gece kosusu
  `CapabilityRefused` ile `partial` yazilir. Sessiz kalmaz -- ve tam da bu
  yuzden acik bir maddedir.

ZEKA'nin hesap motoru bu iki kapi olmadan da **calisir ve test edilir**
(`--dry-run` cagrilari toplar); kaybedilen sey, sonucun okulun veritabanina
inmesidir.

---

## insight.report -- okul raporu BELGESI (sunucu-baslatimli; IKI TARAF DA ACILDI 2026-09-18)

**Sahibi: backend'deki `InsightDoors` hatti.** Iki taraf da yerinde; eksik
kalan bir sey yok:
servis ilan eder ve dagitir (`handlers.report`; acilista
`capabilities.verify_dispatchable()` denetler), backend'in sabiti
(`constant.rs:645`), dagitimi (`ai/insight.rs::report`) ve kapisi
(`POST /runs/{run_day}/report`, `web/insights.rs`) yerindedir. `insight.class`
icin durum ayni degildir: o ad hala ilan edilir ama gonderilmez (Madde 3).

### Ne isteniyor

Backend, okulun `zeka_*` satirlarini **kendi okur** ve tek bir
`insight.report` istegiyle gonderir; servis belgeyi uretir ve cevap
cercevesinde **HTML metni olarak** dondurur. Blob yuklemesi yok, depo yok:
belge, servisin hicbir okuma yapmadigi tek `insight.*` isleyicisidir.

**Istek payload'i.** Cercevedeki `school` = tireli okul uuid'si. Satirlar ZEKA'nin
depo yoluyla yazdigi bicimdir -- backend'in kendi yapilari (`db/insight.rs`
`SummaryRow` / `RecommendationRow` / `ProfileRow` / `RunRow`), yani ikinci bir
esleme yok:

| Alan | Tip | Ne |
|---|---|---|
| `kind` | str | Zorunlu; sunulan tek deger `okul` |
| `run_day` | str | `YYYY-MM-DD` (TR gunu); yoksa en yeni kosu satirindan turetilir |
| `requested_by` | str | Belgeyi isteyen mudur; okuma yapilmadigi icin yalniz log'a yazilir |
| `school` | nesne | `{id, name}`; `name` belge BASLIGIDIR, `id` cercevedeki uuid ile aynidir. `slug` yok |
| `classes` | liste | `[{id, name}]`: okulun butun subeleri, ad sirasinda. Satirlardaki `marks.classes` KIMLIK tasir; tabloya yazilan GORUNEN ad bu haritadan gelir. Kabul edilen ikinci bicim `class_names: {<id>: "<ad>"}` (`classes` varsa o kazanir) |
| `summaries` | liste | `zeka_student_summary` satirlari (`attention` listesi dahil) |
| `recommendations` | liste | `zeka_recommendation` satirlari |
| `profiles` | liste | `zeka_student_segment_profile` satirlari |
| `runs` | liste | `zeka_run` satirlari (`run_day` alani belgenin gununu verir) |

Satirlarda `school` GONDERILMEZ: ZEKA onu hic yazmaz, cercevede gelir ve
servis her satira kendisi damgalar (tek kimlik kaynagi). Yine de bir satir
baska bir okul tasirsa istek reddedilir -- damgalamak degil, reddetmek.

**Sube ETIKETI (2026-09-18 canli kusuru).** Belge artik ham sube kimligini
YAZMAZ: `marks.classes`teki bir kimlik `classes` haritasinda varsa GORUNEN ad,
yoksa `Adı bilinmeyen şube` basilir. Harita hic yoksa (eski backend) ayni
yedek etiket kullanilir; belge kurulur, kimlik gorunmez. Siralama gorunen ADA
gore yapilir. Sayilar etiketten bagimsizdir: kovalar kimlige gore kurulur,
"Sube" sayaci kimlikten sayilir -- adı bilinmeyen iki sube tek satira
dusmez.

**Cevap payload'i** (belge cercevenin ICINDE gider):

```json
{ "kind": "okul", "run_day": "2026-09-18", "format": "html",
  "html": "<!DOCTYPE html>...", "byte_size": 12345, "truncated": false,
  "notes": ["Siralama yoktur. ...", "Kaniti olmayan satir rapora girmez. ..."],
  "coverage": { "rows": {"summaries": 42, "recommendations": 7,
                          "profiles": 11, "runs": 1}, "empty": false } }
```

- `byte_size` = `html`in UTF-8 bayt uzunlugu; `truncated` bugun her zaman
  `false` (sinir asilirsa belge KESILMEZ, asagidaki kodla reddedilir).
- `notes` paketin kendi kapsam/sinir cumleleridir: backend onlari oldugu gibi
  gosterir, kendi cumlesini uydurmaz.
- `coverage` sozlesme disi ek alandir (refresh'in `status`u gibi: serde
  bilinmeyen alani yok sayar): ham satir sayilari + paketin `empty` hukmu,
  "belge neden bos" sorusu log'dan da cevaplanabilsin diye.

### Redler (backend'in HTTP durumuna eslemesi icin)

| Kod | Ne zaman | Onerilen esleme |
|---|---|---|
| `bad_request` | Sozlesmeye uymayan payload: sunulmayan/bilinmeyen `kind`, bozuk `run_day`, liste olmayan satir alani, cerceveyle celisen okul | 400 |
| `insufficient_rows` | Dort liste de bos: uretilecek belge yok; bos belge cevap degildir | 404/409 -- ekran kendi "yetersiz veri" durumunu gostersin |
| `document_too_large` | HTML 4 MiB'i asiyor (cerceve kapagi 8 MiB) | 413 |
| `internal` | Paket belgeyi kuramadi ya da cizemedi | 500/502 |

### Bugunun sinirlari

- **Dort rapor tipinden yalniz `okul` sunulur.** `ogrenci` / `ogretmen` /
  `ham` icin istek sozlesmesi yok (payload `student`, `teacher` ve
  `question_segment` tasimaz); istek gelirse `bad_request` doner ve yarim
  belge uretilmez.
- **Kapatilmis tavsiyeler.** Paketin kapatma kapisi satirda `dismissed_at`
  arar; backend'in `RecommendationRow`'u alani tasimaz (kapatma yazimi bugun
  hic yok). Kapatma ozelligi gelirse ya okunan satir `dismissed_at` tasimali
  ya backend kapatilmis satirlari gondermemeli -- yoksa kapatilmis kart
  rapora geri duser.
- **HTML siniri 4 MiB** (`AI_MAX_FRAME_BYTES // 2`): belge cevap cercevesinin
  icinde gider ve JSON kacislarina da yer kalmali.

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

## Madde 3 -- Kullanici (kadro) listeleme yolu yok

### Ne isteniyor

Okul listesi Madde 1a'dadir (`insight.schools.list`). Burada kalan tek sey
**kadro**: rotalar **vardir** ama izin listesinde **degildir**:

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

Sonucu sudur: servis, o okullarda **kimlerin bulundugunu** ogrenebilecegi bir
yola sahip degildir. Backend ZEKA'ya is gonderseydi kullanici `Request`
cercevesinde gelirdi -- ama Madde 1 yuzunden backend ZEKA'ya is gondermiyor.
Yani ZEKA'nin kendi kendine kosmasi gerekiyor ve kendi kendine kosmak icin bir
liste gerekiyor.

### Bugun nasil cozuluyor

**Okul listesi:** artik backend'den (`insight.schools.list`, Madde 1a) gelir;
`ZEKA_SCHOOLS` yalnizca bir **operator filtresidir** (bos birakilirsa
dagitimdaki butun aktif okullar islenir). Yani "yeni okul gorunmez" riski okul
tarafinda kapandi; geriye **kadro** kaldi.

**Ogrenci listesi:** hala yapilandirmadan. `service/src/config.py` icinde:

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
- **Yeni okul gorunmez** — okul listesi backend'den geldigi icin (Madde 1a)
  bu risk kapandi; kalan risk, operatör filtresi (`ZEKA_SCHOOLS`) elle daraltilmis
  birakilirsa ayni sessizligin geri gelmesidir: "filtreye takilmayan okul" ile
  "sorunsuz islenen okul" ayni sessizlikte gorunur.
- **Isletme maliyeti.** Kapsam, kod deposunda degil `compose.yaml` ortam
  degiskeninde yasar; her mevcut degisikligi bir dagitim islemi haline gelir.

---

## Ozet tablo

| # | Istenen | Kaynak dosya | Olmazsa kaybedilen |
|---|---|---|---|
| 1 | Dokuz `insight.*` operasyonu (yazma + liste + supurme) **ve** `insight.student` / `insight.class` / `insight.refresh` sabitleri + dagitim kodu | `src/constant.rs`, `src/ai/` | ZEKA satirlarini **yazamaz** (gece kosusu `partial`); backend ZEKA'yi **hic cagiramaz**, istege bagli her senaryo duser. Sahibi: `InsightDoors`. **Durum 2026-09-18: student + refresh ACILDI; sinif hala acik (Madde 3).** |
| 2 | 9 sinav yolu (+3 sinif/ders yolu) izin listesine | `src/constant.rs:656-676` | **Madde analizi, konu karnesi, sinif isi haritasi** hic uretilemez |
| 3 | `GET /users/search` izin listesine (okul listesi Madde 1a'da) | `src/constant.rs:656-676` | Ogrenci kadrosu elle tutulur; yeni ogrenci **sessizce** gorunmez |
| 4 | `insight.report` dagitim kapisi: backend kendi `zeka_*` satirlarini okuyup gondersin (bkz. `## insight.report`) | `src/ai/`, `src/constant.rs`, `src/web/` | **ACILDI 2026-09-18** (`constant.rs:645`, `ai/insight.rs::report`, `POST /runs/{run_day}/report`); servis tarafi ayni gun baglandi |

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
