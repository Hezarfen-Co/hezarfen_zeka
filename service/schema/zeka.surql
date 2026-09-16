-- ============================================================================
-- ZEKA'nin KENDI veritabani semasi.
--
-- KAPSAM KURALI: bu dosyadaki hicbir tablo okul veritabaninda YASAMAZ.
-- ZEKA okul veritabanina **asla yazmaz**; okul verisini yalnizca `Source`
-- arayuzu uzerinden OKUR. Bu dosya ZEKA'nin kendi SurrealDB veritabaninda
-- (ns/db: zeka) kosulur.
--
-- Kaynak: spec/MODULLER.md §4 (DDL kurallari ve alan listeleri).
-- MODULLER.md §4.1 `question_stat` ve §4.2 `student_subject_stat` tablolari
-- BU SURUMDE YOKTUR: ikisi de ham sinav cevabi / madde verisi gerektirir ve
-- kopru izin listesinde sinav yolu bulunmuyor (bkz. service/src/compute/README.md).
-- Yerlerine not duzeyinde calisan tek bir `student_summary` tablosu gecti.
--
-- BU SURUMDE EKLENEN IKI TABLO (§4, §5): `question_segment` ve
-- `student_segment_profile`. Ikisi de `service/src/segment/` hattinin
-- ciktisidir ve kopru izin listesine DEGIL, tohum verisine / soru metnine
-- dayanir. Madde ISTATISTIGI (p-degeri, ayirt edicilik) yine YOKTUR; bu iki
-- tablo madde ETIKETI ve ogrencinin o etiket altindaki KONTRASTINI tasir.
--
-- DDL kurallari (MODULLER.md §4, migration_sql.rs deneyimi):
--   * Her ifade `DEFINE ... IF NOT EXISTS`.
--   * Tablolar SCHEMAFULL; nested key'ler ayrica tanimlanir.
--   * `DEFAULT []` KULLANILMAZ — PATCH'leri kirdigi deneyimle sabit.
--     Diziler `option<array<...>>` olarak tanimlanir.
--   * Zaman: i64 unix MILLISECONDS, UTC. `TYPE int`, asla `datetime`.
--   * Okul kimligi bir `record` degil, duz `string` slug'dir: ZEKA'nin
--     veritabaninda okul tablolari yoktur, baglanti kurulamaz.
-- ============================================================================


-- ---------------------------------------------------------------------------
-- 1) student_summary — ogrenci basina gecelik ozet
--
-- Kayit anahtari (kompozit, uygulama tarafinda uretilir): `{school}_{user_id}`
-- -> tekillik yapisaldir, UNIQUE indekse gerek yok, UPSERT idempotenttir.
-- ---------------------------------------------------------------------------
-- SURUM NOTU (SurrealDB 3): `FLEXIBLE` anahtar sozcugu `TYPE`'dan SONRA gelir.
-- `... FLEXIBLE TYPE object` yazimi ayristirma hatasi verir ve ifade SESSIZCE
-- yuklenmez; SCHEMAFULL tabloda tanimsiz alan da sessizce DUSER. Yani yanlis
-- siralama, "sema yuklendi ama marks/evidence alanlari kayboldu" demekti.

DEFINE TABLE IF NOT EXISTS student_summary SCHEMAFULL;

DEFINE FIELD IF NOT EXISTS school       ON student_summary TYPE string;
DEFINE FIELD IF NOT EXISTS student      ON student_summary TYPE string;

-- Hesap modullerinin cikti objeleri. FLEXIBLE: sekil hesaplayana aittir,
-- sema her kural surumunde degismek zorunda kalmaz.
DEFINE FIELD IF NOT EXISTS marks        ON student_summary TYPE option<object> FLEXIBLE;
DEFINE FIELD IF NOT EXISTS attendance   ON student_summary TYPE option<object> FLEXIBLE;
DEFINE FIELD IF NOT EXISTS submission   ON student_summary TYPE option<object> FLEXIBLE;
DEFINE FIELD IF NOT EXISTS study        ON student_summary TYPE option<object> FLEXIBLE;

