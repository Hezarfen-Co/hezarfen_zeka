# Hesap modüllerinin altın etikete karşı doğrulanması

**Ne yapıldı:** `service/src/compute/` altındaki hesap modülleri bugüne kadar
yalnız sentetik birim testleriyle sınandı. Bu belge, aynı modüllerin
`seed/_seed_manifest.json` içindeki **250 öğrencinin gizli gerçeğine** karşı
ölçülmüş isabetini raporlar.

| | |
|---|---|
| Ölçüm anı | `T_NOW = 2026-04-13T08:00+03:00` (`1776056400000` ms) |
| Öğrenci | 250 (A1 30 · A2 70 · A3 35 · A4 32 · A5 25 · A6 22 · A7 18 · A8 18) |
| Fikstür üretici | `tools/build_student_fixtures.py` (tohum `.surql` → `Source` biçimi) |
| Fikstür | `service/fixtures/gold_students/` (35 MB, 250 × 5 dosya + `gold.json`) |
| Testler (ölçüm) | `service/tests/test_compute_gold.py` — ilk ölçüm, kusurları sabitler |
| Testler (düzeltme) | `service/tests/test_compute_attention.py` — 29 test, düzeltmenin gerileme koruması |
| Modül kodu | ilk ölçümde **değiştirilmedi**; §5'teki düzeltme turunda K1/K2/K5/K5b/K6/K7 giderildi |

---

## 0. Geçerlilik uyarısı — hangi ölçüm geçerli, hangisi değil

Bu tohum verisinde **soru metni ile madde zorluğu bağımsız üretilmiştir**
(`spec/SENARYO.md` Ek B). Yani bir sorunun metnine bakıp zorluğunu, konusunu ya
da öğrencinin ona vereceği cevabı kestiren hiçbir iddia bu veriyle
doğrulanamaz; metne dayalı her ölçüm **geçersizdir**.

Aşağıdaki yedi ölçümün **hiçbiri metne dayanmaz.** Hepsi doğrudan
`exam_result.mark`, `session_attendance.status`, `homework_submission` ve
`pomodoro_session` kayıtlarından türer; bu kayıtlar arketip parametrelerinden
üretilmiştir ve altın etiketle aynı üretim zincirindedir. Dolayısıyla **yedi
ölçüm de geçerlidir.**

Geçerli olmayan **alt** satırlar ayrıca işaretlendi:

| Geçersiz ölçüm | Neden |
|---|---|
| `gap_subjects` (konu düzeyi boşluk, 105 konu) | `Source` arayüzünde `exam_answer` ve `exam_question.subject` yok; `marks.py` ders düzeyinde çalışır. Konu düzeyi hiç üretilmiyor — ölçülecek bir çıktı yok. |
| §7.3 A10/A11/A12 (`counted_on_time`) | Köprü dondurulmuş `counted_on_time` alanını vermiyor; ölçü `last_touch` vekilidir. `submission.py` bu bayrağı (`counted_on_time_available = False`) taşıdığı sürece sonuç *doğrulanmış* sayılmaz. Sayılar yine de raporlandı (§4). |
| §7.5 P24 (dört tetikleyicinin dördü) | `TriggerKind.EXAM_MISSED` yapısal olarak hiç ateşlenemez (sınav takvimi / `exam_attempt` arayüzde yok). Ölçüt bu sürümde **tanımsızdır**, başarısız değil. |
| §7.5 P3 (A7'de "veri toplanıyor" ≥ %55) | Ölçüt konu × cevap düzeyinde (`n_answered >= 8`) tanımlı. Ders düzeyi karşılığı (`n_marks >= 3`) farklı bir kapıdır; ölçülen %20 ile %55 **karşılaştırılamaz**. |
| A5/A6 için `theta_base` korelasyonu | `theta_base` dönem **başındaki** yetenek; A5'te `T_NOW` yeteneği `theta_base + 1,5·progress`, A6'da `theta_base − 1,40`. Bugünün notu ile dünün yeteneğini karşılaştırmak anlamsızdır (§7). |

---

## 1. Özet tablo

| # | Ölçüm | Ölçülen | Senaryo beklentisi | Tuttu mu |
|---|---|---|---|---|
| 1 | `marks.py` eğilim — A5 (yükselen) | medyan eğim **+7,11** puan/30 gün; eşik +3,0 ile **K = 0,64 · D = 0,92** → *düzeltme sonrası* `rising` sınıfı + `is_rising()` ile **K = 0,79 · D = 0,76** | §3.2 Ö1: "T1 düşük → T2 güçlü" ayrımı | **Evet** (K6 giderildi, §5) |
| 1 | `marks.py` eğilim — A6 (düşen) | modülün kendi `dropped` kuralı: **K = 0,86 · D = 0,82** (18/22) | §3.9 tetikleyici 3: A6'nın tamamı | **Evet** (22'de 18) |
| 2 | Konu boşluğu — ders düzeyi | `Band.REVIEW` ile **K = 0,056**; *düzeltme sonrası* `within_student_contrast` ile **K = 1,00 · D = 0,857** (30 tahminin 30'unda ders de doğru) | §3.6 / §7.5 P19: "genel iyi, bir derste kötü" ayrımı | **Evet** (K7 giderildi, §5) |
| 2 | Konu boşluğu — konu düzeyi | üretilmiyor | §3.6 (ardışık 3 konu) | **Ölçülemez** (veri kısıtı) |
| 3 | `attendance.py` — A7 | modül eşikleriyle **K = 0,95 · D = 1,00** (18/18) | §3.10 / §7.3 A13–A15 | **Evet** |
| 4 | `submission.py` — A4 | `on_time < 0,60` → **D = 0,97**, ama A7'nin 18'i de içeride → **K = 0,62** | §3.7: "erteleyen" ayrımı | **Kısmen** — "erteleme" değil "teslim etmeme" ölçülüyor |
| 5 | `study.py` — sayılan oturum | **250/250 birebir** | `true_counted_pomodoro` | **Evet** |
| 5 | `study.py` — düzensiz çalışan (A4) | `burstiness` A4 **2,14** ↔ okul **2,18**; `pre_deadline_share` A4 **0,714** ↔ okul **0,700** | §3.7: "uzun, yoğun, düzensiz" | **Hayır — ve ölçülemiyor**; bayrak kaldırıldı (K5, §5) |
| 6 | `attention.py` — A6 listede | **22 / 22** → *düzeltme sonrası* **21 / 22** | §7.5 P22: ≥ 18 / 22 | **Evet** (bozulmadı) |
| 6 | `attention.py` — A5 yanlış pozitif | **20 / 25** → *düzeltme sonrası* **0 / 25** | §7.5 P23: ≤ 2 / 25 | **Evet** (K1+K2 giderildi, §5) |
| 6 | `attention.py` — liste büyüklüğü | **193 / 250** → *düzeltme sonrası* **46 / 250** | §7.5 P21: 32–48 | **Evet** (K1+K2 giderildi, §5) |
| 7 | Yetenek kestirimi | Spearman **0,923** (250); **0,969** (A5/A6 hariç, n = 203) | — (senaryoda ölçüt yok) | **Evet** |

*(K = kesinlik / precision, D = duyarlılık / recall.)*

---

## 2. Ölçüm ölçüm ayrıntı

### [1] `marks.py` eğilim tespiti ↔ `theta_trend`

Altın etiketteki `theta_trend`: A5 `+1,50` · A8 `+0,20` · A2/A1/A3/A6 `0,00` ·
A4 `−0,10` · A7 `−0,15`. (A6'nın düşüşü `theta_trend`'de değil `t_break_ms` +
`θ − 1,40` kırılmasında kodlanmış.)

Modül `course_trend()` içinde iki sayı üretiyor: `slope_per_30d` (regresyon
eğimi) ve `dropped` (son 3 ↔ önceki 3, ≥ 15 puan düşüş).

**Arketip başına medyan `slope_per_30d` (puan / 30 gün):**

| A1 | A2 | A3 | A4 | A5 | A6 | A7 | A8 |
|---|---|---|---|---|---|---|---|
| +0,71 | +0,93 | +0,46 | +0,84 | **+7,11** | **−5,94** | +0,16 | +0,98 |

A5 ve A6 dışındaki altı arketip 0,16–0,98 aralığına sıkışıyor; iki uç arasında
geniş bir boşluk var. Eşik taraması:

| Eşik (±) | Yükselen (A5) K / D | Düşen (A6) K / D |
|---|---|---|
| 2,0 | 0,39 / 0,92 | 0,61 / 0,91 |
| 3,0 | 0,64 / 0,92 | 0,82 / 0,82 |
| 4,0 | 0,82 / 0,88 | 0,94 / 0,73 |
| 5,0 | 0,91 / 0,80 | 1,00 / 0,64 |

Testte **+3,0** sabitlendi; bu değer sonucu güzelleştirmek için değil, iki küme
arasındaki boşluğun ortasına düştüğü için seçildi (ve seçim burada açıkça
yazılıdır).

Modülün **kendi** düşüş kuralı (`dropped`, `MARK_DROP_POINTS = 15`) A6'yı
21 tahminde 18 doğruyla buluyor (K = 0,86 · D = 0,82); yanlış pozitifler A1, A3
ve A8'den birer öğrenci.

> **Kusur K6 — yükselen için sınıf yok.** `course_trend()` `dropped` üretiyor
> ama `rising` / `improved` karşılığı yok. `spec/SENARYO.md` §3.2 Ö1 satırı A5
> için "T1 düşük → T2 güçlü" ürününü istiyor; modül ham eğimi veriyor, ürünü
> tüketiciye bırakıyor. Sebep: **modül kusuru** (eksik ürün), veri kısıtı değil
> — veri sinyali fazlasıyla taşıyor.

> **Sınır (kusur değil).** Sıralama `exam` ULID'inin **oluşturulma** damgasına
> dayanıyor (`marks._ordered_marks` bunu yazıyor). Bu veride sınav ULID'leri
> 2025-10-03 – 2026-03-31 arasında dağılmış ve sıralama tutarlı çıktı; yine de
> öğrencinin sınava girme anı bilinmiyor.

### [2] Konu boşluğu tespiti ↔ `gap_course` / `gap_subjects`

**Bu, tasarım belgesindeki en değerli üründür ve en zayıf sonucu burada aldık.**

Altın gerçek: 35 A3 öğrencisinin her birinde **1 boşluk dersi** ve o dersten
**ardışık 3 boşluk konusu** (toplam 105 konu).

**(a) Konu düzeyi — üretilemiyor.** `Source.marks()` ders bazında verilmiş
notları döndürüyor; ham `exam_answer` ve `exam_question.subject` izin
listesinde yok. `marks.py` başlığı bunu zaten söylüyor ve modül bir
`limitation` satırı taşıyor. Ölçülecek bir çıktı olmadığı için bu satır
**geçersiz ölçüm**dür — modül kusuru değil, **veri kısıtı**.

**(b) Ders düzeyi — bant çalışıyor ama seçici değil.**

| Ölçü | Değer |
|---|---|
| Altın boşluk dersi `Band.REVIEW` bandına düşen öğrenci | **31 / 35** (D = 0,886) |
| Okul genelinde toplam `REVIEW` (öğrenci, ders) çifti | **556** |
| Bunlardan altın boşluk dersi olan | 31 → **K = 0,056** |
| Boşluk dersi dışında `REVIEW` dersi olan öğrenci | **129 / 250** |
| Öğrencinin **en düşük z'li dersi** = altın boşluk dersi | **32 / 35** |

Arketip başına medyan `REVIEW` ders sayısı: A1 **0** · A2 1 · A3 1 · A4 4 ·
A5 4 · A6 0 · A7 **8** · A8 1. Yani bant, genel olarak zayıf öğrencinin
(A7) neredeyse **her** dersini kırmızıya boyuyor; A3'ün tek dersini onların
arasından ayıramıyor.

**(c) Veri bu ürünü destekliyor — eksik olan modül.** Modülün *kendi
çıktısından* türetilen bir ölçü — öğrencinin en düşük z'li dersi ile diğer
derslerinin medyan z'si arasındaki fark — A3'ü neredeyse kusursuz buluyor:

| Kontrast eşiği | Tahmin | DP | YP | K | D | Ders de doğru |
|---|---|---|---|---|---|---|
| −1,0 | 68 | 31 | 37 | 0,46 | 0,89 | 31 |
| −1,2 | 42 | 31 | 11 | 0,74 | 0,89 | 31 |
| **−1,5** | **30** | **30** | **0** | **1,00** | **0,86** | **30** |
| −2,0 | 20 | 20 | 0 | 1,00 | 0,57 | 20 |

Altın 35 öğrencide medyan kontrast **−2,18**, diğerlerinde **−0,71**.

> **Kusur K7 — öğrenci-içi kontrast yok.** `place_in_cohort()` öğrenciyi
> **kohorda** konumlandırıyor (dış karşılaştırma); "bu öğrenci kendi
> derslerine göre nerede" (iç karşılaştırma) hiçbir yerde hesaplanmıyor.
> `MODULLER.md` §2.3'ün z-bandı doğru uygulanmış; eksik olan ikinci eksen.
> Sebep: **modül kusuru / eksik ürün.** Eşik kalibrasyonu değil — mevcut
> çıktıya tek satır eklenerek K = 1,00 elde ediliyor.

### [3] `attendance.py` ↔ devamsız arketip A7

Arketip başına medyan devam oranı ve kohort medyanına göre fark:

| | A1 | A2 | A3 | A4 | A5 | A6 | A7 | A8 |
|---|---|---|---|---|---|---|---|---|
| `rate` | 0,982 | 0,930 | 0,942 | 0,884 | 0,932 | 0,905 | **0,667** | 0,934 |
| `relative_gap` | +0,047 | 0,000 | +0,019 | −0,036 | 0,000 | −0,015 | **−0,252** | −0,001 |

Modülün **kendi** dikkat eşikleri (`rate < 0,80` **ve**
`relative_gap ≤ −0,10`) 19 öğrenci seçiyor: A7'nin **18'i ve** 1 A6.
**K = 0,947 · D = 1,000.** Senaryo §7.3 A13/A14/A15 (A7 %69±4, A1 %97±2,
fark ≥ 20 puan) **tutuyor**: ölçülen 0,667 / 0,982 / 31,6 puan.

Kohort göreliliği ayrıca §7.5 **P26'yı da karşılıyor**: grip haftası tüm şubeyi
birlikte etkilediği için medyanı da kaydırıyor; tetiklenen 19 öğrencinin hepsi
gerçekten düşük devamlı. Kolektif olaydan kaynaklanan bireysel uyarı **0**.

> **Kusur K3 — A6'nın çöküşü görünmüyor.** Devam ucu yalnız **dönem
> kümülatifi** sayaç döndürdüğü için A6'nın kırılma sonrası %94 → %73 düşüşü
> dönem ortalamasının içinde eriyor (medyan 0,905). §3.9 tetikleyici 1 A6'nın
> **tamamında** ateşlenmesini bekliyor; ölçülen **1 / 22**. Sebep: **veri
> kısıtı** (satır düzeyinde tarih yok) — `attendance.py` başlığı bu sınırı
> zaten yazıyor ve `trend.available = False` taşıyor. Modül dürüst davranıyor;
> ürün eksik kalıyor.

> **Küçük bulgu.** Devam kohortu 208 kova üretiyor ama yalnız 110'u
> `usable` (≥ 8 kişi); geri kalanlar öğrencinin şubesine bağlı olmayan
> derslerden geliyor ve `relative_gap = None` bırakıyor. Bu, `COHORT_MIN`
> kapısının doğru çalıştığının kanıtı — yalnız 1 öğrencide genel
> `relative_gap` boş kaldı.

### [4] `submission.py` erteleme ↔ erteleyen arketip A4

Arketip başına medyan `on_time_rate_by_last_touch`:

| A1 | A2 | A3 | A4 | A5 | A6 | A7 | A8 |
|---|---|---|---|---|---|---|---|
| 0,961 | 0,755 | 0,813 | **0,463** | 0,692 | 0,736 | **0,326** | 0,791 |

| Eşik | Tahmin | A4 D | A4 K | İçeriye düşen diğer arketipler |
|---|---|---|---|---|
| 0,50 | 42 | 0,75 | 0,57 | A7 ×18 |
| **0,60** | **50** | **0,97** | **0,62** | A7 ×18, A5 ×1 |
| 0,70 | 75 | 1,00 | 0,43 | A7 ×18, A5 ×14, A6 ×6, A2 ×5 |

**Senaryo §7.3 A10/A11/A12** (geçerlilik uyarısı: `last_touch` vekili):
A4 ort. **0,465** (beklenen %48 ± 5 ✔), A1 ort. **0,961** (beklenen %97 ± 2 ✔),
fark **49,6 puan** (beklenen ≥ 40 ✔). Üç satır da **bantta**; ama
`counted_on_time_available = False` bayrağı açık olduğu sürece bu ampirik bir
uyuşmadır, doğrulama değil.

> **Kusur K4 — "erteleme" ölçülmüyor, "teslim etmeme" ölçülüyor.** A4'ün
> tanımlayıcı özelliği teslim payının medyanı (**−2 saat**, yani teslimlerin
> yarısı son tarihten *sonra*). `submitted_at` köprüde olmadığı için
> `procrastination.available = False` ve modül `median_lead_ms`,
> "son dakika" etiketi, son-24-saat yığılması üretmiyor. Geriye kalan tek ölçü
> A4'ü A7'den **ayıramıyor** — A7 daha da düşük. Sebep: **veri kısıtı**;
> modül bunu sahte sayıyla kapatmamış, doğru davranış.

### [5] `study.py` ↔ `true_counted_pomodoro` ve düzensiz çalışma

**Sayılan oturum sayısı: 250 / 250 birebir.** `study.countable()` kuralı
(`finished_at` dolu **ve** `counted is True`) altın etiketle her öğrencide tam
olarak aynı sayıyı veriyor. Katalogdaki en temiz sonuç budur.

Son 28 gün oturum sayısı medyanı:

| A1 | A2 | A3 | A4 | A5 | A6 | A7 | A8 |
|---|---|---|---|---|---|---|---|
| 104 | 30 | 41 | 34 | 38 | **3,5** | **0** | 55 |

A6'nın çöküşü (§3.9: 3,4 → 0,25 gün/hafta) ve A7'nin kopukluğu (§3.10: 18'in
13'ünde hiç oturum yok) net görünüyor: 5 oturumdan az olan 38 öğrencinin 32'si
A6 + A7.

> **Kusur K5 — düzensizlik ölçüsü A4'ü ayırmıyor.** Medyan `burstiness`:
> A1 2,34 · A2 2,17 · A3 2,15 · **A4 2,14** · A5 2,25 · A8 2,42. A4, okul
> medyanından ayırt edilemiyor. `BURSTINESS_FLAG = 3,0` eşiği 250 öğrencide
> yalnız **12** kişiyi işaretliyor ve bu 12 kişi arketipe göre dağılmıyor.
> Sebep: ölçünün **tanımı**. `burstiness = max(günlük stint) / ort(günlük
> stint)` gün-**arası** yığılmayı ölçüyor; A4'ün deseni ise "sınavdan önceki
> 48 saatte %70" — yani **olaya göre** yığılma. Modül sınav takvimini
> göremediği için `pre_exam_share = None` (veri kısıtı) ve `pre_deadline_share`
> hiçbir tetikleyiciye bağlı değil (tasarım kararı).

> **Kusur K5b — gece penceresi senaryonunkiyle örtüşmüyor.**
> `NIGHT_HOURS = (0, 1, 2)` (TR 00:00–03:00, `[M]` D17 ile hizalı). Senaryo
> arketip tablosunda gece payı **22:00–02:00** olarak tanımlı (A4 %47,
> A2 %28). İki pencere farklı olduğu için ölçülen `night_share` A4 **0,088** ↔
> A2 **0,076** — ayrım yok. Sebep: **eşik/pencere kalibrasyonu**. (İki pencere
> iki farklı belgeden geliyor; hangisinin doğru olduğu bu ölçümle
> belirlenemez, ama ikisinin **aynı** olmadığı belirlenebilir.)

> **Küçük bulgu.** Isı haritası gösterilebilen öğrenci **212 / 250**;
> §7.5 P7 **160–175** bekliyor. Pencere tanımı farklı (P7 bütün günlük, modül
> son 28 gün) olduğundan iki sayı doğrudan kıyaslanamaz, ama modül beklenenden
> **cömert** davranıyor.

### [6] `attention.py` dikkat listesi ↔ §7.5 P21–P26

**Ölçülen liste: 250 öğrencinin 193'ü.**

| Arketip | A1 | A2 | A3 | A4 | A5 | A6 | A7 | A8 |
|---|---|---|---|---|---|---|---|---|
| Listede | 9/30 | 53/70 | 27/35 | 30/32 | **20/25** | **22/22** | 18/18 | 14/18 |

| Tetikleyici | Ateşlediği öğrenci | Arketip dağılımı |
|---|---|---|
| `homework` | **192** | her arketipten |
| `mark_trend` | 21 | A6 ×18, A1/A3/A8 ×1 |
| `attendance` | 19 | A7 ×18, A6 ×1 |
| `exam_missed` | **0** | yapısal olarak imkânsız |

| # | Senaryo ölçütü | Beklenen | Ölçülen | Tuttu mu |
|---|---|---|---|---|
| P21 | Listedeki öğrenci | 32–48 | **193** | **HAYIR** |
| P22 | A6'dan listede | ≥ 18 / 22 | **22 / 22** | Evet |
| P23 | A5'ten listede | ≤ 2 / 25 | **20 / 25** | **HAYIR** |
| P24 | 4/4 tetikleyici | 12–18, hepsi A6 | **0** | Tanımsız (bkz. §0) |
| P25 | Yeni gelenden listede | 0 | **5 / 6** (`mid_term_join`) | **HAYIR** |
| P26 | Grip haftası kaynaklı uyarı | 0 | **0** | Evet |

> **Kusur K1 — ödev tetikleyicisi aşırı ateşliyor. Bu modüldeki tek ve en ağır
> kusur budur.** `MISSING_TRIGGER = 3` ("son 30 günde `missing >= 3`") bu
> veride 192 öğrencide ateşliyor. Sebep aritmetik: 30 günlük pencerede öğrenci
> başına **medyan 20 ödev** düşüyor ve okul geneli medyan eksik sayısı
> **4**'tür (çeyrekler: 3 / 4 / 6). Yani eşik okul medyanının **altında**
> kalıyor. `MODULLER.md` §2.8'in verdiği 3 sayısı, bu ödev yoğunluğundan çok
> daha seyrek bir okul için kalibre edilmiş. Sebep: **eşik kalibrasyonu**.
>
> Kanıt ki kusur tek bir eşikte, modülün bütününde değil: ödev maddesi
> çıkarıldığında listede **40 öğrenci** kalıyor (A6 ×19, A7 ×18, A1/A3/A8 ×1)
> — tam olarak P21'in beklediği **32–48** bandı ve P23'ün beklediği
> **A5'ten 0**.

> **Kusur K2 — seviye kuralı değişim kuralının yerini almış.** §2.8
> tetikleyici 2 iki koşulu **VEYA** ile bağlıyor: (a) `missing >= 3`,
> (b) zamanında teslim oranı %60'tan %50'nin altına düştü. (b) bir **değişim**
> kuralı ve A5'i doğru biçimde dışarıda bırakırdı; (a) bir **seviye** kuralı ve
> herkesi içeri alıyor. `VEYA` bağlacı yüzünden değişim kuralının koruyucu
> etkisi tamamen kayboluyor. §3.8'in "T4'ün kuralları *son 30 gün önceki 30
> günden kötü* der" cümlesi kodda yalnız yarı yarıya karşılanmış durumda.
> Sebep: **modül kusuru** (kural tasarımı), eşik değil.

> **Kusur K3'ün sonucu burada da görünüyor:** A6'da dört tetikleyiciden yalnız
> ikisi (ödev + not eğilimi) ateşleniyor; devamsızlık kümülatif orana takılıyor,
> `exam_missed` yok. En çok **2 farklı** tetikleyici taşıyan öğrenci: A6 ×19,
> A7 ×18.

> **P25 hakkında.** Soğuk başlangıç kapısı iki parçalı: küresel
> `COLD_START_WEEKS = 4` (dönem başından 10 hafta geçtiği için kapalı değil) ve
> öğrenci başına `MIN_HISTORY_ITEMS = 5` ödev geçmişi. Dönem ortasında katılan
> 6 öğrencinin 5'i 5 ödevlik geçmişi doldurduğu için kapıdan geçiyor. Kapı
> yanlış değil, **ödev tetikleyicisi onu anlamsızlaştıracak kadar duyarlı**
> (K1'in türevi).

**Yapısal kurallar gerçek veride de geçiyor:** 246 dikkat maddesinin hepsi
kanıt taşıyor, hiçbirinde "risk" kelimesi geçmiyor, `AttentionItem` üzerinde
`score`/`rank` alanı yok, sıralama alfabetik. `[T§6.6]` maddeleri sentetik
testte olduğu gibi gerçek veride de tutuyor.

### [7] Yetenek kestirimi ↔ `theta_base`

Modüllerin ürettiği başarı ölçüsü = öğrencinin ders ortalamalarının ortalaması
(`marks.student_course_stats()` → `average`, ağırlıklı).

| Küme | n | Pearson | Spearman |
|---|---|---|---|
| Tüm öğrenciler | 250 | 0,920 | **0,923** |
| Zaman içinde sabit arketipler (A5/A6 hariç) | 203 | 0,978 | **0,969** |
| Ortalama kohort-z ile (bant ölçüsü) | 245 | 0,920 | 0,931 |
| A1 | 30 | 0,927 | 0,920 |
| A2 | 70 | 0,950 | 0,929 |
| A3 | 35 | 0,941 | 0,920 |
| A4 | 32 | 0,965 | 0,940 |
| A5 | 25 | **0,056** | **0,104** |
| A6 | 22 | 0,615 | 0,842 |
| A7 | 18 | 0,906 | 0,897 |
| A8 | 18 | 0,944 | 0,915 |

A5'in sıfıra yakın korelasyonu bir kusur **değil**, beklenen sonuçtur:
`theta_base` A5'te `−0,70` civarı bir başlangıç değeri, `T_NOW` yeteneği ise
`+0,80` civarı. Ders ortalaması bugünün yeteneğini ölçüyor. Aynı sebeple
A6'da da korelasyon düşük. Bu iki satır **geçersiz ölçüm**dür (§0).

Arketip başına medyan ders ortalaması (100'lük): A1 **86,5** · A2 61,9 ·
A3 68,2 · A4 55,5 · A5 55,2 · A6 67,7 · A7 **41,6** · A8 58,8.

---

## 3. Bulunan kusurların listesi

İlk ölçüm turunda bulunan kusurlar. **Durum** kolonu ikinci turu (§5) gösterir.
Sıra önem sırasıdır.

| # | Modül | Kusur | Sebep türü | Etkisi | Durum |
|---|---|---|---|---|---|
| K1 | `attention.py` | `MISSING_TRIGGER = 3` bu ödev yoğunluğunda okul medyanının altında (medyan eksik 4 / 30 gün) | **eşik kalibrasyonu** | Liste 193/250; P21 ve P23 düşüyor | **GİDERİLDİ** (§5.1) |
| K2 | `attention.py` | Ödev tetikleyicisinde **seviye** kuralı (`missing ≥ 3`) **değişim** kuralıyla `VEYA` ile bağlı; değişim kuralının koruyucu etkisi yok oluyor | **modül kusuru (kural tasarımı)** | A5 yanlış pozitif 20/25 | **GİDERİLDİ** (§5.2) |
| K7 | `marks.py` | Öğrenci-**içi** ders kontrastı hiç hesaplanmıyor; yalnız kohort-dışı z var | **modül kusuru (eksik ürün)** | A3 (kataloğun en değerli ürünü) K = 0,056; aynı çıktıdan türetilince K = 1,00 | **GİDERİLDİ** (§5.4) |
| K3 | `attendance.py` | Devam yalnız dönem kümülatifi; iki pencere yok | **veri kısıtı** (modülde belgeli) | A6'nın %94→%73 çöküşü görünmüyor (1/22) | açık (veri kısıtı) |
| K4 | `submission.py` | `submitted_at` yok → erteleme profili yok; kalan ölçü A4'ü A7'den ayıramıyor | **veri kısıtı** (modülde belgeli) | A4 K = 0,62 | açık (veri kısıtı) |
| K5 | `study.py` | `burstiness` gün-arası yığılmayı ölçüyor; A4'ün deseni olay-öncesi yığılma. `BURSTINESS_FLAG = 3,0` 250'de 12 kişiyi buluyor | **ölçü tanımı + eşik** | A4 ayırt edilemiyor | **BELGELENDİ + bayrak kaldırıldı** (§5.5) |
| K5b | `study.py` | `NIGHT_HOURS = (0,1,2)`, senaryo gece penceresi 22:00–02:00 | **pencere kalibrasyonu** | `night_share` arketip ayırmıyor | **GİDERİLDİ** (pencere), ayrım gücü yok (§5.5) |
| K6 | `marks.py` | `course_trend()` `dropped` üretiyor, `rising` üretmiyor | **modül kusuru (eksik ürün)** | A5 ürünü tüketiciye bırakılmış | **GİDERİLDİ** (§5.3) |
| K8 | `attention.py` | `EXAM_MISSED` hiç ateşlenemiyor | **veri kısıtı** (modül `unavailable_triggers()` ile raporluyor) | P24 tanımsız | açık (veri kısıtı) |
| K9 | `study.py` | Isı haritası kapısı 212/250 açıyor, P7 160–175 bekliyor | **pencere farkı** (kıyas geçersiz) | bilgi amaçlı | açık (kıyas geçersiz) |

**Kusur bulunmayan yerler:** `attendance.py` kohort mantığı (K = 0,95,
kolektif olaydan bağışık), `study.countable()` (250/250), `marks.py` kohort
kurgusu (şube × ders, okul havuzu yok), `place_in_cohort()` güven kapıları,
`model.AttentionItem` yapısal kısıtları.

---

## 5. Düzeltme turu — ne yapıldı, sonra ne ölçüldü

İkinci turda K1, K2, K5, K5b, K6 ve K7 giderildi. **Düzeltmelerin hiçbiri
liste büyüklüğüne üst sınır koymuyor**: "en kötü N'i göster" bir sıralama
üretir ve `[T§6.6]` madde 2 sıralamayı yasaklar. Çözümün tamamı eşiğin
kendisinde.

### 5.0 Önce / sonra

| Ölçü | Önce | Sonra | Hedef |
|---|---|---|---|
| Dikkat listesi büyüklüğü | **193 / 250** | **46 / 250** | 32–48 (P21) ✔ |
| A5 (yükselen) yanlış pozitif | **20 / 25** | **0 / 25** | ≤ 2 (P23) ✔ |
| A6 (düşen) yakalanan | 22 / 22 | **21 / 22** | ≥ 18 (P22) ✔ |
| A3 konu boşluğu — kesinlik | 0,056 | **1,000** | — ✔ |
| A3 konu boşluğu — duyarlılık | 0,886 | **0,857** | — ✔ |
| `rising` sınıfı → A5 | *sınıf yok* | **K 0,79 · D 0,76** (24 tahminin 19'u A5) | — ✔ |
| P25 — dönem ortasında katılandan listede | 5 / 6 | **1 / 6** | 0 | kısmen |

Düzeltme sonrası liste dağılımı:

| Arketip | A1 | A2 | A3 | A4 | A5 | A6 | A7 | A8 |
|---|---|---|---|---|---|---|---|---|
| Listede | 1/30 | 3/70 | 2/35 | 1/32 | **0/25** | **21/22** | 17/18 | 1/18 |

| Tetikleyici | Ateşlediği öğrenci | Arketip dağılımı |
|---|---|---|
| `mark_trend` | 21 | A6 ×18, A1/A3/A8 ×1 |
| `homework` | 21 | A6 ×14, A2 ×3, A7 ×2, A3/A4 ×1 |
| `attendance` | 18 | A7 ×17, A6 ×1 |
| `exam_missed` | 0 | yapısal olarak imkânsız (K8, açık) |

74 dikkat maddesinin 48'i **değişim**, 26'sı **seviye** dayanaklı
(`evidence.rule_basis`). Önceki turda 246 maddenin 192'si tek bir seviye
kuralından geliyordu.

### 5.1 K1 — eşik mutlaktan kohort-göreliye

`submission.MISSING_TRIGGER = 3` artık **kullanılmıyor**. Yerine ölçü
`missing_rate_30d` (eksik / verilen ödev) ve referansı öğrencinin **kendi
şubesinin medyan eksik oranı**:

```
kronik yol:  missing_rate ≥ MISSING_COHORT_FACTOR × medyan(şube)
```

`MISSING_COHORT_FACTOR = 2,0` — "şubesinin iki katı". Gerekçe ölçülmüştür,
seçilmemiştir: çarpan 1,75 / 2,00 / 2,25 / 2,50 / 3,00 değerlerinin
**hepsinde** liste P21 bandının içinde (46, 46, 44, 44, 44) ve A5 yanlış
pozitifi 0. Düzlük geniş olduğu için eşiğin sonucu güzelleştirmek üzere
oynatılmasına gerek de imkân da yok. (1,5'te liste 57'ye çıkar; bant kenarı
orada.)

Şube medyanları bu okulda %15,8 – %31,6 arasında değişiyor — tek bir mutlak
sayının neden yanlış eksende olduğunun doğrudan kanıtı.

**Fail-closed.** Kohort `attention.submission_cohort_medians()` ile kurulur ve
`evaluate(..., submission_cohort=...)` ile verilir. Verilmezse ödev
tetikleyicisi **hiç ateşlemez**; mutlak eşiğe düşmek düzeltilen kusurun ta
kendisidir. Kohortsuz hâlde liste 39 kişi (yine P21 bandında), yalnız
devamsızlık + not eğiliminden.

### 5.2 K2 — `VEYA` yerine koruyucu `VE`

```
ateşler  ⇔  ¬iyileşiyor  ∧  ( kohort-göreli seviye  ∨  kötüleşme )
```

* **Koruyucu kapı.** `_is_improving()` — eksik oranı düştüyse **ya da**
  zamanında teslim oranı yükseldiyse ödev maddesi hiç üretilmez. Değişim
  kuralı artık ikinci bir suçlama yolu değil, birinci yolun önündeki filtre.
  Altın kümede 250 öğrencinin 175'i bu kapıdan korunuyor.
* **Kötüleşme yolu da kohort-göreli.** §2.8'in %60 → %50 altı kuralı
  korunuyor ama eksik oranın **en az şube medyanı kadar** olması da aranıyor:
  şubesinden hâlâ iyi durumdaki bir öğrenci kötüleşse de listelenmez. Bar
  burada 1,0× medyan (2,0× değil), çünkü kötüleşmenin kendisi ikinci kanıttır.
* **A5 koruması.** `_suppress_rising()`: madde sayısı **tam olarak 1**, o
  maddenin dayanağı **seviye**, ve öğrencinin not eğilimi yükseliyorsa
  (`is_rising()`) madde düşer. Koruma liste büyüklüğü için konmadı — A5 yanlış
  pozitifi bu kapı olmadan da 0; kapı onu **yapısal olarak** 0'da tutar. Altın
  kümede 2 öğrenciyi bastırıyor (1 A1, 1 A7); liste 48 → 46.

### 5.3 K6 — `rising` sınıfı

`course_trend()` artık `rising` üretiyor: son 3 notun ortalaması önceki 3'ten
**≥ 15 puan yüksek** (`MARK_RISE_POINTS`, `MARK_DROP_POINTS`'un simetriği)
**ve** `slope_per_30d ≥ 3,0` (`RISING_SLOPE_PER_30D`). İki koşul birlikte
aranır: sıçrama tek bir iyi sınavdan gelebilir, eğim süreklilik ister.

Eşik ölçümden gelir: öğrenci başına medyan `slope_per_30d` A5'te **+7,11**
(en düşüğü +3,73), diğer yedi arketipte **+0,16 … +0,98**, A6'da −5,94.
3,0 bu boşluğun ortasındadır.

`attention.is_rising()` ders düzeyini öğrenci düzeyine toplar: eğilimi
hesaplanabilen derslerin **çoğunluğu** `rising` **ve hiçbiri** `dropped`
olmayacak. "Herhangi bir dersi yükseliyor" çok gevşek (96 kişi, K 0,24);
çoğunluk kuralı 24 kişi bulur, 19'u A5 (**K 0,79 · D 0,76**).

### 5.4 K7 — öğrenci-içi ders kontrastı

`marks.within_student_contrast()` eklendi, çıktısı `student_profile()`
sözlüğünde `within_student_contrast` anahtarında. Ölçü: en düşük z'li ders −
diğer derslerin medyan z'si; `≤ −1,5` ise `flagged`.

Altın kümede: **30 tahmin, 30 doğru → kesinlik 1,00**, duyarlılık 0,857
(35 A3 öğrencisinin 30'u) ve 30'unun hepsinde **hangi ders** olduğu da doğru.

Ölçü `placement` sözlüğüne **konmadı**: bu bir ders özelliği değil,
öğrencinin ders kümesine ait bir ölçüdür. Konu (subject) düzeyi hâlâ
üretilmiyor ve iddia da edilmiyor — `MIN_COURSES_FOR_CONTRAST = 3` altında
ölçü kapalıdır.

### 5.5 K5 / K5b — çalışma ölçüleri

**K5b (giderildi):** `NIGHT_HOURS` artık `(22, 23, 0, 1)` — senaryonun
22:00–02:00 penceresi, yarı açık aralık. Çıktıya `night_window_tr` alanı
eklendi.
**Ama ayrım gücü yok ve iddia edilmiyor:** düzeltmeden sonra `night_share`
medyanı A4 **0,228** ↔ A2 **0,250**. Düzeltme tanım doğruluğu içindir.

**K5 (ölçülemiyor, belgelendi):** `bursty` bayrağı **kaldırıldı**.
`burstiness` gün-**arası** yığılmayı ölçüyor; A4'ün deseni ise olay-öncesi
yığılma. İki aday ölçünün ikisi de ayırmıyor:

| Ölçü | A4 | okul geneli |
|---|---|---|
| `burstiness` medyanı | 2,14 | 2,18 |
| `pre_deadline_share` medyanı | 0,714 | 0,700 |

Olay ekseni (`exam.starts_at`) `Source` arayüzünde olmadığı sürece "düzensiz
çalışıyor" ölçülemez. Sayı betimleyici olarak kalıyor, yanında ne ölçmediğini
söyleyen `burstiness_limitation` ile. Ölçemediğimiz şey bayrağa dönüşmez.

### 5.6 Düzeltilemeyenler

* **K3 / K4 / K8** — veri kısıtı; köprü izin listesi genişlemeden çözülemez
  (`course_session.starts_at`, `homework_submission.submitted_at`,
  `exam_attempt`).
* **K5** — yukarıdaki gerekçeyle ölçülemiyor; belgelendi, bayrak kaldırıldı.
* **P25 (0 hedefi)** — dönem ortasında katılan 6 öğrencinin 1'i hâlâ listede
  (önce 5). Kalan vaka ödev tetikleyicisinden değil, **not eğilimi**
  tetikleyicisinden geliyor; `MIN_HISTORY_ITEMS` ödev geçmişine bakıyor ama
  not geçmişine bakmıyor. Bu ayrı bir kapı sorunudur ve bu turun kapsamı
  dışında bırakıldı.
* **P24 (4/4 tetikleyici)** — K8 nedeniyle yapısal olarak tanımsız; hâlâ 0.

---

## 4. Yeniden üretme

```bash
# 1) Fikstürleri tohumdan üret (~2 dk, ek bağımlılık yok)
python tools/build_student_fixtures.py

# 2) İlk ölçüm (kusurları sabitleyen tur)
cd service && python -m unittest tests.test_compute_gold -v

# 3) Düzeltmenin gerileme koruması
cd service && python -m unittest tests.test_compute_attention -v
```

`tools/build_student_fixtures.py` tohum `.surql` dosyalarını doğrudan
ayrıştırır (SurrealDB konteyneri gerekmez) ve
`service/fixtures/gold_students/` altına `Source` arayüzünün tam biçiminde
yazar. `service/tests/test_compute_gold.py` içindeki eşikler dosyanın başında
`SENARYO_*` (senaryo §7'den birebir) ve `OLCULEN_*` (gerileme koruması) diye
ayrılmıştır; tutmayan senaryo ölçütleri `@unittest.expectedFailure` ile
işaretlidir, **değerleri düşürülmemiştir**.

`service/tests/test_compute_attention.py` aynı ayrımı düzeltme turu için
yapar: `SENARYO_*` senaryo ölçütleridir (P21/P22/P23), `OLCULEN_*` düzeltme
sonrası bir kez ölçülmüş değerlerdir. `test_liste_ust_sinirla_kirpilmiyor`
ayrıca listede hiçbir üst sınır/kırpma bulunmadığını sabitler: eşik
gevşetildiğinde liste bandı **taşabilmelidir**.

> ⚠️ `test_compute_gold.py` ilk ölçüm turunun fotoğrafıdır ve K1/K5b/K6
> kusurlarını **davranış olarak sabitler** (`OLCULEN_DIKKAT_TOPLAM = 193`,
> `NIGHT_HOURS == (0,1,2)`, `assertNotIn("rising", trend)`), ayrıca P21/P23'ü
> `@unittest.expectedFailure` ile işaretler. Düzeltmeden sonra bu beş iddia
> artık geçerli değildir; dosya bu turda **dokunulmaması istendiği için**
> güncellenmedi ve kendi sahibi tarafından güncellenmesi gerekir.
