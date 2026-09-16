"""Operasyon alanı: randevu, etkinlik, yemek, ödeme, mesai.

Ledger tabloları (meal_ledger / payment_ledger) READONLY ve append-only'dir;
kayıt kimlikleri `domain/meal_ledger.rs` ve `domain/payment_ledger.rs` gramerine
uyar (c = charge, r = reversal, k = credit, kr = refund).
"""

from __future__ import annotations

import datetime as _dt

import config as C
import dists as D
import timeline as T
from ids import UlidFactory, random_ulid, rid, substream


# ---------------------------------------------------------------------------
# Randevu
# ---------------------------------------------------------------------------

def build_appointments(ctx) -> None:
    seed = ctx.seed
    em = ctx.emitter
    slot_fac = UlidFactory(substream(seed, "ulid.appointment_slot"))
    app_fac = UlidFactory(substream(seed, "ulid.appointment"))
    series_fac = UlidFactory(substream(seed, "ulid.appointment_series"))
    rng = substream(seed, "appointment.core")

    # Randevu slotu öğretmen sayısına bağlıdır, öğrenci sayısına değil.
    n_teachers = min(C.APPOINTMENT_TEACHERS, len(ctx.teachers))
    teachers = ctx.teachers[:n_teachers]
    weeks = T.past_teaching_weeks()
    future_weeks = [w for w in T.all_teaching_weeks() if w not in weeks]
    future_weeks = future_weeks[:C.APPOINTMENT_FUTURE_WEEKS]
    all_weeks = weeks + future_weeks

    student_weights = [(s, max(0.05, s.arch["appointments"])) for s in ctx.students]
    slots = []
    appointments = []
    old_pending = 0
    for t_i, t in enumerate(teachers):
        series_id = None
        if rng.random() < C.APPOINTMENT_SERIES_SHARE:
            series_id = series_fac.make(T.local_ms(C.T1_START, 9 * 60))
        for w_i, w in enumerate(all_weeks):
            # Her hafta slot açılmaz (§2.7: öğretmen başına ~2 slot/hafta)
            if (w_i + t_i) % 4 == 0:
                continue
            for wd in C.APPOINTMENT_SLOT_DAYS[(t_i % 2):(t_i % 2) + 1]:
                day = w + _dt.timedelta(days=wd)
                if not T.is_school_day(day):
                    continue
                for minute in C.APPOINTMENT_SLOT_MINUTES:
                    starts = T.local_ms(day, minute)
                    created = min(starts - 7 * C.DAY_MS, T.T_NOW - C.HOUR_MS)
                    key = slot_fac.make(created)
                    occupied = 0
                    if rng.random() < C.APPOINTMENT_REQUEST_SHARE:
                        status = D.pick_weighted(rng, C.APPOINTMENT_STATUS_SHARES)
                        if status in ("pending", "approved"):
                            occupied = 1
                        if rng.random() < C.APPOINTMENT_STUDENT_SHARE:
                            # Talep sikligi arketipe baglidir (A8 en yuksek)
                            requester = D.pick_weighted(rng, student_weights)
                        else:
                            if ctx.parent_links:
                                requester = ctx.parent_links[
                                    rng.randrange(len(ctx.parent_links))][0]
                            else:
                                requester = ctx.students[rng.randrange(len(ctx.students))]
                        a_created = created + rng.randint(1, 5) * C.DAY_MS
                        if a_created > T.T_NOW:
                            a_created = T.T_NOW - C.HOUR_MS
                        if status == "pending" and rng.random() < C.APPOINTMENT_OLD_PENDING_SHARE:
                            a_created = T.T_NOW - rng.randint(4, 20) * C.DAY_MS
                            old_pending += 1
                        proposed = rng.random() < C.APPOINTMENT_PROPOSED_SHARE
                        appointments.append({
                            "id": rid("appointment", app_fac.make(a_created)),
                            "slot": rid("appointment_slot", key),
                            "requester": requester.rid,
                            "status": status,
                            "reason": C.APPOINTMENT_REASONS[
                                rng.randrange(len(C.APPOINTMENT_REASONS))][
                                    :C.MAX_APPOINTMENT_REASON_LEN],
                            "proposed_starts_at": starts + 20 * C.MIN_MS if proposed else None,
                            "proposed_ends_at": starts + 40 * C.MIN_MS if proposed else None,
                            "proposed_by": t.rid if proposed else None,
                            "decided_by": t.rid if status in ("approved", "rejected") else None,
                            "cancelled_by": (requester.rid if status == "cancelled" else None),
                            "cancel_reason": (
                                C.APPOINTMENT_CANCEL_REASONS[
                                    rng.randrange(len(C.APPOINTMENT_CANCEL_REASONS))]
                                if status == "cancelled"
                                and rng.random() < C.APPOINTMENT_CANCEL_REASON_SHARE
                                else None),
                            "reject_reason": (
                                C.APPOINTMENT_REJECT_REASONS[
                                    rng.randrange(len(C.APPOINTMENT_REJECT_REASONS))]
                                if status == "rejected" else None),
                            "created_at": a_created,
                        })
                        if requester.role == "student":
                            ctx.appointment_by_student[requester.archetype] = \
                                ctx.appointment_by_student.get(requester.archetype, 0) + 1
                    slots.append({
                        "id": rid("appointment_slot", key),
                        "teacher": t.rid,
                        "starts_at": starts,
                        "ends_at": starts + C.APPOINTMENT_SLOT_LEN_MIN * C.MIN_MS,
                        "occupied": occupied,
                        "note": None,
                        "series": series_id,
                        "created_at": created,
                    })
    em.add_many("appointment_slot", slots)
    em.add_many("appointment", appointments)
    ctx.stats["appointment_slots"] = len(slots)
    ctx.stats["appointments"] = len(appointments)
    ctx.stats["appointments_old_pending"] = old_pending


