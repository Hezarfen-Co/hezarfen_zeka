# hezarfen-ZEKA

Öğrenci analizi ve tavsiye servisi. Podcast ve Çelebi ile **aynı desende**
çalışır: kendi konteynerinde durur, **port açmaz**, backend'in QUIC köprüsüne
dışa arama yapar.

Okul verisini köprüden **okur**, kendi çıktısını okulun veritabanındaki dokuz
`zeka_*` tablosuna **yazar**. Aradaki her şey — hesap modülleri, segmentasyon,
kural katalogu — bu depodadır.

---

## Backend ekibi için hızlı bakış

Bağlamak için gereken üç şey:

```sh
AI_SHARED_TOKEN=<backend ile aynı sır>
ZEKA_PG_DSN=postgres://<kullanıcı>:<parola>@<host>:5432/<kontrol_veritabanı>
LLM_API_KEY=<segment hattı için; OpenAI uyumlu her sağlayıcı olur>
```

```sh
podman compose up -d
```

Port açmaz, `hezarfen_backend_default` ağına katılır ve backend'e dial-out eder.

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

Protokol sürümü **`hab/2`** (`constant.rs:515`). Podcast ve Çelebi `hab/1`
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

## 2. Nereye yazar

Dokuz tablo, hepsi `zeka_` önekli, hepsi okulun kendi veritabanında:

| Tablo | Ne tutar |
|---|---|
| `zeka_student_summary` | öğrenci başına gecelik özet (PK: `student`) |
| `zeka_attention_item` | dikkat listesi, tetikleyici başına bir satır |
| `zeka_recommendation` | tavsiyeler + kapatma izi |
| `zeka_run` | gece işinin defteri (PK: `run_day`) |
| `zeka_run_pending` | bütçe dolunca kalanlar |
| `zeka_run_failed_module` | hata veren modüller |
| `zeka_question_segment` | soru başına bilişsel etiket (PK: `question`) |
| `zeka_question_segment_dimension` | üretim/deneysel boyut ayrımı |
| `zeka_student_segment_profile` | öğrenci × boyut × etiket, `contrast` dahil |

DDL: `service/schema/postgres/school/20260916000001_zeka.sql` — backend'in
`migrations/school/` klasörüne **eklenir**, mevcut dosyalara dokunulmaz.

**Yabancı anahtarlar tek yönlü.** `zeka_*` tabloları `app_user`, `course`,
`subject`, `exam`, `exam_question`'a bakar; okul tablolarının hiçbiri
`zeka_*`'a bakmaz. Dosyayı silseniz okul şeması olduğu gibi ayakta kalır.
`tools/check_pg_schema.sh` bunu ayrıca sınar ve ters yönlü tek bir FK bulursa
hata verir.

**ZEKA mevcut 69 tablonun hiçbirine yazmaz.** `store_pg.TABLES` bu kuralın
makine tarafından okunabilir hâlidir.

### Depo seçimi

Tek ölçüt `ZEKA_PG_DSN`: doluysa Postgres, boşsa (eski) SurrealDB.
İki ayrı "mod" bayrağı yok — bayrakla adres ters düştüğünde hangisinin
kazandığı tahmin işine döner. Bkz. `src/store_factory.py`.

`pipeline.py` ve `scheduler.py` hangi depoya yazdıklarını **bilmez**; ikisi de
aynı sekiz yöntemi çağırır. Geçişin hesap kodundaki maliyeti sıfırdı.

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
ve `computed_at` olmadan `ValueError` fırlatır. Depolama katmanı ikinci kez
kontrol eder.

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

1. **ZEKA'nın yetenekleri backend'de tanımlı değil.** Backend yalnız
   `chat.reply` ve `rag.index` tanır ve eşleşme tamdır. ZEKA bağlansa bile hiç
   iş almaz — podcast'in yaşadığı sorunun aynısı. Bu olmadan **istek üzerine**
   çalışan her senaryo kapalıdır. (Kendi takvimiyle çalışması etkilenmez.)
2. **Sınav yolları izin listesinde yok.** Madde analizi için gereken 9 yol
   listelenmiştir.
3. **Okul ve kullanıcı listeleme yolu yok.** ZEKA kimleri işleyeceğini
   köprüden öğrenemiyor; bugün yapılandırmadan çözülüyor. Dönem ortası kayıt
   olan öğrenci görünmez, ayrılan silinmez.

Bu maddeler **başka bir ekibin sorumluluğundadır.** ZEKA onlarsız da kendi
takvimiyle çalışır, yalnız kapsamı dardır.

---

## 6. Tohum verisi

Depoda **tohumun kendisi yok, üreticisi var.** 101 MB'lık bir SQL dosyası
GitHub'ın tek dosya sınırını aşıyor ve deterministik üretildiği için depoda
tutmanın kazandıracağı bir şey yok.

```sh
python generator/main.py --scale full --postgres --out cikti/
```

Üretilen: `pg_school.sql` (576.487 satır), `pg_control.sql` (okul + 563 kişi),
`pg_dogrula.sql` (48 bütünlük denetimi), ve yanında SurrealQL sürümü.

