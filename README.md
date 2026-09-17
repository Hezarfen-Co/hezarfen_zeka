# hezarfen-ZEKA

Öğrenci analizi ve tavsiye servisi. Podcast ve Çelebi ile **aynı desende**
çalışır: kendi konteynerinde durur, **port açmaz**, backend'in QUIC köprüsüne
dışa arama yapar.

**Veritabanı bağlantısı yoktur.** Ne bir sürücü, ne bir bağlantı dizesi, ne bir
sorgu — uykuda bile yoktur ve olmayacaktır. Okul verisini köprüden **okur**,
hesapladığı satırları köprüye **yazar**. Aradaki her şey — hesap modülleri,
segmentasyon, kural katalogu — bu depodadır.

---

## Backend ekibi için hızlı bakış

Bağlamak için gereken iki şey:

```sh
AI_SHARED_TOKEN=<backend ile aynı sır>
LLM_API_KEY=<segment hattı için; OpenAI uyumlu her sağlayıcı olur>
```

```sh
podman compose up -d
```

Port açmaz, `hezarfen_backend_default` ağına katılır ve backend'e dial-out
eder. Köprü adresi varsayılanlıdır (`AI_BRIDGE_HOST`/`AI_BRIDGE_PORT`);
değiştirmek gerekmedikçe yazılmaz.

ZEKA'nın yazdığı dokuz `zeka_*` tablosu **her okulun kendi veritabanında**
durur. DDL'i backend deposundadır:
`hezarfen_backend/migrations/school/20260917000002_zeka.sql`. ZEKA o dosyayı
ne yazar ne uygular — yalnız "şu satırları yaz" der.

Okul listesi backend'den gelir (`insight.schools.list`). `ZEKA_SCHOOLS` bir
operatör **filtresidir**: boş bırakılırsa dağıtımdaki tüm aktif okullar
işlenir, doluysa yalnız listelenenler.

Okul veritabanının **adı okulun uuid'sinden** türer (`tenant.rs:112` →
`{control}_school_{uuid.simple}`), slug'dan **değil**. Demo okulu için:

```
hezarfen_control_school_0193000000007000800000000000de70
```

---

## 1. Veriyi nasıl çeker — REST'e bağlanmaz

Yapay zekâ servisleri sistemden veri çekerken **REST'i taklit eden köprü
yapısını** kullanır. Servis kendi açtığı bir QUIC akışına `ApiRequest` yazar,
backend o yolu kendi içinde dağıtır ve `ApiResponse` döner. Ortada HTTP yoktur.

```
ZEKA ──QUIC hab/2──> backend
      ApiRequest{school, path, query, on_behalf_of}
      ApiResponse{outcome, body}
```

Önemli ayrıntı: **veri okuma akışlarını servis başlatır**, üstelik kontrol
akışından sonra istediği zaman. Bu yüzden ZEKA, backend kendisine iş
göndermesini beklemeden kendi takvimiyle çalışabilir.

Protokol sürümü **`hab/2`** (`constant.rs:530`). Podcast ve Çelebi `hab/1`
kullanıyor ve bu yüzden **hiç bağlanamıyorlar**; ZEKA o hatayı tekrarlamaz ve
bir test sabiti pinler.

### Veri erişim cephesi

Hesap modülleri veritabanını da köprüyü de görmez. Yalnız `Source` arayüzünü
görür — sekiz yöntem, izin listesindeki 19 yola karşılık:

| Yöntem | Köprü yolu |
|---|---|
| `profile` | `/users/{id}/profile` |
| `marks` | `/marks/{user}` |
| `attendance` | `/attendance/{user}` |
| `pomodoro` | `/pomodoro/{user}` |
| `homework_report` | `/homework/report/{user}` |
| `homework_list` | `/homework` |
| `notes` | `/notes` |
| `course_notes` | `/course-notes?course=` |

Bu arayüzde **yemek, ödeme, diyet, mesaj ve sohbet verisine erişen hiçbir
yöntem yoktur.** Bu bir kural değil, **yapısal kapıdır**: hesap modülü o veriyi
isteyemez çünkü çağıracağı fonksiyon mevcut değildir. `test_guard.py` yasaklı
terimleri hem arayüzde hem iki uygulamada hem de `compute/` altındaki tüm
modüllerde tarar.

