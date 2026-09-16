# Demo kurulumu — yeni (PostgreSQL) backend

> **Kime:** backend ekibi.
> Bu belge demo okulunu sıfırdan ayağa kaldırmanın tam yolunu verir.

---

## 0. Ne değişti, tek cümle

Backend SurrealDB'den PostgreSQL'e geçti. ZEKA'nın çıktı tabloları artık okulun
kendi Postgres veritabanında duruyor, tohum verisi de oraya yükleniyor.

**Köprü değişmedi:** `hab/2`, 19 yolluk izin listesi aynı. ZEKA'nın veri çekme
tarafı bu geçişten hiç etkilenmedi.

---

## 1. Demo okulu

| | |
|---|---|
| slug | `hezarfen-demo` |
| uuid | `01930000-0000-7000-8000-00000000de70` |
| veritabanı | `hezarfen_control_school_0193000000007000800000000000de70` |
| öğrenci | 250 (563 kullanıcı: + 24 öğretmen, 285 veli, 4 yönetici) |
| kapsam | 2025-09-07 → 2026-04-13 (217 gün, 27 öğretim haftası) |
| satır | okul 576.487, control 1.148 |
| modüller | 21'inin tamamı açık |

Ayrı bir okuldur; başka bir okulun verisine dokunmaz.

### uuid neden sabit

Okul veritabanının **adı slug'dan değil uuid'den** türüyor
(`tenant.rs:112` — `"{control}_school_{uuid.simple}"`). Yani tohumu hangi
veritabanına yazacağımızı, backend okulu yaratmadan önce bilmemiz gerekiyor.
Sabit uuid bunu mümkün kılar; tek kaynağı `generator/pg_map.DEMO_SCHOOL_ID`.

---

## 2. ZEKA'nın tabloları

`migrations/school/20260916000001_zeka.sql` backend deposuna **eklendi**.
Mevcut dört migration dosyasına dokunulmadı — sqlx bunları sağlama toplamıyla
izliyor, birini düzenlemek uygulanmış veritabanlarını kırardı.

Dokuz tablo: `zeka_student_summary`, `zeka_attention_item`,
`zeka_recommendation`, `zeka_run`, `zeka_run_pending`,
`zeka_run_failed_module`, `zeka_question_segment`,
`zeka_question_segment_dimension`, `zeka_student_segment_profile`.

**Yabancı anahtarlar tek yönlü:** `zeka_*` tabloları `app_user`, `course`,
`subject`, `exam`, `exam_question`'a bakar; okul tablolarının hiçbiri
`zeka_*`'a bakmaz. Dosyayı silseniz okul şeması olduğu gibi ayakta kalır.
`tools/check_pg_schema.sh` bunu ayrıca sınar.

Backend'in kendi `scripts/prepare_db.sh`'i bu dosyayla birlikte geçiyor.

---

## 3. Kurulum

```sh
# 1) Postgres
podman compose up -d postgres

# 2) Tohumu üret (SurrealQL çıktısı da aynı geçişte üretilir, o değişmez)
python generator/main.py --scale full --postgres --out /tmp/pgseed

# 3) Yükle — okul db'sini kurar, şemaları uygular, veriyi döker,
#    48 bütünlük denetimini koşturur, control kaydını EN SONA yazar
tools/load_pg_seed.sh /tmp/pgseed

# 4) Backend'i başlat; okulu hazır ve `active` bulur
```

Control kaydının en sona bırakılması bilinçli: backend okulu `active` görür
görmez istek kabul etmeye başlıyor, veri hazır olmadan kaydı yazmak **yarım bir
okul açmak** olurdu.

Yükleme bütünlük sınavında düşerse orada durur. "Yüklendi" deyip bozuk veriyle
devam etmek, hiç yüklememekten kötüdür.

### Tekrar yükleme

Her iki dosya da tek transaction'da koşar ve birincil anahtarlar
deterministiktir — ikinci yükleme çakışır ve **hiçbir şey yazmaz**. Yeniden
yüklemek için iki veritabanını da düşürmek gerekir.

---

## 4. Giriş

Yeni backend'de parola okul veritabanında **değil**, control'deki `person`
satırında. Zincir: `person` → `person_school` → `app_user.person`.

Tohum bu zinciri kuruyor: 563 `person`, 563 `person_school`, ve her `app_user`
satırında dolu bir `person` alanı. Ölçüldü: **563/563 eşleşiyor.**

Bu kurulmasaydı veri görünür, sistem kullanılamaz olurdu.

