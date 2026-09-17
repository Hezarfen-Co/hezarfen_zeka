"""Dört raporun kurucuları.

| Rapor | Kime | İçerik |
|---|---|---|
| `okul`     | Yönetim  | Şube × ders kırılımı, toplu görünüm, koşu defteri |
| `ogretmen` | Öğretmen | Kendi şubeleri, dikkat listesi, sınıf ısı haritası |
| `ogrenci`  | Öğrenci  | Kendi eğilimi, çalışma düzeni, teslim durumu |
| `ham`      | Teknik   | Makine okunabilir beş tablo |

Kurucuların uyduğu değişmezler (hepsi `docs/CIKTI-SOZLESMESI.md`'den):

1. **Dikkat listesi öğrenci raporuna giremez** — `gate.py`: öğrenci kurucusu
   `attention` alanı olmayan bir tiple çalışır, personel demetini reddeder.
2. **Sıralama yok** — bütün listeler alfabetik ya da şube/ders sırasına
   göredir; "en kötüden en iyiye" bir düzen üretilmez.
3. **Kanıtsız satır girmez** (`filters.has_evidence`).
4. **Düşük güvende sayı yerine ibare** (`text.measure`, düşük güvende kart
   olgusu da ibareye döner).
5. **Kapatılmış** ve **süresi geçmiş** satırlar hiç görünmez.
6. **Segment karşıtlık olarak anlatılır**; ham doğruluk okunmaz bile
   (`reader.py` izdüşümünde `accuracy` yoktur).
7. **Öğrenci raporunda akran sıralaması yoktur**: karşılaştırma öğrencinin
   kendi geçmişi ve **anonim** şube dağılımıdır (tek sayı: şube ortalaması).
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from ..compute import marks as marks_mod
from ..compute import recommend as recommend_mod
from . import filters, text
from .document import Cards, Column, Data, Note, Report, Table
from .gate import (
    StaffSummary,
    StudentFacingBundle,
    allowed_roles,
    require_staff,
    require_student_facing,
)

BAND_KEYS = ("review", "on_track", "strong", "insufficient_data")

SIRALAMA_NOTU = (
    "Bu raporda sıralama yoktur. Listeler alfabetik ya da şube/ders sırasına "
    "göredir; öğrenciler birbirine göre dizilmez."
)

KANIT_NOTU = (
    "Kanıtı olmayan satır rapora girmez. Kapatılmış (dismissed) ve süresi "
    "geçmiş (expires_at) tavsiyeler gösterilmez."
)

GUVEN_NOTU = (
    "Güven kademesi düşük olan ölçülerde sayı gösterilmez, "
    f"«{text.LOW_CONFIDENCE_TEXT}» yazar. «{text.EXPLORATORY_SUFFIX}» eki, "
    "ölçünün henüz kararlı olmadığını söyler."
)

SEGMENT_NOTU = (
    "Segment sonuçları ham doğruluk olarak değil, karşıtlık olarak verilir: "
    "ham doğruluk öğrencinin genel yeteneğini yansıtır ve ayrım gücü yoktur "
    "(iyi öğrenci her segmentte yüksek çıkar). Karşıtlık, öğrencinin bir "
    "segmentteki başarısının kendi genel düzeyinden sapmasıdır. Etiketler bir "
    "dil modelinin çıktısıdır ve hatalıdır (docs/SEGMENT-CIKTI.md §4)."
)

DIKKAT_NOTU = (
    "Dikkat listesi bir öğretmen aracıdır: öğrenciye ve veliye gösterilmez "
    "(CIKTI-SOZLESMESI.md §5). Maddeler sıralanmaz; biri diğerinden «daha "
    "acil» değildir."
)

OGRENCI_NOTU = (
    "Bu raporda akran sıralaması yoktur. Karşılaştırma iki yönlüdür: kendi "
    "geçmişin ve şubenin anonim ortalaması. Başka bir öğrencinin adı, notu "
    "ya da sırası bu rapora girmez."
)

BOS_NOTU = (
    "Bu rapor boş üretildi: belirtilen okul/kişi için ZEKA veritabanında "
    "gösterilebilir satır bulunamadı. Gece koşusu hiç çalışmamış, koşu "
    "«skipped» dönmüş ya da bütün satırlar kapanma/süre/kanıt kapılarından "
    "düşmüş olabilir."
)


# ---------------------------------------------------------------------------
# Ortak yardımcılar
# ---------------------------------------------------------------------------


def _courses(summary: Any) -> dict[str, Any]:
    marks = getattr(summary, "marks", None) or {}
    courses = marks.get("courses") if isinstance(marks, dict) else None
    return courses if isinstance(courses, dict) else {}


def _class_ids(summary: Any) -> list[str]:
    marks = getattr(summary, "marks", None) or {}
    classes = marks.get("classes") if isinstance(marks, dict) else None
    return [str(c) for c in (classes or [])] or ["(şube bilinmiyor)"]


def _placement(cstat: dict[str, Any]) -> dict[str, Any]:
    placement = cstat.get("placement")
    return placement if isinstance(placement, dict) else {}


def _cards(
    rows: Iterable[dict[str, Any]], *, show_about: bool
) -> list[dict[str, Any]]:
    """Tavsiye kartları. Kanıt kapısı çağıran tarafta uygulanmıştır.

    Düşük güvende (**`confidence = none`**) kartın «Olgu» satırı sayı yerine
    ibare taşır: kanıt sayıları o kademede tek başına okunacak kadar
    güvenilir değildir.
    """
    items: list[dict[str, Any]] = []
    for row in rows:
        evidence = filters.evidence_payload(row)
        level = str(row.get("confidence") or "none")
        why = text.why_block(row, evidence)
        if level in text.LOW_CONFIDENCE:
            why[0] = {
                "label": "Olgu",
                "text": (
                    f"{text.LOW_CONFIDENCE_TEXT} — bu satırın kanıt sayıları "
                    "güven kapısının altında, tek başına okunmamalıdır."
                ),
            }
        item = {
            "rule_id": str(row.get("rule_id") or ""),
            "title": text.rule_title(row.get("rule_id")),
            "product": str(row.get("product") or ""),
            "course": row.get("course"),
            "confidence": level,
            "confidence_label": text.CONFIDENCE_LABELS.get(level, level),
            "why": why,
        }
        if show_about:
            item["about"] = row.get("about") or row.get("audience")
        items.append(item)
    return items


def _class_course_rows(summaries: list[StaffSummary]) -> list[dict[str, Any]]:
    """Şube × ders toplaması. Kohort ölçüleri `placement`'tan gelir."""
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for summary in summaries:
        for class_id in _class_ids(summary):
            for course_id, cstat in _courses(summary).items():
                key = (class_id, str(course_id))
                bucket = buckets.setdefault(
                    key,
                    {
                        "class": class_id,
                        "course": str(course_id),
                        "course_title": cstat.get("course_title") or str(course_id),
                        "n_students": 0,
                        "n_marks": 0,
                        "bands": Counter(),
                        "_cohort_n": 0,
                        "_class_average": None,
                        "_confidence": "none",
                    },
                )
                bucket["n_students"] += 1
                bucket["n_marks"] += int(cstat.get("n_marks") or 0)
                placement = _placement(cstat)
                band = str(placement.get("band") or "insufficient_data")
                bucket["bands"][band] += 1
                cohort_n = int(placement.get("cohort_n") or 0)
                if cohort_n > bucket["_cohort_n"]:
                    bucket["_cohort_n"] = cohort_n
                    bucket["_class_average"] = placement.get("class_average")
                    bucket["_confidence"] = str(placement.get("confidence") or "none")

    rows: list[dict[str, Any]] = []
    for (class_id, course_id), bucket in sorted(buckets.items()):
        row = {
            "class": class_id,
            "course": bucket["course_title"],
            "course_id": course_id,
            "n_students": bucket["n_students"],
            "n_marks": bucket["n_marks"],
            "class_average": text.measure(
                bucket["_class_average"], bucket["_confidence"]
            ),
            "cohort_n": bucket["_cohort_n"],
        }
        for band in BAND_KEYS:
            row[band] = int(bucket["bands"][band])
        n = sum(int(bucket["bands"][b]) for b in BAND_KEYS)
        # Isı değeri: «tekrar önerilir» bandındaki öğrencilerin payı. Bir
        # SIRALAMA DEĞİLDİR: şube-ders hücresinin yoğunluğunu gösterir,
        # öğrencileri birbirine göre dizmez.
        row["heat"] = (row["review"] / n) if n else 0.0
        rows.append(row)
    # Gösterilen ada göre alfabetik: tabloda ders adı görünür, kimliği değil.
    rows.sort(key=lambda r: (r["class"], r["course"], r["course_id"]))
    return rows