Gerekçe etik: diyet profili özel nitelikli veridir, ödeme defteri sosyoekonomik
vekildir. Kantin borcunu bugün öğretmen bile göremiyor; öğretmene tavsiye üreten
bir modele o veriyi vermek, erişim kontrolünü modelin içinden dolanmak olurdu.

---

## 2. Nereye yazar — köprüye, yetenek çağrısıyla

İki yön de aynı köprüdedir:

* **Okuma** (okulun kendi API'si): `ApiRequest` izin listesi, §1.
* **Yazma ve depo okumaları:** `insight.*` **yetenek çağrıları**. Servis
  `hab/2` üzerinde taze bir istemci-başlatımlı akış açar ve çerçeveyi yazar:

```
{ "id": "<ulid>", "capability": "insight.<ad>", "school": "<slug>", "payload": {...} }

{ "status": "ok",  "id": ..., "school": ..., "payload": {...} }
{ "status": "err", "id": ..., "school": ..., "code": ..., "message": ... }
```

Okul **çerçevededir**, payload'da değil: backend slug'ı çözer ve her ifadeyi o
okulun kendi veritabanında koşturur. Reddin kodu tiplidir (`unknown_school`,
`not_permitted`, `invalid_payload`, `too_many_rows`, `unavailable`, …) ve
`CapabilityRefused` olarak yükselir; `status: "err"` asla başarı sayılmaz.

### Servisin çağırdığı yetenekler

| Yetenek | Ne yapar |
|---|---|
| `insight.schools.list` | Dağıtımın **aktif** okulları (tek dağıtım ölçekli çağrı: okul alanı boş gider) |
| `insight.summary.upsert` | Gecelik öğrenci özeti + dikkat listesi |
| `insight.recommendation.upsert` | Tavsiye satırları (kanıtsız satır reddedilir) |
| `insight.segment.upsert` | Soru bilişsel etiketleri |
| `insight.profile.upsert` | Öğrenci × boyut × etiket profili |
| `insight.run.upsert` | Koşu defteri (+ devreden öğrenciler, düşen modüller) |
| `insight.pending.list` | Önceki koşudan devreden öğrenciler |
| `insight.retention.sweep` | Süresi dolmuş satırların süpürülmesi |
| `insight.departed.purge` | Okuldan ayrılanın satırlarının silinmesi |

Yazma **500 satırlık gruplar** hâlindedir; bir grup ikinci denemede de düşerse
atlanır, `warn` loglanır ve `WriteReport.status` `partial` olur — koşu defterine
`store` olarak yazılır. Sessiz başarı yoktur.

### Servisin servis ettiği yetenekler

Backend'in ZEKA'yı çağırdığı adlar (§5 madde 1, `src/capabilities.py`):

| Yetenek | Ne yapar |
|---|---|
| `insight.student` | Tek öğrenci için hesap + tavsiye |
| `insight.class` | Bir sınıf (şube × ders) için toplu analiz |
| `insight.refresh` | Okul çapında yeniden koşu (parti işi) |

`insight.refresh` ayrıca ZEKA'nın **kendi zamanlayıcısı** tarafından da
çağrılır: hesaplar backend istemeden de koşar, yeteneğin tanımlı olması yalnız
"istek üzerine tetikleme"yi açar.

### Tablolar

Dokuz tablo, hepsi `zeka_` önekli, hepsi okulun kendi veritabanında:

| Tablo | Ne tutar |
|---|---|
| `zeka_student_summary` | öğrenci başına gecelik özet (PK: `student`) |
| `zeka_attention_item` | dikkat listesi, tetikleyici başına bir satır (`ord` ile sıralı) |
| `zeka_recommendation` | tavsiyeler + kapatma izi |
| `zeka_run` | gece işinin defteri (PK: `run_day`) |
| `zeka_run_pending` | bütçe dolunca kalanlar |
| `zeka_run_failed_module` | hata veren modüller |
| `zeka_question_segment` | soru başına bilişsel etiket (PK: `question`) |
| `zeka_question_segment_dimension` | üretim/deneysel boyut ayrımı |
| `zeka_student_segment_profile` | öğrenci × boyut × etiket, `contrast` dahil |

**Satırda `school` alanı yoktur:** kiracı, veritabanının kendisidir. Kimlikleri
**yazan taraf üretir** — uuid7'yi backend mints eder, ZEKA göndermez.

**Yabancı anahtarlar tek yönlü.** `zeka_*` tabloları `app_user`, `course`,
`subject`, `exam`, `exam_question`'a bakar; okul tablolarının hiçbiri
`zeka_*`'a bakmaz. DDL dosyası silinse okul şeması olduğu gibi ayakta kalır.

**ZEKA mevcut okul tablolarının hiçbirine yazmaz.** Yazabildiği tek şey yukarıdaki
dokuz tablodur; başka bir tabloyu güncelleyen bir yol yoktur.

Üzerine yazma **upsert**'tir: uygulamanın yazdığı alanlar (`dismissed_at`,
`dismissed_by`, `dismiss_reason`) korunur. Tam değiştirme kullansaydık her gece
kullanıcının kapatma kaydı silinirdi.

