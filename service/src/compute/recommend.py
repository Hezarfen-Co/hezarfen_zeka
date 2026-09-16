"""Kural motoru: hesap modüllerinin çıktısını kanıtlı tavsiyelere çevirir.

Kaynak: `spec/MODULLER.md` §2.10 `insight::recommend`.

**Girdi yalnız bellekteki modül çıktılarıdır. Ham tablo okunmaz, `Source`
çağrılmaz.** Bu bilinçli bir kısıttır: motorun erişim alanı, hesap
modüllerinin çıktı tipleriyle sınırlanır (`MODULLER.md` §2.10 girdi künyesi).

**Beş yapısal kural (`MODULLER.md` §2.10):**

1. **Kanıtsız satır yazılmaz.** `model.Recommendation` boş `evidence` ile
   kurulamaz — assert değil, tip kısıtı.
2. **Beş bölümlü "Neden?" zorunlu:** Olgu · Karşılaştırma · Kural (hangi eşik,
   hangi sürüm) · **Sınır** (neyin dahil olmadığı) · Tarih. `limitation` alanı
   boşsa nesne kurulamaz.
3. **Otomatik eylem yok.** Hiçbir tavsiye bir notu değiştirmez, bir öğrenciyi
   bir gruba atamaz. `store.py` yalnız `student_summary`, `recommendation` ve
   `insight_run` tablolarına yazar; okul veritabanına **hiç** yazmaz.
4. **Kapatma bir veridir.** `dismissed_*` alanları şemada tanımlı.
5. **Sessiz değişiklik yasak.** `model.RULE_VERSION` artışı kullanıcıya
   gösterilir.

**Güven kapısı devralınır:** bir modül `InsufficientData` döndürdüyse motor o
satırı **hiç üretmez** — boş kart göstermez (`[T§3]` ilke 4: sinyali olmayan
ürün kendini gizler).
"""

from __future__ import annotations

from typing import Any

from . import clock, marks as marks_mod, segments as segments_mod, study as study_mod
from .model import (
    Audience,
    AttentionItem,
    Band,
    Confidence,
    Recommendation,
    TriggerKind,
)

# `MODULLER.md` §2.10 kural kataloğu, `expires_at` sütunu.
EXPIRY_NEXT_RUN_DAYS = 1
EXPIRY_STUDY_DAYS = 7
EXPIRY_ATTENTION_DAYS = 30
# Segment profili yavaş değişir: kapıyı geçmek için segment başına 150 cevap
# gerekiyor, bu da haftalar demek. Her gece yeniden üretilen bir kart burada
# "yeni bilgi" taşımaz; 30 gün, kartın bayatlamadan yaşayacağı süredir.
EXPIRY_SEGMENT_DAYS = 30

# Öğrenciye giden segment kuralı **hangi boyutlara** bakar.
# `dikkat_tuzagi` bilerek dışarıdadır: onun kendi kuralı var
# (`O2.segment_trap_prone`), çünkü söylediği şey farklıdır — "zor buluyor"
# değil, "tuzağa yakalanıyor".
STUDENT_SEGMENT_DIMENSIONS = ("bilissel_talep", "okuma_yuku")

# `MODULLER.md` §2.8 tetikleyici → `rule_id` eşlemesi.
_TRIGGER_RULE = {
    TriggerKind.ATTENDANCE: "T4.attendance",
    TriggerKind.HOMEWORK: "T4.homework",
    TriggerKind.MARK_TREND: "T4.mark_trend",
    TriggerKind.EXAM_MISSED: "T4.exam_missed",
}


# ---------------------------------------------------------------------------
# Kural kataloğu — v1'de ÜRETİLEBİLENLER
# ---------------------------------------------------------------------------