-- Dikkat listesi maddeleri: her oge TEK bir tetikleyici tasir.
-- Tek bir "risk skoru" alani KASITLI OLARAK YOKTUR (MODULLER.md §2.8,
-- 20_tavsiye_sistemi_tasarim.md §6.6 madde 1-2). Skor alani olmadigi icin
-- siralama da semadan uretilemez.
-- SIRA ONEMLI: `attention.*` once tanimlanir. `TYPE option<array<object>>`
-- ifadesi, `.*` alt tanimini KENDILIGINDEN (FLEXIBLE olmadan) uretir; sonra
-- gelen `IF NOT EXISTS` onu atlar ve dikkat maddelerinin ic anahtarlari
-- (`evidence` nesnesi dahil) SESSIZCE DUSER. Once `.*` tanimlanirsa dizi
-- tanimi var olani ezmez.
DEFINE FIELD IF NOT EXISTS attention.*      ON student_summary TYPE object FLEXIBLE;
DEFINE FIELD IF NOT EXISTS attention        ON student_summary TYPE option<array<object>>;

-- Guven kademesi, girdilerden devralinir: 'none' | 'exploratory' | 'stable'
-- (MODULLER.md §0 kural 3, [L-5] Linacre 1994 esikleri).
DEFINE FIELD IF NOT EXISTS confidence   ON student_summary TYPE string;

DEFINE FIELD IF NOT EXISTS computed_at  ON student_summary TYPE int;
-- Saklama suresi: bu damgadan sonra supurulur.
-- MODULLER.md §2.11 adim 2 / [T§6.7]: turetilmis ogrenci profili "donem + 1 yil".
DEFINE FIELD IF NOT EXISTS retain_until ON student_summary TYPE int;

DEFINE INDEX IF NOT EXISTS student_summary_school  ON student_summary FIELDS school;
DEFINE INDEX IF NOT EXISTS student_summary_student ON student_summary FIELDS school, student;
DEFINE INDEX IF NOT EXISTS student_summary_retain  ON student_summary FIELDS retain_until;


-- ---------------------------------------------------------------------------
-- 2) recommendation — uretilmis tavsiyeler
--
-- Her satir bir NEDEN tasir. Aciklanamayan tavsiye gosterilmez ([T§6.3]).
-- `evidence` BOS OLAMAZ: store katmani bos kanitli satiri REDDEDER
-- (MODULLER.md §2.10 yapisal kural 1).
--
-- Kayit anahtari: `{school}_{audience}_{product}_{rule_id}[_{scope}]`
-- -> ayni kural ayni kisi icin cogaltilmaz, UPSERT idempotenttir.
-- ---------------------------------------------------------------------------
DEFINE TABLE IF NOT EXISTS recommendation SCHEMAFULL;

DEFINE FIELD IF NOT EXISTS school       ON recommendation TYPE string;
-- Kime gosterilecek.
DEFINE FIELD IF NOT EXISTS audience     ON recommendation TYPE string;
-- Kim hakkinda. Ogrenci kendi kartinda NONE.
DEFINE FIELD IF NOT EXISTS about        ON recommendation TYPE option<string>;
-- Kime gosterilebilir rol kapisi: 'student' | 'teacher' | 'parent' | 'manager'
-- T4 maddeleri yalnizca 'teacher' tasir — ogrenciye/veliye gosterilmez ([T§6.8]).
DEFINE FIELD IF NOT EXISTS audience_role ON recommendation TYPE string;

-- Urun kodu: 'O1'|'O2'|'O3'|'O4'|'T3'|'T4' (bu surumde uretilebilenler).
-- 'O2' yalnizca segment tabanli kurallardir (`O2.segment_*`); madde bazli
-- tekrar listesi (`O2.retry_item`) hala uretilemiyor. 'V1' (veli ozeti)
-- uretilemiyor: `parent_link` yok (bkz. recommend.unavailable_rules()).
DEFINE FIELD IF NOT EXISTS product      ON recommendation TYPE string;
DEFINE FIELD IF NOT EXISTS course       ON recommendation TYPE option<string>;

