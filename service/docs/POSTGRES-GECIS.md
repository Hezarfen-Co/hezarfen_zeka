# Postgres geçişi — hazırlık durumu

> **CANLIYA HİÇBİR ŞEY YAPILMADI.** Bu belge hazırlığın nerede olduğunu ve
> uygulama gününde ne yapılacağını anlatır. Backend deposunda tek bir dosya
> değiştirilmedi; üretilen her şey `hezarfen-ZEKA/` altındadır.

---

## 0. Ne değişti

Backend veritabanını değiştirdi: **SurrealDB 3.2 → PostgreSQL 18** (`sqlx 0.9`).
Şema artık kodun içinde gömülü değil, `migrations/control/` ve
`migrations/school/` altında dosyalar hâlinde; `Migrator` bunları açılışta
şablona ve her yeni okul veritabanına uyguluyor.

ZEKA açısından **değişmeyenler** — bunları ayrıca doğruladım:

| | |
|---|---|
| Köprü protokolü | `hab/2`, aynı |
| İzin listesi | 19 yol, **harfi harfine aynı** (sınav yolu yine yok) |
| Kiracılık | okul başına ayrı veritabanı, aynı |
| Zaman | `BIGINT` unix-ms UTC, aynı |
| Yetenekler | yine yalnız `chat.reply` + `rag.index` |

Yani `service/src/` içindeki köprü, `Source` arayüzü ve hesap modülleri
**etkilenmiyor**. Etkilenen iki şey var: ZEKA'nın çıktı şeması ve tohum verisi.

---

## 1. Hazır olan: ZEKA'nın Postgres şeması

`service/schema/postgres/school/20260916000001_zeka.sql`

Uygulama günü bu dosya backend'in `migrations/school/` klasörüne **eklenecek**
(hiçbir mevcut dosya değişmeyecek — sqlx migration'ları sağlama toplamıyla
izler, var olan bir dosyayı düzenlemek uygulanmış veritabanlarını kırar).

Tablolar:

| Tablo | Ne tutar |
|---|---|
| `zeka_student_summary` | öğrenci başına gecelik özet (PK: `student`) |
| `zeka_attention_item` | dikkat listesi maddeleri, tetikleyici başına satır |
| `zeka_recommendation` | tavsiyeler, kapatma izi dahil |
| `zeka_run` | gece işinin defteri (PK: `run_day`) |
| `zeka_run_pending` | bütçe dolunca kalanlar |
| `zeka_run_failed_module` | hata veren modüller |
| `zeka_question_segment` | soru başına bilişsel etiket (PK: `question`) |
| `zeka_question_segment_dimension` | üretim/deneysel boyut ayrımı |
| `zeka_student_segment_profile` | öğrenci × boyut × etiket, `contrast` dahil |

Backend'in kendi çeviri kurallarına uyuldu:

- `school` kolonu **yok** — kiracı veritabanın kendisi
- kayıt bağları → `uuid` FK, hepsi `ON DELETE NO ACTION`
- `{a}_{b}` metin anahtarları → doğal bileşik PK
- `option<object> FLEXIBLE` → **JSONB**, yalnız şekli servise ait alanlarda
  (`exam_question.choices` ve `rag_output.payload` ile aynı çizgi)
- diziler → `ord` kolonlu **çocuk tablo**, Postgres dizisi değil (backend
  elindeki her `TEXT[]`/`uuid[]`'i böyle açtı; dizi kullansaydık şemadaki tek
  istisna olurduk)
- kimlikler uygulama tarafından basılan **uuid v7**

**FK yönü tek taraflı:** `zeka_*` tabloları `app_user`, `course`, `subject`,
`exam_question`'a bakar; okul tablolarının hiçbiri `zeka_*`'a bakmaz. Doğrulama
betiği bunu ayrıca sınar — ters yönlü tek bir FK bile çıkarsa hata verir,
çünkü o, okul şemasını ZEKA'ya bağımlı hâle getirirdi.

### Çeviride bilinçli verilen iki karar

**`zeka_recommendation.id` eklendi.** SurrealDB'de anahtar
`{school}_{audience}_{product}_{rule_id}[_{scope}]` idi. Postgres'te `scope`
NULL olabildiği için bu doğal anahtar PK olamıyor (`NULLS NOT DISTINCT` yalnız
`UNIQUE` için geçerli). Doğal anahtar `UNIQUE NULLS NOT DISTINCT` olarak duruyor
ve UPSERT hâlâ onun üzerinden idempotent; ayrıca bir vekil `id` var. Bu zaten
işe yarıyor: kartı kapatmak tek satıra yazmaktır, istemcinin dört kolon
adlandırması gerekmesin.

**`zeka_question_segment.course` denormalize bırakıldı.** `subject.course`'tan
türetilebilir ama öğretmenin "ders × bilişsel talep" ekranı join'siz çalışsın
diye satırda duruyor. Çıktı sözleşmesinde zaten yayınlanmış durumda, kaldırmak
frontend'i etkilerdi.