RULE_CATALOG: dict[str, dict[str, str]] = {
    "O1.review_band": {
        "product": "O1",
        "audience": "student",
        "condition": "band = Review ve n_marks >= 3",
        "source": "MODULLER.md §2.10 kural tablosu (O1.review_band)",
    },
    "O3.pattern": {
        "product": "O3",
        "audience": "student",
        "condition": "n_stints >= 5",
        "source": "MODULLER.md §2.10 kural tablosu (O3.pattern)",
    },
    "O4.deadline": {
        "product": "O4",
        "audience": "student",
        "condition": "remind_at <= now <= due_at ve teslim yok",
        "source": "MODULLER.md §2.10 kural tablosu (O4.deadline)",
    },
    "T3.class_gap": {
        "product": "T3",
        "audience": "teacher",
        "condition": "kohort ortalaması < 50 ve kohort >= 8",
        "source": "MODULLER.md §2.10 kural tablosu (T3.class_gap)",
    },
    "T3.individual_gap": {
        "product": "T3",
        "audience": "teacher",
        "condition": "kohort ortalaması >= 50 ve z < -0,8",
        "source": "MODULLER.md §2.10 kural tablosu (T3.individual_gap)",
    },
    "T4.attendance": {
        "product": "T4",
        "audience": "teacher",
        "condition": "attention.py tetikleyici 1",
        "source": "MODULLER.md §2.8",
    },
    "T4.homework": {
        "product": "T4",
        "audience": "teacher",
        "condition": "attention.py tetikleyici 2",
        "source": "MODULLER.md §2.8",
    },
    "T4.mark_trend": {
        "product": "T4",
        "audience": "teacher",
        "condition": "attention.py tetikleyici 3",
        "source": "MODULLER.md §2.8",
    },
    # --- Segment tabanlı kurallar (bu sürümde eklendi) --------------------
    #
    # Üçünün de girdisi `student_segment_profile` tablosunun bellekteki hâli
    # (`compute/segments.py::profile_payload`). Üçü de **göreli kontrast**
    # okur: ham doğruluk öğrencinin genel yeteneğini taşır, ayrım gücü yoktur.
    "O2.segment_cognitive_gap": {
        "product": "O2",
        "audience": "student",
        "condition": (
            f"n_answers >= {segments_mod.MIN_ANSWERS_PER_SEGMENT} ve "
            "relative_contrast <= boyut eşiği (bilissel_talep -0,080 / "
            "okuma_yuku -0,060)"
        ),
        "source": "service/docs/SEGMENT-CIKTI.md §3 (ölçülmüş eşik)",
    },
    "O2.segment_trap_prone": {
        "product": "O2",
        "audience": "student",
        "condition": (
            f"dikkat_tuzagi=var, n_answers >= "
            f"{segments_mod.MIN_ANSWERS_PER_SEGMENT} ve relative_contrast "
            "<= -0,032"
        ),
        "source": "service/docs/SEGMENT-CIKTI.md §3 (ölçülmüş eşik)",
    },
    "T3.segment_class_gap": {
        "product": "T3",
        "audience": "teacher",
        "condition": (
            f"sınıfta kapıyı geçen >= {segments_mod.MIN_CLASS_STUDENTS} "
            "öğrenci ve sınıf ortalama relative_contrast <= "
            f"{segments_mod.CLASS_RELATIVE_CONTRAST_GATE}"
        ),
        "source": "service/docs/SEGMENT-CIKTI.md §5",
    },
}


def unavailable_rules() -> dict[str, str]:
    """v1'de **üretilemeyen** kurallar ve engelleri.

    Sahte bir uygulama yazmak yerine listelemek, `[T§3 Y1]`'in "ölçüm
    eklenmedi der, sahte sayı göstermez" ilkesinin kural motoru karşılığıdır.
    """
    return {
        "O2.retry_item": "Ham sınav cevabı yok — madde bazlı tekrar listesi kurulamaz.",
        "O2.common_mistake": "Çeldirici dağılımı yok (ham cevap yok).",
        "O2.progress": "seq=2 cevapları yok.",
        "O4.last_minute": "submitted_at yok — erteleme profili hesaplanamaz.",
        "O5.pool_match": "Havuz sorusu ve çözüm verisi Source arayüzünde yok.",
        "T1.hard_item": "Madde analizi yapılamıyor (ham cevap yok).",
        "T1.distractor_beats_key": "Aynı sebep.",
        "T2.low_discrimination": "Ayırt edicilik hesaplanamıyor (ham cevap yok).",
        "T2.key_suspect": "Aynı sebep.",
        "T4.exam_missed": "Sınav takvimi ve exam_attempt yok.",
        "T5.stale_appointment": "Randevu verisi Source arayüzünde yok.",
        "T5.unanswered_pool": "Havuz sorusu verisi yok.",
        "T5.chat_failures": "Sohbet verisi yok ve etik olarak istenmedi.",
        "V1.weekly_digest": (
            "parent_link yok — velinin kim olduğu çözülemiyor. Ayrıca haftalık "
            "pencere için devam verisinde tarih yok."
        ),
        "Y1.uncovered_subject": "subject sayaçları ve sınav listesi yok.",
        "Y1.grade_inconsistency": "class_blueprint verisi yok.",
        "Y1.ungraded_exam": "Sınav listesi yok.",
    }


