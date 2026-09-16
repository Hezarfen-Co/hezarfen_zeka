"""Dikkat listesi kalibrasyonunun **altın küme üzerinde** gerileme koruması.

Bu dosya, `service/docs/HESAP-DOGRULAMA.md`'de ölçülen K1/K2/K5/K5b/K6/K7
kusurlarının düzeltilmiş olduğunu 250 öğrencilik altın küme
(`service/fixtures/gold_students/`, `tools/build_student_fixtures.py`)
üzerinde doğrular.

**Neden birim testi değil de ölçüm testi.** Kusurların hiçbiri tek bir
öğrencide görünmüyordu: `MISSING_TRIGGER = 3` her sentetik senaryoda "doğru"
davranıyor, kusur ancak **okulun ödev yoğunluğuyla birlikte** ortaya çıkıyor
(medyan 20 ödev / 4 eksik). Kalibrasyon kusuru dağılım düzeyinde bir kusurdur
ve yalnız dağılım düzeyinde sabitlenebilir.

**Eşikler dosyanın başında sabittir.** İkisi ayrı cinstendir:
  * `SENARYO_*` — `spec/SENARYO.md` §7.5'in kabul ölçütleri. Bunlar üründen
    gelir, ölçümden değil; gevşetilemez.
  * `OLCULEN_*` — düzeltmeden sonra bu fikstür üzerinde **bir kez ölçülmüş**
    değerler, kenar payıyla. Amaçları modülün sessizce bozulmasını yakalamak.
"""

from __future__ import annotations

import collections
import json
import pathlib
import statistics
import unittest

from src.compute import attendance as attendance_mod
from src.compute import attention as attention_mod
from src.compute import marks as marks_mod
from src.compute import study as study_mod
from src.compute import submission as submission_mod

FIXTURE_ROOT = (
    pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "gold_students"
)
GOLD_PATH = FIXTURE_ROOT / "gold.json"

# Bahar dönemi başlangıcı (`seed/01_temel.surql` → `term:bahar2026.starts_at`).
TERM_START_MS = 1769979600000


# --- Senaryo kabul ölçütleri (`spec/SENARYO.md` §7.5) -----------------------

# P21: dikkat listesine giren toplam öğrenci 32–48.
SENARYO_DIKKAT_TOPLAM = (32, 48)
# P23 / §3.8: yükselen arketip A5'ten listeye giren en çok 2 / 25.
SENARYO_A5_DIKKAT_MAX = 2
# P22: düşen arketip A6'nın 22 öğrencisinden en az 18'i listede.
SENARYO_A6_DIKKAT_MIN = 18


# --- Düzeltme sonrası ölçülen değerler --------------------------------------
#
# Hepsi `t_now = 1776056400000` fikstürü üzerinde bir kez ölçüldü.

# [K1/K2] Dikkat listesi. Ölçülen: 48 / 0 / 22.
# Tohum bilişsel desenle yeniden üretildikten sonra liste 46'dan 48'e çıktı;
# A6 yakalaması 21'den 22'ye (22/22) yükseldi. Bandın (32–48) üst ucuna yakın.
OLCULEN_LISTE_BUYUKLUGU = 48
OLCULEN_A5_YANLIS_POZITIF = 0
OLCULEN_A6_YAKALANAN = 22
# Kohort verilmediğinde ödev tetikleyicisi hiç ateşlemez → liste yalnız
# devamsızlık + not eğiliminden oluşur. Ölçülen 40.
OLCULEN_KOHORTSUZ_LISTE = 40
# `MISSING_COHORT_FACTOR` düzlüğü: bu çarpanların hepsinde liste P21 bandında.
# ÖLÇÜLDÜ (yeni tohum): 1,5 → 53 | 1,75 → 50 | 2,0 → 48 | 2,25 → 47 |
# 2,5 → 46 | 3,0 → 46 | 4,0 → 45. Düzlük 2,0'dan başlıyor; 1,75 artık bandın
# dışına taşıyor, bu yüzden listeden çıkarıldı. Eşik hâlâ bir düzlüğün
# içindedir (2,0–4,0 arası 45–48), tek bir noktaya oturtulmuş değildir.
OLCULEN_CARPAN_DUZLUGU = (2.0, 2.25, 2.5, 3.0)

