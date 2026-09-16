-- ZEKA tablolarinin DAVRANIS sinavi: DDL'in yuklenmesi degil, CALISMASI.
--
-- Bu dosya `tools/check_pg_schema.sh` tarafindan, backend'in ve ZEKA'nin
-- migration'lari uygulandiktan SONRA kosturulur. Her blok ya yazar ya da
-- yazamamasi GEREKTIGINI kanitlar; sonuncular `sonuc` tablosuna 'RED BEKLENDI'
-- yazar ve kisit atesLEMEZSE test duser.
--
-- Neden var: SurrealDB surumunde sema "yuklendi" ve yine de bes alani sessizce
-- dusurdu. Yuklenmeyi gormek yetmiyor; satirin girip girmedigini gormek gerek.

\set ON_ERROR_STOP on

-- SAVEPOINT yalnizca transaction icinde gecerli; ayrica sinav satirlarinin
-- veritabaninda kalmasina gerek yok.
BEGIN;

CREATE TEMP TABLE sonuc (sira int GENERATED ALWAYS AS IDENTITY, ad text, durum text);

-- ---------------------------------------------------------------------------
-- Okul tarafinda en az bir gercek satir zinciri: app_user -> course -> subject
-- -> exam -> exam_question. ZEKA'nin FK'leri bunlara bakiyor.
-- ---------------------------------------------------------------------------
INSERT INTO app_user (id, username, role, created_at) VALUES
  ('01920000-0000-7000-8000-000000000001', 'ogrenci1', 'student', 1776056400000),
  ('01920000-0000-7000-8000-000000000002', 'ogretmen1', 'teacher', 1776056400000);

INSERT INTO course (id, creator, title, description, kind)
VALUES ('01920000-0000-7000-8000-00000000000a',
        '01920000-0000-7000-8000-000000000002', 'Matematik', '', 'course');

INSERT INTO subject (id, course, name, description)
VALUES ('01920000-0000-7000-8000-00000000000b',
        '01920000-0000-7000-8000-00000000000a', 'Turev', '');

INSERT INTO exam (id, creator, course, title, description, kind)
VALUES ('01920000-0000-7000-8000-00000000000c',
        '01920000-0000-7000-8000-000000000002',
        '01920000-0000-7000-8000-00000000000a', 'Deneme 1', '', 'quiz');

INSERT INTO exam_question (id, exam, text, kind, points, subject, choices)
VALUES ('01920000-0000-7000-8000-00000000000d',
        '01920000-0000-7000-8000-00000000000c',
        'f(x)=x^2 icin f''(2) kactir?', 'multiple_choice', 5,
        '01920000-0000-7000-8000-00000000000b',
        '[{"id":"a","text":"2"},{"id":"b","text":"4"},{"id":"c","text":"8"}]'::jsonb);


-- ---------------------------------------------------------------------------
-- 1) student_summary + attention: gercek sekilli JSONB girsin
-- ---------------------------------------------------------------------------
INSERT INTO zeka_student_summary
  (student, marks, attendance, submission, study, confidence, computed_at, retain_until)
VALUES ('01920000-0000-7000-8000-000000000001',
        '{"courses":[{"course":"01920000-0000-7000-8000-00000000000a","average":63.4,"band":"Orta","cohort_percentile":41}]}'::jsonb,
        '{"courses":[{"course":"01920000-0000-7000-8000-00000000000a","present_rate":0.91,"cohort_median":0.93}]}'::jsonb,
        '{"missing_rate":0.18,"late_rate":0.23,"n":41}'::jsonb,
        '{"weekly_minutes":213,"night_share":0.07}'::jsonb,
        'stable', 1776056400000, 1807592400000);
INSERT INTO sonuc (ad, durum) VALUES ('student_summary yazildi', 'OK');

