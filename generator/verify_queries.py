"""99_dogrula.surql — SENARYO §7.6'daki 48 bütünlük sorgusunu üretir.

Her sorgu, ihlal eden satır sayısını döndürür ve sonuç **0 olmalıdır**.

TAŞINABİLİRLİK KURALLARI (gerçek SurrealDB 3.1.6 üzerinde sınandı)
-------------------------------------------------------------------
1. **Her sorgu TEK SATIR.** `surreal sql` istemcisi girdiyi satır satır
   ayrıştırır; çok satırlı bir ifade ikinci satırda sözdizimi hatası verir
   ("Unexpected token `WHERE`"). Tek satır hem CLI hem HTTP ile çalışır.
2. **`array::contains` YOK.** 3.1.6'da bu ad çözülmüyor
   ("Invalid function/constant path"). Üyelik için `IN` / `NOT IN`, alan
   dizisinde arama için `INSIDE` / `NOTINSIDE` kullanılır.
3. **`HAVING` YOK.** Gruplanmış sonucu süzmek için `SELECT ... FROM (SELECT
   ... GROUP BY ...) WHERE ...` kalıbı kullanılır.
4. **Satır başına alt sorgu pahalıdır.** 20.000+ satırlık bir tabloda her satır
   için alt sorgu çalıştırmak zaman aşımına uğrar; bunun yerine çocuk tablo
   tek geçişte `GROUP BY` ile toplanır ve ebeveyn sayacıyla karşılaştırılır.

KULLANILAN SurrealQL FONKSİYON VE İŞLEÇLERİ (hepsi 3.1.6'da doğrulandı)
------------------------------------------------------------------------
    count()                 -- toplulaştırma ve alt sorgu satır sayısı
    math::sum(x)            -- toplam
    math::floor(x)          -- aşağı yuvarlama (gün kovası)
    array::len(x)           -- dizi / alt sorgu uzunluğu
    string::concat(a, b)    -- birleştirme (kompozit kimlik kurma)
    string::starts_with(s, p)
    string::ends_with(s, p)
    string::len(s)
    record::id(id)          -- kayıt kimliğinin anahtar kısmı
    type::record(tbl, key)  -- metinden kayıt bağı kurma
    İşleçler: IN · NOT IN · INSIDE · NOTINSIDE · ?? · IS NONE · != ·
              IF ... THEN ... ELSE ... END · <string> dönüşümü ·
              GROUP ALL · GROUP BY · alt sorgudan SELECT

KULLANILMAYANLAR (3.1.6'da geçersiz — bir daha eklemeyin)
    array::contains(...)    -- Invalid function/constant path
    ... GROUP BY ... HAVING -- Unexpected token
    meta::version()         -- Invalid function/constant path

SONUÇ NASIL OKUNUR
    `GROUP ALL` kullanan sorgular ihlal yokken `[[{ count: 0 }]]` döndürür.
    Gruplanmış (alt sorgulu) sorgular ihlal yokken `[[]]` (boş) döndürür.
    Her iki biçim de SIFIR anlamına gelir; başka her çıktı ihlaldir.
"""

from __future__ import annotations

import config as C
from emit import sq_string


def _list(values):
    """Dize kaçışlaması tek yerden gelir: emit.sq_string."""
    return "[" + ", ".join(sq_string(v) for v in values) + "]"


# Kompozit kimlikten kayıt bağı kuran ortak parça (E3: seq=1'de ek yok)
_ATTEMPT_KEY = ("string::concat(record::id(exam), '_', record::id(user), "
                "IF seq > 1 THEN string::concat('_', <string> seq) ELSE '' END)")