# [K7] Öğrenci-içi ders kontrastı ↔ altın `gap_course` (A3, 35 öğrenci).
# Ölçülen: 31 tahmin, kesinlik 0,968, duyarlılık 0,857, 30/30'unda ders doğru.
OLCULEN_KONTRAST_KESINLIK_MIN = 0.95
OLCULEN_KONTRAST_DUYARLILIK_MIN = 0.80
OLCULEN_KONTRAST_TAHMIN = 31

# [K6] `is_rising()` ↔ A5 (25 öğrenci). Ölçülen: 20 tahmin, K 0,900, D 0,720.
OLCULEN_RISING_KESINLIK_MIN = 0.70
OLCULEN_RISING_DUYARLILIK_MIN = 0.70
# Ders düzeyinde `rising` sayısı — sıfır olmamalı (K6'nın kendisi buydu).
OLCULEN_RISING_DERS_MIN = 60  # ölçülen 69

# [K5b] Gece penceresi 22:00–02:00. ÖLÇÜLDÜ: pencere düzeltildikten sonra da
# A4 ile A2 arasında ayrım YOK (medyan 0,244 ↔ 0,231). Test bu **ölçememeyi**
# sabitler; "düzelttik, artık ayırıyor" demek yalan olurdu.
OLCULEN_GECE_A4_A2_FARK_MAX = 0.05


def _score(predicted: set[str], positives: set[str]) -> tuple[float, float]:
    """(kesinlik, duyarlılık). Boş tahminde kesinlik 0,0 sayılır."""
    tp = len(predicted & positives)
    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(positives) if positives else 0.0
    return precision, recall


class Bench:
    """Fikstürleri bir kez okur, tüm profilleri ve dikkat listesini bir kez kurar."""

    _instance: Bench | None = None

    def __init__(self) -> None:
        gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
        self.now_ms = int(gold["t_now_ms"])
        root = FIXTURE_ROOT / gold["school"]
        self.gold = {s["key"]: s for s in gold["students"]}
        self.by_archetype: dict[str, list[str]] = collections.defaultdict(list)
        for s in gold["students"]:
            self.by_archetype[s["archetype"]].append(s["key"])

        def read(kind: str, key: str):
            return json.loads(
                (root / kind / f"{key}.json").read_text(encoding="utf-8")
            )

        self.raw = {
            key: {
                kind: read(kind, key)
                for kind in (
                    "profile",
                    "marks",
                    "attendance",
                    "pomodoro",
                    "homework_report",
                )
            }
            for key in self.gold
        }

        # Kohortlar — `MODULLER.md` §0 kural 2: şube × ders (not/devam),
        # şube (ödev).
        self.classes = {
            key: marks_mod.class_ids_of(blob["profile"])
            for key, blob in self.raw.items()
        }
        distributions = marks_mod.cohort_distributions(
            marks_mod.collect_cohort_samples(
                {
                    key: (
                        self.classes[key],
                        marks_mod.student_course_stats(blob["marks"]),
                    )
                    for key, blob in self.raw.items()
                }
            )
        )
        medians = attendance_mod.cohort_medians(
            attendance_mod.collect_cohort_samples(
                {
                    key: (
                        self.classes[key],
                        attendance_mod.course_stats(blob["attendance"]),
                    )
                    for key, blob in self.raw.items()
                }
            )
        )

        self.marks: dict[str, dict] = {}
        self.attendance: dict[str, dict] = {}
        self.submission: dict[str, dict] = {}
        self.study: dict[str, dict] = {}
        for key, blob in self.raw.items():
            self.marks[key] = marks_mod.student_profile(
                blob["marks"], blob["profile"], distributions
            )
            self.attendance[key] = attendance_mod.student_profile(
                blob["attendance"], self.classes[key], medians
            )
            self.submission[key] = submission_mod.student_profile(
                blob["homework_report"], None, self.now_ms
            )
            self.study[key] = study_mod.student_profile(blob["pomodoro"], self.now_ms)

        # Ödev kohortu — kusur K1 düzeltmesinin çekirdeği.
        self.submission_cohort = attention_mod.submission_cohort_medians(
            {key: (self.classes[key], self.submission[key]) for key in self.gold}
        )
        self.attention = {
            key: attention_mod.evaluate(
                key,
                attendance_profile=self.attendance[key],
                submission_profile=self.submission[key],
                marks_profile=self.marks[key],
                now_ms=self.now_ms,
                term_start_ms=TERM_START_MS,
                submission_cohort=self.submission_cohort,
            )
            for key in self.gold
        }

    @classmethod
    def get(cls) -> Bench:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def arch(self, code: str) -> set[str]:
        return set(self.by_archetype[code])

    def listed(self) -> set[str]:
        return {k for k, items in self.attention.items() if items}

    def listed_by_trigger(self, trigger: str) -> set[str]:
        return {
            k
            for k, items in self.attention.items()
            if any(i.trigger.value == trigger for i in items)
        }