CLASS_COURSE_COLUMNS = [
    Column("class", "Şube"),
    Column("course", "Ders"),
    Column("n_students", "Öğrenci"),
    Column("n_marks", "Notlanmış sınav"),
    Column("class_average", "Şube ortalaması"),
    Column("review", "Tekrar önerilir"),
    Column("on_track", "Sınıf düzeyinde"),
    Column("strong", "Güçlü"),
    Column("insufficient_data", "Yeterli veri yok"),
]


def _attention_rows(summaries: list[StaffSummary]) -> list[dict[str, Any]]:
    """Dikkat listesi satırları — **yalnız personel raporlarında** çağrılır."""
    rows: list[dict[str, Any]] = []
    for summary in sorted(summaries, key=lambda s: s.student):
        for item in summary.attention:
            if not item.get("evidence"):
                continue  # kanıtsız madde rapora girmez
            rows.append(
                {
                    "student": summary.student,
                    "class": ", ".join(_class_ids(summary)),
                    "trigger": text.TRIGGER_LABELS.get(
                        str(item.get("trigger") or ""), str(item.get("trigger") or "")
                    ),
                    "fact": str(item.get("fact") or ""),
                    "window_from": text.date_tr(item.get("window_from")),
                    "window_to": text.date_tr(item.get("window_to")),
                }
            )
    return rows


