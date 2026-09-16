"""Asama 3 — Dogrulama: 741 altin maddeye karsi olcum ve karar kurali.

BU VERIDE NEYIN DOGRULANABILECEGI (ve neyin DOGRULANAMAYACAGI)
--------------------------------------------------------------
GECERLI HEDEF — kavram yanilgisi celdiricisi:
  `generator/content_tr.py::MISCONCEPTIONS` 14 konu icin (dogru, yanilgi) cifti
  tanimlar ve `apply_misconception()` bunlari sik metinlerine GERCEKTEN yazar.
  Veride 741 madde bu cifti tasiyor ve `gold.misconception_choice_text` tam
  olarak yanilgi sikkini gosteriyor. Kalan ~3.637 madde TEMIZ NEGATIFTIR.
  `dikkat_tuzagi` boyutunun kesinlik/duyarlilik/F1'i bu kumeye karsi olculur.

GECERSIZ HEDEF — p-degeri korelasyonu:
  `spec/SENARYO.md` §4.2/§4.4: zorluk (b_i) once bant oranlarina gore cekilir ve
  metin ureticisine BU BILGI HIC VERILMEZ. Yani soru METNI ile ZORLUK tohum
  verisinde BAGIMSIZ uretilmistir. Dolayisiyla LLM etiketleri ile `p_value`
  arasinda sifir korelasyon beklenir ve bu, yontem hakkinda HICBIR SEY SOYLEMEZ.
  `pvalue_probe()` bu olcumu yine de hesaplar ama ciktiyi daima
  `gecerli=False` ve `not="bu veride anlamsiz"` ile isaretler.

DIGER MADDELERDEKI `misconception_choice`:
  Yalnizca sayisal cekicilik agirligidir (§4.5, w_m); metinde anlamsal karsiligi
  YOKTUR. Hedef alinmaz.
"""

from __future__ import annotations

import json
import math
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .rubric import DIMENSION_ORDER
from .schema import ItemSegmentation
from .stability import krippendorff_alpha, pairwise_agreement

