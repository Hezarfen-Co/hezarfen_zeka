"""Testler için sahte kaynak, sahte köprü ve fikstür üreticileri.

`FakeSource` imzaları `Source` protokolüyle **birebir aynıdır**; böylece
köprü ajanının yazdığı `FileSource` geldiğinde testler değişmeden çalışır.
`ReplyingCaller` ise `src.store.BridgeCaller` protokolünü uygular: depo
çağrıları gerçek hat üzerinden koşar, yalnız taşıma sahtedir.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.compute import clock
from src.store import CAP_SCHOOLS, RecordingCaller

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


# ---------------------------------------------------------------------------
# Fikstür üretimi -- `FileSource`'un okuduğu dizin düzeni
# ---------------------------------------------------------------------------
#
# Bu üreticiler eskiden `tests/zeka_db.py` içindeydi; o dosya gerçek
# SurrealDB'ye bağlanan entegrasyon testleriyle birlikte silindi. Disk
# fikstürü YAZMAK veritabanı gerektirmez, o yüzden burada yaşıyor.

NOW = 1_699_963_200_000  # 2023-11-14 12:00 UTC
DAY = 86_400_000
HOUR = 3_600_000
TERM_START = NOW - 150 * DAY


def student_payload(
    uid: str,
    class_id: str,
    marks_list: list[int],
    present: int,
    absent: int,
    *,
    now_ms: int = NOW,
) -> dict[str, Any]:
    """Tek öğrencinin bütün kaynak verisi (`FakeSource` ile aynı şekil)."""
    base = now_ms - 100 * DAY
    return {
        "profile": profile(uid, [class_id], ["course-1"]),
        "marks": [course_marks("course-1", marks_list, base, teachers=["teacher-1"])],
        "attendance": [course_attendance("course-1", present=present, absent=absent)],
        "pomodoro": [
            pomodoro(
                (clock.tr_day(now_ms) - d) * DAY + 10 * HOUR - clock.TR_OFFSET_MS
            )
            for d in range(1, 7)
        ],
        "homework_report": [
            report_entry(
                f"hw-{uid}-{i}", "course-1", now_ms - (i + 1) * DAY, submitted=True
            )
            for i in range(6)
        ],
        "homework_list": [homework("upcoming", "course-1", now_ms + 6 * HOUR, [uid])],
    }


def dataset(count: int = 12, *, now_ms: int = NOW) -> dict[str, dict]:
    """Bir şube, bir ders, `count` öğrenci; ilki belirgin biçimde düşük."""
    data: dict[str, dict] = {}
    for i in range(count):
        uid = f"student-{i:02d}"
        if i == 0:
            data[uid] = student_payload(
                uid, "class-A", [40, 41, 39, 42, 40, 38], 60, 40, now_ms=now_ms
            )
        else:
            data[uid] = student_payload(
                uid, "class-A", [70, 72, 71, 69, 70, 71], 95, 5, now_ms=now_ms
            )
    data["_school"] = {
        "homework_list": [
            homework("hw-school", "course-1", now_ms + DAY, list(data.keys()))
        ]
    }
    return data


def write_fixtures(root: Path, school: str, data: dict[str, dict]) -> list[str]:
    """`data` sözlüğünü `FileSource`'un beklediği dizin düzenine yazar.

    Dönen değer: okul genelinde işlenecek öğrenci kimlikleri.
    """
    base = root / school
    #: yöntem -> (alt dizin, zarf anahtarı veya None)
    layout = {
        "profile": ("profile", None),
        "marks": ("marks", "courses"),
        "attendance": ("attendance", "courses"),
        "pomodoro": ("pomodoro", "items"),
        "homework_report": ("homework_report", "items"),
        "homework_list": ("homework", "items"),
    }
    for directory, _ in layout.values():
        (base / directory).mkdir(parents=True, exist_ok=True)

    students: list[str] = []
    for key, payload in data.items():
        name = "_service" if key == "_school" else key
        if key != "_school":
            students.append(key)
        for method, (directory, envelope) in layout.items():
            if method not in payload:
                continue
            body = payload[method]
            if envelope is None:
                out: Any = body
            elif method == "homework_report":
                out = {"items": body, "total": len(body), "limit": None, "offset": 0}
            else:
                out = {envelope: body}
            (base / directory / f"{name}.json").write_text(
                json.dumps(out, ensure_ascii=False), encoding="utf-8"
            )
    return students


# ---------------------------------------------------------------------------
# Sahte köprü -- depo çağrılarını toplayan ve cevap veren istemci
# ---------------------------------------------------------------------------


class ReplyingCaller(RecordingCaller):
    """`RecordingCaller` + yetenek başına hazır cevap.

    `RecordingCaller` okuma çağrılarına boş listeler döner; okul listesi,
    devreden öğrenciler gibi gerçek içerik gereken yerlerde bu sınıf
    kullanılır. Kayıt ve hata davranışı aynen devralınır.
    """

    def __init__(self, replies: dict[str, dict[str, Any]], **kw: Any) -> None:
        super().__init__(**kw)
        self.replies = dict(replies)

    async def call(
        self, capability: str, school: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if (
            capability in self.replies
            and self.fail_times <= 0
            and capability not in self.fail_capabilities
        ):
            self.calls.append((capability, school, payload))
            return dict(self.replies[capability])
        return await super().call(capability, school, payload)


def schools_caller(schools: list[str], **kw: Any) -> ReplyingCaller:
    """Okul listesini `insight.schools.list`'ten veren sahte köprü."""
    return ReplyingCaller({CAP_SCHOOLS: {"schools": list(schools)}}, **kw)