ATTENTION_COLUMNS = [
    Column("student", "Öğrenci"),
    Column("class", "Şube"),
    Column("trigger", "Tetikleyici"),
    Column("fact", "Olgu"),
    Column("window_from", "Pencere başı"),
    Column("window_to", "Pencere sonu"),
]


def _run_table(runs: list[dict[str, Any]]) -> Table:
    rows = []
    for run in runs:
        rows.append(
            {
                "date": text.date_tr(run.get("started_at")),
                "status": str(run.get("status") or ""),
                "students_total": int(run.get("students_total") or 0),
                "students_ok": int(run.get("students_ok") or 0),
                "students_failed": int(run.get("students_failed") or 0),
                "students_skipped": int(run.get("students_skipped") or 0),
                "rows_written": int(run.get("rows_written") or 0),
                "budget_exceeded": "evet" if run.get("budget_exceeded") else "hayır",
                "failed_modules": ", ".join(run.get("failed_modules") or []) or "—",
                # `pending_students` bir KİŞİ LİSTESİDİR: rapora yalnız sayısı
                # girer (CIKTI-SOZLESMESI.md §5 son satır).
                "pending_count": len(run.get("pending_students") or []),
            }
        )
    note = ""
    if rows and rows[0]["status"] == "partial":
        note = (
            "Son koşu «partial»: bu gece bazı öğrenciler işlenemedi. Eksik "
            "veri sessizce tam gibi gösterilmemelidir."
        )
    return Table(
        id="kosu_defteri",
        title="Koşu defteri",
        columns=[
            Column("date", "Tarih"),
            Column("status", "Durum"),
            Column("students_total", "Öğrenci"),
            Column("students_ok", "Başarılı"),
            Column("students_failed", "Düşen"),
            Column("students_skipped", "Atlanan"),
            Column("rows_written", "Yazılan satır"),
            Column("budget_exceeded", "Bütçe aşıldı"),
            Column("failed_modules", "Düşen modül"),
            Column("pending_count", "Devreden öğrenci (sayı)"),
        ],
        rows=rows,
        note=note,
    )


def _rule_distribution(rows: list[dict[str, Any]]) -> Table:
    counter = Counter(str(r.get("rule_id") or "") for r in rows)
    table_rows = [
        {
            "rule_id": rule_id,
            "title": text.rule_title(rule_id),
            "count": count,
        }
        for rule_id, count in sorted(counter.items())
    ]
    return Table(
        id="tavsiye_dagilimi",
        title="Tavsiye dağılımı (kural bazında)",
        columns=[
            Column("rule_id", "Kural"),
            Column("title", "Ne der"),
            Column("count", "Satır"),
        ],
        rows=table_rows,
    )


