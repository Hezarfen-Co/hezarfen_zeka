"""Sayaç hesabı ve sayaç taşıyan satırların yazımı (Ek A adım 27).

Sayaçlar önbellek değil OTORİTEDİR (db/cap.rs). Yanlış bir sayaç dersi kalıcı
olarak silinemez yapar. Bu yüzden hiçbir sayaç tahmin edilmez; üretilen
satırlardan sayılır. Geri doldurma mekanizması olmayan sayaçlar
(`term.class_count`, `class_group.*_count`, `user.board_count`,
`course_note.file_count`, `user.marks_given_total`, rozet toplamları,
`board.epoch*`) burada mutlaka yazılır.

İki sayaç KASTEN yazılmaz (SENARYO §5.3): `user.lessons_attended_total` ve
`user.high_mark_total`. Bu yüzden ilgili 6 rozet kodu da hiç verilmez.
"""

from __future__ import annotations

import config as C
import timeline as T
from emit import sq_string
from ids import rid

USER_COUNTER_FIELDS = [
    "chatbot_thread_count", "board_count",
    "homework_submitted_total", "homework_on_time_total", "exam_sat_total",
    "pomodoro_finished_total", "pomodoro_focus_ms_total", "marks_given_total",
    "lessons_held_total", "pool_approved_total", "pool_published_total",
    "lessons_attended_total", "high_mark_total",
    "study_streak_longest", "study_streak_current", "study_streak_last_day",
    "pomodoro_counted_day", "pomodoro_counted_today",
]


def emit_users(ctx) -> None:
    em = ctx.emitter
    for u in ctx.users:
        row = {"id": u.rid, "username": u.username,
               "password_hash": u.profile["password_hash"], "role": u.role,
               "name": u.name, "surname": u.surname}
        for key in ("email", "phone", "birth_date", "theme", "language",
                    "palette_color", "display_name", "bio", "avatar_file",
                    "avatar_content_type", "avatar_size"):
            row[key] = u.profile.get(key)
        for field in USER_COUNTER_FIELDS:
            if field in C.UNWRITTEN_COUNTERS:
                row[field] = None          # kasıtlı eksik sayaç
            else:
                row[field] = u.counters.get(field)
        em.add("user", row)


def emit_structure(ctx) -> None:
    """Sayaç taşıyan yapı satırları: term, class_group, course, subject."""
    em = ctx.emitter

    course_count = len(ctx.courses)
    class_count = len(ctx.classes)
    for term in ctx.terms:
        row = dict(term)
        if row["id"] is ctx.term_bahar or str(row["id"]) == str(ctx.term_bahar):
            row["course_count"] = course_count
            row["class_count"] = class_count
        else:
            row["course_count"] = 0
            row["class_count"] = 0
        em.add("term", row)

    for cg in ctx.classes:
        grade = (C.INCONSISTENT_GRADE_VALUE
                 if cg.name == C.INCONSISTENT_GRADE_BRANCH else cg.grade)
        em.add("class_group", {
            "id": cg.rid, "name": cg.name, "grade": grade,
            "term": ctx.term_bahar, "creator": ctx.admin.rid,
            "teacher": cg.teacher.rid,
            "class_member_count": cg.member_count,
            "class_course_count": cg.course_count,
        })

    for grade in C.GRADES:
        courses = [co.rid for co in ctx.core_courses if co.grade == grade]
        em.add("class_blueprint", {
            "id": ctx.blueprints[grade], "grade": grade,
            "courses": courses, "creator": ctx.admin.rid,
        })

    for co in ctx.courses:
        em.add("course", {
            "id": co.rid, "creator": co.creator.rid,
            "teachers": [t.rid for t in co.teachers],
            "title": co.title,
            "description": "%s dersi." % co.title,
            "kind": co.kind,
            "term": ctx.term_bahar,
            "capacity": co.capacity,
            "enrollment_count": co.enrollment_count,
        })

    for sb in ctx.subjects:
        em.add("subject", {
            "id": sb.rid, "course": sb.course.rid, "name": sb.name,
            "description": sb.description,
            "exam_question_count": sb.exam_question_count,
            "homework_count": sb.homework_count,
        })


def emit_reference_tables(ctx) -> None:
    """settings, kind_ref, slot_ref, migration_mark."""
    em = ctx.emitter
    em.add("settings", dict({"id": rid("settings", "school")}, **C.SETTINGS))

    for kind in C.EXAM_KINDS:
        em.add("kind_ref", {
            "id": rid("kind_ref", kind),
            "count": ctx.kind_ref_counts.get(kind, 0),
            "retired": False,
        })
    for slot in C.MEAL_SLOTS:
        em.add("slot_ref", {
            "id": rid("slot_ref", slot),
            "count": ctx.slot_ref_counts.get(slot, 0),
            "retired": False,
        })
    # migration_mark: profil sayaçlarının yeniden hesaplanmasını engeller;
    # tohumdaki kasıtlı sayaç hataları (§5.3) böylece korunur.
    for mark in ("board_roster", "profile_counters"):
        em.add("migration_mark", {
            "id": rid("migration_mark", mark),
            "done_at": T.T_NOW, "fingerprint": None,
        })


def write_control_file(path: str, created_ms: int) -> None:
    """00_control.surql — control veritabanına okul satırı (21 modül açık)."""
    # Dize kaçışlaması tek yerden gelir: emit.sq_string
    modules = ", ".join(sq_string(m) for m in C.MODULES_ALL)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("-- ---------------------------------------------------------------\n")
        fh.write("-- Hezarfen tohum verisi — 00_control.surql\n")
        fh.write("-- Tablo: school (CONTROL veritabanı) — 1 satır\n")
        fh.write("-- Bu dosya CONTROL veritabanında çalıştırılır (USE NS hezarfen DB control).\n")
        fh.write("-- Okul zaten builder ile oluşturulmuşsa satır UPSERT ile güncellenir;\n")
        fh.write("-- 21 modülün tamamı açılır (Module::ALL, sıralı saklanır — E23).\n")
        fh.write("-- Diğer dosyalar OKUL veritabanında, numara sırasıyla yüklenir.\n")
        fh.write("-- ---------------------------------------------------------------\n\n")
        fh.write("UPSERT school:⟨%s⟩ CONTENT {\n" % C.SCHOOL_SLUG)
        fh.write("  slug: %s,\n" % sq_string(C.SCHOOL_SLUG))
        fh.write("  name: %s,\n" % sq_string(C.SCHOOL_NAME))
        fh.write("  status: %s,\n" % sq_string("active"))
        fh.write("  created_at: %d,\n" % created_ms)
        fh.write("  modules: [%s]\n" % modules)
        fh.write("};\n")
