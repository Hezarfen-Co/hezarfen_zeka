# SENARYO — Hezarfen 250 Öğrencilik Tohum Verisi (Seed Data) Tasarımı

**Belge türü:** Kod üreticisine doğrudan girdi olacak *spesifikasyon*. Her dağılım için tip
ve parametre, her hacim için kesin sayı verilmiştir. Belirsiz bırakılan hiçbir değer yoktur;
bir değer "üreticinin kararı" ise açıkça öyle yazılmıştır.

**Kaynak belgeler:** `_analiz_raporlari/20_tavsiye_sistemi_tasarim.md` (§1 sinyal envanteri,
§3 ürün kataloğu), `01_backend.md` (§4 uçlar, §5 veri modeli), `30_literatur_arastirma.md`
(madde kalibrasyonu örneklem eşikleri).

**Tasarım hedefi:** Üretilen veri, §3'teki **12 tavsiye ürününün (Ö1–Ö5, T1–T5, V1, Y1)
tamamını** besleyecek sinyali taşımalıdır. Her arketip ve her kenar durumu, en az bir ürünün
davranışını test etmek üzere tasarlanmıştır; §3.2'deki eşleme tablosu bunu izlenebilir kılar.

**Şema uyumu:** Tüm tablo ve alan adları `hezarfen_backend-main/src/migration_sql.rs`
tanımlarına birebir uyar. Zaman damgaları **milisaniye cinsinden `int`** (Unix epoch, UTC);
kodda hiçbir yerde `datetime` tipi kullanılmaz. Kayıt id'leri sıralama gerektiren tablolarda
**monotonik ULID**'dir (`exam_attempt`, `chatbot_message`, `board_stroke`, `note`,
`pomodoro_session`, `message`, `pool_question`, `solution`, ledger'lar).

---

## İçindekiler

