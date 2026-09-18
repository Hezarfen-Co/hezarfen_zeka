# ZEKA Çıktı Sözleşmesi

> **Frontend ve backend ekibine verilecek tek belge budur.**
> ZEKA'nın ürettiği her satır, her alan, her kural kimliği burada.
> DDL kaynağı **backend deposudur**:
> `hezarfen_backend/migrations/school/20260917000002_zeka.sql` — tablolar her
> okulun kendi veritabanında durur, sahibi backend'dir.
> Yazan katman: `service/src/store.py`, köprü deposu (`BridgeStore`).
> Kural motoru: `service/src/compute/recommend.py`.

---

## 0. Beş cümlede sözleşme

1. ZEKA'nın **veritabanı bağlantısı yoktur**. Yazdığı her satır backend'e
   QUIC köprüsünden, `insight.*` **yetenek çağrısıyla** gider; okulun kendi
   API'sinden okuduğu veriler de aynı köprüdedir (`ApiRequest`).
2. Dokuz tablo vardır ve bu listenin dışında bir tablo yoktur. Hepsi `zeka_`
   önekli ve hepsi **okulun kendi veritabanında**: kiracı, veritabanının
   kendisidir, satırda `school` alanı yoktur.
3. Bütün zaman alanları **i64 unix milisaniye, UTC**. `datetime` tipi
   kullanılmaz.
4. Kimlikler okulun kendi uuid'leridir (`app_user`, `course`, `exam_question`
   …); metin kimlik taşınmaz ve satır kimliğini **yazan taraf üretir** —
   uuid7'yi backend mints eder.
5. **Tek bir "risk skoru" alanı yoktur.** Hiçbir tabloda `score`, `rank`,
   `weight`, `severity` alanı bulunmaz ve bulunmayacaktır — sıralama şemadan
   üretilemesin diye (`[T§6.6]`).

---

## 1. Tabloların özeti

Beş **varlık** ve dört **çocuk tablo** (eskiden gömülü diziydi, artık `ord`
kolonlu satırlar):

|#|Tablo|Satır neyi anlatır|Anahtar|Saklama|
|---|---|---|---|---|
|1|`zeka_student_summary`|Bir öğrencinin gecelik özeti|`student`|400 gün|
|2|`zeka_attention_item`|Dikkat listesi, tetikleyici başına bir satır|`(student, trigger, course)`|ebeveynle|
|3|`zeka_recommendation`|Üretilmiş tek tavsiye + kanıtı|`id` (uuid); doğal anahtar `(audience, product, rule_id, about, scope)`|`min(expires_at, +90 gün)`|
|4|`zeka_run`|Koşu defteri|`run_day` (`YYYY-MM-DD`)|90 gün|
|5|`zeka_run_pending`|Bütçe dolunca kalanlar|`(run, student)`|ebeveynle|
|6|`zeka_run_failed_module`|Hata veren modüller|`(run, module)`|ebeveynle|
|7|`zeka_question_segment`|Bir sorunun bilişsel etiketi|`question`|1095 gün|
|8|`zeka_question_segment_dimension`|Üretim/deneysel boyut ayrımı|`(question, dimension)`|ebeveynle|
|9|`zeka_student_segment_profile`|Öğrenci × boyut × etiket performansı|`(student, dimension, label)`|400 gün|

Anahtarlar **doğal**dır: gece koşusunu tekrar çalıştırmak satır çoğaltmaz
(upsert idempotent). Tavsiyenin `about` alanı **anahtarın parçasıdır** ve bu
süs değildir: öğretmen kuralı öğrenci başına bir kez ateşler; `about` anahtarda
olmasaydı otuz öğrenci tek anahtarı paylaşır, upsert sonuncuyu tutar ve
öğretmene otuz kişi yerine **biri** gösterilirdi.

---

## 2. Tablolar, alan alan

### 2.1 `zeka_student_summary`