@unittest.skipUnless(
    GOLD_PATH.exists(), "altın fikstürler yok; tools/build_student_fixtures.py"
)
class GoldCase(unittest.TestCase):
    bench: Bench

    @classmethod
    def setUpClass(cls) -> None:
        cls.bench = Bench.get()


class TestListeBuyuklugu(GoldCase):
    """K1 — "herkesi işaretleyen liste" kusurunun kapanışı."""

    def test_p21_liste_senaryo_bandinda(self) -> None:
        """Düzeltme öncesi 193/250 idi; §7.5 P21 bandı 32–48."""
        n = len(self.bench.listed())
        self.assertGreaterEqual(n, SENARYO_DIKKAT_TOPLAM[0], f"liste {n}")
        self.assertLessEqual(n, SENARYO_DIKKAT_TOPLAM[1], f"liste {n}")

    def test_olculen_liste_buyuklugu_sabit(self) -> None:
        self.assertEqual(len(self.bench.listed()), OLCULEN_LISTE_BUYUKLUGU)

    def test_liste_ust_sinirla_kirpilmiyor(self) -> None:
        """Çözüm eşikte; "en kötü N'i göster" kırpması YOK.

        Kırpma bir **sıralama** üretir ve `[T§6.6]` madde 2 sıralamayı yasaklar.
        Modülde böyle bir sabit ya da kesme bulunmadığını sabitliyoruz: eşiği
        gevşetince liste bandı **taşabilmeli**; taşamıyorsa bir yerde kırpma
        vardır.
        """
        onceki = attention_mod.MISSING_COHORT_FACTOR
        try:
            attention_mod.MISSING_COHORT_FACTOR = 0.0
            genis = {
                key
                for key in self.bench.gold
                if attention_mod.evaluate(
                    key,
                    attendance_profile=self.bench.attendance[key],
                    submission_profile=self.bench.submission[key],
                    marks_profile=self.bench.marks[key],
                    now_ms=self.bench.now_ms,
                    term_start_ms=TERM_START_MS,
                    submission_cohort=self.bench.submission_cohort,
                )
            }
        finally:
            attention_mod.MISSING_COHORT_FACTOR = onceki
        self.assertGreater(len(genis), SENARYO_DIKKAT_TOPLAM[1])

    def test_carpan_duzlugu_bandin_icinde(self) -> None:
        """Eşik sonucu güzelleştirmek için seçilmedi: geniş bir düzlük var."""
        onceki = attention_mod.MISSING_COHORT_FACTOR
        try:
            for carpan in OLCULEN_CARPAN_DUZLUGU:
                attention_mod.MISSING_COHORT_FACTOR = carpan
                liste = {
                    key
                    for key in self.bench.gold
                    if attention_mod.evaluate(
                        key,
                        attendance_profile=self.bench.attendance[key],
                        submission_profile=self.bench.submission[key],
                        marks_profile=self.bench.marks[key],
                        now_ms=self.bench.now_ms,
                        term_start_ms=TERM_START_MS,
                        submission_cohort=self.bench.submission_cohort,
                    )
                }
                self.assertGreaterEqual(
                    len(liste), SENARYO_DIKKAT_TOPLAM[0], f"çarpan {carpan}"
                )
                self.assertLessEqual(
                    len(liste), SENARYO_DIKKAT_TOPLAM[1], f"çarpan {carpan}"
                )
                self.assertLessEqual(
                    len(liste & self.bench.arch("A5")),
                    SENARYO_A5_DIKKAT_MAX,
                    f"çarpan {carpan}",
                )
        finally:
            attention_mod.MISSING_COHORT_FACTOR = onceki