# ---------------------------------------------------------------------------
# Etkinlik
# ---------------------------------------------------------------------------

def build_events(ctx) -> None:
    seed = ctx.seed
    em = ctx.emitter
    fac = UlidFactory(substream(seed, "ulid.event"))
    rng = substream(seed, "event.core")

    # Etkinlikler okul takvimine bağlıdır, öğrenci sayısına değil.
    n_past, n_future = C.EVENT_PAST, C.EVENT_FUTURE
    n_att_events = C.EVENT_ATTENDANCE_EVENTS
    n_full = C.EVENT_FULL_CAPACITY
    staff = ctx.managers + [ctx.admin] + ctx.teachers

    events = []
    registrations = []
    attendances = []
    att_done = 0
    for i in range(n_past + n_future):
        past = i < n_past
        if past:
            d = C.T1_START + _dt.timedelta(days=rng.randrange(
                max(1, (_dt.date(2026, 4, 12) - C.T1_START).days)))
            while not T.is_school_day(d):
                d += _dt.timedelta(days=1)
            starts = T.local_ms(d, rng.choice([600, 780, 900]))
            if starts > T.T_NOW:
                starts = T.T_NOW - rng.randint(1, 30) * C.DAY_MS
        else:
            starts = T.T_NOW + rng.randint(2, 60) * C.DAY_MS
            if starts > T.local_ms(C.T2_END, 0):
                starts = T.local_ms(C.T2_END, 600)
        created = min(starts - 10 * C.DAY_MS, T.T_NOW - C.HOUR_MS)
        key = fac.make(created)
        kind = D.pick_weighted(rng, C.EVENT_AUDIENCE_SHARES)
        audience = {"kind": kind, "role": None, "course": None, "class": None,
                    "capacity": None}
        scope = list(ctx.students)
        if kind == "role":
            audience["role"] = "student"
        elif kind == "class":
            cg = ctx.classes[rng.randrange(len(ctx.classes))]
            audience["class"] = cg.rid
            scope = list(cg.students)
        elif kind == "course":
            co = ctx.courses[rng.randrange(len(ctx.courses))]
            audience["course"] = co.rid
            scope = list(co.students)
        elif kind == "registration":
            audience["capacity"] = rng.choice([20, 30, 40, 60])
        creator = staff[rng.randrange(len(staff))]
        n_reg = 0
        regs = []
        if scope:
            share = C.EVENT_REGISTRATION_SHARE
            picked = D.take_share(rng, scope, share)
            if kind == "registration":
                cap = audience["capacity"]
                if i < n_full:
                    picked = picked[:cap] if len(picked) >= cap else picked
                    audience["capacity"] = len(picked)
                else:
                    picked = picked[:cap]
            for s in picked:
                if not s.active_at(starts):
                    continue
                regs.append({
                    "id": rid("registration", "%s_%s" % (key, s.key)),
                    "event": rid("event", key), "user": s.rid,
                    "registered_by": creator.rid,
                })
                n_reg += 1
        registrations.extend(regs)
        if past and att_done < n_att_events:
            att_done += 1
            for r in regs:
                status = "present" if rng.random() < 0.88 else (
                    "absent" if rng.random() < 0.7 else "excused")
                attendances.append({
                    "id": rid("attendance", r["id"].key),
                    "event": rid("event", key),
                    "user": r["user"], "status": status,
                    "marked_by": creator.rid,
                })
        events.append({
            "id": rid("event", key), "creator": creator.rid,
            "title": C.EVENT_TITLES[i % len(C.EVENT_TITLES)],
            "description": "Okulumuzda düzenlenecek etkinlik hakkında bilgilendirme.",
            "audience": audience,
            "registration_count": n_reg,
            "starts_at": starts,
            "ends_at": starts + rng.choice([60, 90, 120, 180]) * C.MIN_MS,
        })
    em.add_many("event", events)
    em.add_many("registration", registrations)
    em.add_many("attendance", attendances)
    ctx.stats["events"] = len(events)
    ctx.stats["registrations"] = len(registrations)
    ctx.stats["event_attendance"] = len(attendances)


