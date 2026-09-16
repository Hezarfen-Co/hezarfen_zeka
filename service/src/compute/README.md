# `compute/` — hesap modülleri

Saf fonksiyonlar. Girdi veri, çıktı sonuç. **Yan etki yok, ağ yok, veritabanı yok.**

| Dosya | Ne yapar | Ana kaynak |
|---|---|---|
| `stat.py` | ortalama, medyan, σ, z, Wilson aralığı, regresyon eğimi | `MODULLER.md` §2.0 |
| `clock.py` | UTC ms ↔ TR (UTC+3) gün/saat/hafta, pencere sınırları | `MODULLER.md` §2.0 |
| `model.py` | paylaşılan çıktı tipleri; bant, güven, tetikleyici, tavsiye | `MODULLER.md` §2.0 |
| `marks.py` | ders ortalaması, kohorttaki konum (z + üç bant), dönem içi eğilim | `MODULLER.md` §2.3 |
| `attendance.py` | devam oranı, statü dağılımı, kohort medyanına göre göreli fark | `MODULLER.md` §2.5 |
| `submission.py` | teslim / geç / eksik sayımları, yaklaşan teslimler | `MODULLER.md` §2.4 |
| `study.py` | haftalık hacim, düzenlilik, ısı haritası, kendi geçmişiyle kıyas | `MODULLER.md` §2.6 |
| `attention.py` | dikkat listesi — dört tetikleyici, **tek skor yok, sıralama yok** | `MODULLER.md` §2.8 |
| `recommend.py` | kural motoru; kanıtsız tavsiye üretmez | `MODULLER.md` §2.10 |

---

## Veri sözleşmesi

Hesap modülleri veritabanını ve köprüyü **görmez**. Yalnız `Source` arayüzünün
döndürdüğü sözlükleri görür. Beklenen şekiller (backend'in `src/web/` altındaki
`Serialize` DTO'larından birebir; JSON anahtarları Rust alan adlarının aynısıdır,
hiçbirinde `serde(rename)` yok):

```
profile(school, user_id) -> dict | None          # ProfileResponse
  { id, username, display_name, role, bio, avatar,
    classes: [{id, name, grade}],                # ← kohort kimliği buradan
    courses: [{id, title, kind}],
    badges:  [{id, earned_at}],
    stats:   { pomodoro_*, homework_*, lessons_*, ... } }   # OKUNMAZ, bkz. aşağı

marks(school, user_id) -> list[dict]             # MarksReport.courses
  [ { course: CourseResponse{id, creator, teachers[], title, description,
                             kind, term, capacity},
      results: [{exam, title, kind, weight, mark, grade, graded_by}],
      average, average_grade } ]

attendance(school, user_id) -> list[dict]        # AttendanceReport.courses
  [ { course: CourseResponse,
      counts: {present, absent, late, excused, custom{}, total, rate} } ]

pomodoro(school, user_id) -> list[dict]          # PomodoroLog.items
  [ {id, user, started_at, finished_at, duration_ms, counted} ]

homework_report(school, user_id) -> dict | None  # Page<HomeworkReportEntry>
  { items: [{course, homework, title, subject, due_at,
             submitted, late, missing,
             result: {status, mark, graded_by, created_at} | null}],
    total, limit, offset }

homework_list(school, on_behalf_of) -> list[dict]  # Page<HomeworkResponse>.items
  [ {id, course, subject, title, description, due_at,
     assigned, created_by, created_at} ]

notes(school, on_behalf_of) -> list[dict]        # [{id, title, content}]
course_notes(school, course_id) -> list[dict]    # [{id, course, title, content}]
```

Tüm zaman damgaları **unix milisaniye, UTC** (`[S]` `time_and_value_formats`).

Her modül girdiyi tek bir `normalize_rows` / `normalize_items` fonksiyonundan
geçirir; köprü listeyi bir zarf (`{"items": …}` / `{"courses": …}`) içinde
verirse de çalışır. Şekil tahmini **yalnız** o fonksiyonlarda yapılır.

