"""Akademik yapı: dönem, şube, ders, konu, kayıt, ders oturumu ve yoklama.

Kritik modelleme kararı (SENARYO §1.4): bir `course` = (seviye × ders). Aynı
seviyenin tüm şubeleri `class_course` ile o derse bağlanır ve o seviyenin tüm
öğrencileri `enrollment` ile derse kayıtlıdır. Yoklama şube düzeyinde kalır:
`course_session.topic` şube etiketini taşır ve `session_attendance` yalnız o
şubenin öğrencileri için yazılır.
"""

from __future__ import annotations

import datetime as _dt

import config as C
import dists as D
import timeline as T
from ids import UlidFactory, rid, substream


class Subject:
    __slots__ = ("key", "rid", "course", "name", "index", "description",
                 "exam_question_count", "homework_count")

    def __init__(self, key, course, name, index, description):
        self.key = key
        self.rid = rid("subject", key)
        self.course = course
        self.name = name
        self.index = index
        self.description = description
        self.exam_question_count = 0
        self.homework_count = 0


class Course:
    __slots__ = ("key", "rid", "grade", "area", "title", "kind", "teachers", "subjects",
                 "students", "branches", "weekly_blocks", "difficulty_shift", "extra",
                 "creator", "capacity", "enrollment_count", "swap_at", "old_teacher")

    def __init__(self, key, grade, area, title, kind, weekly_blocks, difficulty_shift,
                 extra=False):
        self.key = key
        self.rid = rid("course", key)
        self.grade = grade
        self.area = area
        self.title = title
        self.kind = kind
        self.teachers = []
        self.subjects = []
        self.students = []
        self.branches = []
        self.weekly_blocks = weekly_blocks
        self.difficulty_shift = difficulty_shift
        self.extra = extra
        self.creator = None
        self.capacity = None
        self.enrollment_count = 0
        self.swap_at = None
        self.old_teacher = None

    @property
    def teacher(self):
        return self.teachers[0]


class ClassGroup:
    __slots__ = ("key", "rid", "name", "grade", "teacher", "students", "courses",
                 "member_count", "course_count")

    def __init__(self, key, name, grade):
        self.key = key
        self.rid = rid("class_group", key)
        self.name = name
        self.grade = grade
        self.teacher = None
        self.students = []
        self.courses = []
        self.member_count = 0
        self.course_count = 0


# ---------------------------------------------------------------------------
# Yapı
# ---------------------------------------------------------------------------