-- Hangi kuralin hangi surumu bunu uretti ([T§6.4] madde 3).
DEFINE FIELD IF NOT EXISTS rule_id      ON recommendation TYPE string;
DEFINE FIELD IF NOT EXISTS rule_version ON recommendation TYPE int;

-- Kanit: hangi sayilar, hangi pencere. "Neden?" ekranini besler.
DEFINE FIELD IF NOT EXISTS evidence     ON recommendation TYPE object FLEXIBLE;

DEFINE FIELD IF NOT EXISTS confidence   ON recommendation TYPE string;
DEFINE FIELD IF NOT EXISTS created_at   ON recommendation TYPE int;
DEFINE FIELD IF NOT EXISTS expires_at   ON recommendation TYPE int;
-- `expires_at` veya 90 gun — hangisi once ([T§6.7]). Supurme bunu okur.
DEFINE FIELD IF NOT EXISTS retain_until ON recommendation TYPE int;

-- Insan mudahalesi izi (KVKK m.11): itiraz / kapatma / faydali-degil.
DEFINE FIELD IF NOT EXISTS dismissed_at   ON recommendation TYPE option<int>;
DEFINE FIELD IF NOT EXISTS dismissed_by   ON recommendation TYPE option<string>;
DEFINE FIELD IF NOT EXISTS dismiss_reason ON recommendation TYPE option<string>;

DEFINE INDEX IF NOT EXISTS recommendation_audience ON recommendation FIELDS school, audience, created_at;
DEFINE INDEX IF NOT EXISTS recommendation_about    ON recommendation FIELDS school, about, product;
DEFINE INDEX IF NOT EXISTS recommendation_retain   ON recommendation FIELDS retain_until;
-- Kural kalibrasyon olcumu: bir kural surekli "bu dogru degil" ile kapaniyorsa
-- kural yanlistir ([T§6.4] madde 2).
DEFINE INDEX IF NOT EXISTS recommendation_rule     ON recommendation FIELDS rule_id, created_at;


-- ---------------------------------------------------------------------------
-- 3) insight_run — kosu defteri
--
-- Kismi basarisizlik ve butce muhasebesi buna dayanir (MODULLER.md §3.4).
-- Kayit anahtari: `{school}_{YYYY-MM-DD}` (TR tarihi, 10 karakter sabit).
-- ---------------------------------------------------------------------------
DEFINE TABLE IF NOT EXISTS insight_run SCHEMAFULL;

DEFINE FIELD IF NOT EXISTS school       ON insight_run TYPE string;
DEFINE FIELD IF NOT EXISTS started_at   ON insight_run TYPE int;
DEFINE FIELD IF NOT EXISTS finished_at  ON insight_run TYPE option<int>;
-- 'running' | 'ok' | 'partial' | 'failed' | 'skipped'
DEFINE FIELD IF NOT EXISTS status       ON insight_run TYPE string;
DEFINE FIELD IF NOT EXISTS duration_ms  ON insight_run TYPE option<int>;

DEFINE FIELD IF NOT EXISTS students_total   ON insight_run TYPE int;
DEFINE FIELD IF NOT EXISTS students_ok      ON insight_run TYPE int;
DEFINE FIELD IF NOT EXISTS students_failed  ON insight_run TYPE int;
DEFINE FIELD IF NOT EXISTS students_skipped ON insight_run TYPE int;
DEFINE FIELD IF NOT EXISTS rows_written     ON insight_run TYPE int;

