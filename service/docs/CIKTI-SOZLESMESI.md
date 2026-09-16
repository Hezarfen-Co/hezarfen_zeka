# ZEKA Çıktı Sözleşmesi

> **Frontend ve backend ekibine verilecek tek belge budur.**
> ZEKA'nın ürettiği her satır, her alan, her kural kimliği burada.
> DDL kaynağı: `service/schema/zeka.surql`. Yazan katman:
> `service/src/store.py`. Kural motoru: `service/src/compute/recommend.py`.

---

## 0. Beş cümlede sözleşme

1. ZEKA **kendi** SurrealDB veritabanına yazar (ns/db: `hezarfen`/`zeka`).
   **Okul veritabanına hiçbir koşulda yazmaz**; okul verisini yalnız okur.
2. Tablo sayısı **beş**tir ve bu listenin dışında bir tablo yoktur.
3. Bütün zaman alanları **i64 unix milisaniye, UTC**. `datetime` tipi
   kullanılmaz.
4. Bütün kimlikler (öğrenci, soru, sınav, ders, konu) **düz metin**dir,
   `record` bağlantısı değildir: ZEKA'nın veritabanında okul tabloları yoktur.
   Biçim okul tarafındaki hâliyle korunur (`user:01K42...`).
5. **Tek bir "risk skoru" alanı yoktur.** Hiçbir tabloda `score`, `rank`,
   `weight`, `severity` alanı bulunmaz ve bulunmayacaktır — sıralama şemadan
   üretilemesin diye (`[T§6.6]`).

---

## 1. Tabloların özeti

| # | Tablo | Satır neyi anlatır | Anahtar | Saklama |
|---|---|---|---|---|
| 1 | `student_summary` | Bir öğrencinin gecelik özeti | `{school}_{student}` | 400 gün |
| 2 | `recommendation` | Üretilmiş tek tavsiye + kanıtı | `{school}_{audience}_{product}_{rule_id}_{scope}` | `min(expires_at, +90 gün)` |
| 3 | `insight_run` | Koşu defteri | `{school}_{YYYY-MM-DD}` | 90 gün |
| 4 | `question_segment` | Bir sorunun bilişsel etiketi | `{school}_{question}` | 1095 gün |
| 5 | `student_segment_profile` | Öğrenci × boyut × etiket performansı | `{school}_{student}_{dimension}_{label}` | 400 gün |

Anahtarlar **kompozit**tir: tekillik yapısaldır, `UNIQUE` indekse gerek yoktur
ve gece koşusunu tekrar çalıştırmak satır çoğaltmaz (UPSERT idempotent).

---

## 2. Tablolar, alan alan

### 2.1 `student_summary`

| Alan | Tip | Anlam |
|---|---|---|
| `school` | `string` | Okul slug'ı (kiracı ayracı). Her sorguya konur. |
| `student` | `string` | Öğrenci kimliği |
| `marks` | `option<object>` FLEXIBLE | Not modülü çıktısı: `courses.<course>.{average, n_marks, placement{band, z, class_average, class_sd, cohort_n, confidence}}` |
| `attendance` | `option<object>` FLEXIBLE | Devam modülü çıktısı |
| `submission` | `option<object>` FLEXIBLE | Ödev/teslim modülü çıktısı; `upcoming[]` yaklaşan teslimler |
| `study` | `option<object>` FLEXIBLE | Çalışma (pomodoro) modülü çıktısı |
| `attention` | `option<array<object>>` | **Dikkat listesi.** Her öğe TEK tetikleyici: `{trigger, fact, evidence, window_from, window_to}` |
| `confidence` | `string` | `none` \| `exploratory` \| `stable` |
| `computed_at` | `int` | Hesap anı (unix ms) |
| `retain_until` | `int` | Bu damgadan sonra süpürülür |

`marks`/`attendance`/`submission`/`study` **FLEXIBLE**'dır: şekil hesap
modülüne aittir ve her kural sürümünde şema değişmek zorunda kalmaz. Frontend
bu nesnelerin içinden **okuduğu alanı adıyla** almalı, sırayla değil.

### 2.2 `recommendation`