def build_structure(ctx) -> None:
    seed = ctx.seed
    em = ctx.emitter

    # --- term ------------------------------------------------------------
    ctx.term_guz = rid("term", "guz2025")
    ctx.term_bahar = rid("term", "bahar2026")
    ctx.terms = [
        {"id": ctx.term_guz, "name": "2025-2026 Güz Dönemi",
         "starts_at": T.local_ms(C.T1_START, 0),
         "ends_at": T.local_ms(C.T1_END, 23 * 60 + 59),
         "archived_at": None, "course_count": 0, "class_count": 0},
        {"id": ctx.term_bahar, "name": "2025-2026 Bahar Dönemi",
         "starts_at": T.local_ms(C.T2_START, 0),
         "ends_at": T.local_ms(C.T2_END, 23 * 60 + 59),
         "archived_at": None, "course_count": 0, "class_count": 0},
    ]

    # --- class_group ------------------------------------------------------
    cg_fac = UlidFactory(substream(seed, "ulid.class_group"))
    base_ms = T.local_ms(_dt.date(2025, 9, 2), 9 * 60)
    ctx.classes = []
    by_grade = {}
    for i, (name, grade, _n) in enumerate(C.BRANCHES):
        cg = ClassGroup(cg_fac.make(base_ms + i * 60_000), name, grade)
        cg.teacher = ctx.teachers[i % (len(ctx.teachers) - 1)]
        ctx.classes.append(cg)
        by_grade.setdefault(grade, []).append(cg)
    ctx.classes_by_grade = by_grade
    ctx.class_by_name = {c.name: c for c in ctx.classes}

    for s in ctx.students:
        cg = ctx.class_by_name[s.branch]
        cg.students.append(s)

    # class_member (kompozit kimlik: {class}_{user})
    for cg in ctx.classes:
        for s in cg.students:
            added = s.join_ms if s.join_ms is not None else T.local_ms(C.T1_START, 8 * 60)
            em.add("class_member", {
                "id": rid("class_member", "%s_%s" % (cg.key, s.key)),
                "class": cg.rid, "user": s.rid,
                "added_by": ctx.admin.rid, "added_at": added,
            })
            cg.member_count += 1

    # --- class_blueprint --------------------------------------------------
    ctx.blueprints = {}
    for grade in C.GRADES:
        ctx.blueprints[grade] = rid("class_blueprint", grade)

    # --- course + subject -------------------------------------------------
    course_fac = UlidFactory(substream(seed, "ulid.course"))
    subj_fac = UlidFactory(substream(seed, "ulid.subject"))
    subj_rng = substream(seed, "academics.subject")
    course_ms = T.local_ms(_dt.date(2025, 9, 3), 9 * 60)

    ctx.courses = []
    area_teachers = {}
    for t in ctx.teachers:
        if t.area:
            area_teachers.setdefault(t.area, []).append(t)
    area_cursor = {a: 0 for a in area_teachers}

    idx = 0
    for grade in C.GRADES:
        for name, area, blocks, n_subjects, shift in C.CORE_SUBJECTS:
            title = C.GRADE_PREFIX[grade] + name
            if grade == "12" and area in C.GRADE12_TITLE_OVERRIDE:
                title = C.GRADE12_TITLE_OVERRIDE[area]
            co = Course(course_fac.make(course_ms + idx * 30_000), grade, area, title,
                        "course", blocks, shift)
            pool = area_teachers[area]
            co.teachers = [pool[area_cursor[area] % len(pool)]]
            area_cursor[area] += 1
            co.creator = ctx.admin
            co.branches = list(by_grade[grade])
            ctx.courses.append(co)
            idx += 1
            names = C.SUBJECT_NAMES.get((grade, area)) or C.SUBJECT_FALLBACK[area]
            for j in range(n_subjects):
                desc = ""
                if subj_rng.random() < C.SUBJECT_DESCRIPTION_FILL:
                    desc = "%s dersinin %s konusu; kazanımlar ve örnek uygulamalar." % (
                        title, names[j % len(names)])
                sb = Subject(subj_fac.make(course_ms + idx * 30_000 + j * 1000), co,
                             names[j % len(names)], j, desc)
                co.subjects.append(sb)

    ctx.core_courses = list(ctx.courses)

    # ek dersler (etüt / kulüp)
    extra_rng = substream(seed, "academics.extra")
    for e_i, (title, kind, enrolled, n_subjects) in enumerate(C.EXTRA_COURSES):
        co = Course(course_fac.make(course_ms + (100 + e_i) * 30_000), None, None,
                    title, kind, 1, 0.0, extra=True)
        co.teachers = [ctx.teachers[e_i % (len(ctx.teachers) - 1)]]
        co.creator = ctx.admin
        ctx.courses.append(co)
        for j in range(n_subjects):
            sb = Subject(subj_fac.make(course_ms + (100 + e_i) * 30_000 + j * 1000), co,
                         C.EXTRA_SUBJECT_NAMES[j % len(C.EXTRA_SUBJECT_NAMES)], j,
                         "%s için %s." % (title, C.EXTRA_SUBJECT_NAMES[j % 3].lower()))
            co.subjects.append(sb)
    ctx.extra_courses = [c for c in ctx.courses if c.extra]

    # ortak yürütülen dersler (#19) ve öğretmen değişimi (#17)
    co_rng = substream(seed, "academics.coteach")
    n_co = max(1, round(C.CO_TAUGHT_COURSES * ctx.scale.ratio))
    for co in D.take_share(co_rng, ctx.core_courses, n_co / max(1, len(ctx.core_courses))):
        pool = [t for t in area_teachers[co.area] if t not in co.teachers]
        if pool:
            co.teachers.append(pool[co_rng.randrange(len(pool))])
    n_swap = max(1, round(C.TEACHER_SWAP_COURSES * ctx.scale.ratio))
    swap_rng = substream(seed, "academics.swap")
    for co in D.take_share(swap_rng, [c for c in ctx.core_courses if len(c.teachers) == 1],
                           n_swap / max(1, len(ctx.core_courses))):
        pool = [t for t in area_teachers[co.area] if t not in co.teachers]
        if pool:
            co.old_teacher = co.teachers[0]
            co.teachers = [pool[swap_rng.randrange(len(pool))]]
            co.swap_at = T.local_ms(C.TEACHER_SWAP_DATE, 8 * 60)

    # --- class_course -----------------------------------------------------
    for co in ctx.core_courses:
        for cg in co.branches:
            # 12-A blueprint kullanamaz (kenar durum #10)
            source = None if cg.name == C.INCONSISTENT_GRADE_BRANCH else ctx.blueprints[co.grade]
            em.add("class_course", {
                "id": rid("class_course", "%s_%s" % (cg.key, co.key)),
                "class": cg.rid, "course": co.rid,
                "attached_by": ctx.admin.rid,
                "attached_at": T.local_ms(C.T1_START, 8 * 60),
                "source": source,
            })
            cg.course_count += 1
            cg.courses.append(co)

    # --- enrollment -------------------------------------------------------
    for co in ctx.core_courses:
        for cg in co.branches:
            for s in cg.students:
                co.students.append(s)
                em.add("enrollment", {
                    "id": rid("enrollment", "%s_%s" % (co.key, s.key)),
                    "course": co.rid, "user": s.rid,
                    "enrolled_by": ctx.admin.rid, "source": cg.rid,
                })
                co.enrollment_count += 1

    enr_rng = substream(seed, "academics.enroll_extra")
    for (title, kind, enrolled, _n), co in zip(C.EXTRA_COURSES, ctx.extra_courses):
        target = max(1, round(enrolled * ctx.scale.ratio))
        pool = [s for s in ctx.students if s.leave_ms is None]
        enr_rng.shuffle(pool)
        for s in pool[:target]:
            co.students.append(s)
            em.add("enrollment", {
                "id": rid("enrollment", "%s_%s" % (co.key, s.key)),
                "course": co.rid, "user": s.rid,
                "enrolled_by": ctx.admin.rid, "source": None,
            })
            co.enrollment_count += 1
        co.capacity = max(target, target + 4)

    # Öğrenci başına ders/konu sapmaları (delta_u).
    # A3'te bir "boşluk dersi" ve o dersin ardışık 3 konusu sabit negatif alır.
    enrolled_courses = {}
    for co in ctx.courses:
        for s in co.students:
            enrolled_courses.setdefault(s.key, []).append(co)

    delta_rng = substream(seed, "academics.delta")
    for s in ctx.students:
        a = s.arch
        my_courses = enrolled_courses.get(s.key, [])
        gap_course = None
        if s.archetype == "A3" and s.gap_area:
            grade = ctx.class_by_name[s.branch].grade
            for co in my_courses:
                if co.grade == grade and co.area == s.gap_area:
                    gap_course = co
                    break
            if gap_course is None:
                gap_course = next((co for co in my_courses if not co.extra), None)
            if gap_course is not None:
                s.gap_course_key = gap_course.key
        for co in my_courses:
            if gap_course is not None and co is gap_course:
                s.course_delta[co.key] = a["gap_delta"]
            elif gap_course is not None:
                s.course_delta[co.key] = delta_rng.gauss(a.get("other_course_mu", 0.0),
                                                         a["d_course"])
            else:
                s.course_delta[co.key] = delta_rng.gauss(0.0, a["d_course"])
            for sb in co.subjects:
                s.subject_delta[sb.key] = delta_rng.gauss(0.0, a["d_subject"])
        if gap_course is not None and gap_course.subjects:
            span = max(1, len(gap_course.subjects) - 2)
            start_i = delta_rng.randrange(span)
            gap_subjects = gap_course.subjects[start_i:start_i + 3]
            s.gap_subject_keys = tuple(sb.key for sb in gap_subjects)
            for sb in gap_subjects:
                s.subject_delta[sb.key] = a["gap_subject_delta"]

    ctx.enrolled_courses = enrolled_courses

    ctx.subjects = [sb for co in ctx.courses for sb in co.subjects]
    ctx.subject_by_key = {sb.key: sb for sb in ctx.subjects}
    ctx.course_by_key = {co.key: co for co in ctx.courses}


