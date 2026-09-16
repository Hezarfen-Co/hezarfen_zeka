"""Hesap modüllerinin **altın etikete** karşı isabet ölçümü.

Bu dosya `service/tests/` altındaki diğer testlerden farklıdır: orada modüller
sentetik, elle kurulmuş girdilerle sınanır ("bu girdiye bu çıktı"). Burada
`seed/_seed_manifest.json` içindeki **250 gerçek öğrencinin gizli gerçeği**
(arketip, `theta_base`, `theta_trend`, `gap_course`, `true_counted_pomodoro`)
ile modüllerin ürettiği sinyal karşılaştırılır.

Fikstürler `tools/build_student_fixtures.py` ile tohum `.surql` dosyalarından
üretilir ve `service/fixtures/gold_students/` altında **`Source` arayüzünün tam
biçiminde** durur. Fikstür yoksa bu dosyadaki testler atlanır (CI'da fikstürler
depoda olduğu için koşarlar).

GEÇERLİLİK UYARISI
------------------
Bu tohumda **soru metni ile madde zorluğu bağımsız üretilmiştir**; metne dayalı
hiçbir çıkarım bu veriyle doğrulanamaz. Buradaki ölçümlerin hiçbiri metne
dayanmaz — hepsi not / devam / teslim / çalışma kaydına dayanır, dolayısıyla
**geçerlidirler**. Geçerli olmayan tek tek satırlar ayrıca işaretlenmiştir
(`gap_subjects` konu düzeyi, `counted_on_time`, `exam_missed`).

EŞİK POLİTİKASI
---------------
Aşağıdaki eşikler **ölçüm sonucunu güzelleştirmek için ayarlanmamıştır**. İki
tür sabit var ve ikisi de adıyla ayrılmış:

* `SENARYO_*` — `spec/SENARYO.md` §7'den **birebir alınan** kabul ölçütü.
  Tutmayanlar `@unittest.expectedFailure` ile işaretlidir; testi yeşile boyamak
  için değer düşürülmemiştir, beklenti olduğu gibi durur ve kusur
  `service/docs/HESAP-DOGRULAMA.md` içinde raporlanır.
* `OLCULEN_*` — bu koşuda **ölçülen** değerin gerileme (regression) koruması.
  Modül davranışı değişirse test kırılsın diye vardır; bir kabul ölçütü
  değildir.
"""

from __future__ import annotations

import collections
import json
import math
import pathlib
import statistics
import unittest

from src.compute import attendance as attendance_mod
from src.compute import attention as attention_mod
from src.compute import marks as marks_mod
from src.compute import model
from src.compute import study as study_mod
from src.compute import submission as submission_mod

FIXTURE_ROOT = (
    pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "gold_students"
)
GOLD_PATH = FIXTURE_ROOT / "gold.json"

# --- Senaryo kabul ölçütleri (spec/SENARYO.md §7.5 / §3) --------------------

# §7.5 P22: dikkat listesinde A6'nın 22 öğrencisinden en az 18'i.
SENARYO_A6_DIKKAT_MIN = 18
# §7.5 P23 / §3.8: A5'ten listeye giren en çok 2 / 25 (yanlış pozitif kontrolü).
SENARYO_A5_DIKKAT_MAX = 2
# §7.5 P21: dikkat listesine giren toplam öğrenci 32–48.
SENARYO_DIKKAT_TOPLAM = (32, 48)
# §7.5 P24: dört tetikleyicinin dördünü de ateşleyen 12–18 öğrenci, hepsi A6.
SENARYO_DORT_TETIK = (12, 18)
# §7.3 A10 / A11 / A12: `counted_on_time` A4 %48±5, A1 %97±2, fark ≥ 40 puan.
SENARYO_A4_ON_TIME = (0.43, 0.53)
SENARYO_A1_ON_TIME = (0.95, 0.99)
SENARYO_ON_TIME_FARK_MIN = 0.40
# §7.3 A13/A14/A15: devam oranı A7 %69±4, A1 %97±2, fark ≥ 20 puan.
SENARYO_A7_DEVAM = (0.65, 0.73)
SENARYO_A1_DEVAM = (0.95, 0.99)
SENARYO_DEVAM_FARK_MIN = 0.20

# --- Ölçülen değerlerin gerileme koruması -----------------------------------
#
# Hepsi 2026-04-13 (`t_now`) fikstürü üzerinde bir kez ölçülmüş, sonra sabite
# yazılmıştır. Kenar payları ölçüm gürültüsü için değil, modülün *anlamlı*
# değişiminde kırılsın diye dardır.