def _unavailable_note() -> Note:
    """«Neden boş» sorusunun cevabı — üretilemeyen kurallar koddan okunur."""
    pairs = recommend_mod.unavailable_rules()
    lines = [f"{rule}: {reason}" for rule, reason in sorted(pairs.items())]
    return Note(
        id="uretilemeyenler",
        title="Üretilmeyen kurallar ve nedenleri",
        text=(
            "Aşağıdaki kurallar bilerek boştur; verisi olmadığı için "
            "üretilmiyorlar. Bu satırlar için ekran kurulmamalıdır.\n"
            + "\n".join(lines)
        ),
    )


# ---------------------------------------------------------------------------
# 1) Okul raporu — yönetim
# ---------------------------------------------------------------------------


def build_school_report(bundle: Any) -> Report:
    staff = require_staff(bundle)
    now = staff.generated_at
    visible = filters.visible_recommendations(
        staff.recommendations, now_ms=now, allowed_roles=allowed_roles("okul")
    )
    class_course = _class_course_rows(staff.summaries)
    attention = _attention_rows(staff.summaries)

    classes = sorted({row["class"] for row in class_course})
    overview = Table(
        id="toplu_gorunum",
        title="Toplu görünüm",
        columns=[
            Column("metric", "Ölçü"),
            Column("value", "Değer"),
        ],
        rows=[
            {"metric": "Öğrenci", "value": len(staff.summaries)},
            {"metric": "Şube", "value": len(classes)},
            {"metric": "Şube × ders hücresi", "value": len(class_course)},
            {"metric": "Gösterilen tavsiye", "value": len(visible)},
            {"metric": "Dikkat listesi maddesi", "value": len(attention)},
            {
                "metric": "Segment satırı (gösterilebilir)",
                "value": len(filters.visible_segment_profiles(staff.segment_profiles)),
            },
        ],
    )

    sections: list[Any] = [
        overview,
        Table(
            id="sube_ders",
            title="Şube × ders kırılımı",
            columns=CLASS_COURSE_COLUMNS,
            rows=class_course,
            note=(
                "Bant dağılımı öğrenci sayısıdır. Referans dağılım şube × ders "
                "düzeyindedir; okul geneli havuz kullanılmaz."
            ),
        ),
        _run_table(staff.runs),
        Table(
            id="dikkat_listesi",
            title="Dikkat listesi (yalnız yönetim ve öğretmen)",
            columns=ATTENTION_COLUMNS,
            rows=attention,
            note=DIKKAT_NOTU,
        ),
        _rule_distribution(visible),
        _unavailable_note(),
    ]

    empty = not staff.summaries and not visible and not staff.runs
    notes = [SIRALAMA_NOTU, KANIT_NOTU, GUVEN_NOTU, DIKKAT_NOTU, SEGMENT_NOTU]
    if empty:
        notes.insert(0, BOS_NOTU)
    return Report(
        kind="okul",
        school=staff.school,
        generated_at=now,
        title=f"{staff.school} — okul raporu",
        sections=sections,
        notes=notes,
        empty=empty,
    )


# ---------------------------------------------------------------------------
# 2) Öğretmen raporu
# ---------------------------------------------------------------------------


def build_teacher_report(bundle: Any) -> Report:
    staff = require_staff(bundle)
    now = staff.generated_at
    teacher = staff.teacher or ""
    visible = filters.visible_recommendations(
        staff.recommendations, now_ms=now, allowed_roles=allowed_roles("ogretmen")
    )
    mine = [r for r in visible if str(r.get("audience") or "") == teacher]
    # Öğretmenin kapsamı: hakkında tavsiye aldığı öğrenciler.
    students = {str(r.get("about")) for r in mine if r.get("about")}
    scoped = [s for s in staff.summaries if s.student in students]
    if not scoped and not students:
        scoped = []

    class_course = _class_course_rows(scoped)
    attention = _attention_rows(scoped)

    heat = Table(
        id="isi_haritasi",
        title="Sınıf ısı haritası (şube × ders)",
        columns=CLASS_COURSE_COLUMNS + [Column("heat", "Tekrar payı")],
        rows=[
            {**row, "heat": text.num(row["heat"] * 100, 0) + "%"}
            for row in class_course
        ],
        note=(
            "Hücre yoğunluğu «tekrar önerilir» bandındaki öğrenci payıdır. "
            "Bu bir sıralama değildir: öğrenciler birbirine göre dizilmez."
        ),
    )

    sections: list[Any] = [
        Table(
            id="siniflarim",
            title="Şubelerim ve derslerim",
            columns=CLASS_COURSE_COLUMNS,
            rows=class_course,
        ),
        Table(
            id="dikkat_listesi",
            title="Dikkat listesi",
            columns=ATTENTION_COLUMNS,
            rows=attention,
            note=DIKKAT_NOTU,
        ),
        heat,
        Cards(
            id="tavsiyeler",
            title="Tavsiyeler",
            items=_cards(mine, show_about=True),
            note=KANIT_NOTU,
        ),
        _unavailable_note(),
    ]

    empty = not mine and not scoped
    notes = [SIRALAMA_NOTU, KANIT_NOTU, GUVEN_NOTU, DIKKAT_NOTU]
    if empty:
        notes.insert(0, BOS_NOTU)
    return Report(
        kind="ogretmen",
        school=staff.school,
        generated_at=now,
        title=f"{staff.school} — öğretmen raporu",
        subject=teacher,
        sections=sections,
        notes=notes,
        empty=empty,
    )