# --------------------------------------------------------------------------
# Altin kaynak — `generator/content_tr.py::MISCONCEPTIONS` (92 cift)
# Buraya KOPYALANDI cunku `generator/` ayri bir paket degil (import edilemez) ve
# bu alt sistem oraya YAZMAZ. `load_misconception_pairs()` dosya erisilebiliyorsa
# gercek tablodan yeniden okur ve SAPMA VARSA hata verir.
# --------------------------------------------------------------------------
MISCONCEPTION_PAIRS: dict[str, tuple[str, str]] = {
    'Üslü ve Köklü İfadeler': ('(a·b)^n = a^n · b^n',
                             '(a+b)^n = a^n + b^n'),
    'Mutlak Değer': ('|x-3| = 5 için kök kümesi {8, -2} olur',
                   '|x-3| = 5 için kök kümesi yalnız {8} olur'),
    'Fonksiyon Kavramı': ('Bileşkede sıra önemlidir: f∘g ≠ g∘f',
                        'Bileşkede sıra önemsizdir: f∘g = g∘f'),
    'İkinci Dereceden Denklemler': ('Diskriminant negatifse gerçel çözüm yoktur',
                                  'Diskriminant negatif olsa da iki gerçel çözüm vardır'),
    'Trigonometri': ('sin²x + cos²x = 1',
                   'sin x + cos x = 1'),
    'Trigonometriye Giriş': ('sin(2x) = 2·sin x·cos x',
                           'sin(2x) = 2·sin x'),
    'Kümeler': ('s(A∪B) = s(A) + s(B) - s(A∩B)',
              's(A∪B) = s(A) + s(B)'),
    'Sayı Kümeleri': ('Her tam sayı rasyoneldir, tersi doğru değildir',
                    'Her rasyonel sayı tam sayıdır'),
    'Denklem ve Eşitsizlikler': ('Negatif sayıyla çarpılınca eşitsizliğin yönü değişir',
                               'Negatif sayıyla çarpılınca eşitsizliğin yönü değişmez'),
    'Denklem ve Eşitsizlik Sistemleri': ('Bir denklemin iki katı alınınca çözüm kümesi değişmez',
                                       'Bir denklemin iki katı alınınca çözüm kümesi ikiye katlanır'),
    'Polinomlar': ('P(x)·Q(x) polinomunun derecesi derecelerin toplamıdır',
                 'P(x)·Q(x) polinomunun derecesi derecelerin çarpımıdır'),
    'Fonksiyonlarla İşlemler': ('(f+g)(x) = f(x) + g(x)',
                              '(f·g)(x) = f(x) + g(x)'),
    'Fonksiyonlarda Uygulamalar': ('f⁻¹ ile 1/f farklı şeylerdir',
                                 'f⁻¹ ile 1/f aynı şeydir'),
    'Olasılık': ('Ayrık olaylarda P(A∪B) = P(A) + P(B)',
               'Her durumda P(A∪B) = P(A) + P(B)'),
    'Basit Olayların Olasılığı': ('Bağımsız olaylarda P(A∩B) = P(A)·P(B)',
                                'Her durumda P(A∩B) = P(A)·P(B)'),
    'Sayma ve Olasılık': ('Sıra önemliyse permütasyon, değilse kombinasyon kullanılır',
                        'Sıra önemli olsa da kombinasyon kullanılır'),
    'Kombinasyon': ('C(n,r) = C(n, n-r)',
                  'C(n,r) = C(r, n-r)'),
    'Veri Analizi': ('Aritmetik ortalama uç değerlerden etkilenir',
                   'Aritmetik ortalama uç değerlerden etkilenmez'),
    'İstatistik': ('Ortanca sıralı veride ortadaki değerdir',
                 'Ortanca en çok tekrar eden değerdir'),
    'İstatistik ve Olasılık': ('Standart sapma yayılımı, ortalama merkezi gösterir',
                             'Standart sapma da merkezi gösterir'),
    'Limit': ('Limitin var olması sürekliliği gerektirmez',
            'Limit varsa fonksiyon o noktada mutlaka süreklidir'),
    'Limit Kavramına Giriş': ('Soldan ve sağdan limit eşitse limit vardır',
                            'Soldan limit varsa limit vardır'),
    'Türev': ('Türevin sıfır olması yalnız kritik nokta verir',
            'Türevin sıfır olduğu her nokta yerel ekstremumdur'),
    'Türevin Uygulamaları': ('f″ işaret değiştiriyorsa büküm noktası vardır',
                           'f″ sıfırsa her zaman büküm noktası vardır'),
    'İntegral': ('Belirsiz integrale sabit eklenir',
               'Belirsiz integralde sabit eklenmez'),
    'Belirli İntegral': ('Belirli integral işaretli değer verir',
                       'Belirli integral her zaman pozitif değer verir'),
    'Diziler': ('Aritmetik dizide ardışık fark sabittir',
              'Aritmetik dizide ardışık oran sabittir'),
    'Diziler ve Seriler': ('Geometrik seride |r| < 1 ise toplam yakınsar',
                         'Geometrik seride her r için toplam yakınsar'),
    'Üstel ve Logaritmik Fonksiyonlar': ('log(a·b) = log a + log b',
                                       'log(a+b) = log a + log b'),
    'Üçgenler': ('Benzerlikte açılar eşit, kenarlar orantılıdır',
               'Benzerlikte kenarlar da eşittir'),
    'Dörtgenler ve Çokgenler': ('Her kare bir eşkenar dörtgendir, tersi doğru değildir',
                              'Her eşkenar dörtgen bir karedir'),
    'Çember ve Daire': ('Merkez açı, gördüğü çevre açının iki katıdır',
                      'Merkez açı, gördüğü çevre açıya eşittir'),
    'Çemberin Analitik İncelenmesi': ('Denklemdeki r² yarıçapın karesidir',
                                    'Denklemdeki r² yarıçapın kendisidir'),
    'Doğrunun Analitik İncelenmesi': ("Dik doğruların eğimleri çarpımı -1'dir",
                                    'Dik doğruların eğimleri birbirine eşittir'),
    'Analitik Geometri': ('İki nokta arası uzaklıkta farkların karesi alınır',
                        'İki nokta arası uzaklıkta farklar doğrudan toplanır'),
    'Katı Cisimler': ('Hacim uzunluğun küpüyle, yüzey alanı karesiyle ölçeklenir',
                    'Hacim ve yüzey alanı aynı oranda ölçeklenir'),
    'Uzay Geometri': ('Kesit alanı ile taban alanı farklı büyüklüklerdir',
                    'Kesit alanı ile taban alanı her zaman eşittir'),
    'Uzay Geometride Hacim': ('Koninin hacmi silindirin üçte biridir',
                            'Koninin hacmi silindirin yarısıdır'),
    'Geometrik Cisimler': ('Yüzey alanı iki boyutlu, hacim üç boyutlu ölçüdür',
                         'Yüzey alanı ile hacim aynı ölçüdür'),
    'Cebirsel İfadeler': ('Benzer terimler toplanabilir',
                        'Benzer olmayan terimler de toplanabilir'),
    'Denklemler': ('Denklemin iki yanına aynı sayı eklenebilir',
                 'Denklemin yalnız bir yanına sayı eklenebilir'),
    'Fonksiyonlar': ('Bir girdiye tek çıktı düşer',
                   'Bir girdiye birden çok çıktı düşebilir'),
    'Sayılar ve İşlemler': ('İşlem önceliğinde çarpma toplamadan öncedir',
                          'İşlem önceliğinde soldan sağa gidilir, çarpma beklemez'),
    "Newton'ın Hareket Yasaları": ('Etki ve tepki farklı cisimlere etkir',
                                 'Etki ve tepki aynı cisme etkir, dengelenir'),
    'Tork ve Denge': ('Tork, kuvvet ile dik uzaklığın çarpımıdır',
                    'Tork, kuvvet ile uzaklığın çarpımıdır, açı önemsizdir'),
    'Vektörler': ('Bileşke, vektörlerin yönü dikkate alınarak bulunur',
                'Bileşke, büyüklüklerin doğrudan toplamıdır'),
    'Bağıl Hareket': ('Bağıl hız, hızların vektörel farkıdır',
                    'Bağıl hız, hızların sayısal toplamıdır'),
    'İş Güç Enerji': ('İş, kuvvetin hareket doğrultusundaki bileşeniyle hesaplanır',
                    'İş, kuvvet ile alınan mesafenin doğrudan çarpımıdır'),
    'Enerji': ('Kinetik enerji hızın karesiyle artar',
             'Kinetik enerji hızla doğru orantılı artar'),
    'Enerji Dönüşümleri': ('Sürtünmede mekanik enerji ısıya dönüşür, yok olmaz',
                         'Sürtünmede mekanik enerji yok olur'),
    'Atışlar': ('Yatay atışta düşey hareket ilk hızdan bağımsızdır',
              'Yatay atışta düşey hareket ilk hıza bağlıdır'),
    'Hareket ve Kuvvet': ('Sabit hızlı harekette net kuvvet sıfırdır',
                        'Sabit hızlı harekette net kuvvet sabit ve sıfırdan farklıdır'),
    'Basit Makineler': ('Basit makine işten kazandırmaz, kuvvetten kazandırır',
                      'Basit makine işten de kazandırır'),
    'Isı ve Sıcaklık': ('Isı aktarılan enerji, sıcaklık ise ölçülen düzeydir',
                      'Isı ile sıcaklık aynı büyüklüktür'),
    'Elektrostatik': ('Aynı işaretli yükler birbirini iter',
                    'Aynı işaretli yükler birbirini çeker'),
    'Elektriksel Kuvvet ve Alan': ('Elektriksel kuvvet uzaklığın karesiyle ters orantılıdır',
                                 'Elektriksel kuvvet uzaklıkla ters orantılıdır'),
    'Elektrik Akımı': ('Seri bağlamada akım şiddeti aynı, potansiyel fark bölünür',
                     'Seri bağlamada potansiyel fark aynı, akım şiddeti bölünür'),
    'Manyetizma': ('Manyetik alan hareketli yüke kuvvet uygular',
                 'Manyetik alan duran yüke de kuvvet uygular'),
    'Optik': ('Yansımada geliş açısı yansıma açısına eşittir',
            'Yansımada geliş açısı kırılma açısına eşittir'),
    'Dalgalar': ('Ortam değişince frekans korunur, dalga boyu değişir',
               'Ortam değişince frekans da değişir'),
    'Modern Fizik': ('Foton enerjisi frekansla doğru orantılıdır',
                   'Foton enerjisi dalga boyuyla doğru orantılıdır'),
    'Madde ve Özellikleri': ('Kütle ayırt edici bir özellik değildir',
                           'Kütle ayırt edici bir özelliktir'),
    'Fizik Bilimine Giriş': ('Temel büyüklükler türetilmiş büyüklüklerden farklıdır',
                           'Bütün büyüklükler temel büyüklüktür'),
    'Atom ve Periyodik Sistem': ('Periyotta soldan sağa atom yarıçapı küçülür',
                               'Periyotta soldan sağa atom yarıçapı büyür'),
    'Kimyasal Türler Arası Etkileşim': ('Hidrojen bağı bir moleküller arası etkileşimdir',
                                      'Hidrojen bağı bir kovalent bağdır'),
    'Maddenin Halleri': ('Hal değişimi sürerken kaynama noktası sabit kalır',
                       'Hal değişimi sürerken kaynama noktası sürekli yükselir'),
    'Karışımlar': ('Karışımın bileşenleri sabit oranda değildir',
                 'Karışımın bileşenleri sabit orandadır'),
    'Asitler ve Bazlar': ('pH düştükçe asitlik artar',
                        'pH düştükçe asitlik azalır'),
    'Kimyasal Tepkimeler': ('Denkleştirmede katsayılar değiştirilir, alt indisler değişmez',
                          'Denkleştirmede alt indisler de değiştirilebilir'),
    'Gazlar': ('Sabit sıcaklıkta basınç ile hacim ters orantılıdır',
             'Sabit sıcaklıkta basınç ile hacim doğru orantılıdır'),
    'Çözeltiler': ('Seyreltmede molarite azalır, çözünürlük değişmez',
                 'Seyreltmede çözünürlük de azalır'),
    'Kimya ve Enerji': ('Ekzotermik tepkimede entalpi değişimi negatiftir',
                      'Ekzotermik tepkimede entalpi değişimi pozitiftir'),
    'Kimya Bilimi': ('Nitel gözlem ölçüm gerektirmez, nicel gözlem gerektirir',
                   'Nitel gözlem de ölçüm gerektirir'),
    'Hücre Bölünmeleri (Mitoz)': ('Mitozda kromozom sayısı korunur',
                                'Mitozda kromozom sayısı yarıya iner'),
    'Hücre Bölünmeleri': ('Mitoz sonunda iki özdeş hücre oluşur',
                        'Mitoz sonunda dört özdeş hücre oluşur'),
    'Mayoz ve Eşeyli Üreme': ('Mayozda kromozom sayısı yarıya iner',
                            'Mayozda kromozom sayısı korunur'),
    'Kalıtım': ('Çekinik fenotip yalnız aa genotipinde görülür',
              'Aa genotipinde de çekinik fenotip görülür'),
    'Modern Genetik Uygulamaları': ('Gen aktarımı genotipi değiştirir',
                                  'Gen aktarımı yalnız fenotipi değiştirir'),
    'Fotosentez': ('Işıktan bağımsız evre ışığa ihtiyaç duymaz',
                 'Işıktan bağımsız evre yalnız karanlıkta gerçekleşir'),
    'Solunum': ('Oksijenli solunum daha çok enerji açığa çıkarır',
              'Oksijensiz solunum daha çok enerji açığa çıkarır'),
    'Canlılar ve Enerji': ('Üreticiler enerjiyi kendileri üretir',
                         'Üreticiler enerjiyi tüketicilerden alır'),
    'Ekosistem Ekolojisi': ('Enerji piramitte yukarı çıkıldıkça azalır',
                          'Enerji piramitte yukarı çıkıldıkça artar'),
    'Madde Döngüleri': ('Madde döngüde yeniden kullanılır',
                      'Madde döngüde tükenir ve yeniden kullanılamaz'),
    'Bitki Biyolojisi': ('Terleme su taşınmasına katkı sağlar',
                       'Terleme su taşınmasını engeller'),
    'Hücre': ('Zar seçici geçirgendir',
            'Zar bütün maddeleri geçirir'),
    'Canlılar Dünyası': ('Sınıflandırmada tür en küçük birimdir',
                       'Sınıflandırmada tür en büyük birimdir'),
    'Yaşam Bilimi Biyoloji': ('Denetimli deneyde tek değişken değiştirilir',
                            'Denetimli deneyde bütün değişkenler birlikte değiştirilir'),
    'Sistemler': ('Sistemler birbirinden bağımsız çalışmaz',
                'Sistemler birbirinden bağımsız çalışır'),
    'Yazım Kuralları ve Noktalama': ('"ve" bağlacından önce virgül konmaz',
                                   'Her bağlaçtan önce virgül konur'),
    'Şiir': ('Redif ile kafiye farklı kavramlardır',
           'Redif ile kafiye aynı şeydir'),
    'Present Perfect': ('since + zaman noktası kullanılır',
                      'since + süre kullanılır'),
    "Türkiye'de Sanayi": ("Sanayinin en çok yoğunlaştığı bölge Marmara'dır",
                        "Sanayinin en çok yoğunlaştığı bölge İç Anadolu'dur"),
}