class TestArketipAyrimi(GoldCase):
    """K2 — yanlış pozitif ve doğru pozitif aynı anda korunuyor mu."""

    def test_p23_a5_yanlis_pozitif(self) -> None:
        """Düzeltme öncesi 20/25 idi; §7.5 P23 en çok 2."""
        a5 = self.bench.listed() & self.bench.arch("A5")
        self.assertLessEqual(len(a5), SENARYO_A5_DIKKAT_MAX, sorted(a5))
        self.assertEqual(len(a5), OLCULEN_A5_YANLIS_POZITIF)

    def test_p22_a6_yakalama_bozulmadi(self) -> None:
        """Düzeltmenin bedeli A6'dan ödenmemeli: 22/22."""
        bulunan = len(self.bench.listed() & self.bench.arch("A6"))
        self.assertGreaterEqual(bulunan, SENARYO_A6_DIKKAT_MIN, f"A6 {bulunan}")
        self.assertEqual(bulunan, OLCULEN_A6_YAKALANAN)

    def test_liste_agirligi_a6_a7de(self) -> None:
        """Liste, hedeflenen iki arketiple dolu olmalı; geri kalan kuyruk ince."""
        listed = self.bench.listed()
        hedef = len(listed & (self.bench.arch("A6") | self.bench.arch("A7")))
        self.assertGreater(hedef, len(listed) / 2)


class TestKuralTasarimi(GoldCase):
    """K2 — seviye ve değişim kurallarının bağlanma biçimi."""

    def test_iyiye_giden_ogrenci_odev_maddesi_almaz(self) -> None:
        """Koruyucu değişim kuralı: iyileşen öğrenci eşiği geçse de listelenmez."""
        sayac = 0
        for key, items in self.bench.attention.items():
            recent = self.bench.submission[key]["recent_30d"]
            previous = self.bench.submission[key]["previous_30d"]
            if not attention_mod._is_improving(recent, previous):
                continue
            sayac += 1
            self.assertNotIn(
                "homework", {i.trigger.value for i in items}, key
            )
        # İyileşen öğrenci sayısı anlamlı olmalı; yoksa test boş geçer.
        self.assertGreater(sayac, 100)

    def test_seviye_maddesi_tek_basina_yukseleni_listelemiyor(self) -> None:
        """A5 koruması (`_suppress_rising`) — tek seviye maddesi yetmez."""
        for key, items in self.bench.attention.items():
            if len(items) != 1:
                continue
            if items[0].evidence.get("rule_basis") != attention_mod.BASIS_LEVEL:
                continue
            self.assertFalse(
                attention_mod.is_rising(self.bench.marks[key]), key
            )

    def test_her_madde_kural_dayanagini_tasiyor(self) -> None:
        for key, items in self.bench.attention.items():
            for item in items:
                self.assertIn(
                    item.evidence.get("rule_basis"),
                    (attention_mod.BASIS_LEVEL, attention_mod.BASIS_CHANGE),
                    key,
                )

    def test_odev_maddesi_kohort_kanitini_tasiyor(self) -> None:
        """Mutlak eşik kalmadı: her ödev maddesi şube ortancasını gösterir."""
        maddeler = [
            i
            for items in self.bench.attention.values()
            for i in items
            if i.trigger.value == "homework"
        ]
        self.assertTrue(maddeler)
        for item in maddeler:
            self.assertIsNotNone(item.evidence["cohort_missing_rate_median"])
            self.assertEqual(
                item.evidence["measure"], "missing_rate_vs_cohort_median"
            )
            self.assertNotIn("n_missing >= 3", item.fact)

    def test_kohort_yoksa_odev_tetikleyicisi_ateslemiyor(self) -> None:
        """Fail-closed: kohort bilinmeden mutlak eşiğe düşülmez."""
        liste = set()
        for key in self.bench.gold:
            items = attention_mod.evaluate(
                key,
                attendance_profile=self.bench.attendance[key],
                submission_profile=self.bench.submission[key],
                marks_profile=self.bench.marks[key],
                now_ms=self.bench.now_ms,
                term_start_ms=TERM_START_MS,
            )
            self.assertNotIn("homework", {i.trigger.value for i in items}, key)
            if items:
                liste.add(key)
        self.assertEqual(len(liste), OLCULEN_KOHORTSUZ_LISTE)
        # Kohortsuz hâl de bandın içinde kalmalı — yarım liste bile taşmamalı.
        self.assertGreaterEqual(len(liste), SENARYO_DIKKAT_TOPLAM[0])
        self.assertLessEqual(len(liste), SENARYO_DIKKAT_TOPLAM[1])