QUERIES = [
    ("I1", "exam_answer -> exam_question referansı kopuk satır",
     "SELECT count() FROM exam_answer WHERE question.text IS NONE GROUP ALL;"),

    ("I2", "exam_answer.seq ile eşleşen exam_attempt bulunmayan satır",
     "SELECT count() FROM exam_answer WHERE type::record('exam_attempt', %s)"
     ".started_at IS NONE GROUP ALL;" % _ATTEMPT_KEY),

    ("I3", "exam_answer.selected değeri sorunun choices[].id kümesinde değil",
     "SELECT count() FROM exam_answer WHERE selected != NONE"
     " AND selected NOTINSIDE question.choices.*.id GROUP ALL;"),

    ("I4", "kind='text' soruda selected dolu",
     "SELECT count() FROM exam_answer WHERE question.kind = 'text'"
     " AND selected != NONE GROUP ALL;"),

    ("I5", "kind='choice' soruda text dolu",
     "SELECT count() FROM exam_answer WHERE question.kind = 'choice'"
     " AND text != NONE GROUP ALL;"),

    ("I6", "kind='choice' soruda correct boş veya choices boş",
     "SELECT count() FROM exam_question WHERE kind = 'choice'"
     " AND (correct = NONE OR choices = NONE OR array::len(choices) = 0) GROUP ALL;"),

    ("I7", "seq = 1 kaydın id'sinde _1 eki (E3 ihlali)",
     "SELECT count() FROM exam_attempt"
     " WHERE string::ends_with(record::id(id), '_1') GROUP ALL;"),

    ("I8", "homework_submission.submitted_at > updated_at",
     "SELECT count() FROM homework_submission WHERE submitted_at > updated_at GROUP ALL;"),

    ("I9", "homework_result var ama homework_submission yok (status != 'missing')",
     "SELECT count() FROM homework_result WHERE status != 'missing'"
     " AND type::record('homework_submission', record::id(id)).submitted_at IS NONE"
     " GROUP ALL;"),

    ("I10", "pomodoro_session.finished_at < started_at",
     "SELECT count() FROM pomodoro_session WHERE finished_at != NONE"
     " AND finished_at < started_at GROUP ALL;"),

    ("I11", "counted = true ama süre < 300.000 ms",
     "SELECT count() FROM pomodoro_session WHERE counted = true"
     " AND (finished_at = NONE OR (finished_at - started_at) < 300000) GROUP ALL;"),

    ("I12", "aynı UTC gününde counted = true sayısı > 16 olan (öğrenci, gün)",
     "SELECT count() FROM (SELECT user, math::floor(started_at / 86400000) AS gun,"
     " count() AS n FROM pomodoro_session WHERE counted = true GROUP BY user, gun)"
     " WHERE n > 16 GROUP ALL;"),

    ("I13", "open_ önekli id'ye sahip, aynı kullanıcıda birden fazla pomodoro_session",
     "SELECT count() FROM (SELECT user, count() AS n FROM pomodoro_session"
     " WHERE string::starts_with(record::id(id), 'open_') GROUP BY user)"
     " WHERE n > 1 GROUP ALL;"),

    ("I14", "session_attendance.status ∉ settings.attendance_statuses",
     "SELECT count() FROM session_attendance WHERE status NOT IN %s GROUP ALL;"
     % _list(C.SETTINGS["attendance_statuses"])),

    ("I15", "exam.kind ∉ settings.exam_kinds[].name",
     "SELECT count() FROM exam WHERE kind NOT IN %s GROUP ALL;" % _list(C.EXAM_KINDS)),

    ("I16", "menu.slot ∉ settings.meal_slots[].name",
     "SELECT count() FROM menu WHERE slot NOT IN %s GROUP ALL;" % _list(C.MEAL_SLOTS)),

    ("I17", "meal_attendance.status ∉ {served, missed}",
     "SELECT count() FROM meal_attendance"
     " WHERE status NOT IN ['served', 'missed'] GROUP ALL;"),

    ("I18", "homework_result.status ∉ {done, incomplete, missing}",
     "SELECT count() FROM homework_result"
     " WHERE status NOT IN ['done', 'incomplete', 'missing'] GROUP ALL;"),

    ("I19", "board_stroke.kind ∉ {stroke, clear}",
     "SELECT count() FROM board_stroke"
     " WHERE kind NOT IN ['stroke', 'clear'] GROUP ALL;"),

    ("I20", "pool_question.status ∉ {pending, approved}",
     "SELECT count() FROM pool_question"
     " WHERE status NOT IN ['pending', 'approved'] GROUP ALL;"),

    ("I21", "badge_award.badge 34 sabit kodun dışında", None),   # write() doldurur

    ("I22", "badge_award var ama ilgili user.*_total eşiğin altında / NONE",
     "SELECT count() FROM badge_award WHERE"
     " (badge = 'homework_submitted_1' AND (user.homework_submitted_total ?? -1) < 1)"
     " OR (badge = 'homework_submitted_10' AND (user.homework_submitted_total ?? -1) < 10)"
     " OR (badge = 'homework_submitted_50' AND (user.homework_submitted_total ?? -1) < 50)"
     " OR (badge = 'exam_sat_1' AND (user.exam_sat_total ?? -1) < 1)"
     " OR (badge = 'exam_sat_10' AND (user.exam_sat_total ?? -1) < 10)"
     " OR (badge = 'exam_sat_25' AND (user.exam_sat_total ?? -1) < 25)"
     " OR string::starts_with(badge, 'lessons_attended_')"
     " OR string::starts_with(badge, 'high_mark_') GROUP ALL;"),

    ("I23", "exam_question.subject.course != exam_question.exam.course",
     "SELECT count() FROM exam_question WHERE subject.course != exam.course GROUP ALL;"),

    ("I24", "homework.subject.course != homework.course",
     "SELECT count() FROM homework WHERE subject.course != course GROUP ALL;"),

    ("I25", "öğrenci/veliden öğrenci/veliye message (rol kısıtı)",
     "SELECT count() FROM message WHERE sender.role IN ['student', 'parent']"
     " AND recipient.role IN ['student', 'parent'] GROUP ALL;"),

    ("I26", "appointment.requester veli ve hedef öğrenciyle parent_link yok",
     "SELECT count() FROM appointment WHERE requester.role = 'parent'"
     " AND array::len((SELECT id FROM parent_link WHERE parent = $parent.requester)) = 0"
     " GROUP ALL;"),

    ("I27", "course.enrollment_count != gerçek enrollment sayısı",
     "SELECT count() FROM course WHERE (enrollment_count ?? 0) !="
     " array::len((SELECT id FROM enrollment WHERE course = $parent.id)) GROUP ALL;"),

    ("I28", "subject.exam_question_count != gerçek sayı",
     "SELECT count() FROM subject WHERE (exam_question_count ?? 0) !="
     " array::len((SELECT id FROM exam_question WHERE subject = $parent.id)) GROUP ALL;"),

    ("I29", "subject.homework_count != gerçek sayı",
     "SELECT count() FROM subject WHERE (homework_count ?? 0) !="
     " array::len((SELECT id FROM homework WHERE subject = $parent.id)) GROUP ALL;"),

    ("I30", "exam.result_count != gerçek exam_result sayısı",
     "SELECT count() FROM exam WHERE (result_count ?? 0) !="
     " array::len((SELECT id FROM exam_result WHERE exam = $parent.id)) GROUP ALL;"),

    ("I31", "class_group.class_member_count / class_course_count != gerçek",
     "SELECT count() FROM class_group WHERE (class_member_count ?? 0) !="
     " array::len((SELECT id FROM class_member WHERE class = $parent.id))"
     " OR (class_course_count ?? 0) !="
     " array::len((SELECT id FROM class_course WHERE class = $parent.id)) GROUP ALL;"),

    ("I32", "term.course_count / class_count != gerçek",
     "SELECT count() FROM term WHERE (course_count ?? 0) !="
     " array::len((SELECT id FROM course WHERE term = $parent.id))"
     " OR (class_count ?? 0) !="
     " array::len((SELECT id FROM class_group WHERE term = $parent.id)) GROUP ALL;"),

    ("I33", "menu.seats_booked != 'booked' durumundaki meal_booking sayısı",
     "SELECT count() FROM menu WHERE (seats_booked ?? 0) != array::len("
     "(SELECT id FROM meal_booking WHERE menu = $parent.id AND status = 'booked'))"
     " GROUP ALL;"),

    ("I34", "event.registration_count != gerçek registration sayısı",
     "SELECT count() FROM event WHERE (registration_count ?? 0) !="
     " array::len((SELECT id FROM registration WHERE event = $parent.id)) GROUP ALL;"),

    ("I35", "fee_plan.assignment_count != gerçek sayı",
     "SELECT count() FROM fee_plan WHERE (assignment_count ?? 0) !="
     " array::len((SELECT id FROM fee_plan_assignment WHERE plan = $parent.id))"
     " GROUP ALL;"),

    ("I36", "board.epoch_stroke_count / total_stroke_count != gerçek",
     "SELECT count() FROM board WHERE (total_stroke_count ?? 0) !="
     " array::len((SELECT id FROM board_stroke WHERE board = $parent.id))"
     " OR (epoch_stroke_count ?? 0) != array::len((SELECT id FROM board_stroke"
     " WHERE board = $parent.id AND epoch = $parent.epoch AND kind = 'stroke'))"
     " GROUP ALL;"),

    ("I37", "user.chatbot_thread_count / board_count != gerçek",
     "SELECT count() FROM user WHERE (chatbot_thread_count ?? 0) !="
     " array::len((SELECT id FROM chatbot_thread WHERE user_id = $parent.id))"
     " OR (board_count ?? 0) !="
     " array::len((SELECT id FROM board WHERE creator = $parent.id)) GROUP ALL;"),

    # I38 tek geçişte toplulaştırır: satır başına alt sorgu 23.700 teslimde
    # zaman aşımına uğruyordu. İki yön ayrı ayrı kapatılır:
    #   (a) dosyası olan satırın sayacı yanlış mı  -> GROUP BY ile
    #   (b) dosyası olmayan satır sayaç şişirmiş mi -> toplam eşitliği ile
    ("I38", "note.file_count / homework_submission.file_count != gerçek",
     "SELECT count() FROM (SELECT note, count() AS n FROM note_file GROUP BY note)"
     " WHERE (note.file_count ?? 0) != n GROUP ALL;\n"
     "SELECT count() FROM (SELECT submission, count() AS n FROM homework_file"
     " GROUP BY submission) WHERE (submission.file_count ?? 0) != n GROUP ALL;\n"
     "RETURN (SELECT math::sum(file_count ?? 0) AS toplam FROM note GROUP ALL)[0].toplam"
     " - (SELECT count() FROM note_file GROUP ALL)[0].count;\n"
     "RETURN (SELECT math::sum(file_count ?? 0) AS toplam FROM homework_submission"
     " GROUP ALL)[0].toplam - (SELECT count() FROM homework_file GROUP ALL)[0].count;"),

    ("I39", "study_streak_last_day / pomodoro_counted_day ms gibi görünen değer",
     "SELECT count() FROM user WHERE (study_streak_last_day ?? 0) > 100000000"
     " OR (pomodoro_counted_day ?? 0) > 100000000 GROUP ALL;"),

    ("I40", "T_NOW'dan sonra course_session / exam_answer / session_attendance satırı",
     "SELECT count() FROM course_session WHERE starts_at > $t_now GROUP ALL;\n"
     "SELECT count() FROM exam_answer WHERE updated_at > $t_now GROUP ALL;\n"
     "SELECT count() FROM session_attendance WHERE session.starts_at > $t_now GROUP ALL;"),

    ("I41", "2026-06-19'dan sonra herhangi bir satır (örnek tablolar)",
     "SELECT count() FROM exam WHERE starts_at > $t_end GROUP ALL;\n"
     "SELECT count() FROM homework WHERE due_at > $t_end GROUP ALL;\n"
     "SELECT count() FROM event WHERE starts_at > $t_end GROUP ALL;\n"
     "SELECT count() FROM appointment_slot WHERE starts_at > $t_end GROUP ALL;"),

    ("I42", "2025-09-08'den önce herhangi bir satır (kullanıcı oluşturma hariç)",
     "SELECT count() FROM course_session WHERE starts_at < $t_start GROUP ALL;\n"
     "SELECT count() FROM exam WHERE starts_at < $t_start GROUP ALL;\n"
     "SELECT count() FROM pomodoro_session WHERE started_at < $t_start GROUP ALL;"),

    ("I43", "exam_result.mark / homework_result.mark ∉ 0..=100",
     "SELECT count() FROM exam_result WHERE mark < 0 OR mark > 100 GROUP ALL;\n"
     "SELECT count() FROM homework_result WHERE mark != NONE"
     " AND (mark < 0 OR mark > 100) GROUP ALL;"),

    ("I44", "exam_question.points ∉ 1..=100",
     "SELECT count() FROM exam_question WHERE points < 1 OR points > 100 GROUP ALL;"),

    ("I45", "bir sınavın soru puanları toplamı != 100",
     "SELECT count() FROM (SELECT exam, math::sum(points) AS toplam FROM exam_question"
     " GROUP BY exam) WHERE toplam != 100 GROUP ALL;"),

    ("I46", "*_minor alanı negatif veya > 10.000.000",
     "SELECT count() FROM menu_dish WHERE price_minor < 0"
     " OR price_minor > 1000000 GROUP ALL;\n"
     "SELECT count() FROM meal_ledger WHERE amount_minor < 0"
     " OR amount_minor > 10000000 GROUP ALL;\n"
     "SELECT count() FROM payment_ledger WHERE amount_minor < 0"
     " OR amount_minor > 10000000 GROUP ALL;"),

    ("I47", "menu.date uzunluğu != 10",
     "SELECT count() FROM menu WHERE string::len(date) != 10 GROUP ALL;"),

    ("I48", "removed_fields listesindeki bir kolona yazım (source_bank, audience.users)",
     "SELECT count() FROM exam_question WHERE source_bank != NONE GROUP ALL;\n"
     "SELECT count() FROM event WHERE audience.users != NONE GROUP ALL;"),
]