---

## 5. ZEKA servisi

```
ZEKA_PG_DSN=postgresql://<kullanici>:<parola>@<host>:5432/hezarfen_control_school_0193000000007000800000000000de70
```

Üretimde bu kullanıcı **yalnız dokuz `zeka_*` tablosuna yazma, kalan 77 tabloya
salt okuma** yetkisine daraltılmalı. Bugün geliştirmede tam yetkili kullanıcı
kullanılıyor.

Servis okumayı bu bağlantıdan değil, **köprüden** yapar. Veritabanı bağlantısı
yalnızca yazma içindir.

---

## 6. Doğrulama

| Ne | Nasıl | Sonuç |
|---|---|---|
| Şema + davranış | `tools/check_pg_schema.sh` | 19 test, çıkış 0 |
| Yüklenen veri | `pg_dogrula.sql` (yükleyici koşturur) | 48 denetim temiz |
| ZEKA yazma katmanı | `python -m unittest tests.test_store_pg` | 13 test |
| Tüm paket | `python -m unittest discover -s tests -t .` | 686 test |

Bütünlük sınavının beş maddesi (I1, I7, I9, I13, I48) yeni şemada **ihlal
edilemez** — yabancı anahtarlar, kısmi tekil indeksler ve kolonun hiç var
olmaması bunu yapısal olarak imkânsız kılıyor. Listede duruyorlar ve neyle
zorlandıkları yanlarında yazıyor. Sıfır dönen bir sorgu, bir şeyi ispatladığı
için değil, sorulması imkânsız hale geldiği için de sıfır dönebilir; ikisi aynı
şey değil.

---

## 7. Bilinmesi gerekenler

**Beş zaman damgası yaklaşıktır.** Yeni şemanın eklediği ve tohumda karşılığı
olmayan kolonlar, ilgili kaydın ULID damgasından türetiliyor:

| Kolon | Doğruluk |
|---|---|
| `session_attendance.marked_at` | tam (dersin kendi damgası) |
| `attendance.marked_at` | yaklaşık (etkinlik damgası, saatler mertebesinde sapma) |
| `registration.created_at` | yaklaşık (kayıt etkinlikten önce olur) |
| `enrollment.created_at` | yaklaşık (dönem ortası kaydolan için yanlış) |
| `exam_result.graded_at` | yaklaşık — **"notlandırma gecikmesi" ölçümü için kullanılamaz** |

Gerekçeleri `generator/pg_map.DERIVED_COLUMNS` içinde yazılı. ZEKA hiçbirini
okumuyor (köprü izin listesinde o yollar yok).

**İki kasıtlı bozukluk temsil edilemiyor.** K2 (`lessons_attended_total` NONE)
ve K3 (`high_mark_total` NONE), 250'şer satır. Yeni şemada sayaç kolonları
`BIGINT NOT NULL DEFAULT 0`; ikisi de `0` oluyor. Anlam aynı ama ZEKA artık
"hiç sayılmadı" ile "sıfır sayıldı" ayrımını yapamaz. Kalan sekiz bozukluk
(K1, K4–K10) aynen taşınıyor.

**Tohumda bir düzeltme yapıldı.** 4.929 açık pomodoro oturumu vardı, bir
öğrencide 68 tane. Hem eski hem yeni backend kullanıcı başına **tek** açık
oturuma izin veriyor; SurrealDB bunu zorlamadığı için görünmüyordu. Artık 8
açık oturum var, terk edilmişlik `counted = false` ile taşınıyor.

---

## 8. Hâlâ backend ekibinden beklenenler

Bu üçü geçişten bağımsız, `docs/BACKEND-GEREKSINIMLERI.md` ile aynı:

1. **ZEKA'nın yetenekleri backend'de tanımlı değil.** Backend yalnız
   `chat.reply` ve `rag.index` tanıyor. ZEKA bağlansa bile iş almaz; istek
   üzerine çalışan her senaryo kapalı. (Kendi takvimiyle çalışması etkilenmez.)
2. **Sınav yolları izin listesinde yok** — madde analizi bu yüzden
   üretilemiyor. Tohumda 216.633 sınav cevabı ve kasıtlı bozuk maddeler var:
   bulunacak şey mevcut, bulunacak yol yok.
3. **Okul ve kullanıcı listeleme yolu yok** — ZEKA kimleri işleyeceğini
   köprüden öğrenemiyor, bugün yapılandırmadan çözülüyor.
