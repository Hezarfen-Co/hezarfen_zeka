#!/usr/bin/env python3
"""Tohum `.surql` dosyalarından `Source` biçiminde öğrenci fikstürü üretir.

Neden bu betik var: hesap modülleri (`service/src/compute/`) bugüne kadar yalnız
sentetik birim testleriyle sınandı. `seed/_seed_manifest.json` 250 öğrencinin
**altın etiketini** (arketip, `theta_base`, `theta_trend`, `gap_subjects`,
`true_counted_pomodoro`, …) taşıyor. Modüllerin bu etiketleri bulup bulamadığını
ölçmek için, gerçek tohum verisinin **backend yanıt biçiminde** fikstüre
dönüştürülmesi gerekiyor.

Veri kaynağı olarak SurrealDB konteyneri yerine **doğrudan `.surql` dosyaları**
seçildi (görevdeki (b) yolu): konteynerdeki namespace boştu, 170 MB tohumu
yüklemek dakikalar sürüyor ve bu betiğin CI'da da yeniden koşabilmesi isteniyor.
`.surql` satırları satır başına bir kayıt biçiminde yazılmış; aşağıdaki küçük
ayrıştırıcı SurrealQL nesne sözdizimini (tırnaksız anahtar, `tablo:⟨id⟩` kayıt
bağı, `NONE`/`NULL`, tek tırnaklı dize) okur.

Üretilen biçimler `service/src/source.py` docstring'lerinde yazılı olanlardır:

* `profile`    → `ProfileResponse` düz nesnesi
* `marks`      → `MarksReport.courses[]` listesi
* `attendance` → `AttendanceReport.courses[]` listesi
* `pomodoro`   → `PomodoroLog.items[]` listesi
* `homework_report` → `Page<HomeworkReportEntry>` zarfı

Çıktı:
    service/fixtures/gold_students/<school>/<kind>/<user_key>.json
    service/fixtures/gold_students/gold.json     (altın etiketler + meta)

Kullanım:
    python tools/build_student_fixtures.py
    python tools/build_student_fixtures.py --limit 25   (hızlı deneme)
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any, Iterator

ROOT = pathlib.Path(__file__).resolve().parents[1]
SEED_DIR = ROOT / "seed"
OUT_DIR = ROOT / "service" / "fixtures" / "gold_students"
SCHOOL = "ataturk-anadolu"

# Hangi tablo hangi dosyada. Dosya başına tek geçiş yapılır.
TABLE_FILES: dict[str, tuple[str, ...]] = {
    "01_temel.surql": ("settings", "term"),
    "02_kullanicilar.surql": ("user",),
    "03_profil_ve_yapi.surql": ("class_group", "course"),
    "05_kisisel_kayitlar.surql": ("pomodoro_session",),
    "06_iliskiler.surql": ("class_member", "enrollment"),
    "07_akademik.surql": ("exam", "subject"),
    "08_degerlendirme.surql": ("exam_result", "session_attendance", "homework"),
    "09_sorular.surql": ("homework_result",),
    "12_teslimler.surql": ("homework_submission",),
}


# --- SurrealQL nesne ayrıştırıcı ------------------------------------------
#
# Tam bir SurrealQL ayrıştırıcısı değildir; tohum üreticisinin yazdığı alt
# kümeyi okur. Bilinmeyen bir jeton görürse sessizce geçmez, hata fırlatır.


class _Parser:
    __slots__ = ("s", "i", "n")

    def __init__(self, s: str) -> None:
        self.s = s
        self.i = 0
        self.n = len(s)

    def _ws(self) -> None:
        while self.i < self.n and self.s[self.i] in " \t\r\n":
            self.i += 1

    def parse_object(self) -> dict[str, Any]:
        self._ws()
        assert self.s[self.i] == "{", self.s[self.i : self.i + 40]
        self.i += 1
        out: dict[str, Any] = {}
        while True:
            self._ws()
            if self.s[self.i] == "}":
                self.i += 1
                return out
            key = self._key()
            self._ws()
            assert self.s[self.i] == ":", self.s[self.i : self.i + 40]
            self.i += 1
            out[key] = self.parse_value()
            self._ws()
            if self.s[self.i] == ",":
                self.i += 1

    def _key(self) -> str:
        self._ws()
        if self.s[self.i] in "'\"":
            return self._string()
        start = self.i
        while self.s[self.i] not in " \t\r\n:":
            self.i += 1
        return self.s[start : self.i]

    def _string(self) -> str:
        quote = self.s[self.i]
        self.i += 1
        buf: list[str] = []
        while True:
            c = self.s[self.i]
            if c == "\\":
                nxt = self.s[self.i + 1]
                buf.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
                self.i += 2
                continue
            if c == quote:
                self.i += 1
                return "".join(buf)
            buf.append(c)
            self.i += 1

    def parse_value(self) -> Any:
        self._ws()
        c = self.s[self.i]
        if c == "{":
            return self.parse_object()
        if c == "[":
            self.i += 1
            arr: list[Any] = []
            while True:
                self._ws()
                if self.s[self.i] == "]":
                    self.i += 1
                    return arr
                arr.append(self.parse_value())
                self._ws()
                if self.s[self.i] == ",":
                    self.i += 1
        if c in "'\"":
            return self._string()
        # Çıplak jeton: sayı, true/false, NONE/NULL ya da `tablo:⟨id⟩` kayıt bağı.
        start = self.i
        while self.i < self.n:
            ch = self.s[self.i]
            if ch == "⟨":  # kayıt kimliği süslü köşeli parantez içinde
                while self.s[self.i] != "⟩":
                    self.i += 1
                self.i += 1
                continue
            if ch in ",}] \t\r\n":
                break
            self.i += 1
        tok = self.s[start : self.i].strip()
        return _atom(tok)


def _atom(tok: str) -> Any:
    if tok in ("NONE", "NULL", "None", "null"):
        return None
    if tok == "true":
        return True
    if tok == "false":
        return False
    try:
        if "." in tok or "e" in tok or "E" in tok:
            return float(tok)
        return int(tok)
    except ValueError:
        pass
    # Kayıt bağı: `tablo:⟨ULID⟩` → `tablo:ULID` (köşeli parantezler atılır).
    return tok.replace("⟨", "").replace("⟩", "")


def parse_rows(path: pathlib.Path, tables: tuple[str, ...]) -> Iterator[tuple[str, dict]]:
    """Dosyadaki `INSERT INTO <tablo> [...]` bloklarından satır sözlükleri üretir."""
    wanted = set(tables)
    current: str | None = None
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("INSERT INTO "):
                name = line[12:].split(" ", 1)[0].strip()
                current = name if name in wanted else None
                continue
            if current is None:
                continue
            stripped = line.lstrip()
            if not stripped.startswith("{"):
                if stripped.startswith("]"):
                    current = None
                continue
            yield current, _Parser(stripped).parse_object()


# --- Toplama ---------------------------------------------------------------


def key_of(record_id: str | None) -> str:
    """`tablo:ULID` → `ULID`. Dosya adı olarak da kullanılır."""
    if not record_id:
        return ""
    return str(record_id).split(":", 1)[-1]


def load_all(verbose: bool = True) -> dict[str, Any]:
    """Gerekli tabloları tek geçişte toplar."""
    data: dict[str, Any] = {
        "settings": None,
        "user": {},
        "class_group": {},
        "course": {},
        "class_member": [],
        "enrollment": [],
        "exam": {},
        "subject": {},
        "exam_result": [],
        # (user, course) -> statü sayacı
        "attendance_counts": {},
        "homework": {},
        "homework_result": {},
        "homework_submission": {},
        "pomodoro": {},
    }
    for fname, tables in TABLE_FILES.items():
        path = SEED_DIR / fname
        if verbose:
            print(f"  okunuyor: {fname} ({', '.join(tables)})", file=sys.stderr)
        for table, row in parse_rows(path, tables):
            if table == "settings":
                data["settings"] = row
            elif table == "user":
                data["user"][row["id"]] = row
            elif table in ("class_group", "course", "exam", "subject"):
                data[table][row["id"]] = row
            elif table in ("class_member", "enrollment"):
                data[table].append(row)
            elif table == "exam_result":
                data["exam_result"].append(row)
            elif table == "session_attendance":
                bucket = data["attendance_counts"].setdefault(
                    (row["user"], row["course"]), {}
                )
                st = row.get("status") or "unknown"
                bucket[st] = bucket.get(st, 0) + 1
            elif table == "homework":
                data["homework"][row["id"]] = row
            elif table == "homework_result":
                data["homework_result"][(row["user"], row["homework"])] = row
            elif table == "homework_submission":
                data["homework_submission"][(row["user"], row["homework"])] = row
            elif table == "pomodoro_session":
                data["pomodoro"].setdefault(row["user"], []).append(row)
    return data


def person_ref(users: dict, uid: str | None) -> dict | None:
    if not uid:
        return None
    u = users.get(uid)
    if u is None:
        return {"id": uid, "username": key_of(uid), "display_name": None}
    return {
        "id": uid,
        "username": u.get("username"),
        "display_name": u.get("display_name") or f"{u.get('name')} {u.get('surname')}",
    }


def course_response(users: dict, course: dict) -> dict:
    """`CourseResponse` (`web/dto.rs:211`) — `marks`/`attendance` içine gömülür."""
    return {
        "id": course["id"],
        "creator": person_ref(users, course.get("creator")),
        "teachers": [
            person_ref(users, t) for t in (course.get("teachers") or []) if t
        ],
        "title": course.get("title"),
        "description": course.get("description"),
        "kind": course.get("kind"),
        "term": course.get("term"),
        "capacity": course.get("capacity"),
    }


def build(limit: int | None = None, verbose: bool = True) -> dict[str, Any]:
    manifest = json.loads((SEED_DIR / "_seed_manifest.json").read_text(encoding="utf-8"))
    students = manifest["students"]
    if limit:
        students = students[:limit]
    gold_ids = {s["user"] for s in students}

    data = load_all(verbose=verbose)
    users = data["user"]
    courses = data["course"]
    exams = data["exam"]

    # Sınav türü → ağırlık (`settings.exam_kinds`). Backend `MarkEntry.weight`'i
    # istek anında buradan çözüyor (`marks.course_average` docstring'i).
    weights = {
        k["name"]: int(k.get("weight") or 1)
        for k in (data["settings"] or {}).get("exam_kinds", [])
    }

    # Öğrenci → şubeler
    classes_of: dict[str, list[str]] = {}
    for cm in data["class_member"]:
        classes_of.setdefault(cm["user"], []).append(cm["class"])

    # Öğrenci → dersler (enrollment, backend'in tek doğru kaynağı)
    courses_of: dict[str, set[str]] = {}
    for en in data["enrollment"]:
        courses_of.setdefault(en["user"], set()).add(en["course"])

    # Öğrenci → ders → not satırları
    marks_of: dict[str, dict[str, list[dict]]] = {}
    for r in data["exam_result"]:
        uid = r["user"]
        if uid not in gold_ids:
            continue
        ex = exams.get(r["exam"])
        if ex is None:
            continue
        kind = ex.get("kind")
        marks_of.setdefault(uid, {}).setdefault(ex["course"], []).append(
            {
                "exam": r["exam"],
                "title": ex.get("title"),
                "kind": kind,
                "weight": weights.get(kind, 1),
                "mark": r.get("mark"),
                "grade": None,
                "graded_by": r.get("graded_by"),
            }
        )

    # Ders → o dersin ödevleri
    hw_by_course: dict[str, list[dict]] = {}
    for hw in data["homework"].values():
        hw_by_course.setdefault(hw["course"], []).append(hw)

    t_now = int(manifest["t_now_ms"])
    out_root = OUT_DIR / SCHOOL
    for kind in ("profile", "marks", "attendance", "pomodoro", "homework_report"):
        (out_root / kind).mkdir(parents=True, exist_ok=True)

    written = 0
    for s in students:
        uid = s["user"]
        ukey = key_of(uid)
        u = users.get(uid, {})
        my_classes = classes_of.get(uid, [])
        my_courses = sorted(courses_of.get(uid, set()))

        # --- profile ---
        profile = {
            "id": uid,
            "username": u.get("username"),
            "display_name": u.get("display_name")
            or f"{u.get('name', '')} {u.get('surname', '')}".strip(),
            "role": "student",
            "bio": u.get("bio"),
            "avatar": None,
            "classes": [
                {
                    "id": cid,
                    "name": data["class_group"].get(cid, {}).get("name"),
                    "grade": data["class_group"].get(cid, {}).get("grade"),
                }
                for cid in my_classes
            ],
            "courses": [
                {
                    "id": cid,
                    "title": courses.get(cid, {}).get("title"),
                    "kind": courses.get(cid, {}).get("kind"),
                }
                for cid in my_courses
            ],
            "badges": [],
            "stats": {
                # Kasıtlı şişkin sayaç (`[M]` K1) olduğu gibi taşınır; hesap
                # modülleri zaten okumuyor, ama fikstür gerçeği saklamaz.
                "pomodoro_finished_total": u.get("pomodoro_finished_total"),
                "lessons_attended_total": u.get("lessons_attended_total"),
                "high_mark_total": u.get("high_mark_total"),
                "study_streak_current": u.get("study_streak_current"),
            },
        }

        # --- marks: MarksReport.courses[] ---
        marks_rows = []
        for cid, results in sorted(marks_of.get(uid, {}).items()):
            course = courses.get(cid)
            if course is None:
                continue
            total_w = sum(r["weight"] for r in results if r.get("mark") is not None)
            total = sum(
                float(r["mark"]) * r["weight"]
                for r in results
                if r.get("mark") is not None
            )
            marks_rows.append(
                {
                    "course": course_response(users, course),
                    "results": results,
                    "average": (total / total_w) if total_w else None,
                    "average_grade": None,
                }
            )

        # --- attendance: AttendanceReport.courses[] ---
        att_rows = []
        for cid in my_courses:
            counts = data["attendance_counts"].get((uid, cid))
            if not counts:
                continue
            course = courses.get(cid)
            if course is None:
                continue
            present = counts.get("present", 0)
            absent = counts.get("absent", 0)
            late = counts.get("late", 0)
            excused = counts.get("excused", 0)
            custom = {
                k: v
                for k, v in counts.items()
                if k not in ("present", "absent", "late", "excused")
            }
            denom = present + absent + late
            att_rows.append(
                {
                    "course": course_response(users, course),
                    "counts": {
                        "present": present,
                        "absent": absent,
                        "late": late,
                        "excused": excused,
                        "custom": custom,
                        "total": present + absent + late + excused + sum(custom.values()),
                        "rate": ((present + late) / denom) if denom else None,
                    },
                }
            )

        # --- pomodoro: PomodoroLog.items[] ---
        pomo = []
        for p in sorted(
            data["pomodoro"].get(uid, []), key=lambda r: r.get("started_at") or 0
        ):
            started = p.get("started_at")
            finished = p.get("finished_at")
            pomo.append(
                {
                    "id": p["id"],
                    "user": uid,
                    "started_at": started,
                    "finished_at": finished,
                    "duration_ms": (int(finished) - int(started))
                    if (started is not None and finished is not None)
                    else None,
                    "counted": p.get("counted"),
                }
            )

        # --- homework_report: Page<HomeworkReportEntry> ---
        hw_items = []
        for cid in my_courses:
            for hw in hw_by_course.get(cid, []):
                due_at = hw.get("due_at")
                sub = data["homework_submission"].get((uid, hw["id"]))
                res = data["homework_result"].get((uid, hw["id"]))
                submitted = sub is not None
                # `HomeworkReportEntry.late` = "en son dokunuş due_at sonrası mı"
                # (`homework.rs:1178`). Dondurulmuş `counted_on_time` DEĞİLDİR.
                late = bool(
                    sub
                    and due_at is not None
                    and (sub.get("updated_at") or sub.get("submitted_at") or 0) > due_at
                )
                missing = bool(
                    not submitted and due_at is not None and int(due_at) < t_now
                )
                hw_items.append(
                    {
                        "course": cid,
                        "homework": hw["id"],
                        "title": hw.get("title"),
                        "subject": hw.get("subject"),
                        "due_at": due_at,
                        "submitted": submitted,
                        "late": late,
                        "missing": missing,
                        "result": (
                            {
                                "status": res.get("status"),
                                "mark": res.get("mark"),
                                "graded_by": res.get("graded_by"),
                            }
                            if res
                            else None
                        ),
                    }
                )
        hw_items.sort(key=lambda i: i.get("due_at") or 0, reverse=True)

        _dump(out_root / "profile" / f"{ukey}.json", profile)
        _dump(out_root / "marks" / f"{ukey}.json", marks_rows)
        _dump(out_root / "attendance" / f"{ukey}.json", att_rows)
        _dump(out_root / "pomodoro" / f"{ukey}.json", pomo)
        _dump(
            out_root / "homework_report" / f"{ukey}.json",
            {
                "items": hw_items,
                "total": len(hw_items),
                "limit": len(hw_items),
                "offset": 0,
            },
        )
        written += 1

    # --- altın etiketler ---
    gold = {
        "t_now_ms": t_now,
        "school": SCHOOL,
        "calendar": manifest["calendar"],
        "students": [
            {
                "user": s["user"],
                "key": key_of(s["user"]),
                "archetype": s["archetype"],
                "class": s.get("class"),
                "theta_base": s.get("theta_base"),
                "theta_trend": s.get("theta_trend"),
                "t_break_ms": s.get("t_break_ms"),
                "gap_course": s.get("gap_course"),
                "gap_subjects": s.get("gap_subjects") or [],
                "omission_omega": s.get("omission_omega"),
                "edge_flags": s.get("edge_flags") or [],
                "true_counted_pomodoro": s.get("true_counted_pomodoro"),
            }
            for s in students
        ],
    }
    _dump(OUT_DIR / "gold.json", gold)
    return {"students": written, "out": str(OUT_DIR)}


def _dump(path: pathlib.Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None, help="yalnız ilk N öğrenci")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    info = build(limit=args.limit, verbose=not args.quiet)
    print(f"{info['students']} öğrenci fikstürü yazıldı → {info['out']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