INSERT INTO zeka_attention_item
  (student, trigger, course, fact, window_from, window_to, evidence, ord) VALUES
  ('01920000-0000-7000-8000-000000000001', 'attendance',
   '01920000-0000-7000-8000-00000000000a',
   'Son 28 gunde derse katilim %78; sube ortancasi %93.',
   1773464400000, 1776056400000,
   '{"measure":"level_vs_cohort_median","value":0.78,"cohort_median":0.93,"window_days":28}'::jsonb, 0),
  -- Ders bagimsiz madde: course NULL. NULLS NOT DISTINCT bunu DOLU bir yuva
  -- sayar, yani ayni ogrenciye ikinci bir ders-bagimsiz 'homework' giremez.
  ('01920000-0000-7000-8000-000000000001', 'homework', NULL,
   'Son 30 gunde verilen odevlerin %44 kadari teslim edilmedi; sube ortancasi %18.',
   1773464400000, 1776056400000,
   '{"measure":"missing_rate_vs_cohort_median","missing_rate":0.44,"cohort_missing_rate_median":0.18}'::jsonb, 1);
INSERT INTO sonuc (ad, durum) VALUES ('attention_item 2 satir (biri course NULL)', 'OK');


-- ---------------------------------------------------------------------------
-- 2) recommendation: UPSERT idempotan mi, ve kapatma izi KORUNUYOR mu?
--    Bu ikincisi belgelenmis tuzak: duz bir DO UPDATE SET her kolonu yazar ve
--    kullanicinin kapatma kaydini her gece siler.
-- ---------------------------------------------------------------------------
INSERT INTO zeka_recommendation
  (id, audience, product, rule_id, rule_version, scope, about, audience_role,
   course, evidence, confidence, created_at, expires_at, retain_until)
VALUES ('01920000-0000-7000-8000-000000000101',
        '01920000-0000-7000-8000-000000000002', 'T4', 'T4.homework', 3,
        '01920000-0000-7000-8000-00000000000a',
        '01920000-0000-7000-8000-000000000001', 'teacher',
        '01920000-0000-7000-8000-00000000000a',
        '{"missing_rate":0.44,"cohort_median":0.18,"n":41}'::jsonb,
        'stable', 1776056400000, 1778648400000, 1783832400000);

-- Ogretmen kapatti.
UPDATE zeka_recommendation
   SET dismissed_at = 1776142800000,
       dismissed_by = '01920000-0000-7000-8000-000000000002',
       dismiss_reason = 'ogrenci rapor verdi'
 WHERE id = '01920000-0000-7000-8000-000000000101';

-- Ertesi gece ayni kural yeniden uretildi. DOGRU yazim: catisma dogal anahtar
-- uzerinde, ve SET listesi dismiss_* kolonlarini ICERMEZ.
INSERT INTO zeka_recommendation
  (id, audience, product, rule_id, rule_version, scope, about, audience_role,
   course, evidence, confidence, created_at, expires_at, retain_until)
VALUES ('01920000-0000-7000-8000-000000000102',
        '01920000-0000-7000-8000-000000000002', 'T4', 'T4.homework', 3,
        '01920000-0000-7000-8000-00000000000a',
        '01920000-0000-7000-8000-000000000001', 'teacher',
        '01920000-0000-7000-8000-00000000000a',
        '{"missing_rate":0.46,"cohort_median":0.18,"n":43}'::jsonb,
        'stable', 1776142800000, 1778734800000, 1783918800000)
ON CONFLICT (audience, product, rule_id, about, scope) DO UPDATE SET
  rule_version = EXCLUDED.rule_version,
  evidence     = EXCLUDED.evidence,
  confidence   = EXCLUDED.confidence,
  created_at   = EXCLUDED.created_at,
  expires_at   = EXCLUDED.expires_at,
  retain_until = EXCLUDED.retain_until;

INSERT INTO sonuc (ad, durum)
SELECT 'recommendation UPSERT tek satir birakti',
       CASE WHEN count(*) = 1 THEN 'OK' ELSE 'DUSTU: ' || count(*) END
  FROM zeka_recommendation;

INSERT INTO sonuc (ad, durum)
SELECT 'kapatma izi gece yaziminda KORUNDU',
       CASE WHEN dismissed_at = 1776142800000
             AND dismiss_reason = 'ogrenci rapor verdi'
            THEN 'OK' ELSE 'DUSTU' END
  FROM zeka_recommendation;

INSERT INTO sonuc (ad, durum)
SELECT 'gece yazimi kaniti tazeledi',
       CASE WHEN evidence->>'n' = '43' THEN 'OK' ELSE 'DUSTU' END
  FROM zeka_recommendation;


