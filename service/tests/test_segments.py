"""Segment profili, segment kurallari ve depoya yazim testleri.

Dort kume:

* **Sozlesme** -- `compute/segments.py` ile `segment/rubric.py` ayni boyut
  kumesini mi tasiyor (iki taraf sessizce ayrilmasin).
* **Hesap** -- kontrast, guven kademesi, referans kontrast, sinif toplama.
* **Kural** -- guven kapisi, kanitsiz uretmeme, ham dogrulukla ATESLEMEME.
* **Yazim** -- satir bicimi, saklama suresi, supurme, koprunun donusumu.

Entegrasyon (gercek SurrealDB) kismi `tests/test_store.py` icindedir; burasi
veritabani GEREKTIRMEZ.
"""

from __future__ import annotations

import asyncio
import unittest

from src.compute import segments as seg
from src.compute.model import (
    Confidence,
    QuestionSegment,
    StudentSegmentProfile,
)
from src.compute.recommend import (
    RULE_CATALOG,
    for_class_segments,
    for_student,
    for_student_segments,
)
from src.segment import persist as persist_mod
from src.segment.labelers import LabelBatch
from src.segment.rubric import (
    DIMENSIONS,
    EXPERIMENTAL_DIMENSIONS,
    PRODUCTION_DIMENSIONS,
)
from src.segment.schema import CallUsage, DimensionResult, ItemSegmentation
from src.store import (
    RETENTION_DAYS,
    CollectingClient,
    Store,
    load_schema_text,
    question_segment_row,
    split_statements,
    student_segment_profile_row,
)

NOW = 1_699_963_200_000
DAY = 86_400_000


def profile(
    label: str,
    *,
    dimension: str = "bilissel_talep",
    n: int = 200,
    accuracy: float = 0.4,
    overall: float = 0.6,
    student: str = "s1",
) -> StudentSegmentProfile:
    return StudentSegmentProfile(
        school="okul-a",
        student=student,
        dimension=dimension,
        label=label,
        n_answers=n,
        n_correct=round(n * accuracy),
        overall_n_answers=1000,
        overall_accuracy=overall,
        computed_at=NOW,
        confidence=seg.confidence_for(n),
    )


def reference_for(dimension: str, label: str, mean: float) -> dict:
    return {dimension: {label: {"mean_contrast": mean, "n_students": 40}}}


# ===========================================================================
# SOZLESME
# ===========================================================================


class TestRubricUyumu(unittest.TestCase):
    """`compute/` rubrigi ice aktarmaz; sapma burada yakalanir."""

    def test_uretim_boyutlari_ayni(self) -> None:
        self.assertEqual(
            sorted(seg.PRODUCTION_DIMENSIONS), sorted(PRODUCTION_DIMENSIONS)
        )

    def test_deneysel_boyutlar_ayni(self) -> None:
        self.assertEqual(
            sorted(seg.EXPERIMENTAL_DIMENSIONS), sorted(EXPERIMENTAL_DIMENSIONS)
        )

    def test_etiket_kumeleri_ayni(self) -> None:
        for name, labels in {
            **seg.PRODUCTION_DIMENSIONS,
            **seg.EXPERIMENTAL_DIMENSIONS,
        }.items():
            self.assertEqual(tuple(labels), DIMENSIONS[name].labels, name)

    def test_deneysel_boyut_asagi_akisa_girmez(self) -> None:
        for name in seg.EXPERIMENTAL_DIMENSIONS:
            self.assertNotIn(name, seg.DOWNSTREAM_DIMENSIONS)


# ===========================================================================
# HESAP
# ===========================================================================