# ---------------------------------------------------------------------------
# Ders programı ve oturumlar
# ---------------------------------------------------------------------------

def build_timetable(ctx) -> None:
    """Şube başına haftalık sabit ders programı: 14 blok, 30 slot içine çakışmasız."""
    rng = substream(ctx.seed, "academics.timetable")
    ctx.timetable = {}
    slots = [(d, b) for d in range(5) for b in range(len(C.BLOCK_MINUTES))]
    for cg in ctx.classes:
        blocks = []
        for co in cg.courses:
            blocks.extend([co] * co.weekly_blocks)
        pool = list(slots)
        rng.shuffle(pool)
        rng.shuffle(blocks)
        ctx.timetable[cg.name] = sorted(
            [(pool[i][0], pool[i][1], co) for i, co in enumerate(blocks)],
            key=lambda x: (x[0], x[1]))


def absence_probability(ctx, student, course, day, block_index, exam_today) -> float:
    ms = T.local_ms(day, C.BLOCK_MINUTES[block_index])
    base = student.param("absence", ms)
    mult = C.ABSENCE_DAY_MULT[day.weekday()]
    if exam_today:
        mult *= C.ABSENCE_EXAM_DAY_MULT
    mult *= T.near_break(day)
    if T.is_flu_week(day):
        mult *= C.ABSENCE_FLU_MULT
    else:
        mult *= C.season_mult(day.month)
    a = student.arch
    if day.weekday() == 0 and a.get("monday_absence_mult"):
        mult *= a["monday_absence_mult"]
    if day.weekday() == 4 and a.get("friday_absence_mult"):
        mult *= a["friday_absence_mult"]
    return D.clip(base * mult, 0.0, 0.95)