-- ---------------------------------------------------------------------------
-- 3) run defteri + cocuk tablolari
-- ---------------------------------------------------------------------------
INSERT INTO zeka_run (run_day, started_at, status, students_total, students_ok,
                      budget_ms, retain_until)
VALUES ('2026-04-13', 1776056400000, 'partial', 250, 231, 3600000, 1783832400000);

INSERT INTO zeka_run_pending (run, student, ord)
VALUES ('2026-04-13', '01920000-0000-7000-8000-000000000001', 0);

INSERT INTO zeka_run_failed_module (run, module, ord)
VALUES ('2026-04-13', 'submission', 0);
INSERT INTO sonuc (ad, durum) VALUES ('run + pending + failed_module', 'OK');


-- ---------------------------------------------------------------------------
-- 4) question_segment: bilesik FK gercekten (exam, question) uyumunu zorluyor
-- ---------------------------------------------------------------------------
INSERT INTO zeka_question_segment
  (question, exam, course, subject, bilissel_talep, dikkat_tuzagi, okuma_yuku,
   adim_sayisi, confidence_bilissel_talep, confidence_dikkat_tuzagi,
   confidence_okuma_yuku, confidence_adim_sayisi, confidence, trap_choice,
   rationale, model, prompt_version, variant, computed_at, retain_until)
VALUES ('01920000-0000-7000-8000-00000000000d',
        '01920000-0000-7000-8000-00000000000c',
        '01920000-0000-7000-8000-00000000000a',
        '01920000-0000-7000-8000-00000000000b',
        'uygulama', 'var', 'dusuk', 'tek_adim',
        0.91, 0.78, 0.95, 0.61, 'stable', 'c',
        'Turev kurali dogrudan uygulanir; c sikki ussu carpan sanan ogrenciyi ceker.',
        'deepseek-v4-pro', 'v3', NULL, 1776056400000, 1783832400000);

INSERT INTO zeka_question_segment_dimension (question, dimension, role, ord) VALUES
  ('01920000-0000-7000-8000-00000000000d', 'bilissel_talep', 'downstream', 0),
  ('01920000-0000-7000-8000-00000000000d', 'dikkat_tuzagi', 'downstream', 1),
  ('01920000-0000-7000-8000-00000000000d', 'okuma_yuku', 'downstream', 2),
  ('01920000-0000-7000-8000-00000000000d', 'adim_sayisi', 'experimental', 3);
INSERT INTO sonuc (ad, durum) VALUES ('question_segment + boyut ayrimi', 'OK');


-- ---------------------------------------------------------------------------
-- 5) student_segment_profile: contrast ve sayac kisiti
-- ---------------------------------------------------------------------------
INSERT INTO zeka_student_segment_profile
  (student, dimension, label, n_answers, n_correct, accuracy,
   overall_n_answers, overall_accuracy, contrast, confidence,
   computed_at, retain_until)
VALUES ('01920000-0000-7000-8000-000000000001', 'bilissel_talep', 'analiz',
        86, 31, 0.3605, 412, 0.5825, -0.2220, 'stable',
        1776056400000, 1807592400000);
INSERT INTO sonuc (ad, durum) VALUES ('segment_profile (contrast -0.222)', 'OK');


-- ===========================================================================
-- REDDEDILMESI GEREKENLER.
--
-- Her sinav PL/pgSQL'in KENDI ic blogunu kullanir: `BEGIN ... EXCEPTION` zaten
-- ortuk bir savepoint acar ve hata halinde YALNIZ o blogu geri alir. Acik
-- SAVEPOINT/ROLLBACK kullanilmiyor: `ROLLBACK TO SAVEPOINT` sonucu yazan
-- satiri da geri aliyordu ve yedi sinav rapora HIC ulasmiyordu. Rapor sekiz
-- test gosterip "tamami gecti" diyordu -- yani testin kendisi sessizce
-- kayboluyordu, tam da bu dosyanin yakalamak icin yazildigi hata sinifi.
--
-- `kabul` degiskeni PL/pgSQL bellegindedir; geri alma onu etkilemez, sonuc
-- satiri ic blok bittikten SONRA yazilir.
--
-- Beklenen hata turu tek tek yazilir (`check_violation` gibi). Baska bir hata
-- gelirse yakalanmaz, yukari firlar ve betigi durdurur -- yani "dogru sebeple
-- mi reddedildi" sorusu da sinaniyor.
-- ===========================================================================