class TestKontrast(unittest.TestCase):
    def test_kontrast_genel_dogrulugu_cikarir(self) -> None:
        p = profile("analiz", accuracy=0.40, overall=0.60)
        self.assertAlmostEqual(p.accuracy, 0.40, places=4)
        self.assertAlmostEqual(p.contrast, -0.20, places=4)

    def test_iyi_ogrencinin_yuksek_dogrulugu_pozitif_kontrast_demek_degil(self) -> None:
        """Ayni kontrast, cok farkli iki genel duzeyde ayni seyi soyler."""
        zayif = profile("analiz", accuracy=0.20, overall=0.30)
        iyi = profile("analiz", accuracy=0.70, overall=0.80)
        self.assertAlmostEqual(zayif.contrast, iyi.contrast, places=4)
        self.assertGreater(iyi.accuracy, zayif.accuracy)

    def test_bos_cevap_profil_uretmez(self) -> None:
        self.assertEqual(seg.student_profiles("o", "s", [], {}, NOW), [])

    def test_etiketsiz_soru_paydaya_girmez(self) -> None:
        labels = {"q1": {"bilissel_talep": "analiz"}}
        rows = seg.student_profiles(
            "o", "s", [("q1", 1), ("q2", 0), ("q3", 0)], labels, NOW
        )
        self.assertEqual(len(rows), 1)
        # q2/q3 etiketsiz: ne segmente ne de genel paydaya girer.
        self.assertEqual(rows[0].overall_n_answers, 1)
        self.assertEqual(rows[0].n_answers, 1)

    def test_n_sifir_profil_kurulamaz(self) -> None:
        with self.assertRaises(ValueError):
            StudentSegmentProfile(
                school="o", student="s", dimension="d", label="l",
                n_answers=0, n_correct=0, overall_n_answers=10,
                overall_accuracy=0.5, computed_at=NOW,
            )

    def test_guven_kademesi_esikleri(self) -> None:
        self.assertEqual(seg.confidence_for(29), Confidence.NONE)
        self.assertEqual(seg.confidence_for(30), Confidence.EXPLORATORY)
        self.assertEqual(seg.confidence_for(100), Confidence.STABLE)


class TestReferans(unittest.TestCase):
    def test_referans_ortalamasi_ve_gorelilik(self) -> None:
        rows = [
            profile("analiz", accuracy=0.30, overall=0.50, student=f"s{i}")
            for i in range(10)
        ]
        reference = seg.reference_contrasts(rows)
        self.assertAlmostEqual(
            reference["bilissel_talep"]["analiz"]["mean_contrast"], -0.20, places=3
        )
        # Kohortla ayni olan ogrencinin GORELI kontrasti sifirdir.
        self.assertAlmostEqual(
            seg.relative_contrast(rows[0], reference), 0.0, places=3
        )

    def test_kucuk_n_referansa_girmez(self) -> None:
        rows = [profile("analiz", n=10, accuracy=0.0, overall=0.9)]
        self.assertEqual(seg.reference_contrasts(rows), {})

    def test_referans_yoksa_goreli_kontrast_yok(self) -> None:
        self.assertIsNone(seg.relative_contrast(profile("analiz"), {}))


class TestSinifToplama(unittest.TestCase):
    def test_sinif_ortalamasi_goreli_kontrastlardan_hesaplanir(self) -> None:
        reference = reference_for("bilissel_talep", "analiz", -0.10)
        rows = [
            profile("analiz", accuracy=0.35, overall=0.60, student=f"s{i}")
            for i in range(9)
        ]
        stats = seg.class_contrasts({"9-A": rows}, reference)
        row = stats["9-A"]["bilissel_talep"]["analiz"]
        self.assertEqual(row["n_students"], 9)
        # kontrast -0,25 ; referans -0,10 -> goreli -0,15
        self.assertAlmostEqual(row["mean_relative_contrast"], -0.15, places=3)

    def test_kapinin_altindaki_ogrenci_sinif_ortalamasina_girmez(self) -> None:
        reference = reference_for("bilissel_talep", "analiz", -0.10)
        rows = [profile("analiz", n=10, student=f"s{i}") for i in range(9)]
        self.assertEqual(seg.class_contrasts({"9-A": rows}, reference), {})