| Alan | Tip | Anlam |
|---|---|---|
| `school` | `string` | Okul slug'ı |
| `audience` | `string` | **Kime gösterilecek** (öğrenci ya da öğretmen kimliği) |
| `about` | `option<string>` | **Kim hakkında.** Öğrenci kendi kartında boştur |
| `audience_role` | `string` | `student` \| `teacher` \| `parent` \| `manager` — **rol kapısı** |
| `product` | `string` | `O1` \| `O2` \| `O3` \| `O4` \| `T3` \| `T4` |
| `course` | `option<string>` | İlgili ders (varsa) |
| `rule_id` | `string` | Hangi kural (§3 listesi) |
| `rule_version` | `int` | Kural kataloğu sürümü. Arttığında kullanıcıya "hesaplama yöntemi güncellendi" gösterilir |
| `evidence` | `object` FLEXIBLE | **Boş olamaz.** "Neden?" ekranını besleyen sayılar; içinde ayrıca `limitation` (Sınır satırı) |
| `confidence` | `string` | `none` \| `exploratory` \| `stable` |
| `created_at` | `int` | Üretim anı |
| `expires_at` | `int` | Bu andan sonra **gösterilmez** |
| `retain_until` | `int` | Bu andan sonra **silinir** |
| `dismissed_at` | `option<int>` | Kullanıcı kapattıysa an |
| `dismissed_by` | `option<string>` | Kapatan kişi |
| `dismiss_reason` | `option<string>` | `bu doğru değil` gibi serbest metin |

**Beş bölümlü "Neden?"** zorunludur: Olgu · Karşılaştırma · Kural (hangi eşik,
hangi sürüm) · **Sınır** (neyin dahil olmadığı) · Tarih. Sınır satırı
`evidence.limitation` alanındadır ve **gösterilmesi zorunludur**; o satır
olmadan ürün olduğundan çok şey bildiğini ima eder.

`dismissed_*` alanlarını **yalnız uygulama yazar**. Gece koşusu `MERGE`
kullanır ve bu alanlara dokunmaz.

### 2.3 `insight_run`

| Alan | Tip | Anlam |
|---|---|---|
| `school` | `string` | Okul |
| `started_at` / `finished_at` | `int` / `option<int>` | Koşu penceresi |
| `status` | `string` | `running` \| `ok` \| `partial` \| `failed` \| `skipped` |
| `duration_ms` | `option<int>` | Süre |
| `students_total` / `students_ok` / `students_failed` / `students_skipped` | `int` | Muhasebe |
| `rows_written` | `int` | Yazılan satır |
| `pending_students` | `option<array<string>>` | Bütçe aşıldıysa **devreden** öğrenciler; sonraki koşu buradan devam eder |
| `failed_modules` | `option<array<string>>` | Düşen modül adları → UI'da "eksik" işareti |
| `budget_exceeded` | `bool` | Zaman bütçesi aşıldı mı |
| `budget_ms` | `int` | Tavan |
| `retain_until` | `int` | 90 gün |

`status = partial` ise ekran **"bu gece bazı öğrenciler işlenemedi"** demeli;
sessizce eksik veri göstermemeli.

### 2.4 `question_segment` — YENİ

Bir sorunun bilişsel etiketi. **Kişisel veri değildir**, hiçbir öğrenciye
bağlanamaz. Kaynağı `service/src/segment/` hattıdır (LLM etiketleme).

| Alan | Tip | Anlam |
|---|---|---|
| `school` | `string` | Okul slug'ı |
| `question` | `string` | Soru kimliği (`exam_question:<ULID>`) |
| `exam` | `option<string>` | Sınav kimliği |
| `course` | `option<string>` | Ders kimliği (kaynakta yoksa boş) |
| `subject` | `option<string>` | Konu kimliği |
| `bilissel_talep` | `string` | `hatirlama` \| `uygulama` \| `analiz` |
| `dikkat_tuzagi` | `string` | `var` \| `yok` |
| `okuma_yuku` | `string` | `dusuk` \| `yuksek` |
| `adim_sayisi` | `string` | `tek_adim` \| `cok_adim` — **DENEYSEL** (aşağı akışta kullanılmaz) |
| `confidence_bilissel_talep` | `float` | Modelin bu boyuttaki güveni [0,1] |
| `confidence_dikkat_tuzagi` | `float` | " |
| `confidence_okuma_yuku` | `float` | " |
| `confidence_adim_sayisi` | `float` | " |
| `confidence` | `string` | Satır kademesi: **üretim** boyutlarının en düşük güveninden türetilir. Deneysel boyut bu kademeye girmez |
| `downstream_dimensions` | `option<array<string>>` | Öğrenci profiline ve kurallara **giren** boyutlar |
| `experimental_dimensions` | `option<array<string>>` | Etiketlenen ama **girmeyen** boyutlar |
| `trap_choice` | `option<string>` | `dikkat_tuzagi = var` ise tuzak şıkkın kimliği. `yok` ise alan **hiç yazılmaz** |
| `rationale` | `string` | Modelin kendi gerekçesi, en fazla iki cümle. **Öğrenciye gösterilmez** (§5) |
| `model` | `string` | Etiketi üreten model kimliği |
| `prompt_version` | `string` | İstem sürümü |
| `variant` | `option<string>` | Etiketleyici varyantı (`baseline`, `self_consistency`, …) |
| `computed_at` | `int` | Etiketleme anı |
| `retain_until` | `int` | 1095 gün |

