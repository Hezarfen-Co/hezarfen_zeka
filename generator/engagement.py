"""Katılım alanı: ödev, pomodoro, soru havuzu, sohbet, not, mesaj, tahta, rozet."""

from __future__ import annotations

import datetime as _dt
import math

import config as C
import dists as D
import timeline as T
from ids import UlidFactory, rid, substream


# ---------------------------------------------------------------------------
# Ödev
# ---------------------------------------------------------------------------

def build_homework(ctx) -> None:
    seed = ctx.seed
    em = ctx.emitter
    hw_fac = UlidFactory(substream(seed, "ulid.homework"))
    file_fac = UlidFactory(substream(seed, "ulid.homework_file"))
    rng = substream(seed, "homework.plan")
    sub_rng = substream(seed, "homework.submit")
    res_rng = substream(seed, "homework.result")
    file_rng = substream(seed, "homework.file")

    weeks = T.all_teaching_weeks()
    past_weeks = T.past_teaching_weeks()
    ctx.homeworks = []
    submissions = []          # sonra yazılır (file_count / graded_by_result için)
    results = []
    files = []

    def plan_for(course, n_past, n_future):
        rows = []
        for i in range(n_past):
            monday = past_weeks[min(len(past_weeks) - 1,
                                    int((i + 0.5) * len(past_weeks) / n_past))]
            created = T.local_ms(monday + _dt.timedelta(days=rng.randrange(5)),
                                 rng.randint(9 * 60, 16 * 60))
            rows.append((created, i, True))
        for j in range(n_future):
            created = T.T_NOW - rng.randint(1, 6) * C.DAY_MS
            rows.append((created, n_past + j, False))
        return rows

    for co in ctx.courses:
        if co.extra:
            n_past, n_future = C.HOMEWORK_EXTRA_PER_COURSE - 1, 1
        else:
            n_past, n_future = C.HOMEWORK_PAST_PER_COURSE, C.HOMEWORK_FUTURE_PER_COURSE
        for created, i, is_past in plan_for(co, n_past, n_future):
            subject = co.subjects[i % len(co.subjects)]
            span = rng.randint(5, 12)
            due_minute = (23 * 60 + 59) if rng.random() < C.HOMEWORK_DUE_2359_SHARE else 17 * 60
            due_day = _dt.date(1970, 1, 1) + _dt.timedelta(
                days=(created - T.SHIFT_MS + C.TZ_OFFSET_MS) // C.DAY_MS + span)
            due = T.local_ms(due_day, due_minute)
            if is_past and due > T.T_NOW:
                due = T.T_NOW - rng.randint(1, 5) * C.DAY_MS
            if not is_past and due <= T.T_NOW:
                due = T.T_NOW + rng.randint(1, 20) * C.DAY_MS
            shifted = rng.random() < C.HOMEWORK_DUE_SHIFT_SHARE
            if shifted and is_past:
                due += 48 * C.HOUR_MS
            targets = list(co.students)
            assigned = None
            if rng.random() < C.HOMEWORK_ASSIGNED_SUBSET and targets:
                k = min(C.MAX_HOMEWORK_ASSIGNED,
                        max(1, int(len(targets) * C.HOMEWORK_ASSIGNED_RATIO)))
                pool = list(targets)
                rng.shuffle(pool)
                targets = pool[:k]
                assigned = [s.rid for s in targets]
            key = hw_fac.make(created)
            hw_rid = rid("homework", key)
            ctx.homeworks.append({
                "id": hw_rid, "course": co.rid, "subject": subject.rid,
                "title": "%s — %s ödevi" % (subject.name, co.title),
                "description": "%s konusuyla ilgili soruları çözüp yükleyiniz." % subject.name,
                "due_at": due,
                "assigned": assigned,
                "created_by": co.teachers[0].rid,
                "created_at": created,
            })
            subject.homework_count += 1
            if shifted:
                ctx.stats["due_shifted"] = ctx.stats.get("due_shifted", 0) + 1

            for s in targets:
                if not s.active_at(created):
                    continue
                if "no_homework_course" in s.edge and co is ctx.courses[0]:
                    continue
                if "passive" in s.edge and sub_rng.random() < 0.8:
                    continue
                if is_past:
                    p = s.param("hw_submit", created)
                    if s.gap_course_key == co.key:
                        p = s.arch.get("gap_hw_submit", p)
                else:
                    near = (due - T.T_NOW) < 7 * C.DAY_MS
                    p = C.HOMEWORK_FUTURE_NEAR_SUBMIT if near else C.HOMEWORK_FUTURE_FAR_SUBMIT
                if sub_rng.random() >= p:
                    if is_past and res_rng.random() < C.HOMEWORK_MISSING_RESULT_SHARE:
                        results.append({
                            "id": rid("homework_result", "%s_%s" % (key, s.key)),
                            "homework": hw_rid, "user": s.rid, "status": "missing",
                            "mark": None, "graded_by": co.teachers[0].rid,
                            "created_at": due + res_rng.randint(1, 6) * C.DAY_MS,
                        })
                        ctx.bump(co.teachers[0], "marks_given_total")
                    continue
                delta_h = _submission_offset(sub_rng, s, created)
                submitted = int(due - delta_h * C.HOUR_MS)
                submitted = max(created + C.HOUR_MS, submitted)
                if submitted > T.T_NOW:
                    submitted = T.T_NOW - sub_rng.randint(1, 12) * C.HOUR_MS
                if submitted <= created:
                    submitted = created + C.HOUR_MS
                on_time = submitted <= due
                updated = submitted
                if sub_rng.random() < C.HOMEWORK_UPDATED_SHARE:
                    updated = submitted + int(D.exponential(sub_rng, 9.0) * C.HOUR_MS)
                    if updated > T.T_NOW:
                        updated = T.T_NOW
                n_files = 0
                sub_key = "%s_%s" % (key, s.key)
                if file_rng.random() < C.HOMEWORK_FILE_SHARE:
                    n_files = min(C.MAX_HOMEWORK_FILES,
                                  max(1, D.poisson(file_rng, C.HOMEWORK_FILE_MEAN)))
                    for f in range(n_files):
                        files.append({
                            "id": rid("homework_file", file_fac.make(submitted + f + 1)),
                            "submission": rid("homework_submission", sub_key),
                            "name": "odev-%d.pdf" % (f + 1),
                            "content_type": "application/pdf",
                            "size": file_rng.randint(20_000, 4_000_000),
                            "file": "homework/%s-%d.bin" % (sub_key.lower(), f + 1),
                            "created_at": submitted + f + 1,
                        })
                graded = is_past and res_rng.random() < C.HOMEWORK_GRADED_SHARE
                result_rid = None
                if graded:
                    status = D.pick_weighted(res_rng, C.HOMEWORK_STATUS_SHARES)
                    if status == "missing":
                        status = "done"
                    theta = s.theta_at(submitted) + s.course_delta.get(co.key, 0.0)
                    mark = D.clip(int(round(58 + 21 * theta + res_rng.gauss(0, 7))), 0, 100)
                    result_rid = rid("homework_result", sub_key)
                    results.append({
                        "id": result_rid, "homework": hw_rid, "user": s.rid,
                        "status": status, "mark": mark,
                        "graded_by": co.teachers[0].rid,
                        "created_at": max(submitted, due) + res_rng.randint(1, 8) * C.DAY_MS,
                    })
                    ctx.bump(co.teachers[0], "marks_given_total")
                submissions.append({
                    "id": rid("homework_submission", sub_key),
                    "homework": hw_rid, "user": s.rid,
                    "text": ("Ödevimi ekte gönderiyorum." if n_files
                             else "Çözümlerim: %s konusundaki sorular." % subject.name),
                    "submitted_at": submitted, "updated_at": updated,
                    "file_count": n_files, "counted_on_time": on_time,
                    "graded_by_result": result_rid,
                })
                ctx.bump(s, "homework_submitted_total")
                if on_time:
                    ctx.bump(s, "homework_on_time_total")
                ctx.hw_stats["total"] += 1
                if on_time:
                    ctx.hw_stats["on_time"] += 1
                if not on_time:
                    ctx.hw_stats["late"] += 1
                if 0 <= (due - submitted) <= 24 * C.HOUR_MS:
                    ctx.hw_stats["last24"] += 1
                if on_time and updated > due:
                    ctx.hw_stats["on_time_but_updated_late"] += 1
                a = ctx.hw_archetype.setdefault(s.archetype, {"n": 0, "on_time": 0})
                a["n"] += 1
                a["on_time"] += 1 if on_time else 0

    em.add_many("homework", ctx.homeworks)
    em.add_many("homework_result", results)
    em.add_many("homework_submission", submissions)
    em.add_many("homework_file", files)
    ctx.stats["homework_submissions"] = len(submissions)
    ctx.stats["homework_results"] = len(results)


def _submission_offset(rng, student, created_ms):
    """Δ = due_at − submitted_at (saat, pozitif = erken) — §5.2 karma dağılım."""
    w = student.param("hw_weights", created_ms)
    # 5.2'deki agirliklar ile 3'teki counted_on_time hedefleri birbirini tam
    # tutmuyor; gec bilesen arketipin on_time hedefine gore yeniden normalize
    # edilir, boylece A10 / A11 / D13 olcumleri tanim geregi tutar.
    late_target = 1.0 - student.param("on_time", created_ms)
    head = sum(w[:3])
    if head > 0:
        factor = (1.0 - late_target) / head
        w = (w[0] * factor, w[1] * factor, w[2] * factor, late_target)
    r = rng.random()
    acc = 0.0
    for idx, weight in enumerate(w):
        acc += weight
        if r <= acc:
            break
    if idx == 0:      # son 24 saat
        return D.clip(D.exponential(rng, 7.0), 0.0, 24.0)
    if idx == 1:      # 1-7 gün
        return D.clip(D.lognormal_median(rng, 52.0, 0.5), 24.0, 168.0)
    if idx == 2:      # erken
        return rng.uniform(168.0, 480.0)
    return -D.clip(D.exponential(rng, 26.0), 0.0, 240.0)   # geç


# ---------------------------------------------------------------------------
# Pomodoro
# ---------------------------------------------------------------------------

def build_pomodoro(ctx) -> None:
    seed = ctx.seed
    em = ctx.emitter
    fac = UlidFactory(substream(seed, "ulid.pomodoro"))
    rng = substream(seed, "pomodoro.core")
    open_rng = substream(seed, "pomodoro.open")

    exam_days = sorted({e.date for e in ctx.exams if e.past})
    start_day = C.T1_START
    end_day = _dt.date(2026, 4, 13)
    n_days = (end_day - start_day).days

    open_target = max(1, round(C.POMO_OPEN_USERS * ctx.scale.ratio))
    overflow_target = max(1, round(C.POMO_OVERFLOW_STUDENTS * ctx.scale.ratio))
    open_students = set()
    overflow_students = set()
    # A21: A7'de 13 ogrencide hic pomodoro kaydi olmaz
    a7 = [s for s in ctx.students if s.archetype == "A7"]
    open_rng.shuffle(a7)
    n_zero = min(len(a7), max(0, round(C.POMO_A7_ZERO_STUDENTS * ctx.scale.ratio)))
    zero_students = {s.key for s in a7[:n_zero]}
    pool = [s for s in ctx.students if s.arch["pomo_days"] > 1.0]
    open_rng.shuffle(pool)
    for s in pool[:open_target]:
        open_students.add(s.key)
    for s in pool[open_target:open_target + overflow_target]:
        overflow_students.add(s.key)

    total = 0
    unfinished = 0
    counted_total = 0
    night_total = 0
    for s in ctx.students:
        counted_days = []
        focus_ms = 0
        counted_count = 0
        last_day_counts = {}
        for d_i in range(n_days):
            day = start_day + _dt.timedelta(days=d_i)
            ms_day = T.local_ms(day, 12 * 60)
            if not s.active_at(ms_day):
                continue
            if "passive" in s.edge or s.key in zero_students:
                continue
            base = s.param("pomo_days", ms_day) / 7.0
            if base <= 0:
                continue
            mult = C.POMO_DAY_MULT[day.weekday()]
            bk = T.break_kind(day)
            if bk:
                mult *= C.POMO_BREAK_MULT[bk]
            # E_sinav LAMBDA'ya uygulanir (gun olasiligina degil): sinav oncesi
            # yigilma stint sayisini artirir, calisilan gun sayisini degil.
            exam_mult = 1.0
            nxt = next((e for e in exam_days if e >= day), None)
            if nxt is not None:
                gap = (nxt - day).days
                coef = C.POMO_EXAM_COEF * s.arch.get("exam_rush", 1.0)
                exam_mult = 1.0 + coef * math.exp(-gap / C.POMO_EXAM_DECAY)
            p_day = D.clip(base * mult, 0.0, 1.0)
            if rng.random() >= p_day:
                continue
            lam = s.arch["pomo_lambda"] * exam_mult
            n_stints = min(C.POMO_MAX_PER_DAY, max(1, D.poisson(rng, lam)))
            if s.key in overflow_students and d_i % 97 == 0:
                n_stints = rng.randint(18, 20)
            day_counted = 0
            for k in range(n_stints):
                window = D.pick_weighted(rng, C.POMO_START_WINDOWS)
                minute = rng.randint(window[0], window[1]) + k * 3
                started = T.local_ms(day, minute)
                if started > T.T_NOW:
                    continue
                dur_min = D.clip(D.lognormal_median(rng, s.arch["pomo_median"],
                                                    s.arch["pomo_sigma"]), 3, 55)
                dur_ms = int(dur_min * C.MIN_MS)
                finished = started + dur_ms
                is_open = False
                abandoned = False
                if rng.random() < C.POMO_UNFINISHED_SHARE:
                    unfinished += 1
                    abandoned = True
                    # Terk edilmiş seans, gerçek sistemde AÇIK SATIR BIRAKMAZ.
                    # Uygulamanın açık seansı tek bir deterministik satırdır
                    # (`open_{user}`); yeni seans başlatmak onu üzerine yazar,
                    # bitirmek ise ULID anahtarlı yeni bir satır yazar. Yani
                    # `finished_at = NONE` taşıyan ULID anahtarlı bir satır
                    # ÜRETİLEMEZ.
                    #
                    # Eskiden burada terk edilmiş bir seans için de
                    # `finished = None` yazılıyordu ve hiçbir şema bunu
                    # zorlamadığı için fark edilmiyordu: 4.929 açık seans,
                    # tek bir öğrencide 68 tane. Değişmez artık yukarıdaki
                    # defterle korunuyor: ULID anahtarlı bir satır
                    # `finished = None` taşımaz.
                    #
                    # Terk edilmişlik `counted = false` ile taşınmaya devam
                    # ediyor; süre sayaçlarına zaten girmiyordu.
                    if s.key in open_students and s.key not in ctx.open_pomodoro:
                        is_open = True
                        finished = None
                counted = None
                if abandoned:
                    # Terk edilen seans sayılmaz — açık kaldıysa da, üzerine
                    # yazılıp kapandıysa da. Süre sayaçlarına girmez; terk
                    # edilmişliğin şemadaki tek izi budur.
                    counted = False
                elif finished is not None:
                    counted = dur_ms >= C.MIN_COUNTED_POMODORO_MS and \
                        day_counted < C.MAX_COUNTED_POMODORO_PER_DAY
                    if counted:
                        day_counted += 1
                        counted_count += 1
                        focus_ms += dur_ms
                        counted_total += 1
                else:
                    counted = False
                utc_day = T.day_number(started)
                if counted:
                    if not counted_days or counted_days[-1] != utc_day:
                        counted_days.append(utc_day)
                    last_day_counts[utc_day] = last_day_counts.get(utc_day, 0) + 1
                local_minute = ((started + C.TZ_OFFSET_MS) % C.DAY_MS) // C.MIN_MS
                if local_minute < 150:
                    night_total += 1
                if is_open:
                    key = "open_%s" % s.key
                    ctx.open_pomodoro[s.key] = True
                else:
                    key = fac.make(started)
                em.add("pomodoro_session", {
                    "id": rid("pomodoro_session", key),
                    "user": s.rid, "started_at": started,
                    "finished_at": finished, "counted": counted,
                })
                total += 1
        # sayaç alanları (E2: gün numarası)
        if counted_days:
            longest = 1
            run = 1
            for i in range(1, len(counted_days)):
                if counted_days[i] == counted_days[i - 1] + 1:
                    run += 1
                else:
                    run = 1
                longest = max(longest, run)
            current = 1
            for i in range(len(counted_days) - 1, 0, -1):
                if counted_days[i] == counted_days[i - 1] + 1:
                    current += 1
                else:
                    break
            last_day = counted_days[-1]
            s.counters["study_streak_longest"] = longest
            s.counters["study_streak_current"] = current
            s.counters["study_streak_last_day"] = last_day
            s.counters["pomodoro_counted_day"] = last_day
            s.counters["pomodoro_counted_today"] = last_day_counts.get(last_day, 0)
        # kasıtlı sayaç hatası: %8 şişirme (§5.3)
        s.counters["pomodoro_finished_total"] = int(round(
            counted_count * (1.0 + C.POMO_FINISHED_TOTAL_INFLATION)))
        s.counters["pomodoro_focus_ms_total"] = focus_ms
        ctx.pomodoro_true_counted[s.key] = counted_count
        if counted_count == 0:
            ctx.stats["students_without_pomodoro"] = \
                ctx.stats.get("students_without_pomodoro", 0) + 1

    ctx.stats["pomodoro_total"] = total
    ctx.stats["pomodoro_unfinished"] = unfinished
    ctx.stats["pomodoro_counted"] = counted_total
    ctx.stats["pomodoro_night"] = night_total


# ---------------------------------------------------------------------------
# Soru havuzu
# ---------------------------------------------------------------------------

POOL_TITLES = [
    "Bu soruyu nasıl çözerim?", "Konuyu anlamadım, yardım eder misiniz?",
    "Şu adımda takıldım", "İki çözüm yolu var gibi görünüyor",
    "Sonucu bulamıyorum", "Formülü karıştırıyorum", "Örnek çözüm arıyorum",
]
POOL_BODIES = [
    "Soruyu çözerken ikinci adımda tıkanıyorum; hangi kuralı uygulamam gerekiyor?",
    "Kitaptaki örnekte farklı bir yol izlenmiş, ikisi de doğru olabilir mi?",
    "Sonuç anahtarla uyuşmuyor, nerede hata yapıyorum acaba?",
    "Konunun mantığını anlatan kısa bir açıklama yazabilir misiniz?",
    "Bu tip sorularda hangi adımdan başlamak gerekir?",
]
SOLUTION_BODIES = [
    "Önce verilenleri yazıp bilinmeyeni belirle; ardından ilgili bağıntıyı uygula.",
    "İkinci adımda işaret hatası var; parantezi açarken dikkat etmen yeterli.",
    "Şu formülü kullanırsan sonuç doğrudan çıkıyor, denemeni öneririm.",
    "Grafiği çizip aralıkları işaretlersen çözüm çok daha kolay görünüyor.",
]


def build_pool(ctx) -> None:
    seed = ctx.seed
    em = ctx.emitter
    q_fac = UlidFactory(substream(seed, "ulid.pool_question"))
    s_fac = UlidFactory(substream(seed, "ulid.solution"))
    rng = substream(seed, "pool.core")

    weights = {"A2": 0.26, "A8": 0.21, "A3": 0.18, "A5": 0.14, "A4": 0.10,
               "A1": 0.06, "A6": 0.04, "A7": 0.01}
    target = max(4, round(640 * ctx.scale.ratio))
    students = ctx.students
    pairs = [(s, weights.get(s.archetype, 0.05) / max(1, ctx.archetype_counts.get(s.archetype, 1)))
             for s in students]
    approvers = [t for t in ctx.teachers] + ctx.managers

    questions = []
    solutions = []
    unsolved_old = 0
    for i in range(target):
        s = D.pick_weighted(rng, pairs)
        asked = T.local_ms(C.T1_START, 0) + rng.randrange(
            max(1, T.T_NOW - T.local_ms(C.T1_START, 0)))
        if not s.active_at(asked):
            asked = s.created_ms + C.DAY_MS
        key = q_fac.make(asked)
        approved = rng.random() < C.POOL_APPROVED_SHARE
        approver = approvers[rng.randrange(len(approvers))] if approved else None
        subject = None
        my = ctx.enrolled_courses.get(s.key, [])
        if my:
            co = my[rng.randrange(len(my))]
            if co.subjects:
                subject = co.subjects[rng.randrange(len(co.subjects))]
        if s.gap_subject_keys and rng.random() < 0.68:
            subject = ctx.subject_by_key.get(s.gap_subject_keys[0], subject)
        row = {
            "id": rid("pool_question", key),
            "asker": s.rid,
            "title": POOL_TITLES[i % len(POOL_TITLES)],
            "body": POOL_BODIES[i % len(POOL_BODIES)] + (
                " (%s)" % subject.name if subject else ""),
            "status": "approved" if approved else "pending",
            "asked_at": asked,
            "approved_by": approver.rid if approver else None,
            "image_file": None, "image_content_type": None, "image_size": None,
        }
        if rng.random() < C.POOL_IMAGE_SHARE:
            row["image_file"] = "pool/%s.png" % key.lower()
            row["image_content_type"] = "image/png"
            row["image_size"] = rng.randint(10_000, 600_000)
        questions.append(row)
        ctx.pool_true_subject.append({
            "id": "pool_question:" + key,
            "true_subject": ("subject:" + subject.key) if subject else None,
            "asker_archetype": s.archetype,
        })
        if approved and approver is not None:
            ctx.bump(approver, "pool_approved_total")
            ctx.bump(s, "pool_published_total")
        n_sol = 0
        if approved and rng.random() < C.POOL_SOLVED_SHARE:
            n_sol = 1 + D.poisson(rng, C.POOL_SOLUTIONS_PER_SOLVED - 1)
        if approved and n_sol == 0 and asked < T.T_NOW - 7 * C.DAY_MS:
            unsolved_old += 1
        for j in range(n_sol):
            if rng.random() < C.POOL_SOLUTION_TEACHER_SHARE:
                author = ctx.teachers[rng.randrange(len(ctx.teachers))]
            else:
                author = students[rng.randrange(len(students))]
            offered = asked + rng.randint(1, 72) * C.HOUR_MS
            if offered > T.T_NOW:
                offered = T.T_NOW - C.HOUR_MS
            solutions.append({
                "id": rid("solution", s_fac.make(offered)),
                "question": rid("pool_question", key),
                "author": author.rid,
                "body": SOLUTION_BODIES[(i + j) % len(SOLUTION_BODIES)],
                "offered_at": offered,
                "image_file": None, "image_content_type": None, "image_size": None,
            })
    em.add_many("pool_question", questions)
    em.add_many("solution", solutions)
    ctx.stats["pool_questions"] = len(questions)
    ctx.stats["solutions"] = len(solutions)
    ctx.stats["pool_unsolved_old"] = unsolved_old


# ---------------------------------------------------------------------------
# Sohbet
# ---------------------------------------------------------------------------

def build_chatbot(ctx) -> None:
    seed = ctx.seed
    em = ctx.emitter
    t_fac = UlidFactory(substream(seed, "ulid.chatbot_thread"))
    m_fac = UlidFactory(substream(seed, "ulid.chatbot_message"))
    rng = substream(seed, "chat.core")

    n_student_users = max(1, round(C.CHAT_STUDENT_USERS_FULL * ctx.scale.ratio))
    n_teacher_users = max(1, round(C.CHAT_TEACHER_USERS * ctx.scale.ratio))
    # A22: A7'de 18 ogrencinin 15'i hic sohbet kullanmaz -> 3'u listeye alinir
    a7 = [s for s in ctx.students if s.archetype == "A7"]
    others = [s for s in ctx.students if s.archetype != "A7"]
    n_a7 = min(len(a7), max(0, len(a7) - round(15 * ctx.scale.ratio)))
    users = (others[:max(0, n_student_users - n_a7)] + a7[:n_a7])[:n_student_users]
    for s in ctx.students:
        if s not in users:
            s.counters["chatbot_thread_count"] = 0
    users = list(users) + ctx.teachers[:n_teacher_users]

    threads = []
    messages = []
    failed_recent = {}
    pending = 0
    failed = 0
    for u in users:
        is_student = u.role == "student"
        base = C.CHAT_THREADS_PER_STUDENT if is_student else C.CHAT_THREADS_PER_TEACHER
        n_threads = min(C.MAX_CHATBOT_THREADS, max(1, D.poisson(rng, base)))
        for ti in range(n_threads):
            created = T.local_ms(C.T1_START, 0) + rng.randrange(
                max(1, T.T_NOW - T.local_ms(C.T1_START, 0)))
            if not u.active_at(created):
                created = u.created_ms + C.DAY_MS
            bk = T.break_kind(_epoch_date(created))
            if bk == "semester" and rng.random() > 0.35:
                continue
            tkey = t_fac.make(created)
            turns = 1 + D.poisson(rng, C.CHAT_TURNS_LAMBDA)
            cursor = created
            title = None
            for turn in range(turns):
                content = (rng.choice(C.CHAT_CONTENT_PROMPTS)
                           if rng.random() < C.CHAT_CONTENT_SHARE
                           else rng.choice(C.CHAT_SYSTEM_PROMPTS))
                if title is None and rng.random() < C.CHAT_TITLE_SHARE:
                    title = content[:40]
                messages.append({
                    "id": rid("chatbot_message", m_fac.make(cursor)),
                    "thread_id": rid("chatbot_thread", tkey),
                    "user_id": u.rid, "role": "user",
                    "content": content[:C.MAX_CHATBOT_MESSAGE_LEN],
                    "status": "complete", "truncated": False,
                    "error_code": None, "created_at": cursor,
                    "completed_at": cursor,
                })
                latency = int(D.clip(D.lognormal_median(rng, C.CHAT_LATENCY_MEDIAN_MS,
                                                        C.CHAT_LATENCY_SIGMA), 250, 25000))
                status = D.pick_weighted(rng, C.CHAT_STATUS_SHARES)
                if u.archetype == "A8" and rng.random() < 0.02:
                    status = "failed"
                # 'pending' kayitlar kuyrukta takili kalmis yanitlardir (#25);
                # yalniz son 24 saatle sinirlandirilirsa hedef 270 satira ulasilamaz.
                reply_ms = cursor + 1000
                err = None
                completed = reply_ms + latency
                if status == "failed":
                    err = D.pick_weighted(rng, C.CHAT_ERROR_CODES)
                    failed += 1
                    if cursor > T.T_NOW - 14 * C.DAY_MS:
                        failed_recent[u.key] = failed_recent.get(u.key, 0) + 1
                elif status == "pending":
                    completed = None
                    pending += 1
                body = (rng.choice(C.CHAT_CONTENT_REPLIES)
                        if content in C.CHAT_CONTENT_PROMPTS
                        else rng.choice(C.CHAT_SYSTEM_REPLIES))
                messages.append({
                    "id": rid("chatbot_message", m_fac.make(reply_ms)),
                    "thread_id": rid("chatbot_thread", tkey),
                    "user_id": u.rid, "role": "assistant",
                    "content": body[:C.MAX_CHATBOT_MESSAGE_LEN],
                    "status": status,
                    "truncated": rng.random() < C.CHAT_TRUNCATED_SHARE,
                    "error_code": err, "created_at": reply_ms,
                    "completed_at": completed,
                })
                cursor = completed or (reply_ms + latency)
                cursor += rng.randint(20_000, 600_000)
                if cursor > T.T_NOW:
                    cursor = T.T_NOW
            threads.append({
                "id": rid("chatbot_thread", tkey),
                "user_id": u.rid, "title": title,
                "created_at": created, "updated_at": min(cursor, T.T_NOW),
            })
            u.counters["chatbot_thread_count"] = u.counters.get("chatbot_thread_count", 0) + 1

    # T5(c): A8 arketipinde 11 ogrencide son 14 gunde >=3 'failed' mesaj bulunmali.
    # Zamanlama kaydirilarak bu tetikleyici veriye acikca gomulur (SENARYO 5.4).
    a8 = [s for s in ctx.students if s.archetype == "A8"]
    n_force = min(len(a8), max(1, round(C.CHAT_A8_FAILED_STUDENTS * ctx.scale.ratio)))
    for u in a8[:n_force]:
        created = T.T_NOW - rng.randint(2, 12) * C.DAY_MS
        tkey = t_fac.make(created)
        cursor = created
        first = None
        for turn in range(3 + rng.randrange(2)):
            content = rng.choice(C.CHAT_CONTENT_PROMPTS)
            if first is None:
                first = content
            messages.append({
                "id": rid("chatbot_message", m_fac.make(cursor)),
                "thread_id": rid("chatbot_thread", tkey),
                "user_id": u.rid, "role": "user",
                "content": content[:C.MAX_CHATBOT_MESSAGE_LEN],
                "status": "complete", "truncated": False,
                "error_code": None, "created_at": cursor, "completed_at": cursor,
            })
            reply_ms = cursor + 1000
            err = D.pick_weighted(rng, C.CHAT_ERROR_CODES)
            failed += 1
            failed_recent[u.key] = failed_recent.get(u.key, 0) + 1
            messages.append({
                "id": rid("chatbot_message", m_fac.make(reply_ms)),
                "thread_id": rid("chatbot_thread", tkey),
                "user_id": u.rid, "role": "assistant",
                "content": "Yanit uretilemedi.", "status": "failed",
                "truncated": False, "error_code": err,
                "created_at": reply_ms, "completed_at": reply_ms + 1200,
            })
            cursor = reply_ms + rng.randint(60_000, 3_600_000)
            if cursor > T.T_NOW:
                cursor = T.T_NOW
        threads.append({
            "id": rid("chatbot_thread", tkey), "user_id": u.rid,
            "title": first[:40] if first else None,
            "created_at": created, "updated_at": min(cursor, T.T_NOW),
        })
        u.counters["chatbot_thread_count"] = u.counters.get("chatbot_thread_count", 0) + 1

    em.add_many("chatbot_thread", threads)
    em.add_many("chatbot_message", messages)
    ctx.stats["chatbot_threads"] = len(threads)
    ctx.stats["chatbot_messages"] = len(messages)
    ctx.stats["chatbot_failed"] = failed
    ctx.stats["chatbot_assistant"] = sum(1 for m in messages if m["role"] == "assistant")
    ctx.stats["chatbot_pending"] = pending
    ctx.stats["a8_failed_3_in_14"] = sum(
        1 for s in ctx.students if s.archetype == "A8" and failed_recent.get(s.key, 0) >= 3)
    ctx.stats["students_using_chat"] = sum(
        1 for s in ctx.students if s.counters.get("chatbot_thread_count", 0) > 0)


def _epoch_date(ms):
    return _dt.date(1970, 1, 1) + _dt.timedelta(
        days=(ms - T.SHIFT_MS + C.TZ_OFFSET_MS) // C.DAY_MS)


# ---------------------------------------------------------------------------
# Notlar
# ---------------------------------------------------------------------------

def build_notes(ctx) -> None:
    seed = ctx.seed
    em = ctx.emitter
    n_fac = UlidFactory(substream(seed, "ulid.note"))
    f_fac = UlidFactory(substream(seed, "ulid.note_file"))
    rng = substream(seed, "note.core")

    notes = []
    files = []
    authors = D.take_share(rng, ctx.students, C.NOTE_STUDENT_SHARE)
    plan = [(s, C.NOTE_PER_STUDENT) for s in authors] + \
           [(t, C.NOTE_PER_TEACHER) for t in ctx.teachers]
    for u, count in plan:
        my = ctx.enrolled_courses.get(u.key, []) if u.role == "student" else \
            [c for c in ctx.courses if u in c.teachers]
        for i in range(count):
            created = T.local_ms(C.T1_START, 0) + rng.randrange(
                max(1, T.T_NOW - T.local_ms(C.T1_START, 0)))
            if not u.active_at(created):
                created = u.created_ms + C.DAY_MS
            subject_name = "Genel"
            if my:
                co = my[rng.randrange(len(my))]
                if co.subjects:
                    subject_name = co.subjects[rng.randrange(len(co.subjects))].name
            key = n_fac.make(created)
            n_files = 0
            if rng.random() < C.NOTE_FILE_SHARE:
                n_files = min(C.MAX_NOTE_FILES, 1 if rng.random() < 0.8 else 2)
                for f in range(n_files):
                    files.append({
                        "id": rid("note_file", f_fac.make(created + f + 1)),
                        "note": rid("note", key),
                        "name": "not-%d.png" % (f + 1),
                        "content_type": "image/png",
                        "size": rng.randint(20_000, 1_500_000),
                    })
            notes.append({
                "id": rid("note", key), "user": u.rid,
                "title": "%s — çalışma notu" % subject_name,
                "content": ("%s konusunda dikkat edilecekler: tanımlar, formüller ve "
                            "örnek sorular." % subject_name),
                "file_count": n_files,
            })
    em.add_many("note", notes)
    em.add_many("note_file", files)
    ctx.stats["notes"] = len(notes)


# ---------------------------------------------------------------------------
# Mesajlar
# ---------------------------------------------------------------------------

def build_messages(ctx) -> None:
    seed = ctx.seed
    em = ctx.emitter
    fac = UlidFactory(substream(seed, "ulid.message"))
    rng = substream(seed, "message.core")

    target = max(10, round(C.MESSAGE_TOTAL_FULL * ctx.scale.ratio))
    staff = ctx.teachers + ctx.managers + [ctx.admin]
    rows = []
    for i in range(target):
        kind = D.pick_weighted(rng, C.MESSAGE_DIRECTION_SHARES)
        if kind == "student_teacher":
            sender = ctx.students[rng.randrange(len(ctx.students))]
            recipient = ctx.teachers[rng.randrange(len(ctx.teachers))]
        elif kind == "teacher_student":
            sender = ctx.teachers[rng.randrange(len(ctx.teachers))]
            recipient = ctx.students[rng.randrange(len(ctx.students))]
        elif kind == "parent_teacher":
            if not ctx.parent_links:
                continue
            parent, _student = ctx.parent_links[rng.randrange(len(ctx.parent_links))]
            sender = parent
            recipient = ctx.teachers[rng.randrange(len(ctx.teachers))]
        elif kind == "teacher_parent":
            if not ctx.parent_links:
                continue
            parent, _student = ctx.parent_links[rng.randrange(len(ctx.parent_links))]
            sender = ctx.teachers[rng.randrange(len(ctx.teachers))]
            recipient = parent
        else:
            sender = staff[rng.randrange(len(staff))]
            pool = ctx.students + ctx.parents + ctx.teachers
            recipient = pool[rng.randrange(len(pool))]
        # ROL KISITI: öğrenci ve veli yalnız öğretmen+ kullanıcılara yazabilir
        if sender.role in ("student", "parent") and \
                recipient.role not in ("teacher", "manager", "admin"):
            continue
        sent = T.local_ms(C.T1_START, 0) + rng.randrange(
            max(1, T.T_NOW - T.local_ms(C.T1_START, 0)))
        if not sender.active_at(sent) or not recipient.active_at(sent):
            continue
        sf = D.pick_weighted(rng, C.MESSAGE_SENDER_FOLDERS)
        rf = D.pick_weighted(rng, C.MESSAGE_RECIPIENT_FOLDERS)
        rows.append({
            "id": rid("message", fac.make(sent)),
            "sender": sender.rid, "recipient": recipient.rid,
            "subject": C.MESSAGE_SUBJECTS[i % len(C.MESSAGE_SUBJECTS)],
            "body": C.MESSAGE_BODIES[i % len(C.MESSAGE_BODIES)],
            "label": (C.MESSAGE_LABELS[i % len(C.MESSAGE_LABELS)]
                      if rng.random() < C.MESSAGE_LABEL_SHARE else None),
            "sent_at": sent,
            "read": rng.random() < C.MESSAGE_READ_SHARE,
            "sender_folder": sf,
            "recipient_folder": rf,
            "sender_origin": None if sf == "sent" else "sent",
            "recipient_origin": None if rf == "inbox" else "inbox",
        })
    em.add_many("message", rows)
    ctx.stats["messages"] = len(rows)
    ctx.stats["messages_read"] = sum(1 for r in rows if r["read"])


# ---------------------------------------------------------------------------
# Tahtalar
# ---------------------------------------------------------------------------

def build_boards(ctx) -> None:
    seed = ctx.seed
    em = ctx.emitter
    b_fac = UlidFactory(substream(seed, "ulid.board"))
    s_fac = UlidFactory(substream(seed, "ulid.board_stroke"))
    rng = substream(seed, "board.core")

    # Öğretmen tahtaları ders anlatımına bağlıdır (24 öğretmen), ölçeklenmez.
    n_teacher = C.BOARD_TEACHER_COUNT
    n_student = max(1, round(C.BOARD_STUDENT_COUNT * ctx.scale.ratio))
    n_closed, n_locked, n_epoch2 = C.BOARD_CLOSED, C.BOARD_LOCKED, C.BOARD_EPOCH2
    strokes_target = round(C.BOARD_STROKES_TOTAL
                           * (C.BOARD_TEACHER_COUNT + C.BOARD_STUDENT_COUNT * ctx.scale.ratio)
                           / (C.BOARD_TEACHER_COUNT + C.BOARD_STUDENT_COUNT))

    creators = [ctx.teachers[i % len(ctx.teachers)] for i in range(n_teacher)] + \
               [ctx.students[i % len(ctx.students)] for i in range(n_student)]
    boards = []
    strokes = []
    per_board = max(4, strokes_target // max(1, len(creators)))
    for i, creator in enumerate(creators):
        created = T.local_ms(C.T1_START, 0) + rng.randrange(
            max(1, T.T_NOW - T.local_ms(C.T1_START, 0)))
        if not creator.active_at(created):
            created = creator.created_ms + C.DAY_MS
        key = b_fac.make(created)
        lo_hi = D.pick_weighted(rng, C.BOARD_PARTICIPANT_SHARES)
        n_part = rng.randint(lo_hi[0], lo_hi[1])
        pool = ctx.students if creator.role == "teacher" else ctx.students
        participants = []
        for _ in range(n_part):
            u = pool[rng.randrange(len(pool))]
            if u.rid not in participants:
                participants.append(u.rid)
        epoch = 2 if i < n_epoch2 else 0
        n_strokes = max(1, D.poisson(rng, per_board))
        epoch_count = 0
        total_count = 0
        cursor = created + 60_000
        cur_epoch = 0
        for j in range(n_strokes):
            cursor += rng.randint(2_000, 60_000)
            if cursor > T.T_NOW:
                break
            # D24: vuruslarin %3'u 'clear' isaretcisidir; her clear epoch'u artirir
            is_clear = rng.random() < C.BOARD_CLEAR_SHARE
            if is_clear:
                strokes.append({
                    "id": rid("board_stroke", s_fac.make(cursor)),
                    "board": rid("board", key), "author": creator.rid,
                    "kind": "clear", "payload": None, "count": None,
                    "epoch": cur_epoch, "created_at": cursor,
                })
                total_count += 1
                cur_epoch += 1
                epoch_count = 0
                continue
            if participants and rng.random() < 0.35:
                author_rid = participants[rng.randrange(len(participants))]
            else:
                author_rid = creator.rid
            strokes.append({
                "id": rid("board_stroke", s_fac.make(cursor)),
                "board": rid("board", key), "author": author_rid,
                "kind": "stroke",
                "payload": _fake_path(rng),
                "count": rng.randint(2, 40),
                "epoch": cur_epoch, "created_at": cursor,
            })
            epoch_count += 1
            total_count += 1
        locked = i < n_locked
        closed = n_locked <= i < n_locked + n_closed
        boards.append({
            "id": rid("board", key), "creator": creator.rid,
            "title": "Tahta %d — %s" % (i + 1, rng.choice(
                ["konu anlatımı", "soru çözümü", "grup çalışması", "deneme"])),
            "participants": participants,
            "locked": locked,
            "locked_by": creator.rid if locked else None,
            "locked_at": cursor if locked else None,
            "epoch": cur_epoch,
            "epoch_stroke_count": epoch_count,
            "total_stroke_count": total_count,
            "closed_at": cursor if closed else None,
            "created_at": created,
        })
        creator.counters["board_count"] = creator.counters.get("board_count", 0) + 1
    em.add_many("board", boards)
    em.add_many("board_stroke", strokes)
    ctx.stats["boards"] = len(boards)
    ctx.stats["board_strokes"] = len(strokes)
    ctx.stats["board_clear"] = sum(1 for s in strokes if s["kind"] == "clear")


def _fake_path(rng):
    pts = ["M %d %d" % (rng.randint(0, 800), rng.randint(0, 600))]
    for _ in range(rng.randint(3, 24)):
        pts.append("L %d %d" % (rng.randint(0, 800), rng.randint(0, 600)))
    return " ".join(pts)[:4096]


# ---------------------------------------------------------------------------
# Rozetler
# ---------------------------------------------------------------------------

def build_badges(ctx) -> None:
    """E13: rozet yalnız ilgili sayaç eşiği aştığında verilir."""
    em = ctx.emitter
    rng = substream(ctx.seed, "badge.core")
    rows = []
    for u in ctx.users:
        for badge, counter, threshold in C.BADGES:
            if counter in C.UNWRITTEN_COUNTERS:
                continue
            value = u.counters.get(counter)
            if value is None or value < threshold:
                continue
            earned = T.T_NOW - rng.randint(1, 180) * C.DAY_MS
            if earned < u.created_ms:
                earned = u.created_ms + C.DAY_MS
            rows.append({
                "id": rid("badge_award", "%s_%s" % (u.key, badge)),
                "user": u.rid, "badge": badge, "earned_at": earned,
            })
    em.add_many("badge_award", rows)
    ctx.stats["badges"] = len(rows)