### Bilerek kullanılmayan girdiler

* **`notes()` ve `course_notes()` — hiçbir hesap modülü bunları okumaz.**
  Serbest metin motora girmez (`[T§1.1]` 🟡 kuralı). Not içeriği öğrencinin
  kendi yazdığı metindir; ondan çıkarım yapmak mevcut erişim modelini
  genişletir.
* **`profile().stats` sayaçları — okunmaz.** `[T§1.3]` kural 3: ham kaydı oku,
  sayacı yalnız rozet göstermek için kullan. Gerekçe veriyle sabit: `[M]` K1
  tohumda **230 kullanıcıda kasıtlı sayaç şişmesi**, K2/K3 ise
  `lessons_attended_total` ve `high_mark_total`'ın **250 öğrencinin tamamında
  NONE** olduğunu söylüyor.

### Yapısal olarak erişilemeyen veri

`Source` arayüzünde **yemek, ödeme, diyet, mesai, mesaj ve sohbet verisi
yoktur ve olmayacaktır** (`[T§6.5]` Kapı 1). Bu bir yorum değil, yapısal
kapıdır: fonksiyon yoksa çağrılamaz. İkincil savunma
`tests/test_guard.py`'dir — `compute/` altındaki tüm kaynağı tarar ve yasaklı
tablo/alan adlarından biri geçiyorsa test düşer (`[T§6.5]` Kapı 2,
`tests/telemetry.rs` deseninin Python karşılığı).

---

## Eşikler ve kaynakları

| Eşik | Değer | Nerede | Kaynak |
|---|---|---|---|
| Bant için asgari not | 3 | `marks.MIN_MARKS_FOR_BAND` | **ürün kararı** `(doğrulanmadı)` — gerekçe kodda |
| Eğilim için asgari not | 6 | `marks.MIN_MARKS_FOR_TREND` | `MODULLER.md` §2.8 tetikleyici 3 (3+3) |
| Kohort büyüklüğü | 8 | `marks.COHORT_MIN`, `attendance.COHORT_MIN` | `MODULLER.md` §2.3 güven kapısı |
| Bant sınırı | \|z\| = 0,8 | `marks.BAND_Z` | `MODULLER.md` §2.3 adım 4, `[T§3 Ö1]` |
| σ tabanı | 0,05 | `stat.SD_FLOOR` | `MODULLER.md` §2.0 (mühendislik kararı) |
| Not düşüşü | 15 puan | `marks.MARK_DROP_POINTS` | `MODULLER.md` §2.8 tetikleyici 3 |
| Devam gözlemi | 10 | `attendance.MIN_OBS` | `MODULLER.md` §2.5 güven kapısı |
| Devam tetikleyicisi | oran < 0,80 **ve** göreli fark ≤ −0,10 | `attendance.*` | `MODULLER.md` §2.8 tetikleyici 1 |
| Teslim gözlemi | 5 | `submission.MIN_OBSERVATIONS` | `MODULLER.md` §2.4 güven kapısı |
| Eksik ödev (dikkat listesi) | şube medyanının **2,0 katı** — mutlak sayı YOK | `attention.MISSING_COHORT_FACTOR` | ölçüldü: `HESAP-DOGRULAMA.md` §5.1 (kusur K1) |
| Eksik ödev kohort kapısı | 8 kişi | `attention.COHORT_MIN` | `[L-6]`; altında ateşlemez |
| Zamanında oran düşüşü | %60 → %50 | `submission.ON_TIME_*` | `MODULLER.md` §2.8 tetikleyici 2 |
| Isı haritası | 5 oturum | `study.MIN_STINTS_FOR_HEATMAP` | `MODULLER.md` §2.6 güven kapısı |
| Düzenlilik | 3 aktif gün | `study.MIN_ACTIVE_DAYS` | `MODULLER.md` §2.6 güven kapısı |
| Yığılma bayrağı | **kaldırıldı** | — | ölçülemiyor: `HESAP-DOGRULAMA.md` §5.5 (kusur K5) |
| Gece penceresi | 22:00–02:00 | `study.NIGHT_HOURS` | `SENARYO.md` arketip tablosu (kusur K5b) |
| Yükselen not eğilimi | eğim ≥ 3,0 puan/30 gün **ve** +15 puan | `marks.RISING_SLOPE_PER_30D`, `marks.MARK_RISE_POINTS` | ölçüldü: `HESAP-DOGRULAMA.md` §5.3 (kusur K6) |
| Öğrenci-içi ders kontrastı | ≤ −1,5 z | `marks.WITHIN_STUDENT_CONTRAST` | ölçüldü: `HESAP-DOGRULAMA.md` §5.4 (kusur K7) |
| Dikkat listesi ömrü | 30 gün | `attention.EXPIRY_DAYS` | `[T§6.6]` madde 5 |
| Soğuk başlangıç | 4 hafta | `attention.COLD_START_WEEKS` | `[T§3 T4]` |
| Segment başına asgari cevap | 100 | `segments.MIN_ANSWERS_PER_SEGMENT` | ölçüldü: `SEGMENT-CIKTI.md` §2.2 (kapı taraması) |
| Göreli kontrast kapısı | −0,080 / −0,032 / −0,060 | `segments.RELATIVE_CONTRAST_GATE` | ölçüldü: `SEGMENT-CIKTI.md` §2.1 (kontrol ort. − 2·SD) |
| Sınıf segment kapısı | −0,040 | `segments.CLASS_RELATIVE_CONTRAST_GATE` | ölçüldü: `SEGMENT-CIKTI.md` §5 (şube-arası ort. − 3·SD) |
| Sınıf segment kohortu | 8 kişi | `segments.MIN_CLASS_STUDENTS` | `[L-6]` — `marks.COHORT_MIN` ile aynı |