def build_sessions(ctx) -> None:
    """course_session + session_attendance (akışlı)."""
    seed = ctx.seed
    em = ctx.emitter
    sess_fac = UlidFactory(substream(seed, "ulid.course_session"))
    held_rng = substream(seed, "sessions.held")
    cover_rng = substream(seed, "sessions.coverage")
    att_rng = substream(seed, "sessions.attendance")

    weeks = T.past_teaching_weeks()
    ctx.teaching_week_count = len(weeks)
    exam_days = ctx.exam_days_by_grade  # {grade: set(date)}

    n_sessions = 0
    n_no_attendance = 0

    for w_i, monday in enumerate(weeks):
        for cg in ctx.classes:
            plan = ctx.timetable[cg.name]
            for weekday, block, co in plan:
                day = monday + _dt.timedelta(days=weekday)
                if not T.is_school_day(day):
                    continue
                starts = T.local_ms(day, C.BLOCK_MINUTES[block])
                if starts > T.T_NOW:
                    continue
                n_subj = len(co.subjects)
                s_idx = min(n_subj - 1, int(w_i * n_subj / max(1, len(weeks))))
                subject = co.subjects[s_idx]
                teacher = co.teachers[0]
                if co.swap_at is not None and starts < co.swap_at and co.old_teacher:
                    teacher = co.old_teacher
                held = None
                if held_rng.random() < C.SESSION_HELD_COUNTED_SHARE:
                    held = starts + held_rng.randint(35, 180) * C.MIN_MS
                    ctx.bump(teacher, "lessons_held_total")
                else:
                    ctx.stats["held_counted_none"] = ctx.stats.get("held_counted_none", 0) + 1
                key = sess_fac.make(starts)
                em.add("course_session", {
                    "id": rid("course_session", key),
                    "course": co.rid, "teacher": teacher.rid,
                    "topic": "%s · %s" % (cg.name, subject.name),
                    "starts_at": starts,
                    "ends_at": starts + C.BLOCK_LENGTH_MIN * C.MIN_MS,
                    "held_counted_at": held,
                })
                n_sessions += 1
                if cover_rng.random() >= C.SESSION_ATTENDANCE_SHARE:
                    n_no_attendance += 1
                    continue
                exam_today = day in exam_days.get(cg.grade, ())
                for s in cg.students:
                    if not s.active_at(starts):
                        continue
                    p_abs = absence_probability(ctx, s, co, day, block, exam_today)
                    if att_rng.random() < p_abs:
                        share = s.param("absent_share", starts)
                        status = "absent" if att_rng.random() < share else "excused"
                    else:
                        p_late = s.param("late", starts)
                        if day.weekday() == 0:
                            p_late *= C.LATE_MONDAY_MULT
                        if block == 0:
                            p_late *= C.LATE_FIRST_BLOCK_MULT
                        p_late *= C.LATE_SCALE
                        status = "late" if att_rng.random() < min(0.9, p_late) else "present"
                    em.add("session_attendance", {
                        "id": rid("session_attendance", "%s_%s" % (key, s.key)),
                        "session": rid("course_session", key),
                        "course": co.rid, "user": s.rid,
                        "status": status, "marked_by": teacher.rid,
                    })
                    ctx.attendance_stats[status] = ctx.attendance_stats.get(status, 0) + 1
                    if status in ("present", "late"):
                        ctx.student_attend[s.key] = ctx.student_attend.get(s.key, 0) + 1

    # etüt / kulüp oturumları: haftada 1
    extra_rng = substream(seed, "sessions.extra")
    for co in ctx.extra_courses:
        for w_i, monday in enumerate(weeks):
            day = monday + _dt.timedelta(days=2)
            if not T.is_school_day(day):
                continue
            starts = T.local_ms(day, C.BLOCK_MINUTES[-1] + 60)
            if starts > T.T_NOW:
                continue
            subject = co.subjects[w_i % len(co.subjects)]
            teacher = co.teachers[0]
            held = None
            if extra_rng.random() < C.SESSION_HELD_COUNTED_SHARE:
                held = starts + extra_rng.randint(35, 180) * C.MIN_MS
                ctx.bump(teacher, "lessons_held_total")
            else:
                ctx.stats["held_counted_none"] = ctx.stats.get("held_counted_none", 0) + 1
            key = sess_fac.make(starts)
            em.add("course_session", {
                "id": rid("course_session", key),
                "course": co.rid, "teacher": teacher.rid,
                "topic": "%s · %s" % (co.title, subject.name),
                "starts_at": starts,
                "ends_at": starts + 60 * C.MIN_MS,
                "held_counted_at": held,
            })
            n_sessions += 1
            for s in co.students:
                if not s.active_at(starts):
                    continue
                if extra_rng.random() >= C.EXTRA_COURSE_ATTENDANCE_SHARE:
                    continue
                status = "present" if extra_rng.random() < 0.93 else "absent"
                em.add("session_attendance", {
                    "id": rid("session_attendance", "%s_%s" % (key, s.key)),
                    "session": rid("course_session", key),
                    "course": co.rid, "user": s.rid,
                    "status": status, "marked_by": teacher.rid,
                })
                ctx.attendance_stats[status] = ctx.attendance_stats.get(status, 0) + 1

    ctx.stats["course_session"] = n_sessions
    ctx.stats["sessions_without_attendance"] = n_no_attendance