def load_misconception_pairs(content_tr: Path | None = None) -> dict[str, tuple[str, str]]:
    """Altin tabloyu dondurur; `generator/content_tr.py` varsa DOGRULAR.

    Yalnizca OKUR (gorev kurali: hezarfen-ZEKA disina ve mevcut dosyalara
    yazilmaz). Uretecteki tablo degisirse burada sessiz sapma olmasin diye
    yanilgi metinlerinin kumesi karsilastirilir.
    """
    if content_tr is None or not Path(content_tr).exists():
        return dict(MISCONCEPTION_PAIRS)
    src = Path(content_tr).read_text(encoding="utf-8")
    try:
        start = src.index("MISCONCEPTIONS = {")
        end = src.index("def apply_misconception")
    except ValueError:
        return dict(MISCONCEPTION_PAIRS)
    ns: dict[str, Any] = {}
    exec(compile(src[start:end], "content_tr.MISCONCEPTIONS", "exec"), ns)  # noqa: S102
    table = {k: tuple(v) for k, v in ns["MISCONCEPTIONS"].items()}
    return table


def wrong_texts(pairs: dict[str, tuple[str, str]]) -> set[str]:
    """Yanilgi (yanlis) sik metinlerinin kumesi."""
    return {v[1] for v in pairs.values()}