---

## 2. Hazır olan: doğrulama betiği

`tools/check_pg_schema.sh`

Tek kullanımlık bir Postgres'e önce backend'in kendi migration'larını, sonra
ZEKA'nınkini uygular; `zeka_*` tablolarını, dışa giden FK'leri ve ters FK
olmadığını raporlar; sonunda veritabanını düşürür. Hiçbir backend dosyasına
yazmaz.

Bunun neden var olduğu deneyle sabit: bu şemanın SurrealDB sürümü iki kez
gözden geçirildi ve yine de beş alanı sessizce düşürdü — `FLEXIBLE TYPE object`
ayrıştırma hatası veriyor, SCHEMAFULL tablo tanımsız alanı tek kelime etmeden
atıyor. Okumakla görülmüyor; yalnız koşturmakla görülüyor.

---

## 3. Henüz yapılmayanlar

**a) Depolama katmanı.** `src/store.py` (739 satır) SurrealDB'ye yazıyor:
`DbClient` protokolü, `SurrealHttpClient`, `UPSERT ... MERGE`. Postgres'te
karşılığı `INSERT ... ON CONFLICT DO UPDATE`. Yeni bir istemci ve yeni bir
`Store` uygulaması gerekiyor; arayüz (`write_summaries`,
`write_recommendations`, `write_question_segments`, `write_segment_profiles`,
`write_run`, `last_pending`, `sweep`, `purge_departed`) aynı kalabilir.

> Burada bir tuzak var, önceden not ediyorum: nightly yazım
> `zeka_recommendation`'a **MERGE** yapmalı. `dismissed_at`, `dismissed_by` ve
> `dismiss_reason` kolonlarını ezen bir `ON CONFLICT DO UPDATE SET` yazılırsa
> kullanıcının kapatma kaydı her gece silinir. SurrealDB sürümünde aynı tuzak
> vardı ve şema yorumuna yazılmıştı; Postgres'te `DO UPDATE SET` varsayılan
> olarak *her* kolonu yazdığı için risk daha yüksek.

**b) Tohum verisi.** 569.808 satır SurrealQL. 58/59 tablo birebir karşılık
buluyor (yalnız `migration_mark` düşüyor, o da backend tarafından kasten
atılmış). Gereken iş:

1. ULID → UUID v7 **deterministik** eşleme (ikisi de 48 bit ms damgası taşıyor,
   sıralama korunabilir). Deterministik olmak zorunda, yoksa "başka lokalde
   aynı veri" hedefi bozulur.
2. Üreticiye Postgres yazıcısı (regex'le `.surql` ayrıştırmak **değil** —
   bunun bedelini bir kez ödedik, `\'` kaçışını anlamayan bir regex 47 hatalı
   ölçüm üretmişti).
3. 10 gömülü diziyi çocuk tablo satırlarına aç.
4. Control veritabanı: `person`, `person_school`, `school` satırları.

Referans bütünlüğünü şimdiden kontrol ettim, Postgres'in FK'leri artık
zorlaması sorun çıkarmıyor:

```
from_bank referansı: 2.636 | kopuk: 0
exam_answer (exam, question) çelişkili: 0 / 216.633
```

**c) Bir semantik kayıp.** Sayaç kolonları artık `BIGINT NOT NULL DEFAULT 0`.
Tohumdaki **K2** (`lessons_attended_total` NONE, 250 satır) ve **K3**
(`high_mark_total` NONE, 250 satır) kasıtlı bozuklukları Postgres'te temsil
edilemiyor; `0` olacaklar. Anlam aynı — migration başlığı da bunu söylüyor:
*"counter columns (absent-reads-as-zero in Surreal) are BIGINT NOT NULL
DEFAULT 0"* — ama ZEKA artık "hiç sayılmadı" ile "sıfır sayıldı" ayrımını
yapamaz. Kalan 8 kasıtlı bozukluk (K1, K4–K10) aynen taşınıyor.

---

## 4. Uygulama günü sırası

1. `tools/check_pg_schema.sh` yeşil olsun
2. `20260916000001_zeka.sql` backend'in `migrations/school/`'una **eklensin**
   (mevcut dosyalara dokunulmadan)
3. `scripts/prepare_db.sh` koşsun — sqlx derleme zamanı sorgu kontrolü
4. Depolama katmanı Postgres'e çevrilsin, gerçek veritabanına karşı test edilsin
5. Tohum dönüştürülsün ve yüklensin
6. Hat uçtan uca koşsun

**1–5 arası hiçbir adım canlıyı etkilemez.** Adım 2 backend deposunda bir
dosya ekler; o da bizim değil, backend ekibinin kararı ve onların eliyle
yapılmalı.
