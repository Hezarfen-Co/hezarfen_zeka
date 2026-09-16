-- Yuklenmis tohumun butunluk sinavi (PostgreSQL).
--
-- `seed/99_dogrula.surql`'deki 48 denetimin karsiligi. HARFI HARFINE CEVIRI
-- DEGIL: SurrealQL'in graf gezinmesi (`question.text`), `NOTINSIDE` ve
-- `type::record` deyimlerinin Postgres'te karsiligi yok; her denetim burada
-- ayni SORUYU sorar, kendi dilinde.
--
-- Okuma: her satir ihlal SAYISIDIR ve SIFIR olmalidir. Sonda sifirdan buyuk
-- bir sayi varsa betik hata ile duser.
--
---------------------------------------------------------------------------
-- SEMANIN ZORLADIGI DENETIMLER
---------------------------------------------------------------------------
-- Bes denetim (I1, I7, I9, I13, I48) yeni semada ARTIK IHLAL EDILEMEZ:
-- yabanci anahtarlar, kismi tekil indeksler ve kolonun hic var olmamasi bunu
-- yapisal olarak imkansiz kiliyor. Yine de listede duruyorlar ve ne ile
-- zorlandiklari yaninda yaziyor.
--
-- Bunlari "gecti" diye saymak yerine ayri isaretlemek onemli: sifir donduren
-- bir sorgu, bir seyi ispatladigi icin degil, sorulmasi imkansiz hale
-- geldigi icin de sifir donebilir. Ikisi ayni sey degil.

\set ON_ERROR_STOP on

\set t_now   1776056400000
\set t_start 1757278800000
\set t_end   1781902740000

CREATE TEMP TABLE sonuc (
    sira  int GENERATED ALWAYS AS IDENTITY,
    kod   text,
    baslik text,
    ihlal bigint,
    not_  text DEFAULT ''
);

-- ===========================================================================
-- Sinav / cevap butunlugu
-- ===========================================================================

INSERT INTO sonuc (kod, baslik, ihlal, not_)
SELECT 'I1', 'exam_answer -> exam_question kopuk', count(*),
       'FK exam_answer_exam_question_fkey zorluyor'
  FROM exam_answer a
  LEFT JOIN exam_question q ON q.id = a.question AND q.exam = a.exam
 WHERE q.id IS NULL;

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I2', 'exam_answer.seq ile eslesen exam_attempt yok', count(*)
  FROM exam_answer a
  LEFT JOIN exam_attempt t
         ON t.exam = a.exam AND t.app_user = a.app_user AND t.seq = a.seq
 WHERE t.exam IS NULL;

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I3', 'selected degeri sorunun choices[].id kumesinde degil', count(*)
  FROM exam_answer a JOIN exam_question q ON q.id = a.question
 WHERE a.selected IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(coalesce(q.choices,'[]'::jsonb)) c
                    WHERE c->>'id' = a.selected);

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I4', 'kind=text soruda selected dolu', count(*)
  FROM exam_answer a JOIN exam_question q ON q.id = a.question
 WHERE q.kind = 'text' AND a.selected IS NOT NULL;

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I5', 'kind=choice soruda text dolu', count(*)
  FROM exam_answer a JOIN exam_question q ON q.id = a.question
 WHERE q.kind = 'choice' AND a.text IS NOT NULL;

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I6', 'kind=choice soruda correct/choices bos', count(*)
  FROM exam_question
 WHERE kind = 'choice'
   AND (correct IS NULL OR choices IS NULL OR jsonb_array_length(choices) = 0);

INSERT INTO sonuc (kod, baslik, ihlal, not_)
SELECT 'I7', 'seq=1 kaydin kimliginde _1 eki', 0,
       'kimlik artik uuid; metin anahtar deseni yok';

-- ===========================================================================
-- Odev / calisma
-- ===========================================================================

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I8', 'submitted_at > updated_at', count(*)
  FROM homework_submission WHERE submitted_at > updated_at;

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I9', 'homework_result var ama submission yok', count(*)
  FROM homework_result r
  LEFT JOIN homework_submission s
         ON s.homework = r.homework AND s.app_user = r.app_user
 WHERE r.status <> 'missing' AND s.id IS NULL;

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I10', 'pomodoro finished_at < started_at', count(*)
  FROM pomodoro_session WHERE finished_at IS NOT NULL AND finished_at < started_at;

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I11', 'counted=true ama sure < 300.000 ms', count(*)
  FROM pomodoro_session
 WHERE counted AND (finished_at IS NULL OR finished_at - started_at < 300000);

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I12', 'ayni UTC gununde counted>16 olan (ogrenci, gun)', count(*)
  FROM (SELECT app_user, started_at / 86400000 AS gun
          FROM pomodoro_session WHERE counted
         GROUP BY app_user, started_at / 86400000
        HAVING count(*) > 16) x;