| Alan | Tip | Anlam |
|---|---|---|
| `student` | `uuid` | Öğrenci kimliği (`app_user`) — **PK** |
| `marks` | `JSONB` | Not modülü çıktısı: `courses.<course>.{average, n_marks, placement{band, z, class_average, class_sd, cohort_n, confidence}}` |
| `attendance` | `JSONB` | Devam modülü çıktısı |
| `submission` | `JSONB` | Ödev/teslim modülü çıktısı; `upcoming[]` yaklaşan teslimler |
| `study` | `JSONB` | Çalışma (pomodoro) modülü çıktısı |
| `confidence` | `TEXT` | `none` \| `exploratory` \| `stable` |
| `computed_at` | `BIGINT` | Hesap anı (unix ms) |
| `retain_until` | `BIGINT` | Bu damgadan sonra süpürülür |

Dikkat listesi bu satırın içinde **değildir**: `zeka_attention_item` çocuk
tablosundadır, `ord` yazanın sırasını tutar (tetikleyiciye göre **alfabetik**,
şiddete göre değil).

`marks`/`attendance`/`submission`/`study` **JSONB**'dir: şekil hesap
modülüne aittir ve her kural sürümünde şema değişmek zorunda kalmaz. Frontend
bu nesnelerin içinden **okuduğu alanı adıyla** almalı, sırayla değil.

#### `zeka_attention_item` — çocuk tablo

| Alan | Tip | Anlam |
|---|---|---|
| `student` | `uuid` | Özetin sahibi (FK → `zeka_student_summary`) |
| `trigger` | `TEXT` | `attendance` \| `homework` \| `mark_trend` |
| `course` | `uuid`, boş olabilir | Maddenin dersi; yalnız not-eğilimi tetikleyicisinde dolu |
| `fact` | `TEXT` | **Öğretmenin okuduğu cümle.** Yargı değil olgu: "son 30 günün 4 ödevi teslim edilmedi" |
| `window_from` / `window_to` | `BIGINT` | Maddenin penceresi (her maddede sorulur) |
| `evidence` | `JSONB` | Arkasındaki sayılar. **Boş olamaz** — açıklanamayan madde yazılmaz |
| `ord` | `SMALLINT` | Yazma sırası |

Tekil: `(student, trigger, course)`.

### 2.2 `zeka_recommendation`

| Alan | Tip | Anlam |
|---|---|---|
| `id` | `uuid` | Satır kimliği. **Backend üretir**, ZEKA göndermez — kapatma tek satıra yazılan bir işlemdir |
| `audience` | `uuid` | **Kime gösterilecek** (öğrenci ya da öğretmen) |
| `about` | `uuid`, boş olabilir | **Kim hakkında.** Öğrenci kendi kartında boştur. **Doğal anahtarın parçası** |
| `audience_role` | `TEXT` | `student` \| `teacher` \| `parent` \| `manager` — **rol kapısı** |
| `product` | `TEXT` | `O1` \| `O2` \| `O3` \| `O4` \| `T3` \| `T4` |
| `scope` | `TEXT`, boş olabilir | Kuralın kendi kapsamı (segment etiketi gibi); ders değil |
| `course` | `uuid`, boş olabilir | İlgili ders (varsa) |
| `rule_id` | `TEXT` | Hangi kural (§3 listesi) |
| `rule_version` | `BIGINT` | Kural kataloğu sürümü. Arttığında kullanıcıya "hesaplama yöntemi güncellendi" gösterilir |
| `evidence` | `JSONB` | **Boş olamaz.** "Neden?" ekranını besleyen sayılar; içinde ayrıca `limitation` (Sınır satırı) |
| `confidence` | `TEXT` | `none` \| `exploratory` \| `stable` |
| `created_at` | `BIGINT` | Üretim anı |
| `expires_at` | `BIGINT` | Bu andan sonra **gösterilmez** |
| `retain_until` | `BIGINT` | Bu andan sonra **silinir** |
| `dismissed_at` | `BIGINT` | Kullanıcı kapattıysa an |
| `dismissed_by` | `uuid` | Kapatan kişi |
| `dismiss_reason` | `TEXT` | `bu doğru değil` gibi serbest metin |

