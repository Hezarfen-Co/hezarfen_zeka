# Sunucuya gönderilecek paket

İki ayrı şey var ve **farklı yerlere** gidiyorlar. Karıştırılırsa biri eksik kalır.

> **Bu klasörde depoda duran şey:** `20260916000001_zeka.sql`, iki betik ve bu
> belge. SQL veri dosyaları (`pg_school.sql` 101 MB, `pg_control.sql`,
> `pg_dogrula.sql`) **gitignore'ludur** — GitHub'ın tek dosya sınırı 100 MB ve
> deterministik üretildikleri için depoda tutmanın kazandıracağı bir şey yok:
>
> ```sh
> python generator/main.py --scale full --postgres --out paket/
> ```
>
> `migrations/` de depoda değil: backend'in kendi şemasının kopyasıdır ve iki
> yerde duran bir şema er ya da geç ayrışır. Yükleyici gerçek checkout'u alır:
>
> ```sh
> BACKEND=/yol/hezarfen_backend-main bash load_pg_seed.sh .
> ```

---

## 1. ZEKA'nın tabloları → her okul veritabanına

`20260916000001_zeka.sql` — dokuz tablo (`zeka_*`).

Bu dosya iki yere birden konmalı:

**a) `migrations/school/` klasörüne** — yeni açılacak okullar ve şablon için.
Backend ekibi commit edip deploy etmeli. Mevcut dört migration dosyasına
**dokunulmuyor**: sqlx bunları sağlama toplamıyla izliyor, birini düzenlemek
uygulanmış veritabanlarını kırar.

**b) `apply_zeka_tables.sh` ile mevcut okullara** — çünkü (a) onları kapsamaz.

```sh
HEZARFEN_PG_CONTAINER=hezarfen_backend_postgres \
POSTGRES_USER=hezarfen POSTGRES_DB=hezarfen_control \
bash apply_zeka_tables.sh
```

### (b) neden gerekiyor

Backend'in kendi kaynağı (`database.rs:126`):

> *"The schema is the caller's business — `migrate_school` for a mint,
> **nothing for a re-dial of an existing school**."*

Ve `reconcile_provisioning` yalnız `provisioning` durumundaki okullara bakıyor.
Yani sunucuda **zaten duran** bir okul, migration dosyası eklense bile `zeka_*`
tablolarını asla kendiliğinden almaz. Betik o boşluğu kapatır.

Betik yalnız `CREATE TABLE` / `CREATE INDEX` çalıştırır, hiçbir mevcut tabloya
dokunmaz, hiçbir satırı değiştirmez. Tabloları zaten olan okulu **atlar**.
Okulları control kütüğünden çözer, ad deseninden değil.

---

## 2. Demo verisi → kendi yeni veritabanına

`pg_school.sql` (101 MB) + `pg_control.sql` (150 KB) + `pg_dogrula.sql`

```sh
HEZARFEN_PG_CONTAINER=hezarfen_backend_postgres \
POSTGRES_USER=hezarfen POSTGRES_DB=hezarfen_control \
bash load_pg_seed.sh .
```

Ne yapar:

1. Okul veritabanını backend'in **kendi** adlandırma kuralıyla kurar
   (`tenant.rs:112` → `{control}_school_{uuid.simple}`)
2. `migrations/` içindeki şemayı uygular (ZEKA'nınki dahil)
3. `pg_school.sql`'i döker — 576.487 satır
4. **48 bütünlük denetimini koşturur**; bir tanesi bile ihlal bulursa orada durur
5. Control kaydını **en sona** yazar

(5) bilinçli: backend okulu `active` görür görmez istek kabul etmeye başlıyor,
veri hazır olmadan kaydı yazmak yarım bir okul açmak olurdu.

### Demo okulu

| | |
|---|---|
| slug | `hezarfen-demo` |
| uuid | `01930000-0000-7000-8000-00000000de70` |
| öğrenci | 250 (563 kullanıcı) |
| kapsam | 2025-09-07 → 2026-04-13, 27 öğretim haftası |
| satır | okul 576.487, control 1.148 |

**Mevcut okullara dokunmaz.** Kendi veritabanını kurar, control'e bir satır
ekler. Okul kaydı slug ile çakışırsa `DO NOTHING` — üzerine yazmaz.

---

## Giriş

Yeni backend'de parola okul veritabanında **değil**, control'deki `person`
satırında: `person` → `person_school` → `app_user.person`.

Tohum bu zinciri kuruyor (563 `person`, 563 `person_school`). Kurulmasaydı veri
görünür, sistem kullanılamaz olurdu.

`person_school.school` bir alt sorgudur (`SELECT id FROM school WHERE slug=...`),
sabit uuid değil — okulu backend yaratmış olsa bile üyelik doğru okula bağlanır.

---

## Sıra

```sh
# 0) YEDEK — önce
~/hezarfen_backend/backup-postgres.sh

# 1) mevcut okullara ZEKA tabloları
bash apply_zeka_tables.sh

# 2) demo verisi
bash load_pg_seed.sh .

# 3) migration dosyasını backend deposuna commit et (yeni okullar için)
```

Adım 1 ve 2 birbirinden bağımsız; sırası önemli değil. Adım 3 backend ekibinin.

---

## Bilinmesi gerekenler

**Yükleme tekrarlanamaz.** Birincil anahtarlar deterministik; ikinci çalıştırma
çakışır ve hiçbir şey yazmaz. Yeniden yüklemek için okul veritabanını düşürmek
gerekir. Demo için doğru davranış, ama "bir daha çalıştırayım" refleksi işe
yaramaz.

**Yüklenen okulda `_sqlx_migrations` tablosu yok.** Şemayı elle uyguladığımız
için. Bugün zararsız: backend aktif bir okulu yeniden migrate etmiyor. İleride
bu davranış değişirse o okul "relation already exists" ile düşer — sessiz
değil, gürültülü bir hata.

**Beş zaman damgası yaklaşık.** Yeni şemanın eklediği, tohumda karşılığı olmayan
kolonlar ilgili kaydın ULID damgasından türetiliyor. `exam_result.graded_at`
özellikle: **"notlandırma gecikmesi" gibi bir ölçüm için kullanılamaz.**
Ayrıntısı `generator/pg_map.DERIVED_COLUMNS` içinde. ZEKA hiçbirini okumuyor.

**ZEKA servisinin veritabanı kullanıcısı** üretimde yalnız dokuz `zeka_*`
tablosuna yazma, kalanına salt okuma yetkisine daraltılmalı.