**Deneysel boyut neden şemada duruyor:** `adim_sayisi` etiketlenir ve
raporlanır, ama LLM etiketlemesinde kararlılık kapısını (alpha ≥ 0,70)
geçemedi. Bu yüzden öğrenci profiline ve tavsiye kurallarına **girmez**. Bunu
belgeye bakmadan anlayabilmek için satırın kendisi iki listeyi taşır. Frontend
`downstream_dimensions` içinde olmayan bir boyutu **karar ekranında
kullanmamalıdır**.

### 2.5 `student_segment_profile` — YENİ

| Alan | Tip | Anlam |
|---|---|---|
| `school` | `string` | Okul slug'ı |
| `student` | `string` | Öğrenci kimliği |
| `dimension` | `string` | `bilissel_talep` \| `dikkat_tuzagi` \| `okuma_yuku` (yalnız üretim boyutları) |
| `label` | `string` | O boyutun bir etiketi |
| `n_answers` | `int` | Bu segmentte **işaretlenmiş** cevap sayısı (boş bırakılan madde paydaya girmez) |
| `n_correct` | `int` | Doğru sayısı |
| `accuracy` | `float` | `n_correct / n_answers`. **Tek başına gösterilmez** (§5) |
| `overall_n_answers` | `int` | Öğrencinin etiketli tüm maddelerdeki cevap sayısı |
| `overall_accuracy` | `float` | Öğrencinin genel doğruluğu |
| `contrast` | `float` | **`accuracy − overall_accuracy`.** Bu tablonun asıl ölçüsü |
| `confidence` | `string` | `none` (n<30) \| `exploratory` (n≥30) \| `stable` (n≥100) |
| `computed_at` | `int` | Hesap anı |
| `retain_until` | `int` | 400 gün |

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
| `O1.review_band` | O1 | öğrenci | Bu derste tekrar önerilir | `student_summary.marks` (`placement.band = review`, n_marks ≥ 3) |
| `O2.segment_cognitive_gap` | O2 | öğrenci | Bu tür sorularda kendi genel seviyene göre geridesin | `student_segment_profile` (`bilissel_talep`, `okuma_yuku`); n ≥ 100 ve göreli kontrast ≤ −0,080 / −0,060 |
| `O2.segment_trap_prone` | O2 | öğrenci | Dikkat tuzağı taşıyan sorularda akranlarına göre daha çok kaybediyorsun | `student_segment_profile` (`dikkat_tuzagi=var`); n ≥ 100 ve göreli kontrast ≤ −0,032 |
| `O3.pattern` | O3 | öğrenci | Çalışma düzenin şöyle görünüyor | `student_summary.study` (n_stints ≥ 5) |
| `O4.deadline` | O4 | öğrenci | Yaklaşan teslim | `student_summary.submission.upcoming` |
| `T3.class_gap` | T3 | öğretmen | Sınıf düzeyinde boşluk | `marks` (kohort ort. < 50, kohort ≥ 8) |
| `T3.individual_gap` | T3 | öğretmen | Bireysel destek | `marks` (kohort ort. ≥ 50, z < −0,8) |
| `T3.segment_class_gap` | T3 | öğretmen | Sınıf bu bilişsel segmentte topluca geride | `student_segment_profile` sınıf toplaması; ≥ 8 öğrenci ve sınıf ortalama göreli kontrast ≤ −0,040. **Bugün hiçbir koşu bunu üretmiyor** — §4.1 |
| `T4.attendance` | T4 | **yalnız öğretmen** | Devam tetikleyicisi | `student_summary.attention` |
| `T4.homework` | T4 | **yalnız öğretmen** | Ödev tetikleyicisi | `student_summary.attention` |
| `T4.mark_trend` | T4 | **yalnız öğretmen** | Not eğilimi tetikleyicisi | `student_summary.attention` |

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

| Tablo | Yazan | Ne zaman | Kip |
|---|---|---|---|
| `student_summary` | `pipeline.run_school` | Gece koşusu, okul başına | `CONTENT` (tam değiştirir) |
| `recommendation` | `pipeline.run_school` **ve** `segment.cli run --persist` | Gece koşusu / segmentasyon koşusu | **`MERGE`** |
| `insight_run` | `pipeline.run_school` | Koşu başı ve sonu | `CONTENT` |
| `question_segment` | `segment.cli run --persist` | Segmentasyon koşusu (ayrı, seyrek) | **`MERGE`** |
| `student_segment_profile` | `segment.cli run --persist` | Segmentasyon koşusu | **`MERGE`** |