# ===========================================================================
# KURAL
# ===========================================================================


class TestSegmentKurallari(unittest.TestCase):
    def setUp(self) -> None:
        self.reference = reference_for("bilissel_talep", "analiz", -0.05)

    def _payload(self, **over):
        rows = [profile("analiz", **over)]
        return seg.profile_payload(rows, self.reference)

    def test_katalogda_uc_yeni_kural_var(self) -> None:
        for rule_id in (
            "O2.segment_cognitive_gap",
            "O2.segment_trap_prone",
            "T3.segment_class_gap",
        ):
            self.assertIn(rule_id, RULE_CATALOG)
            self.assertTrue(RULE_CATALOG[rule_id]["condition"])
            self.assertTrue(RULE_CATALOG[rule_id]["source"])

    def test_belirgin_sapma_kural_uretir(self) -> None:
        recs = for_student_segments(
            "okul-a", "s1", self._payload(accuracy=0.30, overall=0.60), NOW
        )
        self.assertEqual([r.rule_id for r in recs], ["O2.segment_cognitive_gap"])
        self.assertEqual(recs[0].product, "O2")
        self.assertEqual(str(recs[0].audience_role), "student")

    def test_guven_kapisi_altinda_kural_uretilmez(self) -> None:
        """Ayni sapma, az cevapla: kural ATESLEMEZ."""
        az = seg.MIN_ANSWERS_PER_SEGMENT - 1
        recs = for_student_segments(
            "okul-a", "s1", self._payload(n=az, accuracy=0.30, overall=0.60), NOW
        )
        self.assertEqual(recs, [])

    def test_ham_dogruluk_tek_basina_atesLEMEZ(self) -> None:
        """Genel olarak dusuk ama segmenti kohortla ayni olan ogrenci.

        Ham dogrulugu %25 -- cok dusuk. Kontrasti kohort ortalamasiyla ayni,
        dolayisiyla bu segment hakkinda soylenecek bir sey YOK.
        """
        recs = for_student_segments(
            "okul-a", "s1", self._payload(accuracy=0.25, overall=0.30), NOW
        )
        self.assertEqual(recs, [])

    def test_referans_yoksa_kural_uretilmez(self) -> None:
        payload = seg.profile_payload([profile("analiz", accuracy=0.1)], {})
        self.assertEqual(for_student_segments("okul-a", "s1", payload, NOW), [])

    def test_uretilen_her_satir_kanit_ve_sinir_tasir(self) -> None:
        recs = for_student_segments(
            "okul-a", "s1", self._payload(accuracy=0.30, overall=0.60), NOW
        )
        for rec in recs:
            payload = {k: v for k, v in rec.evidence.items() if k != "limitation"}
            self.assertTrue(payload)
            self.assertIn("relative_contrast", rec.evidence)
            self.assertIn("n_answers", rec.evidence)
            self.assertTrue(rec.limitation)

    def test_tuzak_kurali_ayri_kimlik_uretir(self) -> None:
        reference = reference_for("dikkat_tuzagi", "var", -0.01)
        rows = [profile("var", dimension="dikkat_tuzagi", accuracy=0.35, overall=0.50)]
        recs = for_student_segments(
            "okul-a", "s1", seg.profile_payload(rows, reference), NOW
        )
        self.assertEqual([r.rule_id for r in recs], ["O2.segment_trap_prone"])
        self.assertIn("comparison", recs[0].evidence)

    def test_iki_farkli_segment_iki_ayri_kayit_anahtari(self) -> None:
        """Ayni kural iki segmentte ateslerse satirlar birbirini EZMEZ."""
        reference = {
            "bilissel_talep": {"analiz": {"mean_contrast": -0.05, "n_students": 40}},
            "okuma_yuku": {"yuksek": {"mean_contrast": -0.05, "n_students": 40}},
        }
        rows = [
            profile("analiz", accuracy=0.30, overall=0.60),
            profile("yuksek", dimension="okuma_yuku", accuracy=0.30, overall=0.60),
        ]
        recs = for_student_segments(
            "okul-a", "s1", seg.profile_payload(rows, reference), NOW
        )
        self.assertEqual(len(recs), 2)
        self.assertEqual(len({r.record_key() for r in recs}), 2)

    def test_segment_profili_yoksa_for_student_degismez(self) -> None:
        """Segmentasyon kosmamis kurulumda davranis AYNI kalir."""
        ortak = dict(
            marks_profile={}, attendance_profile={}, submission_profile={},
            study_profile={}, attention_items=[], course_teachers={}, now_ms=NOW,
        )
        self.assertEqual(for_student("okul-a", "s1", **ortak), [])
        self.assertEqual(
            for_student("okul-a", "s1", segment_profile=None, **ortak), []
        )