# ---------------------------------------------------------------------------
# Öğrenciye giden kurallar
# ---------------------------------------------------------------------------


def _student_rules(
    school: str,
    student: str,
    marks_profile: dict[str, Any],
    study_profile: dict[str, Any],
    submission_profile: dict[str, Any],
    now_ms: int,
) -> list[Recommendation]:
    out: list[Recommendation] = []

    # --- O1.review_band ----------------------------------------------------
    for course_id, cstat in (marks_profile.get("courses") or {}).items():
        placement = cstat.get("placement") or {}
        if placement.get("band") != Band.REVIEW:
            continue
        out.append(
            Recommendation(
                school=school,
                audience=student,
                audience_role=Audience.STUDENT,
                product="O1",
                rule_id="O1.review_band",
                course=course_id,
                confidence=placement.get("confidence") or Confidence.EXPLORATORY,
                evidence={
                    "course": course_id,
                    "course_title": cstat.get("course_title"),
                    "n_marks": cstat.get("n_marks"),
                    "average": cstat.get("average"),
                    "class_average": placement.get("class_average"),
                    "class_sd": placement.get("class_sd"),
                    "z": placement.get("z"),
                    "cohort_n": placement.get("cohort_n"),
                    "band": str(placement.get("band")),
                    "rule": f"z < -{marks_mod.BAND_Z} (MODULLER.md §2.3 adım 4)",
                },
                computed_at=now_ms,
                expires_at=now_ms + EXPIRY_NEXT_RUN_DAYS * clock.DAY_MS,
                limitation=marks_profile.get("limitation", ""),
            )
        )

    # --- O3.pattern --------------------------------------------------------
    recent = study_profile.get("recent_28d") or {}
    if int(recent.get("n_stints") or 0) >= study_mod.MIN_STINTS_FOR_HEATMAP:
        out.append(
            Recommendation(
                school=school,
                audience=student,
                audience_role=Audience.STUDENT,
                product="O3",
                rule_id="O3.pattern",
                confidence=Confidence.EXPLORATORY,
                evidence={
                    "n_stints_28": recent.get("n_stints"),
                    "active_days_28": recent.get("active_days"),
                    "regularity": recent.get("regularity"),
                    "burstiness": recent.get("burstiness"),
                    # `bursty` bayrağı kaldırıldı (kusur K5): ölçü gün-arası
                    # yığılmayı ölçüyor, "düzensiz çalışıyor" yargısını değil.
                    "burstiness_limitation": recent.get("burstiness_limitation"),
                    "median_stint_min": (
                        None
                        if recent.get("median_stint_ms") is None
                        else recent["median_stint_ms"] / 60_000.0
                    ),
                    "streak_local": study_profile.get("streak_local"),
                    "active_days_delta": (study_profile.get("change") or {}).get(
                        "active_days_delta"
                    ),
                    "rule": (
                        f"n_stints >= {study_mod.MIN_STINTS_FOR_HEATMAP} "
                        "(MODULLER.md §2.6 güven kapısı)"
                    ),
                },
                computed_at=now_ms,
                expires_at=now_ms + EXPIRY_STUDY_DAYS * clock.DAY_MS,
                limitation=study_profile.get("limitation", ""),
            )
        )

    # --- O4.deadline -------------------------------------------------------
    for item in submission_profile.get("upcoming") or []:
        if item.get("submitted"):
            continue
        if now_ms < int(item["remind_at"]):
            continue
        out.append(
            Recommendation(
                school=school,
                audience=student,
                audience_role=Audience.STUDENT,
                product="O4",
                rule_id="O4.deadline",
                course=item.get("course") or None,
                confidence=Confidence.STABLE,
                evidence={
                    "homework": item.get("homework"),
                    "title": item.get("title"),
                    "due_at": item.get("due_at"),
                    "hours_left": item.get("hours_left"),
                    "high_priority": item.get("high_priority"),
                    "rule": (
                        "remind_at = due_at - 24 saat (sabit; erteleme profili "
                        "hesaplanamadığı için MODULLER.md §2.4 kapı-altı kolonu)"
                    ),
                },
                computed_at=now_ms,
                expires_at=int(item["due_at"]),
                limitation=submission_profile.get("limitation", ""),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Öğretmene giden kurallar
# ---------------------------------------------------------------------------


def _teacher_rules(
    school: str,
    student: str,
    marks_profile: dict[str, Any],
    attention_items: list[AttentionItem],
    course_teachers: dict[str, list[str]],
    now_ms: int,
) -> list[Recommendation]:
    """T3 ve T4 satırları.

    **Yetki kuralı (`[T§5.3]`, `MODULLER.md` §2.8 "Kapsam" kapısı):** alıcı,
    yalnız öğrencinin o dersindeki öğretmendir — o veriyi bugün de görebilen
    kişi. Ders öğretmeni yalnız **kendi dersindeki** tetikleyiciyi görür.
    Öğretmeni çözülemeyen bir tetikleyici **üretilmez**; yayın yapılmaz.
    """
    out: list[Recommendation] = []
    student_courses = list((marks_profile.get("courses") or {}).keys())

    # --- T3.class_gap / T3.individual_gap ---------------------------------
    for course_id, cstat in (marks_profile.get("courses") or {}).items():
        placement = cstat.get("placement") or {}
        class_avg = placement.get("class_average")
        z = placement.get("z")
        if class_avg is None or z is None:
            continue
        teachers = course_teachers.get(course_id) or []
        if not teachers:
            continue

        if class_avg < marks_mod.CLASS_GAP_AVERAGE:
            rule_id, product_note = "T3.class_gap", "sınıf düzeyinde boşluk"
        elif z < -marks_mod.BAND_Z:
            rule_id, product_note = "T3.individual_gap", "bireysel destek"
        else:
            continue

        for teacher in teachers:
            out.append(
                Recommendation(
                    school=school,
                    audience=teacher,
                    audience_role=Audience.TEACHER,
                    about=student,
                    product="T3",
                    rule_id=rule_id,
                    course=course_id,
                    confidence=placement.get("confidence") or Confidence.EXPLORATORY,
                    evidence={
                        "student": student,
                        "course": course_id,
                        "course_title": cstat.get("course_title"),
                        "student_average": cstat.get("average"),
                        "class_average": class_avg,
                        "z": z,
                        "cohort_n": placement.get("cohort_n"),
                        "reading": product_note,
                        "rule": RULE_CATALOG[rule_id]["condition"],
                    },
                    computed_at=now_ms,
                    expires_at=now_ms + EXPIRY_NEXT_RUN_DAYS * clock.DAY_MS,
                    limitation=marks_profile.get("limitation", ""),
                )
            )

    # --- T4.* --------------------------------------------------------------
    for item in attention_items:
        rule_id = _TRIGGER_RULE[item.trigger]
        if item.trigger is TriggerKind.MARK_TREND:
            scope = [str(item.evidence.get("course") or "")]
        else:
            # Ders üstü tetikleyici: öğrencinin **derslerinin** öğretmenlerine
            # gider. Bu kişiler o öğrencinin devamını/ödevini bugün de
            # görebiliyor; yetki genişletmesi yok (`[T§5.3]`).
            scope = student_courses
        seen: set[str] = set()
        for course_id in scope:
            for teacher in course_teachers.get(course_id) or []:
                if teacher in seen:
                    continue
                seen.add(teacher)
                out.append(
                    Recommendation(
                        school=school,
                        audience=teacher,
                        # T4 **yalnız** öğretmene gider; öğrenciye ve veliye
                        # gösterilmez (`[T§6.8]`).
                        audience_role=Audience.TEACHER,
                        about=student,
                        product="T4",
                        rule_id=rule_id,
                        course=course_id or None,
                        confidence=Confidence.EXPLORATORY,
                        evidence={
                            "student": student,
                            "trigger": item.trigger.value,
                            "fact": item.fact,
                            "window_from": item.window_from,
                            "window_to": item.window_to,
                            **item.evidence,
                        },
                        computed_at=now_ms,
                        expires_at=now_ms + EXPIRY_ATTENTION_DAYS * clock.DAY_MS,
                        limitation=str(
                            item.evidence.get("limitation")
                            or "Bu madde bir olgudur, bir yargı değildir."
                        ),
                    )
                )
    return out


# ---------------------------------------------------------------------------
# Segment tabanlı kurallar
# ---------------------------------------------------------------------------
#
# ÜÇ ORTAK KURAL — üçü de zorunlu:
#
# 1. **Ham doğruluk kural ateşlemez.** `accuracy` öğrencinin genel yeteneğini
#    yansıtır. Ateşleyen ölçü `relative_contrast`, yani
#    (segment doğruluğu − kendi genel doğruluğu) − (kohortun aynı farkı).
#    İkinci çıkarma madde zorluğunu siler: analiz soruları **herkes** için
#    zordur, çıkarılmazsa kural herkeste ateşlerdi.
# 2. **Güven kapısı.** Segmentte `MIN_ANSWERS_PER_SEGMENT` cevabın altında
#    kural ÜRETİLMEZ — boş kart gösterilmez (`[T§3]` ilke 4).
# 3. **Kanıt zorunlu.** Her satır hangi sayıların eşiği geçtiğini taşır;
#    `Recommendation` kanıtsız kurulamaz zaten.


def _segment_fact(dimension: str, label: str) -> str:
    """Olgu cümlesinin okunur hâli. "zayıf" kelimesi KULLANILMAZ ([T§3 Ö1])."""
    return {
        ("bilissel_talep", "analiz"): "analiz gerektiren sorular",
        ("bilissel_talep", "uygulama"): "uygulama gerektiren sorular",
        ("bilissel_talep", "hatirlama"): "bilgi hatırlatan sorular",
        ("okuma_yuku", "yuksek"): "uzun metinli sorular",
        ("okuma_yuku", "dusuk"): "kısa metinli sorular",
        ("dikkat_tuzagi", "var"): "dikkat tuzağı taşıyan sorular",
        ("dikkat_tuzagi", "yok"): "dikkat tuzağı taşımayan sorular",
    }.get((dimension, label), f"{dimension}={label} soruları")


def _segment_evidence(
    dimension: str, label: str, row: dict[str, Any], overall: dict[str, Any] | None
) -> dict[str, Any]:
    """Kanıt nesnesi — "Neden?" ekranının beslendiği yer."""
    return {
        "dimension": dimension,
        "label": label,
        "fact": _segment_fact(dimension, label),
        "n_answers": row.get("n_answers"),
        "n_correct": row.get("n_correct"),
        "accuracy": row.get("accuracy"),
        "overall_accuracy": (overall or {}).get("accuracy"),
        "overall_n_answers": (overall or {}).get("n_answers"),
        "contrast": row.get("contrast"),
        "reference_mean_contrast": row.get("reference_mean_contrast"),
        "reference_n_students": row.get("reference_n_students"),
        "relative_contrast": row.get("relative_contrast"),
        "gate_n_answers": segments_mod.MIN_ANSWERS_PER_SEGMENT,
    }


def _segment_student_rules(
    school: str,
    student: str,
    segment_profile: dict[str, Any],
    now_ms: int,
) -> list[Recommendation]:
    """`O2.segment_cognitive_gap` ve `O2.segment_trap_prone`."""
    out: list[Recommendation] = []
    dimensions = segment_profile.get("dimensions") or {}
    overall = segment_profile.get("overall")
    limitation = segment_profile.get("limitation") or segments_mod.LIMITATION

    def _fires(dimension: str, row: dict[str, Any]) -> bool:
        if not row.get("gate_passed"):
            return False
        relative = row.get("relative_contrast")
        gate = segments_mod.RELATIVE_CONTRAST_GATE.get(dimension)
        if relative is None or gate is None:
            # Referans yoksa (kohort çok küçük) kural ÜRETİLMEZ. Ham kontrastla
            # ateşlemek, madde zorluğunu öğrenciye yazmak olurdu.
            return False
        return float(relative) <= gate

    # --- O2.segment_cognitive_gap -----------------------------------------
    for dimension in STUDENT_SEGMENT_DIMENSIONS:
        for label, row in sorted((dimensions.get(dimension) or {}).items()):
            if not _fires(dimension, row):
                continue
            out.append(
                Recommendation(
                    school=school,
                    audience=student,
                    audience_role=Audience.STUDENT,
                    product="O2",
                    rule_id="O2.segment_cognitive_gap",
                    scope=f"{dimension}={label}",
                    confidence=Confidence(
                        row.get("confidence") or Confidence.EXPLORATORY
                    ),
                    evidence={
                        **_segment_evidence(dimension, label, row, overall),
                        "rule": (
                            "relative_contrast <= "
                            f"{segments_mod.RELATIVE_CONTRAST_GATE[dimension]} "
                            f"ve n_answers >= "
                            f"{segments_mod.MIN_ANSWERS_PER_SEGMENT} "
                            "(SEGMENT-CIKTI.md §3)"
                        ),
                    },
                    computed_at=now_ms,
                    expires_at=now_ms + EXPIRY_SEGMENT_DAYS * clock.DAY_MS,
                    limitation=limitation,
                )
            )

    # --- O2.segment_trap_prone --------------------------------------------
    trap = (dimensions.get("dikkat_tuzagi") or {}).get("var")
    if trap and _fires("dikkat_tuzagi", trap):
        out.append(
            Recommendation(
                school=school,
                audience=student,
                audience_role=Audience.STUDENT,
                product="O2",
                rule_id="O2.segment_trap_prone",
                scope="dikkat_tuzagi=var",
                confidence=Confidence(
                    trap.get("confidence") or Confidence.EXPLORATORY
                ),
                evidence={
                    **_segment_evidence("dikkat_tuzagi", "var", trap, overall),
                    "comparison": (
                        "aynı kohorttaki öğrencilerin tuzaklı sorulardaki "
                        "ortalama kontrastı"
                    ),
                    "rule": (
                        "relative_contrast <= "
                        f"{segments_mod.RELATIVE_CONTRAST_GATE['dikkat_tuzagi']} "
                        f"ve n_answers >= "
                        f"{segments_mod.MIN_ANSWERS_PER_SEGMENT} "
                        "(SEGMENT-CIKTI.md §3)"
                    ),
                },
                computed_at=now_ms,
                expires_at=now_ms + EXPIRY_SEGMENT_DAYS * clock.DAY_MS,
                limitation=(
                    limitation
                    + " Ayrıca ölçülen şey tuzak şıkkın SEÇİLMESİ değil, "
                    "tuzaklı sorulardaki doğruluktur: hangi şıkkın "
                    "işaretlendiği bu hesaba girmez."
                ),
            )
        )
    return out


def for_student_segments(
    school: str,
    student: str,
    segment_profile: dict[str, Any],
    now_ms: int,
) -> list[Recommendation]:
    """Yalnız segment kuralları — `for_student` çağrılmadan da kullanılabilir.

    Segmentasyon hattı, ZEKA'nın gece koşusundan **bağımsız** kosuyor olabilir
    (`src/segment/cli.py run --persist`). O durumda diğer modüllerin çıktısı
    elde yoktur; bu yüzey segment kurallarını tek başına üretir.
    """
    return _segment_student_rules(school, student, segment_profile, now_ms)


def for_class_segments(
    school: str,
    class_id: str,
    *,
    class_segments: dict[str, dict[str, dict[str, Any]]],
    class_teachers: list[str],
    now_ms: int,
    limitation: str = segments_mod.LIMITATION,
) -> list[Recommendation]:
    """`T3.segment_class_gap` — sınıfın topluca geride olduğu segment.

    **Öğrenci başına değil, sınıf başına** çağrılır: madde sınıf hakkındadır,
    `about` alanı boştur. Bu aynı zamanda mezuniyet temizliğinin bu satırı
    yanlışlıkla silmesini de engeller (`store.purge_departed` yalnız `about`
    dolu satırlara bakar) — bir sınıf kimliği `about`'a yazılsaydı her gece
    silinirdi.

    Alıcı: yalnız o sınıfa ders veren öğretmenler. Öğretmeni çözülemeyen bir
    madde **üretilmez** (`[T§5.3]` yetki kuralı).
    """
    out: list[Recommendation] = []
    if not class_teachers:
        return out
    for dimension, labels in sorted(class_segments.items()):
        for label, row in sorted(labels.items()):
            n_students = int(row.get("n_students") or 0)
            mean = row.get("mean_relative_contrast")
            if n_students < segments_mod.MIN_CLASS_STUDENTS or mean is None:
                continue
            if float(mean) > segments_mod.CLASS_RELATIVE_CONTRAST_GATE:
                continue
            for teacher in class_teachers:
                out.append(
                    Recommendation(
                        school=school,
                        audience=teacher,
                        audience_role=Audience.TEACHER,
                        product="T3",
                        rule_id="T3.segment_class_gap",
                        scope=f"{class_id}_{dimension}={label}",
                        confidence=Confidence.EXPLORATORY,
                        evidence={
                            "class": class_id,
                            "dimension": dimension,
                            "label": label,
                            "fact": _segment_fact(dimension, label),
                            "n_students": n_students,
                            "mean_relative_contrast": mean,
                            "sd_relative_contrast": row.get(
                                "sd_relative_contrast"
                            ),
                            "reading": "sınıf düzeyinde bilişsel segment boşluğu",
                            "rule": RULE_CATALOG["T3.segment_class_gap"][
                                "condition"
                            ],
                        },
                        computed_at=now_ms,
                        expires_at=now_ms + EXPIRY_SEGMENT_DAYS * clock.DAY_MS,
                        limitation=(
                            limitation
                            + " Sınıf ortalaması bireysel farkı gizler: "
                            "ortalamanın altında kalan öğrenci de vardır, "
                            "üstünde kalan da."
                        ),
                    )
                )
    return out


# ---------------------------------------------------------------------------
# Dış yüzey
# ---------------------------------------------------------------------------


def for_student(
    school: str,
    student: str,
    *,
    marks_profile: dict[str, Any],
    attendance_profile: dict[str, Any],
    submission_profile: dict[str, Any],
    study_profile: dict[str, Any],
    attention_items: list[AttentionItem],
    course_teachers: dict[str, list[str]],
    now_ms: int,
    segment_profile: dict[str, Any] | None = None,
) -> list[Recommendation]:
    """Bir öğrenci için tüm tavsiyeler.

    `attendance_profile` bugün doğrudan bir kurala girmez (devam tetikleyicisi
    `attention_items` üzerinden gelir); imzada duruyor çünkü kanıt objesine
    devam sayıları eklenecek ilk yer burasıdır ve çağıran taraf değişmesin.

    `segment_profile` **isteğe bağlıdır**: segmentasyon hattı koşmamış bir
    kurulumda `None` gelir ve SEG kuralları hiç üretilmez. Boş kart yerine
    hiç kart: `[T§3]` ilke 4.
    """
    del attendance_profile  # şimdilik yalnız attention üzerinden kullanılıyor
    out = _student_rules(
        school, student, marks_profile, study_profile, submission_profile, now_ms
    )
    if segment_profile:
        out.extend(
            _segment_student_rules(school, student, segment_profile, now_ms)
        )
    out.extend(
        _teacher_rules(
            school, student, marks_profile, attention_items, course_teachers, now_ms
        )
    )
    return out
