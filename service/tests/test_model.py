"""`compute.model` birim testleri: kimlikten unix-ms zaman çözümü.

Kusur (2026-09-18): zaman çapası yalnız 26 karakterlik ULID kabul ediyordu;
backend ise kimlikleri **uuid v7** olarak basıyor (`domain/monotonic_id.rs`).
Sonuç: her not satırının zamanı "bilinmiyor" sayılıp düşüyor, 8 notu olan bir
derste bile `trend.available = False` ve "yetersiz veri" görünüyordu.

İki biçimin de ilk 48 biti unix-ms'tir; testler canlı/göç kaynaklı GERÇEK
örneklerle iki yolu da çiviliyor.
"""

from __future__ import annotations

import unittest

from src import ids
from src.compute import marks
from src.compute.model import id_ms

from .fakes import make_ulid

# Canlı backend'den gerçek sınav kimliği (2026-09-17) ve çözülen damgası.
UUID7_SAMPLE = "01a0b1af-f86f-776d-a344-3eec7547708b"
UUID7_SAMPLE_MS = 1_789_687_494_767  # 0x01A0B1AFF86F

# Gerçek ULID: `fixtures/demo/demo-okul/marks/student-00.json` satırı.
ULID_SAMPLE = "01H75BFWG00000000000000000"
ULID_SAMPLE_MS = 1_691_323_200_000

BASE = 1_700_000_000_000
DAY = 86_400_000


class TestIdMs(unittest.TestCase):
    def test_uuid7_sample_decodes(self) -> None:
        self.assertEqual(id_ms(UUID7_SAMPLE), UUID7_SAMPLE_MS)

    def test_ulid_sample_decodes(self) -> None:
        self.assertEqual(id_ms(ULID_SAMPLE), ULID_SAMPLE_MS)

    def test_migrated_pair_agrees(self) -> None:
        """Göçteki gerçek çift aynı damgayı vermeli.

        `ids.ulid_to_uuid7` bir ULID'i zamanı koruyarak uuid v7'ye çevirir;
        göç sonrası aynı sınavın kimliği bu biçimdedir. İki biçim ayrışırsa
        eğilim, göç öncesi ve sonrası satırlarda farklı davranır.
        """
        converted = str(ids.ulid_to_uuid7(ULID_SAMPLE))
        self.assertEqual(id_ms(converted), ULID_SAMPLE_MS)

    def test_table_prefixed_forms(self) -> None:
        self.assertEqual(id_ms("exam:" + UUID7_SAMPLE), UUID7_SAMPLE_MS)
        self.assertEqual(id_ms("exam:" + ULID_SAMPLE), ULID_SAMPLE_MS)

    def test_unknown_forms_return_none_without_raising(self) -> None:
        for bad in (
            "",
            None,
            "not-an-id",
            "01H75BFWGU000000000000000",  # 26 karakter ama Crockford dışı harf
            "01H75BFWG0000000000000000",  # 25 karakter
            "01a0b1af-f86f-476d-a344-3eec7547708b",  # uuid v4: damga değil
            "01a0b1aff-86f-776d-a344-3eec7547708b",  # tire yanlış yerde
            "gga0b1af-f86f-776d-a344-3eec7547708b",  # hex olmayan
        ):
            with self.subTest(bad=bad):
                self.assertIsNone(id_ms(bad))


def _uuid7_mark_entry(ms: int, mark: int) -> dict:
    """`MarkEntry` satırı; kimlik backend'in gerçek biçiminde (uuid v7)."""
    return {"exam": str(ids.uuid7(ms)), "mark": mark, "weight": 1}