# ---------------------------------------------------------------------------
# Ders notları
# ---------------------------------------------------------------------------

def build_course_notes(ctx) -> None:
    seed = ctx.seed
    em = ctx.emitter
    note_fac = UlidFactory(substream(seed, "ulid.course_note"))
    file_fac = UlidFactory(substream(seed, "ulid.course_note_file"))
    rag_fac = UlidFactory(substream(seed, "ulid.rag_output"))
    rng = substream(seed, "academics.course_note")

    weeks = T.past_teaching_weeks()
    notes = []
    files_per_note = {}
    for co in ctx.core_courses:
        for i in range(C.COURSE_NOTE_PER_COURSE):
            monday = weeks[min(len(weeks) - 1, int(i * len(weeks) / C.COURSE_NOTE_PER_COURSE))]
            ms = T.local_ms(monday + _dt.timedelta(days=rng.randrange(5)),
                            rng.randint(9 * 60, 17 * 60))
            if ms > T.T_NOW:
                ms = T.T_NOW - C.DAY_MS
            subject = co.subjects[i % len(co.subjects)]
            key = note_fac.make(ms)
            author = co.teachers[0]
            files = []
            if rng.random() < C.COURSE_NOTE_FILE_SHARE:
                for f in range(1 if rng.random() < 0.75 else 2):
                    fkey = file_fac.make(ms + 1000 * (f + 1))
                    files.append({
                        "id": rid("course_note_file", fkey),
                        "course_note": rid("course_note", key),
                        "name": "%s-%d.pdf" % (subject.name.split()[0].lower(), f + 1),
                        "content_type": "application/pdf",
                        "size": rng.randint(40_000, 2_400_000),
                    })
            notes.append({
                "id": rid("course_note", key),
                "course": co.rid, "author": author.rid,
                "title": "%s — %s" % (co.title, subject.name),
                "content": ("%s konusunun özeti: temel kavramlar, örnek çözümler ve "
                            "sınavda dikkat edilmesi gerekenler." % subject.name),
                "file_count": len(files),
            })
            files_per_note[key] = files
            em.add("rag_output", {
                "id": rid("rag_output", rag_fac.make(ms + 5000)),
                "course_note": rid("course_note", key),
                "course": co.rid,
                "sources": [f["id"] for f in files],
                "payload": {"chunks": rng.randint(3, 24),
                            "model": rng.choice(C.RAG_MODELS),
                            "indexed_at_ms": ms + 5000,
                            "dim": 384},
                "generated_at": ms + 5000,
            })
    em.add_many("course_note", notes)
    for files in files_per_note.values():
        em.add_many("course_note_file", files)
