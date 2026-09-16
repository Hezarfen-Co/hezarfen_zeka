"""Demet kurulumu: `Reader` → `StudentFacingBundle` / `StaffBundle`.

Kapı burada **okuma anında** uygulanır:

* Öğrenci raporu için `student_summary` sorgusunun sütun listesinde
  `attention` yoktur (`gate.SUMMARY_COLUMNS_STUDENT`) — satır veritabanından
  dikkat listesi taşımadan çıkar.
* Öğrenci raporu için `recommendation` sorgusu `audience_role = 'student'` ve
  `audience = <öğrenci>` ile daraltılır; öğretmen satırı hiç getirilmez.
* Öğretmen/yönetim raporu `StaffBundle` alır ve dikkat listesini taşır.
"""

from __future__ import annotations

from typing import Any

from .gate import (
    StaffBundle,
    StudentFacingBundle,
    staff_summary,
    student_facing_summary,
    summary_columns,
)
from .reader import Reader


async def load_student_bundle(
    reader: Reader, school: str, student: str, *, now_ms: int
) -> StudentFacingBundle:
    """Öğrenci/veli raporunun demeti. Dikkat listesi **okunmaz**."""
    rows = await reader.summaries(
        school, columns=summary_columns("ogrenci"), student=student
    )
    summary = student_facing_summary(rows[0]) if rows else None
    recommendations = await reader.recommendations(
        school, audience=student, audience_role="student"
    )
    profiles = await reader.segment_profiles(school, student=student)
    return StudentFacingBundle(
        school=school,
        student=student,
        generated_at=now_ms,
        summary=summary,
        recommendations=recommendations,
        segment_profiles=profiles,
    )


async def load_staff_bundle(
    reader: Reader,
    school: str,
    kind: str,
    *,
    now_ms: int,
    teacher: str | None = None,
) -> StaffBundle:
    """Yönetim / öğretmen / teknik rapor demeti."""
    rows = await reader.summaries(school, columns=summary_columns(kind))
    summaries = [staff_summary(row) for row in rows]
    summaries.sort(key=lambda s: s.student)
    recommendations = await reader.recommendations(school)
    profiles = await reader.segment_profiles(school)
    runs = await reader.runs(school)
    question_segments: list[dict[str, Any]] = []
    if kind == "ham":
        question_segments = await reader.question_segments(school)
    return StaffBundle(
        school=school,
        kind=kind,
        generated_at=now_ms,
        summaries=summaries,
        recommendations=recommendations,
        segment_profiles=profiles,
        runs=runs,
        question_segments=question_segments,
        teacher=teacher,
    )


async def load_bundle(
    reader: Reader,
    school: str,
    kind: str,
    *,
    now_ms: int,
    student: str | None = None,
    teacher: str | None = None,
) -> Any:
    """Rapor tipine göre doğru demeti kurar."""
    if kind == "ogrenci":
        if not student:
            raise ValueError("öğrenci raporu için --about (öğrenci kimliği) zorunlu")
        return await load_student_bundle(reader, school, student, now_ms=now_ms)
    if kind == "ogretmen" and not teacher:
        raise ValueError("öğretmen raporu için --teacher zorunlu")
    return await load_staff_bundle(
        reader, school, kind, now_ms=now_ms, teacher=teacher
    )