INSERT INTO sonuc (kod, baslik, ihlal, not_)
SELECT 'I13', 'kullanici basina birden fazla ACIK pomodoro', count(*),
       'kismi tekil indeks pomodoro_session_open_stint zorluyor'
  FROM (SELECT app_user FROM pomodoro_session WHERE finished_at IS NULL
         GROUP BY app_user HAVING count(*) > 1) x;

-- ===========================================================================
-- Sozluk / kume kisitlari
-- ===========================================================================

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I14', 'session_attendance.status sozluk disi', count(*)
  FROM session_attendance
 WHERE status NOT IN (SELECT status FROM settings_attendance_status);

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I15', 'exam.kind sozluk disi', count(*)
  FROM exam WHERE kind NOT IN (
      SELECT e->>'name' FROM settings s, jsonb_array_elements(s.exam_kinds) e);

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I16', 'menu.slot sozluk disi', count(*)
  FROM menu WHERE slot NOT IN (SELECT name FROM slot_ref);

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I17', 'meal_attendance.status sozluk disi', count(*)
  FROM meal_attendance WHERE status NOT IN ('served', 'missed');

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I18', 'homework_result.status sozluk disi', count(*)
  FROM homework_result WHERE status NOT IN ('done', 'incomplete', 'missing');

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I19', 'board_stroke.kind sozluk disi', count(*)
  FROM board_stroke WHERE kind NOT IN ('stroke', 'clear');

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I20', 'pool_question.status sozluk disi', count(*)
  FROM pool_question WHERE status NOT IN ('pending', 'approved');

-- @ROZET_KATALOGU@

-- ===========================================================================
-- Capraz tutarlilik
-- ===========================================================================

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I23', 'exam_question.subject.course != exam.course', count(*)
  FROM exam_question q JOIN subject s ON s.id = q.subject
                       JOIN exam e ON e.id = q.exam
 WHERE s.course <> e.course;

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I24', 'homework.subject.course != homework.course', count(*)
  FROM homework h JOIN subject s ON s.id = h.subject
 WHERE s.course <> h.course;

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I25', 'ogrenci/veliden ogrenci/veliye mesaj', count(*)
  FROM message m JOIN app_user a ON a.id = m.sender
                 JOIN app_user b ON b.id = m.recipient
 WHERE a.role IN ('student', 'parent') AND b.role IN ('student', 'parent');

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I26', 'veli randevusu ama parent_link yok', count(*)
  FROM appointment ap JOIN app_user u ON u.id = ap.requester
 WHERE u.role = 'parent'
   AND NOT EXISTS (SELECT 1 FROM parent_link p WHERE p.parent = ap.requester);

-- ===========================================================================
-- Sayac alanlari — gercek sayiyla ayni mi
-- ===========================================================================

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I27', 'course.enrollment_count yanlis', count(*) FROM course c
 WHERE c.enrollment_count <> (SELECT count(*) FROM enrollment e WHERE e.course = c.id);

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I28', 'subject.exam_question_count yanlis', count(*) FROM subject s
 WHERE s.exam_question_count <> (SELECT count(*) FROM exam_question q WHERE q.subject = s.id);

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I29', 'subject.homework_count yanlis', count(*) FROM subject s
 WHERE s.homework_count <> (SELECT count(*) FROM homework h WHERE h.subject = s.id);

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I30', 'exam.result_count yanlis', count(*) FROM exam e
 WHERE e.result_count <> (SELECT count(*) FROM exam_result r WHERE r.exam = e.id);

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I31', 'class_group sayaclari yanlis', count(*) FROM class_group g
 WHERE g.class_member_count <> (SELECT count(*) FROM class_member m WHERE m.class = g.id)
    OR g.class_course_count <> (SELECT count(*) FROM class_course c WHERE c.class = g.id);

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I32', 'term sayaclari yanlis', count(*) FROM term t
 WHERE t.course_count <> (SELECT count(*) FROM course c WHERE c.term = t.id)
    OR t.class_count  <> (SELECT count(*) FROM class_group g WHERE g.term = t.id);

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I33', 'menu.seats_booked yanlis', count(*) FROM menu m
 WHERE m.seats_booked <> (SELECT count(*) FROM meal_booking b
                           WHERE b.menu = m.id AND b.status = 'booked');

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I34', 'event.registration_count yanlis', count(*) FROM event e
 WHERE e.registration_count <> (SELECT count(*) FROM registration r WHERE r.event = e.id);

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I35', 'fee_plan.assignment_count yanlis', count(*) FROM fee_plan f
 WHERE f.assignment_count <> (SELECT count(*) FROM fee_plan_assignment a WHERE a.plan = f.id);

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I36', 'board vurus sayaclari yanlis', count(*) FROM board b
 WHERE b.total_stroke_count <> (SELECT count(*) FROM board_stroke s WHERE s.board = b.id)
    OR b.epoch_stroke_count <> (SELECT count(*) FROM board_stroke s
                                 WHERE s.board = b.id AND s.epoch = b.epoch);

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I37', 'app_user thread/board sayaclari yanlis', count(*) FROM app_user u
 WHERE u.chatbot_thread_count <> (SELECT count(*) FROM chatbot_thread t WHERE t.user_id = u.id)
    OR u.board_count <> (SELECT count(*) FROM board b WHERE b.creator = u.id);

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I38', 'note / submission file_count yanlis', count(*) FROM (
  SELECT 1 FROM note n
   WHERE n.file_count <> (SELECT count(*) FROM note_file f WHERE f.note = n.id)
  UNION ALL
  SELECT 1 FROM homework_submission s
   WHERE s.file_count <> (SELECT count(*) FROM homework_file f WHERE f.submission = s.id)) x;

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I39', 'gun numarasi alanina ms yazilmis', count(*) FROM app_user
 WHERE coalesce(study_streak_last_day, 0) > 100000000
    OR coalesce(pomodoro_counted_day, 0) > 100000000;