Doğal anahtar: `(audience, product, rule_id, about, scope)`, `NULLS NOT
DISTINCT` — "kapsamsız" da bir yuva tutar.

**Beş bölümlü "Neden?"** zorunludur: Olgu · Karşılaştırma · Kural (hangi eşik,
hangi sürüm) · **Sınır** (neyin dahil olmadığı) · Tarih. Sınır satırı
`evidence.limitation` alanındadır ve **gösterilmesi zorunludur**; o satır
olmadan ürün olduğundan çok şey bildiğini ima eder.

`dismissed_*` alanlarını **yalnız uygulama yazar**. Gece koşusu **upsert**
kullanır ve bu üç alana dokunmaz.

### 2.3 `zeka_run`

| Alan | Tip | Anlam |
|---|---|---|
| `run_day` | `TEXT` (`YYYY-MM-DD`) | **PK**. Gün backend'de yeniden türetilmez; TR gününü bilen taraf ZEKA |
| `started_at` / `finished_at` | `BIGINT` / boş olabilir | Koşu penceresi |
| `status` | `TEXT` | `running` \| `ok` \| `partial` \| `failed` \| `skipped` |
| `duration_ms` | `BIGINT` | Süre |
| `students_total` / `students_ok` / `students_failed` / `students_skipped` | `BIGINT` | Muhasebe |
| `rows_written` | `BIGINT` | Yazılan satır |
| `budget_exceeded` | `bool` | Zaman bütçesi aşıldı mı |
| `budget_ms` | `BIGINT` | Tavan |
| `retain_until` | `BIGINT` | 90 gün |

`status = partial` ise ekran **"bu gece bazı öğrenciler işlenemedi"** demeli;
sessizce eksik veri göstermemeli. `partial`'ın bir kaynağı da depodur: bir
yazma grubu ikinci denemede de düşerse koşu `partial` yazılır.

#### Çocuk tablolar

| Tablo | Alanlar | Ne tutar |
|---|---|---|
| `zeka_run_pending` | `run`, `student`, `ord` | Bütçe aşıldıysa **devreden** öğrenciler; sonraki koşu buradan devam eder |
| `zeka_run_failed_module` | `run`, `module`, `ord` | Düşen modül adları → UI'da "eksik" işareti |

### 2.4 `zeka_question_segment`

Bir sorunun bilişsel etiketi. **Kişisel veri değildir**, hiçbir öğrenciye
bağlanamaz. Kaynağı `service/src/segment/` hattıdır (LLM etiketleme).

| Alan | Tip | Anlam |
|---|---|---|
| `question` | `uuid` | Soru kimliği — **PK** (FK: `exam_question(exam, id)`) |
| `exam` | `uuid` | Sınav kimliği |
| `course` | `uuid` | Ders kimliği (yazma anında çözülür) |
| `subject` | `uuid` | Konu kimliği |
| `bilissel_talep` | `TEXT` | `hatirlama` \| `uygulama` \| `analiz` |
| `dikkat_tuzagi` | `TEXT` | `var` \| `yok` |
| `okuma_yuku` | `TEXT` | `dusuk` \| `yuksek` |
| `adim_sayisi` | `TEXT` | `tek_adim` \| `cok_adim` — **DENEYSEL** (aşağı akışta kullanılmaz) |
| `confidence_bilissel_talep` | `double` | Modelin bu boyuttaki güveni [0,1] |
| `confidence_dikkat_tuzagi` | `double` | " |
| `confidence_okuma_yuku` | `double` | " |
| `confidence_adim_sayisi` | `double` | " |
| `confidence` | `TEXT` | Satır kademesi: **üretim** boyutlarının en düşük güveninden türetilir. Deneysel boyut bu kademeye girmez |
| `trap_choice` | `TEXT`, boş olabilir | `dikkat_tuzagi = var` ise tuzak şıkkın kimliği |
| `rationale` | `TEXT` | Modelin kendi gerekçesi, en fazla iki cümle. **Öğrenciye gösterilmez** (§5) |
| `model` | `TEXT` | Etiketi üreten model kimliği |
| `prompt_version` | `TEXT` | İstem sürümü |
| `variant` | `TEXT`, boş olabilir | Etiketleyici varyantı (`baseline`, `self_consistency`, …) |
| `computed_at` | `BIGINT` | Etiketleme anı |
| `retain_until` | `BIGINT` | 1095 gün |