### Depo katmanı

`src/store.py` — `BridgeStore`: **okul dizini + okul başına depo** ve satır
payload'larını kuran fonksiyonlar. Zamanlayıcı `store_for(school)` ile o okulun
deposunu ister; dönen nesne `pipeline`'ın beklediği sekiz yöntemi taşır.
Paylaşılan bir depo yoktur ve olmamalıdır: yanlış okula yazmanın en kolay yolu
paylaşılan bir nesnenin okul alanını unutmaktır; burada okul nesnenin
kimliğindedir.

`pipeline.py` ve `scheduler.py` hangi taşımayı kullandıklarını **bilmez**; ikisi
de aynı sekiz yöntemi çağırır. Satırların şekli backend'in kolon adlarıyla
aynıdır — iki taraf tek sözlüğü konuşur.

---

## 3. Bugün ne üretiyor

| Ürün | Durum |
|---|---|
| Not karnesi | ✅ **ders** düzeyinde (konu kırılımı yok) |
| Çalışma düzeni aynası | ✅ |
| Teslim takvimi | ✅ kısmi (erteleme profili yok) |
| Sınıf ısı haritası | ✅ ders × şube |
| Dikkat listesi | ✅ 4 tetikleyiciden 3'ü |
| Soru segmentasyonu | ✅ 3 üretim boyutu + 1 deneysel |

Dikkat listesi tasarım gereği **tek bir risk skoru üretmez**. Tetikleyiciler
ayrı ayrı listelenir, sıralama **alfabetiktir** (şiddete göre değil), her madde
kanıtına bağlıdır. Bir çocuğa "riskli" etiketi takmanın pedagojik savunması
yoktur ve literatür turu bu ürün için doğrulanmış nedensel kanıt bulamamıştır.

Tavsiyeler kanıtsız kurulamaz: `Recommendation` nesnesi `evidence`, `rule_id`
ve `computed_at` olmadan `ValueError` fırlatır. Depo katmanı ikinci kez
kontrol eder; kanıtsız satır reddedilir ve sayısı rapora geçer.

### `contrast` — segment profilinin var olma sebebi

Ham doğruluk bir **ayrım ölçüsü değildir**: bir öğrencinin herhangi bir
segmentteki doğruluğu büyük ölçüde genel yeteneğini yansıtır. İyi öğrenci her
segmentte yüksek çıkar. Kurallar **yalnız** `contrast = accuracy −
overall_accuracy` üzerinden ateşler, `accuracy` üzerinden **asla**.

---

## 4. Bugün ne üretemiyor ve neden

Servis bunları **sahte uygulamayla doldurmaz**; çıktısında eksik olduğunu
gerekçesiyle raporlar (`unavailable_triggers`, `unavailable_rules`).