1. [Okul yapısı](#1-okul-yapısı)
2. [Takvim ve hacim](#2-takvim-ve-hacim)
3. [Öğrenci arketipleri](#3-öğrenci-arketipleri)
4. [Madde (soru) modeli](#4-madde-soru-modeli)
5. [Diğer gerçekçilik kuralları](#5-diğer-gerçekçilik-kuralları)
6. [Kenar durumlar](#6-kenar-durumlar)
7. [Doğrulanabilirlik — beklenen değerler](#7-doğrulanabilirlik--beklenen-değerler)

---

## 0. Üretici sözleşmesi (okumadan başlama)

| Parametre | Değer | Not |
|---|---|---|
| `SEED` | `20260912` | Tüm RNG'ler bu tohumdan türetilir (`SEED + tablo_indeksi` ile alt akış) |
| `SCHOOL_SLUG` | `ataturk-anadolu` | Control DB'de `school:ataturk-anadolu` |
| `SCHOOL_NAME` | `Özel Hezarfen Anadolu Lisesi` | |
| `TZ` | `Europe/Istanbul` (UTC+3, DST yok) | **Depolama UTC ms; üretimde yerel saatten UTC'ye çevir** |
| `T_NOW` | `2026-04-13T08:00:00+03:00` = `1776056400000` ms | Verinin "şimdi" imleci |
| `DATE_SHIFT_DAYS` | `0` (varsayılan) | `152` verilirse tüm damgalar +152 gün kayar ve `T_NOW` → `2026-09-12` olur |
| Para birimi | `*_minor` alanları **kuruş** (TRY ×100) | |
| Dil / tema varsayılanı | `tr` / `system` | |

### 0.1 Tarih çelişkisi ve nasıl çözüldüğü (ÖNEMLİ)

Görev iki koşul veriyor: **(a)** bugün `2026-09-12`, **(b)** Türkiye eğitim takvimi (güz
eylül–ocak, bahar şubat–haziran) ve ikinci dönemin ortasındayız. Bu ikisi **aynı anda
sağlanamaz**: 12 Eylül, Türk eğitim takviminde bahar döneminin ortası değil, güz döneminin
ilk haftasıdır.

**Çözüm:** Kanonik veri, gerçek Türk takvimine sadık kurulur ve **veri içi "şimdi" imleci
`T_NOW = 2026-04-13`** olur — bu tarih, bahar döneminin *tam ortasıdır* (10 hafta geçmiş,
9,6 hafta kalmış = "1 dönem + 2 ay çalışıldı, bitmesine 2 ay var" koşulunun birebir
karşılığı). `2026-09-12` **belgenin/üretimin yazım tarihidir**, verinin tarihi değil.

Uygulamayı gerçek duvar saatiyle `2026-09-12`'de çalıştırıp "yaklaşan teslimler" görmek
isteyen için tek düğme bırakılmıştır: `DATE_SHIFT_DAYS = 152`. Bu değer **tüm** `int` zaman
damgalarına sabit olarak eklenir. 152 gün 7'nin katı olmadığı için haftanın günü deseni
kayar (Pazartesi→Cumartesi); devamsızlığın gün deseni (§5.1) bozulmasın isteniyorsa
`DATE_SHIFT_DAYS = 154` (= 22 tam hafta) kullanılmalı, bu durumda `T_NOW → 2026-09-14 Pzt`.
**Varsayılan `0`'dır ve öneri budur.**

---

## 1. Okul yapısı

### 1.1 Sınıf seviyeleri ve şubeler — toplam tam 250 öğrenci

Tek bir Anadolu lisesi (9–12). **Neden ortaokul yok:** 250 öğrenciyi 8 seviyeye yaymak,
şube başına 10–14 öğrenci demektir; bu, madde analizinin (T1/T2) ve ısı haritasının (T3)
istatistiksel olarak anlamsızlaşacağı bir örneklemdir. Literatür (`30_…` Bulgu 5, Linacre
1994) madde kalibrasyonu için ±1 logit/%95 bandında **≥30 gözlem** istiyor; T2'nin kendi
güven kapısı da `n ≥ 30`. 4 seviyede yoğunlaştırma, sınav başına 47–70 cevaplayıcı üretir.

| Seviye | `class_group.grade` | Şubeler | Öğrenci sayısı | Seviye toplamı |
|---|---|---|---|---|
| 9 | `"9"` | 9-A, 9-B, 9-C | 24, 23, 23 | **70** |
| 10 | `"10"` | 10-A, 10-B, 10-C | 23, 23, 22 | **68** |
| 11 | `"11"` | 11-A, 11-B, 11-C | 22, 22, 21 | **65** |
| 12 | 12-A → `"12. Sınıf"`, 12-B → `"12"` | 12-A, 12-B | 24, 23 | **47** |
| | | **11 şube** | | **250** |

12-A'nın `grade` değeri **kasten** `"12. Sınıf"` yazılır. Bu, sinyal envanterindeki L23
tutarsızlığının (`domain/class_group.rs:65-66`) canlı örneğidir ve Y1 panosunun
"sınıf seviyesi tutarlılığı" uyarısını tetikler. 12-A bu yüzden `class_blueprint`'ten
beslenmez; dersleri elle bağlanır (`class_course.source = NONE`).

`class_blueprint`: 4 satır, id = `9`, `10`, `11`, `12`. 12-B bu blueprint'i kullanır
(`class_course.source = class_blueprint:12`), 12-A kullanamaz.

### 1.2 Kullanıcılar ve roller

| Rol | Sayı | Not |
|---|---|---|
| `admin` | 1 | kullanıcı adı `yonetici` |
| `manager` | 3 | 1 müdür + 2 müdür yardımcısı |
| `teacher` | 24 | 23 branş + 1 rehber öğretmen (dersi yok, yalnız randevu açar) |
| `student` | 250 | |
| `parent` | 285 | |
| **`user` toplam** | **563** | |

**Veli–öğrenci bağı (`parent_link`, 299 satır) — kesin üretim kuralı:**

```
veli_kullanıcı  = 285
bağ dağılımı    = { 1 öğrenciye bağlı: 273 veli, 2 öğrenciye bağlı (kardeş): 12 veli }
                → 273 + 24 = 297 bağ
kalan 2 bağ     = 2 öğrenciye ikinci bir veli (vasi) eklenir       → 299 bağ
bağlı öğrenci   = 230   (250 − 20 velisiz)
iki velisi olan = 69 öğrenci  (yukarıdaki dağılımın ürettiği çakışma)
velisi olmayan  = 20 öğrenci  (kenar durum #6)
```

### 1.3 Türkçe isim havuzu (üretici bunu kullanır)

**Erkek adı (40):** Ahmet, Mehmet, Mustafa, Ali, Hüseyin, Hasan, İbrahim, Osman, Yusuf, Murat,
Emre, Burak, Kerem, Eymen, Çınar, Arda, Deniz, Efe, Kaan, Mert, Poyraz, Alp, Ömer, Halil,
Ramazan, Selim, Barış, Onur, Serkan, Tolga, Umut, Volkan, Yiğit, Berk, Cem, Doruk, Ege,
Furkan, Görkem, Levent

**Kadın adı (40):** Ayşe, Fatma, Emine, Hatice, Zeynep, Elif, Meryem, Şerife, Zehra, Sultan,
Hanife, Merve, Esra, Büşra, Rabia, Aleyna, Nisanur, Ecrin, Defne, Azra, Asya, Duru, İrem,
Selin, Ceren, Damla, Ebru, Gamze, Hande, Işıl, Jale, Kübra, Lale, Melis, Nehir, Özge,
Pınar, Seda, Tuğçe, Yasemin

**Soyadı (50):** Yılmaz, Kaya, Demir, Şahin, Çelik, Yıldız, Yıldırım, Öztürk, Aydın, Özdemir,
Arslan, Doğan, Kılıç, Aslan, Çetin, Kara, Koç, Kurt, Özkan, Şimşek, Polat, Korkmaz, Çakır,
Erdoğan, Güneş, Aksoy, Bulut, Turan, Avcı, Bozkurt, Kaplan, Tekin, Sarı, Duman, Ateş, Taş,
Güler, Uçar, Keskin, Yalçın, Balcı, Ergin, Soydan, Karaca, Aktaş, Başaran, Çakmak, Demirci,
Erdem, Sezer

**Kullanıcı adı üretimi:** `ad.soyad` → Türkçe harfler ASCII'ye indirgenir (`ç→c, ğ→g, ı→i,
ö→o, ş→s, ü→u`), küçük harf, boşluk yok. Çakışma olursa sonuna `2`, `3`… eklenir.
Örnek: `Ayşe Öztürk → ayse.ozturk`. Öğrenci parolası tekdüze `Ogrenci2026!`, öğretmen
`Ogretmen2026!`, veli `Veli2026!`, yönetici `Yonetici2026!` (yalnız yerel/test ortamı).

`user` profil doluluğu (gerçekçi eksiklik): `name`/`surname` %100, `email` %86,
`phone` %71, `birth_date` %63, `display_name` %28, `bio` %19, `avatar_file` %34,
`palette_color` %41, `theme` %52 (`light` %58 / `dark` %42), `language` %96 = `tr`.

### 1.4 Dersler ve konular

**Kritik modelleme kararı:** Bir `course` = **(seviye × ders)**, o seviyenin *tüm* şubelerine
`class_course` ile bağlanır. Yani "9. Sınıf Matematik" tek bir `course`'tur, `enrollment_count
= 70`'tir ve 9-A/9-B/9-C'nin üç şubesini birden kapsar (`enrollment.source` şubeyi tutar).

- **Neden böyle:** sınav (`exam`) bir `course`'a bağlıdır. Şube başına ders açılsaydı her
  sınavın örneklemi ~23 olurdu; T2'nin `n ≥ 30` kapısı **hiç açılmazdı** ve T1'in çeldirici
  yüzdeleri gürültü olurdu. Bu kurulumla her sınav 47–70 cevaplayıcı görür.
- **Yoklama nasıl şube düzeyinde kalıyor:** `course_session` satırının `topic` alanı
  `"9-A · Fonksiyonlar"` biçiminde şube etiketi taşır ve `session_attendance` **yalnız o
  şubenin öğrencileri için** yazılır. Şema bunu serbest bırakır (oturuma kayıtlı tüm
  öğrencilerin satırı olması zorunlu değildir). Böylece T3 ısı haritası hem ders (sınav)
  hem şube (yoklama) kırılımını alabilir.

**Ders listesi (her seviyede 10 ders = 40 `course` + 10 ek = 50 `course`):**

| Ders (`course.title` öneki: `"9. Sınıf "`, `"10. Sınıf "`, …) | 9 | 10 | 11 | 12 | Haftalık blok/şube | Konu (`subject`) |
|---|---|---|---|---|---|---|
| Matematik | ✓ | ✓ | ✓ | ✓ | 3 | 10 |
| Türk Dili ve Edebiyatı | ✓ | ✓ | ✓ | ✓ | 2 | 10 |
| Fizik | ✓ | ✓ | ✓ | ✓ | 1 | 10 |
| Kimya | ✓ | ✓ | ✓ | ✓ | 1 | 10 |
| Biyoloji | ✓ | ✓ | ✓ | ✓ | 1 | 10 |
| Tarih (12'de: T.C. İnkılap Tarihi ve Atatürkçülük) | ✓ | ✓ | ✓ | ✓ | 1 | 10 |
| Coğrafya | ✓ | ✓ | ✓ | ✓ | 1 | 10 |
| İngilizce | ✓ | ✓ | ✓ | ✓ | 2 | 10 |
| Din Kültürü ve Ahlak Bilgisi | ✓ | ✓ | ✓ | ✓ | 1 | 5 |
| Beden Eğitimi ve Spor | ✓ | ✓ | ✓ | ✓ | 1 | 5 |
| **Toplam** | | | | | **14 blok** | **90 / seviye** |

**Ek dersler (`course.kind`):**

| `kind` | Başlık | Sayı | Kayıtlı öğrenci | `subject` |
|---|---|---|---|---|
| `study` | TYT Matematik Etüdü, AYT Fizik Etüdü, İngilizce Konuşma Etüdü, Edebiyat Etüdü | 4 | 32, 28, 30, 30 | 3 her biri |
| `club` | Satranç, Robotik, Münazara, Fotoğrafçılık, Tiyatro, Bilim Kulübü | 6 | 18, 22, 16, 20, 24, 18 | 3 her biri |

**`subject` toplamı:** `4 seviye × 90 = 360` + `10 ek ders × 3 = 30` = **390**.

**Konu adları (müfredata yakın — üretici tam listeyi bu desende üretir):**

- *9. Sınıf Matematik:* Kümeler · Denklem ve Eşitsizlikler · Üslü ve Köklü İfadeler ·
  Mutlak Değer · Sayı Kümeleri · Üçgenler · Veri Analizi · Fonksiyon Kavramı ·
  Olasılık · Doğrunun Analitik İncelenmesi
- *10. Sınıf Matematik:* Sayma ve Olasılık · Fonksiyonlarla İşlemler · Polinomlar ·
  İkinci Dereceden Denklemler · Dörtgenler ve Çokgenler · Çemberin Analitik İncelenmesi ·
  Katı Cisimler · Veri Analizi · Basit Olayların Olasılığı · Trigonometriye Giriş
- *11. Sınıf Matematik:* Trigonometri · Analitik Geometri · Fonksiyonlarda Uygulamalar ·
  Denklem ve Eşitsizlik Sistemleri · Çember ve Daire · Uzay Geometri · Olasılık ·
  Diziler · Limit Kavramına Giriş · İstatistik
- *11. Sınıf Fizik:* Vektörler · Bağıl Hareket · Newton'ın Hareket Yasaları ·
  Tork ve Denge · Basit Makineler · İş Güç Enerji · Atışlar · Enerji Dönüşümleri ·
  Elektriksel Kuvvet ve Alan · Manyetizma
- *10. Sınıf Biyoloji:* Hücre Bölünmeleri (Mitoz) · Mayoz ve Eşeyli Üreme · Kalıtım ·
  Modern Genetik Uygulamaları · Ekosistem Ekolojisi · Madde Döngüleri · Bitki Biyolojisi ·
  Canlılar ve Enerji · Fotosentez · Solunum
- *9. Sınıf Türk Dili ve Edebiyatı:* Giriş (Edebiyatın Tanımı) · Hikâye · Şiir · Masal/Fabl ·
  Roman · Tiyatro · Biyografi ve Otobiyografi · Mektup/E-posta · Günlük ·
  Yazım Kuralları ve Noktalama
- *12. Sınıf Coğrafya:* Ekonomik Faaliyetler · Türkiye'de Tarım · Türkiye'de Sanayi ·
  Ulaşım Sistemleri · Türkiye'nin İşlevsel Bölgeleri · Küresel Ticaret ·
  Doğal Kaynak Yönetimi · Çevre Sorunları · Bölgesel Kalkınma Projeleri · Jeopolitik Konum

Kalan 33 dersin konu listesi aynı desende (MEB konu başlıklarına yakın, seviyeye uygun)
üretilir; `subject.description` 1–2 cümlelik Türkçe açıklama (%78 dolu, %22 boş string).

### 1.5 Öğretmen yükü ve ders eşlemesi

| Branş | Öğretmen | `course` (seviye) | Öğretmen başına şube (aynı ders) | Haftalık blok |
|---|---|---|---|---|
| Matematik | 4 | 4 (9,10,11,12) | 2–3 | 6–9 |
| Türk Dili ve Edebiyatı | 3 | 4 | 3–6 | 6–8 |
| Fizik | 2 | 4 | 5–6 | 5–6 |
| Kimya | 2 | 4 | 5–6 | 5–6 |
| Biyoloji | 2 | 4 | 5–6 | 5–6 |
| Tarih / İnkılap | 2 | 4 | 5–6 | 5–6 |
| Coğrafya | 2 | 4 | 5–6 | 5–6 |
| İngilizce | 3 | 4 | 3–4 | 7–8 |
| Din Kültürü | 1 | 4 | 11 | 11 |
| Beden Eğitimi | 2 | 4 | 5–6 | 5–6 |
| Rehberlik | 1 | 0 | — | 0 |
| **Toplam** | **24** | **40** | | |

Gereklilik karşılandı: **her branş öğretmeni aynı dersi 2–6 şubeye verir** (Din Kültürü
öğretmeni tek olduğu için 11 şubeye verir — küçük okullarda gerçekçidir).

Ek 10 ders (etüt/kulüp) ikincil yük olarak 10 farklı öğretmene dağıtılır. `course.teachers`
dizisi çoğu derste tek elemanlı; **6 derste 2 elemanlı** (ortak yürütme — `can_manage_course`
çoklu yetki yolunu test eder). **2 derste dönem ortasında öğretmen değişir** (kenar durum
#17): `teachers` dizisi 2026-02-09'da değişmiş kabul edilir; geçmiş `course_session.teacher`
eski öğretmeni, sonrakiler yeniyi gösterir.

Sınıf öğretmeni (`class_group.teacher`): 11 şubenin her birine bir öğretmen atanır
(24 öğretmenden 11'i). Rehber öğretmen sınıf öğretmeni değildir.

### 1.6 Modüller ve okul ayarları

**21 modülün tamamı açık** (`school.modules` = `Module::ALL`, 4 paketin tamamı).
"Tam aktif kullanım" gereksinimi budur; modül kapısına dayanıklılık (§3 ilke 4) ancak tüm
modüller açıkken *pozitif* yönde test edilebilir — kapalı modül testi ayrı bir senaryodur.

`settings:school` (tek satır):

```
exam_kinds:          [{homework,1},{quiz,1},{midterm,2},{final,3},{project,2},{oral,1}]
attendance_statuses: ["present","absent","late","excused"]
grade_bands:         [{min:85,label:"Pekiyi"},{min:70,label:"İyi"},{min:55,label:"Orta"},
                      {min:45,label:"Geçer"},{min:0,label:"Geçmez"}]
max_file_bytes:          5242880
chatbot_history_turns:   8
max_chatbot_threads:     20
max_chatbot_message_len: 4000
meal_slots:          [{name:"kahvaltı",serving_minute:480},
                      {name:"öğle",serving_minute:735},
                      {name:"ikindi",serving_minute:930}]
dietary_tags:        ["vejetaryen","glutensiz","laktozsuz","fındık_alerjisi","helal"]
meal_cancel_cutoff_minutes: 720
```

**Not:** `exam_kinds` ağırlıkları varsayılandan (hepsi 1) farklı verilmiştir — böylece ders
ortalaması hesabının ağırlıklı yolu da veriyle test edilir.

### 1.7 `term` satırları

| id | `name` | `starts_at` | `ends_at` | `archived_at` |
|---|---|---|---|---|
| `term:guz2025` | `2025-2026 Güz Dönemi` | 2025-09-08 00:00 +03 | 2026-01-16 23:59 +03 | `NONE` |
| `term:bahar2026` | `2025-2026 Bahar Dönemi` | 2026-02-02 00:00 +03 | 2026-06-19 23:59 +03 | `NONE` |

Tüm `course` ve `class_group` satırları `term:bahar2026`'ya bağlanır (Hezarfen şemasında ders
yıl boyu tek kayıttır, `term` yalnız etikettir). `term.course_count = 50`,
`term.class_count = 11` (bahar); güz için `0`, `0`.

---

## 2. Takvim ve hacim

### 2.1 Kesin takvim

| Olay | Başlangıç | Bitiş | Gün/Hafta |
|---|---|---|---|
| **Güz dönemi (T1)** | **2025-09-08 Pzt** | **2026-01-16 Cum** | 19 hafta |
| Kasım ara tatili | 2025-11-10 Pzt | 2025-11-14 Cum | 1 hafta |
| Cumhuriyet Bayramı | 2025-10-29 Çar | 2025-10-29 | 1 gün |
| Yılbaşı | 2026-01-01 Per | 2026-01-01 | 1 gün |
| **Yarıyıl tatili** | **2026-01-19 Pzt** | **2026-01-30 Cum** | 2 hafta |
| **Bahar dönemi (T2)** | **2026-02-02 Pzt** | **2026-06-19 Cum** | 20 hafta |
| Ramazan Bayramı | 2026-03-20 Cum | 2026-03-22 Paz | okul 1 gün kapalı |
| Nisan ara tatili | 2026-04-06 Pzt | 2026-04-10 Cum | 1 hafta |
| **⭐ T_NOW (şimdi)** | **2026-04-13 Pzt 08:00 +03** | — | T2'nin 11. haftası |
| Ulusal Egemenlik ve Çocuk Bayramı | 2026-04-23 Per | — | *gelecek* |
| Emek ve Dayanışma Günü | 2026-05-01 Cum | — | *gelecek* |
| Atatürk'ü Anma, Gençlik ve Spor B. | 2026-05-19 Sal | — | *gelecek* |
| Kurban Bayramı | 2026-05-26 Sal | 2026-05-29 Cum | *gelecek* |

**Aritmetik kontrolü:**
- T1 = 130 gün = 19,0 hafta; eksi 1 hafta ara tatil → **18 öğretim haftası**
- T2 başlangıcından `T_NOW`'a = 70 gün = **tam 10,0 hafta**; eksi 1 hafta Nisan ara tatili
  → **9 öğretim haftası**
- `T_NOW`'dan T2 sonuna = 67 gün = **9,57 hafta ≈ 2,2 ay** ✔ ("bitmesine 2 ay var")
- **Geçmiş toplam öğretim haftası = 18 + 9 = 27**
- Geçmiş okul günü = 27 × 5 − 3 resmi tatil = **132 gün**

**Üretim penceresi kuralı:**
- `starts_at ≤ T_NOW` olan her şey **gerçekleşmiş** kabul edilir (yoklama, cevap, teslim var).
- `T_NOW < starts_at ≤ 2026-06-19` olanlar **planlanmış** kayıtlardır: ileri tarihli `exam`
  (cevapsız), ileri `due_at`'li `homework` (kısmi teslimli), ileri `menu`, ileri
  `appointment_slot`, ileri `event`, ileri `fee_plan` taksitleri. `course_session`
  **ileri tarihli üretilmez** (oturum = yapılmış ders).
- `2026-06-19` sonrası hiçbir satır yoktur.

### 2.2 ŞEMA ERRATA — §1.6'daki ayarları BU DEĞERLER GEÇERSİZ KILAR

`spec/schema.json` kodda doğrulandı. Aşağıdaki maddeler §0–§2.1'de yazılanların üzerine
yazar; **çelişki halinde bu bölüm geçerlidir.**

| # | Düzeltme |
|---|---|
| E1 | Okul DB'sinde **60 tablo**, control DB'sinde **4 tablo** vardır (71 değil). |
| E2 | Tüm zaman alanları `int` **unix-ms**. **İki istisna:** `user.study_streak_last_day` ve `user.pomodoro_counted_day` **gün numarasıdır**: `gün = floor(unix_ms / 86400000) + 719163` (1970-01-01 = 719163). |
| E3 | `seq = 1` olan `exam_attempt` / `exam_answer` / `exam_result` / `answer_image` kayıt id'sine **sıra eki eklenmez** (`{exam}_{user}`); `seq` **sütununa** yine `1` yazılır. `seq > 1` için `{exam}_{user}_{seq}`. |
| E4 | Şemada **hiç `ASSERT` yok** → geçersiz enum sessizce kabul edilir. Üretici, yazdığı her enum değerini `schema.json → enums` ile **kod içinde** doğrulamalıdır. |
| E5 | `meal_slots` **varsayılanda bırakılır**: `breakfast`, `lunch`, `snack`. Sebep: slot adı `menu` kayıt id'sine **birebir** girer; Türkçe karakter ve `/ \ ? # %` risklidir. Ekranda Türkçe etiket UI işidir. |
| E6 | `dietary_tags` **varsayılanda bırakılır**: `vegetarian`, `vegan`, `gluten_free`, `lactose_free`, `nut_allergy`. |
| E7 | `meal_attendance.status` = **`served` / `missed`** (okulun `attendance_statuses` listesi DEĞİL). |
| E8 | `homework_result.status` = **`done` / `incomplete` / `missing`**. |
| E9 | `meal_booking.status` = **`booked` / `cancelled`** (yalnız ikisi). |
| E10 | `board_stroke.kind` = **`stroke` / `clear`** (yalnız ikisi; `image` yoktur). |
| E11 | `pool_question.status` = **`pending` / `approved`** (red bir durum değil — soru silinir). |
| E12 | `message.sender_folder` ∈ {`sent`,`archive`,`trash`}; `recipient_folder` ∈ {`inbox`,`archive`,`trash`}. `*_origin` alanları ev klasöründeyken `NONE`. |
| E13 | `badge_award.badge` **34 sabit koddan** biridir (12 değil). Rozet satırı, kullanıcının ilgili `*_total` sayacıyla **tutarlı olmak zorundadır** (`db/badge.rs` yalnız eşik aşıldığında verir). |
| E14 | `event.audience.kind` ∈ {`school`,`role`,`course`,`class`,`registration`}. `audience.users` alanı **kaldırılmıştır**, yazılmaz. |
| E15 | `pomodoro_session` ve `work_entry` **açıkken** id'si `open_{user_key}`, **kapanınca** yeni bir ULID'e taşınır. Tohumda kapalı kayıtlar ULID id alır; her kullanıcı için **en fazla 1** açık kayıt olabilir. |
| E16 | `settings.grade_bands` varsayılanı **boş listedir**; doldurulacaksa `min ∈ 0..=100`, `min` değerleri benzersiz ve **bir bant 0'dan başlamalı** (§1.6'daki liste bu kurala uyar). |
| E17 | `exam.mode` ∈ {`sync`,`async`,`open`,`NONE`}; `NONE` = çevrimdışı notlanan, girilemeyen taslak. |
| E18 | Para alanları tamsayı **kuruş**; `menu_dish.price_minor ≤ 1.000.000`, ledger `amount_minor ≤ 10.000.000`. |
| E19 | `exam_result.mark` / `homework_result.mark` ∈ `0..=100`; `HIGH_MARK_MIN = 90`. `exam_question.points` ∈ `1..=100`. |
| E20 | `menu.date` tam **10 karakter** `YYYY-MM-DD` metnidir ve kayıt id'sinin parçasıdır. |
| E21 | `exam_question.choices[*].id` **rastgele ULID**'dir (monotonik değil); şıklar **sıraya** göre gösterilir, id'ye göre değil. |
| E22 | `homework_result` ile `homework_submission` **aynı kayıt anahtarını** paylaşır (`{homework}_{user}`) — `graded_by_result` bu sayede aramasız adreslenir. |
| E23 | `module` listesi **sıralı** saklanır. Bağımlılıklar: `subjects`/`course_notes`/`sessions`/`classes` → `courses`; `exams`+`homework` → `courses`+`subjects`; `marks` → `exams`; `attendance` → `events`+`sessions`. 21'inin tamamı açık olduğu için hepsi sağlanır. |

### 2.3 Hacim tablosu — tablo bazında satır sayıları

> Sıra: satır sayısına göre azalan. **Hedef aralık: 300.000–600.000.**

| # | Tablo | Satır | Hesap / gerekçe |
|---|---|---|---|
| 1 | `exam_answer` | **259.000** | 14.800 oturum × 20 soru × 0,875 cevaplama oranı |
| 2 | `session_attendance` | **98.400** | 4.158 çekirdek oturum × 22,7 öğr. + 270 etüt/kulüp × 15 |
| 3 | `homework_submission` | **26.200** | 480 geçmiş ödev × 62,5 kayıtlı × 0,873 teslim oranı |
| 4 | `pomodoro_session` | **26.000** | 170 kullanan öğrenci × ~153 stint (27 hafta) |
| 5 | `homework_result` | **23.000** | teslimlerin %87,8'i notlandı |
| 6 | `exam_attempt` | **14.800** | 14.100 ilk oturum + 564 ikinci deneme + 150 etüt/kulüp |
| 7 | `exam_result` | **13.600** | oturumların %92'si notlandı |
| 8 | `meal_ledger` | **12.400** | 11.800 `charge` + 580 `credit` + 20 `reversal` |
| 9 | `meal_booking` | **11.800** | 132 gün × 75 öğle + 2.500 ikindi |
| 10 | `meal_attendance` | **11.100** | rezervasyonların %94'ü |
| 11 | `homework_file` | **9.500** | teslimlerin %26'sı × 1,4 dosya |
| 12 | `board_stroke` | **9.000** | 280 tahta × ortalama 32 vuruş |
| 13 | `chatbot_message` | **9.000** | 1.500 iş parçacığı × 6 mesaj (3 `user` + 3 `assistant`) |
| 14 | `message` | **6.800** | 563 kullanıcı × ort. 12 mesaj |
| 15 | `exam_question` | **6.640** | 320 çoktan-seçmeli/karma sınav × 20 + 20 etüt sınavı × 12 |
| 16 | `course_session` | **4.428** | 14 blok × 11 şube × 27 hafta + 10 ek ders × 27 |
| 17 | `payment_ledger` | **4.400** | 2.250 `charge` + 2.130 `credit` + 20 `refund` |
| 18 | `registration` | **4.100** | 58 etkinlik × ort. 71 kayıt |
| 19 | `work_entry` | **3.460** | 28 personel × 132 gün × 0,94 |
| 20 | `enrollment` | **2.790** | 2.500 çekirdek + 290 etüt/kulüp |
| 21 | `attendance` (etkinlik) | **2.500** | yoklama alınan 35 etkinlik × ~71 |
| 22 | `note` | **1.530** | 138 öğrenci × 9 + 24 öğretmen × 12 |
| 23 | `chatbot_thread` | **1.500** | 155 öğrenci × 9 + 19 öğretmen × 4 |
| 24 | `menu_dish` | **1.240** | 310 menü × 4 yemek |
| 25 | `bank_question` | **900** | 24 öğretmen × ort. 37,5 şablon |
| 26 | `appointment_slot` | **800** | 15 öğretmen × 27 hafta × ~2 |
| 27 | `answer_image` | **800** | metin cevaplarının %6'sı çizimli |
| 28 | `solution` | **780** | 319 çözümlü havuz sorusu × 2,44 |
| 29 | `badge_award` | **730** | 200 aktif öğrenci × 3,4 + 24 öğretmen × 2 |
| 30 | `pool_question` | **640** | 148 kullanan öğrenci × 4,3 |
| 31 | `homework` | **590** | 40 ders × 14 (12 geçmiş + 2 gelecek) + 30 ek |
| 32 | `user` | **563** | 1 + 3 + 24 + 250 + 285 |
| 33 | `appointment` | **520** | 800 slotun %65'i talep gördü |
| 34 | `note_file` | **420** | notların %27'si |
| 35 | `question_image` | **400** | soruların %6'sı |
| 36 | `subject` | **390** | 360 çekirdek + 30 ek |
| 37 | `course_note` | **360** | 40 ders × 9 |
| 38 | `rag_output` | **360** | her ders notu için 1 indeks çıktısı |
| 39 | `exam` | **340** | 240 geçmiş + 80 gelecek + 20 etüt/kulüp |
| 40 | `menu` | **310** | 132 öğle + 112 ikindi + 66 kahvaltı |
| 41 | `parent_link` | **299** | §1.2 |
| 42 | `board` | **280** | 192 öğretmen + 88 öğrenci tahtası |
| 43 | `course_note_file` | **260** | ders notlarının %72'si |
| 44 | `class_member` | **250** | 1 öğrenci = 1 şube |
| 45 | `fee_plan_assignment` | **250** | her öğrenci bir plana atanmış |
| 46 | `class_course` | **110** | 11 şube × 10 ders |
| 47 | `event` | **58** | 27 haftada ~2,1/hafta |
| 48 | `dietary_profile` | **55** | öğrencilerin %22'si |
| 49 | `course` | **50** | 40 çekirdek + 4 `study` + 6 `club` |
| 50 | `session` (giriş) | **40** | canlı oturum (test kullanıcıları) |
| 51 | `bank_question_image` | **35** | banka sorularının %4'ü |
| 52 | `class_group` | **11** | |
| 53 | `kind_ref` | **6** | kullanılan 6 sınav türü |
| 54 | `class_blueprint` | **4** | 9, 10, 11, 12 |
| 55 | `fee_plan` | **4** | Peşin · 9 Taksit · 6 Taksit · Burslu |
| 56 | `slot_ref` | **3** | breakfast, lunch, snack |
| 57 | `term` | **2** | |
| 58 | `migration_mark` | **2** | |
| 59 | `settings` | **1** | `settings:school` |
| 60 | `school` (control DB) | **1** | `school:ataturk-anadolu` |
| | **TOPLAM** | **≈ 572.000** | hedef aralığın (300k–600k) üst yarısında |

**Alt toplamlar (doğrulama için):**

| Küme | Satır | Pay |
|---|---|---|
| Sınav ekseni (`exam*`, `question_image`, `answer_image`, `bank_question*`) | 296.175 | %51,8 |
| Yoklama / oturum (`course_session`, `session_attendance`) | 102.828 | %18,0 |
| Ödev (`homework*`) | 59.290 | %10,4 |
| Davranış (`pomodoro`, `board*`, `chatbot*`, `note*`, `message`) | 54.490 | %9,5 |
| Yemek + ödeme (etik kapı altındaki veri) | 51.304 | %9,0 |
| Diğer (kimlik, yapı, etkinlik, randevu, havuz) | 8.021 | %1,4 |

### 2.4 Ders oturumu ve yoklama takvimi

- **Haftalık blok dağılımı (şube başına 14):** Matematik 3 · Edebiyat 2 · İngilizce 2 ·
  Fizik 1 · Kimya 1 · Biyoloji 1 · Tarih 1 · Coğrafya 1 · Din 1 · Beden 1
- **Blok saatleri (TR):** 08:40, 09:40, 10:40, 11:40, 13:20, 14:20. Haftalık 14 blok bu
  6 slot × 5 gün = 30 slot içine çakışmasız dağıtılır (şube ders programı sabittir).
  `course_session.starts_at` = slot başı, `ends_at = starts_at + 40 dk`.
- `course_session.topic` = `"<şube> · <konu adı>"`, ör. `"9-A · Fonksiyon Kavramı"`.
  Konu ilerleyişi doğrusaldır: dersin 10 konusu 27 haftaya eşit bölünür.
- **`held_counted_at`:** oturumların **%96'sında** dolu (`starts_at + U(35, 180) dk`),
  **%4'ünde `NONE`** (öğretmen "yapıldı" işaretlemedi) → `lessons_held_total` sayacı ile
  ham veri arasında kontrollü sapma.
- **Yoklama girme oranı:** oturumların **%91'inde** `session_attendance` satırı var;
  **%9'unda hiç yoklama girilmemiş** (399 oturum). Yoklaması olmayan oturum devam oranı
  paydasına **girmez** — "veri yok" ile "devamsız" ayrımının testi.
- **Etüt/kulüp:** haftada 1 oturum, kayıtlı öğrencilerin %78'i yoklamada.
- `session_attendance.marked_by` = oturumun öğretmeni (her zaman).

### 2.5 Sınav takvimi

**Ders başına geçmiş sınav = 6** (T1: 4, T2: 2). **Gelecek planlanmış = 2.**

| # | Dönem | Pencere | `kind` | `mode` | Soru | `duration_ms` | `max_attempts` | `allow_review` |
|---|---|---|---|---|---|---|---|---|
| 1 | T1 | 2025-10-06 … 10-17 | `quiz` | `sync` | 10 | 1.200.000 | 1 | `true` |
| 2 | T1 | 2025-11-17 … 11-28 | `midterm` | `sync` | 25 | 2.400.000 | 1 | `true` |
| 3 | T1 | 2025-12-08 … 12-19 | `project` | `async` | 6 (`text`) | `NONE` | 1 | `false` |
| 4 | T1 | 2026-01-05 … 01-16 | `final` | `sync` | 30 | 3.600.000 | 1 | `true` |
| 5 | T2 | 2026-02-23 … 03-06 | `quiz` | `sync` | 12 | 1.200.000 | **2** | `true` |
| 6 | T2 | 2026-03-23 … 04-03 | `midterm` | `sync` | 25 | 2.400.000 | 1 | %62 `true` |
| 7 | T2 | **2026-04-27 … 05-08** | `oral` | `open` | 5 (`text`) | `NONE` | 1 | `false` |
| 8 | T2 | **2026-05-25 … 06-05** | `final` | `sync` | 30 | 3.600.000 | 1 | `false` |

7 ve 8 numaralı sınavlar `T_NOW`'un ötesindedir → `exam_attempt` / `exam_answer` /
`exam_result` **yoktur**; `exam_question` satırları vardır (öğretmen hazırlamış) ve
8 numaralıların **%35'i `draft = true`**'dur.

- **Tarih dağıtımı:** her dersin sınavı, penceresindeki rastgele bir okul gününe düşer;
  **aynı şubede aynı gün ≤ 2 sınav** kısıtı uygulanır.
- **`mode` genel payı:** `sync` %56 · `async` %33 · `open` %11 (yukarıdaki tablodan türer).
- **`allow_rejoin`:** `sync` sınavların %72'sinde `true`, diğerlerinde şema varsayılanı.
- **`starts_at`/`ends_at`:** `sync` → aynı gün 1–2 saatlik pencere · `async` → 5 gün ·
  `open` → 10 gün.
- **Soru tipi karışımı (birleşik):** `choice` **%85** · `text` **%15**. 3 ve 7 numaralı
  sınavlar **%100 `text`**'tir; kalan sınavlarda `text` payı **%8**'dir.
- **`points`:** sınav toplam puanı **daima tam 100**'dür. 10 soruluk sınavda 10 puan,
  25'likte 4, 30'lukta 3 (+ artan puan ilk sorulara dağıtılır), `text` sorular 10–20 puan.
  Tümü `1..=100` aralığında (E19).
- **`kind_ref`:** kullanılan 6 sınav türü için birer satır; not girildikçe sayaç artar.
- **Notlandırma gecikmesi:** `ends_at` + `LogN(medyan 4,2 gün, σ_log 0,80)`, üst sınır 21 gün.
  Bu gecikme yalnız `_seed_manifest.json`'a yazılır — `exam_result`'ta zaman damgası yoktur.
- **Son 3 haftanın 26 sınavı hiç notlandırılmamıştır** (`exam_result` yok, `result_count = 0`).

### 2.6 Ödev takvimi

- **Ders başına:** ayda 2 ödev → **12 geçmiş** + **2 gelecek** (`due_at > T_NOW`).
  Etüt/kulüp dersleri 3'er ödev.
- `homework.created_at` = atanma anı; `due_at = created_at + U(5, 12) gün`, saat
  **23:59 TR** (%86) veya **17:00 TR** (%14).
- `assigned`: **%78'inde `NONE`** (tüm ders), %22'sinde kayıtlı öğrencilerin rastgele %55'i
  (üst sınır `MAX_HOMEWORK_ASSIGNED = 200`, aşılmaz).
- `subject`: o haftaya denk gelen konu (doğrusal ilerleyiş).
- **Gelecek ödevlerde kısmi teslim:** `due_at − T_NOW < 7 gün` ise teslim oranı **%34**,
  daha uzaksa **%6**. Bu, Ö4'ün "yaklaşan teslim" kartını canlı veriyle besler.
- **`due_at` kaydırma:** geçmiş ödevlerin **%7'sinde (34 ödev)** `due_at`, ilk teslimler
  geldikten sonra **+48 saat** ileri alınmıştır.

### 2.7 Diğer modüllerin takvimi ve hacmi

| Modül | Kural | Hacim |
|---|---|---|
| **Etkinlik** | Ayda 2 okul geneli + ayda 1,5 şube/ders bazlı; tatilde 0 | 58 (43 geçmiş, 15 gelecek) |
| `event.audience.kind` | `school` %31 · `role` %10 · `class` %26 · `course` %21 · `registration` %12 | — |
| `registration` | Kapsamdaki öğrencilerin %62'si; `registered_by` = personel (öğrenci kendini kaydedemez) | 4.100 |
| `attendance` | 43 geçmiş etkinliğin 35'inde yoklama alınmış | 2.500 |
| **Randevu** | 15 öğretmen haftada 2 slot (Salı/Perşembe 15:30 ve 16:00), 20 dk, `occupied` cap 1 | `appointment_slot` 800 |
| `appointment_slot.series` | %64'ünde dolu (haftalık seri ULID metni), %36 tekil | — |
| `appointment.status` | `approved` %58 · `pending` %17 · `rejected` %9 · `cancelled` %16 | 520 |
| `appointment.requester` | öğrenci %61 · veli %39 | — |
| **Menü** | `lunch` her okul günü (132) · `snack` haftada 4 (112) · `breakfast` haftada 2,5 (66) | `menu` 310 |
| `menu.capacity` | lunch 180 · snack 90 · breakfast 60; `seats_booked` tutarlı | — |
| `menu_dish` | menü başına 4; `price_minor` `U(1500, 6500)` kuruş; `tags` %38'inde 1–2 etiket | 1.240 |
| **Ödeme** | 4 plan (aşağıda); taksit vadesi her ayın 10'u, 2025-09-10 → 2026-06-10 | `fee_plan_assignment` 250 |
| `payment_ledger` | `charge` 2.250 · `credit` 2.130 · `refund` 20; gecikmiş taksit %11 | 4.400 |
| **Pomodoro** | §5.3 | 26.000 |
| **Sohbet** | §5.4 | 1.500 thread / 9.000 mesaj |
| **Not** | 138 öğrenci (%55) × 9 + 24 öğretmen × 12; `updated_at` alanı **yok** | 1.530 |
| **Mesaj** | §5.7 | 6.800 |
| **Tahta** | 280 tahta; 12'si `closed_at` dolu; 8'i `locked`; 3'ü `epoch = 2` | 9.000 vuruş |
| **Mesai** | 28 personel × 132 gün × 0,94; `check_out` %5'inde `NONE` (E15: açık kayıt id'si `open_<user>`, kullanıcı başına en fazla 1) | 3.460 |
| **Rozet** | 34 koddan seçilir; `earned_at` = sayacın eşiği geçtiği gerçek an | 730 |
| **Ders notu** | 40 ders × 9; her not için 1 `rag_output` (`payload` FLEXIBLE, sahte gömme meta verisi) | 360 + 360 |

**Ücret planları:**

| `fee_plan.name` | Öğrenci | Taksit | `amount_minor` / taksit |
|---|---|---|---|
| Peşin Ödeme | 22 | 1 | 1.800.000 |
| 9 Taksit | 168 | 9 | 220.000 |
| 6 Taksit | 42 | 6 | 325.000 |
| Burslu | 18 | 9 | 55.000 |

Tutarlar `MAX_LEDGER_AMOUNT_MINOR = 10.000.000` sınırının altındadır (E18).

---

## 3. Öğrenci arketipleri

**Bu bölüm senaryonun çekirdeğidir.** Tavsiye sisteminin bulması *gereken* desenler burada
tanımlanır. Bir ürün bir arketipi bulamıyorsa ürün yanlıştır, veri değil.

### 3.1 Arketip tablosu

| Kod | Ad | Pay | Öğrenci | Test ettiği ürün |
|---|---|---|---|---|
| **A1** | İstikrarlı Yüksek Başarılı | %12,0 | **30** | Ö1 (güçlü bant), Y1, V1 |
| **A2** | Ortalama / Sabit | %28,0 | **70** | taban çizgi — tüm ürünlerin "normal" referansı |
| **A3** | Tek Derste Konu Boşluğu | %14,0 | **35** | **Ö1, Ö2, T3** (bireysel vs. sınıf ayrımı) |
| **A4** | Erteleyen | %12,8 | **32** | **Ö4**, T4 (ödev tetikleyicisi), Ö3 (düzensiz çalışma) |
| **A5** | Yükselen | %10,0 | **25** | Ö1 zaman serisi, V1, **T4 yanlış-pozitif kontrolü** |
| **A6** | Düşen (kırılma noktalı) | %8,8 | **22** | **T4** (dört tetikleyicinin tamamı), V1 |
| **A7** | Devamsız / Kopuk | %7,2 | **18** | T4 (devamsızlık), **Ö1 soğuk başlangıç kapısı** |
| **A8** | Yardım Arayan | %7,2 | **18** | **T5, Ö5**, Ö3 |
| | **Toplam** | **%100,0** | **250** | |

**Dağıtım kuralı:** arketipler şubeler arasında **tabakalı** dağıtılır — her şubede her
arketipten en az 1 öğrenci bulunur (T3'ün her sınıfta hem bireysel hem sınıf düzeyi sinyal
göstermesi için). İki bilinçli yoğunlaşma: **9-B'de 5 adet A6**, **11-C'de 6 adet A7** —
T4'ün "sınıf düzeyinde sorun" ile "bireysel sorun" ayrımını test eder.

### 3.2 Ürün × arketip sinyal matrisi

| Ürün | A1 | A2 | A3 | A4 | A5 | A6 | A7 | A8 |
|---|---|---|---|---|---|---|---|---|
| **Ö1** Konu Karnesi | güçlü bant | sınıf düzeyi | **1 derste 3 konu düşük** | sınıf düzeyi | T1 düşük→T2 güçlü | T1 güçlü→T2 düşük | **n<8 kapısı devreye girer** | sınıf düzeyi |
| **Ö2** Tekrar Listesi | 2–3 madde | 5–7 madde | **hep aynı konu** | 6–9 madde | azalan | artan | çok az veri | 6–8 madde |
| **Ö3** Çalışma Aynası | düzenli ısı haritası | seyrek | düzenli | **sınav öncesi yığılma** | artan sıklık | **sıfıra iniş** | veri yok | kısa+sık, gece |
| **Ö4** Teslim Takvimi | −3,2 gün medyan | −14 saat | −16 saat | **+2 saat (GEÇ)** | iyileşen | **kötüleşen** | **%48 eksik** | −20 saat |
| **Ö5** Sorunu Sor | kullanmaz | nadir | **konu eşleşir** | nadir | artan | azalan | kullanmaz | **7,5 soru/dönem** |
| **T1** Madde Analizi | üst %27 grubu | orta | orta | orta | değişken | değişken | alt %27 grubu | alt-orta |
| **T2** Soru Kalitesi | ayırt ediciliği besler | — | — | — | — | — | ayırt ediciliği besler | — |
| **T3** Isı Haritası | yeşil satır | nötr | **tek kırmızı hücre** | nötr | soldan sağa yeşilleşen | soldan sağa kızaran | gri (veri yok) | nötr |
| **T4** Dikkat Listesi | **listede olmamalı** | olmamalı | olmamalı | **ödev tetikleyicisi** | **olmamalı (yanlış poz.)** | **4/4 tetikleyici** | **devamsızlık tetikleyicisi** | olmamalı |
| **T5** Yardım Arayan | — | — | — | — | — | — | — | **3/3 tetikleyici** |
| **V1** Veli Özeti | dolu, olumlu | dolu | dolu | eksik ödev satırı | iyileşme | kötüleşme | eksik devam | dolu |
| **Y1** Ölçme Panosu | *(öğrenci bağımsız — §6 #10, #11, #12 besler)* | | | | | | | |

### 3.3 Ortak gösterim

- `θ_u` = öğrencinin **gizli yeteneği** (logit ölçeği, Rasch mantığı — §4.4).
- `θ_u(t)` = zamana bağlı yetenek; `trend` sıfır değilse `progress(t) ∈ [0,1]` ile ölçeklenir.
  `progress(t)` = öğretim günü indeksinin normalize hali (`0` = 2025-09-08, `1` = `T_NOW`).
- `δ_u(ders)`, `δ_u(konu)` = kişiye özel ders/konu sapmaları (logit, toplanır).
- "Oran" parametreleri `Beta(α, β)` (ortalama `α/(α+β)`), "süre/gecikme" parametreleri
  belirtilen dağılımdan çekilir.
- `ω_u` = boş bırakma eğilimi (§4.6'da kullanılır).

### 3.4 A1 — İstikrarlı Yüksek Başarılı (30 öğrenci, %12,0)

| Parametre | Değer |
|---|---|
| `θ_u` | `N(μ=1.25, σ=0.30)`, kırpma `[0.55, 2.10]`, `trend = 0` |
| `δ_u(ders)` | `N(0, 0.22)` her ders için bağımsız |
| `δ_u(konu)` | `N(0, 0.18)` |
| **Beklenen doğruluk** | **%78 ± 4** |
| Devamsızlık taban oranı | `Beta(3, 97)` → **%3,0** |
| Devamsızlık statüsü | `absent` %42 · `excused` %58 (raporlu) |
| `late` oranı | %2,1 |
| Ödev teslim oranı | `Beta(99, 1)` → **%99** |
| Teslim payı medyanı | **3,2 gün önce** (dağılım ağırlıkları §5.2) |
| `counted_on_time` oranı | **%97** |
| Pomodoro | **5,2 gün/hafta** · günlük stint `Poisson(λ=3.1)` · süre `LogN(medyan 27 dk, σ_log 0.38)` |
| Pomodoro gece payı (22:00–02:00) | %14 |
| Sohbet | kullanan %63; kullananlarda **4 mesaj/ay** |
| Randevu | **0,8 / dönem** |
| Havuz | 0,4 soru sorma · **2,1 çözüm yazma** (akran çözümü üretir) |
| `ω_u` (boş bırakma) | **0,25** → beklenen boş oranı %4,2 |
| Sınava katılım | %99 |
| Tahta vuruşu | 6 / hafta |
| Rozet sayısı | 6–9 |

### 3.5 A2 — Ortalama / Sabit (70 öğrenci, %28,0)

| Parametre | Değer |
|---|---|
| `θ_u` | `N(0.05, 0.35)`, kırpma `[-0.70, 0.85]`, `trend = 0` |
| `δ_u(ders)` / `δ_u(konu)` | `N(0, 0.30)` / `N(0, 0.26)` |
| **Beklenen doğruluk** | **%58 ± 5** |
| Devamsızlık | `Beta(8, 92)` → **%8,0**; `absent` %78 · `excused` %22 |
| `late` | %5,5 |
| Ödev teslim oranı | `Beta(88, 12)` → **%88** |
| Teslim payı medyanı | **14 saat önce** |
| `counted_on_time` | **%79** |
| Pomodoro | **2,4 gün/hafta** · `Poisson(2.2)` · `LogN(22 dk, 0.45)` · gece payı %28 |
| Sohbet | kullanan %58; **3 mesaj/ay** |
| Randevu | **0,4 / dönem** |
| Havuz | 1,1 sorma · 0,7 çözüm |
| `ω_u` | **0,55** → boş oranı %11,8 |
| Sınava katılım | %95 |
| Tahta | 3 / hafta · Rozet 3–5 |

### 3.6 A3 — Tek Derste Konu Boşluğu (35 öğrenci, %14,0)

**Amaç:** Ö1 ve T3'ün "genel olarak iyi ama şu konuda boşluk var" ayrımını yapabildiğini
kanıtlamak. Kataloğun en değerli çıktısı budur.

| Parametre | Değer |
|---|---|
| `θ_u` (genel) | `N(0.45, 0.30)`, kırpma `[-0.15, 1.20]`, `trend = 0` |
| **Boşluk dersi** (öğrenci başına 1) | Matematik %34 · Fizik %20 · Kimya %14 · Biyoloji %11 · İngilizce %11 · Edebiyat %10 |
| **`δ_u(boşluk dersi)`** | **`−1.60`** (sabit, gürültüsüz) |
| **Boşluk konuları** | O dersin konularından **ardışık 3 konu**; bunlara ek `δ_u(konu) = −0.90` |
| Diğer derslerde `δ_u(ders)` | `N(+0.10, 0.20)` |
| `δ_u(konu)` (boşluk dışı) | `N(0, 0.24)` |
| **Beklenen doğruluk (genel)** | **%66 ± 5** |
| **Beklenen doğruluk (boşluk konuları)** | **%31 ± 6** |
| **Beklenen doğruluk (diğer konular)** | **%72 ± 5** |
| Aynı konuda **sınıf ortalaması** | **%58 ± 5** → "sınıf iyi, öğrenci kötü" ayrımı geçerli |
| Devamsızlık | `Beta(7, 93)` → **%7,0**; `absent` %75 · `excused` %25 |
| `late` | %4,8 |
| Ödev teslim oranı | **%90** genel; **boşluk dersinde %71** (kaçınma davranışı) |
| Teslim payı medyanı | 16 saat önce; boşluk dersinde 4 saat önce |
| `counted_on_time` | %85 |
| Pomodoro | **2,8 gün/hafta** · `Poisson(2.4)` · `LogN(24 dk, 0.42)` |
| Sohbet | kullanan %60; 3 mesaj/ay |
| Randevu | **1,2 / dönem** — **%64'ü boşluk dersinin öğretmeniyle** |
| Havuz | **2,3 soru / dönem — %68'i boşluk dersinin konusundan** (Ö5 eşleştirme testi) |
| `ω_u` | 0,60 genel; **boşluk konularında 1,15** → o konularda boş oranı **%28** |
| Sınava katılım | %94; boşluk dersinde %88 |

### 3.7 A4 — Erteleyen (32 öğrenci, %12,8)

| Parametre | Değer |
|---|---|
| `θ_u` | `N(-0.10, 0.40)`, kırpma `[-1.00, 0.70]`, **`trend = −0.10`** |
| `δ_u(ders)` / `δ_u(konu)` | `N(0, 0.32)` / `N(0, 0.28)` |
| **Beklenen doğruluk** | **%53 ± 6** |
| Devamsızlık | `Beta(11, 89)` → **%11,0**; **Pazartesi'ye ek çarpan ×1,8** |
| Devamsızlık statüsü | `absent` %84 · `excused` %16 |
| **`late` oranı** | **%12,4** (geç gelme belirgin) |
| Ödev teslim oranı | `Beta(82, 18)` → **%82** |
| **Teslim payı medyanı** | **−2 saat** (teslimlerin yarısı son tarihten *sonra*) |
| **`counted_on_time`** | **%48** → Ö4 "yüksek öncelik" rozeti + T4 ödev tetikleyicisi |
| Teslim dağılım ağırlıkları | son-24-saat %52 · 1–7 gün %10 · erken %1 · **geç %37** |
| Pomodoro | **2,1 gün/hafta**, ama **%70'i sınavdan önceki 48 saatte** (`E_sınav` üs katsayısı ×1,8) |
| Pomodoro süresi | `LogN(medyan 41 dk, σ_log 0.55)` — uzun, yoğun, düzensiz |
| **Pomodoro gece payı (22:00–02:00)** | **%47** |
| Sohbet | kullanan %66; 5 mesaj/ay |
| Randevu | 0,6 / dönem · Havuz 1,0 |
| `ω_u` | **0,75** → boş oranı %16,5 |
| Sınava katılım | **%91** (kaçırdığı sınavlar T4'ün 4. tetikleyicisine altyapı) |

### 3.8 A5 — Yükselen (25 öğrenci, %10,0)

| Parametre | Değer |
|---|---|
| **`θ_u(t)`** | **`θ_u(t) = −0.70 + 1.50 · progress(t)` + `N(0, 0.25)` (kişiye sabit kayma)** |
| Sonuç | T1 başı `θ ≈ −0.70` (doğruluk ~%37) → `T_NOW` `θ ≈ +0.80` (doğruluk ~%72) |
| **Beklenen doğruluk** | **T1: %40 ± 5 → T2: %70 ± 5** |
| `δ_u(ders)` / `δ_u(konu)` | `N(0, 0.28)` / `N(0, 0.24)` |
| Devamsızlık | T1 **%14** → T2 **%5** (2026-02-02'de doğrusal geçiş) |
| `late` | %7 → %3 |
| Ödev teslim oranı | T1 **%70** → T2 **%95** |
| `counted_on_time` | T1 **%55** → T2 **%89** |
| Teslim ağırlıkları | T1 (%50/%26/%6/%18) → T2 (%38/%34/%22/%6) |
| Pomodoro | T1 **0,9** → T2 **4,3** gün/hafta · `LogN(25 dk, 0.44)` |
| Sohbet | 2 → 5 mesaj/ay (kullanan %72) |
| Randevu | **2,1 / dönem** (çoğu T2'de — yardım aramaya başladı) |
| Havuz | 0,8 → 2,4 |
| `ω_u` | **0,55** (sabit) → boş oranı %11,5 |
| Sınava katılım | T1 %88 → T2 %99 |

**T4 için kritik:** A5 **Dikkat Listesi'nde görünmemelidir.** T4'ün kuralları "son 30 gün
önceki 30 günden kötü" der; A5'te tersi doğrudur. Bu arketip, T4'ün yanlış pozitif
üretmediğini kanıtlayan **negatif kontroldür** (kabul ölçütü: ≤ 2 / 25).

### 3.9 A6 — Düşen, kırılma noktalı (22 öğrenci, %8,8)

**Kırılma tarihi `T_BREAK`:** öğrenci başına şu 4 Pazartesi'den biri —
**2026-02-09 · 2026-02-16 · 2026-02-23 · 2026-03-02** (her birine 5–6 öğrenci).
Kırılma sonrası geçiş **ani değil, 10 günde doğrusaldır** (gerçekçi).

| Parametre | `T_BREAK` öncesi | `T_BREAK` sonrası (`T_NOW`'da) |
|---|---|---|
| `θ_u` | `N(0.55, 0.28)` | `θ_önce − 1.40` |
| **Beklenen doğruluk** | **%64 ± 5** | **%37 ± 5** |
| Devamsızlık | **%6** | **%27** |
| Devamsızlık statüsü | `absent` %70 / `excused` %30 | `absent` %88 / `excused` %12 |
| `late` | %4 | %14 |
| Ödev teslim oranı | **%92** | **%48** |
| `counted_on_time` | %85 | **%31** |
| Teslim payı medyanı | 20 saat önce | **−9 saat (geç)** |
| Teslim ağırlıkları | %44/%30/%14/%12 | %36/%12/%2/**%50** |
| Pomodoro gün/hafta | **3,4** | **0,25** |
| Sohbet mesajı/ay | 4 | 1 |
| Randevu / dönem | 0,5 | 0,2 |
| Havuz / dönem | 1,4 | 0,1 |
| Sınava katılım | %97 | **%74** |
| `ω_u` | 0,50 | **0,85** |
| Tahta / hafta | 4 | 0,5 |

**T4 için kritik — dört tetikleyicinin dördü de ateşlenmelidir:**

| # | T4 kuralı | A6'da beklenen |
|---|---|---|
| 1 | Devam oranı son 30 günde `< %80` **ve** önceki 30 günden `≥ 10` puan düşük | **%73 vs %94** ✔ |
| 2 | Son 30 günde `missing ≥ 3` **veya** `counted_on_time < %50` | **ort. 4,1 eksik; %31** ✔ |
| 3 | Son 3 sınav ortalaması önceki 3'ten `≥ 15` puan düşük | **ort. −21 puan** ✔ |
| 4 | Penceresi kapanmış sınavda `exam_attempt` yok, son 30 günde `≥ 2` | **22 öğrencinin 14'ünde** ✔ |

### 3.10 A7 — Devamsız / Kopuk (18 öğrenci, %7,2)

| Parametre | Değer |
|---|---|
| `θ_u` | `N(-0.75, 0.35)`, kırpma `[-1.80, -0.05]`, **`trend = −0.15`** |
| `δ_u(ders)` / `δ_u(konu)` | `N(0, 0.34)` / `N(0, 0.30)` |
| **Beklenen doğruluk** | **%42 ± 7** |
| Devamsızlık | `Beta(31, 69)` → **%31,0**; **Pazartesi'ye ek ×1,55, Cuma'ya ek ×1,50** |
| Devamsızlık statüsü | `absent` **%86** · `excused` %14 (raporsuz devamsızlık) |
| `late` | %9,8 |
| Ödev teslim oranı | `Beta(52, 48)` → **%52** |
| Teslim ağırlıkları | %40/%12/%2/**%46 geç** |
| `counted_on_time` | **%29** |
| Pomodoro | **0,15 gün/hafta** → **18 öğrencinin 13'ünde hiç `pomodoro_session` yok** |
| Sohbet | **18 öğrencinin 15'i hiç kullanmamış** (`chatbot_thread_count = 0`) |
| Randevu | 0,1 / dönem · Havuz 0,05 |
| `ω_u` | **1,10** → boş oranı **%25,4** |
| Sınava katılım | **%78** |
| Tahta | 0,4 / hafta · Rozet 0–2 |
| Mesaj | **veliden öğretmene** mesaj yüksek: 3,2 / dönem (devamsızlık uyarısı yanıtı) |

**Ö1 için kritik:** A7'nin cevap hacmi düşük olduğundan çoğu konuda `n < 8` kalır → Ö1'in
**güven kapısı devreye girmeli** ve bant yerine "veri toplanıyor" gösterilmelidir.
Kabul ölçütü: A7'de konuların **≥ %55'i** "veri toplanıyor" durumunda.

### 3.11 A8 — Yardım Arayan (18 öğrenci, %7,2)

| Parametre | Değer |
|---|---|
| `θ_u` | `N(-0.25, 0.30)`, kırpma `[-0.95, 0.45]`, **`trend = +0.20`** (yardım işe yarıyor) |
| `δ_u(ders)` / `δ_u(konu)` | `N(0, 0.28)` / `N(0, 0.25)` |
| **Beklenen doğruluk** | **%50 ± 5** |
| Devamsızlık | `Beta(9, 91)` → **%9,0**; `absent` %72 · `excused` %28 |
| `late` | %5,0 |
| Ödev teslim oranı | **%91** · `counted_on_time` **%81** · teslim payı medyanı 20 saat önce |
| Pomodoro | **3,1 gün/hafta** · `Poisson(2.6)` · `LogN(medyan 19 dk, σ_log 0.50)` — **kısa ve sık** |
| Pomodoro gece payı | %34 |
| **Randevu / dönem** | **4,2** (toplam ≈ 76) — **%40'ı `pending` ve `created_at` 3 günden eski** → **T5(a)** |
| **Havuz sorusu / dönem** | **7,5** (toplam ≈ 135) — **%35'i çözümsüz ve 7 günden eski** → **T5(b)** |
| **Sohbet mesajı / ay** | **22** (en yüksek; kullanan %100) — mesajların **%18'i `status = 'failed'`** |
| T5(c) koşulu | **18 öğrencinin 11'inde** son 14 günde `≥ 3 failed` mesaj |
| Sohbet konusu | %64 sistem kullanımı · %36 ders içeriği (asistan cevaplayamaz) |
| `ω_u` | 0,60 → boş oranı %13,2 |
| Sınava katılım | %96 |
| Mesaj | **öğrenciden öğretmene** 5,4 / dönem (en yüksek) |
| Rozet | 4–6 |

### 3.12 Arketip doğrulama özeti

| Arketip | Genel doğruluk | Devam oranı | `counted_on_time` | Pomodoro gün/hafta |
|---|---|---|---|---|
| A1 | **%78 ± 4** | %97,0 | %97 | 5,2 |
| A2 | **%58 ± 5** | %92,0 | %79 | 2,4 |
| A3 | **%66 ± 5** (boşlukta **%31 ± 6**) | %93,0 | %85 | 2,8 |
| A4 | **%53 ± 6** | %89,0 | **%48** | 2,1 |
| A5 | T1 **%40** → T2 **%70** | %86 → %95 | %55 → %89 | 0,9 → 4,3 |
| A6 | önce **%64** → sonra **%37** | %94 → %73 | %85 → %31 | 3,4 → 0,25 |
| A7 | **%42 ± 7** | **%69,0** | %29 | 0,15 |
| A8 | **%50 ± 5** | %91,0 | %81 | 3,1 |
| **Okul geneli** | **%58,4** | **%93,5** | **%74,8** | **2,5** |

---

## 4. Madde (soru) modeli

### 4.1 Üretici model ile analiz modeli neden farklı

Literatür (`30_literatur_arastirma.md`, Bulgu 5 / Linacre 1994) Rasch-1PL için ±1 logit
bandında ~30 gözlemi yeterli görür; **ayırt edicilik parametresi için 500–1000+ örneklem**
ister. 250 öğrencilik bir okulda 2PL kalibrasyonu **güvenilir değildir** — ve test etmemiz
gereken tam olarak budur.

- **Üretici model:** ayırt edicilik (`a_i`) ve şans tabanı (`c_i`) içeren, 1PL/Rasch
  çekirdeği üzerine kurulu 3PL. `a_i` bilerek geniş ve **kirli** üretilir (§4.3).
- **Analiz modeli:** §3'ün T1/T2 tasarımına uygun **klasik madde analizi** (`p` ve `D`).
- İkisi **kasıtlı olarak aynı değildir** — böylece sistem "kendi ürettiği modeli geri bulma"
  yanılsamasına düşemez.
- Gerçek `a_i`, `b_i`, `c_i` değerleri **DB'ye değil**, `_seed_manifest.json`'a yazılır.

### 4.2 Zorluk (p-değeri) dağılımı

`b_i` çekildikten sonra beklenen p-değeri, okul yetenek dağılımına (`θ` ort. ≈ 0,06,
σ ≈ 0,62) göre oluşur.

| Bant | Pay | `b_i` dağılımı | Hedef p | Soru (6.640 üzerinden) |
|---|---|---|---|---|
| Çok kolay | **%8** | `U(−2.60, −1.90)` | `p > 0.90` | **531** |
| Kolay | **%18** | `U(−1.85, −0.95)` | `0.80 ≤ p ≤ 0.90` | **1.195** |
| Uygun (orta) | **%44** | `U(−0.90, +0.60)` | `0.45 ≤ p < 0.80` | **2.922** |
| Zor | **%22** | `U(+0.65, +1.60)` | `0.30 ≤ p < 0.45` | **1.461** |
| Çok zor | **%8** | `U(+1.65, +2.80)` | `p < 0.30` | **531** |

**Neden bu şekil:** T1'in bant kuralı (`p < 0.30` çok zor, `p > 0.90` çok kolay) her iki
uçta da **görünür sayıda madde** bulmalıdır; dar bir dağılım T1'in uyarılarını hiç
tetiklemezdi. %16'lık uç pay gerçek okul sınavlarına da yakındır.

**Ders bazlı zorluk kayması (`b_i`'ye eklenir):** Matematik **+0.18** · Fizik **+0.18** ·
Kimya +0.10 · Biyoloji 0 · Tarih 0 · Coğrafya 0 · Edebiyat 0 · İngilizce **−0.12** ·
Din Kültürü **−0.45** · Beden Eğitimi **−0.45**.

### 4.3 Ayırt edicilik ve KASITLI KÖTÜ MADDELER

| Bant | Pay | `a_i` dağılımı | Beklenen klasik `D` | Soru | T2'nin vermesi gereken karar |
|---|---|---|---|---|---|
| İyi | **%62** | `N(1.15, 0.20)`, kırpma `[0.80, 1.80]` | `D ≥ 0.40` | **4.117** | "iyi" |
| Kabul | **%20** | `U(0.50, 0.79)` | `0.20 ≤ D < 0.40` | **1.328** | "kabul edilebilir" |
| Zayıf | **%10** | `U(0.18, 0.49)` | `0.10 ≤ D < 0.20` | **664** | "gözden geçir" |
| **Kasıtlı bozuk** | **%5** | `U(0.00, 0.10)` | `D < 0.10` | **332** | **"elden geçir"** |
| **Kasıtlı negatif** | **%3** | `U(−0.90, −0.35)` | **`D < 0`** | **199** | **"anahtar hatası şüphesi"** |

**Bozuk madde (`a ≈ 0`) anlamı:** doğruluk olasılığı yetenekten **bağımsızdır**;
`P(doğru) ≈ c + (1−c)·0,5` civarında sabitlenir → üst %27 ile alt %27 aynı oranda doğru
yapar → `D ≈ 0`. Gerçek karşılığı: belirsiz ifadeli, iki şıkkı da savunulabilir soru.

**Negatif madde (`a < 0`) anlamı:** iyi öğrenci **daha çok yanlış** yapar. Ek kural: bu
maddelerde çekici çeldiricinin çekiciliği yetenekle **artar**:
`w_m(θ) = clip(0.45 + 0.22 · θ, 0.20, 0.90)`.
Gerçek karşılığı: **cevap anahtarı yanlış girilmiş soru**. T1'de "bir çeldirici doğru
cevaptan fazla seçilmiş", T2'de negatif `D` uyarısı üretir.

> **ZORUNLU KURAL — örneklem kapısı.** T2'nin `n ≥ 30` kapısı açılmazsa bu maddeler asla
> bulunamaz ve senaryo boşa gider. Bu yüzden: **199 negatif maddenin tamamı ve 332 bozuk
> maddenin en az 166'sı (yarısı) bir `bank_question` şablonundan gelmek (`from_bank` dolu)
> ve o şablon en az 2 farklı sınavda kullanılmış olmak zorundadır.** Bu, madde başına
> **≥ 94 cevap** (2 × en küçük kohort 47) garanti eder.
>
> **Negatif kontrol:** bunların dışında **12 negatif madde** tek sınavda / tek kullanımda
> bırakılır → T2'nin "yeterli veri yok" davranışı test edilir.

### 4.4 Cevap üretim formülü

```
# 1) Öğrencinin o maddedeki etkin yeteneği
theta_ui(t) = theta_u(t)                 # arketipin zaman-bagimli yetenegi (§3)
            + delta_u(ders(i))           # kisiye ozel ders sapmasi
            + delta_u(konu(i))           # kisiye ozel konu sapmasi
            + phi_u(sinav)               # gun-formu: N(0, 0.28), SINAV BASINA TEK CEKIM
            + eps                        # madde-ici gurultu: N(0, 0.22)

# 2) Dogru cevap olasiligi  (1PL/Rasch cekirdegi + ayirt edicilik + sans tabani)
P(dogru | u,i) = c_i + (1 - c_i) * 1 / (1 + exp(-a_i * (theta_ui - b_i)))

# 3) Sans tabani
c_i = (1 / k_i) * 0.85       # k_i = sik sayisi
                             # k=4 -> c = 0.2125 ; k=5 -> c = 0.1700 ; k=3 -> c = 0.2833
```

**Notlar:**
- `a_i = 1` alınırsa formül **saf Rasch/1PL**'e indirgenir; §4.3'teki `a_i` dağılımı bunun
  üzerine kasıtlı kirlilik ekler.
- `a_i < 0` maddelerde formül **aynen** uygulanır; işaret ters etkiyi kendiliğinden üretir.
- `c_i`'deki `0.85` çarpanı: öğrenciler tamamen rastgele işaretlemez, en az bir şıkkı eler
  → saf şanstan biraz düşük taban.
- **`k_i` (şık sayısı) dağılımı:** 4 şık **%78** · 5 şık **%19** · 3 şık **%3**.
- **`phi_u(sinav)` sınav başına bir kez** çekilir ve o sınavın tüm maddelerinde sabit kalır —
  "o gün kötüydü" etkisi. Bu, sınav düzeyinde korelasyon üretir ve `exam_result.mark`
  dağılımının gerçekçi dalgalanmasını sağlar; aksi halde notlar fazla düzgün olurdu.
- **`exam_result.mark` üretimi:** `mark = clip(round(100 * (kazanılan puan / 100)), 0, 100)`,
  yani sorunun `points` değerleriyle ağırlıklı doğruluk. `text` sorularda puan
  `clip(round(points * (0.42 + 0.30 * theta_ui + N(0, 0.12))), 0, points)`.

### 4.5 Çeldirici desenleri

Doğru cevap verilmediğinde ve soru boş bırakılmadığında, yanlış şık şöyle seçilir:

1. Her madde için bir şık **"kavram yanılgısı çeldiricisi"** olarak işaretlenir (`m`).
   Bu, `_seed_manifest.json`'da `misconception_choice` alanında tutulur.
2. `m`'nin seçilme ağırlığı `w_m`; kalan `k − 2` çeldiricinin her birinin ağırlığı
   `(1 − w_m) / (k − 2)`.

| `w_m` | Pay | Anlamı | T1'de üreteceği çıktı |
|---|---|---|---|
| **0,34** | **%45** | nötr — çeldiriciler eşit çekiyor | normal dağılım |
| **0,50** | **%40** | belirgin yanılgı | "%25 öğrenci C'yi seçti" |
| **0,72** | **%15** | **güçlü sistematik yanılgı** | **"sınıfın %41'i B çeldiricisine gitti"** |

**Yoğunlaştırma kuralı:** `w_m = 0.72` bandındaki **996 maddenin %40'ı zor bantta**
(`b_i > 0.65`) toplanır. Böylece doğru cevap oranı düşerken çeldirici yükselir ve
**çeldirici doğru cevaptan fazla seçilir**. Beklenen: **≈ 180 maddede çeldirici > doğru**.

**Türkçe kavram yanılgısı havuzu (soru metni üretiminde konuya göre kullanılır):**

| Konu | Doğru | Çekici çeldirici (yanılgı) |
|---|---|---|
| Üslü ve Köklü İfadeler | `(a·b)ⁿ = aⁿ·bⁿ` | `(a+b)ⁿ = aⁿ + bⁿ` |
| Mutlak Değer | `|x−3| = 5 → x ∈ {8, −2}` | `x = 8` (tek kök) |
| Fonksiyon Kavramı | bileşke sırası `f∘g` | `g∘f` ile karıştırma |
| İkinci Dereceden Denklemler | `Δ < 0` → reel kök yok | "iki kök vardır" |
| Trigonometri | `sin²x + cos²x = 1` | `sin x + cos x = 1` |
| Newton'ın Hareket Yasaları | etki-tepki **farklı** cisimlere etkir | "aynı cisme etkir, dengelenir" |
| Tork ve Denge | tork = kuvvet × **dik** uzaklık | "kuvvet × uzaklık" (açı yok sayılır) |
| Hücre Bölünmeleri (Mitoz) | kromozom sayısı **korunur** | "yarıya iner" |
| Fotosentez | ışıktan bağımsız evre ışığa ihtiyaç duymaz | "yalnız karanlıkta olur" |
| Kalıtım | çekinik fenotip yalnız `aa`'da | "`Aa` da çekinik görünür" |
| Yazım Kuralları ve Noktalama | "ve"den önce virgül konmaz | "her bağlaçtan önce virgül" |
| Şiir | redif ile kafiye farkı | "ikisi aynı şeydir" |
| Present Perfect (İngilizce) | `since` + zaman **noktası** | `since` + süre |
| Türkiye'de Sanayi | sanayinin yoğunlaştığı bölge Marmara | "İç Anadolu" |

### 4.6 Boş bırakma (omission) modeli

`exam_answer` **satırının yokluğu** boş bırakmadır (L3). Satır **yazılmaz.**

```
P(bos | u,i) = clip( omega_u * sigmoid(1.40 * (b_i - theta_ui)) * tau , 0.01 , 0.58 )

omega_u : arketip bos birakma egilimi (§3.4-3.11'de her arketipte verildi)
tau     : zaman baskisi carpani
        = 1.00   -> async / open mod
        = 1.00   -> sync, sorunun ilk %80'i
        = 1.55   -> sync, son %20 soru (sure bitiyor)
```

**Hedef genel boş bırakma oranı: %12,5** (envanterin %10–30 bandının alt ucu; `ω_u`
değerleri bu hedefe kalibre edilmiştir).

| Arketip | A1 | A2 | A3 | A4 | A5 | A6 (önce→sonra) | A7 | A8 |
|---|---|---|---|---|---|---|---|---|
| Beklenen boş oranı | %4,2 | %11,8 | %13,0 (boşluk konularında **%28**) | %16,5 | %11,5 | %12,0 → %21,0 | **%25,4** | %13,2 |

**Ek kural — sıralı terk:** `sync` sınavların **%6'sında** öğrenci sınavı yarıda bırakır
(§6 #3). Bu durumda **belirli bir soru indeksinden sonrasının tamamı** boştur — rastgele
dağılmış boşluk değil. T1'in "boş bırakma oranı" metriğinin bu iki deseni ayırt edememesi
(L3 uyarısı) bilinçli olarak veriye gömülür.

### 4.7 Metin (`text`) soruları

- Tüm maddelerin **%15'i** `kind = 'text'`. `correct = NONE`, `choices = NONE`.
- `exam_answer.selected = NONE`, `exam_answer.text` doludur (E: `kind='choice'` soruda
  `text` **yazılmaz**, `kind='text'` soruda `selected` **yazılmaz**).
- Cevap uzunluğu: `LogN(medyan 165 karakter, σ_log 0.62)`, kırpma `[15, 1200]`.
  Arketip çarpanı: A1 ×1,7 · A7 ×0,5 · A6 (kırılma sonrası) ×0,4 · diğerleri ×1,0.
- **Boş bırakma oranı %18** (çoktan seçmeliden yüksek — yazmak maliyetli).
- **Doğruluk tutulmaz.** Not insan tarafından girilir (`exam_result.mark`); madde düzeyinde
  hiçbir doğruluk işareti yazılmaz.
- **Ayrı davranış zorunluluğu:** Ö1, Ö2, T1, T2 hesaplarının **paydasına girmezler**.
  §7'deki tüm "doğruluk" ölçümlerinin paydası daima `kind = 'choice'` ile sınırlıdır.
- `answer_image`: metin cevaplarının **%6'sında** çizim eklenmiş (**800 satır**) —
  Faz 3 sinyali; bugün kullanılmaz.

### 4.8 Soru bankası ve köken bağı

- **`bank_question` = 900 şablon.** Sahiplik `LogNormal` ile 24 öğretmene dağıtılır
  (medyan 28 · en çok yazan 112 · en az 4).
- `visibility`: **`school` %38** · `private` %62.
- `bank_question.subject`: %94 dolu, **%6 `NONE`** (54 satır — konu silinmiş, cascade
  `SET subject = NONE`).
- **`exam_question.from_bank` soruların %45'inde dolu** (≈ 2.988 soru).
  Kullanılan 612 şablonun kullanım dağılımı:

| Kaç sınavda | Şablon | Doğan soru |
|---|---|---|
| 1 | 337 (%55) | 337 |
| 2 | 153 (%25) | 306 |
| 3 | 80 (%13) | 240 |
| 4 | 31 (%5) | 124 |
| 5–6 | 11 (%2) | 61 |
| *(çoklu seviye kullanımı ile şişer)* | | **≈ 2.988** |

  4–6 sınavda kullanılan bir şablon **madde başına 190–420 cevap** demektir → T2'nin
  `n ≥ 30` kapısını bolca aşar ve **çapraz-sınav birleştirmesinin**
  (`from_bank ∪ banked_as`) doğru çalıştığını kanıtlar.
- **`banked_as`:** soruların **%6'sında** dolu (öğretmen sınavda yazdığı soruyu bankaya
  kaydetti). Bu şablonlarda `bank_question.source_exam` de doludur (398 şablon).
- **Iraksama:** `from_bank` dolu soruların **%12'sinde (359 soru)** `text` alanı şablondan
  **farklıdır**. `_seed_manifest.json` bunları işaretler → T2'nin "kopyalar farklılaşmış"
  uyarısının hedefi.
- **Kopuk köken bağı (L9):** seed sonunda **15 `bank_question` silinir**; bunlara işaret
  eden **48 `exam_question.from_bank`** alanı `NONE` olur.

### 4.9 İkinci deneme (`seq`)

- `max_attempts = 2` olan sınavlar: geçmiş 240 sınavın **%18'i = 43 sınav**.
- Bu sınavlara giren öğrencilerin **%21'i ikinci oturum yapar** →
  **564 `exam_attempt` (`seq = 2`)**, **≈ 9.870 `exam_answer` (`seq = 2`)**,
  **564 `exam_result` (`seq = 2`)**.
- **Kayıt id kuralı (E3):** `seq = 1` kayıtlarının id'si `{exam}_{user}` (ek yok);
  `seq = 2` kayıtlarının id'si `{exam}_{user}_2`. `seq` sütununa her iki durumda da
  doğru değer yazılır.
- İkinci oturumda yetenek `theta_ui + 0.45` (çalışıp geldi). **Aynı sorular** sorulur.
- Beklenen: **ilk denemede yanlış / ikincide doğru madde ≈ 2.960** → Ö2'nin "ilerleme"
  bölümünü besler.
- İkinci deneme yapanların arketip dağılımı: **A8 %34 · A5 %28 · A3 %22 · A2 %14 ·
  diğer %2**. **A7 hiç ikinci deneme yapmaz.**

---

## 5. Diğer gerçekçilik kuralları

### 5.1 Yoklama deseni

```
P(absent) = p_abs(u) * M_gun * M_sinav * M_tatil * M_mevsim * M_arketip
```

| Çarpan | Değer |
|---|---|
| `M_gun` | **Pzt 1,35** · Sal 0,90 · **Çar 0,85** · Per 0,95 · **Cum 1,30** |
| `M_sinav` | O gün o şubede sınav varsa **0,55** |
| `M_tatil` | Tatilden önceki son iş günü **1,60** · tatilden sonraki ilk iş günü **1,45** · diğer 1,00 |
| `M_mevsim` | Aralık–Şubat **1,20** · Eylül–Kasım 0,95 · Mart–Nisan 1,05 |
| `M_arketip` | A4: Pzt ek **×1,8** · A7: Pzt ek **×1,55**, Cum ek **×1,50** · diğerleri 1,00 |

**Statü kuralı (`settings.attendance_statuses` = present/absent/late/excused):**
- Devamsız sayıldıysa: `absent` / `excused` payı arketipe göre (§3.4–3.11 tabloları).
  Okul geneli: `absent` **%78**, `excused` **%22**.
- Devamsız değilse: `late` olasılığı `p_late(u) × M_gun` (Pzt ×1,8, günün 1. bloğu ×2,2);
  kalan **`present`**.

**Grip dalgası (bilinçli kolektif olay):** **2025-12-15 … 2025-12-19** haftasında tüm okul
için `M_mevsim = 2,40`. Bu, T4'ün "devamsızlık artışı" kuralının **sınıf geneli bir olayla**
karşılaştığında ne yaptığını test eder — ideal olarak bireysel uyarı üretmemelidir.

**Beklenen okul geneli dağılım:** `present` **%84,1** · `absent` **%9,0** ·
`late` **%4,6** · `excused` **%2,3**.
Devam oranı `(present + late) / (present + absent + late)` = **%93,5**
(`excused` ne paya ne paydaya girer — `web/attendance.rs:69-72`).

### 5.2 Ödev teslim zamanı dağılımı

`Δ = due_at − submitted_at` (saat; **pozitif = erken**).

| Bileşen | Dağılım | A1 | A2 | A3 | A4 | A5 (T1→T2) | A6 (önce→sonra) | A7 | A8 |
|---|---|---|---|---|---|---|---|---|---|
| **Son 24 saat** | `Exp(ort. 7 sa)`, kırpma `[0, 24]` | %10 | %46 | %48 | **%52** | %50→%38 | %44→%36 | %40 | %44 |
| **1–7 gün** | `LogN(medyan 52 sa)`, `[24, 168]` | %30 | %27 | %26 | %10 | %26→%34 | %30→%12 | %12 | %31 |
| **Erken (>7 gün)** | `U(168, 480)` | **%58** | %15 | %13 | %1 | %6→%22 | %14→%2 | %2 | %14 |
| **Geç** (Δ negatif) | `Exp(ort. 26 sa)`, `[0, 240]` | %2 | %12 | %13 | **%37** | %18→%6 | %12→**%50** | **%46** | %11 |

- **Okul geneli "son 24 saate yığılma" = %44,8** — istenen desen.
- `submitted_at` **READONLY**, ilk teslimde donar.
  `counted_on_time = (submitted_at ≤ due_at)`, ilk teslimde dondurulur.
- **`updated_at` ayrışması:** teslimlerin **%22'sinde** öğrenci sonradan dosya ekler →
  `updated_at = submitted_at + Exp(ort. 9 sa)`. Bunların **%13'ünde** `updated_at > due_at`
  olur → **`counted_on_time = true` ama türetilmiş `late = true`** (L14 tutarsızlığının
  kontrollü örneği, **≈ 750 satır**). Ö4 ve V1'in `counted_on_time` kullanması gerektiğini
  bu satırlar kanıtlar.
- `homework_result.status` (E8): **`done` %88 · `incomplete` %7 · `missing` %5.**
- `homework_result.mark`: `clip(round(58 + 21 * theta_ui + N(0, 7)), 0, 100)`.
  `status = 'missing'` satırlarda `mark = NONE`.
- **Hiç teslim edilmemiş ödev için `homework_submission` satırı YAZILMAZ.** "Eksik" bunun
  türevidir. (Öğretmenin `missing` olarak notladığı durumlar ayrıca `homework_result`
  satırı üretir — 5%.)
- **Dosya:** teslimlerin %26'sında `homework_file`, ortalama 1,4 dosya
  (üst sınır `MAX_HOMEWORK_FILES_PER_SUBMISSION = 10`).

### 5.3 Pomodoro deseni

```
lambda_u(gun) = base_u * W_gun * E_sinav * H_tatil
E_sinav       = 1 + 1.90 * exp(-gun_sayisi_sonraki_sinava / 2.5)
```

| Çarpan | Değer |
|---|---|
| `W_gun` | Pzt 1,00 · Sal 1,05 · Çar 1,00 · Per 1,10 · **Cum 0,65** · Cmt 0,85 · **Paz 1,25** |
| `H_tatil` | Yarıyıl tatili **0,28** · Nisan/Kasım ara tatili **0,45** · resmi tatil 0,55 · diğer 1,00 |
| `E_sinav` (A4) | üs katsayısı ×1,8 → `1 + 3.42 * exp(...)` — sınav öncesi yığılma belirgin |

- Günlük stint sayısı `Poisson(lambda_u(gun))`, üst sınır **18**.
- Süre: arketipte verilen `LogN(medyan, σ_log)`, kırpma **`[3, 55]` dakika**.
- **`counted` kuralı (koddan):** `counted = (sure >= 300.000 ms) AND (o UTC gununde
  sayilan < 16)` — `MIN_COUNTED_POMODORO_MS = 300000`, `MAX_COUNTED_POMODORO_PER_DAY = 16`.
  Beklenen `counted = true` oranı: **%81,4**.
- **`finished_at = NONE`** (terk edilmiş oturum): stintlerin **%6'sı** (≈ 1.560).
  E15 gereği kullanıcı başına **en fazla 1** açık kayıt `open_{user_key}` id'siyle durur;
  kalan terk edilmiş stintler kapatılmış ama `finished_at` yazılmamış olarak **üretilmez** —
  bunun yerine %6'nın tamamı geçmişte kalan, `finished_at = NONE` ULID kayıtlarıdır ve
  yalnız **8 kullanıcıda** `open_{user}` id'li canlı kayıt bırakılır.
- **Başlangıç saati (TR) karma dağılımı:** 07:00–08:30 **%5** · 12:30–13:30 **%6** ·
  **16:00–19:00 %40** · **20:00–23:30 %41** · **00:00–02:30 %8**.
  Depolama UTC olduğundan 00:00–02:30 TR = **21:00–23:30 UTC (önceki gün)** → Ö3'ün
  uyardığı streak kayması veride **gerçekten** vardır.
- **Sayaç alanları:** `study_streak_current` / `study_streak_longest` /
  `study_streak_last_day` ve `pomodoro_counted_day` / `pomodoro_counted_today` ham log'dan
  **UTC gününe göre** tutarlı hesaplanır. **E2:** `study_streak_last_day` ve
  `pomodoro_counted_day` **gün numarasıdır** (`floor(ms / 86400000) + 719163`), ms değil.
- **Kasıtlı sayaç hatası:** `user.pomodoro_finished_total` **%8 şişirilir** (envanterdeki
  D3 backfill hatasının simülasyonu) → Ö3'ün "ham log'u oku, sayacı okuma" kuralı test edilir.
- **Kasıtlı eksik sayaç:** `user.lessons_attended_total` ve `user.high_mark_total`
  **hiç yazılmaz** (`NONE`) — kısmi backfill durumunun aynısı.
  **Rozet tutarlılığı (E13):** bu iki sayaç `NONE` olduğu için `lessons_attended_*` ve
  `high_mark_*` rozetleri de **verilmez** (6 rozet kodu kullanılmaz).

### 5.4 Sohbet (chatbot) mesajları

Asistan **kural tabanlıdır ve ders içeriğini bilmez.** Mesajlar buna uygun olmalıdır.

**Kullanıcı mesajı havuzu — sistem kullanımı (%78):**

```
ödevimi nasıl teslim ederim
teslim ettiğim ödevi sonradan değiştirebilir miyim
ödevi geç teslim edersem ne olur
sınav sonucum ne zaman açıklanır
sınavda geri dönüp cevabımı değiştirebilir miyim
sınava girdim ama internetim gitti, tekrar girebilir miyim
sınavı iki kez yapabilir miyim
devamsızlığımı nereden görebilirim
yoklamam yanlış girilmiş, kime yazmalıyım
pomodoro sayacım neden sayılmadı
günde kaç pomodoro sayılıyor
şifremi nasıl değiştiririm
profil fotoğrafımı nasıl değiştiririm
veli hesabım nasıl bağlanır
soru havuzuna nasıl soru sorarım
sorduğum soru neden onaylanmadı
yemek rezervasyonumu nasıl iptal ederim
öğretmenimden nasıl randevu alırım
randevum onaylandı mı
notlarım nerede görünüyor
ders notlarına nereden ulaşırım
tahtaya nasıl katılırım
mesaj kutumdaki mesajı nasıl arşivlerim
rozetleri nasıl kazanıyorum
etkinliğe nasıl kaydolurum
```

**Ders içeriği mesajları (%22) — asistan cevaplayamaz, kaçınma/yönlendirme yanıtı üretir:**

```
türev nasıl alınır
mitoz ve mayoz farkı nedir
present perfect ne zaman kullanılır
ikinci dereceden denklem çözümünü anlatır mısın
tork formülü neydi
fotosentez denklemini yazar mısın
bu soruyu çözemiyorum yardım eder misin
matematik sınavına nasıl çalışmalıyım
```

| Parametre | Değer |
|---|---|
| `chatbot_thread` | **1.500** (155 öğrenci × 9 + 19 öğretmen × 4) |
| `chatbot_message` | **9.000**; thread başına tur sayısı `1 + Poisson(2.1)`, her tur 1 `user` + 1 `assistant` |
| `thread.title` | ilk kullanıcı mesajının ilk 40 karakteri (%82) veya `NONE` (%18) |
| `assistant.status` (E: pending/complete/failed) | **`complete` %92,4 · `failed` %4,6 · `pending` %3,0** |
| `error_code` (`failed` içinde) | `ai_unavailable` %55 · `timeout` %30 · `module_disabled` %8 · `rate_limited` %7 |
| `truncated = true` | mesajların %3'ü |
| Yanıt gecikmesi (`completed_at − created_at`) | `LogN(medyan 1.400 ms, σ_log 0.60)`, kırpma `[250, 25.000]` |
| `pending` mesajlar | `completed_at = NONE`; yalnız son 24 saatte açılmış thread'lerde |
| `content` uzunluk sınırı | `max_chatbot_message_len = 4000` (§1.6) aşılmaz |
| Thread sınırı | `max_chatbot_threads = 20` — hiçbir kullanıcı aşmaz |

- **A8 için zorunlu kural:** 18 öğrencinin **11'inde son 14 günde `≥ 3 failed`** mesaj
  olacak biçimde hata zamanlaması kaydırılır → T5(c) tetikleyicisi veride gerçekten bulunur.
- **Kullanım payı:** 250 öğrencinin **155'i** (%62) kullanmış, **95'i hiç kullanmamış**
  (`chatbot_thread_count = 0` veya `NONE`; `chatbot_thread` satırı yok).
- Mevsimsellik: yarıyıl tatilinde hacim **×0,35**.

### 5.5 Yemek, ödeme, randevu

**Yemek (E5–E7, E9):**
- `menu.slot` ∈ `breakfast` / `lunch` / `snack`; `menu.date` tam 10 karakter `YYYY-MM-DD`.
- `meal_booking` **11.800**: `lunch` günlük ortalama **75 öğrenci** (250'nin %30'u —
  yemekhane isteğe bağlı), `snack` günlük ortalama **22**.
  `status`: **`booked` %89 · `cancelled` %11**. `attempt` alanı %6'da `2`
  (iptal sonrası yeniden rezerve). `price_minor` = o menünün yemek fiyatları toplamı.
- `meal_attendance` **11.100**: `status` ∈ **`served` %91 · `missed` %9**.
- `meal_ledger` **12.400**: `charge` 11.800 · `credit` 580 (aylık veli ödemesi) ·
  `reversal` 20 (iptal iadesi). READONLY, append-only.
- `dietary_profile` **55** (öğrencilerin %22'si); `tags` varsayılan listeden, profil başına
  1–3 etiket (üst sınır 10).
- **Bu veri modele girmez (K2–K4).** Üretilmesinin tek sebebi: **etik kapının kod düzeyinde
  test edilebilmesi** — olmayan veriyi engellemek bir test değildir.

**Ödeme:**
- Taksit vadeleri: her ayın 10'u, **2025-09-10 → 2026-06-10**.
- `payment_ledger`: `charge` vade gününde yazılır (**2.250**); `credit` (tahsilat)
  vade `± Exp(ort. 4 gün)` — **%89'u zamanında/erken, %11'i gecikmiş** (medyan gecikme
  12 gün); **20 `refund`**.
- `method`: `havale` %52 · `kredi_karti` %38 · `nakit` %10.
- Tüm tutarlar kuruş ve `≤ 10.000.000` (E18).

**Randevu:**
- `appointment_slot` **800**: 15 öğretmen × Salı/Perşembe 15:30 ve 16:00, 20 dk,
  `occupied` cap 1. 27 geçmiş + 9 gelecek hafta. `series` %64'ünde dolu (ULID metni).
- `appointment` **520**: `reason` Türkçe, **konu etiketsiz** (envanterin 1.3(2) gözlemi).
  Örnekler: *"Matematik dersinde son konularda zorlanıyorum, birlikte bakabilir miyiz?"* ·
  *"Oğlumun devamsızlığı hakkında görüşmek istiyorum."* · *"Sınav sonucumu değerlendirmek
  için randevu almak istiyorum."* (`MAX_APPOINTMENT_REASON_LEN = 1000` aşılmaz)
- `status`: `approved` %58 · `pending` %17 · `rejected` %9 · `cancelled` %16.
- **`pending` olanların %51'i (45 randevu) 3 günden eskidir** → **T5(a) tetikleyicisi.**
- `proposed_starts_at`/`proposed_ends_at`/`proposed_by` %14'ünde dolu;
  `reject_reason` her `rejected` satırda; `cancel_reason` `cancelled`'ların %72'sinde.
- `requester`: öğrenci %61 · veli %39. **Veli yalnız bağlı olduğu öğrenci için talep açar.**

### 5.6 Havuz soruları ve çözümler

- `pool_question` **640**: `status` ∈ **`approved` %78 (499) · `pending` %22 (141)** (E11).
- `asker` arketip dağılımı: A2 %26 · **A8 %21** · A3 %18 · A5 %14 · A4 %10 · A1 %6 ·
  A6 %4 · A7 %1.
- `title` kısa Türkçe (≤200), `body` 80–600 karakter (≤10.000).
  **Konu etiketi yoktur** (Ş6 eksikliği veride görünür kalmalı) — ancak
  `_seed_manifest.json` her sorunun **gerçek konusunu** tutar, böylece Ö5'in Ş6 sonrası
  ne kadar iyi çalışacağı ölçülebilir.
- `solution` **780**: `approved` soruların **%64'ünde (319 soru)** en az 1 çözüm var
  (çözümlü soru başına ortalama 2,44). Yazar: **öğretmen %41 · öğrenci %59** (A1 ağırlıklı).
- **Çözümsüz kalan ve 7 günden eski `approved` soru: 180** — bunların **47'si A8
  öğrencilerine ait** → **T5(b) tetikleyicisi.**
- `image_file` %12'sinde dolu.
- `pool_approved_total` / `pool_published_total` sayaçları ve ilgili rozetler tutarlı yazılır.

### 5.7 Tahta, not, mesaj, ders notu

**`board` 280 · `board_stroke` 9.000:**
- 192 öğretmen tahtası (ders anlatımı) + 88 öğrenci tahtası.
- `participants` uzunluğu: 1 (%22) · 2–3 (%36) · 4–8 (%28) · 9–25 (%14).
- 12 tahtada `closed_at` dolu · 8 tahtada `locked = true` (+ `locked_by`, `locked_at`) ·
  **3 tahtada `epoch = 2`** (iki kez temizlenmiş).
- `board_stroke.kind` ∈ **`stroke` %97 · `clear` %3** (E10 — başka değer yoktur).
  `clear` satırları `count = NONE`, `payload = NONE`; `epoch` artışının işaretçisidir.
- `payload` ≤ **4096** karakter sahte SVG path verisi — **semantik yok** (D6 uyarısı bilinçli).
- Vuruşlar ders saatlerinde yoğunlaşır; yarıyıl tatilinde ×0,15.
- `epoch_stroke_count` ve `total_stroke_count` sayaçları gerçek satır sayısıyla tutarlı.

**`note` 1.530 · `note_file` 420:**
- 138 öğrenci (%55) × 9 + 24 öğretmen × 12.
- `title` Türkçe ders/konu adlarından türetilir (≤200); `content` 100–3.000 karakter
  (üst sınır 10.000). **`updated_at` alanı şemada yoktur** (D11 uyarısı) — oluşturma anı
  ULID'den okunur. `file_count` gerçek dosya sayısıyla tutarlı (üst sınır 10).

**`message` 6.800:**
- Yön dağılımı: öğrenci→öğretmen **%38** · öğretmen→öğrenci **%24** · veli→öğretmen **%19** ·
  öğretmen→veli **%11** · yönetim→herkes **%8**.
- **ROL KISITI (zorunlu):** öğrenci ve veli **yalnız öğretmen+ kullanıcılara** yazabilir
  (`domain/role.rs:69-79`). Öğrenci→öğrenci, öğrenci→veli, veli→veli **tek satır bile
  üretilmez**.
- `sender_folder`: `sent` %86 · `archive` %10 · `trash` %4 (E12).
  `recipient_folder`: `inbox` %78 · `archive` %16 · `trash` %6.
  `sender_origin` / `recipient_origin`: ev klasöründeyken **`NONE`**, taşınmışsa önceki klasör.
- `read = true` **%66**. **`read_at` alanı yoktur** (D12 uyarısı) — okuma anı ölçülemez.
- `subject` ≤200, `body` ≤10.000, `label` %12'sinde dolu (≤50).

**`course_note` 360 · `course_note_file` 260 · `rag_output` 360:**
- 40 çekirdek ders × 9 not; `author` dersin öğretmeni.
- `rag_output.payload` **FLEXIBLE object** — sahte indeksleme meta verisi
  (`{chunks: n, model: "...", indexed_at_ms: ...}`).

### 5.8 Mevsimsellik özeti (tek tablo)

| Pencere | `course_session` | `homework` | `exam` | `pomodoro` | `chatbot` | `board_stroke` | `meal` | `message` |
|---|---|---|---|---|---|---|---|---|
| Normal öğretim haftası | 154/hafta | 2/ders/ay | takvim | ×1,00 | ×1,00 | ×1,00 | ×1,00 | ×1,00 |
| Kasım ara tatili (1 hafta) | **0** | **0** | **0** | ×0,45 | ×0,55 | ×0,20 | **0** | ×0,60 |
| **Yarıyıl tatili (2 hafta)** | **0** | **0** | **0** | **×0,28** | **×0,35** | **×0,15** | **0** | **×0,40** |
| Nisan ara tatili (1 hafta) | **0** | **0** | **0** | ×0,45 | ×0,55 | ×0,20 | **0** | ×0,60 |
| Resmi tatil (tek gün) | **0** | **0** | **0** | ×0,55 | ×0,70 | ×0,25 | **0** | ×0,70 |
| Sınav haftası | ×1,00 | ×0,60 | — | **×2,40** | ×1,30 | ×1,10 | ×1,00 | ×1,20 |
| Grip dalgası (2025-12-15…19) | ×1,00 | ×1,00 | ×1,00 | ×0,75 | ×1,00 | ×0,80 | ×0,70 | ×1,30 |

---

## 6. Kenar durumlar

Her madde **kesin sayı** ve **test ettiği ürün** ile verilmiştir. Bunlar 250 öğrencinin
*üzerine* işaretlenen bayraklardır; ayrı arketip değildir. Üretici bunları
`_seed_manifest.json → students[].edge_flags` alanında tutar.

| # | Durum | Sayı | Nasıl üretilir | Test ettiği |
|---|---|---|---|---|
| 1 | **Dönem ortası kayıt (yeni gelen)** | **6 öğrenci** | Kayıt: 2026-02-16, 2026-02-23, 2026-03-02, 2026-03-09 (×2), 2026-03-23. Bu tarihten **önce hiçbir tabloda satırı yok** (T1 verisi sıfır). `class_member.added_at` = kayıt tarihi. | **T4 soğuk başlangıç kapısı** (<4 hafta veri → uyarı üretmemeli), Ö1 `n<8` kapısı |
| 2 | **Ayrılan öğrenci** | **4 öğrenci** | Son aktivite: 2025-11-21, 2025-12-19, 2026-01-16, 2026-02-27. Sonrasında hiç satır yok; `user` ve `class_member` **silinmez**. | T4'ün "son görülme" (D19) vekili, V1'in boş özet davranışı |
| 3 | **Sınavı yarıda bırakan** | **31 `exam_attempt`** | `finished_at = NONE`, `left_at = started_at + U(4, 22) dk`. Cevapların yalnız **ilk %35'i** yazılır. `exam_result` yazılır, `mark` düşük. | L7 oturum zinciri, T1'in boş bırakma yorumu |
| 4 | **İkinci deneme (`seq = 2`)** | **564 attempt / 9.870 cevap / 564 sonuç** | §4.9; kayıt id kuralı E3 | Ö2 "ilerleme" bölümü, T2'nin `seq` bazlı üst/alt %27 gruplaması |
| 5 | **Hiç sohbet kullanmayan** | **95 öğrenci** | `chatbot_thread_count = 0`; `chatbot_thread` satırı yok. | Ö5/T5'in sinyalsiz **gizlenme** davranışı |
| 6 | **Velisi olmayan** | **20 öğrenci** | `parent_link` satırı yok. | **V1'in hiç üretilmemesi** gereken durum |
| 7 | **Soğuk başlangıç (çok düşük hacim)** | **8 öğrenci** | `< 40` toplam `exam_answer`, `≤ 2` ödev teslimi, `0` pomodoro, `0` sohbet. 6'sı #1 ile örtüşür, 2'si dönem başından beri kayıtlı ama pasif. | **Tüm ürünlerin soğuk başlangıç kapıları** |
| 8 | **Tüm soruları boş bırakan** | **9 `exam_attempt` (4 öğrenci)** | `exam_attempt` var, `finished_at` dolu, **`exam_answer` satırı sıfır**, `exam_result.mark = 0`. | Sıfıra bölme koruması; T1'de boş oranı %100 |
| 9 | **Bir derste hiç ödev teslim etmeyen** | **3 öğrenci × 1 ders** | O dersin 12 geçmiş ödevinin hiçbirinde `homework_submission` yok. | Ö4 ve V1'in "eksik" sayımı |
| 10 | **`grade` tutarsızlığı** | **1 şube** | 12-A → `"12. Sınıf"`; diğerleri `"9"/"10"/"11"/"12"`. 12-A blueprint kullanamaz. | **Y1** seviye tutarlılığı uyarısı (L23) |
| 11 | **Hiç ölçülmemiş konu** | **22 `subject`** | `exam_question_count = 0` **ve** `homework_count = 0`. | **Y1** kapsama listesi |
| 12 | **Notlandırılmamış sınav** | **26 `exam`** | `ends_at < T_NOW` ama `exam_result` yok; `result_count = 0`. Son 3 haftadakiler. | Y1; T1'in "notlandırılmadı" durumu |
| 13 | **Cevap anahtarı sonradan düzeltilen** | **5 soru** | Seed sonunda `exam_question.correct` değiştirilir; eski değer **yalnız manifest'te**. | **L2 uyarısı** — "geçmiş istatistik sessizce değişir" |
| 14 | **Silinen banka şablonu** | **15 şablon / 48 soru** | Seed sonunda silinir; `from_bank` alanları `NONE` olur. | **L9** köken bağının kopması, T2 |
| 15 | **Kapatılmış / kilitli / temizlenmiş tahta** | **12 · 8 · 3** | §5.7 | D5 `epoch` mantığı |
| 16 | **Günde 16'dan fazla pomodoro** | **3 öğrenci × 2 gün** | 18–20 stint; 16'dan sonrakiler `counted = false`. | `MAX_COUNTED_POMODORO_PER_DAY`, Ö3 şeffaflık kuralı |
| 17 | **Dönem ortası öğretmen değişimi** | **2 `course`** | 2026-02-09'da `course.teachers` değişir; geçmiş oturumlar eski öğretmeni gösterir. | T3'ün `can_manage_course` kapsamı |
| 18 | **%100 metin sorulu sınav** | **4 `exam`** | Tüm soruları `kind = 'text'`; doğruluk hesaplanamaz. | Ö1/Ö2/T1/T2'nin `kind='choice'` filtresi |
| 19 | **Ortak yürütülen ders** | **6 `course`** | `teachers` dizisi 2 elemanlı. | Çoklu öğretmen yetkisi |
| 20 | **Yoklaması hiç girilmemiş oturum** | **399 oturum (%9)** | `session_attendance` satırı yok. | Devam oranı paydası; "veri yok" ≠ "devamsız" |
| 21 | **Aynı gün 2 sınav** | **18 (gün × şube)** | Sınav takvimi kısıtının üst sınırı. | Yoklamada `M_sinav` çarpanının etkisi |
| 22 | **Konusuz banka sorusu** | **54 `bank_question`** | `subject = NONE`. | T2 ve Y1'in `NONE` konu davranışı |
| 23 | **`due_at` ileri alınmış ödev** | **34 `homework` (%7)** | §2.6 | Ö4'ün `counted_on_time` tercihi |
| 24 | **Terk edilmiş pomodoro** | **1.560 (%6)** | `finished_at = NONE`; yalnız 8'i `open_{user}` id'li canlı kayıt. | Ö3'ün `NONE` süre güvenliği |
| 25 | **Yanıtı gelmemiş sohbet mesajı** | **270 (%3)** | `status = 'pending'`, `completed_at = NONE`. | D8 / D9 |
| 26 | **Açık mesai kaydı** | **4 personel** | `check_out = NONE`, id `open_{user_key}` (E15). | `work_entry` açık/kapalı id ayrımı |
| 27 | **Kapasitesi dolan etkinlik** | **5 `event`** | `audience.kind = 'registration'`, `registration_count = capacity`. | Kapasite claim yolu |

---

## 7. Doğrulanabilirlik — beklenen değerler

Üretim bittikten sonra aşağıdaki ölçümler çalıştırılır. **Tolerans sütunundaki bandın
dışına çıkan her satır, üreticide hata olduğunun kanıtıdır.** Bu bölüm doğrulama ajanının
doğrudan girdisidir; makine okunur kopyası `_seed_manifest.json → expected` altındadır.

### 7.1 Hacim kontrolleri

| # | Ölçüm | Beklenen | Tolerans |
|---|---|---|---|
| H1 | `count(user)` | **563** | kesin |
| H2 | `count(user WHERE role='student')` | **250** | kesin |
| H3 | `count(user WHERE role='teacher')` | **24** | kesin |
| H4 | `count(user WHERE role='parent')` | **285** | kesin |
| H5 | `count(parent_link)` | **299** | kesin |
| H6 | Velisi olmayan öğrenci | **20** | kesin |
| H7 | `count(course)` | **50** | kesin |
| H8 | `count(subject)` | **390** | kesin |
| H9 | `count(class_group)` | **11** | kesin |
| H10 | `count(class_member)` | **250** | kesin |
| H11 | `count(class_course)` | **110** | kesin |
| H12 | `count(enrollment)` | **2.790** | ±2 |
| H13 | `count(course_session)` | **4.428** | ±%3 |
| H14 | `count(session_attendance)` | **98.400** | ±%4 |
| H15 | `count(exam)` | **340** | kesin |
| H16 | `count(exam_question)` | **6.640** | ±%2 |
| H17 | `count(exam_attempt)` | **14.800** | ±%3 |
| H18 | **`count(exam_answer)`** | **259.000** | **±%5** |
| H19 | `count(exam_result)` | **13.600** | ±%3 |
| H20 | `count(bank_question)` | **885** (900 − 15 silinen) | kesin |
| H21 | `count(homework)` | **590** | kesin |
| H22 | `count(homework_submission)` | **26.200** | ±%4 |
| H23 | `count(homework_result)` | **23.000** | ±%4 |
| H24 | `count(pomodoro_session)` | **26.000** | ±%5 |
| H25 | `count(chatbot_thread)` | **1.500** | ±%4 |
| H26 | `count(chatbot_message)` | **9.000** | ±%5 |
| H27 | `count(pool_question)` | **640** | ±%3 |
| H28 | `count(solution)` | **780** | ±%4 |
| H29 | `count(appointment)` | **520** | ±%4 |
| H30 | `count(message)` | **6.800** | ±%5 |
| H31 | `count(board_stroke)` | **9.000** | ±%5 |
| H32 | `count(meal_booking)` | **11.800** | ±%5 |
| H33 | `count(payment_ledger)` | **4.400** | ±%3 |
| H34 | Okul DB'sindeki **tablo sayısı** | **60** | kesin |
| H35 | **Tüm tabloların satır toplamı** | **572.000** | **±%6 → [538.000, 606.000]** |

### 7.2 Öğrenme çıktısı kontrolleri

> **Tüm doğruluk ölçümlerinin paydası `exam_question.kind = 'choice'` ile sınırlıdır.**

| # | Ölçüm | Beklenen | Tolerans |
|---|---|---|---|
| L1 | Öğrenci başına ortalama `exam_answer` (choice) | **881** | ±%6 |
| L2 | Öğrenci başına yıllık projeksiyon (×36/27) | **1.175** | bilgi amaçlı (bkz. Ek B-1) |
| L3 | **Genel doğruluk oranı** (cevaplanmış choice) | **%58,4** | **±2,0 puan** |
| L4 | Boş bırakma oranı (cevaplanmamış / sorulmuş) | **%12,5** | ±1,5 puan |
| L5 | `kind='text'` soru payı | **%15,0** | ±1,0 puan |
| L6 | Metin sorularında boş bırakma | **%18,0** | ±2,0 puan |
| L7 | `exam_result.mark` ortalaması | **62,8** | ±3 puan |
| L8 | `exam_result.mark` standart sapması | **17,4** | ±2 |
| L9 | `exam_result.mark >= 90` oranı (`HIGH_MARK_MIN`) | **%7,2** | ±2 puan |
| L10 | Madde `p`-değeri ortalaması | **0,585** | ±0,03 |
| L11 | `p < 0.30` madde sayısı | **531** (%8) | ±%15 |
| L12 | `p > 0.90` madde sayısı | **531** (%8) | ±%15 |
| L13 | **Çeldiricinin doğru cevaptan fazla seçildiği madde** | **≈ 180** | **≥ 120 olmalı** |
| L14 | `n ≥ 30` cevap almış banka şablonu | **≈ 540** | ≥ 450 |
| L15 | `D < 0` (negatif) hesaplanabilen madde | **≥ 150** (199'un 12'si kasıtlı `n<30`) | ≥ 130 |
| L16 | `D < 0.10` hesaplanabilen madde | **≥ 250** | ≥ 200 |
| L17 | İlk denemede yanlış / ikincide doğru madde | **≈ 2.960** | ±%12 |
| L18 | `from_bank` dolu `exam_question` payı | **%45** | ±2 puan |
| L19 | `from_bank = NONE` ama manifest'te banka kökenli | **48** | kesin |
| L20 | `banked_as` dolu `exam_question` payı | **%6** | ±1 puan |
| L21 | Metin ıraksaması olan `from_bank` sorusu | **359** | ±%10 |
| L22 | `seq = 2` `exam_attempt` | **564** | ±%6 |
| L23 | `exam_answer` satırı hiç olmayan `exam_attempt` | **9** | kesin |
| L24 | `finished_at = NONE` olan `exam_attempt` | **31** | kesin |

### 7.3 Arketip ayrışma kontrolleri (EN KRİTİK)

| # | Ölçüm | Beklenen | Tolerans |
|---|---|---|---|
| A1 | A1 grubunun genel doğruluğu | **%78** | ±4 puan |
| A2 | A7 grubunun genel doğruluğu | **%42** | ±7 puan |
| A3 | **A1 − A7 doğruluk farkı** | **36 puan** | **≥ 28 puan olmalı** |
| A4 | **A3 grubunun boşluk konularındaki doğruluğu** | **%31** | ±6 puan |
| A5 | **A3 grubunun diğer konulardaki doğruluğu** | **%72** | ±5 puan |
| A6 | **A3'ün konu-içi farkı (aynı öğrenci)** | **41 puan** | **≥ 30 puan olmalı** |
| A7 | A3'ün boşluk konularında **sınıf ortalaması** | **%58** | ±5 puan |
| A8 | A5: T1 doğruluğu → T2 doğruluğu | **%40 → %70** | her biri ±5 puan |
| A9 | A6: kırılma öncesi → sonrası doğruluk | **%64 → %37** | her biri ±5 puan |
| A10 | A4 grubunun `counted_on_time` oranı | **%48** | ±5 puan |
| A11 | A1 grubunun `counted_on_time` oranı | **%97** | ±2 puan |
| A12 | **A4 − A1 `counted_on_time` farkı** | **49 puan** | **≥ 40 puan olmalı** |
| A13 | A7 grubunun devam oranı | **%69** | ±4 puan |
| A14 | A1 grubunun devam oranı | **%97** | ±2 puan |
| A15 | **A1 − A7 devam oranı farkı** | **28 puan** | **≥ 20 puan olmalı** |
| A16 | A8 grubunun toplam randevu sayısı | **≈ 76** | ±10 |
| A17 | A8 grubunun toplam havuz sorusu | **≈ 135** | ±15 |
| A18 | A8'de son 14 günde `≥3 failed` mesajı olan öğrenci | **11** | ≥ 8 |
| A19 | A6: pomodoro haftalık gün, önce → sonra | **3,4 → 0,25** | ±0,4 / ±0,15 |
| A20 | A4'ün pomodoro stintlerinin sınav öncesi 48 saatteki payı | **%70** | ±8 puan |
| A21 | A7'de hiç `pomodoro_session` olmayan öğrenci | **13 / 18** | ±2 |
| A22 | A7'de hiç `chatbot_thread` olmayan öğrenci | **15 / 18** | ±2 |

### 7.4 Davranış ve katılım kontrolleri

| # | Ölçüm | Beklenen | Tolerans |
|---|---|---|---|
| D1 | Okul geneli devam oranı `(present+late)/(present+absent+late)` | **%93,5** | ±1,5 puan |
| D2 | `present` payı (tüm `session_attendance`) | **%84,1** | ±2 puan |
| D3 | `absent` / `late` / `excused` payları | **%9,0 / %4,6 / %2,3** | her biri ±1,5 puan |
| D4 | **Pazartesi devamsızlığı ÷ Çarşamba devamsızlığı** | **1,59** | **≥ 1,30 olmalı** |
| D5 | Cuma devamsızlığı ÷ Çarşamba devamsızlığı | **1,53** | ≥ 1,25 olmalı |
| D6 | Sınav günü devamsızlığı ÷ normal gün devamsızlığı | **0,55** | **≤ 0,70 olmalı** |
| D7 | Grip haftası (2025-12-15…19) devamsızlığı ÷ normal | **2,40** | ≥ 1,80 |
| D8 | Yarıyıl tatilinde `course_session` sayısı | **0** | kesin |
| D9 | Yarıyıl tatilinde pomodoro/gün ÷ normal gün | **0,28** | ±0,08 |
| D10 | **Sınav öncesi 2 gün pomodoro ÷ normal gün** | **≈ 2,40** | **≥ 1,80 olmalı** |
| D11 | **Son 24 saatte teslim edilen ödev payı** | **%44,8** | **±4 puan** |
| D12 | Geç teslim payı (okul geneli) | **%19,6** | ±3 puan |
| D13 | Okul geneli `counted_on_time` oranı | **%74,8** | ±3 puan |
| D14 | `counted_on_time = true` ama `updated_at > due_at` satır | **≈ 750** | ±%20 |
| D15 | `counted = true` pomodoro payı | **%81,4** | ±3 puan |
| D16 | `finished_at = NONE` pomodoro payı | **%6,0** | ±1,5 puan |
| D17 | Pomodoro stintlerinin 00:00–02:30 TR payı | **%8,0** | ±2 puan |
| D18 | Sohbet kullanan öğrenci | **155 / 250** | ±5 |
| D19 | `chatbot_message.status='failed'` payı | **%4,6** | ±1,0 puan |
| D20 | `chatbot_message.status='pending'` sayısı | **270** | ±%15 |
| D21 | 3 günden eski `pending` randevu | **45** | ±8 |
| D22 | 7 günden eski, çözümsüz `approved` havuz sorusu | **180** | ±20 |
| D23 | Yoklaması hiç girilmemiş `course_session` | **399** | ±%10 |
| D24 | `board_stroke.kind = 'clear'` payı | **%3,0** | ±1 puan |
| D25 | `message.read = true` payı | **%66** | ±3 puan |

### 7.5 Ürün tetikleme kontrolleri (tavsiye sistemi kurulunca)

Bu satırlar, veri üretiminden sonra **ürün mantığı yazıldığında** doğrulanır. Veri bunları
tetikleyebiliyorsa senaryo amacına ulaşmıştır.

| # | Ürün | Beklenen tetikleme | Kabul ölçütü |
|---|---|---|---|
| P1 | **Ö1** | Konu bazında bant gösterilebilen öğrenci (n≥8 kapısı) | **≥ 205 / 250** |
| P2 | **Ö1** | `z < −0.8` ("tekrar önerilir") bandı alan (öğrenci, konu) çifti | **≥ 900** |
| P3 | **Ö1** | A7 grubunda "veri toplanıyor" gösterilen konu oranı | **≥ %55** |
| P4 | **Ö2** | Tekrar listesi üretilebilen (öğrenci, sınav) çifti | **≥ 11.000** |
| P5 | **Ö2** | "Sık yapılan hata" etiketi (≥%30 aynı çeldirici) alan madde | **≥ 700** |
| P6 | **Ö2** | "İlerleme" bölümü dolan (öğrenci, sınav) çifti | **≥ 500** |
| P7 | **Ö3** | Isı haritası gösterilebilen öğrenci (≥5 stint) | **160–175** |
| P8 | **Ö4** | "Son dakika profili" (medyan pay < 6 sa) işaretlenen öğrenci | **50–70** (ağırlıkla A4 + A7) |
| P9 | **Ö4** | "Yüksek öncelik" rozeti alan yaklaşan teslim | **≥ 40** |
| P10 | **Ö5** | Zayıf konusuyla eşleşen çözümlü havuz sorusu bulunan öğrenci | **≥ 60** (manifest konusu ile) |
| P11 | **T1** | `p < 0.30` uyarısı çıkan sınav | **≥ 150 / 240** |
| P12 | **T1** | "Çeldirici doğrudan fazla seçildi" bulgusu | **≥ 120 madde** |
| P13 | **T2** | `n ≥ 30` ile `D` hesaplanabilen banka şablonu | **≥ 450 / 885** |
| P14 | **T2** | "Anahtar hatası şüphesi" (`D < 0`) uyarısı | **≥ 130 şablon** |
| P15 | **T2** | "Elden geçir" (`D < 0.10`) uyarısı | **≥ 200 şablon** |
| P16 | **T2** | "Iraksama" uyarısı (metin hash'i farklı) | **≈ 359** |
| P17 | **T2** | "Yeterli veri yok" denen madde (kasıtlı negatif kontrol) | **≥ 12** |
| P18 | **T3** | `p_sınıf < 0.50` işaretlenen (ders, konu) çifti | **≥ 70** |
| P19 | **T3** | "Bireysel destek" hücresi (`p_sınıf` yüksek, `p_öğr` düşük) | **≥ 105** (ağırlıkla A3) |
| P20 | **T3** | Gri (n<8) hücre oranı | **%14–22** |
| P21 | **T4** | Dikkat listesine giren öğrenci | **32–48** |
| P22 | **T4** | Listedeki öğrencilerin A6 payı | **22 A6'nın ≥ 18'i listede** |
| P23 | **T4** | **A5 grubundan listeye giren** | **≤ 2 / 25** (yanlış pozitif kontrolü) |
| P24 | **T4** | Dört tetikleyicinin dördünü ateşleyen öğrenci | **12–18**, **tamamı A6** |
| P25 | **T4** | Yeni gelen 6 öğrenciden listeye giren | **0** (soğuk başlangıç kapısı) |
| P26 | **T4** | Grip haftası nedeniyle tetiklenen bireysel uyarı | **0** (kolektif olay ayırt edilmeli) |
| P27 | **T5** | (a) 3 günden eski `pending` randevu | **45** |
| P28 | **T5** | (b) çözümsüz eski havuz sorusu | **180** |
| P29 | **T5** | (c) `≥3 failed` / 14 gün olan öğrenci | **≥ 14** |
| P30 | **V1** | Haftalık özet üretilebilen veli-öğrenci çifti | **230 / 250** |
| P31 | **V1** | Boş özet ("bu hafta kayıt yok") verilecek çift | **8–14** |
| P32 | **Y1** | "Bu dönem hiç ölçülmemiş konu" listesi | **22** |
| P33 | **Y1** | Seviye tutarsızlığı uyarısı | **1** (12-A) |
| P34 | **Y1** | Notlandırılmamış sınav | **26** |
| P35 | **Y1** | Öğretmen kırılımı içeren çıktı | **0** (ürün kuralı — pano öğretmen bazlı olamaz) |

### 7.6 Bütünlük ve sayaç tutarlılığı (hepsi sıfır olmalı)

Şemada **hiç `ASSERT` yok** (E4) → aşağıdaki ihlaller sessizce yazılabilir. Doğrulama
ajanı bunları **tek tek** kontrol etmelidir.

| # | Kontrol | Beklenen |
|---|---|---|
| I1 | `exam_answer` → `exam_question` referansı kopuk satır | **0** |
| I2 | `exam_answer.seq` ile eşleşen `exam_attempt` bulunmayan satır | **0** |
| I3 | `exam_answer.selected` değeri sorunun `choices[].id` kümesinde değil | **0** |
| I4 | `kind='text'` soruda `selected` dolu | **0** |
| I5 | `kind='choice'` soruda `text` dolu | **0** |
| I6 | `kind='choice'` soruda `correct` boş veya `choices` boş | **0** |
| I7 | `seq = 1` kaydın id'sinde `_1` eki (E3 ihlali) | **0** |
| I8 | `homework_submission.submitted_at > updated_at` | **0** |
| I9 | `homework_result` var ama `homework_submission` yok (status ≠ `missing`) | **0** |
| I10 | `pomodoro_session.finished_at < started_at` | **0** |
| I11 | `counted = true` ama süre < 300.000 ms | **0** |
| I12 | Aynı UTC gününde `counted = true` sayısı > 16 olan (öğrenci, gün) | **0** |
| I13 | `open_` önekli id'ye sahip, aynı kullanıcıda birden fazla `pomodoro_session` | **0** |
| I14 | `session_attendance.status` ∉ `settings.attendance_statuses` | **0** |
| I15 | `exam.kind` ∉ `settings.exam_kinds[].name` | **0** |
| I16 | `menu.slot` ∉ `settings.meal_slots[].name` | **0** |
| I17 | `meal_attendance.status` ∉ {`served`,`missed`} | **0** |
| I18 | `homework_result.status` ∉ {`done`,`incomplete`,`missing`} | **0** |
| I19 | `board_stroke.kind` ∉ {`stroke`,`clear`} | **0** |
| I20 | `pool_question.status` ∉ {`pending`,`approved`} | **0** |
| I21 | `badge_award.badge` 34 sabit kodun dışında | **0** |
| I22 | `badge_award` var ama ilgili `user.*_total` eşiğin altında / `NONE` | **0** |
| I23 | `exam_question.subject.course` ≠ `exam_question.exam.course` | **0** |
| I24 | `homework.subject.course` ≠ `homework.course` | **0** |
| I25 | Öğrenci/veliden öğrenci/veliye `message` (rol kısıtı) | **0** |
| I26 | `appointment.requester` veli ve hedef öğrenciyle `parent_link` yok | **0** |
| I27 | `course.enrollment_count` ≠ gerçek `enrollment` sayısı | **0** |
| I28 | `subject.exam_question_count` ≠ gerçek sayı | **0** |
| I29 | `subject.homework_count` ≠ gerçek sayı | **0** |
| I30 | `exam.result_count` ≠ gerçek `exam_result` sayısı | **0** |
| I31 | `class_group.class_member_count` / `class_course_count` ≠ gerçek | **0** |
| I32 | `term.course_count` / `class_count` ≠ gerçek | **0** |
| I33 | `menu.seats_booked` ≠ `booked` durumundaki `meal_booking` sayısı | **0** |
| I34 | `event.registration_count` ≠ gerçek `registration` sayısı | **0** |
| I35 | `fee_plan.assignment_count` ≠ gerçek sayı | **0** |
| I36 | `board.epoch_stroke_count` / `total_stroke_count` ≠ gerçek | **0** |
| I37 | `user.chatbot_thread_count` / `board_count` ≠ gerçek | **0** |
| I38 | `note.file_count` / `homework_submission.file_count` ≠ gerçek | **0** |
| I39 | `user.study_streak_last_day` veya `pomodoro_counted_day` ms gibi görünen değer (> 100.000) | **0** (E2: gün numarası, ~739.000 aralığında) |
| I40 | `T_NOW`'dan sonra `course_session` / `exam_answer` / `session_attendance` satırı | **0** |
| I41 | 2026-06-19'dan sonra herhangi bir satır | **0** |
| I42 | 2025-09-08'den önce herhangi bir satır (kullanıcı oluşturma hariç) | **0** |
| I43 | `exam_result.mark` veya `homework_result.mark` ∉ `0..=100` | **0** |
| I44 | `exam_question.points` ∉ `1..=100` | **0** |
| I45 | Bir sınavın soru puanları toplamı ≠ 100 | **0** |
| I46 | `*_minor` alanı negatif veya `> 10.000.000` | **0** |
| I47 | `menu.date` uzunluğu ≠ 10 | **0** |
| I48 | `removed_fields` listesindeki bir kolona yazım (`source_bank`, `audience.users`) | **0** |

### 7.7 Kasıtlı hata kontrolleri (bunlar SIFIR OLMAMALI)

Aşağıdakiler **bilinçli olarak** yerleştirilmiştir; sıfır çıkarsa üretici görevi yapmamıştır.

| # | Kontrol | Beklenen |
|---|---|---|
| K1 | `user.pomodoro_finished_total` ≠ gerçek `counted` stint sayısı olan öğrenci | **≈ 170** (%8 şişkin) |
| K2 | `user.lessons_attended_total = NONE` olan öğrenci | **250** (hepsi) |
| K3 | `user.high_mark_total = NONE` olan öğrenci | **250** (hepsi) |
| K4 | `held_counted_at = NONE` olan `course_session` | **≈ 177** (%4) |
| K5 | `bank_question.subject = NONE` | **54** |
| K6 | `exam_question.from_bank = NONE` ama manifest'te banka kökenli | **48** |
| K7 | `grade` değeri `"12. Sınıf"` olan `class_group` | **1** |
| K8 | Manifest'te `answer_key_edits` kaydı | **5** |
| K9 | `a_i < 0` işaretli madde (manifest) | **199** |
| K10 | `a_i ∈ [0, 0.10]` işaretli madde (manifest) | **332** |

### 7.8 `_seed_manifest.json` — gizli gerçek

Üretici, DB'ye yazılmayan ama doğrulama için zorunlu olan gerçeği ayrı bir dosyaya yazar.
**Bu dosya olmadan §7.3, §7.5 ve §7.7 doğrulanamaz.**

```jsonc
{
  "seed": 20260912,
  "t_now_ms": 1776056400000,
  "date_shift_days": 0,
  "school_slug": "ataturk-anadolu",
  "calendar": {
    "t1": ["2025-09-08", "2026-01-16"],
    "t2": ["2026-02-02", "2026-06-19"],
    "breaks": [["2025-11-10","2025-11-14"], ["2026-01-19","2026-01-30"],
               ["2026-04-06","2026-04-10"]],
    "holidays": ["2025-10-29","2026-01-01","2026-03-20"],
    "flu_week": ["2025-12-15","2025-12-19"],
    "teaching_weeks_elapsed": 27,
    "school_days_elapsed": 132
  },
  "students": [
    { "user": "user:01J...", "archetype": "A3", "class": "class_group:01J...",
      "theta_base": 0.51, "theta_trend": 0.0, "t_break_ms": null,
      "gap_course": "course:01J...", "gap_subjects": ["subject:...","...","..."],
      "omission_omega": 0.60, "edge_flags": ["cold_start"] }
  ],
  "items": [
    { "question": "exam_question:01J...", "a": -0.62, "b": 1.14, "c": 0.2125,
      "k": 4, "misconception_choice": "01J...", "w_m": 0.72,
      "difficulty_band": "zor", "quality_band": "negatif",
      "from_bank_true": "bank_question:01J...", "text_diverged": false }
  ],
  "pool_questions": [ { "id": "pool_question:01J...", "true_subject": "subject:01J..." } ],
  "answer_key_edits": [ { "question": "exam_question:01J...",
                          "old_correct": "01J...", "new_correct": "01J..." } ],
  "deleted_bank_templates": ["bank_question:01J...", "..."],
  "grading_delays_ms": { "exam:01J...": 362880000 },
  "expected": { "H": {...}, "L": {...}, "A": {...}, "D": {...}, "P": {...},
                "I": {...}, "K": {...} }
}
```

---

## Ek A — Üretim sırası (topolojik)

```
 1. school (control DB) + settings:school + term x2
 2. user: admin 1, manager 3, teacher 24, student 250, parent 285      -> 563
 3. parent_link x299
 4. class_blueprint x4, class_group x11, class_member x250
 5. course x50, subject x390, class_course x110, enrollment x2.790
 6. bank_question x900 (+ bank_question_image x35)
 7. course_session x4.428      -> session_attendance x98.400
 8. exam x340 -> exam_question x6.640 (+ question_image x400)
 9. exam_attempt x14.800       -> exam_answer x259.000 (+ answer_image x800)
10. exam_result x13.600        (+ exam.result_count yaz)
11. homework x590 -> homework_submission x26.200 (+ homework_file x9.500)
                  -> homework_result x23.000
12. pomodoro_session x26.000   -> user streak / pomodoro sayac alanlari (E2: gun no)
13. pool_question x640         -> solution x780
14. appointment_slot x800      -> appointment x520
15. event x58 -> registration x4.100 -> attendance x2.500
16. menu x310 -> menu_dish x1.240 -> meal_booking x11.800
              -> meal_attendance x11.100 -> meal_ledger x12.400
17. dietary_profile x55
18. fee_plan x4 -> fee_plan_assignment x250 -> payment_ledger x4.400
19. work_entry x3.460          (4 tanesi open_<user> id'li)
20. chatbot_thread x1.500      -> chatbot_message x9.000
21. note x1.530 (+ note_file x420) ; course_note x360 (+ file x260, rag_output x360)
22. message x6.800             (ROL KISITI zorunlu)
23. board x280                 -> board_stroke x9.000
24. badge_award x730 + user.*_total sayaclari (kasitli hatalariyla, E13 tutarlilik)
25. session x40                (canli giris oturumu)
26. BOZMA ADIMI:
      - 15 bank_question sil (48 exam_question.from_bank -> NONE)
      - 5 exam_question.correct degistir (eski deger yalniz manifest'e)
      - 2 course'un teachers dizisini degistir
      - 12-A'nin grade'ini "12. Sinif" yap
27. MATERIALIZE: tum sayaclari yeniden hesapla ve yaz
      enrollment_count, exam_question_count, homework_count, result_count,
      class_member_count, class_course_count, course_count, class_count,
      seats_booked, registration_count, assignment_count,
      epoch_stroke_count, total_stroke_count, chatbot_thread_count,
      board_count, file_count, occupied, kind_ref, slot_ref
28. _seed_manifest.json yaz
29. Bolum 7'nin tum sorgularini calistir, rapor uret
```

## Ek B — Bu senaryonun bilinçli sınırları

1. **Öğrenci başına cevap sayısı (≈1.175/yıl-eşdeğeri) envanterin 1.500–4.000 bandının
   altındadır.** Sebep: 600.000 satırlık tavan. Daha yoğun sinyal isteniyorsa ders başına
   geçmiş sınav sayısını **6 → 8** çıkarmak yeterlidir (`exam_answer` ≈ 345.000,
   toplam ≈ 660.000 satır — hedef aralığın dışına çıkar).
2. **Kazanım (KC) kodu yoktur** — `subject` en ince taksonomi birimidir. Literatürün
   Best-LR/PFA kazanımları KC etiketli veri üzerindedir; bu tohum veri o modelleri
   *olduğu gibi* kurmaya yetmez. Bu, bilinçli bir sınırdır, eksiklik değil.
3. **Ayırt edicilik (2PL) kalibrasyonu bu ölçekte güvenilir değildir** (Linacre: 2PL için
   500–1000+ örneklem). Veri, T2'nin `n ≥ 30` kapısını **keşifsel** düzeyde besler;
   yüksek riskli not kararı için kullanılamaz. Senaryo bunu kanıtlamak üzere kuruludur.
4. **`board_stroke.payload` anlamsızdır.** Yalnız yoğunluk sinyali taşır (D6).
5. **Tek okul.** Çok kiracılı genellenebilirlik (literatürün ana bulgusu) bu veriyle test
   edilemez; ikinci bir okul senaryosu ayrı iştir.
6. **Yemek / ödeme verisi üretilir ama modele girmemelidir** (K2–K4). Varlığının tek
   sebebi, etik kapının kod düzeyinde test edilebilmesidir.
7. **`exam_result` zaman damgası yoktur** (X10) — not verme gecikmesi ölçülemez. Üretici
   gecikmeyi *kullanır* ama veriye yazamaz; yalnız `_seed_manifest.json`'a yazar.
8. **Randevu geçiş damgaları yoktur** (D14) — "ne kadar sürede yanıtlandı" ölçülemez.
   T5 yalnız `created_at` + mevcut `status` üzerinden çalışır.
9. **`seq` dışında oturum içi zaman dizisi yoktur** — soru bazında süre ve tıklama akışı
   olmadığı için derin bilgi takibi (DKT) modelleri bu veride avantaj üretemez.
