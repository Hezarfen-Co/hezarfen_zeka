# DEPOLAMA — ZEKA'nın kendi veritabanı

Bu belge, ZEKA'nın **kendi** SurrealDB veritabanına yazan katmanı anlatır:
şema, yazım hacmi, saklama politikası, nasıl koşturulacağı ve **neyin
kanıtlanmadığı**.

> **Tek ve mutlak kural:** ZEKA okul veritabanına **asla yazmaz**. Okul
> verisini yalnız `Source` arayüzü üzerinden okur. Burada anlatılan beş tablo
> ZEKA'nın kendi veritabanında yaşar ve okul şemasıyla hiçbir bağı yoktur —
> okul kimliği bir `record` değil, düz `string` slug'dır.

---

## 1. Şema

Kaynak: `service/schema/zeka.surql` — 104 DDL ifadesi, beş tablo.
Alan alan sözleşme (frontend/backend için): `docs/CIKTI-SOZLESMESI.md`.

| Tablo | Ne tutar | Kayıt anahtarı |
|---|---|---|
| `student_summary` | Öğrenci başına gecelik özet | `{school}_{student}` |
| `recommendation` | Üretilmiş tavsiye + kanıtı | `{school}_{audience}_{product}_{rule_id}_{scope}` |
| `insight_run` | Koşu defteri | `{school}_{YYYY-MM-DD}` (TR tarihi) |
| `question_segment` | Soru başına bilişsel etiket (segmentasyon hattı) | `{school}_{question}` |
| `student_segment_profile` | Öğrenci × boyut × etiket performansı, `contrast` ile | `{school}_{student}_{dimension}_{label}` |

Anahtarlar **kompozit** olduğu için tekillik yapısaldır: `UNIQUE` indekse gerek
yoktur ve `UPSERT` idempotenttir — aynı geceyi iki kez koşturmak satır
çoğaltmaz.

### Şema yüklenirken yaşanan üç gerçek hata

Bu üç şey, şema ilk kez **gerçek** bir SurrealDB 3 örneğine yüklendiğinde
ortaya çıktı. Üçü de "kod doğru görünüyordu ama hiç koşmamıştı" sınıfından.

1. **`type::thing()` SurrealDB 3'te yoktur.** Karşılığı `type::record()`.
   `store.py`'nin toplu UPSERT'i `type::thing` kullanıyordu; gerçek bir
   veritabanına gönderildiğinde ayrıştırma hatası veriyor, yani **hiçbir satır
   yazılmıyordu**.
2. **`FLEXIBLE`, `TYPE`'dan sonra gelmek zorunda.** `... FLEXIBLE TYPE object`
   yazımı ayrıştırma hatası verir. Bu hata sessizdir: `surreal sql` ile toplu
   gönderilen dosyada ifade düşer, şema "yüklendi" sanılır, ama SCHEMAFULL
   tabloda tanımsız alan da sessizce düşer. Sonuç: `marks`, `attendance`,
   `submission`, `study` ve `evidence` alanları **hiç var olmuyordu** —
   hesap çıktısının tamamı kayboluyordu.
3. **`attention.*` tanımı `attention`'dan ÖNCE gelmeli.** `TYPE
   option<array<object>>` ifadesi `.*` alt tanımını kendiliğinden (ve
   `FLEXIBLE` olmadan) üretir; sonra gelen `DEFINE FIELD IF NOT EXISTS
   attention.* ... FLEXIBLE` onu atlar. O halde dikkat maddelerinin iç
   anahtarları (`evidence` nesnesi dahil) sessizce düşerdi.

Ayrıca **`option<string>` `NULL` kabul etmez**: SurrealDB 3'te `option<T>`
gerçekte `none | T` demektir. Python'un `None` değeri JSON `null` olarak gider
ve `Couldn't coerce value for field 'dismiss_reason' ... Expected 'none |
string' but found 'NULL'` hatasıyla **tüm transaction'ı** reddeder — tek bir
boş `dismiss_reason`, 500 satırlık grubun tamamını düşürürdü. Doğru karşılık
alanı hiç göndermemektir; `store._drop_nulls()` üst düzey `None` alanlarını
satırdan çıkarır. FLEXIBLE nesnelerin **içindeki** `null`'lar hesap çıktısının
parçasıdır ve olduğu gibi saklanır.

### Alan tipleri testle pinlenir

`tests/test_store.py::TestSchemaApply::test_declared_field_types_are_what_the_schema_says`
`INFO FOR TABLE` çıktısını okuyup **her alanın** ilan edilmiş tipini tek tek
karşılaştırır. Şemadan bir alan düşerse ya da tipi saparsa test kırılır.