-- (a) Bilinmeyen guven kademesi
DO $$
DECLARE kabul boolean := false;
BEGIN
  BEGIN
    INSERT INTO zeka_student_summary (student, confidence, computed_at, retain_until)
    VALUES ('01920000-0000-7000-8000-000000000002', 'cok_iyi', 1, 2);
    kabul := true;
  EXCEPTION WHEN check_violation THEN kabul := false;
  END;
  INSERT INTO sonuc (ad, durum) VALUES ('gecersiz confidence reddedildi',
    CASE WHEN kabul THEN 'DUSTU: kabul etti' ELSE 'OK' END);
END $$;

-- (b) Bilinmeyen bilissel etiket
DO $$
DECLARE kabul boolean := false;
BEGIN
  BEGIN
    INSERT INTO zeka_question_segment
      (question, exam, course, subject, bilissel_talep, dikkat_tuzagi, okuma_yuku,
       adim_sayisi, confidence_bilissel_talep, confidence_dikkat_tuzagi,
       confidence_okuma_yuku, confidence_adim_sayisi, confidence, rationale,
       model, prompt_version, computed_at, retain_until)
    VALUES ('01920000-0000-7000-8000-00000000000d','01920000-0000-7000-8000-00000000000c',
            '01920000-0000-7000-8000-00000000000a','01920000-0000-7000-8000-00000000000b',
            'sentez','var','dusuk','tek_adim',1,1,1,1,'stable','x','m','v',1,2);
    kabul := true;
  EXCEPTION WHEN check_violation THEN kabul := false;
  END;
  INSERT INTO sonuc (ad, durum) VALUES ('gecersiz bilissel_talep reddedildi',
    CASE WHEN kabul THEN 'DUSTU: kabul etti' ELSE 'OK' END);
END $$;

-- (c) Soru DENEME 1'e ait, segment satiri DENEME 2 diyor. Bilesik FK
--     (exam, question) -> exam_question (exam, id) bunu yakalamali.
--     Henuz segmentlenmemis IKINCI bir soru kullanilir: ilki kullanilsaydi
--     tekil anahtar once atesler, bilesik FK hic sinanmamis olurdu.
DO $$
DECLARE
  kabul       boolean := false;
  baska_sinav uuid := '01920000-0000-7000-8000-0000000000ff';
  ikinci_soru uuid := '01920000-0000-7000-8000-00000000000e';
BEGIN
  BEGIN
    INSERT INTO exam (id, creator, course, title, description, kind)
    VALUES (baska_sinav, '01920000-0000-7000-8000-000000000002',
            '01920000-0000-7000-8000-00000000000a', 'Deneme 2', '', 'quiz');
    INSERT INTO exam_question (id, exam, text, kind, points, subject)
    VALUES (ikinci_soru, '01920000-0000-7000-8000-00000000000c',
            'Ikinci soru', 'multiple_choice', 5,
            '01920000-0000-7000-8000-00000000000b');
    INSERT INTO zeka_question_segment
      (question, exam, course, subject, bilissel_talep, dikkat_tuzagi, okuma_yuku,
       adim_sayisi, confidence_bilissel_talep, confidence_dikkat_tuzagi,
       confidence_okuma_yuku, confidence_adim_sayisi, confidence, rationale,
       model, prompt_version, computed_at, retain_until)
    VALUES (ikinci_soru, baska_sinav,
            '01920000-0000-7000-8000-00000000000a','01920000-0000-7000-8000-00000000000b',
            'analiz','yok','dusuk','tek_adim',1,1,1,1,'stable','x','m','v',1,2);
    kabul := true;
  EXCEPTION WHEN foreign_key_violation THEN kabul := false;
  END;
  INSERT INTO sonuc (ad, durum) VALUES ('(exam,question) uyumsuzlugu reddedildi',
    CASE WHEN kabul THEN 'DUSTU: kabul etti' ELSE 'OK' END);
END $$;