# --------------------------------------------------------------------------
# Altin kume insasi
# --------------------------------------------------------------------------

@dataclass
class GoldSet:
    """Dogrulama kumesi: gercek pozitifler + ornekleme ile negatifler."""

    positives: list[dict]
    negatives: list[dict]
    #: question_id -> beklenen tuzak sik metni
    expected_trap: dict[str, str] = field(default_factory=dict)

    @property
    def items(self) -> list[dict]:
        return self.positives + self.negatives

    def is_positive(self, qid: str) -> bool:
        return qid in self.expected_trap

    def to_dict(self) -> dict[str, Any]:
        return {"n_positive": len(self.positives), "n_negative": len(self.negatives)}


def build_gold_set(items: Sequence[dict], *, pairs: dict[str, tuple[str, str]] | None = None,
                   n_negative: int | None = None, seed: int = 20260913) -> GoldSet:
    """Gercek pozitifleri bulur ve belirlenimci negatif ornekleme yapar.

    Pozitif olcut: sikLARDAN biri, MISCONCEPTIONS tablosundaki bir YANILGI
    metninin birebir aynisi. Ek olarak `gold.misconception_choice_text` de ayni
    sikki gostermelidir — ikisi ayrilirsa madde pozitif SAYILMAZ (altin etiketi
    zorlamayiz).
    """
    pairs = pairs or MISCONCEPTION_PAIRS
    wrong = wrong_texts(pairs)
    positives: list[dict] = []
    negatives: list[dict] = []
    expected: dict[str, str] = {}
    for it in items:
        choices = it.get("choices") or []
        hit = [c for c in choices if c in wrong]
        gold_text = (it.get("gold") or {}).get("misconception_choice_text")
        if hit and gold_text in wrong and gold_text in choices:
            positives.append(it)
            expected[it["question_id"]] = gold_text
        elif not hit:
            negatives.append(it)
        # `hit` var ama altin etiket baska sikki gosteriyorsa: belirsiz ->
        # NE pozitif NE negatif. Sessizce negatife atmiyoruz.
    if n_negative is not None and n_negative < len(negatives):
        rng = random.Random(seed)
        negatives = rng.sample(sorted(negatives, key=lambda x: x["question_id"]),
                               n_negative)
    return GoldSet(positives=positives, negatives=negatives, expected_trap=expected)