-- Butce asildiysa: islenmemis ogrenciler. Bir sonraki kosu buradan devam eder.
DEFINE FIELD IF NOT EXISTS pending_students   ON insight_run TYPE option<array<string>>;
DEFINE FIELD IF NOT EXISTS pending_students.* ON insight_run TYPE string;
-- Hata veren modul adlari; kismi liste UI'da "eksik" isaretlenir (MODULLER.md §2.8).
DEFINE FIELD IF NOT EXISTS failed_modules     ON insight_run TYPE option<array<string>>;
DEFINE FIELD IF NOT EXISTS failed_modules.*   ON insight_run TYPE string;
DEFINE FIELD IF NOT EXISTS budget_exceeded    ON insight_run TYPE bool;
DEFINE FIELD IF NOT EXISTS budget_ms          ON insight_run TYPE int;

DEFINE FIELD IF NOT EXISTS retain_until ON insight_run TYPE int;  -- 90 gun ([T§6.7])

DEFINE INDEX IF NOT EXISTS insight_run_started ON insight_run FIELDS school, started_at;
DEFINE INDEX IF NOT EXISTS insight_run_retain  ON insight_run FIELDS retain_until;


-- ---------------------------------------------------------------------------
-- 4) question_segment — soru basina bilissel segment etiketi
--
-- Kaynak: `service/src/segment/` hatti (LLM tabanli etiketleme). Bu tablo
-- MODULLER.md §4.1 `question_stat`in YERINE GECMEZ: o tablo madde
-- ISTATISTIGIdir (p-degeri, ayirt edicilik) ve ham sinav cevabi ister; bu
-- tablo madde ETIKETIdir ve yalnizca soru METNINDEN uretilir.
--
-- Kayit anahtari (kompozit): `{school}_{question}` -> tekillik yapisal,
-- UPSERT idempotent, UNIQUE indekse gerek yok.
--
-- KISISEL VERI DEGILDIR: satir bir soru hakkindadir, hicbir ogrenciye
-- baglanamaz ([T§6.7] "sinirsiz" satiri). Yine de SONLU bir `retain_until`
-- tasir: etiket bir MODEL ve bir ISTEM SURUMUNUN ciktisidir, surum degisince
-- bayatlar. Sonsuz saklama, supurme dongusunde bir istisna da yaratirdi.
-- ---------------------------------------------------------------------------
DEFINE TABLE IF NOT EXISTS question_segment SCHEMAFULL;

DEFINE FIELD IF NOT EXISTS school        ON question_segment TYPE string;
-- Kimlikler ZEKA veritabaninda `record` OLAMAZ: okul tablolari burada yoktur,
-- baglanti kurulamaz (bkz. bu dosyanin bas aciklamasi). Duz metin kimlik.
DEFINE FIELD IF NOT EXISTS question      ON question_segment TYPE string;
DEFINE FIELD IF NOT EXISTS exam          ON question_segment TYPE option<string>;
DEFINE FIELD IF NOT EXISTS course        ON question_segment TYPE option<string>;
DEFINE FIELD IF NOT EXISTS subject       ON question_segment TYPE option<string>;

-- --- Boyutlar. Etiket kumeleri `src/segment/rubric.py` ile birebir. --------
-- 'hatirlama' | 'uygulama' | 'analiz'
DEFINE FIELD IF NOT EXISTS bilissel_talep ON question_segment TYPE string;
-- 'var' | 'yok'
DEFINE FIELD IF NOT EXISTS dikkat_tuzagi  ON question_segment TYPE string;
-- 'yuksek' | 'dusuk'
DEFINE FIELD IF NOT EXISTS okuma_yuku     ON question_segment TYPE string;
-- 'tek_adim' | 'cok_adim' — DENEYSEL boyut (asagiya bakiniz).
DEFINE FIELD IF NOT EXISTS adim_sayisi    ON question_segment TYPE string;