`MODULLER.md` §0 kural 1 gereği **hiçbir modülde eğitilmiş model yoktur.**
`[L-1]`: bizim profilimizde lojistik regresyon/PFA hattı DKT ve SAKT'ı geçiyor
— ama o kazanımlar **kazanım (KC) etiketli** girdide üretildi, bizde kazanım
kodu yok. `[L-3]`: vanilla DKT çıktısı panele yapısal olarak basılamaz.
Bu ölçekte kural ve klasik istatistik yeterlidir.

---

## `segments.py` — segment profili (bu sürümde eklendi)

`service/src/segment/` hattının ürettiği soru etiketleri × ham cevaplar →
öğrenci × boyut × etiket performansı. Diğer modüllerden **tek farkı** girdisinin
`Source`'tan değil, segmentasyon hattından gelmesidir; modülün kendisi yine saf
fonksiyonlardır (ağ yok, veritabanı yok, dosya yok).

Üç ölçü üretir ve üçü farklı şey söyler — ayrıntısı modülün baş yorumunda:
`accuracy` (**ayrım gücü yok**), `contrast` (öğrencinin genel düzeyi sadeleşir,
depoya yazılan ölçü), `relative_contrast` (madde zorluğu da sadeleşir, **kural
eşiklerinin baktığı ölçü**). Kurallar ham doğruluk üzerinden **asla** ateşlemez.

Bu modül `segment/rubric.py`'yi **içe aktarmaz** (paket bağımsızlığı); boyut
kümesi burada ayrıca tanımlıdır ve iki tarafın sapması
`tests/test_segments.py::TestRubricUyumu` ile testte yakalanır.

Ölçülmüş performans ve sınırlar: `docs/SEGMENT-CIKTI.md`.

---

## Bu sürümde YAPILAMAYANLAR

Her madde bir **veri kısıtıdır**, bir eksiklik değil. Sahte uygulama
yazılmadı; her birinin yerine ne gerektiği yazıldı.

### 1. Madde analizi (`item_stats`) — **tamamen yapılamıyor**