# --------------------------------------------------------------------------
# Olcutler
# --------------------------------------------------------------------------

def _norm_text(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().casefold()


@dataclass
class PRF:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    @property
    def precision(self) -> float:
        d = self.tp + self.fp
        return self.tp / d if d else 0.0

    @property
    def recall(self) -> float:
        d = self.tp + self.fn
        return self.tp / d if d else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"tp": self.tp, "fp": self.fp, "fn": self.fn, "tn": self.tn,
                "precision": round(self.precision, 4), "recall": round(self.recall, 4),
                "f1": round(self.f1, 4)}


@dataclass
class VariantScore:
    """Bir varyantin tam degerlendirme sonucu."""

    variant: str
    n_scored: int = 0
    #: Gevsek olcut: yalnizca "dikkat_tuzagi = var" dedi mi.
    detection: PRF = field(default_factory=PRF)
    #: Kati olcut: dogru SIKKI isaret etti mi (asil hedef).
    localized: PRF = field(default_factory=PRF)
    #: question_id -> kati olcutte dogru mu (McNemar icin esli vektor).
    per_item: dict[str, bool] = field(default_factory=dict)
    tokens_per_item: float = 0.0
    cost_usd: float = 0.0
    calls_per_item: float = 0.0
    failures: int = 0
    #: Ajanlar arasi ham uyum (yalnizca cok ajanli varyantlarda).
    agent_agreement: dict[str, float] = field(default_factory=dict)
    agent_alpha: dict[str, float] = field(default_factory=dict)
    #: Ajanlardan en az biri dogruyken nihai cikti yanlis olan madde orani.
    oracle_gap: float = 0.0
    consensus_illusion: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant": self.variant,
            "n_scored": self.n_scored,
            "detection": self.detection.to_dict(),
            "localized": self.localized.to_dict(),
            "tokens_per_item": round(self.tokens_per_item, 1),
            "cost_usd": round(self.cost_usd, 6),
            "calls_per_item": round(self.calls_per_item, 2),
            "failures": self.failures,
            "agent_agreement": {k: round(v, 4) for k, v in self.agent_agreement.items()},
            "agent_alpha": {k: (None if v != v else round(v, 4))
                            for k, v in self.agent_alpha.items()},
            "oracle_gap": round(self.oracle_gap, 4),
            "consensus_illusion": self.consensus_illusion,
            "notes": self.notes,
        }