# ---------------------------------------------------------------------------
# 3) Öğrenci özeti — dikkat listesi BURAYA GİREMEZ
# ---------------------------------------------------------------------------


def build_student_report(bundle: Any) -> Report:
    """Öğrenci/veli raporu.

    İlk satır kapıdır: bu fonksiyon `StudentFacingBundle` dışında bir şey
    kabul etmez ve o tipin `attention` alanı **yoktur**. Dikkat listesi
    buraya bir filtreyle değil, **tip düzeyinde** giremez.
    """
    facing: StudentFacingBundle = require_student_facing(bundle)
    now = facing.generated_at
    summary = facing.summary
    visible = filters.visible_recommendations(
        facing.recommendations, now_ms=now, allowed_roles=allowed_roles("ogrenci")
    )
    segments = filters.visible_segment_profiles(facing.segment_profiles)

    course_rows: list[dict[str, Any]] = []
    for course_id, cstat in sorted(_courses(summary).items()):
        placement = _placement(cstat)
        # Konum bandının güveni kohorta bağlıdır; öğrencinin KENDİ ortalaması
        # ise kendi not sayısına bağlıdır. İkisi ayrı kademelerdir: küçük bir
        # şubede bant üretilemezken öğrencinin ortalaması pekâlâ bilinir.
        level = str(placement.get("confidence") or "none")
        n_marks = int(cstat.get("n_marks") or 0)
        own_level = "stable" if n_marks >= marks_mod.MIN_MARKS_FOR_BAND else "none"
        course_rows.append(
            {
                "course": cstat.get("course_title") or str(course_id),
                "n_marks": n_marks,
                "average": text.measure(cstat.get("average"), own_level),
                "band": text.band_text(placement),
                "trend": text.trend_text(cstat.get("trend")),
                # Anonim dağılım: yalnız şube ortalaması. Akran adı, akran
                # notu, sıra numarası yok.
                "class_average": text.measure(placement.get("class_average"), level),
            }
        )

    study = getattr(summary, "study", None) or {}
    recent = study.get("recent_28d") if isinstance(study, dict) else None
    recent = recent if isinstance(recent, dict) else {}
    regularity_level = "none" if recent.get("regularity_suppressed", True) else "exploratory"
    study_rows = [
        {
            "metric": "Son 28 günde çalışılan gün",
            "value": text.measure(recent.get("active_days"), "stable", digits=0),
        },
        {
            "metric": "Son 28 günde oturum",
            "value": text.measure(recent.get("n_stints"), "stable", digits=0),
        },
        {
            "metric": "Toplam odak (saat)",
            "value": text.measure(
                (int(recent.get("total_focus_ms") or 0) / 3_600_000)
                if recent.get("total_focus_ms")
                else None,
                "stable" if recent.get("total_focus_ms") else "none",
            ),
        },
        {
            "metric": "Düzenlilik (çalışılan gün oranı)",
            "value": text.measure(recent.get("regularity"), regularity_level, digits=2),
        },
    ]

    submission = getattr(summary, "submission", None) or {}
    overall = submission.get("overall") if isinstance(submission, dict) else None
    overall = overall if isinstance(overall, dict) else {}
    rate_level = "none" if overall.get("rates_suppressed", True) else "exploratory"
    submission_rows = [
        {
            "metric": "Ödev sayısı",
            "value": text.measure(overall.get("n"), "stable", digits=0),
        },
        {
            "metric": "Zamanında teslim oranı",
            "value": text.measure(
                overall.get("on_time_rate_by_last_touch"), rate_level, digits=2
            ),
        },
        {
            "metric": "Geç teslim oranı",
            "value": text.measure(overall.get("late_rate"), rate_level, digits=2),
        },
        {
            "metric": "Teslim edilmemiş",
            "value": text.measure(overall.get("n_missing"), "stable", digits=0),
        },
    ]

    upcoming_rows = []
    for item in (submission.get("upcoming") or []) if isinstance(submission, dict) else []:
        if not isinstance(item, dict):
            continue
        upcoming_rows.append(
            {
                "homework": str(item.get("homework") or item.get("id") or ""),
                "course": str(item.get("course") or ""),
                "due_at": text.date_tr(item.get("due_at")),
            }
        )
    upcoming_rows.sort(key=lambda r: (r["due_at"], r["homework"]))

    segment_rows = [
        {
            "dimension": text.dimension_label(row.get("dimension")),
            "label": text.label_label(row.get("label")),
            "sentence": text.contrast_sentence(row),
            "n_answers": int(row.get("n_answers") or 0),
            "confidence": text.CONFIDENCE_LABELS.get(
                str(row.get("confidence") or "none"), "—"
            ),
        }
        for row in segments
    ]

    sections: list[Any] = [
        Table(
            id="dersler",
            title="Derslerim",
            columns=[
                Column("course", "Ders"),
                Column("n_marks", "Notlanmış sınav"),
                Column("average", "Ortalamam"),
                Column("band", "Konum"),
                Column("trend", "Eğilim"),
                Column("class_average", "Şube ortalaması (anonim)"),
            ],
            rows=course_rows,
            note=OGRENCI_NOTU,
        ),
        Table(
            id="calisma",
            title="Çalışma düzenim",
            columns=[Column("metric", "Ölçü"), Column("value", "Değer")],
            rows=study_rows,
        ),
        Table(
            id="teslim",
            title="Teslim durumum",
            columns=[Column("metric", "Ölçü"), Column("value", "Değer")],
            rows=submission_rows,
        ),
        Table(
            id="yaklasan",
            title="Yaklaşan teslimler",
            columns=[
                Column("homework", "Ödev"),
                Column("course", "Ders"),
                Column("due_at", "Son teslim"),
            ],
            rows=upcoming_rows,
        ),
        Table(
            id="segment",
            title="Soru türlerine göre kendi karşıtlığım",
            columns=[
                Column("dimension", "Boyut"),
                Column("label", "Etiket"),
                Column("sentence", "Ne diyor"),
                Column("n_answers", "Cevap"),
                Column("confidence", "Güven"),
            ],
            rows=segment_rows,
            note=SEGMENT_NOTU,
        ),
        Cards(
            id="tavsiyeler",
            title="Sana özel öneriler",
            items=_cards(visible, show_about=False),
            note=KANIT_NOTU,
        ),
    ]

    empty = summary is None and not visible and not segments
    notes = [OGRENCI_NOTU, SIRALAMA_NOTU, KANIT_NOTU, GUVEN_NOTU, SEGMENT_NOTU]
    if empty:
        notes.insert(0, BOS_NOTU)
    return Report(
        kind="ogrenci",
        school=facing.school,
        generated_at=now,
        title=f"{facing.school} — öğrenci özeti",
        subject=facing.student,
        sections=sections,
        notes=notes,
        empty=empty,
    )