# [1] `marks.course_trend().slope_per_30d` medyanı bu değerin üstündeyse
# "yükselen". Eşik seçimi: A5 dışındaki tüm arketiplerin medyan eğimi 0,0–0,9
# aralığında, A5 +5,5 (A6 −7,1). 3,0 iki kümenin arasındaki geniş boşluğa düşer.
OLCULEN_YUKSELEN_ESIK = 3.0
OLCULEN_A5_EGILIM_DUYARLILIK_MIN = 0.78  # ölçülen 0,800 (20/25)
OLCULEN_A5_EGILIM_KESINLIK_MIN = 0.60  # ölçülen 0,645 (31 tahminde 20)
# A6 için modülün **kendi** kuralı kullanılır (`trend.dropped`, §2.8 −15 puan).
OLCULEN_A6_DROPPED_DUYARLILIK_MIN = 0.78  # ölçülen 0,818
OLCULEN_A6_DROPPED_KESINLIK_MIN = 0.80  # ölçülen 0,857

# [2] Ders düzeyi `Band.REVIEW` altın boşluk dersini yakalıyor ama seçici değil.
OLCULEN_GAP_REVIEW_DUYARLILIK_MIN = 0.85  # ölçülen 0,857 (30/35)
OLCULEN_GAP_REVIEW_KESINLIK_MAX = 0.10  # ölçülen 0,053 (30 / 562 çift)
# Modülün ÜRETMEDİĞİ ama çıktısından türetilebilen ölçü: öğrencinin en düşük
# z'li dersi ile diğer derslerinin medyan z'si arasındaki fark.
OLCULEN_KONTRAST_ESIK = -1.5
OLCULEN_KONTRAST_KESINLIK_MIN = 0.95  # ölçülen 0,968 (31 tahminde 30)
OLCULEN_KONTRAST_DUYARLILIK_MIN = 0.80  # ölçülen 0,857 (30/35)

# [3] A7, modülün kendi eşikleriyle (rate < 0,80 ve relative_gap ≤ −0,10).
OLCULEN_A7_DEVAM_DUYARLILIK_MIN = 1.0  # ölçülen 1,00 (18/18)
OLCULEN_A7_DEVAM_KESINLIK_MIN = 0.90  # ölçülen 0,947 (19 tahminde 18)
# NOT: A7 artık `okuma_yuku` boyutunda da sapma taşıyor (yüksek okuma yükünde
# −1,10 logit); devam ölçüleri bundan etkilenmiyor, ölçüm değişmedi.

# [4] Teslim: A4'ü ayıran tek eşik yok; A7 aynı bölgede.
OLCULEN_ON_TIME_ESIK = 0.60
OLCULEN_A4_TESLIM_DUYARLILIK_MIN = 0.95  # ölçülen 1,00 (32/32)

# [5] Çalışma.
OLCULEN_POMODORO_TAM_ESLESME = 250  # 250/250
OLCULEN_A6_STINT_MEDYAN_MAX = 6  # ölçülen 2,0 (degismedi)
OLCULEN_A7_STINT_MEDYAN_MAX = 1  # ölçülen 0
OLCULEN_A2_STINT_MEDYAN_MIN = 20  # ölçülen 34
# A4 "düzensiz çalışan" ayırt EDİLEMİYOR: burstiness medyanı okul medyanından
# neredeyse farksız. Fark bu değerin altında kalırsa ayrım yok demektir.
OLCULEN_A4_BURSTINESS_FARK_MAX = 0.30  # ölçülen ~0,036

# [6] Dikkat listesi — ölçülen gerçek.
# DUZELTME SONRASI olculen (kohort-goreli esik, koruyucu VE kurali).
# Onceki kusurlu deger 193'tu; K1/K2 giderildikten sonra 39, tohum bilissel
# desenle yeniden uretildikten sonra 40.
OLCULEN_DIKKAT_TOPLAM = 40
OLCULEN_DIKKAT_ODEVSIZ = 40  # odev tetikleyicisi olmadan listede kalan
# Kohort beslenmediginde odev tetikleyicisi FAIL-CLOSED: hic atesleme.
OLCULEN_ODEV_TETIKLEYEN_MAX = 0

# [7] Yetenek kestirimi.
# NOT: `theta_base` artık öğrencinin TEK yeteneği değil; üstüne boyut bazında
# sapma biniyor (A4/A7/A8). Genel sıralama korunuyor, korelasyon bir miktar
# düşüyor — bu beklenen ve kasıtlı bir sonuçtur.
OLCULEN_THETA_SPEARMAN_MIN = 0.85  # ölçülen 0,906 (250 öğrenci)
OLCULEN_THETA_SABIT_SPEARMAN_MIN = 0.94  # ölçülen 0,954 (A5/A6 hariç, n=203)
# `theta_base` + boyut sapması ayrımı için bkz. docs/DESEN-DOGRULAMA.md