-- (d) n_correct > n_answers: sayma hatasi
DO $$
DECLARE kabul boolean := false;
BEGIN
  BEGIN
    INSERT INTO zeka_student_segment_profile
      (student, dimension, label, n_answers, n_correct, accuracy,
       overall_n_answers, overall_accuracy, contrast, confidence, computed_at, retain_until)
    VALUES ('01920000-0000-7000-8000-000000000001','okuma_yuku','yuksek',
            10, 11, 1.0, 412, 0.58, 0.42, 'stable', 1, 2);
    kabul := true;
  EXCEPTION WHEN check_violation THEN kabul := false;
  END;
  INSERT INTO sonuc (ad, durum) VALUES ('n_correct > n_answers reddedildi',
    CASE WHEN kabul THEN 'DUSTU: kabul etti' ELSE 'OK' END);
END $$;

-- (e) Ayni ogrenciye IKINCI bir ders-bagimsiz 'homework' maddesi.
--     Iki NULL normalde birbirinden farkli sayilir; NULLS NOT DISTINCT
--     olmasaydi bu GECERDI ve dikkat listesi cogalirdi.
DO $$
DECLARE kabul boolean := false;
BEGIN
  BEGIN
    INSERT INTO zeka_attention_item
      (student, trigger, course, fact, window_from, window_to, evidence, ord)
    VALUES ('01920000-0000-7000-8000-000000000001', 'homework', NULL,
            'ikinci madde', 1, 2, '{"x":1}'::jsonb, 2);
    kabul := true;
  EXCEPTION WHEN unique_violation THEN kabul := false;
  END;
  INSERT INTO sonuc (ad, durum) VALUES ('mukerrer (course NULL) madde reddedildi',
    CASE WHEN kabul THEN 'DUSTU: kabul etti' ELSE 'OK' END);
END $$;

-- (f) Olmayan ogrenci
DO $$
DECLARE kabul boolean := false;
BEGIN
  BEGIN
    INSERT INTO zeka_student_summary (student, confidence, computed_at, retain_until)
    VALUES ('01920000-0000-7000-8000-0000000000ee', 'stable', 1, 2);
    kabul := true;
  EXCEPTION WHEN foreign_key_violation THEN kabul := false;
  END;
  INSERT INTO sonuc (ad, durum) VALUES ('olmayan ogrenci reddedildi',
    CASE WHEN kabul THEN 'DUSTU: kabul etti' ELSE 'OK' END);
END $$;

-- (g) Gecersiz gun bicimi
DO $$
DECLARE kabul boolean := false;
BEGIN
  BEGIN
    INSERT INTO zeka_run (run_day, started_at, status, budget_ms, retain_until)
    VALUES ('13.04.2026', 1, 'ok', 1, 2);
    kabul := true;
  EXCEPTION WHEN check_violation THEN kabul := false;
  END;
  INSERT INTO sonuc (ad, durum) VALUES ('gecersiz run_day reddedildi',
    CASE WHEN kabul THEN 'DUSTU: kabul etti' ELSE 'OK' END);
END $$;

-- (h) Kanitsiz tavsiye. "Aciklanamayan tavsiye gosterilmez" kuralinin
--     semadaki karsiligi: evidence NOT NULL.
DO $$
DECLARE kabul boolean := false;
BEGIN
  BEGIN
    INSERT INTO zeka_recommendation
      (id, audience, product, rule_id, rule_version, audience_role,
       evidence, confidence, created_at, expires_at, retain_until)
    VALUES ('01920000-0000-7000-8000-000000000103',
            '01920000-0000-7000-8000-000000000001', 'O1', 'O1.kanitsiz', 1,
            'student', NULL, 'stable', 1, 2, 3);
    kabul := true;
  EXCEPTION WHEN not_null_violation THEN kabul := false;
  END;
  INSERT INTO sonuc (ad, durum) VALUES ('kanitsiz tavsiye reddedildi',
    CASE WHEN kabul THEN 'DUSTU: kabul etti' ELSE 'OK' END);
END $$;

