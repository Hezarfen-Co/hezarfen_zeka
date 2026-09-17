"""Rapor katmanının testleri.

Sınanan sözleşme kuralları (`docs/CIKTI-SOZLESMESI.md`, `docs/RAPORLAR.md`):

1. Dört rapor tipi de üretilir, üç biçimde.
2. **Dikkat listesi öğrenci raporuna sızmaz** — yapısal kapı testi.
3. Kanıtsız satır rapora girmez.
4. Kapatılmış ve süresi geçmiş satırlar görünmez.
5. Düşük güvende sayı yerine ibare görünür.
6. HTML dış bağımlılık içermez (ağ isteği yok).
7. CSV Türkçe karakterlerde bozulmaz (UTF-8 BOM).
8. Boş veride çökme yok; anlamlı boş rapor üretilir.

Testlerin **hiçbiri** ayakta bir veritabanı gerektirmez: biri fikstürden
hattı koşturur (`report/capture.py`), diğerleri sözlük satırlarıyla çalışır.
Konteyner varsa (`ZEKA_TEST_DB_URL`) gerçek veritabanı üzerinden koşan bir
entegrasyon testi de vardır; yoksa `skipUnless` ile atlanır.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import tempfile
import unittest
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Any

from src import cli
from src.compute import clock
from src.compute.model import Audience, Confidence, Recommendation, StudentSummary
from src.pipeline import run_school
from src.report import build as build_mod
from src.report import filters, load, render, text, writer
from src.report.capture import CapturingCaller
from src.report.gate import (
    SUMMARY_COLUMNS_STUDENT,
    ReportGateError,
    StaffBundle,
    StaffSummary,
    StudentFacingBundle,
    StudentFacingSummary,
    has_attention_field,
)
from src.report.reader import MemoryReader
from src.store import BridgeStore, RecordingCaller

from .fakes import NOW
DAY = clock.DAY_MS
SCHOOL = "demo-okul"

#: Öğrenci raporuna **hiçbir koşulda** girmemesi gereken metin.
GIZLI_OLGU = "GIZLI-DIKKAT-OLGUSU-son-30-gunde-4-odev"


# ---------------------------------------------------------------------------
# Sahte satırlar — beş tablonun bellekteki hâli
# ---------------------------------------------------------------------------


def summary_row(student: str = "ogrenci-a", **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "school": SCHOOL,
        "student": student,
        "marks": {
            "classes": ["9-A"],
            "courses": {
                "course-1": {
                    "course": "course-1",
                    "course_title": "Matematik",
                    "n_marks": 6,
                    "average": 42.5,
                    "trend": {"available": True, "dropped": True, "rising": False},
                    "placement": {
                        "band": "review",
                        "confidence": "stable",
                        "z": -1.8,
                        "class_average": 68.0,
                        "class_sd": 9.0,
                        "cohort_n": 12,
                    },
                },
                "course-2": {
                    "course": "course-2",
                    "course_title": "Fen Bilimleri",
                    "n_marks": 1,
                    "average": 55.0,
                    "trend": {"available": False},
                    # Kohort küçük: bant yok, güven yok.
                    "placement": {
                        "band": "insufficient_data",
                        "confidence": "none",
                        "z": None,
                        "class_average": None,
                        "cohort_n": 3,
                    },
                },
            },
        },
        "attendance": {"overall": {"rate": 0.82}, "courses": {}},
        "submission": {
            "overall": {
                "n": 12,
                "n_submitted": 9,
                "n_missing": 3,
                "on_time_rate_by_last_touch": 0.55,
                "late_rate": 0.22,
                "rates_suppressed": False,
            },
            "upcoming": [
                {"homework": "hw-1", "course": "course-1", "due_at": NOW + 2 * DAY}
            ],
        },
        "study": {
            "recent_28d": {
                "n_stints": 11,
                "active_days": 7,
                "total_focus_ms": 9_000_000,
                "regularity": 0.25,
                "regularity_suppressed": False,
            }
        },
        "attention": [
            {
                "trigger": "homework",
                "fact": GIZLI_OLGU,
                "evidence": {"missing": 4, "cohort_median": 1},
                "window_from": NOW - 30 * DAY,
                "window_to": NOW,
            }
        ],
        "confidence": "stable",
        "computed_at": NOW,
    }
    row.update(over)
    return row


def rec_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "school": SCHOOL,
        "audience": "ogrenci-a",
        "about": None,
        "audience_role": "student",
        "product": "O1",
        "course": "course-1",
        "rule_id": "O1.review_band",
        "rule_version": 1,
        "evidence": {
            "student_average": 42.5,
            "class_average": 68.0,
            "limitation": "Konu kırılımı yok.",
        },
        "confidence": "stable",
        "created_at": NOW - DAY,
        "expires_at": NOW + 7 * DAY,
        "retain_until": NOW + 30 * DAY,
    }
    row.update(over)
    return row


def seg_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "school": SCHOOL,
        "student": "ogrenci-a",
        "dimension": "bilissel_talep",
        "label": "analiz",
        "n_answers": 120,
        "contrast": -0.094,
        "confidence": "stable",
        "computed_at": NOW,
    }
    row.update(over)
    return row


def run_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "school": SCHOOL,
        "started_at": NOW - 3600_000,
        "finished_at": NOW,
        "status": "ok",
        "students_total": 2,
        "students_ok": 2,
        "students_failed": 0,
        "students_skipped": 0,
        "rows_written": 8,
        "budget_exceeded": False,
        "budget_ms": 60000,
        "pending_students": ["ogrenci-b"],
        "retain_until": NOW + 90 * DAY,
    }
    row.update(over)
    return row


def full_reader() -> MemoryReader:
    """Her kapıyı sınayan satır kümesi."""
    return MemoryReader(
        {
            "student_summary": [
                summary_row("ogrenci-a"),
                summary_row("ogrenci-b"),
            ],
            "recommendation": [
                rec_row(),
                # öğretmene giden dikkat maddesi
                rec_row(
                    audience="ogretmen-1",
                    audience_role="teacher",
                    about="ogrenci-a",
                    product="T4",
                    rule_id="T4.homework",
                    evidence={"missing": 4, "limitation": "Teslim anı yok."},
                ),
                rec_row(
                    audience="ogretmen-1",
                    audience_role="teacher",
                    about="ogrenci-b",
                    product="T3",
                    rule_id="T3.individual_gap",
                    evidence={"z": -1.9, "limitation": "Konu kırılımı yok."},
                ),
                # kapatılmış
                rec_row(
                    rule_id="O3.pattern",
                    product="O3",
                    dismissed_at=NOW - 3600_000,
                    dismissed_by="ogrenci-a",
                    evidence={"n_stints": 9, "limitation": "x"},
                ),
                # süresi geçmiş
                rec_row(
                    rule_id="O4.deadline",
                    product="O4",
                    expires_at=NOW - DAY,
                    evidence={"due_at": NOW - 2 * DAY, "limitation": "x"},
                ),
                # kanıtsız (yalnız limitation)
                rec_row(
                    rule_id="O2.segment_trap_prone",
                    product="O2",
                    evidence={"limitation": "yalnız sınır satırı"},
                ),
                # düşük güven
                rec_row(
                    rule_id="O2.segment_cognitive_gap",
                    product="O2",
                    confidence="none",
                    evidence={"relative_contrast": -0.09, "limitation": "x"},
                ),
            ],
            "student_segment_profile": [
                seg_row(),
                seg_row(label="hatirlama", contrast=0.03, confidence="exploratory"),
                # n<30: gösterilmez
                seg_row(
                    dimension="okuma_yuku",
                    label="yuksek",
                    n_answers=11,
                    confidence="none",
                ),
            ],
            "insight_run": [run_row()],
            "question_segment": [
                {
                    "school": SCHOOL,
                    "question": "exam_question:Q1",
                    "bilissel_talep": "analiz",
                    "dikkat_tuzagi": "var",
                    "okuma_yuku": "dusuk",
                    "confidence": "exploratory",
                    "rationale": "MODELIN-GEREKCESI",
                    "trap_choice": "CELDIRICI-B",
                    "computed_at": NOW,
                }
            ],
        }
    )


def build_report(kind: str, *, reader: MemoryReader | None = None, **kw: Any):
    reader = reader or full_reader()
    bundle = asyncio.run(
        load.load_bundle(reader, SCHOOL, kind, now_ms=NOW, **kw)
    )
    return build_mod.build(kind, bundle)


def all_text(report) -> str:
    """Raporun üç biçimdeki bütün metni — sızıntı testleri için."""
    parts = [render.to_json(report), render.to_html(report)]
    parts += [body for _, body in render.csv_tables(report)]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 1) Dört rapor, üç biçim
# ---------------------------------------------------------------------------


class DortRaporUretilir(unittest.TestCase):
    def test_dort_tip_de_uretilir(self):
        for kind, kw in (
            ("okul", {}),
            ("ogretmen", {"teacher": "ogretmen-1"}),
            ("ogrenci", {"student": "ogrenci-a"}),
            ("ham", {}),
        ):
            with self.subTest(kind=kind):
                report = build_report(kind, **kw)
                self.assertEqual(report.kind, kind)
                self.assertFalse(report.empty)
                self.assertTrue(report.sections)
                self.assertTrue(report.notes)

    def test_uc_bicim_de_yazilir(self):
        report = build_report("okul")
        with tempfile.TemporaryDirectory() as tmp:
            for fmt in ("json", "html", "csv"):
                paths = writer.write(report, tmp, fmt)
                self.assertTrue(paths)
                for path in paths:
                    self.assertTrue(path.exists())
                    self.assertGreater(path.stat().st_size, 0)
                    # Ad öngörülebilir ve tarihli.
                    self.assertIn("2023-11-14", path.name)
                    self.assertTrue(path.name.startswith(SCHOOL))

    def test_json_sozlesme_alanlarini_korur(self):
        payload = json.loads(render.to_json(build_report("ham")))
        tables = payload["sections"][0]["data"]
        self.assertEqual(
            sorted(tables),
            [
                "insight_run",
                "question_segment",
                "recommendation",
                "student_segment_profile",
                "student_summary",
                "unavailable_rules",
            ],
        )
        self.assertEqual(payload["report"]["school"], SCHOOL)

    def test_ogretmen_raporu_teacher_ister(self):
        with self.assertRaises(ValueError):
            asyncio.run(load.load_bundle(full_reader(), SCHOOL, "ogretmen", now_ms=NOW))

    def test_ogrenci_raporu_about_ister(self):
        with self.assertRaises(ValueError):
            asyncio.run(load.load_bundle(full_reader(), SCHOOL, "ogrenci", now_ms=NOW))


# ---------------------------------------------------------------------------
# 2) YAPISAL KAPI — dikkat listesi öğrenci raporuna giremez
# ---------------------------------------------------------------------------


class DikkatListesiKapisi(unittest.TestCase):
    """Kapı bir filtre değil, bir tip kısıtıdır."""

    def test_ogrenci_tipinde_attention_alani_yok(self):
        self.assertFalse(has_attention_field(StudentFacingSummary))
        self.assertTrue(has_attention_field(StaffSummary))
        names = {f.name for f in dataclass_fields(StudentFacingSummary)}
        self.assertNotIn("attention", names)

    def test_iki_tip_arasinda_kalitim_yok(self):
        # Kalıtım olsaydı isinstance denetimi personel demetini geçirirdi.
        self.assertFalse(issubclass(StaffSummary, StudentFacingSummary))
        self.assertFalse(issubclass(StudentFacingSummary, StaffSummary))
        self.assertFalse(issubclass(StaffBundle, StudentFacingBundle))

    def test_ogrenci_kurucusu_personel_demetini_reddeder(self):
        staff = StaffBundle(school=SCHOOL, kind="okul", generated_at=NOW)
        with self.assertRaises(ReportGateError):
            build_mod.build_student_report(staff)
        # ReportGateError bir TypeError'dır: çağıran taraf da yakalayabilir.
        self.assertTrue(issubclass(ReportGateError, TypeError))

    def test_personel_kurucusu_ogrenci_demetini_reddeder(self):
        facing = StudentFacingBundle(
            school=SCHOOL, student="ogrenci-a", generated_at=NOW
        )
        for builder in (
            build_mod.build_school_report,
            build_mod.build_teacher_report,
            build_mod.build_raw_report,
        ):
            with self.subTest(builder=builder.__name__):
                with self.assertRaises(ReportGateError):
                    builder(facing)

    def test_bellek_okuyucusu_da_sutun_izdusumunu_uygular(self):
        reader = full_reader()
        rows = asyncio.run(
            reader.summaries(
                SCHOOL, columns=SUMMARY_COLUMNS_STUDENT, student="ogrenci-a"
            )
        )
        self.assertEqual(len(rows), 1)
        self.assertNotIn("attention", rows[0])
        # Okuma sütun listesi dikkat listesini HİÇ istemez: sızıntı kapısı
        # yalnız rapor kurucusunda değil, okuma sözleşmesinde de duruyor.
        self.assertNotIn("attention", " ".join(SUMMARY_COLUMNS_STUDENT))

    def test_ogrenci_raporunun_hicbir_biciminde_dikkat_maddesi_yok(self):
        report = build_report("ogrenci", student="ogrenci-a")
        blob = all_text(report)
        self.assertNotIn(GIZLI_OLGU, blob)
        self.assertNotIn("attention", blob)
        self.assertNotIn("T4.", blob)
        # Başka bir öğrencinin kimliği de girmez (`about` sızıntısı).
        self.assertNotIn("ogrenci-b", blob)

    def test_personel_raporunda_dikkat_maddesi_gorunur(self):
        """Kapı tek yönlüdür: öğretmen ve yönetim listeyi görmelidir."""
        for kind, kw in (("okul", {}), ("ogretmen", {"teacher": "ogretmen-1"})):
            with self.subTest(kind=kind):
                self.assertIn(GIZLI_OLGU, all_text(build_report(kind, **kw)))


# ---------------------------------------------------------------------------
# 3) Kanıt, kapatma, süre kapıları
# ---------------------------------------------------------------------------


class GorunurlukKapilari(unittest.TestCase):
    def test_kanitsiz_satir_rapora_girmez(self):
        blob = all_text(build_report("ogrenci", student="ogrenci-a"))
        self.assertNotIn("O2.segment_trap_prone", blob)
        self.assertFalse(
            filters.has_evidence(rec_row(evidence={"limitation": "yalnız sınır"}))
        )

    def test_kapatilmis_satir_gorunmez(self):
        blob = all_text(build_report("ogrenci", student="ogrenci-a"))
        self.assertNotIn("O3.pattern", blob)

    def test_suresi_gecmis_satir_gorunmez(self):
        blob = all_text(build_report("ogrenci", student="ogrenci-a"))
        self.assertNotIn("O4.deadline", blob)

    def test_expires_at_yoksa_gosterilmez(self):
        row = rec_row()
        row.pop("expires_at")
        self.assertTrue(filters.is_expired(row, NOW))

    def test_dismissed_at_none_metni_kapatma_sayilmaz(self):
        self.assertFalse(filters.is_dismissed(rec_row(dismissed_at="NONE")))
        self.assertTrue(filters.is_dismissed(rec_row(dismissed_at=NOW - 1)))

    def test_gecerli_satir_kalir(self):
        report = build_report("ogrenci", student="ogrenci-a")
        blob = all_text(report)
        self.assertIn("O1.review_band", blob)

    def test_ham_cikti_da_kapilardan_gecer(self):
        payload = json.loads(render.to_json(build_report("ham")))
        rules = {
            r["rule_id"] for r in payload["sections"][0]["data"]["recommendation"]
        }
        self.assertNotIn("O3.pattern", rules)  # kapatılmış
        self.assertNotIn("O4.deadline", rules)  # süresi geçmiş
        self.assertNotIn("O2.segment_trap_prone", rules)  # kanıtsız

    def test_ham_cikti_soru_ipucu_tasimaz(self):
        blob = all_text(build_report("ham"))
        self.assertNotIn("CELDIRICI-B", blob)
        self.assertNotIn("MODELIN-GEREKCESI", blob)


# ---------------------------------------------------------------------------
# 4) Güven kademesi
# ---------------------------------------------------------------------------


class GuvenIbaresi(unittest.TestCase):
    def test_dusuk_guvende_sayi_yerine_ibare(self):
        cell = text.measure(0.41, "none")
        self.assertIsNone(cell["value"])
        self.assertEqual(cell["display"], text.LOW_CONFIDENCE_TEXT)
        self.assertNotIn("0,41", cell["display"])

    def test_on_bulgu_eki(self):
        cell = text.measure(0.41, "exploratory", digits=2)
        self.assertIn(text.EXPLORATORY_SUFFIX, cell["display"])
        self.assertIn("0,41", cell["display"])

    def test_raporda_dusuk_guvenli_hucre_ibare_gosterir(self):
        report = build_report("ogrenci", student="ogrenci-a")
        dersler = next(t for t in report.tables() if t.id == "dersler")
        fen = next(r for r in dersler.rows if r["course"] == "Fen Bilimleri")
        # Kohort küçük → şube ortalaması gösterilemez.
        self.assertEqual(fen["class_average"]["display"], text.LOW_CONFIDENCE_TEXT)
        self.assertIsNone(fen["class_average"]["value"])
        # Öğrencinin kendi ortalaması da tek nota dayanıyor → ibare.
        self.assertEqual(fen["average"]["display"], text.LOW_CONFIDENCE_TEXT)

    def test_dusuk_guvenli_tavsiye_kartinda_sayi_gosterilmez(self):
        reader = MemoryReader(
            {
                "student_summary": [summary_row("ogrenci-a")],
                "recommendation": [
                    rec_row(
                        rule_id="O2.segment_cognitive_gap",
                        confidence="none",
                        evidence={"relative_contrast": -0.09876, "limitation": "x"},
                    )
                ],
            }
        )
        report = build_report("ogrenci", reader=reader, student="ogrenci-a")
        cards = next(s for s in report.sections if getattr(s, "id", "") == "tavsiyeler")
        olgu = cards.items[0]["why"][0]
        self.assertEqual(olgu["label"], "Olgu")
        self.assertIn(text.LOW_CONFIDENCE_TEXT, olgu["text"])
        self.assertNotIn("0,09876", olgu["text"])
        self.assertNotIn("-0.09876", render.to_html(report))

    def test_bes_bolumlu_neden_her_kartta_var(self):
        report = build_report("ogretmen", teacher="ogretmen-1")
        cards = next(s for s in report.sections if getattr(s, "id", "") == "tavsiyeler")
        self.assertTrue(cards.items)
        for item in cards.items:
            labels = [p["label"] for p in item["why"]]
            self.assertEqual(
                labels, ["Olgu", "Karşılaştırma", "Kural", "Sınır", "Tarih"]
            )
            # Sınır satırı boş olamaz.
            self.assertNotEqual(item["why"][3]["text"], "—")


# ---------------------------------------------------------------------------
# 5) Segment: karşıtlık, ham doğruluk değil
# ---------------------------------------------------------------------------


class SegmentKarsitlik(unittest.TestCase):
    def test_ham_dogruluk_hic_okunmaz(self):
        blob = all_text(build_report("ogrenci", student="ogrenci-a"))
        self.assertNotIn("accuracy", blob)
        self.assertNotIn("overall_accuracy", blob)

    def test_karsitlik_cumlesi_kendi_duzeyine_gore(self):
        sentence = text.contrast_sentence(seg_row())
        self.assertIn("kendi genel düzeyinin", sentence)
        self.assertIn("altında", sentence)

    def test_guven_yoksa_segment_satiri_gorunmez(self):
        report = build_report("ogrenci", student="ogrenci-a")
        segment = next(t for t in report.tables() if t.id == "segment")
        etiketler = {row["label"] for row in segment.rows}
        self.assertIn("analiz", etiketler)
        self.assertNotIn("yüksek", etiketler)  # n=11, confidence=none


# ---------------------------------------------------------------------------
# 6) Sıralama yok
# ---------------------------------------------------------------------------


class SiralamaYok(unittest.TestCase):
    def test_dikkat_listesi_alfabetik(self):
        report = build_report("okul")
        table = next(t for t in report.tables() if t.id == "dikkat_listesi")
        students = [row["student"] for row in table.rows]
        self.assertEqual(students, sorted(students))

    def test_sube_ders_kirilimi_alfabetik(self):
        report = build_report("okul")
        table = next(t for t in report.tables() if t.id == "sube_ders")
        keys = [(r["class"], r["course"]) for r in table.rows]
        self.assertEqual(keys, sorted(keys))

    def test_siralama_notu_her_raporda(self):
        for kind, kw in (("okul", {}), ("ogretmen", {"teacher": "ogretmen-1"})):
            with self.subTest(kind=kind):
                report = build_report(kind, **kw)
                self.assertTrue(any("sıralama yoktur" in n for n in report.notes))


# ---------------------------------------------------------------------------
# 7) HTML ve CSV
# ---------------------------------------------------------------------------


class HtmlBicimi(unittest.TestCase):
    YASAK = (
        "http://",
        "https://",
        "<script",
        "<iframe",
        "<link",
        "src=",
        "@import",
        "url(",
        "//cdn",
    )

    def test_dis_bagimlilik_yok(self):
        for kind, kw in (
            ("okul", {}),
            ("ogretmen", {"teacher": "ogretmen-1"}),
            ("ogrenci", {"student": "ogrenci-a"}),
            ("ham", {}),
        ):
            html = render.to_html(build_report(kind, **kw))
            for needle in self.YASAK:
                with self.subTest(kind=kind, needle=needle):
                    self.assertNotIn(needle, html.lower())

    def test_tek_dosya_ve_gomulu_stil(self):
        html = render.to_html(build_report("okul"))
        self.assertIn("<style>", html)
        self.assertIn("@media print", html)
        self.assertTrue(html.startswith("<!DOCTYPE html>"))

    def test_html_kacisi_yapilir(self):
        reader = MemoryReader(
            {
                "student_summary": [
                    summary_row("<script>alert(1)</script>"),
                ],
                "insight_run": [run_row()],
            }
        )
        html = render.to_html(build_report("okul", reader=reader))
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)


class CsvBicimi(unittest.TestCase):
    def test_turkce_karakter_bozulmaz(self):
        report = build_report("okul")
        with tempfile.TemporaryDirectory() as tmp:
            paths = writer.write(report, tmp, "csv")
            names = [p.name for p in paths]
            self.assertTrue(any("sube_ders" in n for n in names))
            target = next(p for p in paths if "sube_ders" in p.name)
            raw = target.read_bytes()
            # Excel uyumu için BOM.
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            body = raw.decode("utf-8-sig")
            self.assertIn("Şube", body)
            self.assertIn("Öğrenci", body)
            rows = list(
                csv.reader(io.StringIO(body), delimiter=render.CSV_DELIMITER)
            )
            self.assertEqual(rows[0][0], "Şube")
            self.assertGreater(len(rows), 1)

    def test_olcu_hucresi_metne_doner(self):
        report = build_report("ogrenci", student="ogrenci-a")
        bodies = dict(render.csv_tables(report))
        self.assertIn("dersler", bodies)
        self.assertIn(text.LOW_CONFIDENCE_TEXT, bodies["dersler"])
        self.assertNotIn("'value':", bodies["dersler"])

    def test_yalniz_tablolar_csv_olur(self):
        report = build_report("ogretmen", teacher="ogretmen-1")
        ids = {section_id for section_id, _ in render.csv_tables(report)}
        self.assertIn("isi_haritasi", ids)
        self.assertNotIn("tavsiyeler", ids)  # kart bölümü CSV'ye dönmez
        self.assertNotIn("uretilemeyenler", ids)


# ---------------------------------------------------------------------------
# 8) Boş veri
# ---------------------------------------------------------------------------


class BosVeri(unittest.TestCase):
    def test_hicbir_satir_yokken_cokmez(self):
        reader = MemoryReader({})
        for kind, kw in (
            ("okul", {}),
            ("ogretmen", {"teacher": "ogretmen-1"}),
            ("ogrenci", {"student": "ogrenci-a"}),
            ("ham", {}),
        ):
            with self.subTest(kind=kind):
                report = build_report(kind, reader=reader, **kw)
                self.assertTrue(report.empty)
                self.assertTrue(any("boş üretildi" in n for n in report.notes))
                html = render.to_html(report)
                self.assertIn("boş", html)
                json.loads(render.to_json(report))

    def test_bos_raporda_dosyalar_yine_yazilir(self):
        report = build_report("okul", reader=MemoryReader({}))
        with tempfile.TemporaryDirectory() as tmp:
            for fmt in ("json", "html", "csv"):
                paths = writer.write(report, tmp, fmt)
                self.assertTrue(paths, f"{fmt}: dosya üretilmedi")

    def test_bos_ogrenci_raporu_ozet_yoksa_da_kurulur(self):
        reader = MemoryReader({"recommendation": [rec_row()]})
        report = build_report("ogrenci", reader=reader, student="ogrenci-a")
        self.assertFalse(report.empty)
        self.assertIn("O1.review_band", all_text(report))


# ---------------------------------------------------------------------------
# 9) Fikstür yolu — gerçek hat, veritabanı yok
# ---------------------------------------------------------------------------


class FiksturYolu(unittest.TestCase):
    """`pipeline` → `store` → `CapturingCaller` → rapor."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parent.parent / "fixtures" / "demo"
        from src.source import FileSource

        caller = CapturingCaller()
        asyncio.run(
            run_school(
                FileSource(root),
                BridgeStore(caller).store_for(SCHOOL),
                SCHOOL,
                now_ms=NOW,
                budget_ms=60_000,
            )
        )
        cls.caller = caller
        cls.tables = caller.as_tables()
        cls.reader = caller.as_reader()

    def test_hat_satir_yazdi(self):
        self.assertIn("student_summary", self.tables)
        self.assertIn("insight_run", self.tables)
        self.assertGreater(len(self.tables["student_summary"]), 0)

    def test_dort_rapor_fiksturden_uretilir(self):
        student = self.tables["student_summary"][0]["student"]
        for kind, kw in (
            ("okul", {}),
            ("ogrenci", {"student": student}),
            ("ham", {}),
        ):
            with self.subTest(kind=kind):
                report = build_report(kind, reader=self.reader, **kw)
                self.assertFalse(report.empty)
                self.assertTrue(render.to_html(report))

    def test_cli_report_komutu_dosya_yazar(self):
        fixtures = str(Path(__file__).resolve().parent.parent / "fixtures" / "demo")
        with tempfile.TemporaryDirectory() as tmp:
            code = cli.main(
                [
                    "report",
                    "--school",
                    SCHOOL,
                    "--type",
                    "okul",
                    "--format",
                    "html",
                    "--out",
                    tmp,
                    "--fixtures",
                    fixtures,
                    "--now",
                    str(NOW),
                ]
            )
            self.assertEqual(code, 0)
            files = list(Path(tmp).glob("*.html"))
            self.assertEqual(len(files), 1)
            self.assertIn("2023-11-14", files[0].name)


# ---------------------------------------------------------------------------
# 10) Gerçek veritabanı — konteyner varsa
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    unittest.main()