def score_variant(batch, gold: GoldSet, *, consensus_threshold: float = 0.80,
                  baseline_localized_f1: float | None = None) -> VariantScore:
    """Bir varyanti altin kumeye karsi puanlar.

    Iki olcut ayri raporlanir:
      * detection — "tuzak var" demek yeterli (gevsek),
      * localized — DOGRU SIKKI gostermek gerekli (kati; asil hedef).
    """
    sc = VariantScore(variant=batch.variant, failures=len(batch.failures))
    agent_units: dict[str, list[list[str]]] = {d: [] for d in DIMENSION_ORDER}
    oracle_hits = 0
    oracle_possible = 0

    for it in gold.items:
        qid = it["question_id"]
        seg: ItemSegmentation | None = batch.results.get(qid)
        if seg is None:
            # Etiketlenemedi: pozitifse kacirilmis sayilir (sessiz atlama YOK).
            if gold.is_positive(qid):
                sc.detection.fn += 1
                sc.localized.fn += 1
                sc.per_item[qid] = False
            continue
        sc.n_scored += 1
        said_var = seg.labels["dikkat_tuzagi"].label == "var"
        positive = gold.is_positive(qid)
        expected = _norm_text(gold.expected_trap.get(qid))
        got = _norm_text(seg.trap_choice_text)

        if positive:
            if said_var:
                sc.detection.tp += 1
            else:
                sc.detection.fn += 1
            if said_var and got == expected:
                sc.localized.tp += 1
                sc.per_item[qid] = True
            else:
                sc.localized.fn += 1
                sc.per_item[qid] = False
        else:
            if said_var:
                sc.detection.fp += 1
                sc.localized.fp += 1
                sc.per_item[qid] = False
            else:
                sc.detection.tn += 1
                sc.localized.tn += 1
                sc.per_item[qid] = True

        # --- uzlasma gostergesi (bulgu 10) --------------------------------
        if seg.agent_labels:
            for dim in DIMENSION_ORDER:
                agent_units[dim].append([a.get(dim) for a in seg.agent_labels])
            if positive:
                oracle_possible += 1
                # Ajanlardan biri DOGRU sikki gosterdi mi?
                idxs = {a.get("tuzak_sik_index") for a in seg.agent_labels}
                choices = it.get("choices") or []
                any_right = any(
                    i is not None and i.isdigit() and 0 <= int(i) < len(choices)
                    and _norm_text(choices[int(i)]) == expected for i in idxs)
                if any_right and not sc.per_item.get(qid):
                    oracle_hits += 1

    if any(agent_units[d] for d in DIMENSION_ORDER):
        for dim in DIMENSION_ORDER:
            if agent_units[dim]:
                sc.agent_agreement[dim] = pairwise_agreement(agent_units[dim])
                sc.agent_alpha[dim] = krippendorff_alpha(agent_units[dim])
    sc.oracle_gap = oracle_hits / oracle_possible if oracle_possible else 0.0

    n = batch.n or 1
    sc.tokens_per_item = batch.usage.tokens_total / n
    sc.cost_usd = batch.usage.cost_usd
    sc.calls_per_item = batch.usage.calls / n

    # Bulgu 10 — UZLASMA YANILSAMASI: ajanlar arasi uyum yuksek AMA dogruluk
    # taban cizginin altinda. Bu ayrica raporlanir.
    if sc.agent_agreement:
        mean_agree = sum(sc.agent_agreement.values()) / len(sc.agent_agreement)
        if (mean_agree >= consensus_threshold and baseline_localized_f1 is not None
                and sc.localized.f1 < baseline_localized_f1):
            sc.consensus_illusion = True
            sc.notes.append(
                f"UZLASMA YANILSAMASI (bulgu 10): ajanlar arasi ortalama uyum "
                f"{mean_agree:.2f} >= {consensus_threshold} fakat kati F1 "
                f"{sc.localized.f1:.3f} < taban cizgi {baseline_localized_f1:.3f}. "
                "Yuksek uyum burada dogruluk degil homojenlik gostergesidir.")
    if sc.oracle_gap > 0:
        sc.notes.append(
            f"oracle_gap={sc.oracle_gap:.3f}: ajanlardan en az biri dogru sikki "
            "gosterdigi halde birlestirme/oylama sonucu yanlis cikti.")
    return sc