# ---------------------------------------------------------------------------
# Yemek
# ---------------------------------------------------------------------------

def build_meals(ctx) -> None:
    seed = ctx.seed
    em = ctx.emitter
    dish_fac = UlidFactory(substream(seed, "ulid.menu_dish"))
    led_fac = UlidFactory(substream(seed, "ulid.meal_ledger"))
    rng = substream(seed, "meal.core")
    book_rng = substream(seed, "meal.booking")

    days = [d for d in T.past_school_days()]
    menus = []
    dishes = []
    bookings = []
    attendances = []
    ledger = []
    slot_counts = {s: 0 for s in C.MEAL_SLOTS}
    students = [s for s in ctx.students]

    for di, day in enumerate(days):
        slots = ["lunch"]
        if di % 5 < C.MENU_SNACK_DAYS_PER_WEEK:
            slots.append("snack")
        if di % 2 == 0:
            slots.append("breakfast")
        for slot in slots:
            date_s = T.date_text(day)
            key = "%s_%s" % (date_s, slot)
            created = T.local_ms(day - _dt.timedelta(days=3), 9 * 60)
            menu_rid = rid("menu", key)
            price_total = 0
            n_dishes = C.MENU_DISHES_PER_MENU
            for j in range(n_dishes):
                price = rng.randint(*C.DISH_PRICE_MINOR)
                price_total += price
                tags = []
                if rng.random() < C.DISH_TAG_SHARE:
                    tags = [C.DIETARY_TAGS[rng.randrange(len(C.DIETARY_TAGS))]]
                    if rng.random() < 0.3:
                        t2 = C.DIETARY_TAGS[rng.randrange(len(C.DIETARY_TAGS))]
                        if t2 not in tags:
                            tags.append(t2)
                dishes.append({
                    "id": rid("menu_dish", dish_fac.make(created + j)),
                    "menu": menu_rid,
                    "name": C.DISH_NAMES[(di * 4 + j) % len(C.DISH_NAMES)],
                    "description": None,
                    "price_minor": min(price, C.MAX_DISH_PRICE_MINOR),
                    "tags": tags,
                    "created_at": created + j,
                })
            if slot == "lunch":
                target = C.MEAL_BOOKING_LUNCH_PER_DAY
            elif slot == "snack":
                target = C.MEAL_BOOKING_SNACK_PER_DAY
            else:
                target = C.MEAL_BOOKING_BREAKFAST_PER_DAY
            target = max(1, round(target * ctx.scale.ratio))
            picked = D.take_share(book_rng, students, min(1.0, target / max(1, len(students))))
            seats = 0
            for s in picked:
                if not s.active_at(T.local_ms(day, 12 * 60)):
                    continue
                bkey = "%s_%s" % (key, s.key)
                cancelled = book_rng.random() < C.MEAL_BOOKING_CANCEL_SHARE
                attempt = 2 if book_rng.random() < C.MEAL_BOOKING_ATTEMPT2_SHARE else 1
                b_created = T.local_ms(day - _dt.timedelta(days=1), 20 * 60)
                bookings.append({
                    "id": rid("meal_booking", bkey),
                    "menu": menu_rid, "student": s.rid,
                    "booked_by": s.rid,
                    "status": "cancelled" if cancelled else "booked",
                    "attempt": attempt,
                    "price_minor": price_total,
                    "cancelled_at": (b_created + 6 * C.HOUR_MS) if cancelled else None,
                    "created_at": b_created,
                })
                ledger.append({
                    "id": rid("meal_ledger", "%s_c%d" % (bkey, attempt)),
                    "student": s.rid, "kind": "charge",
                    "amount_minor": min(price_total, C.MAX_LEDGER_AMOUNT_MINOR),
                    "source": rid("meal_booking", bkey),
                    "method": None, "note": None,
                    "recorded_by": ctx.managers[0].rid, "created_at": b_created,
                })
                if cancelled:
                    ledger.append({
                        "id": rid("meal_ledger", "%s_r%d" % (bkey, attempt)),
                        "student": s.rid, "kind": "reversal",
                        "amount_minor": min(price_total, C.MAX_LEDGER_AMOUNT_MINOR),
                        "source": rid("meal_booking", bkey),
                        "method": None, "note": "İptal iadesi",
                        "recorded_by": ctx.managers[0].rid,
                        "created_at": b_created + 6 * C.HOUR_MS,
                    })
                else:
                    seats += 1
                    if book_rng.random() < C.MEAL_ATTENDANCE_SHARE:
                        served = book_rng.random() < C.MEAL_ATTENDANCE_SERVED
                        attendances.append({
                            "id": rid("meal_attendance", bkey),
                            "menu": menu_rid, "student": s.rid,
                            "status": "served" if served else "missed",
                            "marked_by": ctx.managers[0].rid,
                            "marked_at": T.local_ms(
                                day, C.MEAL_SLOT_SERVING_MINUTE[slot] + 15),
                        })
            menus.append({
                "id": menu_rid, "date": date_s, "slot": slot,
                "capacity": C.MENU_CAPACITY[slot],
                "seats_booked": seats,
                "version": 0,
                "created_by": ctx.managers[0].rid,
                "created_at": created,
            })
            slot_counts[slot] += 1

    # aylık veli ödemesi (credit) — idempotent kredi kimliği
    n_credit = max(2, round(C.MEAL_CREDIT_ROWS * ctx.scale.ratio))
    for i in range(n_credit):
        s = students[i % len(students)]
        when = T.T_NOW - rng.randint(1, 200) * C.DAY_MS
        req = random_ulid(rng, when)
        ledger.append({
            "id": rid("meal_ledger", "%s_k_%s" % (s.key, req)),
            "student": s.rid, "kind": "credit",
            "amount_minor": rng.choice([50_000, 100_000, 150_000, 200_000]),
            "source": None,
            "method": D.pick_weighted(rng, C.PAYMENT_METHODS),
            "note": "Yemek bakiyesi yüklemesi",
            "recorded_by": ctx.managers[0].rid, "created_at": when,
        })

    em.add_many("menu", menus)
    em.add_many("menu_dish", dishes)
    em.add_many("meal_booking", bookings)
    em.add_many("meal_attendance", attendances)
    em.add_many("meal_ledger", ledger)
    ctx.slot_ref_counts = slot_counts
    ctx.stats["menus"] = len(menus)
    ctx.stats["meal_bookings"] = len(bookings)
    ctx.stats["meal_ledger"] = len(ledger)
    del led_fac

    # diyet profilleri
    prof_rng = substream(seed, "meal.diet")
    rows = []
    for s in D.take_share(prof_rng, students, C.DIETARY_PROFILE_SHARE):
        n_tags = prof_rng.randint(1, 3)
        tags = []
        for _ in range(n_tags):
            t = C.DIETARY_TAGS[prof_rng.randrange(len(C.DIETARY_TAGS))]
            if t not in tags:
                tags.append(t)
        rows.append({
            "id": rid("dietary_profile", s.key),
            "student": s.rid, "tags": tags,
            "note": None,
            "updated_by": ctx.managers[0].rid,
            "updated_at": T.local_ms(C.T1_START, 10 * 60),
        })
    em.add_many("dietary_profile", rows)