`O2.segment_*` satırlarını **segmentasyon koşusu** üretir, gece koşusu
değil. Sebep ölçüseldir: segment kuralları kohort ortalamasına göre
ateşler ve o ortalama ancak bütün öğrenciler hesaplandıktan sonra bilinir.
`T3.segment_class_gap` ise **hiçbiri** tarafından üretilmez: şube üyeliği ve
ders öğretmeni `Source` arayüzünden gelir, segmentasyon hattının elinde
yoktur. Öğretmeni çözülemeyen madde üretilmez; kural kodda ve katalogda
hazırdır, çağıran taraf sınıf/öğretmen eşlemesini verdiğinde çalışır.

`MERGE` seçimi güvenlik kararıdır: `CONTENT` ile yazılsaydı her koşu,
kullanıcının **"bu tavsiye faydalı değil"** kaydını ve dışarıdan eklenmiş
alanları sessizce silerdi.

Segment tabloları gece koşusuna **bağlı değildir**: `--persist` verilmediği
sürece segmentasyon hattı tek bir SurrealQL ifadesi bile çalıştırmaz.
Segmentasyon hiç koşmamışsa `question_segment` ve `student_segment_profile`
boştur, `O2.segment_*` / `T3.segment_class_gap` kuralları **hiç üretilmez** —
ekran bunun için boş kart göstermemeli, o bölümü **hiç göstermemelidir**.

### 4.2 Ne zaman düşer

İki ayrı kavram vardır ve karıştırılmamalıdır:

* **`expires_at`** (`recommendation`): *gösterme*. Bu andan sonra tavsiye
  ekranda **görünmez**, ama satır hâlâ durur.
* **`retain_until`** (her tablo): *silme*. Gece koşusunun sonunda
  `DELETE <tablo> WHERE retain_until < now` çalışır ve satır **gerçekten
  silinir**.

Süpürme her koşunun **en sonunda**, okul bazında, sıralı koşar.

Ayrıca **mezuniyet/ayrılma temizliği** vardır: öğrenci listesinde olmayan
kişinin `student_summary`, `student_segment_profile` ve hakkındaki
`recommendation` satırları silinir. `question_segment` bundan **etkilenmez**:
o satır bir soru hakkındadır, kişisel veri değildir.

### 4.3 Kullanıcı kapatınca ne olur

1. Uygulama `recommendation` satırına `dismissed_at`, `dismissed_by`,
   `dismiss_reason` yazar. **ZEKA bu alanları hiç üretmez.**
2. Satır **silinmez**. Kapatma bir veridir: bir kural sürekli "bu doğru değil"
   ile kapanıyorsa kural yanlıştır. `recommendation_rule` indeksi
   (`rule_id, created_at`) tam bu ölçüm içindir.
3. Ertesi gece aynı kural yeniden ateşlerse `MERGE` sayesinde kapatma izi
   **korunur**. Ekran kapatılmış bir tavsiyeyi tekrar göstermemelidir;
   `dismissed_at` dolu olan satır filtrelenir.
4. Süpürme kapatılmış satırı da normal `retain_until`'ünde siler.

**Otomatik eylem yoktur.** Hiçbir tavsiye bir notu değiştirmez, bir öğrenciyi
bir gruba atamaz. `store.py` yalnız bu beş tabloya yazar; buradan okuyup başka
bir tabloyu güncelleyen bir yol **yoktur** ve bu şema düzeyinde garantidir.

---

## 5. Dikkat listesi — öğrenciye gösterilmeyecek alanlar