Şemada kasıtlı olarak **olmayan** şeyler de testle korunur:

* Tek bir **risk skoru** alanı yoktur; `attention` maddelerinde `score`,
  `rank`, `weight`, `severity` bulunmaz. SCHEMAFULL tablo `risk_score`
  taşıyan bir satırı **gürültüyle reddeder**
  (`test_schemafull_rejects_an_undeclared_field`).
* `evidence` boş olamaz: kanıtsız tavsiye depolama katmanında da reddedilir.

---

## 2. Yazım

### Toplu UPSERT

* Grup boyutu `BATCH_SIZE = 500`; her grup **tek transaction**.
* Bir grup düşerse yeniden denenir; **ikinci düşüşte** grup atlanır, `warn`
  loglanır ve hat devam eder (`MAX_ATTEMPTS = 2`). Bayat veri, yanlış veriden
  iyidir.
* `student_summary` ve `insight_run` **`CONTENT`** ile yazılır (satır tümüyle
  yeniden üretilir). `recommendation` **`MERGE`** ile yazılır: hat `dismissed_at`
  / `dismissed_by` / `dismiss_reason` alanlarını hiç üretmez ve CONTENT ile
  yazsaydı her gece kullanıcının "bu tavsiye faydalı değil" kaydını silerdi.
* Sürücü bağımsızlığı korunur: `store.py` bir SurrealDB sürücüsü **import
  etmez**. Gerçek istemci `SurrealHttpClient`'tır ve yalnızca standart
  kütüphane kullanır (`urllib` + JSON-RPC `/rpc`). `requirements.txt`
  değişmedi.

### Neden `/rpc`, neden `surreal sql` değil

* `surreal sql` aracı büyük girdiyi **sessizce keser** ve çok satırlı ifadeleri
  satır satır ayrıştırır (bu projede tohum yüklerken acıyla öğrenildi —
  `tools/load_seed.py` baş açıklaması).
* HTTP `/sql` ucu değişken (`$v`) taşıyamaz; gövde düz metindir. İç içe
  sözlükleri SurrealQL metnine gömmek kaçış hatasına açık olurdu.
* `/rpc` ucu JSON-RPC'dir: `query` yöntemi `[sql, variables]` alır. Değişkenler
  tip korunarak gider.

### En önemli davranış: hata HTTP 200 ile gelir

SurrealDB başarısız ifade için de **HTTP 200** döner; hata, sonuç dizisindeki
`status: "ERR"` alanındadır. `SurrealHttpClient.query_sync()` **her** ifadenin
durumunu tek tek denetler ve ilk `ERR`'de `SurrealError` atar. Denetlemeyen bir
istemci "yazdım" der ve hiçbir şey yazılmamış olur.

Aynı sebeple `apply_schema()` DDL'i **ifade ifade** gönderir: bir ifade düşerse
hangisinin düştüğünü bilmek gerekir.

### Ölçülen hacim

İki okullu kanıt koşusundan (9 + 4 öğrenci, `fixtures` verisi):

| Kaynak | student_summary | recommendation | insight_run |
|---|---|---|---|
| 1. gece (kadıköy, bütçe tam) | 9 | 21 | 1 |
| 1. gece (üsküdar, bütçe −1) | 0 | 0 | 1 |
| 2. gece (ikisi de) | 13 toplam | 16 toplam (bayatlar süpürüldü) | 4 toplam |

Öğrenci başına kabaca **1 özet + 2–3 tavsiye** satırı. Entegrasyon testlerinde
`BATCH_SIZE + 123 = 623` satırlık tek yazım da koşturulur ve hepsinin indiği
sayılarak doğrulanır.

---

## 3. Saklama politikası

`store.RETENTION_DAYS` (`[T§6.7]`, `MODULLER.md` §2.11 adım 2):

| Tablo | Gün | Gerekçe |
|---|---|---|
| `student_summary` | 400 | "dönem + 1 yıl" — türetilmiş veri, ham veriden yeniden üretilebilir |
| `recommendation` | 90 | `retain_until = min(expires_at, created_at + 90 gün)` — bayat tavsiye zararlıdır |
| `insight_run` | 90 | koşu defteri |

Süpürme (`Store.sweep`) hattın **en sonunda**, `DELETE <tablo> WHERE
retain_until < $now` ile koşar. Ayrıca `Store.purge_departed()` artık öğrenci
olmayanların türetilmiş verisini siler: "mezunun ham verisi arşivde kalabilir;
**profili kalmamalıdır**."