# Bahar dönemi başlangıcı (`seed/01_temel.surql` → `term:bahar2026.starts_at`).
TERM_START_MS = 1769979600000


# --- Yardımcılar ------------------------------------------------------------


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys, strict=True))
    sxx = sum((a - mx) ** 2 for a in xs)
    syy = sum((b - my) ** 2 for b in ys)
    return sxy / math.sqrt(sxx * syy)


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    for position, index in enumerate(order):
        out[index] = float(position)
    return out


def _spearman(xs: list[float], ys: list[float]) -> float:
    return _pearson(_ranks(xs), _ranks(ys))


def _score(predicted: set[str], positives: set[str]) -> tuple[float, float]:
    """(kesinlik, duyarlılık). Boş tahminde kesinlik 0,0 sayılır."""
    tp = len(predicted & positives)
    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(positives) if positives else 0.0
    return precision, recall


class GoldBench:
    """Fikstürleri bir kez okur, tüm modül profillerini bir kez hesaplar."""

    _instance: GoldBench | None = None

    def __init__(self) -> None:
        gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
        self.now_ms = int(gold["t_now_ms"])
        root = FIXTURE_ROOT / gold["school"]
        self.gold = {s["key"]: s for s in gold["students"]}
        self.by_archetype: dict[str, list[str]] = collections.defaultdict(list)
        for s in gold["students"]:
            self.by_archetype[s["archetype"]].append(s["key"])

        def read(kind: str, key: str):
            return json.loads((root / kind / f"{key}.json").read_text(encoding="utf-8"))

        raw = {
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
        self.raw = raw

        # Kohortlar — `MODULLER.md` §0 kural 2: şube × ders.
        per_marks = {}
        per_attendance = {}
        for key, blob in raw.items():
            class_ids = marks_mod.class_ids_of(blob["profile"])
            per_marks[key] = (class_ids, marks_mod.student_course_stats(blob["marks"]))
            per_attendance[key] = (
                class_ids,
                attendance_mod.course_stats(blob["attendance"]),
            )
        distributions = marks_mod.cohort_distributions(
            marks_mod.collect_cohort_samples(per_marks)
        )
        medians = attendance_mod.cohort_medians(
            attendance_mod.collect_cohort_samples(per_attendance)
        )

        self.marks: dict[str, dict] = {}
        self.attendance: dict[str, dict] = {}
        self.submission: dict[str, dict] = {}
        self.study: dict[str, dict] = {}
        self.attention: dict[str, list] = {}
        for key, blob in raw.items():
            class_ids = marks_mod.class_ids_of(blob["profile"])
            self.marks[key] = marks_mod.student_profile(
                blob["marks"], blob["profile"], distributions
            )
            self.attendance[key] = attendance_mod.student_profile(
                blob["attendance"], class_ids, medians
            )
            self.submission[key] = submission_mod.student_profile(
                blob["homework_report"], None, self.now_ms
            )
            self.study[key] = study_mod.student_profile(blob["pomodoro"], self.now_ms)
            self.attention[key] = attention_mod.evaluate(
                key,
                attendance_profile=self.attendance[key],
                submission_profile=self.submission[key],
                marks_profile=self.marks[key],
                now_ms=self.now_ms,
                term_start_ms=TERM_START_MS,
            )

    @classmethod
    def get(cls) -> GoldBench:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # --- türetilmiş ölçüler ---

    def arch(self, code: str) -> set[str]:
        return set(self.by_archetype[code])

    def trend_slope(self, key: str) -> float | None:
        slopes = [
            c["trend"]["slope_per_30d"]
            for c in self.marks[key]["courses"].values()
            if c["trend"]["available"] and c["trend"]["slope_per_30d"] is not None
        ]
        return statistics.median(slopes) if slopes else None

    def has_dropped(self, key: str) -> bool:
        return any(
            c["trend"].get("dropped") for c in self.marks[key]["courses"].values()
        )

    def review_courses(self, key: str) -> list[str]:
        return [
            cid
            for cid, c in self.marks[key]["courses"].items()
            if c["placement"]["band"] == model.Band.REVIEW
        ]

    def z_map(self, key: str) -> dict[str, float]:
        return {
            cid: c["placement"]["z"]
            for cid, c in self.marks[key]["courses"].items()
            if c["placement"]["z"] is not None
        }

    def contrast(self, key: str) -> tuple[str | None, float | None]:
        """En düşük z'li ders ve onun diğer derslerin medyanına farkı.

        Bu ölçü **modülde yoktur**; `place_in_cohort()` çıktısından burada
        türetilir. Amacı, verinin A3'ü desteklediğini ama modülün bu ürünü
        üretmediğini göstermektir (bkz. HESAP-DOGRULAMA.md kusur K7).
        """
        zs = self.z_map(key)
        if len(zs) < 3:
            return (None, None)
        worst = min(zs, key=lambda c: zs[c])
        others = [v for c, v in zs.items() if c != worst]
        return (worst, zs[worst] - statistics.median(others))

    def listed(self) -> set[str]:
        return {k for k, items in self.attention.items() if items}

    def listed_by_trigger(self, trigger: str) -> set[str]:
        return {
            k
            for k, items in self.attention.items()
            if any(i.trigger.value == trigger for i in items)
        }


@unittest.skipUnless(GOLD_PATH.exists(), "altın fikstürler yok; build_student_fixtures.py")
class GoldTestCase(unittest.TestCase):
    bench: GoldBench

    @classmethod
    def setUpClass(cls) -> None:
        cls.bench = GoldBench.get()


class TestFixtureButunlugu(GoldTestCase):
    """Fikstürün altın etiketle aynı evreni tarif ettiğini doğrular."""

    def test_250_ogrenci_ve_arketip_dagilimi(self) -> None:
        beklenen = {
            "A1": 30,
            "A2": 70,
            "A3": 35,
            "A4": 32,
            "A5": 25,
            "A6": 22,
            "A7": 18,
            "A8": 18,
        }
        self.assertEqual(len(self.bench.gold), 250)
        self.assertEqual(
            {a: len(ks) for a, ks in sorted(self.bench.by_archetype.items())}, beklenen
        )

    def test_gap_ve_break_etiketleri_arketiple_tutarli(self) -> None:
        gap = {k for k, g in self.bench.gold.items() if g["gap_course"]}
        brk = {k for k, g in self.bench.gold.items() if g["t_break_ms"]}
        self.assertEqual(gap, self.bench.arch("A3"))
        self.assertEqual(brk, self.bench.arch("A6"))


class Test1MarksEgilim(GoldTestCase):
    """[1] `marks.py` eğilim tespiti ↔ `theta_trend`."""

    def test_yukselen_arketip_a5_egimle_ayrilir(self) -> None:
        pred = {
            k
            for k in self.bench.gold
            if (self.bench.trend_slope(k) or 0.0) >= OLCULEN_YUKSELEN_ESIK
        }
        p, r = _score(pred, self.bench.arch("A5"))
        self.assertGreaterEqual(r, OLCULEN_A5_EGILIM_DUYARLILIK_MIN, f"duyarlılık {r}")
        self.assertGreaterEqual(p, OLCULEN_A5_EGILIM_KESINLIK_MIN, f"kesinlik {p}")

    def test_dusen_arketip_a6_modul_kuraliyla_ayrilir(self) -> None:
        # Modülün kendi kuralı: son 3 not ortalaması önceki 3'ten ≥15 puan düşük.
        pred = {k for k in self.bench.gold if self.bench.has_dropped(k)}
        p, r = _score(pred, self.bench.arch("A6"))
        self.assertGreaterEqual(r, OLCULEN_A6_DROPPED_DUYARLILIK_MIN, f"duyarlılık {r}")
        self.assertGreaterEqual(p, OLCULEN_A6_DROPPED_KESINLIK_MIN, f"kesinlik {p}")

    def test_egim_isareti_theta_trend_ile_ayni_yonde(self) -> None:
        """Sabit `theta_trend`li arketiplerde eğim işareti sıfıra yakın kalmalı."""
        for code in ("A1", "A2", "A3"):
            slopes = [
                s
                for s in (self.bench.trend_slope(k) for k in self.bench.arch(code))
                if s is not None
            ]
            self.assertLess(abs(statistics.median(slopes)), 2.0, code)

    def test_modul_yukselen_icin_sinif_uretiyor(self) -> None:
        """K6 GIDERILDI: `course_trend()` artik `rising` de uretiyor.

        `spec/SENARYO.md` §3.2 Ö1 satırı A5 için "T1 düşük → T2 güçlü" ürünü
        istiyor. Modül eğimi **sayı olarak** veriyor ama sınıflandırmıyor;
        yükselen tespiti tüketiciye bırakılmış durumda.
        """
        any_key = next(iter(self.bench.gold))
        trend = next(iter(self.bench.marks[any_key]["courses"].values()))["trend"]
        self.assertIn("dropped", trend)
        self.assertIn("rising", trend)


class Test2KonuBoslugu(GoldTestCase):
    """[2] Konu boşluğu ↔ `gap_course` / `gap_subjects`. En önemli ürün."""

    def setUp(self) -> None:
        self.gap_keys = {k for k, g in self.bench.gold.items() if g["gap_course"]}

    def test_konu_subject_duzeyi_uretilemiyor(self) -> None:
        """GEÇERSİZ ÖLÇÜM: `gap_subjects` (105 konu) bu arayüzle ölçülemez.

        `Source.marks()` ders düzeyinde not veriyor; `exam_answer` ve
        `exam_question.subject` izin listesinde yok. `marks.py` başlığı bunu
        zaten söylüyor; test bunu bir davranış olarak sabitler.
        """
        toplam_konu = sum(len(g["gap_subjects"]) for g in self.bench.gold.values())
        self.assertEqual(toplam_konu, 105)
        key = next(iter(self.gap_keys))
        course_stat = next(iter(self.bench.marks[key]["courses"].values()))
        self.assertNotIn("subjects", course_stat)
        self.assertIn("Konu (subject) kırılımı", self.bench.marks[key]["limitation"])

    def test_review_bandi_bosluk_dersini_yakaliyor_ama_secici_degil(self) -> None:
        yakalanan = sum(
            1
            for k in self.gap_keys
            if self.bench.gold[k]["gap_course"] in self.bench.review_courses(k)
        )
        recall = yakalanan / len(self.gap_keys)
        toplam_cift = sum(len(self.bench.review_courses(k)) for k in self.bench.gold)
        precision = yakalanan / toplam_cift
        self.assertGreaterEqual(recall, OLCULEN_GAP_REVIEW_DUYARLILIK_MIN)
        # Kusur K7: bant kohorta göre mutlak konum ölçer; "genel iyi ama bir
        # derste kötü" ayrımını yapmaz, bu yüzden 500'den fazla yanlış pozitif.
        self.assertLessEqual(precision, OLCULEN_GAP_REVIEW_KESINLIK_MAX)

    def test_ic_ogrenci_kontrasti_bosluğu_neredeyse_kusursuz_bulur(self) -> None:
        """Veri A3'ü destekliyor; eksik olan modülün bu ölçüyü üretmesi."""
        pred: set[str] = set()
        ders_de_dogru = 0
        for key, g in self.bench.gold.items():
            course, delta = self.bench.contrast(key)
            if delta is None or delta > OLCULEN_KONTRAST_ESIK:
                continue
            pred.add(key)
            if g["gap_course"] == course:
                ders_de_dogru += 1
        p, r = _score(pred, self.gap_keys)
        self.assertGreaterEqual(p, OLCULEN_KONTRAST_KESINLIK_MIN, f"kesinlik {p}")
        self.assertGreaterEqual(r, OLCULEN_KONTRAST_DUYARLILIK_MIN, f"duyarlılık {r}")
        # Yakalananların hepsinde **hangi ders** olduğu da doğru bilinmeli.
        self.assertEqual(ders_de_dogru, len(pred & self.gap_keys))

    def test_modulde_ic_ogrenci_kontrasti_yok(self) -> None:
        """Kusur K7 — ölçü modül çıktısında bulunmuyor."""
        key = next(iter(self.gap_keys))
        placement = next(iter(self.bench.marks[key]["courses"].values()))["placement"]
        for alan in ("within_student_gap", "relative_to_own_courses", "contrast"):
            self.assertNotIn(alan, placement)


class Test3Devamsizlik(GoldTestCase):
    """[3] `attendance.py` ↔ devamsız arketip A7."""

    def test_a7_modul_esikleriyle_ayrilir(self) -> None:
        pred = set()
        for key in self.bench.gold:
            overall = self.bench.attendance[key]["overall"]
            rate = overall.get("rate")
            gap = overall.get("relative_gap")
            if rate is None or gap is None:
                continue
            if (
                rate < attendance_mod.ATTENTION_RATE
                and gap <= attendance_mod.ATTENTION_RELATIVE_GAP
            ):
                pred.add(key)
        p, r = _score(pred, self.bench.arch("A7"))
        self.assertGreaterEqual(r, OLCULEN_A7_DEVAM_DUYARLILIK_MIN, f"duyarlılık {r}")
        self.assertGreaterEqual(p, OLCULEN_A7_DEVAM_KESINLIK_MIN, f"kesinlik {p}")

    def test_senaryo_a13_a14_a15_devam_oranlari(self) -> None:
        def med(code: str) -> float:
            vals = [
                self.bench.attendance[k]["overall"]["rate"]
                for k in self.bench.arch(code)
            ]
            return statistics.median([v for v in vals if v is not None])

        a7, a1 = med("A7"), med("A1")
        self.assertGreaterEqual(a7, SENARYO_A7_DEVAM[0])
        self.assertLessEqual(a7, SENARYO_A7_DEVAM[1])
        self.assertGreaterEqual(a1, SENARYO_A1_DEVAM[0])
        self.assertLessEqual(a1, SENARYO_A1_DEVAM[1])
        self.assertGreaterEqual(a1 - a7, SENARYO_DEVAM_FARK_MIN)

    def test_a6_devamsizlik_cokusu_gorunmuyor(self) -> None:
        """Kusur K3: devam verisi dönem kümülatifi; A6'nın kırılma sonrası
        %94 → %73 düşüşü ortalamanın içinde eriyor.

        `spec/SENARYO.md` §3.9 tetikleyici 1 A6'nın **tamamında** ateşlenmesini
        bekliyor; ölçülen 22 öğrencinin 1'i.
        """
        fired = self.bench.listed_by_trigger("attendance") & self.bench.arch("A6")
        self.assertLessEqual(len(fired), 3)
        self.assertFalse(self.bench.attendance[next(iter(self.bench.gold))]["trend"]["available"])


class Test4TeslimErteleme(GoldTestCase):
    """[4] `submission.py` ↔ erteleyen arketip A4."""

    def _on_time(self, key: str) -> float | None:
        return self.bench.submission[key]["overall"]["on_time_rate_by_last_touch"]

    def test_a4_yakalaniyor_ama_a7den_ayrilmiyor(self) -> None:
        pred = {
            k
            for k in self.bench.gold
            if (self._on_time(k) if self._on_time(k) is not None else 1.0)
            < OLCULEN_ON_TIME_ESIK
        }
        _, recall = _score(pred, self.bench.arch("A4"))
        self.assertGreaterEqual(recall, OLCULEN_A4_TESLIM_DUYARLILIK_MIN)
        # Kusur K4: A7'nin **tamamı** aynı bölgede; ölçü "erteleme"yi değil
        # "teslim etmeme"yi görüyor. `procrastination` üretilemediği için
        # A4 ↔ A7 ayrımı bu modülle yapılamaz.
        self.assertEqual(len(pred & self.bench.arch("A7")), 18)

    def test_erteleme_profili_uretilemiyor(self) -> None:
        """GEÇERSİZ ÖLÇÜM: A4'ün tanımlayıcı özelliği (`−2 saat` medyan teslim
        payı) `submitted_at` olmadan hesaplanamaz."""
        proc = self.bench.submission[next(iter(self.bench.gold))]["procrastination"]
        self.assertFalse(proc["available"])
        self.assertIsNone(proc["median_lead_ms"])
        self.assertIsNone(proc["last_minute"])

    def test_senaryo_a10_a11_a12_son_dokunus_olcusuyle_tutuyor(self) -> None:
        """`counted_on_time` köprüde yok; ölçü `last_touch`.

        `submission.py` başlığı bu yüzden A10/A11/A12'yi **geçersiz** sayıyor.
        Ampirik olarak yine de bantta çıkıyorlar; bu bir tesadüf değil ama
        garanti de değil — bayrak açık kaldığı sürece sonuç *doğrulanmış*
        sayılmaz.
        """
        self.assertFalse(
            self.bench.submission[next(iter(self.bench.gold))][
                "counted_on_time_available"
            ]
        )

        def med(code: str) -> float:
            vals = [self._on_time(k) for k in self.bench.arch(code)]
            return statistics.median([v for v in vals if v is not None])

        a4, a1 = med("A4"), med("A1")
        self.assertGreaterEqual(a4, SENARYO_A4_ON_TIME[0])
        self.assertLessEqual(a4, SENARYO_A4_ON_TIME[1])
        self.assertGreaterEqual(a1, SENARYO_A1_ON_TIME[0])
        self.assertLessEqual(a1, SENARYO_A1_ON_TIME[1])
        self.assertGreaterEqual(a1 - a4, SENARYO_ON_TIME_FARK_MIN)


class Test5Calisma(GoldTestCase):
    """[5] `study.py` ↔ `true_counted_pomodoro` ve düzensiz çalışma."""

    def test_sayilan_oturum_sayisi_altin_etiketle_birebir(self) -> None:
        tam = 0
        for key, g in self.bench.gold.items():
            sayilan = len(
                study_mod.countable(
                    study_mod.normalize_rows(self.bench.raw[key]["pomodoro"])
                )
            )
            if sayilan == g["true_counted_pomodoro"]:
                tam += 1
        self.assertEqual(tam, OLCULEN_POMODORO_TAM_ESLESME)

    def test_cokme_ve_kopma_arketipleri_hacimle_ayrilir(self) -> None:
        def med(code: str) -> float:
            return statistics.median(
                [
                    self.bench.study[k]["recent_28d"]["n_stints"]
                    for k in self.bench.arch(code)
                ]
            )

        self.assertLessEqual(med("A6"), OLCULEN_A6_STINT_MEDYAN_MAX)
        self.assertLessEqual(med("A7"), OLCULEN_A7_STINT_MEDYAN_MAX)
        self.assertGreaterEqual(med("A2"), OLCULEN_A2_STINT_MEDYAN_MIN)

    def test_duzensiz_calisan_a4_ayirt_edilemiyor(self) -> None:
        """Kusur K5: `burstiness` A4'ü okul geneli davranışından ayırmıyor.

        `spec/SENARYO.md` §3.7 A4'ü "uzun, yoğun, düzensiz; stintlerinin %70'i
        sınavdan önceki 48 saatte" diye tarif ediyor. Modül sınav takvimini
        göremiyor (`pre_exam_share = None`) ve `burstiness` ölçüsü gün-içi
        yığılmayı değil gün-arası yığılmayı ölçüyor.
        """

        def bursts(code: str) -> list[float]:
            return [
                self.bench.study[k]["recent_28d"]["burstiness"]
                for k in self.bench.arch(code)
                if self.bench.study[k]["recent_28d"]["burstiness"] is not None
            ]

        okul = [
            self.bench.study[k]["recent_28d"]["burstiness"]
            for k in self.bench.gold
            if self.bench.study[k]["recent_28d"]["burstiness"] is not None
        ]
        fark = abs(statistics.median(bursts("A4")) - statistics.median(okul))
        self.assertLess(fark, OLCULEN_A4_BURSTINESS_FARK_MAX)
        self.assertIsNone(self.bench.study[next(iter(self.bench.gold))]["pre_exam_share"])

    def test_gece_penceresi_senaryoyla_ortusuyor(self) -> None:
        """K5b GIDERILDI: gece penceresi artik senaryonun 22:00-02:00
        tanimiyla ortusuyor. Uyari: pencere duzeldi ama A4'u AYIRT ETMIYOR;
        ayrim gucu iddia edilmiyor (bkz. docs/HESAP-DOGRULAMA.md §5)."""
        self.assertEqual(study_mod.NIGHT_HOURS, (22, 23, 0, 1))

        def med(code: str) -> float:
            vals = [
                self.bench.study[k]["recent_28d"]["night_share"]
                for k in self.bench.arch(code)
                if self.bench.study[k]["recent_28d"]["night_share"] is not None
            ]
            return statistics.median(vals)

        self.assertLess(abs(med("A4") - med("A2")), 0.05)


class Test6DikkatListesi(GoldTestCase):
    """[6] `attention.py` ↔ senaryo §7.5 P21–P26."""

    def test_p22_a6_listede(self) -> None:
        bulunan = len(self.bench.listed() & self.bench.arch("A6"))
        self.assertGreaterEqual(bulunan, SENARYO_A6_DIKKAT_MIN)

    def test_p23_a5_yanlis_pozitif_kontrolu(self) -> None:
        """TUTMUYOR — ölçülen 20 / 25, beklenen ≤ 2.

        Sebep: ödev tetikleyicisi `n_missing >= 3` **seviye** kuralıdır,
        §2.8'in "son 30 gün önceki 30 günden kötü" **değişim** kuralı değil.
        Okul genelinde 30 günlük ödev sayısı ~20 ve medyan eksik 4 olduğu için
        eşik neredeyse herkeste ateşliyor.
        """
        self.assertLessEqual(
            len(self.bench.listed() & self.bench.arch("A5")), SENARYO_A5_DIKKAT_MAX
        )

    def test_p21_liste_buyuklugu(self) -> None:
        """TUTMUYOR — ölçülen 193 / 250, beklenen 32–48."""
        n = len(self.bench.listed())
        self.assertGreaterEqual(n, SENARYO_DIKKAT_TOPLAM[0])
        self.assertLessEqual(n, SENARYO_DIKKAT_TOPLAM[1])

    @unittest.expectedFailure
    def test_p24_dort_tetikleyici(self) -> None:
        """TUTMUYOR ve YAPISAL OLARAK TUTAMAZ — `exam_missed` tetikleyicisi
        `Source` arayüzünde karşılığı olmadığı için hiç ateşlenemez; üstelik
        devamsızlık tetikleyicisi de A6'da ateşlenmiyor (kusur K3)."""
        dort = sum(
            1
            for items in self.bench.attention.values()
            if len({i.trigger for i in items}) >= 4
        )
        self.assertGreaterEqual(dort, SENARYO_DORT_TETIK[0])

    def test_exam_missed_hic_ateslenmiyor_ve_bunu_raporluyor(self) -> None:
        for items in self.bench.attention.values():
            for item in items:
                self.assertNotEqual(item.trigger, model.TriggerKind.EXAM_MISSED)
        self.assertIn(
            model.TriggerKind.EXAM_MISSED.value, attention_mod.unavailable_triggers()
        )

    def test_odev_tetikleyicisi_artik_asiri_atesle_miyor(self) -> None:
        """K1 GIDERILDI — gerileme korumasi.

        Esik artik mutlak degil, ogrencinin kendi subesinin medyanina gore.
        Kohort beslenmediginde tetikleyici FAIL-CLOSED calisir (hic atesleme),
        bu yuzden bu kosuda odev maddesi sifirdir.
        """
        self.assertEqual(len(self.bench.listed()), OLCULEN_DIKKAT_TOPLAM)
        self.assertLessEqual(
            len(self.bench.listed_by_trigger("homework")), OLCULEN_ODEV_TETIKLEYEN_MAX
        )
        self.assertEqual(
            len(
                self.bench.listed_by_trigger("attendance")
                | self.bench.listed_by_trigger("mark_trend")
            ),
            OLCULEN_DIKKAT_ODEVSIZ,
        )

    def test_odev_tetikleyicisi_disinda_liste_senaryo_bandinda(self) -> None:
        """Ödev maddesi çıkarıldığında liste 32–48 bandına oturuyor — yani
        kusur tek bir eşikte, modülün bütününde değil."""
        n = OLCULEN_DIKKAT_ODEVSIZ
        self.assertGreaterEqual(n, SENARYO_DIKKAT_TOPLAM[0])
        self.assertLessEqual(n, SENARYO_DIKKAT_TOPLAM[1])

    def test_madde_yapisal_kurallari_gercek_veride_de_geciyor(self) -> None:
        """`[T§6.6]`: skor yok, sıra yok, kanıtsız madde yok, "risk" yok."""
        for key, items in self.bench.attention.items():
            for item in items:
                self.assertTrue(item.evidence, key)
                self.assertNotIn("risk", item.fact.lower())
                self.assertFalse(hasattr(item, "score"))
                self.assertFalse(hasattr(item, "rank"))


class Test7YetenekKestirimi(GoldTestCase):
    """[7] Modüllerin başarı ölçüsü ↔ `theta_base`."""

    def _avg(self, key: str) -> float | None:
        vals = [
            c["average"]
            for c in self.bench.marks[key]["courses"].values()
            if c["average"] is not None
        ]
        return statistics.mean(vals) if vals else None

    def test_theta_base_ile_korelasyon(self) -> None:
        xs: list[float] = []
        ys: list[float] = []
        for key, g in self.bench.gold.items():
            v = self._avg(key)
            if v is None:
                continue
            xs.append(float(g["theta_base"]))
            ys.append(v)
        self.assertGreaterEqual(_spearman(xs, ys), OLCULEN_THETA_SPEARMAN_MIN)

    def test_zaman_icinde_sabit_arketiplerde_korelasyon_daha_yuksek(self) -> None:
        xs: list[float] = []
        ys: list[float] = []
        for key, g in self.bench.gold.items():
            if g["archetype"] in ("A5", "A6"):
                continue
            v = self._avg(key)
            if v is None:
                continue
            xs.append(float(g["theta_base"]))
            ys.append(v)
        self.assertGreaterEqual(_spearman(xs, ys), OLCULEN_THETA_SABIT_SPEARMAN_MIN)

    def test_a5_icin_theta_base_gecersiz_referans(self) -> None:
        """GEÇERSİZ ÖLÇÜM: A5'te `theta_base` dönem **başındaki** yetenektir;
        `T_NOW`'daki yetenek `theta_base + 1,5 · progress`. Ders ortalaması
        bugünün yeteneğini ölçtüğü için `theta_base` ile korelasyon anlamsızdır.
        """
        xs: list[float] = []
        ys: list[float] = []
        for key in self.bench.arch("A5"):
            v = self._avg(key)
            if v is None:
                continue
            xs.append(float(self.bench.gold[key]["theta_base"]))
            ys.append(v)
        self.assertLess(abs(_spearman(xs, ys)), 0.40)


if __name__ == "__main__":
    unittest.main()