class TestSinifKurali(unittest.TestCase):
    def _stats(self, mean: float, n_students: int):
        return {
            "bilissel_talep": {
                "analiz": {
                    "n_students": n_students,
                    "mean_relative_contrast": mean,
                    "sd_relative_contrast": 0.02,
                }
            }
        }

    def test_kucuk_kohortta_uretilmez(self) -> None:
        recs = for_class_segments(
            "okul-a", "9-A",
            class_segments=self._stats(-0.20, seg.MIN_CLASS_STUDENTS - 1),
            class_teachers=["t1"], now_ms=NOW,
        )
        self.assertEqual(recs, [])

    def test_ogretmeni_cozulemeyen_madde_uretilmez(self) -> None:
        recs = for_class_segments(
            "okul-a", "9-A", class_segments=self._stats(-0.20, 20),
            class_teachers=[], now_ms=NOW,
        )
        self.assertEqual(recs, [])

    def test_esigi_gecen_sinif_ogretmene_madde_uretir(self) -> None:
        recs = for_class_segments(
            "okul-a", "9-A", class_segments=self._stats(-0.20, 20),
            class_teachers=["t1", "t2"], now_ms=NOW,
        )
        self.assertEqual(len(recs), 2)
        self.assertEqual({r.audience for r in recs}, {"t1", "t2"})
        self.assertEqual(recs[0].rule_id, "T3.segment_class_gap")
        self.assertEqual(str(recs[0].audience_role), "teacher")
        # Sinif kimligi `about` alanina YAZILMAZ: mezuniyet temizligi
        # `about` dolu satirlari siler, sinif kimligi oraya konsa her gece
        # silinirdi.
        self.assertIsNone(recs[0].about)
        self.assertEqual(recs[0].evidence["class"], "9-A")

    def test_esigin_ustundeki_sinif_icin_uretilmez(self) -> None:
        recs = for_class_segments(
            "okul-a", "9-A",
            class_segments=self._stats(seg.CLASS_RELATIVE_CONTRAST_GATE + 0.001, 20),
            class_teachers=["t1"], now_ms=NOW,
        )
        self.assertEqual(recs, [])


# ===========================================================================
# YAZIM
# ===========================================================================


def question_segment(**over) -> QuestionSegment:
    base = dict(
        school="okul-a",
        question="exam_question:Q1",
        exam="exam:E1",
        subject="subject:S1",
        labels={
            "bilissel_talep": "analiz",
            "adim_sayisi": "cok_adim",
            "dikkat_tuzagi": "var",
            "okuma_yuku": "yuksek",
        },
        confidences={
            "bilissel_talep": 0.9,
            "adim_sayisi": 0.5,
            "dikkat_tuzagi": 0.88,
            "okuma_yuku": 0.95,
        },
        rationale="Iki adimli cikarim ve uzun kok.",
        model="deepseek-flash",
        prompt_version="v1",
        variant="baseline",
        trap_choice="choice-3",
        downstream_dimensions=tuple(seg.PRODUCTION_DIMENSIONS),
        experimental_dimensions=tuple(seg.EXPERIMENTAL_DIMENSIONS),
        computed_at=NOW,
    )
    base.update(over)
    return QuestionSegment(**base)