`MODULLER.md` §2.2 bu modülü p-değeri, ayırt edicilik (`D`), nokta-çift serili
korelasyon, çeldirici dağılımı ve cevap anahtarı dondurma üzerine kuruyor.
Hepsi tek bir girdiye dayanır: **ham sınav cevabı** (`exam_answer.selected`) ve
soru künyesi (`exam_question.correct`, `choices[*].id`).

Köprü izin listesinde **sınav yolu bulunmuyor**; `Source` arayüzünde
`answers_for_exam`, `questions_for_exam`, `results_for_exam`, `attempts_for_exam`
karşılıkları **yok**. Dolayısıyla:

* `p-değeri` — hesaplanamaz
* `ayırt edicilik (D = p_üst27 − p_alt27)` — hesaplanamaz
* `nokta-çift serili korelasyon (r_pb)` — hesaplanamaz
* `çeldirici dağılımı` ve "çeldirici doğru cevaptan fazla seçildi" bayrağı — hesaplanamaz
* `boş bırakma oranı` — hesaplanamaz (`exam_attempt` paydası yok)
* `cevap anahtarı dondurma` — anlamsız (anahtar görülmüyor)
* `from_bank / banked_as` çapraz-sınav birleştirmesi — hesaplanamaz

**Sonuç olarak üretilemeyen ürünler:** T1 (Sınıfın Takıldığı Soru), T2 (Soru
Kalitesi Karnesi), Ö2 (Sınav Sonrası Tekrar Listesi) ve `question_stat` tablosu.

**Gereken:** köprü izin listesine sınav okuma yollarının eklenmesi
(`exam_answer`, `exam_question`, `exam_result`, `exam_attempt`) — ya da bu
hesabın backend içinde, `MODULLER.md`'nin tarif ettiği Rust modülü olarak
yapılması. Eklenirse `[L-5]` (Linacre 1994) iki kademeli kapısı da gelmelidir:
`n ∈ [30,100)` → "ön bulgu", `n ≥ 100` → "kararlı"; ve `D` hiçbir koşulda
otomatik bir eyleme bağlanmaz (`[L-5]` şerh (a): 2PL ayırt ediciliği için
500–1000+ örneklem gerekir, 250 ile güvenilir değildir).

### 2. Konu (`subject`) kırılımı — yapılamıyor

`MODULLER.md` §2.3'ün tamamı öğrenci × konu doğruluk oranı üzerine kurulu.
Konu bağı yalnız `exam_question.subject` üzerinden var; ham soru verisi yok.
**Yerine:** ders (`course`) düzeyinde not ortalaması ve aynı bant mantığı.
Ö1 bu haliyle üretiliyor ama "hangi konuda" sorusuna cevap veremiyor.

### 3. Devam: haftanın günü deseni ve iki pencere eğilimi — yapılamıyor

`GET /attendance/{user}` **yalnız sayaç** döndürüyor
(`present/absent/late/excused/custom/total/rate`); satır, oturum kimliği ve
tarih yok. Satır düzeyindeki `SessionAttendanceResponse` bile zaman damgası
taşımıyor — `[S]` `session_attendance.fields` = `session, course, user, status,
marked_by`, kayıt anahtarı kompozit.
**Sonuç:** `MODULLER.md` §2.5 adım 2–5 (iki pencere, `delta`, kohort delta
medyanı, haftagünü deseni) kurulamıyor. Göreli ölçü **seviye farkı** olarak
korunuyor; **düşüş farkı** olarak değil. Bu, tetikleyiciyi zayıflatır: sürekli
düşük devamlı öğrenci ile **yeni düşen** öğrenci ayırt edilemez.
**Gereken:** `course_session.starts_at` ile ilişkilendirilmiş, satır düzeyinde
devam verisi.

### 4. Erteleme profili — yapılamıyor