| Eksik | Sebep |
|---|---|
| Madde analizinin tamamı | İzin listesinde sınav yolu yok → ham cevap alınamıyor |
| Konu kırılımı | Aynı sebep |
| Erteleme profili | Ödev raporunda `submitted_at` yok |
| Devamda zaman ekseni | Uç satır değil **sayaç** döndürüyor |
| Veli haftalık özeti | `parent_link` yok, velinin kim olduğu çözülemiyor |

Tohum verisinde 216.633 sınav cevabı ve kasıtlı olarak bozuk maddeler var.
Yani **bulunacak şey mevcut, bulunacak yol yok.**

---

## 5. Backend ekibinden beklenenler

`service/docs/BACKEND-GEREKSINIMLERI.md` gerekçeleriyle içerir:

1. **`insight.*` kapıları backend'de yok.** Bugün backend yalnız `chat.reply`
   ve `rag.index` tanıyor; ZEKA'nın çağırdığı dokuz `insight.*` operasyonu ve
   servis ettiği üç yetenek kapı bekliyor. Bu iş backend'de **`InsightDoors`**
   hattının sahibindedir; ZEKA ona karşı yazıldı ve zarf donduruldu.
2. **Sınav yolları izin listesinde yok.** Madde analizi için gereken 9 yol
   listelenmiştir.
3. **Öğrenci listeleme yolu yok.** Okul listesi artık köprüden
   (`insight.schools.list`), ama kimlerin işleneceği hâlâ yapılandırmadan
   çözülüyor. Dönem ortası kayıt olan öğrenci görünmez, ayrılan silinmez.

Bu maddeler **başka bir ekibin sorumluluğundadır.** ZEKA onlarsız da kendi
takvimiyle çalışır, yalnız kapsamı dardır.

---

## 6. Tohum verisi

Depoda **tohumun kendisi yok, üreticisi var.** ~170 MB'lık üretilmiş bir veri
seti GitHub'ın tek dosya sınırını da aşıyor ve deterministik üretildiği için
depoda tutmanın kazandıracağı bir şey yok.

```sh
python generator/main.py --scale full --out /tmp/seed
```

Üretilen: demo okulunun bütün veri seti (`MANIFEST.json` satır sayılarıyla,
`_seed_manifest.json` gizli gerçekle) ve 48 bütünlük sorgusu.

| | |
|---|---|
| okul | `hezarfen-demo` / `01930000-0000-7000-8000-00000000de70` |
| öğrenci | 250 (563 kullanıcı: + 24 öğretmen, 285 veli) |
| kapsam | 2025-09-07 → 2026-04-13, 27 öğretim haftası, 2 ay kalmış |
| ölçüm | 24 öğrenme + 14 arketip + 25 davranış hedefi |
| kasıtlı bozukluk | 8 tür (analizin bulması *gereken* şeyler) |

**Yükleme bu deponun işi değildir.** Tohum backend ekibine verilir; okulu
backend oluşturur ve göç ettirir. ZEKA hiçbir şema uygulamaz, hiçbir veritabanı
kullanıcısı istemez.

---

## 7. Çalıştırma

```sh
# testler
cd service && python -m unittest discover -s tests -t .

# hattı fikstürle uçtan uca koştur (köprü gerekmez)
python -m src.cli run --school hezarfen-demo --source file \
    --fixtures fixtures/demo --dry-run
```

`--dry-run` yazmayı `RecordingCaller`'a çevirir: çağrılar toplanır, hiçbiri
kabloya çıkmaz. Hiçbir test gerçek bir veritabanı istemez — servisin açacağı bir
bağlantı yoktur; köprü testleri gerçek QUIC soketleriyle, sahte bir sunucuya
karşı koşar.

**HTTP sunucusu yoktur ve olmayacaktır.** Çelebi'nin geliştirme amaçlı HTTP
sunucusu üretim imajında duruyor ve denetimde kimlik doğrulamasız yüzey olarak
işaretlendi; burada geliştirme yüzeyi komut satırı aracıdır.

### Doğrulama