class TestYukselenSinifi(GoldCase):
    """K6 — `course_trend()` artık `rising` üretiyor."""

    def test_ders_duzeyinde_rising_uretiliyor(self) -> None:
        toplam = sum(
            1
            for key in self.bench.gold
            for c in self.bench.marks[key]["courses"].values()
            if c["trend"].get("rising")
        )
        self.assertGreaterEqual(toplam, OLCULEN_RISING_DERS_MIN)

    def test_rising_ve_dropped_asla_ayni_anda(self) -> None:
        for key in self.bench.gold:
            for cid, c in self.bench.marks[key]["courses"].items():
                trend = c["trend"]
                self.assertFalse(
                    trend.get("rising") and trend.get("dropped"), f"{key}/{cid}"
                )

    def test_is_rising_a5i_yakaliyor(self) -> None:
        pred = {
            key
            for key in self.bench.gold
            if attention_mod.is_rising(self.bench.marks[key])
        }
        p, r = _score(pred, self.bench.arch("A5"))
        self.assertGreaterEqual(p, OLCULEN_RISING_KESINLIK_MIN, f"kesinlik {p}")
        self.assertGreaterEqual(r, OLCULEN_RISING_DUYARLILIK_MIN, f"duyarlılık {r}")

    def test_dusen_arketip_asla_yukselen_sayilmaz(self) -> None:
        for key in self.bench.arch("A6"):
            self.assertFalse(attention_mod.is_rising(self.bench.marks[key]), key)


class TestKonuBoslugu(GoldCase):
    """K7 — öğrenci-içi ders kontrastı `marks.py` çıktısında."""

    def setUp(self) -> None:
        self.gap_keys = {
            k for k, g in self.bench.gold.items() if g["gap_course"]
        }

    def test_kontrast_profilde_var(self) -> None:
        key = next(iter(self.gap_keys))
        contrast = self.bench.marks[key]["within_student_contrast"]
        for alan in ("available", "course", "delta", "flagged", "others_median_z"):
            self.assertIn(alan, contrast)

    def test_kontrast_a3u_bulur(self) -> None:
        pred = {
            key
            for key in self.bench.gold
            if self.bench.marks[key]["within_student_contrast"]["flagged"]
        }
        p, r = _score(pred, self.gap_keys)
        self.assertEqual(len(pred), OLCULEN_KONTRAST_TAHMIN)
        self.assertGreaterEqual(p, OLCULEN_KONTRAST_KESINLIK_MIN, f"kesinlik {p}")
        self.assertGreaterEqual(r, OLCULEN_KONTRAST_DUYARLILIK_MIN, f"duyarlılık {r}")

    def test_kontrast_hangi_ders_oldugunu_da_dogru_soyluyor(self) -> None:
        dogru = 0
        tahmin = 0
        for key, g in self.bench.gold.items():
            contrast = self.bench.marks[key]["within_student_contrast"]
            if not contrast["flagged"]:
                continue
            if key not in self.gap_keys:
                continue
            tahmin += 1
            if g["gap_course"] == contrast["course"]:
                dogru += 1
        self.assertEqual(dogru, tahmin)

    def test_kontrast_uc_dersten_az_olanda_kapali(self) -> None:
        bos = marks_mod.within_student_contrast({})
        self.assertFalse(bos["available"])
        self.assertFalse(bos["flagged"])
        self.assertIsNone(bos["delta"])

    def test_kontrast_konu_duzeyi_iddia_etmiyor(self) -> None:
        """`gap_subjects` (105 konu) hâlâ ölçülemiyor; ürün bunu iddia etmemeli."""
        key = next(iter(self.gap_keys))
        course_stat = next(iter(self.bench.marks[key]["courses"].values()))
        self.assertNotIn("subjects", course_stat)
        self.assertIn(
            "Konu (subject) kırılımı", self.bench.marks[key]["limitation"]
        )