class TestSemaMetni(unittest.TestCase):
    def test_iki_yeni_tablo_semada_tanimli(self) -> None:
        text = load_schema_text()
        for table in ("question_segment", "student_segment_profile"):
            self.assertIn(f"DEFINE TABLE IF NOT EXISTS {table} SCHEMAFULL;", text)

    def test_her_satir_alani_semada_var(self) -> None:
        """Satir uretecinin yazdigi her alan semada TANIMLI mi?"""
        statements = split_statements(load_schema_text())
        for table, row in (
            ("question_segment", question_segment_row(question_segment())),
            (
                "student_segment_profile",
                student_segment_profile_row(profile("analiz")),
            ),
        ):
            declared = {
                s.split("IF NOT EXISTS", 1)[1].split("ON", 1)[0].strip()
                for s in statements
                if s.startswith("DEFINE FIELD") and f" ON {table} " in s
            }
            self.assertTrue(declared, table)
            self.assertEqual(set(row) - declared, set(), table)

    def test_dizi_alanlarinda_yildiz_once_tanimlanir(self) -> None:
        """`.*` diziden SONRA gelirse ic anahtarlar sessizce duserdi."""
        text = load_schema_text()
        for name in ("experimental_dimensions", "downstream_dimensions"):
            star = text.index(f"{name}.*")
            plain = text.index(f"{name}", star + len(name) + 2)
            self.assertLess(star, plain, name)


class TestSatirBicimi(unittest.TestCase):
    def test_question_segment_saklama_suresi(self) -> None:
        row = question_segment_row(question_segment())
        self.assertEqual(
            row["retain_until"], NOW + RETENTION_DAYS["question_segment"] * DAY
        )

    def test_boyutlar_alan_adina_donusur(self) -> None:
        row = question_segment_row(question_segment())
        self.assertEqual(row["bilissel_talep"], "analiz")
        self.assertEqual(row["confidence_okuma_yuku"], 0.95)

    def test_deneysel_boyut_satirda_isaretli(self) -> None:
        row = question_segment_row(question_segment())
        self.assertEqual(row["experimental_dimensions"], ["adim_sayisi"])
        self.assertNotIn("adim_sayisi", row["downstream_dimensions"])

    def test_kanitsiz_ve_etiketsiz_satir_kurulamaz(self) -> None:
        with self.assertRaises(ValueError):
            question_segment(labels={})
        with self.assertRaises(ValueError):
            question_segment(rationale="")
        with self.assertRaises(ValueError):
            # Boyut var, o boyutun guveni yok -> sozlesme ihlali.
            question_segment(confidences={"bilissel_talep": 0.9})

    def test_profil_satiri_kontrast_tasir(self) -> None:
        row = student_segment_profile_row(
            profile("analiz", accuracy=0.4, overall=0.6)
        )
        self.assertAlmostEqual(row["contrast"], -0.2, places=4)
        self.assertAlmostEqual(row["overall_accuracy"], 0.6, places=4)
        self.assertEqual(
            row["retain_until"],
            NOW + RETENTION_DAYS["student_segment_profile"] * DAY,
        )