`HomeworkReportEntry` `submitted_at` taşımıyor. `MODULLER.md` §2.4 adım 2–3'ün
tamamı (`median_lead`, "son dakika" profili, son 24 saate yığılma oranı,
dinamik `remind_at`) buna dayanıyor. **Yerine:** sabit 24 saat hatırlatma —
belgenin kendi "kapı-altı" davranışı.
**Gereken:** `homework_submission.submitted_at` (ve tercihen dondurulmuş
`counted_on_time`).

### 5. `counted_on_time` yok → geç teslim ölçüsü yanlı

Rapor `late` alanını veriyor: "teslim **en son** `due_at` sonrasında
dokunuldu mu". `MODULLER.md` §2.4 adım 1 bunun **yanlış alan** olduğunu açıkça
söylüyor ve tohumda **1.025 satırın** (`[M]` D14) bu yüzden yanlış tarafa
düştüğünü ölçüyor. Modül sayıyı üretiyor ama adı
(`on_time_rate_by_last_touch`) ve `counted_on_time_available = False` bayrağı
bunu taşıyor. `[N§7.5]` A11/A12 doğrulamaları bu bayrak açıkken geçersizdir.

### 6. Sınav öncesi yığılma — yapılamıyor

Sınav takvimi (`exam.starts_at`) `Source`'ta yok. **Yerine:** ödev teslim
tarihi öncesi yığılma (`study.pre_deadline_share`) — ayrı bir ölçüdür, adı
bunu söyler, hiçbir tetikleyiciye bağlanmaz.

### 7. Dikkat listesi 4. tetikleyicisi (sınav kaçırma) — hiç ateşlenemez

`exam_attempt` ve sınav penceresi yok. `attention.unavailable_triggers()` bunu
çıktıyla birlikte taşır; **yarım liste sessizce gösterilmez** —
eksik listeden "bu öğrenci iyi durumda" çıkarımı yanlış negatiftir.

### 8. Veli haftalık özeti (V1) — üretilemiyor

`parent_link` `Source`'ta yok; velinin kim olduğu çözülemiyor. Ayrıca haftalık
pencere için devam verisinde tarih yok (bkz. 3).

### 9. Ölçme kalitesi panosu (Y1) ve yardım arama (T5) — üretilemiyor

Y1: `subject.exam_question_count` / `homework_count` sayaçları, sınav listesi
ve `class_blueprint` yok.
T5: randevu, havuz sorusu ve çözüm verisi yok. Sohbet sinyali (T5-c) ise zaten
`[T§3 T5]` gereği varsayılan kapalı ve `[T§6.8]` gereği yalnız sayı taşıyabilir;
bu arayüzde hiç yok — ve **istenmiyor**.

---

## Üretilebilen ürünler (v1)

| Ürün | Durum | Not |
|---|---|---|
| **Ö1** Konu Karnesi | ✅ kısmi | ders düzeyinde; konu kırılımı yok |
| **Ö3** Çalışma Düzeni Aynası | ✅ | ders bağı yok (yapısal), sınav öncesi yığılma yok |
| **Ö4** Teslim Takvimi | ✅ kısmi | yaklaşan teslim + eksik sayımı; erteleme profili yok |
| **T3** Sınıf Isı Haritası | ✅ kısmi | ders × şube hücresi; konu ekseni yok |
| **T4** Dikkat Listesi | ✅ kısmi | 4 tetikleyiciden **3'ü**; sınav kaçırma yok |
| **Ö2** Bilişsel segment kartı | ✅ kısmi | `O2.segment_cognitive_gap`, `O2.segment_trap_prone` — segmentasyon hattı koştuysa. Madde bazlı tekrar listesi (`O2.retry_item`) hâlâ yok |
| Ö5, T1, T2, T5, V1, Y1 | ❌ | bkz. yukarıdaki kısıtlar |

`Ö2`'nin ölçülmüş isabeti `docs/SEGMENT-CIKTI.md` §4'tedir ve **boyuta göre
değişir**: bilişsel talep ve dikkat tuzağı ekseninde kullanılabilir, okuma yükü
ekseninde **kullanılabilir değildir** (duyarlılık 0,22).