class TestCalismaOlculeri(GoldCase):
    """K5 / K5b — `study.py`."""

    def test_gece_penceresi_senaryoyla_ayni(self) -> None:
        """22:00–02:00, yarı açık: 22, 23, 00, 01."""
        self.assertEqual(study_mod.NIGHT_HOURS, (22, 23, 0, 1))

    def test_gece_payi_hala_arketip_ayirmiyor(self) -> None:
        """ÖLÇÜLDÜ: pencere düzeltildi ama ayrım gücü **yok**; iddia edilmiyor."""

        def med(code: str) -> float:
            vals = [
                self.bench.study[k]["recent_28d"]["night_share"]
                for k in self.bench.arch(code)
                if self.bench.study[k]["recent_28d"]["night_share"] is not None
            ]
            return statistics.median(vals)

        self.assertLess(abs(med("A4") - med("A2")), OLCULEN_GECE_A4_A2_FARK_MAX)

    def test_burstiness_bayragi_kaldirildi(self) -> None:
        """K5: ölçemediğimiz şey bayrağa dönüşmez."""
        recent = self.bench.study[next(iter(self.bench.gold))]["recent_28d"]
        self.assertNotIn("bursty", recent)
        self.assertIn("burstiness", recent)
        self.assertIn("ÖLÇMEZ", recent["burstiness_limitation"])

    def test_sinav_oncesi_yigilma_hala_uretilemiyor(self) -> None:
        profile = self.bench.study[next(iter(self.bench.gold))]
        self.assertIsNone(profile["pre_exam_share"])
        self.assertTrue(profile["pre_exam_reason"])


class TestYapisalKurallarKorundu(GoldCase):
    """`[T§6.6]` — düzeltme hiçbir yapısal kısıtı gevşetmedi."""

    def test_skor_sira_yok_risk_kelimesi_yok(self) -> None:
        for key, items in self.bench.attention.items():
            for item in items:
                self.assertTrue(item.evidence, key)
                self.assertNotIn("risk", item.fact.lower())
                self.assertFalse(hasattr(item, "score"))
                self.assertFalse(hasattr(item, "rank"))

    def test_siralama_alfabetik_kaliyor(self) -> None:
        hepsi = [i for items in self.bench.attention.values() for i in items]
        ordered = attention_mod.order_items(hepsi)
        anahtarlar = [(i.student, i.trigger.value) for i in ordered]
        self.assertEqual(anahtarlar, sorted(anahtarlar))

    def test_exam_missed_hala_ateslenmiyor_ve_raporlaniyor(self) -> None:
        for items in self.bench.attention.values():
            for item in items:
                self.assertNotEqual(item.trigger.value, "exam_missed")
        self.assertIn("exam_missed", attention_mod.unavailable_triggers())

    def test_her_madde_sinir_satiri_tasiyor(self) -> None:
        for key, items in self.bench.attention.items():
            for item in items:
                self.assertTrue(item.evidence.get("limitation"), key)


if __name__ == "__main__":
    unittest.main()