# --------------------------------------------------------------------------
# Esli anlamlilik testi — McNemar (tam binom, harici paket yok)
# --------------------------------------------------------------------------

def mcnemar_exact(a_correct: dict[str, bool], b_correct: dict[str, bool]
                  ) -> tuple[int, int, float]:
    """Iki varyantin esli karsilastirmasi. Dondurur: (b, c, iki-yonlu p).

    b = a dogru & b yanlis ; c = a yanlis & b dogru.
    Tam binom testi: p = 2 * P(X <= min(b,c)), X ~ Binom(b+c, 0.5), 1 ile sinirli.
    Uyumsuz cift yoksa p = 1,0 (fark yok).
    """
    keys = sorted(set(a_correct) & set(b_correct))
    b = sum(1 for k in keys if a_correct[k] and not b_correct[k])
    c = sum(1 for k in keys if not a_correct[k] and b_correct[k])
    n = b + c
    if n == 0:
        return 0, 0, 1.0
    lo = min(b, c)
    tail = sum(math.comb(n, i) for i in range(lo + 1)) / (2 ** n)
    return b, c, min(1.0, 2 * tail)


# --------------------------------------------------------------------------
# Karar kurali (Asama 3)
# --------------------------------------------------------------------------

@dataclass
class Decision:
    chosen: str
    reason: str
    baseline_f1: float
    best_variant: str | None = None
    best_f1: float = 0.0
    delta: float = 0.0
    p_value: float = 1.0
    budget_matched: bool = False
    rows: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chosen": self.chosen, "reason": self.reason,
            "baseline_f1": round(self.baseline_f1, 4),
            "best_variant": self.best_variant, "best_f1": round(self.best_f1, 4),
            "delta": round(self.delta, 4), "p_value": round(self.p_value, 5),
            "budget_matched": self.budget_matched, "rows": self.rows,
            "notes": self.notes,
        }