-- Boyut basina model guveni [0,1]. Tek bir toplam guven sayisi YETMEZ:
-- bir sorunun okuma yuku kesin, bilissel talebi belirsiz olabilir.
DEFINE FIELD IF NOT EXISTS confidence_bilissel_talep ON question_segment TYPE float;
DEFINE FIELD IF NOT EXISTS confidence_dikkat_tuzagi  ON question_segment TYPE float;
DEFINE FIELD IF NOT EXISTS confidence_okuma_yuku     ON question_segment TYPE float;
DEFINE FIELD IF NOT EXISTS confidence_adim_sayisi    ON question_segment TYPE float;
-- Satir duzeyi guven kademesi (diger tablolarla ayni sozluk):
-- 'none' | 'exploratory' | 'stable'. URETIM boyutlarinin EN DUSUK guveninden
-- turetilir; deneysel boyut bu kademeye GIRMEZ.
DEFINE FIELD IF NOT EXISTS confidence     ON question_segment TYPE string;

-- DENEYSEL / URETIM ayrimi SEMADA gorunur olsun diye iki ayri liste tutulur.
-- `rubric.py` bir boyutu deneysele indirdiginde (alpha kapisinin altinda
-- kalmasi gibi) bu listeler degisir ve asagi akisin o boyutu KULLANMADIGI
-- dogrudan satirdan okunur — belgeye bakmaya gerek kalmaz.
-- SIRA ONEMLI: once `.*`, sonra dizi (bkz. `attention` aciklamasi).
DEFINE FIELD IF NOT EXISTS experimental_dimensions.* ON question_segment TYPE string;
DEFINE FIELD IF NOT EXISTS experimental_dimensions   ON question_segment TYPE option<array<string>>;
DEFINE FIELD IF NOT EXISTS downstream_dimensions.*   ON question_segment TYPE string;
DEFINE FIELD IF NOT EXISTS downstream_dimensions     ON question_segment TYPE option<array<string>>;

-- `dikkat_tuzagi = 'var'` ise isaret edilen sikkin kimligi; aksi halde alan
-- HIC YAZILMAZ (`option<>` NULL kabul etmez).
DEFINE FIELD IF NOT EXISTS trap_choice    ON question_segment TYPE option<string>;
-- Modelin kendi gerekcesi, en fazla iki cumle. OGRENCIYE GOSTERILMEZ
-- (bkz. `docs/CIKTI-SOZLESMESI.md` §5 dikkat listesi).
DEFINE FIELD IF NOT EXISTS rationale      ON question_segment TYPE string;

-- Uretim kunyesi: hangi model, hangi istem surumu, hangi varyant.
-- Sessiz degisiklik yasak ([T§6.4] madde 3): surum degisince satir da degisir.
DEFINE FIELD IF NOT EXISTS model          ON question_segment TYPE string;
DEFINE FIELD IF NOT EXISTS prompt_version ON question_segment TYPE string;
DEFINE FIELD IF NOT EXISTS variant        ON question_segment TYPE option<string>;

DEFINE FIELD IF NOT EXISTS computed_at    ON question_segment TYPE int;
DEFINE FIELD IF NOT EXISTS retain_until   ON question_segment TYPE int;

DEFINE INDEX IF NOT EXISTS question_segment_question ON question_segment FIELDS school, question;
DEFINE INDEX IF NOT EXISTS question_segment_exam     ON question_segment FIELDS school, exam;
DEFINE INDEX IF NOT EXISTS question_segment_subject  ON question_segment FIELDS school, subject;
-- Ders x bilissel talep dagilimi (ogretmen ekrani) tam tarama yapmasin.
DEFINE INDEX IF NOT EXISTS question_segment_talep    ON question_segment FIELDS school, course, bilissel_talep;
DEFINE INDEX IF NOT EXISTS question_segment_retain   ON question_segment FIELDS retain_until;