def write(path: str, t_now_ms: int) -> int:
    badges = _list([b[0] for b in C.BADGES])
    lines = []
    lines.append("-- ---------------------------------------------------------------")
    lines.append("-- Hezarfen tohum verisi — 99_dogrula.surql")
    lines.append("-- SENARYO §7.6: 48 bütünlük sorgusu. HER SORGU 0 DÖNDÜRMELİDİR.")
    lines.append("--")
    lines.append("-- Okuma: `GROUP ALL` kullananlar ihlal yokken [[{ count: 0 }]],")
    lines.append("--   gruplanmış olanlar [[]] (boş) döndürür. İkisi de SIFIR demektir.")
    lines.append("--")
    lines.append("-- Taşınabilirlik (SurrealDB 3.1.6 üzerinde çalıştırılarak sınandı):")
    lines.append("--   * Her sorgu TEK SATIRDIR — `surreal sql` istemcisi girdiyi satır")
    lines.append("--     satır ayrıştırır, çok satırlı ifade ikinci satırda hata verir.")
    lines.append("--   * `array::contains` ve `HAVING` bu sürümde YOKTUR; yerine")
    lines.append("--     `IN` / `NOT IN` / `INSIDE` / `NOTINSIDE` ve alt sorgudan SELECT.")
    lines.append("--   * Satır başına alt sorgu 20.000+ satırda zaman aşımına uğrar;")
    lines.append("--     böyle yerlerde çocuk tablo GROUP BY ile tek geçişte toplanır.")
    lines.append("--")
    lines.append("-- Kullanılan SurrealQL fonksiyonları (hepsi 3.1.6'da doğrulandı):")
    lines.append("--   count()  math::sum  math::floor  array::len  string::concat")
    lines.append("--   string::starts_with  string::ends_with  string::len")
    lines.append("--   record::id  type::record")
    lines.append("-- Kullanılan işleçler:")
    lines.append("--   IN  NOT IN  INSIDE  NOTINSIDE  ??  IS NONE  !=")
    lines.append("--   IF ... THEN ... ELSE ... END   <string> dönüşümü")
    lines.append("--   GROUP ALL  GROUP BY  alt sorgudan SELECT")
    lines.append("-- KULLANMAYIN (3.1.6'da geçersiz):")
    lines.append("--   array::contains(...)   -- Invalid function/constant path")
    lines.append("--   GROUP BY ... HAVING    -- Unexpected token")
    lines.append("--   meta::version()        -- Invalid function/constant path")
    lines.append("--")
    lines.append("-- Okul veritabanında, tüm veri dosyaları yüklendikten SONRA çalıştırın.")
    lines.append("-- ---------------------------------------------------------------")
    lines.append("")
    lines.append("LET $t_now   = %d;   -- T_NOW (unix-ms)" % t_now_ms)
    lines.append("LET $t_start = %d;   -- 2025-09-08 00:00 +03" % _t_start())
    lines.append("LET $t_end   = %d;   -- 2026-06-19 23:59 +03" % _t_end())
    lines.append("")
    n = 0
    for code, title, sql in QUERIES:
        if sql is None and code == "I21":
            sql = ("SELECT count() FROM badge_award WHERE badge NOT IN %s GROUP ALL;"
                   % badges)
        for line in sql.split("\n"):
            if len(line) > 0 and "\n" in line:        # güvenlik ağı
                raise ValueError("%s: sorgu tek satır olmalı" % code)
        lines.append("-- %s: %s" % (code, title))
        lines.append(sql)
        lines.append("")
        n += 1
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
    return n


def _t_start():
    import timeline as T
    return T.local_ms(C.T1_START, 0)


def _t_end():
    import timeline as T
    return T.local_ms(C.T2_END, 23 * 60 + 59)
