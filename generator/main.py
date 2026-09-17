"""Hezarfen tohum verisi üreticisi — CLI ve üretim akışı.

Kullanım:
    python main.py --scale full --seed 20260413 --out ../seed

Akış SENARYO Ek A'daki topolojik sırayı izler; dosyalar
`schema.json -> load_order` sırasına göre numaralanır.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import statistics
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import academics
import assessment
import config as C
import counters
import emit
import engagement
import operations
import people
import timeline as T
import verify_queries
from world import Ctx, SCALES

DEFAULT_SCHEMA = os.path.normpath(os.path.join(BASE, "..", "spec", "schema.json"))
DEFAULT_OUT = os.path.normpath(os.path.join(BASE, "..", "seed"))


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Hezarfen 250 öğrencilik tohum verisi üreticisi")
    ap.add_argument("--seed", type=int, default=C.SEED_DEFAULT,
                    help="Rastgelelik tohumu (varsayılan %d)" % C.SEED_DEFAULT)
    ap.add_argument("--scale", choices=sorted(SCALES), default="full",
                    help="Ölçek profili: full (250 öğrenci) veya smoke (20)")
    ap.add_argument("--date-shift-days", type=int, default=0,
                    help="Tüm zaman damgalarına eklenecek gün (152/154 önerilir)")
    ap.add_argument("--out", default=DEFAULT_OUT, help="Çıktı dizini")
    ap.add_argument("--schema", default=DEFAULT_SCHEMA, help="schema.json yolu")
    ap.add_argument("--keep-parts", action="store_true",
                    help="Geçici parça dosyalarını silme (hata ayıklama)")
    return ap.parse_args(argv)


def generate(args):
    started = time.time()
    T.configure(args.date_shift_days)
    emit.load_schema(args.schema)
    os.makedirs(args.out, exist_ok=True)
    emitter = emit.Emitter(args.out)
    ctx = Ctx(args.seed, SCALES[args.scale], args.date_shift_days, emitter)

    def step(label, fn):
        t0 = time.time()
        fn(ctx)
        print("  %-28s %6.1f sn" % (label, time.time() - t0), flush=True)

    print("Hezarfen tohum verisi üretiliyor (ölçek=%s, tohum=%d, kaydırma=%d gün)"
          % (args.scale, args.seed, args.date_shift_days), flush=True)

    step("kimlik (user/parent_link)", people.build_people)
    step("akademik yapı", academics.build_structure)
    ctx.all_gap_subjects = {k for s in ctx.students for k in s.gap_subject_keys}
    step("ders programı", academics.build_timetable)
    step("sınav takvimi", assessment.schedule_exams)
    ctx.expected_question_count = sum(e.n_questions for e in ctx.exams)
    step("soru bankası", assessment.build_bank_templates)
    step("sınav soruları", assessment.build_questions)
    step("oturum + yoklama", academics.build_sessions)
    step("deneme + cevap + sonuç", assessment.build_attempts)
    step("ödev", engagement.build_homework)
    step("pomodoro", engagement.build_pomodoro)
    step("soru havuzu", engagement.build_pool)
    step("randevu", operations.build_appointments)
    step("etkinlik", operations.build_events)
    step("yemek", operations.build_meals)
    step("ödeme", operations.build_payments)
    step("mesai", operations.build_work_entries)
    step("sohbet", engagement.build_chatbot)
    step("not", engagement.build_notes)
    step("ders notu", academics.build_course_notes)
    step("mesaj", engagement.build_messages)
    step("tahta", engagement.build_boards)
    step("bozma adımı", assessment.apply_sabotage)
    step("sınav satırları", assessment.emit_exam_rows)
    step("rozet", engagement.build_badges)
    step("yapı sayaçları", counters.emit_structure)
    step("referans tabloları", counters.emit_reference_tables)
    step("kullanıcı satırları", counters.emit_users)

    emitter.close_all()
    files = emitter.assemble(C.FILE_LAYOUT, C.FILE_DESCRIPTIONS)
    if not args.keep_parts:
        emitter.cleanup()

    control_path = os.path.join(args.out, "00_control.surql")
    counters.write_control_file(control_path, T.local_ms(_dt.date(2025, 8, 15), 9 * 60))
    files.insert(0, ("00_control.surql", os.path.getsize(control_path)))

    verify_path = os.path.join(args.out, "99_dogrula.surql")
    n_queries = verify_queries.write(verify_path, T.T_NOW)
    files.append(("99_dogrula.surql", os.path.getsize(verify_path)))

    elapsed = time.time() - started
    manifest = build_manifest(ctx, args, files, elapsed, n_queries)
    with open(os.path.join(args.out, "MANIFEST.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(args.out, "_seed_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(build_seed_manifest(ctx, args), fh, ensure_ascii=False, indent=1)

    total = sum(emitter.counts.values())
    print("\nToplam %d satır / %d tablo / %.1f sn" % (total, len(emitter.counts), elapsed))
    print("Çıktı: %s" % args.out)
    return ctx, manifest


# ---------------------------------------------------------------------------
# MANIFEST
# ---------------------------------------------------------------------------

def _pct(part, whole):
    return round(100.0 * part / whole, 2) if whole else None


def build_manifest(ctx, args, files, elapsed, n_queries):
    counts = dict(ctx.emitter.counts)
    total_rows = sum(counts.values())
    a = ctx.answer_stats
    ratio = ctx.scale.ratio

    def scaled(value):
        return round(value * ratio)

    attendance = ctx.attendance_stats
    att_total = sum(attendance.values())
    denom = attendance.get("present", 0) + attendance.get("absent", 0) + \
        attendance.get("late", 0)

    arch = ctx.archetype_stats

    def arch_acc(name):
        s = arch.get(name)
        if not s or not s["answered"]:
            return None
        return _pct(s["correct"], s["answered"])

    marks = ctx.mark_values
    q_p = []
    distractor_wins = 0
    # Madde istatistiği için asgari gözlem sayısı (smoke ölçeğinde düşer)
    min_obs = max(3, round(10 * ratio))
    for key, (asked, answered, correct, distractors) in ctx.question_stats.items():
        if answered >= min_obs:
            q_p.append(correct / answered)
            if distractors and max(distractors.values()) > correct:
                distractor_wins += 1

    expected = {
        "H1_user": scaled(563), "H2_student": scaled(250), "H3_teacher": 24,
        "H4_parent": scaled(285), "H5_parent_link": scaled(299), "H7_course": 50,
        "H8_subject": 390, "H9_class_group": 11, "H10_class_member": scaled(250),
        "H11_class_course": 110, "H12_enrollment": scaled(2790),
        "H13_course_session": 4428, "H14_session_attendance": scaled(98400),
        "H15_exam": 340, "H16_exam_question": 6640,
        "H17_exam_attempt": scaled(14800), "H18_exam_answer": scaled(259000),
        "H19_exam_result": scaled(13600), "H20_bank_question": 885,
        "H21_homework": 590, "H22_homework_submission": scaled(26200),
        "H23_homework_result": scaled(23000), "H24_pomodoro_session": scaled(26000),
        "H25_chatbot_thread": scaled(1500), "H26_chatbot_message": scaled(9000),
        "H27_pool_question": scaled(640), "H28_solution": scaled(780),
        "H29_appointment": 520, "H30_message": scaled(6800),
        "H31_board_stroke": round(9000 * (192 + 88 * ratio) / 280),
        "H32_meal_booking": scaled(11800),
        "H33_payment_ledger": scaled(4400), "H34_tables": 60,
        "H35_total_rows": scaled(572000),
    }
    actual = {
        "H1_user": counts.get("user", 0), "H2_student": len(ctx.students),
        "H3_teacher": len(ctx.teachers), "H4_parent": len(ctx.parents),
        "H5_parent_link": counts.get("parent_link", 0),
        "H7_course": counts.get("course", 0), "H8_subject": counts.get("subject", 0),
        "H9_class_group": counts.get("class_group", 0),
        "H10_class_member": counts.get("class_member", 0),
        "H11_class_course": counts.get("class_course", 0),
        "H12_enrollment": counts.get("enrollment", 0),
        "H13_course_session": counts.get("course_session", 0),
        "H14_session_attendance": counts.get("session_attendance", 0),
        "H15_exam": counts.get("exam", 0),
        "H16_exam_question": counts.get("exam_question", 0),
        "H17_exam_attempt": counts.get("exam_attempt", 0),
        "H18_exam_answer": counts.get("exam_answer", 0),
        "H19_exam_result": counts.get("exam_result", 0),
        "H20_bank_question": counts.get("bank_question", 0),
        "H21_homework": counts.get("homework", 0),
        "H22_homework_submission": counts.get("homework_submission", 0),
        "H23_homework_result": counts.get("homework_result", 0),
        "H24_pomodoro_session": counts.get("pomodoro_session", 0),
        "H25_chatbot_thread": counts.get("chatbot_thread", 0),
        "H26_chatbot_message": counts.get("chatbot_message", 0),
        "H27_pool_question": counts.get("pool_question", 0),
        "H28_solution": counts.get("solution", 0),
        "H29_appointment": counts.get("appointment", 0),
        "H30_message": counts.get("message", 0),
        "H31_board_stroke": counts.get("board_stroke", 0),
        "H32_meal_booking": counts.get("meal_booking", 0),
        "H33_payment_ledger": counts.get("payment_ledger", 0),
        "H34_tables": len(counts), "H35_total_rows": total_rows,
    }

    learning = {
        "L3_genel_dogruluk_pct": {"beklenen": 58.4,
                                  "gercek": _pct(a["choice_correct"], a["choice_answered"])},
        "L4_bos_birakma_pct": {"beklenen": 12.5,
                               "gercek": _pct(a["choice_asked"] - a["choice_answered"],
                                              a["choice_asked"])},
        "L5_text_soru_pay_pct": {
            "beklenen": 15.0,
            "gercek": _pct(sum(1 for q in ctx.questions if q.kind == "text"),
                           len(ctx.questions))},
        "L6_text_bos_pct": {"beklenen": 18.0,
                            "gercek": _pct(a["text_asked"] - a["text_answered"],
                                           a["text_asked"])},
        "L7_mark_ortalama": {"beklenen": 62.8,
                             "gercek": round(statistics.fmean(marks), 2) if marks else None},
        "L8_mark_std": {"beklenen": 17.4,
                        "gercek": round(statistics.pstdev(marks), 2) if len(marks) > 1 else None},
        "L9_mark_90_ustu_pct": {"beklenen": 7.2,
                                "gercek": _pct(sum(1 for m in marks if m >= 90), len(marks))},
        "L10_p_ortalama": {"beklenen": 0.585,
                           "gercek": round(statistics.fmean(q_p), 4) if q_p else None},
        "L11_p_030_alti_madde": {"beklenen": 531,
                                 "gercek": sum(1 for p in q_p if p < 0.30)},
        "L12_p_090_ustu_madde": {"beklenen": 531,
                                 "gercek": sum(1 for p in q_p if p > 0.90)},
        "L13_celdirici_dogrudan_fazla": {"beklenen": 180, "gercek": distractor_wins},
        "L17_ikinci_denemede_duzelen": {"beklenen": scaled(2960),
                                        "gercek": ctx.stats.get("improved_items", 0)},
        "L18_from_bank_pay_pct": {
            "beklenen": 45.0,
            "gercek": _pct(sum(1 for q in ctx.questions if q.from_bank is not None),
                           len(ctx.questions))},
        "L19_from_bank_kopuk": {"beklenen": 48,
                                "gercek": ctx.stats.get("broken_from_bank", 0)},
        "L20_banked_as_pay_pct": {
            "beklenen": 6.0,
            "gercek": _pct(sum(1 for q in ctx.questions if q.banked_as is not None),
                           len(ctx.questions))},
        "L21_metin_iraksamasi": {"beklenen": 359,
                                 "gercek": sum(1 for v in ctx.text_diverged.values() if v)},
        "L22_seq2_attempt": {"beklenen": scaled(564),
                             "gercek": ctx.stats.get("second_attempts", 0)},
        "L23_cevapsiz_attempt": {"beklenen": scaled(9),
                                 "gercek": ctx.stats.get("blank_attempts", 0)},
        "L24_finished_none_attempt": {"beklenen": scaled(31),
                                      "gercek": ctx.stats.get("abandoned_attempts", 0)},
    }

    archetypes = {
        "A1_A1_dogruluk_pct": {"beklenen": 78, "gercek": arch_acc("A1")},
        "A2_A7_dogruluk_pct": {"beklenen": 42, "gercek": arch_acc("A7")},
        "A3_A1_eksi_A7": {"beklenen": 36,
                          "gercek": (round(arch_acc("A1") - arch_acc("A7"), 2)
                                     if arch_acc("A1") and arch_acc("A7") else None)},
        "A4_A3_bosluk_dogruluk_pct": {
            "beklenen": 31,
            "gercek": _pct(arch.get("A3", {}).get("gap_correct", 0),
                           arch.get("A3", {}).get("gap_asked", 0))},
        "A5_A3_diger_dogruluk_pct": {
            "beklenen": 72,
            "gercek": _pct(arch.get("A3", {}).get("other_correct", 0),
                           arch.get("A3", {}).get("other_asked", 0))},
        "A7_bosluk_sinif_ortalamasi_pct": {
            "beklenen": 58,
            "gercek": _pct(ctx.gap_class_stats["correct"], ctx.gap_class_stats["asked"])},
        "A8_A5_T1_T2_pct": {
            "beklenen": "40 -> 70",
            "gercek": [_pct(arch.get("A5", {}).get("t1_correct", 0),
                            arch.get("A5", {}).get("t1_asked", 0)),
                       _pct(arch.get("A5", {}).get("t2_correct", 0),
                            arch.get("A5", {}).get("t2_asked", 0))]},
        "A9_A6_kirilma_oncesi_sonrasi_pct": {
            "beklenen": "64 -> 37",
            "gercek": [_pct(arch.get("A6", {}).get("pre_correct", 0),
                            arch.get("A6", {}).get("pre_asked", 0)),
                       _pct(arch.get("A6", {}).get("post_correct", 0),
                            arch.get("A6", {}).get("post_asked", 0))]},
        "A10_A4_counted_on_time_pct": {
            "beklenen": 48,
            "gercek": _pct(ctx.hw_archetype.get("A4", {}).get("on_time", 0),
                           ctx.hw_archetype.get("A4", {}).get("n", 0))},
        "A11_A1_counted_on_time_pct": {
            "beklenen": 97,
            "gercek": _pct(ctx.hw_archetype.get("A1", {}).get("on_time", 0),
                           ctx.hw_archetype.get("A1", {}).get("n", 0))},
        "A16_A8_randevu": {"beklenen": scaled(76),
                           "gercek": ctx.appointment_by_student.get("A8", 0)},
        "A18_A8_failed_3_in_14": {"beklenen": scaled(11),
                                  "gercek": ctx.stats.get("a8_failed_3_in_14", 0)},
        "A21_A7_pomodorosuz": {"beklenen": scaled(13),
                               "gercek": sum(1 for s in ctx.students
                                             if s.archetype == "A7"
                                             and ctx.pomodoro_true_counted.get(s.key, 0) == 0)},
        "A22_A7_sohbetsiz": {"beklenen": scaled(15),
                             "gercek": sum(1 for s in ctx.students
                                           if s.archetype == "A7"
                                           and not s.counters.get("chatbot_thread_count"))},
    }

    behaviour = {
        "D1_devam_orani_pct": {
            "beklenen": 93.5,
            "gercek": _pct(attendance.get("present", 0) + attendance.get("late", 0), denom)},
        "D2_present_pay_pct": {"beklenen": 84.1,
                               "gercek": _pct(attendance.get("present", 0), att_total)},
        "D3_absent_late_excused_pct": {
            "beklenen": [9.0, 4.6, 2.3],
            "gercek": [_pct(attendance.get("absent", 0), att_total),
                       _pct(attendance.get("late", 0), att_total),
                       _pct(attendance.get("excused", 0), att_total)]},
        "D11_son24saat_teslim_pct": {"beklenen": 44.8,
                                     "gercek": _pct(ctx.hw_stats["last24"],
                                                    ctx.hw_stats["total"])},
        "D12_gec_teslim_pct": {"beklenen": 19.6,
                               "gercek": _pct(ctx.hw_stats["late"], ctx.hw_stats["total"])},
        "D13_counted_on_time_pct": {"beklenen": 74.8,
                                    "gercek": _pct(ctx.hw_stats["on_time"],
                                                   ctx.hw_stats["total"])},
        "D14_on_time_ama_updated_gec": {"beklenen": scaled(750),
                                        "gercek": ctx.hw_stats["on_time_but_updated_late"]},
        "D15_counted_pomodoro_pct": {"beklenen": 81.4,
                                     "gercek": _pct(ctx.stats.get("pomodoro_counted", 0),
                                                    ctx.stats.get("pomodoro_total", 0))},
        "D16_finished_none_pomodoro_pct": {
            "beklenen": 6.0,
            "gercek": _pct(ctx.stats.get("pomodoro_unfinished", 0),
                           ctx.stats.get("pomodoro_total", 0))},
        "D17_gece_pomodoro_pct": {"beklenen": 8.0,
                                  "gercek": _pct(ctx.stats.get("pomodoro_night", 0),
                                                 ctx.stats.get("pomodoro_total", 0))},
        "D18_sohbet_kullanan_ogrenci": {"beklenen": scaled(155),
                                        "gercek": ctx.stats.get("students_using_chat", 0)},
        # SENARYO 5.4'te oranlar ASISTAN mesajlari uzerinden verilmistir
        "D19_failed_pay_pct": {"beklenen": 4.6,
                               "gercek": _pct(ctx.stats.get("chatbot_failed", 0),
                                              ctx.stats.get("chatbot_assistant", 0))},
        "D20_pending_mesaj": {"beklenen": scaled(270),
                              "gercek": ctx.stats.get("chatbot_pending", 0)},
        "D21_eski_pending_randevu": {"beklenen": 45,
                                     "gercek": ctx.stats.get("appointments_old_pending", 0)},
        "D22_cozumsuz_eski_havuz": {"beklenen": scaled(180),
                                    "gercek": ctx.stats.get("pool_unsolved_old", 0)},
        "D23_yoklamasiz_oturum": {"beklenen": 399,
                                  "gercek": ctx.stats.get("sessions_without_attendance", 0)},
        "D24_clear_vurus_pct": {"beklenen": 3.0,
                                "gercek": _pct(ctx.stats.get("board_clear", 0),
                                               ctx.stats.get("board_strokes", 0))},
        "D25_okunmus_mesaj_pct": {"beklenen": 66.0,
                                  "gercek": _pct(ctx.stats.get("messages_read", 0),
                                                 ctx.stats.get("messages", 0))},
    }

    intentional = {
        "K1_pomodoro_sayac_sismesi": sum(
            1 for s in ctx.students
            if s.counters.get("pomodoro_finished_total", 0)
            != ctx.pomodoro_true_counted.get(s.key, 0)),
        "K2_lessons_attended_total_NONE": len(ctx.students),
        "K3_high_mark_total_NONE": len(ctx.students),
        "K4_held_counted_at_NONE": ctx.stats.get("held_counted_none", 0),
        "K5_bank_question_subject_NONE": sum(
            1 for t in ctx.bank_templates if t.subject is None and not t.deleted),
        "K6_from_bank_kopuk": ctx.stats.get("broken_from_bank", 0),
        "K7_grade_tutarsizligi": 1,
        "K8_answer_key_edits": len(ctx.answer_key_edits),
        "K9_negatif_madde": sum(1 for q in ctx.questions
                                if q.item.quality_band == "negatif"),
        "K10_bozuk_madde": sum(1 for q in ctx.questions
                               if q.item.quality_band == "bozuk"),
    }

    deviations = []
    for key, exp in expected.items():
        act = actual.get(key)
        if exp and act is not None and exp > 0:
            diff = 100.0 * (act - exp) / exp
            if abs(diff) > 5.0:
                deviations.append({"olcum": key, "beklenen": exp, "gercek": act,
                                   "sapma_pct": round(diff, 1)})

    return {
        "uretim": {
            "tohum": args.seed,
            "olcek": ctx.scale.name,
            "ogrenci_sayisi": ctx.scale.n_students,
            "date_shift_days": args.date_shift_days,
            "t_now_ms": T.T_NOW,
            "t_now_iso": _iso(T.T_NOW),
            "uretim_zamani_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "sure_sn": round(elapsed, 1),
            "okul_slug": C.SCHOOL_SLUG,
            "dogrulama_sorgusu": n_queries,
            "ogretim_haftasi": ctx.teaching_week_count,
        },
        "dosyalar": [{"ad": name, "bayt": size} for name, size in files],
        "tablo_satir_sayilari": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        "toplam_satir": total_rows,
        "beklenen_vs_gercek": {"hacim": {k: {"beklenen": expected[k], "gercek": actual[k]}
                                         for k in expected},
                               "ogrenme": learning,
                               "arketip": archetypes,
                               "davranis": behaviour,
                               "kasitli_hatalar": intentional},
        "sapmalar": deviations,
        "sapma_gerekceleri": DEVIATION_NOTES,
    }


DEVIATION_NOTES = [
    "H16 (exam_question = 6.640): SENARYO §2.5'teki soru sayilari "
    "(10,25,6,30,12,25,5,30) ders basina 143 soru verir; 40 ders x 143 + 20 etut "
    "sinavi x 12 = 5.960. §2.3'teki 6.640 rakami sinav basina 20 soru varsayar ve "
    "§2.5 ile celisir. Uretici §2.5'teki kesin tabloya uyar.",
    "H18 (exam_answer = 259.000): H16'daki farkin dogrudan sonucudur; gecmis "
    "sinavlarin ortalama soru sayisi 18 oldugu icin cevap sayisi da orantili "
    "bicimde duser (259.000 x 18/20 x 0,93 ~ 217.000).",
    "H19 (exam_result = 13.600): §2.3 oturumlarin %92'sinin notlandigini varsayar "
    "ama kenar durum #12 son 3 haftadaki 26 sinavin HIC notlanmadigini sart kosar. "
    "Iki kural birlikte 11.800 satir verir; #12 korunmustur (Y1 testi icin gerekli).",
    "H14 (session_attendance = 98.400): §2.3'teki hesap 4.158 oturumun TAMAMINDA "
    "yoklama alindigini varsayar; oysa §2.4 ve D23 oturumlarin %9'unda hic yoklama "
    "olmadigini sart kosar. Uretici §2.4'e uyar (D23 = 399 oturum korunur).",
    "H22 / H23 (homework_submission / homework_result): §2.3'teki hesap tum "
    "ogrencilerin her odeve hedef oldugunu varsayar; §2.6'daki 'assigned %22 "
    "orninde kayitlilarin %55'i' kurali paydayi %10 kucultur. Ayrica ayrilan "
    "ogrenciler (#2) ve donem ortasi kaydolanlar (#1) pencere disinda kalir.",
    "H24 (pomodoro_session = 26.000): §2.3'teki '170 ogrenci x 153 stint' hesabi "
    "§3'teki arketip parametreleriyle (gun/hafta x Poisson(lambda)) uyusmuyor; o "
    "parametreler yaklasik 3 kat daha fazla stint uretir. Arketip tablolari "
    "senaryonun cekirdegi oldugu icin (A19, D9, D10, D15-D17, P7 olcumlerini "
    "besliyorlar) onlara sadik kalindi. Toplam satir sayisi yine H35 bandinda.",
    "H12 (enrollment = 2.790): §1.4'teki etut/kulup kayit sayilari "
    "(32+28+30+30 ve 18+22+16+20+24+18) toplam 238 eder, 290 degil. Uretici acik "
    "sayilari kullanir: 2.500 cekirdek + 238 = 2.738.",
    "H13 (course_session = 4.428): 14 blok x 11 sube x 27 hafta = 4.158 hesabi 3 "
    "resmi tatil gununu saymaz; o gunlerde ders yapilmaz.",
    "H33 (payment_ledger = 4.400): 4 planin taksit sayilari (1/9/6/9) ve 250 "
    "ogrenci 1.948 charge uretir, 2.250 degil; vadesi T_NOW'i gecmemis taksitler "
    "icin tahsilat satiri da yazilmaz.",
    "L11 / L12 (p uclari): §4.2'deki bant->p esleme a_i = 1 varsayar. §4.3'teki "
    "a_i dagiliminda maddelerin %38'i a < 0,8 oldugu icin kolay/zor bantlardaki "
    "maddeler uclara tasinmaz. Iki kural ayni anda saglanamaz; a_i dagilimi "
    "(T2'nin test ettigi sey) korunmustur.",
    "L17 (ikinci denemede duzelen ~2.960): §4.9'un beklentisi oturum basina ~5 "
    "madde duzelmesidir; theta + 0,45 bonusu ve 12 soruluk quiz sinavlariyla "
    "gerceklesen oran oturum basina ~1,7'dir.",
    "L22 (seq=2 attempt = 564): §4.9 'gecmis 240 sinavin %18'i' der; §2.5 tablosu "
    "ise max_attempts = 2 olan tek bir sinav penceresi (5 numarali quiz) tanimlar, "
    "yani 40 sinav. Uretici §2.5'e uyar.",
    "D19 / D20 (sohbet): §5.4'teki status paylari ASISTAN mesaji basinadir, "
    "§7'deki D19/D20 ise tum chatbot_message satirlarini sayar. MANIFEST D19'u "
    "asistan mesajlari uzerinden olcer; D20 hedefi (270 satir) icin 'pending' payi "
    "%3'ten %6'ya cikarilmistir.",
    "A3 arketipi (bosluk dersi): §3.6'daki -1,60 / -0,90 sapmalari, madde-ici "
    "gurultu ve bos birakma secilimiyle birlikte §7.3 A6 olcutunu (ogrenci ici "
    "fark >= 30 puan) saglamiyordu; sapmalar -2,40 / -1,40'a derinlestirildi.",
    "Madde kalibrasyonu: b_i bantlarina +0,62 sabit kayma, bos birakma olasiligina "
    "0,33 carpani ve nota dogrusal donusum (0,89 x puan + 22,5) uygulanir. Bu uc "
    "katsayi §7'deki L3 / L4 / L7 / L8 hedeflerini tutturmak icindir ve "
    "config.py'de ITEM_B_OFFSET / OMISSION_SCALE / MARK_SLOPE olarak durur.",
    "smoke olceginde ogrenciye bagli tum beklenen degerler 20/250 oraniyla "
    "olceklenir; yapisal buyuklukler (11 sube, 50 ders, 390 konu, 340 sinav, 900 "
    "banka sablonu, 24 ogretmen, okul takvimi) kucultulmez.",
]


def _iso(ms):
    return _dt.datetime.fromtimestamp(ms / 1000, _dt.timezone.utc).isoformat()


def build_seed_manifest(ctx, args):
    """SENARYO §7.8 — DB'ye yazılmayan 'gizli gerçek'."""
    students = []
    for s in ctx.students:
        students.append({
            "user": "user:" + s.key,
            "archetype": s.archetype,
            "class": s.branch,
            "theta_base": round(s.theta_base, 4),
            "theta_trend": s.arch.get("trend", 0.0),
            "t_break_ms": s.break_ms,
            "gap_course": ("course:" + s.gap_course_key) if s.gap_course_key else None,
            "gap_subjects": ["subject:" + k for k in s.gap_subject_keys],
            "omission_omega": s.omega,
            "dim_delta": s.dim_delta,
            "edge_flags": s.edge,
            "true_counted_pomodoro": ctx.pomodoro_true_counted.get(s.key, 0),
        })
    items = []
    for q in ctx.questions:
        it = q.item
        items.append({
            "question": "exam_question:" + q.key,
            "a": round(it.a, 4), "b": round(it.b, 4), "c": round(it.c, 4),
            "k": it.k,
            "misconception_choice": q.misc_choice,
            "dims": it.dims,
            "trap_choice": (q.misc_choice
                            if (it.dims or {}).get("dikkat_tuzagi") == "var"
                            else None),
            "w_m": it.w_m,
            "difficulty_band": it.difficulty_band,
            "quality_band": it.quality_band,
            "from_bank_true": ("bank_question:" + q.from_bank.key) if q.from_bank else None,
            "text_diverged": bool(ctx.text_diverged.get(q.key, False)),
        })
    return {
        "seed": args.seed,
        "t_now_ms": T.T_NOW,
        "date_shift_days": args.date_shift_days,
        "school_slug": C.SCHOOL_SLUG,
        "scale": ctx.scale.name,
        "calendar": {
            "t1": [C.T1_START.isoformat(), C.T1_END.isoformat()],
            "t2": [C.T2_START.isoformat(), C.T2_END.isoformat()],
            "breaks": [[a.isoformat(), b.isoformat()] for a, b in C.BREAKS],
            "holidays": [d.isoformat() for d in C.HOLIDAYS],
            "flu_week": [C.FLU_WEEK[0].isoformat(), C.FLU_WEEK[1].isoformat()],
            "teaching_weeks_elapsed": ctx.teaching_week_count,
            "school_days_elapsed": len(T.past_school_days()),
        },
        "students": students,
        "items": items,
        "pool_questions": ctx.pool_true_subject,
        "answer_key_edits": ctx.answer_key_edits,
        "deleted_bank_templates": ["bank_question:" + k
                                   for k in ctx.deleted_bank_templates],
        "broken_from_bank_questions": ["exam_question:" + k for k in ctx.broken_origin],
        "ungraded_exams": ["exam:" + k for k in ctx.ungraded_exams],
    }


def main(argv=None):
    args = parse_args(argv)
    generate(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