**Süpürmenin gerçekten sildiğinin kanıtı** (`python -m src.cli sweep`):

```
once   : student_summary 19, recommendation 22, insight_run 4
sonra  : student_summary 13, recommendation 16, insight_run 4
silinen: student_summary  6, recommendation  6, insight_run 0
```

500 gün önce hesaplanmış 6 özet ve 6 tavsiye silindi; taze satırlar duruyor.

---

## 4. Kiracı izolasyonu

Üç katman:

1. **Kayıt anahtarı okulla önekli.** Aynı öğrenci kimliği iki okulda bulunsa
   bile iki ayrı satır olur — kanıt koşusunda iki okul da `student-00…`
   kimliklerini kullanıyor ve toplam `9 + 4 = 13` satır çıkıyor, 9 değil.
2. **Her satır `school` alanı taşır** ve tüm sorgular `WHERE school = $s` ile
   daraltılır (`student_summary_school`, `recommendation_audience` indeksleri).
3. **Zamanlayıcı okulları sırayla ve ayrı `Source` nesneleriyle işler**; bir
   okulun düşmesi diğerini etkilemez.

Testler: `test_store.py::TestTenantIsolation` (4 test) ve
`test_scheduler.py::TestFullCycleAgainstSurreal::test_tenant_isolation_end_to_end`.

---

## 5. Zamanlayıcı — bütçe ve erteleme

* Pencere **03:00–05:00 TR**, tik 15 dakika. Kaçan tik birikmez.
* Okullar **sabit alfabetik sırada**; geçen gece `partial` biten okullar öne
  alınır. Sabit sıra "hep son okul bütçesiz kalır" durumunu görünür kılar.
* **Okul başına bütçe:** `Scheduler(budgets={"okul": ms})`. Sözlükte olmayan
  okul varsayılan `60_000 ms` bütçesini kullanır.
* **Bütçeyi aşan okul ertelenir:** işlenmemiş öğrenciler
  `insight_run.pending_students`'a yazılır ve bir sonraki koşu bu kimlikleri
  listenin **başına** alır (`run_school(resume_students=...)`).
* **Yeniden başlatmaya dayanır:** bellek içi `pending` sözlüğü süreç
  ölünce kaybolur; `Store.last_pending(school)` devreden listeyi
  `insight_run` satırından geri okur.
* **Bir okul düşerse tur durmaz.** O okulun `_last_run_day`'i
  güncellenmez, dolayısıyla aynı gece yeni bir tik onu yeniden dener.

### Test kipi

`Scheduler.serve(tick_seconds=..., ignore_window=True, max_ticks=N)` gece
penceresini ve 15 dakikalık tiki beklemeden tam çevrim koşturur. Bu **ayrı bir
kod yolu değildir** — aynı döngünün parametrelenmiş hali. Ayrı yol olsaydı test
edilen şey üretimde koşan şey olmazdı.

Bütçe testlerinde `monotonic_fn` enjekte edilir (`FakeMonotonic`), böylece
"bütçe kaçıncı öğrenciden sonra dolar" makinenin hızına değil, sayıya bağlıdır.

---

## 6. Nasıl koşturulur

### Veritabanını kaldır

```bash
podman network create hzk
podman run -d --name hzk-zeka --network hzk --memory 2g -v hzk-zeka-data:/data --user 0 \
  docker.io/surrealdb/surrealdb:v3 start --user root --pass root "surrealkv:/data/zeka.db"
```

> Bu makinede host'a **port yönlendirmesi çalışmıyor**; veritabanına `hzk`
> ağının içinden `hzk-zeka:8000` adıyla bağlanılır. Bu yüzden aşağıdaki
> komutların hepsi ağ içindeki bir konteynerden koşar.

### Şemayı yükle ve doğrula

```bash
podman run --rm --network hzk -v /path/to/hezarfen-ZEKA:/repo:ro -w /repo/service \
  docker.io/library/python:3.12-slim \
  python -m src.cli schema --apply --db-url http://hzk-zeka:8000 \
    --db-ns hezarfen --db-name zeka
```

Çıktı `{"ifade_toplam": 56, "uygulanan": 56, "hatalar": []}` ve ardından
`INFO FOR DB` / `INFO FOR TABLE`'dan okunan tablo ve alan listeleridir.

### Bir okulu koştur

```bash
python -m src.cli run --school okul-a --source file --fixtures /yol/fikstur \
  --db-url http://hzk-zeka:8000 --db-name zeka
# ya da veritabanına dokunmadan:
python -m src.cli run --school okul-a --source file --fixtures /yol/fikstur --dry-run
```