| Alan | Nerede | Neden gösterilmez |
|---|---|---|
| `recommendation` satırları, `audience_role = teacher` | tümü | **Rol kapısı.** T4 maddeleri yalnız öğretmene gider; öğrenciye ve veliye gösterilmez (`[T§6.8]`). İstemci bu alanı **sunucu tarafında** filtrelemeli |
| `recommendation.about` | öğretmen kartlarında | Başka bir öğrencinin kimliği. Öğrenci arayüzüne hiç gitmemeli |
| `student_summary.attention[]` | tümü | Dikkat listesi bir **öğretmen aracıdır**. Öğrenciye "senin hakkında şu tetikleyiciler var" demek damgalamadır (`[T§6.6]`) |
| `question_segment.rationale` | öğrenci ekranı | Modelin bir soru hakkındaki gerekçesi. Sınav güvenliği: sorunun tuzağını ve çözüm yapısını anlatır. Ayrıca bir LLM çıktısıdır ve hatalıdır |
| `question_segment.trap_choice` | öğrenci ekranı | **Doğrudan cevap ipucu.** Sınav öncesi görülürse ölçüm geçersizleşir |
| `question_segment.confidence_*` | öğrenci ekranı | Modelin kendi güveni **kalibre edilmemiştir**; sayı olarak gösterilmesi olduğundan çok anlam taşır |
| `student_segment_profile.accuracy` | tek başına | Genel yeteneği yansıtır, ayrım gücü yoktur. "Analiz sorularında %38'sin" cümlesi yanıltıcıdır; gösterilecekse `contrast` ile **birlikte** ve karşılaştırmasıyla gösterilmelidir |
| `student_segment_profile` satırları, `confidence = none` | tümü | n < 30. Gürültü. Depoda durur, **ekranda durmaz** |
| `insight_run.pending_students` | her ekran | İç muhasebe; kişi listesi. Yalnız yönetim/gözlem arayüzüne |

Ayrıca **şemada olmayan** ve olmayacak olanlar, çünkü var olsalardı sıralama ve
damgalama üretirlerdi: `risk_score`, `rank`, `severity`, `weight`, tek bir
"öğrenci puanı". Bir ekran bunlardan birine ihtiyaç duyuyorsa, ihtiyacın
kendisi gözden geçirilmelidir.

---

## 6. Sorgu kalıpları

> ### ⚠️ Kimlikle sorgularken `type::string()` zorunlu
>
> SurrealDB 3, RPC ile gönderilen `"user:01K42..."` biçimli bir **metni** uçta
> `record` değerine çevirir. Bu yüzden
> `WHERE student = $s` karşılaştırması bir kimlik için **sessizce boş sonuç**
> döner — hata vermez, sıfır satır döner. En kötü türden bir tuzaktır.
>
> ```sql
> -- YANLIŞ: her zaman boş döner
> SELECT * FROM student_segment_profile WHERE student = $s;
> -- DOĞRU
> SELECT * FROM student_segment_profile WHERE student = type::string($s);
> ```
>
> Kural: iki nokta içeren **her** değişken karşılaştırması (öğrenci, soru,
> sınav, ders, konu kimliği) `type::string()` ile sarılır. `school` slug'ı iki
> nokta içermediği için sarılmasına gerek yoktur. Yazma tarafında aynı sarma
> `store.py` içinde otomatik yapılır; okuma tarafı çağıranın sorumluluğudur.
> Doğrulayan test: `tests/test_store.py::test_kimlikle_sorgulama_type_string_ister`.

```sql
-- Bir öğrencinin kartı
SELECT * FROM student_summary
 WHERE school = $school AND student = type::string($student);

-- Öğrenciye gösterilecek tavsiyeler (rol kapısı + süre + kapatma)
SELECT * FROM recommendation
 WHERE school = $school AND audience = type::string($student)
   AND audience_role = 'student'
   AND expires_at > $now AND dismissed_at = NONE
 ORDER BY created_at DESC;

-- Öğretmenin dikkat listesi
SELECT * FROM recommendation
 WHERE school = $school AND audience = type::string($teacher)
   AND audience_role = 'teacher' AND expires_at > $now
 ORDER BY created_at DESC;

-- Bir öğrencinin segment profili (gösterilebilir olanlar)
SELECT dimension, label, n_answers, accuracy, contrast, confidence
  FROM student_segment_profile
 WHERE school = $school AND student = type::string($student)
   AND confidence != 'none';

-- Bir sınavın soru etiketleri
SELECT question, bilissel_talep, dikkat_tuzagi, okuma_yuku, confidence
  FROM question_segment
 WHERE school = $school AND exam = type::string($exam);
```

Her sorguda `school` **zorunludur**: kiracı ayrımı indeks düzeyinde bu alana
dayanır ve onsuz sorgu tam tarama yapar.

---

## 7. Bilinen sınırlar

1. **Madde istatistiği yoktur.** `question_stat` (p-değeri, ayırt edicilik,
   çeldirici dağılımı) bu sürümde üretilmiyor; köprü izin listesinde sınav
   yolu yok. `question_segment` onun yerine geçmez — etiket taşır, istatistik
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
6. **WebSocket taşıması denenmedi.** Bütün doğrulama HTTP `/rpc` üzerinden
   yapıldı (`docs/DEPOLAMA.md` §7).