| Ne | Nasıl |
|---|---|
| Tüm paket | `python -m unittest discover -s tests -t .` |
| Köprü | `tests/test_bridge_live.py` — gerçek QUIC, sahte sunucu |
| Yazma katmanı | `tests/test_store.py` — `RecordingCaller` ile hat uçtan uca |

Yazma katmanının testi **sahte bir çağıranla** koşar ve beklenen çerçeveleri
pinler: capability adı, okulun çerçevede gittiği, satır şekilleri. Ölçülen
sözleşme budur — backend'e çıkan tur bu depoda test edilmez, backend'in kendi
kapı testleri ve `InsightDoors` hattı onu ölçer.

---

## 8. Sınırlar — dürüst liste

- **Gerçek backend'e hiç bağlanılmadı.** Köprü, backend'in protokolünü taklit
  eden sahte bir sunucuya karşı kanıtlandı (gerçek QUIC bağlantısı). Sahte
  sunucu Rust kaynağı okunarak yazıldı; kaynak yanlış okunduysa test yanlış
  davranışı doğrular. Backend ayağa kalktığında yeniden sınanmalıdır.
- **`insight.*` kapıları backend'de henüz tanımlı değil** (§5 madde 1). Servis
  kendi takvimiyle çalışır; istek üzerine tetikleme kapılar gelene kadar
  kapalıdır.
- **Sertifika düz HTTP ile çekiliyor** (podcast ve Çelebi ile aynı).
  `AI_TLS_FINGERPRINT` verilirse parmak izi doğrulanır; verilmezse her açılışta
  uyarı basılır. Üretimde verilmelidir.
- **`adim_sayisi` boyutu deneyseldir.** El yazısı probda 0,607 kararlılık aldı;
  tohumda çok adımlılık metne açıkça yazıldığı için oradaki yüksek skor bizim
  kendi kolay sınavımızdır. Etiketlenir, saklanır, **aşağı akışta okunmaz**.
- **Ödev tetikleyicisi kohort medyanı olmadan ateşlemez** (fail-closed).
  `pipeline.py` bugün o medyanı geçirmiyor; iki satırlık iş, açık madde.
- **Ölçek ölçülmedi.** En büyük gerçek koşu 13 öğrenci. 250 öğrencide gece
  bütçesinin nereye oturduğu bilinmiyor.

---

## 9. Yapı

```
generator/   tohum üreticisi (deterministik veri seti + bütünlük sorguları)
paket/       sunucuya verilecek paket — OKU.md
service/
  src/       köprü (bridge.py), depo (store.py), Source, capabilities,
             compute/, segment/, report/, scheduler, pipeline
  tests/     birim + canlı köprü testleri
  docs/      çıktı sözleşmesi, backend gereksinimleri, ölçüm raporları
spec/        şema, senaryo, modüller, segmentasyon araştırması
tools/       doğrulayıcı, ölçüm araçları
```

Frontend ve backend ekipleri için tek belge: **`service/docs/CIKTI-SOZLESMESI.md`**
— üretilen her tablo, alan ve kural kimliği. Segment kurallarının ölçülmüş
isabeti: `service/docs/SEGMENT-CIKTI.md`.

---

## 10. Sırlar

`.env` gitignore'ludur ve depoya **girmez**. `compose.yaml` yalnızca
interpolasyon içerir, literal sır taşımaz. `AI_SHARED_TOKEN` ve `LLM_API_KEY`
`:?` ile **zorunludur**; eski `DEEPSEEK_API_KEY` adı artık **reddedilir** (temiz
kesim): anahtarsız bir servis ayağa kalkıp hiçbir şey yazmadan "çalışıyor"
görünürdü. Açılışta bir satır hata, günler sonra boş bir tablo yerine.

Paylaşılan sır hiçbir yerde loglanmaz. Servisin koruyacak bir veritabanı
parolası yoktur — öyle bir parola artık hiçbir yerde geçmez.

---

## 11. Dağıtım — VPS, yeşil push'ta otomatik

`.github/workflows/main.yml` — ailedeki Çelebi deploy'uyla **aynı şekil**:

```
Katman 1..5 (paralel)  ->  Build and test  ->  Deploy (SSH, health gate, tag rollback)
```