-- (i) contrast araligi disi: accuracy - overall_accuracy en fazla 1 olabilir.
DO $$
DECLARE kabul boolean := false;
BEGIN
  BEGIN
    INSERT INTO zeka_student_segment_profile
      (student, dimension, label, n_answers, n_correct, accuracy,
       overall_n_answers, overall_accuracy, contrast, confidence, computed_at, retain_until)
    VALUES ('01920000-0000-7000-8000-000000000001','dikkat_tuzagi','var',
            10, 8, 0.8, 412, 0.58, 1.9, 'stable', 1, 2);
    kabul := true;
  EXCEPTION WHEN check_violation THEN kabul := false;
  END;
  INSERT INTO sonuc (ad, durum) VALUES ('contrast araligi disi reddedildi',
    CASE WHEN kabul THEN 'DUSTU: kabul etti' ELSE 'OK' END);
END $$;

-- (j) Deneysel boyut ogrenci profiline SIZAMAZ: `adim_sayisi` yalnizca
--     question_segment'te etiketlenir ve hicbir ogrenciye baglanmaz. Bu, bir
--     olcum kararinin (0,607 kararlilik, uretime alinmadi) semadaki karsiligi.
DO $$
DECLARE kabul boolean := false;
BEGIN
  BEGIN
    INSERT INTO zeka_student_segment_profile
      (student, dimension, label, n_answers, n_correct, accuracy,
       overall_n_answers, overall_accuracy, contrast, confidence, computed_at, retain_until)
    VALUES ('01920000-0000-7000-8000-000000000001','adim_sayisi','cok_adim',
            10, 8, 0.8, 412, 0.58, 0.22, 'stable', 1, 2);
    kabul := true;
  EXCEPTION WHEN check_violation THEN kabul := false;
  END;
  INSERT INTO sonuc (ad, durum) VALUES ('deneysel boyut profile sizamadi',
    CASE WHEN kabul THEN 'DUSTU: kabul etti' ELSE 'OK' END);
END $$;

-- (k) AYNI ogretmen, AYNI kural, FARKLI iki ogrenci -> IKI satir.
--     Dogal anahtar `about` tasimasaydi ikisi tek satira coker, ogretmen bir
--     ogrenci gorur, digeri hicbir hata vermeden kaybolurdu. SurrealDB surumu
--     tam boyle davraniyordu: olculdu, bes ogrenci -> bir anahtar.
INSERT INTO zeka_recommendation
  (id, audience, product, rule_id, rule_version, scope, about, audience_role,
   course, evidence, confidence, created_at, expires_at, retain_until)
VALUES
  ('01920000-0000-7000-8000-000000000201',
   '01920000-0000-7000-8000-000000000002', 'T4', 'T4.attendance', 3,
   '01920000-0000-7000-8000-00000000000a',
   '01920000-0000-7000-8000-000000000001', 'teacher', NULL,
   '{"n":1}'::jsonb, 'stable', 1, 2, 3),
  ('01920000-0000-7000-8000-000000000202',
   '01920000-0000-7000-8000-000000000002', 'T4', 'T4.attendance', 3,
   '01920000-0000-7000-8000-00000000000a',
   '01920000-0000-7000-8000-000000000002', 'teacher', NULL,
   '{"n":2}'::jsonb, 'stable', 1, 2, 3);

INSERT INTO sonuc (ad, durum)
SELECT 'ayni kural iki ogrenci icin IKI satir',
       CASE WHEN count(*) = 2 THEN 'OK' ELSE 'DUSTU: ' || count(*) END
  FROM zeka_recommendation WHERE rule_id = 'T4.attendance';


-- ---------------------------------------------------------------------------
-- Rapor
-- ---------------------------------------------------------------------------
\echo ''
\echo '== davranis sinavi'
\pset tuples_only on
\pset format unaligned
SELECT lpad(sira::text, 2) || '. ' || rpad(ad, 50) || ' ' || durum FROM sonuc ORDER BY sira;
\pset tuples_only off
\pset format aligned

\echo ''
DO $$
DECLARE d int;
BEGIN
  SELECT count(*) INTO d FROM sonuc WHERE durum <> 'OK';
  IF d > 0 THEN RAISE EXCEPTION '% adet davranis testi dustu', d; END IF;
  RAISE NOTICE 'davranis sinavi: % testin tamami gecti', (SELECT count(*) FROM sonuc);
END $$;

ROLLBACK;