| | |
|---|---|
| okul | `hezarfen-demo` / `01930000-0000-7000-8000-00000000de70` |
| öğrenci | 250 (563 kullanıcı: + 24 öğretmen, 285 veli) |
| kapsam | 2025-09-07 → 2026-04-13, 27 öğretim haftası, 2 ay kalmış |
| ölçüm | 24 öğrenme + 14 arketip + 25 davranış hedefi |
| kasıtlı bozukluk | 8 tür (analizin bulması *gereken* şeyler) |

Yükleme ve sunucuya gönderme: **`paket/OKU.md`**.

---

## 7. Çalıştırma

```sh
# testler (686)
cd service && python -m unittest discover -s tests -t .

# hattı fikstürle uçtan uca koştur (köprü gerekmez)
python -m src.cli run --school hezarfen-demo --source file \
    --fixtures fixtures/demo --dry-run
```

**HTTP sunucusu yoktur ve olmayacaktır.** Çelebi'nin geliştirme amaçlı HTTP
sunucusu üretim imajında duruyor ve denetimde kimlik doğrulamasız yüzey olarak
işaretlendi; burada geliştirme yüzeyi komut satırı aracıdır.

### Doğrulama

| Ne | Nasıl |
|---|---|
| Tüm paket | `python -m unittest discover -s tests -t .` (686 test) |
| ZEKA'nın yazma katmanı | `ZEKA_PG_DSN=... python -m unittest tests.test_store_pg` |
| Şema + davranış | `tools/check_pg_schema.sh` (19 test) |
| Yüklenen tohum | `pg_dogrula.sql` (48 denetim) |

`tests/test_store_pg.py` sahte istemciyle koşmaz — **gerçek PostgreSQL'e**
karşı koşar. Sebep deneyle sabit: SurrealDB sürümünde birim testlerin tamamı
yeşilken gerçek veritabanında `type::thing()` diye bir fonksiyon olmadığı için
tek satır yazılamıyordu. Mock istemci bunu göremez.

---

## 8. Sınırlar — dürüst liste

- **Gerçek backend'e hiç bağlanılmadı.** Köprü, backend'in protokolünü taklit
  eden sahte bir sunucuya karşı kanıtlandı (35 canlı test, gerçek QUIC
  bağlantısı). Sahte sunucu Rust kaynağı okunarak yazıldı; kaynak yanlış
  okunduysa test yanlış davranışı doğrular. Backend ayağa kalktığında yeniden
  sınanmalıdır.
- **Sertifika düz HTTP ile çekiliyor** (podcast ve Çelebi ile aynı).
  `AI_TLS_FINGERPRINT` verilirse parmak izi doğrulanır; verilmezse her açılışta
  uyarı basılır. Üretimde verilmelidir.
- **ZEKA'nın veritabanı kullanıcısı** üretimde yalnız dokuz `zeka_*` tablosuna
  yazma, kalan 69'una salt okuma yetkisine daraltılmalı. Bugün geliştirmede tam
  yetkili kullanıcı kullanılıyor.
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
generator/   tohum üreticisi (SurrealQL + PostgreSQL, aynı geçiş)
paket/       sunucuya gönderilecek paket — OKU.md
service/
  src/       köprü, Source, compute/, segment/, report/, store_pg
  tests/     686 test
  schema/    ZEKA'nın DDL'i (postgres/ ve eski surql)
  docs/      çıktı sözleşmesi, backend gereksinimleri, ölçüm raporları
spec/        şema, senaryo, modüller, segmentasyon araştırması
tools/       yükleyici, doğrulayıcı, ölçüm araçları
```

Frontend ve backend ekipleri için tek belge: **`service/docs/CIKTI-SOZLESMESI.md`**
— üretilen her tablo, alan ve kural kimliği. Segment kurallarının ölçülmüş
isabeti: `service/docs/SEGMENT-CIKTI.md`.

---

## 10. Sırlar

`.env` gitignore'ludur ve depoya **girmez**. `compose.yaml` yalnızca
interpolasyon içerir, literal sır taşımaz. `AI_SHARED_TOKEN`, `ZEKA_PG_DSN` ve
`LLM_API_KEY` `:?` ile **zorunludur**; eski `DEEPSEEK_API_KEY` adı artık
**reddedilir** (temiz kesim): adressiz ya da anahtarsız bir servis
ayağa kalkıp hiçbir şey yazmadan "çalışıyor" görünürdü. Açılışta bir satır hata,
günler sonra boş bir tablo yerine.

DSN hiçbir yerde loglanmaz; `pg_client._describe()` yalnız host/port/veritabanı
döndürür, kullanıcı adı ve parola asla.

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
   # AI_SHARED_TOKEN / ZEKA_PG_DSN / LLM_API_KEY zorunlu
   chmod 0600 ~/hezarfen_zeka/hezarfen_zeka.env
   ```

5. **Backend tarafı açık olmalı**: `hezarfen_backend.env` içinde
   `AI_QUIC_ADDR=0.0.0.0:8090` ve `AI_SHARED_TOKEN` bu köprününkiyle **aynı**.
   Bu bir **kapı değildir**: ZEKA backend yokken çıkmaz, bekler ve backend
   düzeltilince kendiliğinden kaydolur (bkz. `docs/DAGITIM.md`). Deploy bunu
   yalnız **uyarı** olarak bildirir — kayıt şartı aransaydı ZEKA'nın kendi
   tanımından daha sıkı bir kapı uydurmuş olurduk.

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