| İş | Ne yapar |
|---|---|
| **Katman 1..5** | `ci.yml`'deki beş katmanın kendisi; komutlar birebir aynı. Hepsi yeşil olmadan imaj üretilmez. |
| **Build and test** | İmajı bu koşunun SHA'sıyla derler (`localhost/hezarfen-zeka:$GITHUB_SHA`), imaj tarball'ı + `compose.yaml` + systemd unit'i + `tag` dosyasını `release` artefaktı olarak yükler (30 gün). |
| **Deploy** | SSH: kapasite ön kontrolü → imajı yükle → `stack.env`'in `HEZARFEN_TAG`'ini bu SHA'ya çevir → compose + unit'i kur → `systemctl --user restart` → **servisin kendi sağlık betiğiyle** doğrula → olmazsa önceki tag'e dön → bağımsız son doğrulama. |

**Yeşil bir `main` push'u servisi otomatik dağıtır.** Elle yeniden dağıtım
(süiti tekrar koşmadan, en yeni yeşil build'i):

```bash
gh workflow run main.yml --ref main
```

`main` dalına push yalnızca `main.yml`'de koşar; **diğer dallar ve pull
request'ler** beş katmanı `ci.yml`'den alır (aynı kapı iki kez koşmaz).

### Ön koşullar (bir kez, depo/sunucu dışında yapılır)

1. **Repo secret'ları** — backend ve frontend deploy'unun kullandığı üç isim:
   `SSH_PRIVATE_KEY`, `SSH_HOST`, `SSH_USER`.
2. **Sunucuda `loginctl enable-linger <kullanıcı>`** — kullanıcı unit'i için.
3. **Sunucuda podman + bir compose sağlayıcı** (`podman compose version`).
4. **Operatörün ayar dosyası** — deploy onu **oluşturmaz, yazmaz**, yalnız
   varlığını kontrol eder ve izni 0600'e çeker:

   ```bash
   mkdir -p ~/hezarfen_zeka
   cp deploy/hezarfen_zeka.env.example ~/hezarfen_zeka/hezarfen_zeka.env
   # AI_SHARED_TOKEN / LLM_API_KEY zorunlu
   chmod 0600 ~/hezarfen_zeka/hezarfen_zeka.env
   ```

5. **Backend tarafı açık olmalı**: `hezarfen_backend.env` içinde
   `AI_QUIC_ADDR=0.0.0.0:8090` ve `AI_SHARED_TOKEN` bu köprününkiyle **aynı**.
   Bu bir **kapı değildir**: ZEKA backend yokken çıkmaz, bekler ve backend
   düzeltilince kendiliğinden kaydolur (bkz. `docs/DAGITIM.md`). Deploy bunu
   yalnız **uyarı** olarak bildirir — kayıt şartı aransaydı ZEKA'nın kendi
   tanımından daha sıkı bir kapı uydurmuş olurduk.

   Kapı olmayan şey **davranıştır** da: `insight.*` çağrıları kapılar
   tanımlanana kadar reddedilir (§5 madde 1); servis ölür değil, koşusunu
   `partial` yazar ve devam eder.

### Kapı, rollback ve kapsam

- **Sağlık kapısı = `scripts/saglik.py`**, konteynerde. Ölçtüğü şey köprü
  sürecinin **yaşaması**; backend'e *kayıtlı* olduğunu ölçmez — bu bilinçli
  (backend'in her yeniden dağıtımı ZEKA'yı `unhealthy` işaretlemesin diye).
- **Kapasite ön kontrolü**: ≥ 512 MB boşta RAM ve ≥ 2 GB disk; yetmezse
  **nedeniyle birlikte reddeder** (ölçülen: imaj 152 MB, model yok).
- **Rollback**: `previous_tag`'e döner; ilk dağıtımda geri dönülecek imaj
  yoksa stack durdurulur (`down`, `-v` **yok** — `zeka-fixtures` volume'u kalır).
- **Manuel yol duruyor**: `cd service && podman compose up -d` (bkz. §7) —
  deploy'a ihtiyaç duymadan tek makinede kaldırmak için değişen bir şey yok.