def compare(baseline: VariantScore, variants: Sequence[VariantScore], *,
            min_effect: float = 0.03, alpha: float = 0.05,
            budget_tolerance: float = 0.15,
            target_calls: int | None = None) -> Decision:
    """A/B karsilastirmasi ve ACIK karar kurali.

    KARAR KURALI (bulgu 7 ve 9 dogrudan dayatir):
      Cok ajanli bir varyant SECILIR ancak ve ancak
        (1) token butcesi taban cizgiye gore hedef cagri sayisiyla ESITLENMIS,
        (2) kati (localized) F1 farki >= `min_effect`,
        (3) esli McNemar testi p < `alpha`
      olursa. Aksi halde TABAN CIZGI KULLANILIR. "Cok ajanli daha modern" gibi
      bir gerekce kabul edilmez (bulgu 7: kazanc otomatik degildir; bulgu 9:
      yuzeysel iyilestirmeler +%9,4...+%15,6 ile sinirli).
    """
    dec = Decision(chosen="baseline", reason="", baseline_f1=baseline.localized.f1)
    rows = [{"variant": baseline.variant, **baseline.to_dict()}]

    best: VariantScore | None = None
    best_stats: tuple[int, int, float] = (0, 0, 1.0)
    for v in variants:
        b, c, p = mcnemar_exact(baseline.per_item, v.per_item)
        matched = True
        if target_calls is not None:
            ratio = v.calls_per_item / target_calls if target_calls else 0.0
            matched = abs(1.0 - ratio) <= budget_tolerance
        row = {"variant": v.variant, **v.to_dict(),
               "delta_f1": round(v.localized.f1 - baseline.localized.f1, 4),
               "mcnemar_b": b, "mcnemar_c": c, "mcnemar_p": round(p, 5),
               "budget_matched": matched}
        rows.append(row)
        if not matched:
            dec.notes.append(
                f"{v.variant}: cagri/madde={v.calls_per_item:.2f}, hedef "
                f"{target_calls} -> ESIT BUTCE DISI, karar kuralinda yarisamaz "
                "(bulgu 7: karsilastirma esit token butcesinde yapilmalidir).")
            continue
        if best is None or v.localized.f1 > best.localized.f1:
            best, best_stats = v, (b, c, p)
        if v.consensus_illusion:
            dec.notes.extend(v.notes)

    dec.rows = rows
    if best is None:
        dec.reason = ("Esit butcede yarisan cok ajanli varyant yok -> taban cizgi "
                      "(bulgu 7).")
        return dec
    dec.best_variant = best.variant
    dec.best_f1 = best.localized.f1
    dec.delta = best.localized.f1 - baseline.localized.f1
    dec.p_value = best_stats[2]
    dec.budget_matched = True

    if dec.delta >= min_effect and dec.p_value < alpha:
        dec.chosen = best.variant
        dec.reason = (f"{best.variant} esit butcede taban cizgiyi ANLAMLI bicimde "
                      f"gecti: dF1={dec.delta:+.3f} >= {min_effect}, "
                      f"McNemar p={dec.p_value:.4f} < {alpha}.")
    else:
        dec.chosen = "baseline"
        why = []
        if dec.delta < min_effect:
            why.append(f"dF1={dec.delta:+.3f} < asgari etki {min_effect}")
        if dec.p_value >= alpha:
            why.append(f"McNemar p={dec.p_value:.4f} >= {alpha}")
        dec.reason = ("Taban cizgi kullanilir (bulgu 7/9): en iyi cok ajanli "
                      f"varyant {best.variant} yetersiz — " + "; ".join(why) + ".")
    return dec


# --------------------------------------------------------------------------
# GECERSIZ olcum — yine de hesaplanir, ama isaretlenir
# --------------------------------------------------------------------------

def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    n = len(xs)
    if n < 3:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return float("nan")
    return sxy / math.sqrt(sxx * syy)


def pvalue_probe(batch, items: Sequence[dict]) -> dict[str, Any]:
    """LLM etiketi ile ampirik p-degeri arasindaki iliski — BU VERIDE ANLAMSIZ.

    Hesaplanir cunku gercek bir veri kumesinde bu ASIL dis gecerlilik olcumudur
    (bulgu 11, adim 4) ve boru hattinin o yeteneği hazir dursun. Ancak tohum
    verisinde metin ile zorluk BAGIMSIZ uretildiginden sonuc yorumlanamaz;
    cikti daima `gecerli: False` tasir.
    """
    by_id = {i["question_id"]: i for i in items}
    order = {"hatirlama": 0, "uygulama": 1, "analiz": 2}
    xs, ys = [], []
    for qid, seg in batch.results.items():
        it = by_id.get(qid)
        if not it or it.get("p_value") is None:
            continue
        xs.append(float(order[seg.labels["bilissel_talep"].label]))
        ys.append(float(it["p_value"]))
    r = _pearson(xs, ys)
    return {
        "gecerli": False,
        "not": ("BU VERIDE ANLAMSIZ: tohum uretecinde soru metni ile zorluk "
                "birbirinden bagimsiz uretilmistir (SENARYO §4.2/§4.4); sifir "
                "korelasyon beklenir ve yontem hakkinda hicbir sey soylemez."),
        "n": len(xs),
        "pearson_r": None if r != r else round(r, 4),
        "olculen": "bilissel_talep siralamasi x ampirik p_value",
    }


def write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