-- ===========================================================================
-- Zaman sinirlari
-- ===========================================================================

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I40', 'T_NOW sonrasi satir', count(*) FROM (
  SELECT 1 FROM course_session WHERE starts_at > :t_now
  UNION ALL SELECT 1 FROM exam_answer WHERE updated_at > :t_now
  UNION ALL SELECT 1 FROM pomodoro_session WHERE started_at > :t_now) x;

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I41', 'donem sonundan sonraki satir', count(*) FROM (
  SELECT 1 FROM exam WHERE starts_at > :t_end
  UNION ALL SELECT 1 FROM homework WHERE due_at > :t_end
  UNION ALL SELECT 1 FROM event WHERE starts_at > :t_end) x;

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I42', 'donem basindan onceki satir', count(*) FROM (
  SELECT 1 FROM course_session WHERE starts_at < :t_start
  UNION ALL SELECT 1 FROM exam WHERE starts_at < :t_start
  UNION ALL SELECT 1 FROM pomodoro_session WHERE started_at < :t_start) x;

-- ===========================================================================
-- Deger araliklari
-- ===========================================================================

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I43', 'not degeri 0..100 disinda', count(*) FROM (
  SELECT 1 FROM exam_result WHERE mark < 0 OR mark > 100
  UNION ALL SELECT 1 FROM homework_result
             WHERE mark IS NOT NULL AND (mark < 0 OR mark > 100)) x;

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I44', 'exam_question.points 1..100 disinda', count(*)
  FROM exam_question WHERE points < 1 OR points > 100;

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I45', 'bir sinavin puan toplami != 100', count(*)
  FROM (SELECT exam FROM exam_question GROUP BY exam HAVING sum(points) <> 100) x;

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I46', '*_minor alani negatif veya asiri', count(*) FROM (
  SELECT 1 FROM menu_dish WHERE price_minor < 0 OR price_minor > 1000000
  UNION ALL SELECT 1 FROM meal_ledger WHERE amount_minor < 0 OR amount_minor > 10000000
  UNION ALL SELECT 1 FROM payment_ledger WHERE amount_minor < 0 OR amount_minor > 10000000) x;

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I47', 'menu.date uzunlugu != 10', count(*) FROM menu WHERE length(date) <> 10;

INSERT INTO sonuc (kod, baslik, ihlal, not_)
SELECT 'I48', 'emekli alana yazim (source_bank, audience.users)', 0,
       'kolonlar semada hic yok; DDL zorluyor';

-- ===========================================================================
-- Rapor
-- ===========================================================================
\echo ''
\echo '== tohum butunluk sinavi (PostgreSQL)'
\pset tuples_only on
\pset format unaligned
SELECT lpad(sira::text, 2) || '. ' || rpad(kod, 5) || rpad(baslik, 52) || ' ' ||
       CASE WHEN ihlal = 0 THEN 'OK' ELSE 'IHLAL ' || ihlal END ||
       CASE WHEN not_ <> '' THEN '   [' || not_ || ']' ELSE '' END
  FROM sonuc ORDER BY sira;
\pset tuples_only off
\pset format aligned

\echo ''
DO $$
DECLARE d bigint; n bigint;
BEGIN
  SELECT count(*), coalesce(sum(ihlal), 0) INTO n, d FROM sonuc WHERE ihlal > 0;
  IF n > 0 THEN
    RAISE EXCEPTION '% denetim ihlal buldu (toplam % satir)', n, d;
  END IF;
  RAISE NOTICE 'butunluk sinavi: % denetimin tamami temiz', (SELECT count(*) FROM sonuc);
END $$;