class TestYazim(unittest.IsolatedAsyncioTestCase):
    async def test_merge_kullanilir(self) -> None:
        """CONTENT, insan/baska kaynak alanlarini silerdi."""
        client = CollectingClient()
        store = Store(client)
        await store.write_question_segments([question_segment()])
        await store.write_segment_profiles([profile("analiz")])
        for sql, _ in client.statements:
            self.assertIn("MERGE", sql)
            self.assertIn("type::record(", sql)

    async def test_supurme_iki_yeni_tabloyu_da_gezer(self) -> None:
        client = CollectingClient()
        results = await Store(client).sweep(NOW)
        self.assertIn("question_segment", results)
        self.assertIn("student_segment_profile", results)
        tables = [sql.split()[1] for sql, _ in client.statements]
        self.assertIn("question_segment", tables)
        self.assertIn("student_segment_profile", tables)

    async def test_mezuniyet_temizligi_profili_siler_soruyu_silmez(self) -> None:
        client = CollectingClient()
        await Store(client).purge_departed("okul-a", ["kalan"])
        sql = client.statements[0][0]
        self.assertIn("DELETE student_segment_profile", sql)
        # Soru satiri kisisel veri DEGIL: mezuniyetle silinmez.
        self.assertNotIn("DELETE question_segment", sql)

    async def test_bos_liste_ifade_uretmez(self) -> None:
        client = CollectingClient()
        store = Store(client)
        report = await store.write_question_segments([])
        self.assertEqual(report.written, 0)
        self.assertEqual(client.statements, [])


# ===========================================================================
# KOPRU (segment -> depo)
# ===========================================================================


def item_segmentation(question_id: str, labels: dict[str, str]) -> ItemSegmentation:
    return ItemSegmentation(
        question_id=question_id,
        labels={
            name: DimensionResult(label=label, confidence=0.9)
            for name, label in labels.items()
        },
        trap_choice_index=1 if labels.get("dikkat_tuzagi") == "var" else None,
        trap_choice_text="B sikki" if labels.get("dikkat_tuzagi") == "var" else None,
        rationale="gerekce",
        prompt_version="v1",
        model="deepseek-flash",
        variant="baseline",
        usage=CallUsage(),
    )


ALL_LABELS = {
    "bilissel_talep": "analiz",
    "adim_sayisi": "tek_adim",
    "dikkat_tuzagi": "var",
    "okuma_yuku": "dusuk",
}

ITEMS = [
    {
        "question_id": "q1",
        "exam": "exam:E1",
        "subject": "subject:S1",
        "correct_choice_id": "c-dogru",
        "distractor_distribution": [
            {"choice_id": "c-dogru"},
            {"choice_id": "c-tuzak"},
            {"choice_id": "c-3"},
        ],
    },
    {
        "question_id": "q2",
        "exam": "exam:E1",
        "subject": "subject:S1",
        "correct_choice_id": "c-dogru2",
        "distractor_distribution": [{"choice_id": "c-dogru2"}, {"choice_id": "c-x"}],
    },
]


def batch() -> LabelBatch:
    b = LabelBatch(variant="baseline", prompt_version="v1", model="deepseek-flash")
    b.results = {
        "q1": item_segmentation("q1", ALL_LABELS),
        "q2": item_segmentation("q2", {**ALL_LABELS, "dikkat_tuzagi": "yok"}),
    }
    return b


