# Sunucuya verilecek paket

> **Kime:** backend ekibi. Bu klasörde teslim edilen şey artık bir **not**tur:
> ZEKA hiçbir şema uygulamaz, hiçbir veritabanı bağlantısı açmaz ve sunucuda
> çalıştırılacak bir yükleme betiği **yoktur**.

---

## 1. ZEKA'nın tabloları — backend deposunda

Dokuz `zeka_*` tablosunun DDL'i **backend deposundadır**:

```
hezarfen_backend/migrations/school/20260917000002_zeka.sql
```

Hepsi her **okulun kendi veritabanında** durur; şablon ve yeni açılan okullar
için `migrate_school` uygular. Dosya mevcut dört okul migration'ına **dokunmaz**:
yalnız yeni tablo ve indeks kurar, sqlx bunları sağlama toplamıyla izlediği için
birini düzenlemek uygulanmış veritabanlarını kırardı.

Tabloların sahibi backend'dir: **süpürmeyi ve ayrılan temizliğini de backend
koşturur**, çünkü satırlar okulun veritabanındadır. ZEKA yalnız `insight.*`
yetenek çağrılarıyla "şu satırları yaz" der.

Tabloların hangisi ne tutar, alan alan: `service/docs/CIKTI-SOZLESMESI.md`.

---

## 2. Demo verisi

Depoda **tohumun kendisi yok, üreticisi var**. Deterministik üretildiği için
~170 MB'lık çıktıyı depoda tutmanın kazandıracağı bir şey yok (ve GitHub'ın tek
dosya sınırını aşıyor).

```sh
python generator/main.py --scale full --out /tmp/seed
```

Üretilen: demo okulunun bütün veri seti, tablo başına satır sayısıyla
`MANIFEST.json`, gizli gerçeği taşıyan `_seed_manifest.json` ve 48 bütünlük
sorgusu. **Yüklemesi backend ekibinin işidir.**

| | |
|---|---|
| slug | `hezarfen-demo` |
| uuid | `01930000-0000-7000-8000-00000000de70` |
| öğrenci | 250 (563 kullanıcı: + 24 öğretmen, 285 veli, 4 yönetici) |
| kapsam | 2025-09-07 → 2026-04-13 (217 gün, 27 öğretim haftası) |
| modüller | 21'inin tamamı açık |

Ayrı bir okuldur; başka bir okulun verisine dokunmaz.

### uuid neden sabit

Okul veritabanının **adı slug'dan değil uuid'den** türer (`tenant.rs:112` —
`"{control}_school_{uuid.simple}"`). Yani tohumu hangi veritabanına
yazacağımızı, backend okulu yaratmadan önce bilmemiz gerekiyor. Sabit uuid bunu
mümkün kılar.

---

## 3. Giriş zinciri

Parola okul veritabanında **değil**, control'deki `person` satırındadır:

```
person → person_school → app_user.person
```

Tohum bu zinciri kurar: 563 `person`, 563 `person_school` ve her `app_user`
satırında dolu bir `person` alanı. Ölçüldü: **563/563 eşleşiyor.** Bu
kurulmasaydı veri görünür, sistem kullanılamaz olurdu.

`person_school.school` bir alt sorgudur (`SELECT id FROM school WHERE slug=...`),
sabit uuid değil — okulu backend yaratmış olsa bile üyelik doğru okula bağlanır.

---

## 4. Bilinmesi gerekenler

**Beş zaman damgası yaklaşıktır.** Yeni şemanın eklediği ve tohumda karşılığı
olmayan kolonlar, ilgili kaydın ULID damgasından türetilir. `exam_result.graded_at`
özellikle: **"notlandırma gecikmesi" gibi bir ölçüm için kullanılamaz.**
ZEKA hiçbirini okumaz — köprü izin listesinde o yollar yoktur.

**Bir kapı açık kalıyor:** backend'in ZEKA'yı çağırması (`insight.student`,
`insight.class`, `insight.refresh`) için dağıtım kapısı henüz yoktur. Servisin
backend'i çağırdığı `insight.*` depo yolu ise 2026-09-17'de açıldı (`f84c29d`)
ve çalışır. Gereksinim listesi: `service/docs/BACKEND-GEREKSINIMLERI.md`,
sahibi backend'deki `InsightDoors` hattı.