#### `zeka_question_segment_dimension` — çocuk tablo

| Alan | Tip | Anlam |
|---|---|---|
| `question` | `uuid` | FK → `zeka_question_segment` |
| `dimension` | `TEXT` | `bilissel_talep` \| `dikkat_tuzagi` \| `okuma_yuku` \| `adim_sayisi` |
| `role` | `TEXT` | `downstream` (öğrenci profiline ve kurallara **girer**) \| `experimental` |
| `ord` | `SMALLINT` | Yazma sırası |

**Deneysel boyut neden duruyor:** `adim_sayisi` etiketlenir ve raporlanır, ama
LLM etiketlemesinde kararlılık kapısını (alpha ≥ 0,70) geçemedi. Bu yüzden
öğrenci profiline ve tavsiye kurallarına **girmez**. Bunu belgeye bakmadan
anlayabilmek için satırın kendisi `role` kolonunu taşır. Frontend `role =
downstream` olmayan bir boyutu **karar ekranında kullanmamalıdır**.

### 2.5 `zeka_student_segment_profile`

| Alan | Tip | Anlam |
|---|---|---|
| `student` | `uuid` | Öğrenci kimliği (**PK'nın parçası**) |
| `dimension` | `TEXT` | `bilissel_talep` \| `dikkat_tuzagi` \| `okuma_yuku` (yalnız üretim boyutları) |
| `label` | `TEXT` | O boyutun bir etiketi |
| `n_answers` | `BIGINT` | Bu segmentte **işaretlenmiş** cevap sayısı (boş bırakılan madde paydaya girmez) |
| `n_correct` | `BIGINT` | Doğru sayısı |
| `accuracy` | `double` | `n_correct / n_answers`. **Tek başına gösterilmez** (§5) |
| `overall_n_answers` | `BIGINT` | Öğrencinin etiketli tüm maddelerdeki cevap sayısı |
| `overall_accuracy` | `double` | Öğrencinin genel doğruluğu |
| `contrast` | `double` | **`accuracy − overall_accuracy`.** Bu tablonun asıl ölçüsü |
| `confidence` | `TEXT` | `none` (n<30) \| `exploratory` (n≥30) \| `stable` (n≥100) |
| `computed_at` | `BIGINT` | Hesap anı |
| `retain_until` | `BIGINT` | 400 gün |

Anahtar: `(student, dimension, label)`.

**`contrast` neden var:** ham `accuracy` bir ayrım ölçüsü **değildir**. İyi
öğrenci her segmentte yüksek, zayıf öğrenci her segmentte düşük çıkar; böyle
bir sayıdan "bu öğrenci analiz sorularında zorlanıyor" sonucu **çıkarılamaz**.
`contrast` öğrencinin genel düzeyini sadeleştirir.

**`contrast` de tek başına yetmez.** Kurallar `contrast − kohort ortalaması`
(göreli kontrast) üzerinden ateşler, çünkü kontrast hâlâ madde zorluğunu
taşır: analiz soruları herkes için zordur, kohortun ortalama `analiz`
kontrastı ölçülen tohumda **−0,119**'dur. Kohort ortalaması bu tabloda
**tutulmaz**; her koşuda yeniden hesaplanır ve tavsiyenin `evidence` nesnesine
`reference_mean_contrast` olarak yazılır. Bir ekran "bu öğrenci akranlarına
göre geride" diyecekse sayıyı oradan almalıdır.

---

## 3. Kural kimlikleri

### 3.1 Üretilenler

| `rule_id` | Ürün | Kime | Ne der | Hangi veriden |
|---|---|---|---|---|
| `O1.review_band` | O1 | öğrenci | Bu derste tekrar önerilir | `zeka_student_summary.marks` (`placement.band = review`, n_marks ≥ 3) |
| `O2.segment_cognitive_gap` | O2 | öğrenci | Bu tür sorularda kendi genel seviyene göre geridesin | `zeka_student_segment_profile` (`bilissel_talep`, `okuma_yuku`); n ≥ 100 ve göreli kontrast ≤ −0,080 / −0,060 |
| `O2.segment_trap_prone` | O2 | öğrenci | Dikkat tuzağı taşıyan sorularda akranlarına göre daha çok kaybediyorsun | `zeka_student_segment_profile` (`dikkat_tuzagi=var`); n ≥ 100 ve göreli kontrast ≤ −0,032 |
| `O3.pattern` | O3 | öğrenci | Çalışma düzenin şöyle görünüyor | `zeka_student_summary.study` (n_stints ≥ 5) |
| `O4.deadline` | O4 | öğrenci | Yaklaşan teslim | `zeka_student_summary.submission.upcoming` |
| `T3.class_gap` | T3 | öğretmen | Sınıf düzeyinde boşluk | `marks` (kohort ort. < 50, kohort ≥ 8) |
| `T3.individual_gap` | T3 | öğretmen | Bireysel destek | `marks` (kohort ort. ≥ 50, z < −0,8) |
| `T3.segment_class_gap` | T3 | öğretmen | Sınıf bu bilişsel segmentte topluca geride | `zeka_student_segment_profile` sınıf toplaması; ≥ 8 öğrenci ve sınıf ortalama göreli kontrast ≤ −0,040. **Bugün hiçbir koşu bunu üretmiyor** — §4.1 |
| `T4.attendance` | T4 | **yalnız öğretmen** | Devam tetikleyicisi | `zeka_attention_item` |
| `T4.homework` | T4 | **yalnız öğretmen** | Ödev tetikleyicisi | `zeka_attention_item` |
| `T4.mark_trend` | T4 | **yalnız öğretmen** | Not eğilimi tetikleyicisi | `zeka_attention_item` |

Segment kurallarının ölçülmüş isabeti: `docs/SEGMENT-CIKTI.md` §4.
**Özet:** ezberci arketibi kesinlik 0,765 / duyarlılık 0,722; aceleci 0,793 /
0,719; okuma güçlüğü 0,571 / **0,222** — sonuncusu bu veride
**kullanılabilir değildir** ve ekranda ona güvenilmemelidir.

### 3.2 Üretilemeyenler — ve nedeni

Bu satırlar **bilerek boş**tur. Sahte bir uygulama yazmak yerine listelenirler;
frontend bu kimlikler için ekran kurmamalıdır.

| `rule_id` | Engel |
|---|---|
| `O2.retry_item` | Ham sınav cevabı yok — madde bazlı tekrar listesi kurulamaz |
| `O2.common_mistake` | Çeldirici dağılımı yok |
| `O2.progress` | `seq=2` cevapları yok |
| `O4.last_minute` | `submitted_at` yok — erteleme profili hesaplanamaz |
| `O5.pool_match` | Havuz sorusu ve çözüm verisi Source arayüzünde yok |
| `T1.hard_item` | Madde analizi yapılamıyor (ham cevap yok) |
| `T1.distractor_beats_key` | Aynı sebep |
| `T2.low_discrimination` | Ayırt edicilik hesaplanamıyor |
| `T2.key_suspect` | Aynı sebep |
| `T4.exam_missed` | Sınav takvimi ve `exam_attempt` yok |
| `T5.stale_appointment` | Randevu verisi yok |
| `T5.unanswered_pool` | Havuz sorusu verisi yok |
| `T5.chat_failures` | Sohbet verisi yok **ve etik olarak istenmedi** |
| `V1.weekly_digest` | `parent_link` yok — velinin kim olduğu çözülemiyor |
| `Y1.uncovered_subject` | Konu sayaçları ve sınav listesi yok |
| `Y1.grade_inconsistency` | `class_blueprint` verisi yok |
| `Y1.ungraded_exam` | Sınav listesi yok |

Bu liste koddan okunabilir: `recommend.unavailable_rules()`. CLI çıktısında da
`unavailable_rules` anahtarıyla döner — ekranın "neden boş" sorusunu
cevaplaması için.

---

## 4. Yaşam döngüsü

### 4.1 Ne zaman yazılır

| Tablo | Yazan | Ne zaman | Köprü çağrısı |
|---|---|---|---|
| `zeka_student_summary` (+`zeka_attention_item`) | `pipeline.run_school` | Gece koşusu, okul başına | `insight.summary.upsert` |
| `zeka_recommendation` | `pipeline.run_school` **ve** `segment.cli run --persist` | Gece koşusu / segmentasyon koşusu | `insight.recommendation.upsert` |
| `zeka_run` (+`zeka_run_pending`, `zeka_run_failed_module`) | `pipeline.run_school` | Koşu başı ve sonu | `insight.run.upsert` |
| `zeka_question_segment` (+`zeka_question_segment_dimension`) | `segment.cli run --persist` | Segmentasyon koşusu (ayrı, seyrek) | `insight.segment.upsert` |
| `zeka_student_segment_profile` | `segment.cli run --persist` | Segmentasyon koşusu | `insight.profile.upsert` |

Yazma **500 satırlık gruplar** hâlindedir; grup reddedilirse ikinci kez
denenir, ikinci düşüşte atlanır ve koşu `partial` yazılır. Sessiz başarı yoktur.

`O2.segment_*` satırlarını **segmentasyon koşusu** üretir, gece koşusu
değil. Sebep ölçüseldir: segment kuralları kohort ortalamasına göre
ateşler ve o ortalama ancak bütün öğrenciler hesaplandıktan sonra bilinir.
`T3.segment_class_gap` ise **hiçbiri** tarafından üretilmez: şube üyeliği ve
ders öğretmeni `Source` arayüzünden gelir, segmentasyon hattının elinde
yoktur. Öğretmeni çözülemeyen madde üretilmez; kural kodda ve katalogda
hazırdır, çağıran taraf sınıf/öğretmen eşlemesini verdiğinde çalışır.

**Upsert** seçimi güvenlik kararıdır: tam değiştirme kullansaydık her koşu,
kullanıcının **"bu tavsiye faydalı değil"** kaydını (`dismissed_at`,
`dismissed_by`, `dismiss_reason`) sessizce silerdi. Bu üç alanı yalnız
uygulama yazar; ZEKA hiç üretmez.

Segment tabloları gece koşusuna **bağlı değildir**: `--persist` verilmediği
sürece segmentasyon hattı tek bir `insight.*` yazma çağrısı bile yapmaz.
Segmentasyon hiç koşmamışsa `zeka_question_segment` ve
`zeka_student_segment_profile` boştur, `O2.segment_*` / `T3.segment_class_gap`
kuralları **hiç üretilmez** — ekran bunun için boş kart göstermemeli, o bölümü
**hiç göstermemelidir**.

### 4.2 Ne zaman düşer

İki ayrı kavram vardır ve karıştırılmamalıdır:

* **`expires_at`** (`zeka_recommendation`): *gösterme*. Bu andan sonra tavsiye
  ekranda **görünmez**, ama satır hâlâ durur.
* **`retain_until`** (her tablo): *silme*. Gece koşusunun sonunda
  `insight.retention.sweep` çağrısı satırları **gerçekten siler**; süpürmeyi
  koşturan taraf backend'dir, çünkü sınırı yazan taraf ZEKA'dır ve süpürme
  okulun veritabanında koşar.

Ayrıca **mezuniyet/ayrılma temizliği** vardır (`insight.departed.purge`):
öğrenci listesinde olmayan kişinin `zeka_student_summary`,
`zeka_student_segment_profile` ve hakkındaki `zeka_recommendation` satırları
silinir. `zeka_question_segment` bundan **etkilenmez**: o satır bir soru
hakkındadır, kişisel veri değildir.

### 4.3 Kullanıcı kapatınca ne olur

1. Uygulama `zeka_recommendation` satırına `dismissed_at`, `dismissed_by`,
   `dismiss_reason` yazar. **ZEKA bu alanları hiç üretmez.**
2. Satır **silinmez**. Kapatma bir veridir: bir kural sürekli "bu doğru değil"
   ile kapanıyorsa kural yanlıştır. `(rule_id, created_at)` indeksi tam bu
   ölçüm içindir.
3. Ertesi gece aynı kural yeniden ateşlerse **upsert** sayesinde kapatma izi
   **korunur** (bu yüzden tam değiştirme değil). Ekran kapatılmış bir tavsiyeyi
   tekrar göstermemelidir; `dismissed_at` dolu olan satır filtrelenir.
4. Süpürme kapatılmış satırı da normal `retain_until`'ünde siler.

**Otomatik eylem yoktur.** Hiçbir tavsiye bir notu değiştirmez, bir öğrenciyi
bir gruba atamaz. `store.py` yalnız bu dokuz tabloya yazar; başka bir tabloyu
güncelleyen bir yol **yoktur** ve bu yapısal olarak garantidir: servis yalnız
`insight.*` çağrıları yapar, o çağrıların da dokunabildiği tablo kümesi
yukarıdaki dokuzdur.

---

## 5. Dikkat listesi — öğrenciye gösterilmeyecek alanlar

| Alan | Nerede | Neden gösterilmez |
|---|---|---|
| `zeka_recommendation` satırları, `audience_role = teacher` | tümü | **Rol kapısı.** T4 maddeleri yalnız öğretmene gider; öğrenciye ve veliye gösterilmez (`[T§6.8]`). İstemci bu alanı **sunucu tarafında** filtrelemeli |
| `zeka_recommendation.about` | öğretmen kartlarında | Başka bir öğrencinin kimliği. Öğrenci arayüzüne hiç gitmemeli |
| `zeka_attention_item` satırları | tümü | Dikkat listesi bir **öğretmen aracıdır**. Öğrenciye "senin hakkında şu tetikleyiciler var" demek damgalamadır (`[T§6.6]`) |
| `zeka_question_segment.rationale` | öğrenci ekranı | Modelin bir soru hakkındaki gerekçesi. Sınav güvenliği: sorunun tuzağını ve çözüm yapısını anlatır. Ayrıca bir LLM çıktısıdır ve hatalıdır |
| `zeka_question_segment.trap_choice` | öğrenci ekranı | **Doğrudan cevap ipucu.** Sınav öncesi görülürse ölçüm geçersizleşir |
| `zeka_question_segment.confidence_*` | öğrenci ekranı | Modelin kendi güveni **kalibre edilmemiştir**; sayı olarak gösterilmesi olduğundan çok anlam taşır |
| `zeka_student_segment_profile.accuracy` | tek başına | Genel yeteneği yansıtır, ayrım gücü yoktur. "Analiz sorularında %38'sin" cümlesi yanıltıcıdır; gösterilecekse `contrast` ile **birlikte** ve karşılaştırmasıyla gösterilmelidir |
| `zeka_student_segment_profile` satırları, `confidence = none` | tümü | n < 30. Gürültü. Depoda durur, **ekranda durmaz** |
| `zeka_run_pending` satırları | her ekran | İç muhasebe; kişi listesi. Yalnız yönetim/gözlem arayüzüne |

Ayrıca **şemada olmayan** ve olmayacak olanlar, çünkü var olsalardı sıralama ve
damgalama üretirlerdi: `risk_score`, `rank`, `severity`, `weight`, tek bir
"öğrenci puanı". Bir ekran bunlardan birine ihtiyaç duyuyorsa, ihtiyacın
kendisi gözden geçirilmelidir.

---

## 6. Okuma yüzeyi — bu satırları kim okur

ZEKA'nın tabloları **ZEKA'nın veritabanı değildir**: okulun kendi
veritabanındadır ve okunduğu yer de backend'dir (`/insights` yuvası). Servis
yalnız **yazar** ve koşuya devam etmek için gereken tek listeyi okur
(`insight.pending.list`). Bu yüzden burada okuma sorgusu kalıbı yoktur —
eskiden burada duran kalıplar serviste artık bulunmayan bir veritabanını
tarif ediyordu.

Okumanın nerede olursa olsun uyması gereken kurallar:

| Kural | Neden |
|---|---|
| `school` kolonu **yok** | Kiracı, veritabanının kendisidir. Okuma zaten o okulun veritabanına kapsanmıştır; ayrı bir okul filtresi yanlış okulun satırını getiremez, çünkü satır orada değildir |
| `audience_role = 'teacher'` satırları öğrenciye/veliye **gösterilmez** | Rol kapısı (§5, `[T§6.8]`) |
| `expires_at > now` **ve** `dismissed_at` boş | Süre dolmuş ya da kapatılmış tavsiye ekranda görünmez (§4.3) |
| `confidence = 'none'` satırlar okunmaz | n < 30 gürültüdür; depoda durur, ekranda durmaz (§5) |
| Kimlikler `uuid` | Eski metin-kimlik tuzağı (`type::string()` sarması) veritabanıyla birlikte **ortadan kalktı**: kimlik artık gerçek bir uuid ve karşılaştırma düz eşitliktir |

Son madde, eski bir tuzak sınıfının kapandığı yerdir: eski şemada her kimlik
`user:01K42...` biçimli bir **metindi** ve veritabanı onu uçta kayda çevirirdi;
sarma unutulunca karşılaştırma sessizce **sıfır satır** dönerdi. `uuid` FK ile
bu tuzak yapısal olarak imkânsızdır.

---

## 7. Bilinen sınırlar

1. **Madde istatistiği yoktur.** `question_stat` (p-değeri, ayırt edicilik,
   çeldirici dağılımı) bu sürümde üretilmiyor; köprü izin listesinde sınav
   yolu yok. `zeka_question_segment` onun yerine geçmez — etiket taşır, istatistik
   değil.
2. **`student_subject_stat` yoktur.** Konu bazlı öğrenci özeti aynı sebeple
   üretilemiyor.
3. **Segment etiketleri bir dil modelinin çıktısıdır** ve hatalıdır. Ölçülmüş
   isabet oranları ve kural performansı `docs/SEGMENT-CIKTI.md`'dedir; ekran
   "kesin" dilini kullanmamalıdır.
4. **Segment eşikleri tek bir kohortta ölçüldü.** Başka bir okulda kontrol
   dağılımı farklı olacaktır; eşiklerin kohort başına yeniden ölçülmesi
   gerekir (`SEGMENT-CIKTI.md` §8).
5. **`T3.segment_class_gap` gerçek bir sınıfta hiç ateşlemedi** — yalnız yapay
   pozitif kontrolde. Ekranı kurulabilir, ama boş kalabileceği varsayılmalıdır.
6. **`insight.*` depo kapıları açıldı (`f84c29d`); backend'in ZEKA'yı çağırması
   2026-09-18'de `insight.student` + `insight.refresh` için açıldı** ve servis
   tarafı aynı gün bağlandı (`service/src/handlers.py`; ilan ile dağıtım
   açılışta `verify_dispatchable()` ile denetlenir). `insight.class` ilan
   edilir ama gönderilmez: kadro listeleme yolu yok. Sahibi backend'deki
   `InsightDoors` hattı — `docs/BACKEND-GEREKSINIMLERI.md` Madde 1.
