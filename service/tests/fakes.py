"""Testler için sahte kaynak ve fikstür üreticileri.

`FakeSource` imzaları `Source` protokolüyle **birebir aynıdır**; böylece
köprü ajanının yazdığı `FileSource` geldiğinde testler değişmeden çalışır.
"""

from __future__ import annotations

from typing import Any

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def make_ulid(ms: int, suffix: str = "0" * 16) -> str:
    """Zaman bölümü `ms` olan geçerli bir 26 karakterlik ULID üretir."""
    out = ""
    value = ms
    for _ in range(10):
        out = _CROCKFORD[value % 32] + out
        value //= 32
    return out + suffix


def person(uid: str) -> dict[str, Any]:
    return {"id": uid, "username": uid, "display_name": uid}


def course(cid: str, title: str = "Ders", teachers: list[str] | None = None) -> dict:
    """Backend `CourseResponse` şekli (`web/dto.rs:211`)."""
    teacher_ids = teachers or ["teacher-1"]
    return {
        "id": cid,
        "creator": person(teacher_ids[0]),
        "teachers": [person(t) for t in teacher_ids],
        "title": title,
        "description": "",
        "kind": "course",
        "term": None,
        "capacity": None,
    }


def mark_entry(exam_ms: int, mark: int, weight: int = 1) -> dict[str, Any]:
    """Backend `MarkEntry` şekli (`web/marks.rs:32`) — zaman damgası YOK."""
    return {
        "exam": make_ulid(exam_ms),
        "title": "Sınav",
        "kind": "written",
        "weight": weight,
        "mark": mark,
        "grade": None,
        "graded_by": "teacher-1",
    }


def course_marks(
    cid: str, marks: list[int], base_ms: int, step_ms: int = 86_400_000, **kw: Any
) -> dict[str, Any]:
    """Backend `CourseMarks` şekli."""
    results = [mark_entry(base_ms + i * step_ms, m) for i, m in enumerate(marks)]
    return {
        "course": course(cid, **kw),
        "results": results,
        "average": None,
        "average_grade": None,
    }


def course_attendance(
    cid: str,
    *,
    present: int = 0,
    absent: int = 0,
    late: int = 0,
    excused: int = 0,
    custom: dict[str, int] | None = None,
    **kw: Any,
) -> dict[str, Any]:
    """Backend `CourseAttendance` şekli (`web/attendance.rs`)."""
    counts = {
        "present": present,
        "absent": absent,
        "late": late,
        "excused": excused,
        "custom": custom or {},
        "total": present + absent + late + excused,
        "rate": None,
    }
    return {"course": course(cid, **kw), "counts": counts}


def report_entry(
    homework_id: str,
    course_id: str,
    due_at: int,
    *,
    submitted: bool = False,
    late: bool = False,
    missing: bool = False,
    status: str | None = None,
) -> dict[str, Any]:
    """Backend `HomeworkReportEntry` şekli — `submitted_at` YOK."""
    result = None
    if status is not None:
        result = {
            "status": status,
            "mark": None,
            "graded_by": "teacher-1",
            "created_at": due_at,
        }
    return {
        "course": course_id,
        "homework": homework_id,
        "title": "Ödev",
        "subject": "subject-1",
        "due_at": due_at,
        "submitted": submitted,
        "late": late,
        "missing": missing,
        "result": result,
    }


def homework(hid: str, course_id: str, due_at: int, assigned: list[str] | None = None):
    """Backend `HomeworkResponse` şekli (`web/dto.rs:295`)."""
    return {
        "id": hid,
        "course": course_id,
        "subject": "subject-1",
        "title": "Ödev",
        "description": None,
        "due_at": due_at,
        "assigned": assigned,
        "created_by": "teacher-1",
        "created_at": due_at - 7 * 86_400_000,
    }


def pomodoro(started_at: int, minutes: int = 25, counted: bool = True) -> dict:
    """Backend `PomodoroResponse` şekli (`web/pomodoro.rs`)."""
    duration = minutes * 60_000
    return {
        "id": make_ulid(started_at),
        "user": "student-1",
        "started_at": started_at,
        "finished_at": started_at + duration,
        "duration_ms": duration,
        "counted": counted,
    }


def profile(uid: str, class_ids: list[str], course_ids: list[str]) -> dict[str, Any]:
    """Backend `ProfileResponse` şekli (`web/users.rs:1065`)."""
    return {
        "id": uid,
        "username": uid,
        "display_name": uid,
        "role": "student",
        "bio": None,
        "avatar": None,
        "classes": [{"id": c, "name": c, "grade": "9"} for c in class_ids],
        "courses": [{"id": c, "title": c, "kind": "course"} for c in course_ids],
        "badges": [],
        # Bu blok bilerek doldurulur ama hiçbir hesap modülü OKUMAZ
        # (`[T§1.3]` kural 3 — sayaçlar güvenilmez).
        "stats": {
            "pomodoro_finished_total": 9999,
            "lessons_attended_total": None,
            "high_mark_total": None,
        },
    }


class FakeSource:
    """`Source` protokolünün test uygulaması — imzalar birebir.

    **Yemek, ödeme, diyet, mesaj ve sohbet metodu yoktur ve eklenemez.**
    """

    def __init__(self, data: dict[str, dict[str, Any]], *, fail: set[str] | None = None):
        self._data = data
        self._fail = fail or set()
        self.calls: list[str] = []

    def _get(self, user_id: str, key: str, default: Any) -> Any:
        if user_id in self._fail:
            raise RuntimeError(f"sahte kaynak hatası: {user_id}")
        return self._data.get(user_id, {}).get(key, default)

    async def profile(self, school: str, user_id: str) -> dict | None:
        self.calls.append("profile")
        return self._get(user_id, "profile", None)

    async def marks(self, school: str, user_id: str) -> list[dict]:
        self.calls.append("marks")
        return self._get(user_id, "marks", [])

    async def attendance(self, school: str, user_id: str) -> list[dict]:
        self.calls.append("attendance")
        return self._get(user_id, "attendance", [])

    async def pomodoro(self, school: str, user_id: str) -> list[dict]:
        self.calls.append("pomodoro")
        return self._get(user_id, "pomodoro", [])

    async def homework_report(self, school: str, user_id: str) -> dict | None:
        self.calls.append("homework_report")
        items = self._get(user_id, "homework_report", [])
        return {"items": items, "total": len(items), "limit": None, "offset": 0}

    async def homework_list(
        self, school: str, on_behalf_of: str | None = None
    ) -> list[dict]:
        self.calls.append("homework_list")
        if on_behalf_of is None:
            return self._data.get("_school", {}).get("homework_list", [])
        return self._get(on_behalf_of, "homework_list", [])

    async def notes(self, school: str, on_behalf_of: str) -> list[dict]:
        self.calls.append("notes")
        return []

    async def course_notes(
        self, school: str, course_id: str | None = None
    ) -> list[dict]:
        self.calls.append("course_notes")
        return []