### Zamanlayıcıyı elle tetikle

```bash
python -m src.cli schedule --schools kadikoy-lisesi,uskudar-lisesi \
  --fixtures /yol/fikstur --budget "uskudar-lisesi=-1" \
  --db-url http://hzk-zeka:8000 --db-name zeka
# tam serve() döngüsü, pencere beklemeden:
python -m src.cli schedule ... --ticks 2 --tick-seconds 0.01
```

### Süpürme

```bash
python -m src.cli sweep --db-url http://hzk-zeka:8000 --db-name zeka
```

### Testler

```bash
# Konteyner yoksa: entegrasyon testleri skipUnless ile atlanır.
python -m unittest discover -s service -p "test_*.py" -t service

# Gerçek veritabanına karşı (CI'da da böyle koşar):
podman run --rm --network hzk -e ZEKA_TEST_DB_URL=http://hzk-zeka:8000 \
  -v /path/to/hezarfen-ZEKA:/repo -w /repo/service \
  docker.io/library/python:3.12-slim \
  python -m unittest discover -s . -p "test_*.py" -t .
```

Entegrasyon testlerinin her biri **kendi boş veritabanını** açar
(`tests/zeka_db.py::fresh_schema_client`), böylece testler birbirinin satırını
görmez.

---

## 7. Kanıtlanmayanlar

Dürüstlük bölümü. Aşağıdakiler **koşmadı**, dolayısıyla "çalışıyor" denemez.

1. **Üretim bağlantı yolu.** Testler HTTP `/rpc` ile bağlanır.
   `config.py::db_url` varsayılanı `ws://hezarfen-surrealdb:8000/rpc`
   (WebSocket). WebSocket taşıması **hiç denenmedi**; `SurrealHttpClient`
   yalnızca HTTP konuşur. Üretimde adresin `http(s)://host:port` biçiminde
   verilmesi gerekir.
2. **Kimlik doğrulama yalnızca `root:root` ile denendi.** Sınırlı yetkili bir
   veritabanı kullanıcısı, namespace/database düzeyinde erişim ve
   `PERMISSIONS` kuralları denenmedi. Şemadaki alanlar `PERMISSIONS FULL`.
3. **Gerçek ölçek.** En büyük koşu 623 satırlık tek toplu yazımdı ve tüm
   testler 13 öğrencilik fikstürlerle koştu. Binlerce öğrencili bir okulda
   60 saniyelik bütçenin yeteceği **ölçülmedi**; `surrealkv` arka ucunun
   büyük `DELETE`lerde nasıl davrandığı da ölçülmedi.
4. **Eşzamanlılık.** `Scheduler` süreç içi `asyncio.Lock` kullanır. İki ZEKA
   süreci aynı anda koşarsa ne olduğu denenmedi; ikinci savunma olarak
   gösterilen "`insight_run` satırının varlığı" **kod tarafından
   okunmuyor** — yalnızca `pending_students` okunuyor. Yani çok süreçli tek
   koşu güvencesi şu an **yoktur**.
5. **Köprü (`BridgeSource`) ile uçtan uca koşu.** Tüm entegrasyon testleri
   `FileSource` fikstürleriyle koştu. Canlı köprüden gelen gerçek gövdelerle
   hat hiç denenmedi.
6. **Zaman tabanlı süpürmenin gerçek takvimde koşması.** Süpürme, testlerde ve
   kanıt koşusunda **enjekte edilmiş `now_ms`** ile çalıştırıldı. Gerçek gece
   03:00'te kendiliğinden koşan bir süreç izlenmedi.
7. **`discover_students`'ın sınırı duruyor.** Öğrenci listesi hâlâ
   `homework_list().assigned` alanından türetiliyor; **hiç adrese özel ödev
   almamış öğrenciler kaçırılır**. Bu bir depolama sorunu değil, `Source`
   arayüzünün eksiği (`docs/BACKEND-GEREKSINIMLERI.md` madde 3).
8. **`recommendation.dismissed_*` alanlarını ZEKA hiç yazmaz.** İnsan
   müdahalesi izini (KVKK m.11) dolduracak bir ürün yolu yok; alanlar şemada
   var ama hat onları hiç üretmiyor. Bu alanların gece koşusunda
   **silinmediği** kanıtlandı (`recommendation` tablosu `UPSERT ... MERGE` ile
   yazılır; `test_rerun_does_not_erase_a_human_dismissal`), ama onları dolduran
   tarafın davranışı denenmedi.