class TestKopru(unittest.TestCase):
    def test_etiketler_soru_satirina_donusur(self) -> None:
        rows = persist_mod.question_segments(
            batch(), ITEMS, school="okul-a", now_ms=NOW
        )
        self.assertEqual(len(rows), 2)
        first = {r.question: r for r in rows}["q1"]
        self.assertEqual(first.labels["bilissel_talep"], "analiz")
        self.assertEqual(first.exam, "exam:E1")
        self.assertEqual(first.trap_choice, "c-tuzak")
        self.assertEqual(first.record_key(), "okul-a_q1")

    def test_tuzaksiz_soruda_tuzak_sik_bos(self) -> None:
        rows = {
            r.question: r
            for r in persist_mod.question_segments(
                batch(), ITEMS, school="okul-a", now_ms=NOW
            )
        }
        self.assertIsNone(rows["q2"].trap_choice)

    def test_etiketlenemeyen_madde_satir_uretmez(self) -> None:
        b = batch()
        b.failures = {"q3": "sema hatasi"}
        rows = persist_mod.question_segments(
            b, ITEMS, school="okul-a", now_ms=NOW
        )
        self.assertEqual({r.question for r in rows}, {"q1", "q2"})

    def test_ogrenci_profili_yalniz_uretim_boyutlarini_tasir(self) -> None:
        answers = [
            ("q1", "user:1", "c-dogru"),
            ("q2", "user:1", "c-x"),
            ("q1", "user:2", "c-tuzak"),
        ]
        profiles, matched = persist_mod.segment_profiles(
            batch(), answers, ITEMS, school="okul-a", now_ms=NOW
        )
        self.assertEqual(matched, 3)
        self.assertEqual(
            {p.dimension for p in profiles}, set(seg.PRODUCTION_DIMENSIONS)
        )
        self.assertNotIn("adim_sayisi", {p.dimension for p in profiles})

    def test_bos_birakilan_madde_paydaya_girmez(self) -> None:
        answers = [("q1", "user:1", None), ("q2", "user:1", "c-dogru2")]
        profiles, matched = persist_mod.segment_profiles(
            batch(), answers, ITEMS, school="okul-a", now_ms=NOW
        )
        self.assertEqual(matched, 1)
        self.assertTrue(all(p.overall_n_answers == 1 for p in profiles))

    def test_kuru_kosu_hicbir_sey_yazmaz(self) -> None:
        answers = [("q1", "user:1", "c-dogru")]
        report = asyncio.run(
            persist_mod.persist(
                batch(), ITEMS, answers, school="okul-a", now_ms=NOW, store=None
            )
        )
        self.assertTrue(report.dry_run)
        self.assertEqual(report.question_written, 0)
        self.assertEqual(report.profile_written, 0)
        self.assertEqual(report.question_rows, 2)

    def test_kohortta_belirgin_sapan_ogrenci_icin_tavsiye_de_yazilir(self) -> None:
        """Koprunun dordüncu isi: kural motorunu kosturmak.

        Kohort: 12 ogrenci tuzakli soruyu DOGRU, 1 ogrenci YANLIS yapiyor.
        Sapan ogrencinin goreli kontrasti esigi gecmeli ve tek bir
        `O2.segment_trap_prone` satiri uretilmeli.
        """
        gate = seg.MIN_ANSWERS_PER_SEGMENT
        b = LabelBatch(
            variant="baseline", prompt_version="v1", model="deepseek-flash"
        )
        items: list[dict] = []
        answers: list[tuple[str, str, str | None]] = []
        for i in range(2 * gate):
            qid = f"q{i}"
            tuzakli = i < gate
            b.results[qid] = item_segmentation(
                qid,
                {**ALL_LABELS, "dikkat_tuzagi": "var" if tuzakli else "yok"},
            )
            items.append(
                {
                    "question_id": qid,
                    "exam": "exam:E1",
                    "correct_choice_id": "dogru",
                    "distractor_distribution": [
                        {"choice_id": "dogru"},
                        {"choice_id": "tuzak"},
                    ],
                }
            )
            for s in range(13):
                sapan = s == 0 and tuzakli
                answers.append((qid, f"user:{s}", "tuzak" if sapan else "dogru"))

        client = CollectingClient()
        report = asyncio.run(
            persist_mod.persist(
                b, items, answers, school="okul-a", now_ms=NOW,
                store=Store(client),
            )
        )
        self.assertEqual(report.recommendation_rows, 1)
        self.assertEqual(report.recommendation_written, 1)
        self.assertEqual(report.recommendation_rejected, 0)

    def test_persist_gercek_depoya_yazar(self) -> None:
        client = CollectingClient()
        answers = [("q1", "user:1", "c-dogru"), ("q2", "user:1", "c-dogru2")]
        report = asyncio.run(
            persist_mod.persist(
                batch(), ITEMS, answers, school="okul-a", now_ms=NOW,
                store=Store(client),
            )
        )
        self.assertFalse(report.dry_run)
        self.assertEqual(report.question_written, 2)
        self.assertGreater(report.profile_written, 0)
        self.assertEqual(report.students, 1)


if __name__ == "__main__":
    unittest.main()