# ---------------------------------------------------------------------------
# Ödeme
# ---------------------------------------------------------------------------

def build_payments(ctx) -> None:
    seed = ctx.seed
    em = ctx.emitter
    plan_fac = UlidFactory(substream(seed, "ulid.fee_plan"))
    rng = substream(seed, "payment.core")

    students = list(ctx.students)
    rng.shuffle(students)
    counts = D.largest_remainder(len(students), [p[1] for p in C.FEE_PLANS])
    created = T.local_ms(_dt.date(2025, 9, 1), 9 * 60)

    plans = []
    assignments = []
    ledger = []
    cursor = 0
    for pi, (name, _n, n_inst, amount) in enumerate(C.FEE_PLANS):
        key = plan_fac.make(created + pi * 60_000)
        plan_rid = rid("fee_plan", key)
        installments = []
        due = C.FEE_FIRST_DUE
        for k in range(n_inst):
            month = due.month + k
            year = due.year + (month - 1) // 12
            month = (month - 1) % 12 + 1
            installments.append({"amount_minor": amount,
                                 "due_at": T.local_ms(_dt.date(year, month, 10), 0)})
        mine = students[cursor:cursor + counts[pi]]
        cursor += counts[pi]
        for s in mine:
            akey = "%s_%s" % (key, s.key)
            assignments.append({
                "id": rid("fee_plan_assignment", akey),
                "plan": plan_rid, "student": s.rid,
                "assigned_by": ctx.managers[0].rid,
                "created_at": created,
            })
            for n, inst in enumerate(installments, start=1):
                if inst["due_at"] > T.local_ms(C.T2_END, 0):
                    continue
                line_key = "%s_c%d" % (akey, n)
                ledger.append({
                    "id": rid("payment_ledger", line_key),
                    "student": s.rid, "kind": "charge",
                    "amount_minor": min(inst["amount_minor"], C.MAX_LEDGER_AMOUNT_MINOR),
                    "source": rid("fee_plan_assignment", akey),
                    "due_at": inst["due_at"], "method": None, "note": None,
                    "recorded_by": ctx.managers[0].rid,
                    "created_at": inst["due_at"],
                })
                if inst["due_at"] > T.T_NOW:
                    continue
                on_time = rng.random() < C.PAYMENT_ON_TIME_SHARE
                if on_time:
                    paid = inst["due_at"] - int(D.exponential(rng, 4.0) * C.DAY_MS)
                else:
                    paid = inst["due_at"] + int(
                        D.exponential(rng, C.PAYMENT_LATE_MEDIAN_DAYS) * C.DAY_MS)
                if paid > T.T_NOW:
                    continue
                req = random_ulid(rng, paid)
                ledger.append({
                    "id": rid("payment_ledger", "%s_k_%s" % (line_key, req)),
                    "student": s.rid, "kind": "credit",
                    "amount_minor": min(inst["amount_minor"], C.MAX_LEDGER_AMOUNT_MINOR),
                    "source": rid("fee_plan_assignment", akey),
                    "due_at": inst["due_at"],
                    "method": D.pick_weighted(rng, C.PAYMENT_METHODS),
                    "note": None,
                    "recorded_by": ctx.managers[0].rid,
                    "created_at": paid,
                })
        plans.append({
            "id": plan_rid, "name": name,
            "installments": installments,
            "created_by": ctx.managers[0].rid,
            "created_at": created,
            "assignment_count": len(mine),
        })

    # iadeler
    n_ref = max(1, round(C.PAYMENT_REFUNDS * ctx.scale.ratio))
    credits = [r for r in ledger if r["kind"] == "credit"]
    for i in range(min(n_ref, len(credits))):
        src = credits[i * max(1, len(credits) // max(1, n_ref)) % len(credits)]
        when = src["created_at"] + 10 * C.DAY_MS
        if when > T.T_NOW:
            when = T.T_NOW - C.DAY_MS
        req = random_ulid(rng, when)
        ledger.append({
            "id": rid("payment_ledger", "%s_kr_%s" % (src["id"].key, req)),
            "student": src["student"], "kind": "refund",
            "amount_minor": src["amount_minor"],
            "source": src["source"], "due_at": src["due_at"],
            "method": src["method"], "note": "Fazla tahsilat iadesi",
            "recorded_by": ctx.managers[0].rid, "created_at": when,
        })

    em.add_many("fee_plan", plans)
    em.add_many("fee_plan_assignment", assignments)
    em.add_many("payment_ledger", ledger)
    ctx.stats["fee_plan_assignments"] = len(assignments)
    ctx.stats["payment_ledger"] = len(ledger)


# ---------------------------------------------------------------------------
# Mesai
# ---------------------------------------------------------------------------

def build_work_entries(ctx) -> None:
    seed = ctx.seed
    em = ctx.emitter
    fac = UlidFactory(substream(seed, "ulid.work_entry"))
    rng = substream(seed, "work.core")

    staff = ctx.teachers + ctx.managers + [ctx.admin]
    days = T.past_school_days()
    n_open = max(1, round(C.WORK_ENTRY_OPEN_STAFF * ctx.scale.ratio))
    open_staff = set(u.key for u in staff[:n_open])
    rows = []
    for u in staff:
        opened = False
        for i, day in enumerate(days):
            if rng.random() >= C.WORK_ENTRY_DAY_SHARE:
                continue
            check_in = T.local_ms(day, rng.randint(*C.WORK_CHECK_IN_MINUTE))
            if check_in > T.T_NOW:
                continue
            last_day = (i == len(days) - 1)
            if u.key in open_staff and last_day and not opened:
                opened = True
                rows.append({
                    "id": rid("work_entry", "open_%s" % u.key),
                    "user": u.rid, "check_in": check_in, "check_out": None,
                })
                continue
            check_out = T.local_ms(day, rng.randint(*C.WORK_CHECK_OUT_MINUTE))
            rows.append({
                "id": rid("work_entry", fac.make(check_out)),
                "user": u.rid, "check_in": check_in, "check_out": check_out,
            })
    em.add_many("work_entry", rows)
    ctx.stats["work_entries"] = len(rows)