class TestTrendWithUuid7Ids(unittest.TestCase):
    def test_eight_marks_are_available(self) -> None:
        """Kusurun canlı görünümü: 8 notlu derste eğilim 'veri yok' diyordu."""
        results = [
            _uuid7_mark_entry(BASE + i * DAY, m)
            for i, m in enumerate([70, 70, 70, 70, 45, 50, 48, 52])
        ]
        trend = marks.course_trend(results)
        self.assertTrue(trend["available"])
        self.assertEqual(trend["n"], 8)
        self.assertIsNotNone(trend["delta"])

    def test_drop_is_detected(self) -> None:
        results = [
            _uuid7_mark_entry(BASE + i * DAY, m)
            for i, m in enumerate([70, 70, 70, 50, 50, 50])
        ]
        trend = marks.course_trend(results)
        self.assertTrue(trend["available"])
        self.assertTrue(trend["dropped"])
        self.assertAlmostEqual(trend["delta"], -20.0)

    def test_mixed_id_shapes_order_together(self) -> None:
        """Göç sırasında bir derste iki biçim bir arada bulunur.

        Yalnız bir biçim çözülürse `n` yarıya düşer ve eğilim kaybolur;
        sıralamanın iki biçimden birlikte kurulması gerekir.
        """
        values = [70, 70, 70, 50, 50, 50]
        results = [
            _uuid7_mark_entry(BASE + i * DAY, m) if i % 2 == 0
            else {"exam": make_ulid(BASE + i * DAY), "mark": m, "weight": 1}
            for i, m in enumerate(values)
        ]
        results = [results[3], results[0], results[5], results[1], results[4], results[2]]
        trend = marks.course_trend(results)
        self.assertTrue(trend["available"])
        self.assertEqual(trend["n"], 6)
        self.assertAlmostEqual(trend["delta"], -20.0)


class TestUnanchoredMarksAreVisible(unittest.TestCase):
    """Çapası çözülemeyen not sessizce kaybolmaz.

    Eski `reason` cümlesi "6 not yok" diyordu; 8 notu olup kimlikleri
    çözülemeyen bir derste de **aynı** cümle çıkıyordu — uuid v7 kusurunu
    görünmez kılan tam da bu örtüşmeydi. Artık iki durum ayrı söylenir ve
    düşen satır sayısı sonuçta alan olarak taşınır.
    """

    def _unparsable(self, values: list[int]) -> list[dict]:
        # Gerçek biçimde ama uuid **v4** — damga taşımaz, çapa çözülemez.
        return [
            {"exam": "01a0b1af-f86f-476d-a344-3eec7547708b", "mark": v, "weight": 1}
            for v in values
        ]

    def test_all_unparsable_ids_get_a_distinct_reason(self) -> None:
        results = self._unparsable([70, 70, 70, 70, 45, 50, 48, 52])
        results.append({"exam": "x", "mark": None, "weight": 1})  # notsuz satır sayılmaz
        trend = marks.course_trend(results)
        self.assertFalse(trend["available"])
        # Önce SEBEP: eski kod burada "6 not gerekir" cümlesini basıyordu.
        self.assertNotEqual(
            trend["reason"],
            f"eğilim için en az {marks.MIN_MARKS_FOR_TREND} not gerekir",
        )
        self.assertIn("zaman damgası", trend["reason"])
        self.assertEqual(trend["n"], 0)
        self.assertEqual(trend["n_total"], 8)
        self.assertEqual(trend["n_unanchored"], 8)

    def test_short_but_anchorable_series_keeps_the_gate_reason(self) -> None:
        results = [
            _uuid7_mark_entry(BASE + i * DAY, m)
            for i, m in enumerate([70, 70, 70, 50, 50])
        ]
        trend = marks.course_trend(results)
        self.assertFalse(trend["available"])
        self.assertEqual(trend["n_total"], 5)
        self.assertEqual(trend["n_unanchored"], 0)
        self.assertEqual(
            trend["reason"],
            f"eğilim için en az {marks.MIN_MARKS_FOR_TREND} not gerekir",
        )

    def test_filtered_subset_reports_the_drop_count(self) -> None:
        results = [
            _uuid7_mark_entry(BASE + i * DAY, m)
            for i, m in enumerate([70, 70, 70, 50, 50, 50])
        ] + self._unparsable([60, 60])
        trend = marks.course_trend(results)
        self.assertTrue(trend["available"])
        self.assertEqual(trend["n"], 6)
        self.assertEqual(trend["n_total"], 8)
        self.assertEqual(trend["n_unanchored"], 2)
        self.assertAlmostEqual(trend["delta"], -20.0)


if __name__ == "__main__":
    unittest.main()