# ---------------------------------------------------------------------------
# 4) Ham çıktı — teknik ekip
# ---------------------------------------------------------------------------


def build_raw_report(bundle: Any) -> Report:
    """Makine okunabilir ham çıktı.

    Görünürlük kapıları **burada da** uygulanır: kapatılmış, süresi geçmiş ve
    kanıtsız tavsiye ihraç edilmez. Teknik ekip bu dosyayı kendi ekranına
    bağlar; kapıyı orada yeniden kurmak zorunda kalmamalı.

    `question_segment.rationale` ve `trap_choice` ihraçtan **çıkarılır**
    (`reader.QUESTION_SEGMENT_HIDDEN`): biri modelin hatalı gerekçesi, diğeri
    doğrudan cevap ipucudur. `student_segment_profile.accuracy` zaten
    okunmaz — sözleşme onu tek başına yasaklar, karşılığı `contrast`'tır.
    """
    staff = require_staff(bundle)
    now = staff.generated_at
    visible = filters.visible_recommendations(
        staff.recommendations, now_ms=now, allowed_roles=allowed_roles("ham")
    )
    segments = filters.visible_segment_profiles(staff.segment_profiles)

    summaries = [
        {
            "school": s.school,
            "student": s.student,
            "marks": s.marks,
            "attendance": s.attendance,
            "submission": s.submission,
            "study": s.study,
            "attention": s.attention,
            "confidence": s.confidence,
            "computed_at": s.computed_at,
        }
        for s in sorted(staff.summaries, key=lambda s: s.student)
    ]

    rec_rows = [
        {
            "rule_id": r.get("rule_id"),
            "product": r.get("product"),
            "audience": r.get("audience"),
            "audience_role": r.get("audience_role"),
            "about": r.get("about"),
            "course": r.get("course"),
            "confidence": r.get("confidence"),
            "created_at": r.get("created_at"),
            "expires_at": r.get("expires_at"),
            "rule_version": r.get("rule_version"),
        }
        for r in visible
    ]
    segment_rows = [
        {
            "student": r.get("student"),
            "dimension": r.get("dimension"),
            "label": r.get("label"),
            "n_answers": r.get("n_answers"),
            "contrast": r.get("contrast"),
            "confidence": r.get("confidence"),
        }
        for r in segments
    ]

    sections: list[Any] = [
        Data(
            id="tables",
            title="Beş tablo (filtrelenmiş)",
            data={
                "student_summary": summaries,
                "recommendation": visible,
                "student_segment_profile": segments,
                "insight_run": staff.runs,
                "question_segment": staff.question_segments,
                "unavailable_rules": recommend_mod.unavailable_rules(),
            },
            note=(
                "recommendation: kapatılmış / süresi geçmiş / kanıtsız satırlar "
                "çıkarıldı. question_segment: rationale ve trap_choice "
                "çıkarıldı. student_segment_profile: accuracy okunmaz, "
                "karşılığı contrast'tır."
            ),
        ),
        Table(
            id="recommendation",
            title="recommendation (düz tablo)",
            columns=[
                Column("rule_id", "rule_id"),
                Column("product", "product"),
                Column("audience", "audience"),
                Column("audience_role", "audience_role"),
                Column("about", "about"),
                Column("course", "course"),
                Column("confidence", "confidence"),
                Column("created_at", "created_at"),
                Column("expires_at", "expires_at"),
                Column("rule_version", "rule_version"),
            ],
            rows=rec_rows,
        ),
        Table(
            id="student_segment_profile",
            title="student_segment_profile (düz tablo)",
            columns=[
                Column("student", "student"),
                Column("dimension", "dimension"),
                Column("label", "label"),
                Column("n_answers", "n_answers"),
                Column("contrast", "contrast"),
                Column("confidence", "confidence"),
            ],
            rows=segment_rows,
            note=SEGMENT_NOTU,
        ),
        _unavailable_note(),
    ]

    empty = not summaries and not visible and not staff.runs
    notes = [KANIT_NOTU, GUVEN_NOTU, SEGMENT_NOTU, DIKKAT_NOTU]
    if empty:
        notes.insert(0, BOS_NOTU)
    return Report(
        kind="ham",
        school=staff.school,
        generated_at=now,
        title=f"{staff.school} — ham çıktı",
        sections=sections,
        notes=notes,
        empty=empty,
    )


#: Rapor tipi → kurucu. `StudentFacingBundle` yalnız `ogrenci` kurucusuna
#: verilebilir; diğer üçü `StaffBundle` ister ve tip uymazsa `TypeError` atar.
BUILDERS = {
    "okul": build_school_report,
    "ogretmen": build_teacher_report,
    "ogrenci": build_student_report,
    "ham": build_raw_report,
}


def build(kind: str, bundle: Any) -> Report:
    try:
        builder = BUILDERS[kind]
    except KeyError:
        raise ValueError(f"bilinmeyen rapor tipi: {kind!r}") from None
    return builder(bundle)
