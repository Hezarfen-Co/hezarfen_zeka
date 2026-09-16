"""Üretim bağlamı (ctx): ölçek profili, paylaşılan durum ve sayaç toplayıcıları."""

from __future__ import annotations

import config as C


class Scale:
    """Ölçek profili — senaryodaki tüm oranlar korunur, yalnız hacim küçülür."""

    def __init__(self, name: str, n_students: int):
        self.name = name
        self.n_students = n_students
        self.ratio = n_students / C.N_STUDENTS_FULL


SCALES = {
    "full": Scale("full", C.N_STUDENTS_FULL),
    "smoke": Scale("smoke", 20),
}


class Ctx:
    def __init__(self, seed: int, scale: Scale, shift_days: int, emitter):
        self.seed = seed
        self.scale = scale
        self.shift_days = shift_days
        self.emitter = emitter

        self.users = []
        self.students = []
        self.teachers = []
        self.managers = []
        self.parents = []
        self.parent_links = []
        self.admin = None

        self.courses = []
        self.core_courses = []
        self.extra_courses = []
        self.classes = []
        self.subjects = []
        self.enrolled_courses = {}

        self.exams = []
        self.questions = []
        self.items = {}
        self.item_of_question = {}
        self.bank_templates = []
        self.homeworks = []

        # istatistik ve manifest toplayıcıları
        self.stats = {}
        self.answer_stats = {"choice_asked": 0, "choice_answered": 0, "choice_correct": 0,
                             "text_asked": 0, "text_answered": 0}
        self.question_stats = {}
        self.archetype_stats = {}
        self.attendance_stats = {}
        self.student_attend = {}
        self.hw_stats = {"total": 0, "on_time": 0, "late": 0, "last24": 0,
                         "on_time_but_updated_late": 0}
        self.hw_archetype = {}
        self.mark_values = []
        self.kind_ref_counts = {}
        self.slot_ref_counts = {}
        self.pool_true_subject = []
        self.text_diverged = {}
        self.broken_origin = []
        self.answer_key_edits = []
        self.deleted_bank_templates = []
        self.open_pomodoro = {}
        self.pomodoro_true_counted = {}
        self.appointment_by_student = {}
        self.gap_class_stats = {"asked": 0, "correct": 0}
        self.all_gap_subjects = set()
        self.archetype_counts = {}
        self.ungraded_exams = []
        self.expected_question_count = 0
        self.teaching_week_count = 0

    def bump(self, user, counter: str, amount: int = 1) -> None:
        user.counters[counter] = user.counters.get(counter, 0) + amount