-- ---------------------------------------------------------------------------
-- 5) student_segment_profile — ogrenci x boyut x etiket performansi
--
-- Kayit anahtari (kompozit): `{school}_{student}_{dimension}_{label}`
-- -> UPSERT idempotent.
--
-- `contrast` ALANI BU TABLONUN VAR OLMA SEBEBIDIR.
-- Ham `accuracy` bir AYRIM OLCUSU DEGILDIR: bir ogrencinin herhangi bir
-- segmentteki dogruluk orani buyuk olcude GENEL yetenegini yansitir. Iyi
-- ogrenci her segmentte yuksek, zayif ogrenci her segmentte dusuk cikar;
-- boyle bir sayidan "bu ogrenci analiz sorularinda zorlaniyor" sonucu
-- CIKARILAMAZ.
--   contrast = accuracy - overall_accuracy
-- yani ogrencinin bu segmentteki dogrulugu EKSI kendi genel dogrulugu. Genel
-- duzey bu farkta sadelesir; geriye segmentin kendisine ozgu sapma kalir.
-- Tavsiye kurallari YALNIZCA `contrast` uzerinden ates eder, `accuracy`
-- uzerinden ASLA (bkz. `src/compute/recommend.py` SEG.* kurallari).
--
-- Bu tablo KISISEL VERIDIR: turetilmis ogrenci profili, "donem + 1 yil"
-- ([T§6.7]) ve mezuniyette silinir (`Store.purge_departed`).
-- ---------------------------------------------------------------------------
DEFINE TABLE IF NOT EXISTS student_segment_profile SCHEMAFULL;

DEFINE FIELD IF NOT EXISTS school       ON student_segment_profile TYPE string;
DEFINE FIELD IF NOT EXISTS student      ON student_segment_profile TYPE string;
-- 'bilissel_talep' | 'dikkat_tuzagi' | 'okuma_yuku' (URETIM boyutlari).
-- Deneysel boyut (`adim_sayisi`) bu tabloya GIRMEZ; `question_segment` icinde
-- etiketlenir ve orada kalir.
DEFINE FIELD IF NOT EXISTS dimension    ON student_segment_profile TYPE string;
DEFINE FIELD IF NOT EXISTS label        ON student_segment_profile TYPE string;

DEFINE FIELD IF NOT EXISTS n_answers    ON student_segment_profile TYPE int;
DEFINE FIELD IF NOT EXISTS n_correct    ON student_segment_profile TYPE int;
-- Bu segmentteki dogruluk orani. TEK BASINA GOSTERILMEZ, TEK BASINA KURAL
-- ATESLEMEZ: genel yetenegi tasir, ayrim gucu yoktur.
DEFINE FIELD IF NOT EXISTS accuracy     ON student_segment_profile TYPE float;

-- Ogrencinin ETIKETLENMIS butun maddelerdeki genel dogrulugu — kontrastin
-- cikarani. Kanit nesnesinde gosterilebilsin diye satirda tutulur.
DEFINE FIELD IF NOT EXISTS overall_n_answers ON student_segment_profile TYPE int;
DEFINE FIELD IF NOT EXISTS overall_accuracy  ON student_segment_profile TYPE float;
-- DURUST OLCU: accuracy - overall_accuracy. Negatif = ogrenci kendi genel
-- seviyesine gore bu segmentte GERIDE.
DEFINE FIELD IF NOT EXISTS contrast     ON student_segment_profile TYPE float;

-- 'none' | 'exploratory' | 'stable' — segmentteki cevap sayisindan turetilir
-- ([L-5] Linacre esikleri; olculmus degerler `docs/SEGMENT-CIKTI.md` §3).
DEFINE FIELD IF NOT EXISTS confidence   ON student_segment_profile TYPE string;

DEFINE FIELD IF NOT EXISTS computed_at  ON student_segment_profile TYPE int;
DEFINE FIELD IF NOT EXISTS retain_until ON student_segment_profile TYPE int;

DEFINE INDEX IF NOT EXISTS ssp_student   ON student_segment_profile FIELDS school, student;
DEFINE INDEX IF NOT EXISTS ssp_dimension ON student_segment_profile FIELDS school, dimension, label;
DEFINE INDEX IF NOT EXISTS ssp_retain    ON student_segment_profile FIELDS retain_until;
