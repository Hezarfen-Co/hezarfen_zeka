"""Türkçe metin havuzları: soru kökleri, şık metinleri, öğrenci cevapları.

Neden ayrı modül: üretim kodunda gömülü metin kalmasın, havuzlar tek yerden
büyütülebilsin. Buradaki her üretici fonksiyon **tohumdan türetilmiş** bir
`random.Random` alır; belirlenimcilik bozulmaz.

Tasarım kuralları
-----------------
* Her şık şablonu **en az bir değişken** içerir (`{n}`, `{kavram}`, `{konu}` …).
  Sabit cümle yoktur: tek bir metnin tüm şıklar içindeki payı böylece %2'yi
  geçemez.
* **Kavram havuzu konu düzeyindedir.** Sayısal derslerde (matematik, fizik,
  kimya, biyoloji) kavram, sorunun konusuna ait `SUBJECT_CONCEPTS` havuzundan
  seçilir — ders havuzundan değil. Böylece "Türev konusunda kümenin eleman
  sayısı" gibi uyumsuz kökler üretilemez. Sözel derslerde ders düzeyi havuz
  yeterlidir (konular birbirinin kavramını serbestçe kullanabilir).
* **Şık tipi köke bağlıdır.** Her soru kökü şablonu bir etiket taşır:
  `sayisal` ("kaçtır", "hesaplandığında") sayısal şık ister, `ifade`
  ("hangisi doğrudur") ifade şıkkı ister. `make_choices()` bu etikete uyar.
* Aynı sorunun şıkları birbirinden farklı olacak biçimde üretilir (çakışma
  olursa yeniden çekilir).
* Öğrenci cevapları 1–3 cümledir, **en fazla 400 karakter** ve daima tam
  cümleyle biter; kelime ortasından kesme yoktur.
"""

from __future__ import annotations

# Konu düzeyinde kavram havuzu tutulan dersler
NUMERIC_AREAS = {"mat", "fiz", "kim", "biy"}

# --------------------------------------------------------------------------
# KONU DÜZEYİ KAVRAM HAVUZLARI (sayısal dersler)
# Anahtar = `subject.name`. Kavramlar yalnız o konudan seçilir.
# --------------------------------------------------------------------------

SUBJECT_CONCEPTS = {
    # ---- Matematik 9 ----
    "Kümeler": ["eleman sayısı", "alt küme", "kesişim", "birleşim", "fark kümesi",
                "evrensel küme", "boş küme", "tümleyen"],
    "Denklem ve Eşitsizlikler": ["birinci dereceden denklem", "çözüm kümesi",
                                 "eşitsizliğin yönü", "kök", "denk denklem",
                                 "işaret tablosu"],
    "Üslü ve Köklü İfadeler": ["üs kuralı", "taban", "üs değeri", "köklü ifade",
                               "kök derecesi", "rasyonel üs", "paydayı rasyonel yapma"],
    "Mutlak Değer": ["mutlak değer", "uzaklık yorumu", "iki durumlu çözüm",
                     "mutlak değerli eşitsizlik", "kök kümesi"],
    "Sayı Kümeleri": ["doğal sayı", "tam sayı", "rasyonel sayı", "irrasyonel sayı",
                      "asal sayı", "bölünebilme kuralı", "ebob", "ekok"],
    "Üçgenler": ["kenarortay", "açıortay", "yükseklik", "üçgen eşitsizliği",
                 "benzerlik oranı", "üçgenin alanı", "dik üçgen bağıntısı"],
    "Veri Analizi": ["ortalama", "medyan", "mod", "açıklık", "standart sapma",
                     "frekans tablosu", "histogram"],
    "Fonksiyon Kavramı": ["tanım kümesi", "görüntü kümesi", "bire bir fonksiyon",
                          "örten fonksiyon", "bileşke fonksiyon", "ters fonksiyon",
                          "fonksiyon grafiği"],
    "Olasılık": ["örnek uzay", "olay", "bağımsız olay", "ayrık olay",
                 "koşullu olasılık", "olasılık değeri", "tümleyen olay"],
    "Doğrunun Analitik İncelenmesi": ["eğim", "doğru denklemi", "kesişim noktası",
                                      "paralellik koşulu", "diklik koşulu",
                                      "iki nokta arası uzaklık"],
    # ---- Matematik 10 ----
    "Sayma ve Olasılık": ["permütasyon", "kombinasyon", "faktöriyel", "sayma kuralı",
                          "örnek uzay", "olay sayısı"],
    "Fonksiyonlarla İşlemler": ["bileşke fonksiyon", "ters fonksiyon",
                                "fonksiyonların toplamı", "tanım kümesi",
                                "fonksiyon grafiği", "parçalı fonksiyon"],
    "Polinomlar": ["polinomun derecesi", "baş katsayı", "sabit terim", "kalan bulma",
                   "çarpanlara ayırma", "polinom bölmesi"],
    "İkinci Dereceden Denklemler": ["diskriminant", "kökler toplamı", "kökler çarpımı",
                                    "parabolün tepe noktası", "çarpanlara ayırma",
                                    "kök formülü"],
    "Dörtgenler ve Çokgenler": ["iç açılar toplamı", "dış açılar toplamı", "köşegen",
                                "paralelkenar", "yamuk", "düzgün çokgen", "alan"],
    "Çemberin Analitik İncelenmesi": ["merkez", "yarıçap", "çember denklemi",
                                      "teğet doğru", "kiriş", "merkeze uzaklık"],
    "Katı Cisimler": ["hacim", "yüzey alanı", "prizma", "piramit", "küre", "koni",
                      "taban alanı"],
    "Basit Olayların Olasılığı": ["örnek uzay", "istenen durum", "olasılık değeri",
                                  "ayrık olay", "tümleyen olay"],
    "Trigonometriye Giriş": ["sinüs", "kosinüs", "tanjant", "birim çember",
                             "derece radyan dönüşümü", "dik üçgen oranları"],
    # ---- Matematik 11 ----
    "Trigonometri": ["sinüs", "kosinüs", "tanjant", "birim çember", "periyot",
                     "toplam fark formülü", "temel özdeşlik", "ters trigonometrik"],
    "Analitik Geometri": ["eğim", "doğru denklemi", "iki nokta arası uzaklık",
                          "orta nokta", "noktanın doğruya uzaklığı", "kesişim noktası"],
    "Fonksiyonlarda Uygulamalar": ["fonksiyon grafiği", "artan aralık", "azalan aralık",
                                   "maksimum nokta", "minimum nokta", "tanım kümesi"],
    "Denklem ve Eşitsizlik Sistemleri": ["çözüm kümesi", "yok etme yöntemi",
                                         "yerine koyma yöntemi", "grafik çözüm",
                                         "tutarlı sistem", "işaret tablosu"],
    "Çember ve Daire": ["merkez", "yarıçap", "kiriş", "teğet", "çevre açı",
                        "daire dilimi", "yay uzunluğu"],
    "Uzay Geometri": ["hacim", "yüzey alanı", "ayrıt", "taban alanı", "prizma",
                      "dik piramit", "kesit"],
    "Diziler": ["genel terim", "aritmetik dizi", "geometrik dizi", "ortak fark",
                "ortak çarpan", "dizinin toplamı", "sınırlı dizi"],
    "Limit Kavramına Giriş": ["soldan limit", "sağdan limit", "limit değeri",
                              "süreklilik", "belirsizlik", "asimptot"],
    "İstatistik": ["ortalama", "medyan", "mod", "standart sapma", "varyans",
                   "frekans tablosu", "aykırı değer"],
    # ---- Matematik 12 ----
    "Üstel ve Logaritmik Fonksiyonlar": ["üstel fonksiyon", "logaritma tabanı",
                                         "logaritma kuralı", "doğal logaritma",
                                         "tanım kümesi", "grafik dönüşümü"],
    "Diziler ve Seriler": ["genel terim", "aritmetik seri", "geometrik seri",
                           "ortak fark", "ortak çarpan", "serinin toplamı"],
    "Limit": ["soldan limit", "sağdan limit", "limit değeri", "süreklilik",
              "belirsizlik", "asimptot"],
    "Türev": ["türev", "eğim", "teğet doğrusu", "kritik nokta", "artan aralık",
              "azalan aralık", "türev kuralı", "zincir kuralı"],
    "Türevin Uygulamaları": ["maksimum nokta", "minimum nokta", "büküm noktası",
                             "artan aralık", "azalan aralık", "teğet doğrusu",
                             "optimizasyon"],
    "İntegral": ["belirsiz integral", "integral sabiti", "ters türev",
                 "değişken değiştirme", "integral kuralı"],
    "Belirli İntegral": ["alt sınır", "üst sınır", "eğri altında kalan alan",
                         "belirli integral", "ortalama değer"],
    "Uzay Geometride Hacim": ["hacim", "taban alanı", "yükseklik", "dönel cisim",
                              "küre hacmi", "koni hacmi"],
    "İstatistik ve Olasılık": ["ortalama", "standart sapma", "örnek uzay",
                               "koşullu olasılık", "bağımsız olay", "frekans tablosu"],
    # ---- Matematik yedek liste ----
    "Sayılar ve İşlemler": ["asal çarpan", "ebob", "ekok", "bölünebilme kuralı",
                            "işlem önceliği", "rasyonel sayı"],
    "Cebirsel İfadeler": ["özdeşlik", "çarpanlara ayırma", "ortak çarpan",
                          "terim", "katsayı", "sadeleştirme"],
    "Denklemler": ["çözüm kümesi", "kök", "denk denklem", "birinci dereceden denklem",
                   "yerine koyma"],
    "Fonksiyonlar": ["tanım kümesi", "görüntü kümesi", "bileşke fonksiyon",
                     "ters fonksiyon", "fonksiyon grafiği"],
    "Geometrik Cisimler": ["hacim", "yüzey alanı", "taban alanı", "ayrıt", "prizma"],
    "Kombinasyon": ["kombinasyon", "permütasyon", "faktöriyel", "sayma kuralı"],

    # ---- Fizik 11 ----
    "Vektörler": ["vektörün büyüklüğü", "bileşke vektör", "bileşen", "yön",
                  "vektör toplamı", "skaler çarpım"],
    "Bağıl Hareket": ["bağıl hız", "referans sistemi", "yer değiştirme",
                      "ortalama hız", "hareket yönü"],
    "Newton'ın Hareket Yasaları": ["net kuvvet", "eylemsizlik", "ivme",
                                   "etki tepki", "sürtünme kuvveti", "kütle"],
    "Tork ve Denge": ["tork", "kuvvet kolu", "denge koşulu", "ağırlık merkezi",
                      "destek noktası", "dik uzaklık"],
    "Basit Makineler": ["kuvvet kazancı", "yol kazancı", "kaldıraç", "makara",
                        "eğik düzlem", "verim"],
    "İş Güç Enerji": ["iş", "güç", "kinetik enerji", "potansiyel enerji",
                      "enerji korunumu", "verim"],
    "Atışlar": ["yatay atış", "eğik atış", "menzil", "uçuş süresi",
                "ilk hız", "yerçekimi ivmesi"],
    "Enerji Dönüşümleri": ["enerji korunumu", "kinetik enerji", "potansiyel enerji",
                           "ısı enerjisi", "verim", "enerji kaybı"],
    "Elektriksel Kuvvet ve Alan": ["yük", "elektriksel kuvvet", "elektrik alan",
                                   "potansiyel fark", "Coulomb yasası", "alan çizgileri"],
    "Manyetizma": ["manyetik alan", "akım", "indüksiyon", "manyetik kuvvet",
                   "sağ el kuralı", "bobin"],
    # ---- Fizik yedek liste ----
    "Fizik Bilimine Giriş": ["birim sistemi", "skaler büyüklük", "vektörel büyüklük",
                             "ölçme", "türetilmiş birim", "temel büyüklük"],
    "Madde ve Özellikleri": ["kütle", "hacim", "özkütle", "eylemsizlik",
                             "esneklik", "adezyon"],
    "Hareket ve Kuvvet": ["hız", "ivme", "yer değiştirme", "net kuvvet",
                          "sürtünme kuvveti", "dengelenmiş kuvvet"],
    "Enerji": ["kinetik enerji", "potansiyel enerji", "iş", "güç",
               "enerji korunumu", "verim"],
    "Isı ve Sıcaklık": ["ısı", "sıcaklık", "öz ısı", "hal değişimi",
                        "ısı alışverişi", "genleşme"],
    "Elektrostatik": ["yük", "elektriksel kuvvet", "elektrik alan", "topraklama",
                      "iletken", "yalıtkan"],
    "Elektrik Akımı": ["akım şiddeti", "potansiyel fark", "direnç", "Ohm yasası",
                       "seri bağlama", "paralel bağlama"],
    "Optik": ["yansıma açısı", "kırılma indisi", "odak uzaklığı", "görüntü",
              "mercek", "ayna"],
    "Dalgalar": ["dalga boyu", "frekans", "periyot", "genlik", "yayılma hızı",
                 "girişim"],
    "Modern Fizik": ["foton enerjisi", "fotoelektrik olay", "kara cisim ışıması",
                     "atom modeli", "enerji seviyesi"],

    # ---- Kimya ----
    "Kimya Bilimi": ["element", "bileşik", "sembol", "formül", "laboratuvar kuralı",
                     "kimyanın alt dalları"],
    "Atom ve Periyodik Sistem": ["atom numarası", "kütle numarası", "izotop",
                                 "değerlik elektron", "periyot", "grup",
                                 "elektron dizilimi"],
    "Kimyasal Türler Arası Etkileşim": ["iyonik bağ", "kovalent bağ", "hidrojen bağı",
                                        "London kuvveti", "bağ enerjisi", "polarlık"],
    "Maddenin Halleri": ["erime noktası", "kaynama noktası", "buhar basıncı",
                         "hal değişimi", "süblimleşme", "yoğunlaşma"],
    "Karışımlar": ["homojen karışım", "heterojen karışım", "çözünen", "çözücü",
                   "ayırma yöntemi", "derişim"],
    "Asitler ve Bazlar": ["pH", "asit kuvveti", "baz kuvveti", "nötrleşme",
                          "indikatör", "titrasyon"],
    "Kimyasal Tepkimeler": ["denkleştirme", "tepkime türü", "yükseltgenme",
                            "indirgenme", "mol oranı", "sınırlayıcı bileşen"],
    "Gazlar": ["basınç", "hacim", "mol sayısı", "ideal gaz denklemi",
               "kısmi basınç", "mutlak sıcaklık"],
    "Çözeltiler": ["derişim", "molarite", "çözünürlük", "doymuş çözelti",
                   "seyreltme", "kütlece yüzde"],
    "Kimya ve Enerji": ["endotermik tepkime", "ekzotermik tepkime", "entalpi",
                        "aktivasyon enerjisi", "bağ enerjisi", "ısı alışverişi"],

    # ---- Biyoloji 10 ----
    "Hücre Bölünmeleri (Mitoz)": ["kromozom sayısı", "iğ ipliği", "sitokinez",
                                  "interfaz", "metafaz", "kalıtsal çeşitlilik"],
    "Mayoz ve Eşeyli Üreme": ["kromozom sayısı", "krossing over", "gamet",
                              "haploit hücre", "döllenme", "kalıtsal çeşitlilik"],
    "Kalıtım": ["gen", "alel", "baskın karakter", "çekinik karakter", "genotip",
                "fenotip", "çaprazlama"],
    "Modern Genetik Uygulamaları": ["gen aktarımı", "klonlama", "DNA parmak izi",
                                    "genetik danışmanlık", "biyoteknoloji"],
    "Ekosistem Ekolojisi": ["besin zinciri", "üretici", "tüketici", "ayrıştırıcı",
                            "enerji piramidi", "popülasyon"],
    "Madde Döngüleri": ["karbon döngüsü", "azot döngüsü", "su döngüsü",
                        "ayrıştırıcı", "fotosentez", "solunum"],
    "Bitki Biyolojisi": ["kök", "gövde", "yaprak", "terleme", "iletim demeti",
                         "stoma", "büyüme"],
    "Canlılar ve Enerji": ["ATP", "enzim", "solunum", "fotosentez", "besin zinciri",
                           "enerji dönüşümü"],
    "Fotosentez": ["kloroplast", "klorofil", "ışık evresi", "ışıktan bağımsız evre",
                   "karbondioksit", "glikoz üretimi"],
    "Solunum": ["oksijenli solunum", "oksijensiz solunum", "ATP", "mitokondri",
                "glikoz", "fermantasyon"],
    # ---- Biyoloji yedek liste ----
    "Yaşam Bilimi Biyoloji": ["canlıların ortak özellikleri", "hücre", "organizasyon",
                              "metabolizma", "homeostazi"],
    "Hücre": ["hücre zarı", "sitoplazma", "çekirdek", "mitokondri", "ribozom",
              "golgi aygıtı", "difüzyon", "osmoz"],
    "Canlılar Dünyası": ["sınıflandırma", "tür", "alem", "bakteri", "mantar",
                         "protista"],
    "Hücre Bölünmeleri": ["kromozom sayısı", "mitoz", "mayoz", "sitokinez",
                          "interfaz", "iğ ipliği"],
    "Sistemler": ["sindirim sistemi", "dolaşım sistemi", "solunum sistemi",
                  "boşaltım sistemi", "sinir sistemi", "homeostazi"],
}

# Konu havuzu bulunmayan sayısal konular için KONU-NÖTR yedek kavramlar.
# (Başka bir konunun havuzuna ait olmadıkları için uyum denetimini tetiklemezler.)
GENERIC_NUMERIC_CONCEPTS = {
    "mat": ["tanım", "bağıntı", "kural", "grafik", "işlem sırası", "örnek çözüm"],
    "fiz": ["tanım", "bağıntı", "birim", "grafik", "deney düzeneği", "ölçüm"],
    "kim": ["tanım", "bağıntı", "birim", "deney", "hesaplama adımı", "tablo"],
    "biy": ["tanım", "yapı", "işlev", "şema", "örnek", "gözlem"],
}

# --------------------------------------------------------------------------
# Sözel derslerde kavram havuzu ders düzeyindedir (koordinatör: bunlara dokunma)
# --------------------------------------------------------------------------

CONCEPTS = {
    "tar": ["Kurultay", "tımar sistemi", "devşirme usulü", "divan teşkilatı",
            "lonca düzeni", "vakıf sistemi", "kapitülasyonlar", "ıslahat hareketleri",
            "Tanzimat Fermanı", "Meşrutiyet", "Kanun-i Esasi", "Millî Mücadele",
            "Misak-ı Millî", "Tekâlif-i Milliye", "Saltanatın kaldırılması",
            "Cumhuriyetin ilanı", "Halifeliğin kaldırılması", "Tevhid-i Tedrisat",
            "Harf İnkılabı", "Kabotaj Kanunu", "Montrö Sözleşmesi", "Hatay'ın katılımı"],
    "cog": ["yerel saat", "ortak saat", "enlem etkisi", "boylam etkisi", "yükselti",
            "bakı", "karasal iklim", "Akdeniz iklimi", "Karadeniz iklimi", "maki",
            "step bitki örtüsü", "nüfus yoğunluğu", "aritmetik nüfus yoğunluğu",
            "göç dalgası", "kentleşme oranı", "tarımsal üretim", "sanayi bölgesi",
            "turizm geliri", "ulaşım ağı", "dış ticaret hacmi", "doğal kaynak",
            "erozyon", "heyelan", "deprem kuşağı", "akarsu rejimi", "delta ovası"],
    "edb": ["kafiye", "redif", "ölçü", "durak", "aliterasyon", "teşbih", "istiare",
            "kişileştirme", "mecaz anlam", "yan anlam", "olay örgüsü", "bakış açısı",
            "anlatıcı", "çatışma", "karakter çözümlemesi", "mekân betimlemesi",
            "zaman kurgusu", "tema", "hikâye kişisi", "diyalog", "iç monolog",
            "serim bölümü", "düğüm bölümü", "çözüm bölümü", "yazım kuralı",
            "noktalama işareti", "bağlaç kullanımı", "söz sanatı"],
    "ing": ["present perfect", "past simple", "future continuous", "passive voice",
            "reported speech", "relative clause", "conditional type 2", "modal verb",
            "gerund", "infinitive", "comparative form", "superlative form",
            "phrasal verb", "collocation", "article usage", "preposition of time",
            "countable noun", "uncountable noun", "linking word", "question tag"],
    "din": ["ibadet bilinci", "ahlak ilkesi", "sabır", "şükür", "adalet", "merhamet",
            "doğruluk", "emanet", "yardımlaşma", "komşuluk hakkı", "hoşgörü",
            "sorumluluk bilinci", "temizlik", "dua", "niyet", "paylaşma", "iyilik"],
    "bed": ["ısınma hareketi", "esneklik çalışması", "dayanıklılık", "kuvvet gelişimi",
            "denge", "koordinasyon", "reaksiyon süresi", "nabız takibi", "kondisyon",
            "faul kuralı", "taktik dizilişi", "pas tekniği", "şut tekniği",
            "savunma düzeni", "sportmenlik", "adil oyun", "sakatlıktan korunma"],
    "gen": ["temel kavram", "örnek çözüm", "uygulama adımı", "kontrol listesi",
            "çalışma planı", "grup çalışması", "sunum hazırlığı", "geri bildirim",
            "zaman yönetimi", "kaynak taraması", "not tutma tekniği", "tekrar aralığı"],
}

# --------------------------------------------------------------------------
# Birimler
# --------------------------------------------------------------------------

UNITS = {
    "fiz": ["m/s", "m/s²", "N", "J", "W", "kg·m/s", "N·m", "Pa", "°C", "Hz", "Ω", "V", "A"],
    "kim": ["mol", "g", "g/mol", "L", "mol/L", "kJ", "°C", "atm"],
    "biy": ["adet", "hücre", "mg", "birim"],
    "mat": ["birim", "birim kare", "birim küp", "derece", "radyan"],
    "cog": ["km", "km²", "m", "kişi/km²", "mm", "°C"],
    "bed": ["saniye", "dakika", "metre", "tekrar", "set"],
}

# Konuya uygun birim — sayısal şıklarda kullanılır
SUBJECT_UNITS = {
    "Vektörler": ["N", "m"], "Bağıl Hareket": ["m/s", "m"],
    "Newton'ın Hareket Yasaları": ["N", "m/s²"], "Tork ve Denge": ["N·m", "N"],
    "Basit Makineler": ["N", "m"], "İş Güç Enerji": ["J", "W"],
    "Atışlar": ["m", "m/s"], "Enerji Dönüşümleri": ["J", "W"],
    "Elektriksel Kuvvet ve Alan": ["N", "V"], "Manyetizma": ["Hz", "A"],
    "Hareket ve Kuvvet": ["m/s", "N"], "Enerji": ["J", "W"],
    "Isı ve Sıcaklık": ["°C", "J"], "Elektrostatik": ["N", "V"],
    "Elektrik Akımı": ["A", "V", "Ω"], "Optik": ["m", "derece"],
    "Dalgalar": ["Hz", "m"], "Modern Fizik": ["J", "Hz"],
    "Madde ve Özellikleri": ["kg", "g"], "Fizik Bilimine Giriş": ["m", "kg"],
    "Gazlar": ["atm", "L"], "Çözeltiler": ["mol/L", "g"],
    "Asitler ve Bazlar": ["mol/L", "L"], "Kimyasal Tepkimeler": ["mol", "g"],
    "Kimya ve Enerji": ["kJ", "°C"], "Maddenin Halleri": ["°C", "atm"],
    "Karışımlar": ["g", "L"], "Atom ve Periyodik Sistem": ["g/mol", "mol"],
    "Kimyasal Türler Arası Etkileşim": ["kJ", "g/mol"], "Kimya Bilimi": ["g", "mol"],
}

# Kavrama uygun birim (konu birimi yoksa devreye girer)
CONCEPT_UNITS = {
    "net kuvvet": "N", "sürtünme kuvveti": "N", "elektriksel kuvvet": "N",
    "ivme": "m/s²", "hız": "m/s", "bağıl hız": "m/s", "ortalama hız": "m/s",
    "yer değiştirme": "m", "menzil": "m", "ilk hız": "m/s",
    "kinetik enerji": "J", "potansiyel enerji": "J", "iş": "J", "güç": "W",
    "tork": "N·m", "basınç": "Pa", "ısı": "J", "sıcaklık": "°C",
    "akım şiddeti": "A", "potansiyel fark": "V", "direnç": "Ω",
    "dalga boyu": "m", "frekans": "Hz", "periyot": "saniye",
    "mol sayısı": "mol", "molarite": "mol/L", "derişim": "mol/L",
    "kaynama noktası": "°C", "erime noktası": "°C", "buhar basıncı": "atm",
    "aktivasyon enerjisi": "kJ", "entalpi": "kJ", "hacim": "L",
}

PEOPLE_TR = ["Mustafa Kemal Atatürk", "İsmet İnönü", "Fatih Sultan Mehmet",
             "Kanuni Sultan Süleyman", "II. Mahmut", "Yavuz Sultan Selim",
             "Sultan Abdülmecid", "Mimar Sinan", "Piri Reis", "Katip Çelebi"]

WORKS_TR = ["Çalıkuşu", "Kuyucaklı Yusuf", "Yaban", "Sinekli Bakkal", "Han Duvarları",
            "Safahat", "Otuz Beş Yaş", "Kaldırımlar", "Memleket Hikâyeleri",
            "Dokuzuncu Hariciye Koğuşu", "Sergüzeşt", "Araba Sevdası"]

PLACES_TR = ["Marmara Bölgesi", "Ege Bölgesi", "İç Anadolu Bölgesi",
             "Doğu Anadolu Bölgesi", "Güneydoğu Anadolu Bölgesi", "Akdeniz Bölgesi",
             "Karadeniz Bölgesi", "Çukurova", "Konya Ovası", "Ergene Havzası",
             "Menteşe Yöresi", "Yıldız Dağları"]

ENG_WORDS = ["environment", "technology", "inspiration", "travel", "science",
             "culture", "media", "health", "education", "friendship", "career",
             "tradition", "energy", "nature"]

# --------------------------------------------------------------------------
# ŞIK ŞABLONLARI
# Sayısal derslerde iki küme: `sayisal` (değer isteyen köke) ve `ifade`
# (yargı isteyen köke). Sözel derslerde tek düz liste (hepsi `ifade`).
# Her şablon en az bir değişken içerir.
# --------------------------------------------------------------------------

CHOICE_TEMPLATES = {
    "mat": {
        "sayisal": ["{n}", "-{n}", "{n}/{m}", "{n},{r}", "x = {n}", "x = -{n}",
                    "x = {n}/{m}", "{n}√{m}", "{n}π/{m}", "({n}, {m})", "({n}, -{m})",
                    "{n}·{m}", "2^{s} · {n}", "{n} {birim}", "y = {n}x - {m}",
                    "f(x) = {n}x + {m}", "f(x) = x² - {n}x + {m}", "{d}"],
        "ifade": ["{kavram} artar", "{kavram} azalır", "{kavram} değişmez",
                  "{kavram} {n} olur", "{kavram} ile {kavram2} eşittir",
                  "{kavram} tanımsızdır", "{kavram} her zaman pozitiftir",
                  "yalnızca {kavram} belirleyicidir",
                  "{kavram} ile {kavram2} ters orantılıdır",
                  "{kavram} {kavram2} cinsinden yazılabilir",
                  "{kavram} {n} birim ötelenir", "{kavram} için çözüm yoktur",
                  "{kavram} yalnızca {n} noktasında geçerlidir"],
    },
    "fiz": {
        "sayisal": ["{n} {birim}", "{n},{r} {birim}", "{d} {birim}", "-{n} {birim}",
                    "{n}·10^{s} {birim}", "{n}/{m} {birim}", "{n} {birim} ters işaretli"],
        "ifade": ["{kavram} korunur", "{kavram} artar, {kavram2} azalır",
                  "{kavram} sıfırdır", "{kavram} iki katına çıkar",
                  "{kavram} değişmez", "yalnızca {kavram} etkiler",
                  "{kavram} ile {kavram2} doğru orantılıdır",
                  "{kavram} {n} kat artar", "{kavram} ters işaret alır",
                  "{kavram} ve {kavram2} birlikte artar"],
    },
    "kim": {
        "sayisal": ["{n} {birim}", "{n},{r} {birim}", "{n}·10^-{s} mol/L",
                    "{n}/{m} {birim}", "{d} {birim}"],
        "ifade": ["{kavram} artar", "{kavram} azalır", "{kavram} değişmez",
                  "{kavram} ile {kavram2} orantılıdır", "yalnızca {kavram} artar",
                  "{kavram} {n} katına çıkar", "{kavram} dengeyi sağa kaydırır",
                  "{kavram} tepkimeyi hızlandırır", "{kavram} ve {kavram2} birlikte azalır"],
    },
    "biy": {
        "sayisal": ["{n}", "{n} {birim}", "{n}/{m}", "%{n}", "{n}n", "{n} kromozom"],
        "ifade": ["{kavram} korunur", "{kavram} yarıya iner", "{kavram} iki katına çıkar",
                  "{kavram} evresinde gerçekleşir", "{kavram} değişmez",
                  "{kavram} ve {kavram2} birlikte artar", "yalnızca {kavram} etkilidir",
                  "{kavram} {n} kez tekrarlanır", "{kavram} durur"],
    },
    "tar": ["{yil} yılında", "{yil}-{yil2} arasında", "{kisi} döneminde",
            "{kavram} ile başlar", "{kavram} sonrasında ({yil})",
            "{kisi} tarafından ({yil})", "{kavram} ve {kavram2} birlikte",
            "{kavram} kaldırılmıştır ({yil})", "{yer} merkezli olarak",
            "{kavram} genişletilmiştir ({yil})", "{kisi} önderliğinde {kavram}"],
    "cog": ["{yer}", "{yer} ve çevresi", "{kavram} nedeniyle", "{n} {birim}",
            "{kavram} {n} {birim} artar", "{kavram} etkisiyle {yer}",
            "{kavram} ve {kavram2} birlikte etkiler", "{n},{r} {birim}",
            "yalnızca {kavram} belirleyicidir", "{yer}'de {kavram} baskındır"],
    "edb": ["{kavram} kullanılmıştır", "{kavram} ve {kavram2} birlikte görülür",
            "{eser} adlı eserde", "{kisi} tarafından yazılmıştır",
            "{kavram} yoktur, {kavram2} vardır", "{eser}'de {kavram} öne çıkar",
            "{kavram} {n}. dizede geçer", "metinde {kavram} baskındır",
            "{kavram} yanlış kullanılmıştır", "{eser} ile {kavram} örneklenir"],
    "ing": ["since {yil}", "for {n} years", "{kavram} is used",
            "{kavram} instead of {kavram2}", "the word '{soz}' is correct",
            "'{soz}' + {kavram}", "the {kavram} of '{soz}'", "{n} of them are correct",
            "{kavram} with '{soz}'", "'{soz}' takes {kavram}"],
    "din": ["{kavram} esastır", "{kavram} ve {kavram2} birlikte anılır",
            "{kavram} öne çıkar", "{kavram} {n}. ilke olarak geçer",
            "yalnızca {kavram} yeterlidir", "{kavram} ile açıklanır"],
    "bed": ["{n} {birim}", "{kavram} uygulanır ({n} {birim})",
            "{kavram} ve {kavram2} birlikte", "{n} {birim} dinlenme",
            "{kavram} hatalıdır", "{kavram} {n} kez tekrarlanır"],
    "gen": ["{kavram} önceliklidir", "{n}. adımda uygulanır",
            "{kavram} ve {kavram2} birlikte", "{n} {birim} sürer",
            "yalnızca {kavram} gerekir", "{kavram} göz ardı edilmiştir"],
}

# --------------------------------------------------------------------------
# SORU KÖKÜ ŞABLONLARI
# Sayısal derslerde (şablon, şık_tipi) ikilisi; sözel derslerde düz metin.
# --------------------------------------------------------------------------

STEM_TEMPLATES = {
    "mat": [
        ("{konu} konusunda {kavram} {n} ise sonuç kaçtır?", "sayisal"),
        ("{konu}: {kavram} için hesaplanan değer kaçtır?", "sayisal"),
        ("{n} ve {m} sayıları için {konu} konusundaki {kavram} kaç olur?", "sayisal"),
        ("{konu} konusunda {kavram} hesaplandığında hangi sonuç elde edilir?", "sayisal"),
        ("{konu} konusunda {kavram} {n} birim artarsa yeni değer kaçtır?", "sayisal"),
        ("{konu} konusunda {kavram2} {m} iken {kavram} kaçtır?", "sayisal"),
        ("Aşağıdakilerden hangisi {konu} konusundaki {kavram} için doğrudur?", "ifade"),
        ("{konu} konusunda {kavram} ile ilgili hangi seçenek yanlıştır?", "ifade"),
        ("{konu}: {kavram} ile {kavram2} arasındaki ilişki hangisidir?", "ifade"),
        ("{konu} konusunda {kavram2} sabitken {kavram} için hangisi söylenebilir?", "ifade"),
        ("{kavram} tanımına göre {konu} konusunda hangi ifade geçerlidir?", "ifade"),
        ("{konu} konusunda {kavram} {n} birim değiştiğinde sonuç nasıl değişir?", "ifade"),
    ],
    "fiz": [
        ("{konu} konusunda {kavram} {n} {birim} ise sonuç kaçtır?", "sayisal"),
        ("{konu}: {kavram} için ölçülen değer kaç olur?", "sayisal"),
        ("{konu} konusunda {kavram} hesaplandığında sonuç nedir?", "sayisal"),
        ("Sürtünmesiz ortamda {konu} konusundaki {kavram} kaçtır?", "sayisal"),
        ("{konu} konusunda {kavram2} {m} iken {kavram} kaç olur?", "sayisal"),
        ("Aşağıdakilerden hangisi {konu} konusundaki {kavram} için doğrudur?", "ifade"),
        ("{konu} konusunda {kavram} ile ilgili hangi seçenek yanlıştır?", "ifade"),
        ("{konu}: {kavram} iki katına çıkarılırsa {kavram2} nasıl değişir?", "ifade"),
        ("{konu} konusunda {kavram} korunumu hangi durumda geçerlidir?", "ifade"),
        ("{konu} deneyinde {kavram} ölçülmüştür; hangi çıkarım yapılabilir?", "ifade"),
        ("{konu} konusunda {kavram2} sabit tutulursa {kavram} için hangisi doğrudur?", "ifade"),
    ],
    "kim": [
        ("{konu} konusunda {n} {birim} örnek için {kavram} kaçtır?", "sayisal"),
        ("{konu}: {kavram} hesaplandığında sonuç nedir?", "sayisal"),
        ("{konu} konusunda {kavram2} {m} iken {kavram} kaç olur?", "sayisal"),
        ("{konu} konusunda {kavram} değeri kaçtır?", "sayisal"),
        ("Aşağıdakilerden hangisi {konu} konusundaki {kavram} için doğrudur?", "ifade"),
        ("{konu}: {kavram} artarsa {kavram2} nasıl etkilenir?", "ifade"),
        ("{konu} konusunda {kavram} ile ilgili hangi seçenek yanlıştır?", "ifade"),
        ("{konu} konusunda ortam sıcaklığı {n} °C artırılırsa {kavram} nasıl değişir?", "ifade"),
        ("{konu} konusunda {kavram} için hangi ifade her zaman geçerlidir?", "ifade"),
    ],
    "biy": [
        ("{konu} konusunda {kavram} {n} ise {kavram2} kaç olur?", "sayisal"),
        ("{konu}: {kavram} sayısı kaçtır?", "sayisal"),
        ("{konu} konusunda {kavram} oranı hesaplandığında sonuç nedir?", "sayisal"),
        ("Aşağıdakilerden hangisi {konu} konusundaki {kavram} için doğrudur?", "ifade"),
        ("{konu} konusunda {kavram} ile {kavram2} arasındaki fark nedir?", "ifade"),
        ("{konu} olayında {kavram} hangi aşamada gerçekleşir?", "ifade"),
        ("{konu} konusunda {kavram} engellenirse hangi sonuç beklenir?", "ifade"),
        ("{konu} konusunda {kavram} ile ilgili hangi seçenek yanlıştır?", "ifade"),
    ],
    "tar": [
        "{konu} konusunda {kavram} ile ilgili hangi bilgi doğrudur?",
        "{yil} yılında {kavram} hangi sonucu doğurmuştur? ({konu})",
        "{kisi} döneminde {kavram} nasıl uygulanmıştır? ({konu})",
        "Aşağıdakilerden hangisi {konu} konusundaki {kavram} ile ilgili değildir?",
        "{konu} konusunda {kavram} ve {kavram2} karşılaştırıldığında hangisi söylenebilir?",
        "{konu}: {kavram} hangi gelişmenin sonucudur?",
        "{yil}-{yil2} döneminde {kavram} için hangi değerlendirme yapılabilir?",
        "{konu} konusunda {kavram} hangi alanda değişim sağlamıştır?",
    ],
    "cog": [
        "{konu} konusunda {kavram} için hangisi doğrudur?",
        "{yer}'de {kavram} hangi nedenle belirgindir? ({konu})",
        "{konu}: {kavram} {n} {birim} değiştiğinde hangi sonuç beklenir?",
        "Aşağıdakilerden hangisi {konu} konusundaki {kavram} ile açıklanamaz?",
        "{konu} konusunda {kavram} ve {kavram2} arasındaki ilişki nedir?",
        "{yer} örneğinde {kavram} hangi özelliği gösterir? ({konu})",
        "{konu} konusunda {kavram} en çok hangi bölgede görülür?",
    ],
    "edb": [
        "{konu} konusunda {kavram} ile ilgili hangisi doğrudur?",
        "{eser} adlı eserde {kavram} nasıl kullanılmıştır? ({konu})",
        "Aşağıdakilerden hangisi {konu} konusundaki {kavram} örneğidir?",
        "{konu}: {kavram} ile {kavram2} arasındaki fark nedir?",
        "Verilen metinde {kavram} hangi amaçla kullanılmıştır? ({konu})",
        "{konu} konusunda {kavram} bakımından hangi seçenek yanlıştır?",
        "{kisi} örneğinde {kavram} hangi işlevi üstlenir? ({konu})",
        "{konu} konusunda {n}. dizedeki {kavram} için ne söylenebilir?",
    ],
    "ing": [
        "Which one is correct about {kavram}? ({konu})",
        "Choose the correct form of '{soz}' in {kavram}. ({konu})",
        "{konu}: which sentence uses {kavram} correctly?",
        "Which option is NOT a correct use of {kavram}? ({konu})",
        "Fill in the blank with the correct {kavram} form of '{soz}'. ({konu})",
        "{konu} konusunda {kavram} hangi durumda kullanılır?",
        "Which one shows the difference between {kavram} and {kavram2}? ({konu})",
    ],
    "din": [
        "{konu} konusunda {kavram} ile ilgili hangisi doğrudur?",
        "{konu}: {kavram} hangi davranışla örneklenir?",
        "Aşağıdakilerden hangisi {konu} konusundaki {kavram} kapsamında değildir?",
        "{konu} konusunda {kavram} ve {kavram2} nasıl ilişkilendirilir?",
        "{konu} konusunda {kavram} bilincinin sonucu hangisidir?",
    ],
    "bed": [
        "{konu} konusunda {kavram} nasıl uygulanır?",
        "{konu}: {n} {birim} süren {kavram} için hangisi doğrudur?",
        "Aşağıdakilerden hangisi {konu} konusundaki {kavram} ile ilgili değildir?",
        "{konu} konusunda {kavram} ve {kavram2} arasındaki fark nedir?",
        "{konu} konusunda {kavram} hangi amaçla yapılır?",
    ],
    "gen": [
        "{konu} konusunda {kavram} için hangisi doğrudur?",
        "{konu}: {kavram} uygulanırken hangi adım önceliklidir?",
        "Aşağıdakilerden hangisi {konu} konusundaki {kavram} ile ilgili değildir?",
        "{konu} konusunda {kavram} ve {kavram2} nasıl birlikte kullanılır?",
    ],
}

# Metin (açık uçlu) soru kökleri
TEXT_STEM_TEMPLATES = {
    "_ortak": [
        "{konu} konusunda {kavram} kavramını kendi cümlelerinizle açıklayınız.",
        "{konu} konusunda {kavram} ile {kavram2} arasındaki farkı örnekle yazınız.",
        "{konu} konusundaki {kavram} için bir örnek veriniz ve çözümünü adım adım yazınız.",
        "{konu} konusunda {kavram} neden önemlidir? Gerekçelendiriniz.",
        "{kavram} kavramının {konu} konusundaki işlevini açıklayınız.",
        "{konu} konusunda {kavram} kullanılarak çözülen bir durumu anlatınız.",
        "{konu} konusunda {kavram} ile ilgili yaptığınız çıkarımı yazınız.",
        "{konu} konusundaki {kavram} günlük hayatta nerede karşımıza çıkar? Tartışınız.",
    ],
}

# --------------------------------------------------------------------------
# Öğrenci cevabı cümleleri (kısa, derse uygun)
# --------------------------------------------------------------------------

ANSWER_OPENERS = {
    "mat": ["{kavram} tanımını kullandım.", "Önce {kavram} değerini buldum.",
            "{konu} konusunda {kavram} bağıntısını yazdım.",
            "Verilenleri {kavram} için yerine koydum."],
    "fiz": ["{kavram} korunumunu kullandım.", "Önce {kavram} büyüklüğünü hesapladım.",
            "{konu} konusunda {kavram} bağıntısını yazdım.",
            "Sistemi çizip {kavram} yönünü belirledim."],
    "kim": ["{kavram} değerini hesapladım.", "Önce {kavram} için verilenleri yazdım.",
            "{konu} konusunda {kavram} ilişkisini kullandım.",
            "Tepkime denklemini denkleştirdim."],
    "biy": ["{kavram} olayını adım adım düşündüm.", "Önce {kavram} aşamasını belirledim.",
            "{konu} konusunda {kavram} ile {kavram2} ilişkisini kurdum.",
            "Şemayı çizerek {kavram} sırasını yazdım."],
    "tar": ["{kavram} gelişmesini nedenleriyle açıkladım.",
            "Önce dönemin koşullarını yazdım.",
            "{konu} konusunda {kavram} sonuçlarını sıraladım.",
            "Olayı {kavram} açısından değerlendirdim."],
    "cog": ["{kavram} etkisini göz önüne aldım.", "Önce bölgenin özelliklerini yazdım.",
            "{konu} konusunda {kavram} ile {kavram2} ilişkisini kurdum.",
            "Harita üzerinden {kavram} dağılışını inceledim."],
    "edb": ["Metinde {kavram} kullanıldığını düşünüyorum.",
            "Önce şiirin/metnin temasını belirledim.",
            "{konu} konusunda {kavram} işlevini açıkladım.",
            "Yazarın anlatımında {kavram} öne çıkıyor."],
    "ing": ["I used {kavram} in my answer.", "First I found the correct tense.",
            "I explained {kavram} with an example.",
            "I compared {kavram} and {kavram2}."],
    "din": ["{kavram} ilkesini esas aldım.", "Önce kavramın anlamını yazdım.",
            "{konu} konusunda {kavram} örneğini verdim."],
    "bed": ["{kavram} çalışmasını anlattım.", "Önce ısınma aşamasını yazdım.",
            "{konu} konusunda {kavram} amacını açıkladım."],
    "gen": ["{kavram} adımını uyguladım.", "Önce planı çıkardım.",
            "{konu} konusunda {kavram} yaklaşımını kullandım."],
}

ANSWER_BODIES = {
    "mat": ["İşlem sonucunda {n} buldum.", "Sadeleştirince {n}/{m} kaldı.",
            "İki kök de tanım kümesinde olduğu için ikisini de yazdım.",
            "Grafiği çizince kesişim noktası {n} çıktı.",
            "Kontrol ettiğimde eşitlik sağlandı."],
    "fiz": ["Sonuç {n} {birim} çıktı.", "Enerji kaybı olmadığı için sonuç değişmedi.",
            "Yön farkını dikkate alınca işaret değişti.",
            "Birimleri kontrol ettiğimde tutarlı çıktı."],
    "kim": ["Sonuç {n} {birim} oldu.", "Derişim arttıkça tepkime hızlandı.",
            "Sıcaklık artışı dengeyi ürünler yönüne kaydırdı.",
            "Denkleştirme sonrası katsayılar {n} ve {m} oldu."],
    "biy": ["Kromozom sayısı korunduğu için sonuç değişmedi.",
            "Çaprazlama sonucunda oran {n}/{m} çıktı.",
            "Enzim çalışmayınca olay durdu.",
            "Şemada {kavram} sırasını gösterdim."],
    "tar": ["Bu nedenle {kavram} hızlanmıştır.",
            "Sonuçta merkezî otorite güçlenmiştir.",
            "Bu gelişme sonraki dönemi doğrudan etkilemiştir.",
            "Ekonomik nedenler de belirleyici olmuştur."],
    "cog": ["Bu yüzden nüfus kıyıda yoğunlaşmıştır.",
            "Yükseltinin artması sıcaklığı düşürmüştür.",
            "Ulaşım kolaylığı üretimi artırmıştır.",
            "Bu durum göçü hızlandırmıştır."],
    "edb": ["Bu yüzden anlatım daha etkili olmuştur.",
            "Okuyucuda merak duygusu uyandırılmıştır.",
            "Söz sanatı anlamı güçlendirmiştir.",
            "Bu bölüm olay örgüsünün düğüm kısmıdır."],
    "ing": ["So the correct answer is the present perfect form.",
            "That is why we use 'since' with a point in time.",
            "The passive form changes the focus of the sentence.",
            "I gave an example sentence to explain it."],
    "din": ["Bu davranış toplumda güveni artırır.",
            "Bu ilke günlük hayatta paylaşmayı öğretir.",
            "Sorumluluk bilinci bu şekilde gelişir."],
    "bed": ["Böylece sakatlanma riski azalır.",
            "Nabız takibi yapılarak şiddet ayarlanır.",
            "Tekrar sayısı kondisyona göre artırılır."],
    "gen": ["Bu sayede çalışma daha verimli oldu.",
            "Adımları sırayla uygulayınca sonuç netleşti."],
}

ANSWER_CLOSERS = {
    "ing": ["I am not sure about the last part.",
            "I checked my answer with the example in the book.",
            "I wrote it shortly because of the time.",
            "I think my explanation is correct."],
    "_ortak": ["Bu nedenle sonucun doğru olduğunu düşünüyorum.",
               "Emin olamadığım tek yer son adımdı.",
               "Kontrol ettiğimde tutarlı göründü.",
               "Zamanım kalmadığı için kısa yazdım.",
               "Örneği defterimdeki çözümle karşılaştırdım."],
}

# Zayıf öğrenci cevapları (kısa, eksik ama anlamlı)
WEAK_ANSWERS = [
    "{kavram} olduğunu düşünüyorum ama emin değilim.",
    "{konu} konusunu tam çalışamadım.",
    "Sadece ilk adımı yapabildim.",
    "{kavram} kuralını hatırlayamadım.",
    "Sanırım sonuç {n} çıkıyor.",
    "Bu soruyu derste tekrar etmek istiyorum.",
    "{kavram} ile ilgili olduğunu biliyorum ama çözemedim.",
]

MAX_ANSWER_CHARS = 400


# --------------------------------------------------------------------------
# Üreticiler
# --------------------------------------------------------------------------

def _area(area):
    if area in NUMERIC_AREAS or area in CONCEPTS:
        return area
    return "gen"


def concept_pool(area, subject_name):
    """Kavram havuzu: sayısal derslerde KONU düzeyi, sözel derslerde ders düzeyi."""
    area = _area(area)
    if area in NUMERIC_AREAS:
        pool = SUBJECT_CONCEPTS.get(subject_name)
        if pool:
            return pool
        return GENERIC_NUMERIC_CONCEPTS[area]
    return CONCEPTS[area]


def _unit_for(rng, area, subject_name, concept):
    units = SUBJECT_UNITS.get(subject_name)
    if units:
        return units[rng.randrange(len(units))]
    unit = CONCEPT_UNITS.get(concept)
    if unit:
        return unit
    pool = UNITS.get(area, ["birim"])
    return pool[rng.randrange(len(pool))]


def _fill(rng, template, area, subject_name, pool):
    """Şablondaki değişkenleri konuya uygun değerlerle doldurur."""
    out = template
    picked = None
    if "{kavram}" in out:
        picked = pool[rng.randrange(len(pool))]
        out = out.replace("{kavram}", picked)
    if "{kavram2}" in out:
        out = out.replace("{kavram2}", pool[rng.randrange(len(pool))])
    if "{konu}" in out:
        out = out.replace("{konu}", subject_name)
    if "{birim}" in out:
        out = out.replace("{birim}", _unit_for(rng, area, subject_name, picked))
    if "{n}" in out:
        out = out.replace("{n}", str(rng.randint(2, 99)))
    if "{m}" in out:
        out = out.replace("{m}", str(rng.randint(2, 49)))
    if "{d}" in out:
        out = out.replace("{d}", str(rng.randint(100, 999)))
    if "{r}" in out:
        out = out.replace("{r}", str(rng.randint(1, 9)))
    if "{s}" in out:
        out = out.replace("{s}", str(rng.randint(2, 9)))
    if "{yil2}" in out:
        out = out.replace("{yil2}", str(rng.randint(1900, 1999)))
    if "{yil}" in out:
        out = out.replace("{yil}", str(rng.randint(1071, 1938)))
    if "{kisi}" in out:
        out = out.replace("{kisi}", PEOPLE_TR[rng.randrange(len(PEOPLE_TR))])
    if "{eser}" in out:
        out = out.replace("{eser}", WORKS_TR[rng.randrange(len(WORKS_TR))])
    if "{yer}" in out:
        out = out.replace("{yer}", PLACES_TR[rng.randrange(len(PLACES_TR))])
    if "{soz}" in out:
        out = out.replace("{soz}", ENG_WORDS[rng.randrange(len(ENG_WORDS))])
    return out


def _choice_templates(area, choice_kind):
    templates = CHOICE_TEMPLATES[area]
    if isinstance(templates, dict):
        return templates.get(choice_kind) or templates["ifade"]
    return templates


def make_choices(rng, area, subject_name, k, choice_kind="ifade"):
    """Aynı soru içinde birbirinden farklı k şık metni üretir.

    `choice_kind` soru kökünden gelir: `sayisal` değer isteyen köke, `ifade`
    yargı isteyen köke uygun şıklar üretir.
    """
    area = _area(area)
    pool = concept_pool(area, subject_name)
    templates = _choice_templates(area, choice_kind)
    out = []
    seen = set()
    guard = 0
    while len(out) < k and guard < 40 * k:
        guard += 1
        text = _fill(rng, templates[rng.randrange(len(templates))],
                     area, subject_name, pool)
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    while len(out) < k:                      # teorik olarak ulaşılmaz güvenlik ağı
        text = "%s (%d. seçenek)" % (subject_name, len(out) + 1)
        if text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _pick_stem(rng, area):
    item = STEM_TEMPLATES[area][rng.randrange(len(STEM_TEMPLATES[area]))]
    if isinstance(item, tuple):
        return item
    return item, "ifade"


# Aynı sınav içinde kök tekrarı olmaması için kaç kez yeniden çekileceği.
# Son çare ek kullanıldıysa sayaca yazılır (sessiz tekrar bırakılmaz).
STEM_RETRY = 24
STATS = {"kok_yeniden_cekim": 0, "kok_varyant_eki": 0}


def _unique_stem(rng, area, subject_name, pool, make, avoid):
    """`avoid` kümesinde olmayan bir kök üretir.

    Önce şablon ve değişkenler yeniden çekilir; havuz gerçekten tükenmişse
    (çok küçük konu havuzları) ayırt edici bir ek eklenir ve sayılır.
    """
    stem, choice_kind = make()
    if not avoid:
        return stem, choice_kind
    tries = 0
    while stem in avoid and tries < STEM_RETRY:
        stem, choice_kind = make()
        tries += 1
        STATS["kok_yeniden_cekim"] += 1
    if stem in avoid:
        base = stem
        n = 2
        while stem in avoid:
            stem = "%s (%d. biçim)" % (base, n)
            n += 1
        STATS["kok_varyant_eki"] += 1
    return stem, choice_kind


def make_question(rng, area, subject_name, k, avoid=None):
    """Bir çoktan seçmeli soru: (kök, şık metinleri).

    Kök ve şıklar AYNI konu havuzunu ve kökün istediği şık tipini kullanır.
    `avoid` verilirse kök o kümedeki metinlerden farklı olur (sınav içi tekilik).
    """
    area = _area(area)
    pool = concept_pool(area, subject_name)

    def _make():
        template, choice_kind = _pick_stem(rng, area)
        return _fill(rng, template, area, subject_name, pool), choice_kind

    stem, choice_kind = _unique_stem(rng, area, subject_name, pool, _make, avoid)
    choices = make_choices(rng, area, subject_name, k, choice_kind)
    return stem, choices


def make_stem(rng, area, subject_name, kind="choice", avoid=None):
    """Tek başına soru kökü (metin soruları için)."""
    area = _area(area)
    pool = concept_pool(area, subject_name)

    def _make():
        if kind == "text":
            templates = TEXT_STEM_TEMPLATES["_ortak"]
            return _fill(rng, templates[rng.randrange(len(templates))],
                         area, subject_name, pool), "ifade"
        template, choice_kind = _pick_stem(rng, area)
        return _fill(rng, template, area, subject_name, pool), choice_kind

    stem, _kind = _unique_stem(rng, area, subject_name, pool, _make, avoid)
    return stem


def make_answer(rng, area, subject_name, quality):
    """Gerçekçi, kısa öğrenci cevabı.

    quality: 'strong' | 'normal' | 'weak'
    En fazla MAX_ANSWER_CHARS karakter, daima tam cümleyle biter.
    """
    area = _area(area)
    pool = concept_pool(area, subject_name)
    closers = ANSWER_CLOSERS.get(area, ANSWER_CLOSERS["_ortak"])
    if quality == "weak":
        sentences = [_fill(rng, WEAK_ANSWERS[rng.randrange(len(WEAK_ANSWERS))],
                           area, subject_name, pool)]
        if rng.random() < 0.25:
            sentences.append(_fill(rng, closers[rng.randrange(len(closers))],
                                   area, subject_name, pool))
    else:
        openers = ANSWER_OPENERS[area]
        bodies = ANSWER_BODIES[area]
        sentences = [_fill(rng, openers[rng.randrange(len(openers))],
                           area, subject_name, pool)]
        sentences.append(_fill(rng, bodies[rng.randrange(len(bodies))],
                               area, subject_name, pool))
        # Ortanca uzunluk ~120 karakter olsun diye ikinci gövde cümlesi ve
        # kapanış cümlesi bu oranlarla eklenir.
        if quality == "strong" or rng.random() < 0.32:
            second = _fill(rng, bodies[rng.randrange(len(bodies))],
                           area, subject_name, pool)
            if second not in sentences:
                sentences.append(second)
        if quality == "strong" or rng.random() < 0.58:
            sentences.append(_fill(rng, closers[rng.randrange(len(closers))],
                                   area, subject_name, pool))
    text = " ".join(sentences)
    if len(text) > MAX_ANSWER_CHARS:
        # Kelime ortasından kesme yok: son tam cümlede dur.
        kept = []
        total = 0
        for s in sentences:
            if total + len(s) + 1 > MAX_ANSWER_CHARS:
                break
            kept.append(s)
            total += len(s) + 1
        text = " ".join(kept) if kept else sentences[0][:MAX_ANSWER_CHARS - 1] + "."
    return text



# ==========================================================================
# BİLİŞSEL BOYUT ETİKETLERİ → METİN  (zincir A)
#
# NEDEN: Önceki sürümde soru metni ile madde zorluğu BAĞIMSIZ üretiliyordu;
# metni okuyan bir insan ya da LLM "bu soru analiz gerektiriyor" dese bile o
# soru gerçekten daha zor değildi (ölçülen korelasyon ~0). Artık sıra tersine
# çevrildi: önce maddenin GERÇEK etiketleri belirlenir, metin o etiketlerden
# üretilir, zorluk da o etiketlerden türer (`config.DIM_B_EFFECT`).
#
# Etiket adları ve değerleri `service/src/segment/rubric.py` ile BİREBİR
# aynıdır; aksi hâlde segmentasyon hattının çıktısı altın etiketle
# karşılaştırılamaz.
# ==========================================================================

#: Boyut → izinli etiketler. rubric.DIMENSIONS ile birebir eşleşmelidir.
DIMENSION_LABELS = {
    "bilissel_talep": ("hatirlama", "uygulama", "analiz"),
    "adim_sayisi": ("tek_adim", "cok_adim"),
    "dikkat_tuzagi": ("var", "yok"),
    "okuma_yuku": ("dusuk", "yuksek"),
}

#: Yüksek okuma yükü kökünün asgari karakter sayısı (düşük olanlar ~150).
READING_HIGH_MIN_CHARS = 400

# Sayısal / sözel ders grupları: çok adımlı kök ve okuma bağlamı şablonları
# ders başına değil, grup başına tutulur (havuz büyüklüğü yeterli, tekrar
# eşikleri değişkenlerle karşılanıyor).
_NUMERIC_GROUP = "_sayisal"
_VERBAL_GROUP = "_sozel"


def _group(area):
    return _NUMERIC_GROUP if area in NUMERIC_AREAS else _VERBAL_GROUP


# --------------------------------------------------------------------------
# 1) Bilişsel düzeye göre soru kökü şablonları
#    (şablon, şık_tipi) — şık tipi kökün istediği şık biçimini belirler.
# --------------------------------------------------------------------------

LEVEL_STEM_TEMPLATES = {
    "mat": {
        "hatirlama": [
            ("Aşağıdakilerden hangisi {konu} konusundaki {kavram} kavramının tanımıdır?", "ifade"),
            ("{konu} konusunda {kavram} nedir?", "ifade"),
            ("{konu} konusunda {kavram} için verilen tanım hangisidir?", "ifade"),
            ("{konu}: {kavram} teriminin karşılığı aşağıdakilerden hangisidir?", "ifade"),
            ("{konu} konusunda {kavram} kavramı hangi ifadeyle adlandırılır?", "ifade"),
            ("{konu} konusunda {kavram} ile ilgili doğru tanım hangisidir?", "ifade"),
        ],
        "uygulama": [
            ("{konu} konusunda {kavram} {n} olarak verilmiştir. Bilinen bağıntıyı "
             "uygulayarak sonucu hesaplayınız. Sonuç kaçtır?", "sayisal"),
            ("{konu}: {kavram} {n} ve {kavram2} {m} iken kuralı uygulayınız; sonuç kaçtır?", "sayisal"),
            ("{konu} konusunda {kavram} için verilen formülde {n} değerini yerine "
             "koyduğunuzda sonuç kaçtır?", "sayisal"),
            ("{konu} konusunda {kavram} {n} birim artırılırsa yeni değer kaçtır?", "sayisal"),
            ("{n} ve {m} sayıları için {konu} konusundaki {kavram} kuralını uygulayınız. "
             "Sonuç kaçtır?", "sayisal"),
            ("{konu} konusunda {kavram2} {m} iken {kavram} değerini hesaplayınız. Kaçtır?", "sayisal"),
        ],
        "analiz": [
            ("{konu} konusunda {kavram} ile {kavram2} karşılaştırıldığında aşağıdakilerden "
             "hangisi söylenemez?", "ifade"),
            ("{konu} konusunda verilen {kavram} ve {kavram2} bilgilerine göre hangi çıkarım "
             "yapılamaz?", "ifade"),
            ("{konu}: {kavram} {n} iken {kavram2} için yapılan hangi yorum çelişki doğurur?", "ifade"),
            ("{konu} konusunda {kavram} ile {kavram2} arasındaki ilişkiye bakıldığında hangi "
             "seçenek yanlıştır?", "ifade"),
            ("{konu} konusunda iki farklı {kavram} değeri karşılaştırıldığında hangi genelleme "
             "desteklenmez?", "ifade"),
            ("{konu} konusunda {kavram} ve {kavram2} birlikte değerlendirildiğinde hangi "
             "gerekçelendirme geçersizdir?", "ifade"),
        ],
    },
    "fiz": {
        "hatirlama": [
            ("Aşağıdakilerden hangisi {konu} konusundaki {kavram} kavramının tanımıdır?", "ifade"),
            ("{konu} konusunda {kavram} nedir?", "ifade"),
            ("{konu}: {kavram} için verilen tanım hangisidir?", "ifade"),
            ("{konu} konusunda {kavram} hangi ifadeyle tanımlanır?", "ifade"),
            ("{konu} konusunda {kavram} ile ilgili doğru tanım hangisidir?", "ifade"),
            ("{konu} konusunda {kavram} teriminin karşılığı hangisidir?", "ifade"),
        ],
        "uygulama": [
            ("{konu} konusunda {kavram} {n} {birim} olarak ölçülmüştür. Bilinen bağıntıyı "
             "uygulayarak sonucu hesaplayınız. Sonuç kaçtır?", "sayisal"),
            ("{konu}: {kavram2} {m} iken {kavram} değerini bağıntıda yerine koyarak bulunuz. "
             "Kaçtır?", "sayisal"),
            ("Sürtünmesiz ortamda {konu} konusunda {kavram} {n} {birim} ise sonuç kaçtır?", "sayisal"),
            ("{konu} konusunda {kavram} için verilen formüle {n} değeri konulduğunda sonuç "
             "kaçtır?", "sayisal"),
            ("{konu} konusunda {kavram} {n} {birim} iken kuralı uygulayınız; sonuç kaçtır?", "sayisal"),
        ],
        "analiz": [
            ("{konu} konusunda {kavram} ile {kavram2} karşılaştırıldığında hangisi söylenemez?", "ifade"),
            ("{konu} deneyinde {kavram} ve {kavram2} ölçülmüştür; hangi çıkarım yapılamaz?", "ifade"),
            ("{konu}: {kavram} {n} {birim} iken {kavram2} için hangi yorum çelişkilidir?", "ifade"),
            ("{konu} konusunda {kavram} ile {kavram2} arasındaki ilişkiye göre hangi seçenek "
             "yanlıştır?", "ifade"),
            ("{konu} konusunda iki ölçüm karşılaştırıldığında {kavram} için hangi genelleme "
             "desteklenmez?", "ifade"),
            ("{konu} konusunda {kavram} ve {kavram2} birlikte değerlendirildiğinde hangi "
             "gerekçelendirme geçersizdir?", "ifade"),
        ],
    },
    "kim": {
        "hatirlama": [
            ("Aşağıdakilerden hangisi {konu} konusundaki {kavram} kavramının tanımıdır?", "ifade"),
            ("{konu} konusunda {kavram} nedir?", "ifade"),
            ("{konu}: {kavram} için verilen tanım hangisidir?", "ifade"),
            ("{konu} konusunda {kavram} hangi ifadeyle adlandırılır?", "ifade"),
            ("{konu} konusunda {kavram} ile ilgili doğru tanım hangisidir?", "ifade"),
            ("{konu} konusunda {kavram} teriminin karşılığı hangisidir?", "ifade"),
        ],
        "uygulama": [
            ("{konu} konusunda {n} {birim} örnek için {kavram} değerini hesaplayınız. Kaçtır?", "sayisal"),
            ("{konu}: {kavram2} {m} iken {kavram} değerini bağıntıda yerine koyarak bulunuz. "
             "Kaçtır?", "sayisal"),
            ("{konu} konusunda {kavram} için verilen bağıntıya {n} değeri konulduğunda sonuç "
             "kaçtır?", "sayisal"),
            ("{konu} konusunda {kavram} {n} {birim} iken kuralı uygulayınız; sonuç kaçtır?", "sayisal"),
            ("{konu} konusunda {kavram} değerini verilen veriyle hesaplayınız. Sonuç kaçtır?", "sayisal"),
        ],
        "analiz": [
            ("{konu} konusunda {kavram} ile {kavram2} karşılaştırıldığında hangisi söylenemez?", "ifade"),
            ("{konu} konusunda verilen {kavram} ve {kavram2} verilerine göre hangi çıkarım "
             "yapılamaz?", "ifade"),
            ("{konu}: {kavram} {n} {birim} iken {kavram2} için hangi yorum çelişkilidir?", "ifade"),
            ("{konu} konusunda {kavram} ve {kavram2} ilişkisine göre hangi seçenek yanlıştır?", "ifade"),
            ("{konu} konusunda iki farklı ortam karşılaştırıldığında {kavram} için hangi "
             "genelleme desteklenmez?", "ifade"),
            ("{konu} konusunda {kavram} ve {kavram2} birlikte değerlendirildiğinde hangi "
             "gerekçelendirme geçersizdir?", "ifade"),
        ],
    },
    "biy": {
        "hatirlama": [
            ("Aşağıdakilerden hangisi {konu} konusundaki {kavram} kavramının tanımıdır?", "ifade"),
            ("{konu} konusunda {kavram} nedir?", "ifade"),
            ("{konu}: {kavram} için verilen tanım hangisidir?", "ifade"),
            ("{konu} konusunda {kavram} hangi ifadeyle adlandırılır?", "ifade"),
            ("{konu} konusunda {kavram} ile ilgili doğru tanım hangisidir?", "ifade"),
            ("{konu} konusunda {kavram} teriminin karşılığı hangisidir?", "ifade"),
        ],
        "uygulama": [
            ("{konu} konusunda {kavram} {n} ise kuralı uygulayarak {kavram2} değerini bulunuz. "
             "Kaçtır?", "sayisal"),
            ("{konu}: {kavram} sayısını verilen veriyle hesaplayınız. Kaçtır?", "sayisal"),
            ("{konu} konusunda {kavram} oranını {n} verisiyle hesaplayınız. Sonuç kaçtır?", "sayisal"),
            ("{konu} konusunda {kavram} için verilen bağıntıya {n} değeri konulduğunda sonuç "
             "kaçtır?", "sayisal"),
            ("{konu} konusunda {kavram2} {m} iken {kavram} değeri kaçtır?", "sayisal"),
        ],
        "analiz": [
            ("{konu} konusunda {kavram} ile {kavram2} karşılaştırıldığında hangisi söylenemez?", "ifade"),
            ("{konu} konusunda verilen {kavram} ve {kavram2} gözlemlerine göre hangi çıkarım "
             "yapılamaz?", "ifade"),
            ("{konu}: {kavram} engellenirse {kavram2} için hangi yorum çelişkilidir?", "ifade"),
            ("{konu} konusunda {kavram} ve {kavram2} ilişkisine göre hangi seçenek yanlıştır?", "ifade"),
            ("{konu} konusunda iki gözlem karşılaştırıldığında {kavram} için hangi genelleme "
             "desteklenmez?", "ifade"),
            ("{konu} konusunda {kavram} ve {kavram2} birlikte değerlendirildiğinde hangi "
             "gerekçelendirme geçersizdir?", "ifade"),
        ],
    },
    "tar": {
        "hatirlama": [
            ("Aşağıdakilerden hangisi {konu} konusundaki {kavram} kavramının tanımıdır?", "ifade"),
            ("{konu} konusunda {kavram} hangi yılda gerçekleşmiştir?", "ifade"),
            ("{konu}: {kavram} kimin döneminde uygulanmıştır?", "ifade"),
            ("{konu} konusunda {kavram} için verilen tanım hangisidir?", "ifade"),
            ("{konu} konusunda {kavram} nedir?", "ifade"),
        ],
        "uygulama": [
            ("{konu} konusunda {kavram} ilkesini {yil} yılındaki duruma uygulayınız; hangi "
             "sonuç doğar?", "ifade"),
            ("{konu}: {kavram} kuralı {kisi} dönemine uygulandığında hangi uygulama görülür?", "ifade"),
            ("{konu} konusunda {kavram} ölçütünü kullanarak {yil}-{yil2} aralığını "
             "sıralayınız; hangisi doğrudur?", "ifade"),
            ("{konu} konusunda {kavram} tanımını verilen örneğe uygulayınız. Hangisi doğrudur?", "ifade"),
        ],
        "analiz": [
            ("{konu} konusunda {kavram} ile {kavram2} karşılaştırıldığında hangisi söylenemez?", "ifade"),
            ("{konu} konusunda {yil} yılındaki {kavram} ile ilgili hangi çıkarım yapılamaz?", "ifade"),
            ("{konu}: {kavram} ve {kavram2} birlikte değerlendirildiğinde hangi yorum "
             "çelişkilidir?", "ifade"),
            ("{konu} konusunda {kisi} dönemindeki {kavram} için hangi neden-sonuç ilişkisi "
             "kurulamaz?", "ifade"),
            ("{konu} konusunda iki kaynak karşılaştırıldığında {kavram} için hangi genelleme "
             "desteklenmez?", "ifade"),
        ],
    },
    "cog": {
        "hatirlama": [
            ("Aşağıdakilerden hangisi {konu} konusundaki {kavram} kavramının tanımıdır?", "ifade"),
            ("{konu} konusunda {kavram} nedir?", "ifade"),
            ("{konu}: {kavram} hangi bölgede görülür?", "ifade"),
            ("{konu} konusunda {kavram} için verilen tanım hangisidir?", "ifade"),
            ("{konu} konusunda {kavram} hangi ifadeyle adlandırılır?", "ifade"),
        ],
        "uygulama": [
            ("{konu} konusunda {kavram} {n} {birim} iken kuralı uygulayınız; sonuç kaçtır?", "sayisal"),
            ("{konu}: {yer} için {kavram} değerini hesaplayınız. Kaçtır?", "sayisal"),
            ("{konu} konusunda {kavram} bağıntısına {n} değeri konulduğunda sonuç kaçtır?", "sayisal"),
            ("{konu} konusunda {kavram2} {m} iken {kavram} kaç {birim} olur?", "sayisal"),
        ],
        "analiz": [
            ("{konu} konusunda {kavram} ile {kavram2} karşılaştırıldığında hangisi söylenemez?", "ifade"),
            ("{konu} konusunda {yer} verileri incelendiğinde {kavram} için hangi çıkarım "
             "yapılamaz?", "ifade"),
            ("{konu}: {kavram} ve {kavram2} birlikte değerlendirildiğinde hangi yorum "
             "çelişkilidir?", "ifade"),
            ("{konu} konusunda dağılış haritasına göre {kavram} için hangi genelleme "
             "desteklenmez?", "ifade"),
            ("{konu} konusunda {kavram} ile ilgili hangi neden-sonuç ilişkisi kurulamaz?", "ifade"),
        ],
    },
    "edb": {
        "hatirlama": [
            ("Aşağıdakilerden hangisi {konu} konusundaki {kavram} kavramının tanımıdır?", "ifade"),
            ("{konu} konusunda {kavram} nedir?", "ifade"),
            ("{konu}: {eser} adlı eserin yazarı kimdir?", "ifade"),
            ("{konu} konusunda {kavram} için verilen tanım hangisidir?", "ifade"),
            ("{konu} konusunda {kavram} hangi terimle adlandırılır?", "ifade"),
        ],
        "uygulama": [
            ("{konu} konusunda {kavram} kuralını verilen dizeye uygulayınız; hangisi doğrudur?", "ifade"),
            ("{konu}: {eser} adlı eserden alınan bölümde {kavram} nasıl uygulanır?", "ifade"),
            ("{konu} konusunda {kavram} kuralı {n}. dizeye uygulandığında hangi sonuç çıkar?", "ifade"),
            ("{konu} konusunda {kavram} tanımını verilen örneğe uygulayınız. Hangisi doğrudur?", "ifade"),
        ],
        "analiz": [
            ("{konu} konusunda {kavram} ile {kavram2} karşılaştırıldığında hangisi söylenemez?", "ifade"),
            ("{konu} konusunda verilen parçada {kavram} için hangi çıkarım yapılamaz?", "ifade"),
            ("{konu}: {eser} ile {kisi} anlatımı karşılaştırıldığında {kavram} için hangi yorum "
             "çelişkilidir?", "ifade"),
            ("{konu} konusunda {kavram} ve {kavram2} birlikte değerlendirildiğinde hangi seçenek "
             "yanlıştır?", "ifade"),
            ("{konu} konusunda parçanın anlatıcısı için {kavram} bakımından hangi genelleme "
             "desteklenmez?", "ifade"),
        ],
    },
    "ing": {
        "hatirlama": [
            ("Which one is the definition of {kavram}? ({konu})", "ifade"),
            ("{konu}: what does {kavram} mean?", "ifade"),
            ("Which option gives the correct meaning of '{soz}'? ({konu})", "ifade"),
            ("{konu} konusunda {kavram} nedir?", "ifade"),
            ("Which one names the rule of {kavram}? ({konu})", "ifade"),
        ],
        "uygulama": [
            ("Apply the rule of {kavram} to '{soz}' and choose the correct form. ({konu})", "ifade"),
            ("Fill in the blank with the correct {kavram} form of '{soz}'. ({konu})", "ifade"),
            ("{konu}: rewrite the sentence using {kavram}; which option is correct?", "ifade"),
            ("Use {kavram} with '{soz}' and choose the correct sentence. ({konu})", "ifade"),
        ],
        "analiz": [
            ("Compare {kavram} and {kavram2}; which statement CANNOT be said? ({konu})", "ifade"),
            ("{konu}: according to the paragraph, which inference about {kavram} is NOT "
             "possible?", "ifade"),
            ("Which option contradicts the use of {kavram} in the text? ({konu})", "ifade"),
            ("{konu} konusunda {kavram} ile {kavram2} karşılaştırıldığında hangi yorum "
             "desteklenmez?", "ifade"),
        ],
    },
    "din": {
        "hatirlama": [
            ("Aşağıdakilerden hangisi {konu} konusundaki {kavram} kavramının tanımıdır?", "ifade"),
            ("{konu} konusunda {kavram} nedir?", "ifade"),
            ("{konu}: {kavram} için verilen tanım hangisidir?", "ifade"),
            ("{konu} konusunda {kavram} hangi terimle adlandırılır?", "ifade"),
        ],
        "uygulama": [
            ("{konu} konusunda {kavram} ilkesini verilen davranışa uygulayınız; hangisi "
             "doğrudur?", "ifade"),
            ("{konu}: {kavram} ilkesi günlük bir duruma uygulandığında hangi sonuç doğar?", "ifade"),
            ("{konu} konusunda {kavram} kuralını örneğe uygulayınız. Hangisi doğrudur?", "ifade"),
        ],
        "analiz": [
            ("{konu} konusunda {kavram} ile {kavram2} karşılaştırıldığında hangisi söylenemez?", "ifade"),
            ("{konu} konusunda verilen örnekten {kavram} için hangi çıkarım yapılamaz?", "ifade"),
            ("{konu}: {kavram} ve {kavram2} birlikte değerlendirildiğinde hangi yorum "
             "çelişkilidir?", "ifade"),
        ],
    },
    "bed": {
        "hatirlama": [
            ("Aşağıdakilerden hangisi {konu} konusundaki {kavram} kavramının tanımıdır?", "ifade"),
            ("{konu} konusunda {kavram} nedir?", "ifade"),
            ("{konu}: {kavram} için verilen tanım hangisidir?", "ifade"),
            ("{konu} konusunda {kavram} hangi terimle adlandırılır?", "ifade"),
        ],
        "uygulama": [
            ("{konu} konusunda {kavram} {n} {birim} uygulandığında hangi sonuç beklenir?", "ifade"),
            ("{konu}: {kavram} kuralını verilen duruma uygulayınız; hangisi doğrudur?", "ifade"),
            ("{konu} konusunda {kavram} tekniğini örneğe uygulayınız. Hangisi doğrudur?", "ifade"),
        ],
        "analiz": [
            ("{konu} konusunda {kavram} ile {kavram2} karşılaştırıldığında hangisi söylenemez?", "ifade"),
            ("{konu} konusunda verilen ölçümlerden {kavram} için hangi çıkarım yapılamaz?", "ifade"),
            ("{konu}: {kavram} ve {kavram2} birlikte değerlendirildiğinde hangi yorum "
             "çelişkilidir?", "ifade"),
        ],
    },
    "gen": {
        "hatirlama": [
            ("Aşağıdakilerden hangisi {konu} konusundaki {kavram} kavramının tanımıdır?", "ifade"),
            ("{konu} konusunda {kavram} nedir?", "ifade"),
            ("{konu}: {kavram} için verilen tanım hangisidir?", "ifade"),
            ("{konu} konusunda {kavram} hangi terimle adlandırılır?", "ifade"),
        ],
        "uygulama": [
            ("{konu} konusunda {kavram} adımını verilen duruma uygulayınız; hangisi doğrudur?", "ifade"),
            ("{konu}: {kavram} kuralı {n}. adımda uygulandığında hangi sonuç çıkar?", "ifade"),
            ("{konu} konusunda {kavram} tekniğini örneğe uygulayınız. Hangisi doğrudur?", "ifade"),
        ],
        "analiz": [
            ("{konu} konusunda {kavram} ile {kavram2} karşılaştırıldığında hangisi söylenemez?", "ifade"),
            ("{konu} konusunda verilen bilgilerden {kavram} için hangi çıkarım yapılamaz?", "ifade"),
            ("{konu}: {kavram} ve {kavram2} birlikte değerlendirildiğinde hangi yorum "
             "çelişkilidir?", "ifade"),
        ],
    },
}


# --------------------------------------------------------------------------
# 2) ÇOK ADIMLI kökler — birinin çıktısı diğerinin girdisi olan İKİ işlem
#    kökte AÇIKÇA görünür ("önce … sonra …" / "birinci adımda … ikinci adımda").
#    `hatirlama` düzeyinde çok adım üretilmez (tutarsız etiket olurdu).
# --------------------------------------------------------------------------

MULTISTEP_STEM_TEMPLATES = {
    _NUMERIC_GROUP: {
        "uygulama": [
            ("{konu} konusunda önce {kavram2} değerini {n} verisinden hesaplayınız; sonra "
             "bulduğunuz bu değeri {kavram} bağıntısında yerine koyarak sonucu bulunuz. "
             "Sonuç kaçtır?", "sayisal"),
            ("{konu}: birinci adımda {n} değerini {birim} birimine çeviriniz, ikinci adımda "
             "çevirdiğiniz değerle {kavram} bağıntısını uygulayınız. Sonuç kaçtır?", "sayisal"),
            ("{konu} konusunda önce {kavram} için denklemi kurunuz, sonra kurduğunuz denklemi "
             "çözerek {kavram2} değerini bulunuz. Sonuç kaçtır?", "sayisal"),
            ("{konu} konusunda ilk adımda {kavram2} oranını {m} verisiyle bulunuz; ikinci "
             "adımda bu oranı {kavram} ifadesinde kullanarak sonucu hesaplayınız. Kaçtır?", "sayisal"),
            ("{konu}: önce {kavram} ara değerini {n} ve {m} sayılarından elde ediniz, sonra "
             "bu ara değeri {kavram2} bağıntısına girdi olarak veriniz. Sonuç kaçtır?", "sayisal"),
        ],
        "analiz": [
            ("{konu} konusunda önce {kavram2} değerini {n} verisinden hesaplayınız; sonra bu "
             "sonucu {kavram} ile karşılaştırarak hangi çıkarımın yapılamayacağını "
             "belirleyiniz.", "ifade"),
            ("{konu}: birinci adımda {kavram} ara sonucunu elde ediniz, ikinci adımda bu ara "
             "sonucu {kavram2} ölçütüyle sınayınız. Hangi yorum çelişkilidir?", "ifade"),
            ("{konu} konusunda önce {n} ve {m} verilerinden {kavram2} değerini bulunuz, sonra "
             "bulduğunuz değere göre {kavram} için hangi genellemenin desteklenmediğini "
             "belirleyiniz.", "ifade"),
            ("{konu} konusunda ilk adımda {kavram} bağıntısını kurunuz; ikinci adımda kurduğunuz "
             "bağıntıyı {kavram2} verisiyle sınayarak hangi seçeneğin yanlış olduğunu "
             "bulunuz.", "ifade"),
        ],
    },
    _VERBAL_GROUP: {
        "uygulama": [
            ("{konu} konusunda önce {kavram} kuralını belirleyiniz; sonra belirlediğiniz kuralı "
             "verilen örneğe uygulayarak sonucu bulunuz. Hangisi doğrudur?", "ifade"),
            ("{konu}: birinci adımda {kavram2} ölçütünü saptayınız, ikinci adımda bu ölçütü "
             "{kavram} örneğine uygulayınız. Hangisi doğrudur?", "ifade"),
            ("{konu} konusunda önce parçadaki {kavram} örneğini bulunuz, sonra bulduğunuz örneğe "
             "{kavram2} kuralını uygulayınız. Hangisi doğrudur?", "ifade"),
        ],
        "analiz": [
            ("{konu} konusunda önce {kavram} ile {kavram2} arasındaki bağı kurunuz; sonra "
             "kurduğunuz bağa göre hangi çıkarımın yapılamayacağını belirleyiniz.", "ifade"),
            ("{konu}: birinci adımda parçadaki {kavram} ölçütünü çıkarınız, ikinci adımda bu "
             "ölçütü {kavram2} ile karşılaştırınız. Hangi yorum çelişkilidir?", "ifade"),
            ("{konu} konusunda önce iki kaynağın {kavram} bakımından farkını saptayınız, sonra "
             "sapladığınız farka göre {kavram2} için hangi genellemenin desteklenmediğini "
             "belirleyiniz.", "ifade"),
        ],
    },
}


# --------------------------------------------------------------------------
# 3) YÜKSEK OKUMA YÜKÜ bağlamları — 3-6 cümlelik paragraf, tablo betimi ya da
#    grafik betimi. Yalnız {konu}/{kavram}/{n}/{birim} değişkenleri kullanılır:
#    başka bir dersin kavramı metne sızarsa `selfcheck` konu-kavram denetimi
#    (kusur "l") bunu ihlal sayar.
# --------------------------------------------------------------------------

READING_CONTEXTS = {
    _NUMERIC_GROUP: [
        ("Bir öğrenci ekibi {konu} konusu üzerinde üç haftalık bir inceleme yapmıştır. "
         "İncelemede {kavram} değeri önce {n} olarak kaydedilmiş, ikinci ölçümde aynı değer "
         "{m} düzeyine inmiştir. Ekip, ölçüm koşullarını değiştirmeden üçüncü bir yineleme "
         "daha yapmış ve {kavram2} için ayrı bir kayıt tutmuştur. Kayıtların tamamı aynı "
         "ölçüm düzeneğiyle ve aynı sırayla alınmıştır. Aşağıdaki soruyu bu kayıtlara göre "
         "yanıtlayınız. "),
        ("Aşağıda {konu} konusuna ait bir tablo betimlenmiştir. Tablonun birinci sütununda "
         "yineleme numarası, ikinci sütununda {kavram} değeri, üçüncü sütununda ise {kavram2} "
         "değeri yer almaktadır. Birinci yinelemede {kavram} {n}, ikinci yinelemede {m} "
         "olarak okunmuştur. Üçüncü yinelemede ölçüm tekrarlanmış ve ilk satırdaki değere "
         "yakın bir sonuç elde edilmiştir. Tablodaki hiçbir satırda eksik veri yoktur. "),
        ("Aşağıda {konu} konusuna ait bir grafik betimlenmiştir. Grafiğin yatay ekseninde "
         "yineleme sayısı, düşey ekseninde {kavram} değeri gösterilmektedir. Eğri başlangıçta "
         "{n} düzeyinden başlamakta, orta bölgede {m} düzeyine inmekte ve sonra yeniden "
         "yükselmektedir. Aynı grafik üzerinde ikinci bir eğri {kavram2} için çizilmiştir ve "
         "bu eğri boyunca belirgin bir değişim görülmemektedir. Soruyu grafiğe göre "
         "yanıtlayınız. "),
        ("Bir sınıf, {konu} konusunda iki ayrı düzenek kurmuştur. Birinci düzenekte {kavram} "
         "değeri {n} olarak ayarlanmış, ikinci düzenekte aynı büyüklük {m} düzeyine "
         "getirilmiştir. Her iki düzenekte de {kavram2} kaydı ayrıca tutulmuş ve ölçümler "
         "üçer kez yinelenmiştir. Öğrenciler, yineleme sonuçlarının ortalamasını almış ve "
         "sapması büyük olan tek bir ölçümü dışarıda bırakmıştır. Aşağıdaki soru bu iki "
         "düzeneğin karşılaştırılmasına dayanmaktadır. "),
        ("Aşağıdaki metin {konu} konusuyla ilgilidir. Bir ölçüm dizisinde {kavram} için "
         "sırasıyla {n} ve {m} değerleri elde edilmiştir. Ölçümler arasında düzenekte hiçbir "
         "değişiklik yapılmamış, yalnızca bekleme süresi uzatılmıştır. İkinci ölçümden sonra "
         "{kavram2} için de bir kayıt alınmış, bu kaydın ilk ölçümle uyumlu olduğu "
         "görülmüştür. Metindeki bilgilerin tamamı soruyu yanıtlamak için gereklidir. "),
    ],
    _VERBAL_GROUP: [
        ("Aşağıdaki parça {konu} konusuyla ilgilidir. Parçanın ilk bölümünde {kavram} "
         "kavramının nasıl kullanıldığı anlatılmakta, ikinci bölümünde ise aynı kavramın "
         "farklı bir bağlamdaki karşılığı verilmektedir. Yazar, üçüncü bölümde {kavram2} "
         "kavramına da değinmekte ve iki kavramın birbirini tamamladığını belirtmektedir. "
         "Parçanın son cümlesinde ise bu tamamlayıcılığın her durumda geçerli olmadığı "
         "söylenmektedir. Soruyu yalnızca parçaya göre yanıtlayınız. "),
        ("Aşağıda {konu} konusuna ait iki kısa alıntı betimlenmiştir. Birinci alıntıda "
         "{kavram} öne çıkarılmakta, ikinci alıntıda ise aynı konu {kavram2} açısından ele "
         "alınmaktadır. İki alıntının yazıldığı dönem aynıdır, ancak ele alınan bakış açısı "
         "farklıdır. Alıntıların hiçbirinde konunun tamamı verilmemiş, yalnızca ilgili bölüm "
         "aktarılmıştır. Aşağıdaki soruyu bu iki alıntıyı karşılaştırarak yanıtlayınız. "),
        ("Aşağıda {konu} konusuna ait bir tablo betimlenmiştir. Tablonun satırlarında "
         "incelenen örnekler, sütunlarında ise {kavram} ve {kavram2} ölçütleri yer "
         "almaktadır. Birinci örnekte {kavram} belirgin, ikinci örnekte ise {kavram2} "
         "baskındır. Üçüncü örnekte iki ölçütün birlikte görüldüğü, dördüncü örnekte "
         "ikisinin de bulunmadığı belirtilmiştir. Tabloda eksik hücre yoktur. "),
        ("Bir öğretmen {konu} konusunu anlatırken sınıfa {n} örnek sunmuştur. Örneklerin bir "
         "bölümünde {kavram} açıkça görülmekte, bir bölümünde ise yalnızca {kavram2} "
         "bulunmaktadır. Öğrenciler örnekleri iki gruba ayırmış, ancak bazı örneklerin her "
         "iki gruba da girebileceğini fark etmiştir. Öğretmen, sınır durumların ayrı bir "
         "ölçütle çözülmesi gerektiğini söylemiştir. Aşağıdaki soru bu sınıflandırmaya "
         "dayanmaktadır. "),
        ("Aşağıdaki metin {konu} konusuyla ilgilidir. Metinde önce {kavram} kavramının tanımı "
         "verilmekte, ardından bu tanımın hangi durumlarda yetersiz kaldığı tartışılmaktadır. "
         "Yazar, tartışmayı {kavram2} üzerinden sürdürmekte ve iki kavramın sınırını çizmeye "
         "çalışmaktadır. Metnin sonunda, verilen ölçütün her örnek için geçerli sayılamayacağı "
         "belirtilmektedir. Soruyu metne göre yanıtlayınız. "),
    ],
}

#: Uzunluk eşiğine ulaşılmazsa eklenen dolgu cümleleri (yine yalnız güvenli
#: değişkenler kullanır).
READING_FILLERS = [
    "Verilen bilgilerin dışında herhangi bir varsayım yapmayınız. ",
    "Ölçüm birimleri metin boyunca değişmemiştir. ",
    "Seçenekleri değerlendirirken yalnızca yukarıdaki bilgileri kullanınız. ",
    "Metinde verilmeyen bir bilgiyi doğru kabul etmeyiniz. ",
    "Aşağıdaki soru yukarıdaki bilgilerin tamamını gerektirmektedir. ",
]


# --------------------------------------------------------------------------
# 4) AÇIK UÇLU (metin) kökler — düzeye göre
# --------------------------------------------------------------------------

TEXT_STEM_BY_LEVEL = {
    "hatirlama": [
        "{konu} konusundaki {kavram} kavramını tanımlayınız.",
        "{konu} konusunda {kavram} nedir? Kısaca yazınız.",
        "{konu} konusundaki {kavram} teriminin karşılığını yazınız.",
        "{konu} konusunda {kavram} ile ilgili bildiğiniz tanımı belirtiniz.",
    ],
    "uygulama": [
        "{konu} konusundaki {kavram} kuralını {n} değeri için uygulayınız ve çözümü yazınız.",
        "{konu} konusunda {kavram} bağıntısını kullanarak bir örnek çözünüz.",
        "{konu} konusundaki {kavram} için bir örnek veriniz ve çözümünü adım adım yazınız.",
        "{konu} konusunda {kavram} kuralını verilen duruma uygulayıp sonucu yazınız.",
    ],
    "analiz": [
        "{konu} konusunda {kavram} ile {kavram2} arasındaki farkı gerekçelendirerek yazınız.",
        "{konu} konusundaki {kavram} için yaptığınız çıkarımı ve dayanağını yazınız.",
        "{konu} konusunda {kavram} ve {kavram2} birlikte değerlendirildiğinde hangi yargının "
        "geçersiz kaldığını tartışınız.",
        "{konu} konusunda {kavram} hakkındaki iki farklı görüşü karşılaştırıp "
        "değerlendiriniz.",
    ],
}


# --------------------------------------------------------------------------
# 5) SENARYO §4.5 — Türkçe kavram yanılgısı havuzu (konu adına göre)
#
# `dikkat_tuzagi = var` olan maddelerde doğru şık ile "çekici çeldirici"
# birbirinin YAPISAL İKİZİ olur: aynı kavram, aynı sözcük kalıbı, fakat kural
# bozulmuş. Rubrikteki ölçüt budur; yalnız sayısal çeldirici yeterli değildir.
#
# Havuz 14 konudan 46 konuya genişletildi. Metinler konunun KENDİ kavram
# havuzundaki sözcükleri kullanır; başka konunun kavramı geçerse `selfcheck`
# konu-kavram denetimi ihlal sayar.
# --------------------------------------------------------------------------

MISCONCEPTIONS = {
    # ---- Matematik ----
    "Üslü ve Köklü İfadeler": ("(a·b)^n = a^n · b^n", "(a+b)^n = a^n + b^n"),
    "Mutlak Değer": ("|x-3| = 5 için kök kümesi {8, -2} olur",
                      "|x-3| = 5 için kök kümesi yalnız {8} olur"),
    "Fonksiyon Kavramı": ("Bileşkede sıra önemlidir: f∘g ≠ g∘f",
                          "Bileşkede sıra önemsizdir: f∘g = g∘f"),
    "İkinci Dereceden Denklemler": ("Diskriminant negatifse gerçel çözüm yoktur",
                                    "Diskriminant negatif olsa da iki gerçel çözüm vardır"),
    "Trigonometri": ("sin²x + cos²x = 1", "sin x + cos x = 1"),
    "Trigonometriye Giriş": ("sin(2x) = 2·sin x·cos x", "sin(2x) = 2·sin x"),
    "Kümeler": ("s(A∪B) = s(A) + s(B) - s(A∩B)", "s(A∪B) = s(A) + s(B)"),
    "Sayı Kümeleri": ("Her tam sayı rasyoneldir, tersi doğru değildir",
                      "Her rasyonel sayı tam sayıdır"),
    "Denklem ve Eşitsizlikler": ("Negatif sayıyla çarpılınca eşitsizliğin yönü değişir",
                                 "Negatif sayıyla çarpılınca eşitsizliğin yönü değişmez"),
    "Denklem ve Eşitsizlik Sistemleri": ("Bir denklemin iki katı alınınca çözüm kümesi değişmez",
                                         "Bir denklemin iki katı alınınca çözüm kümesi ikiye katlanır"),
    "Polinomlar": ("P(x)·Q(x) polinomunun derecesi derecelerin toplamıdır",
                   "P(x)·Q(x) polinomunun derecesi derecelerin çarpımıdır"),
    "Fonksiyonlarla İşlemler": ("(f+g)(x) = f(x) + g(x)", "(f·g)(x) = f(x) + g(x)"),
    "Fonksiyonlarda Uygulamalar": ("f⁻¹ ile 1/f farklı şeylerdir",
                                   "f⁻¹ ile 1/f aynı şeydir"),
    "Olasılık": ("Ayrık olaylarda P(A∪B) = P(A) + P(B)",
                 "Her durumda P(A∪B) = P(A) + P(B)"),
    "Basit Olayların Olasılığı": ("Bağımsız olaylarda P(A∩B) = P(A)·P(B)",
                                  "Her durumda P(A∩B) = P(A)·P(B)"),
    "Sayma ve Olasılık": ("Sıra önemliyse permütasyon, değilse kombinasyon kullanılır",
                          "Sıra önemli olsa da kombinasyon kullanılır"),
    "Kombinasyon": ("C(n,r) = C(n, n-r)", "C(n,r) = C(r, n-r)"),
    "Veri Analizi": ("Aritmetik ortalama uç değerlerden etkilenir",
                     "Aritmetik ortalama uç değerlerden etkilenmez"),
    "İstatistik": ("Ortanca sıralı veride ortadaki değerdir",
                   "Ortanca en çok tekrar eden değerdir"),
    "İstatistik ve Olasılık": ("Standart sapma yayılımı, ortalama merkezi gösterir",
                               "Standart sapma da merkezi gösterir"),
    "Limit": ("Limitin var olması sürekliliği gerektirmez",
              "Limit varsa fonksiyon o noktada mutlaka süreklidir"),
    "Limit Kavramına Giriş": ("Soldan ve sağdan limit eşitse limit vardır",
                              "Soldan limit varsa limit vardır"),
    "Türev": ("Türevin sıfır olması yalnız kritik nokta verir",
              "Türevin sıfır olduğu her nokta yerel ekstremumdur"),
    "Türevin Uygulamaları": ("f″ işaret değiştiriyorsa büküm noktası vardır",
                             "f″ sıfırsa her zaman büküm noktası vardır"),
    "İntegral": ("Belirsiz integrale sabit eklenir",
                 "Belirsiz integralde sabit eklenmez"),
    "Belirli İntegral": ("Belirli integral işaretli değer verir",
                         "Belirli integral her zaman pozitif değer verir"),
    "Diziler": ("Aritmetik dizide ardışık fark sabittir",
                "Aritmetik dizide ardışık oran sabittir"),
    "Diziler ve Seriler": ("Geometrik seride |r| < 1 ise toplam yakınsar",
                           "Geometrik seride her r için toplam yakınsar"),
    "Üstel ve Logaritmik Fonksiyonlar": ("log(a·b) = log a + log b",
                                         "log(a+b) = log a + log b"),
    "Üçgenler": ("Benzerlikte açılar eşit, kenarlar orantılıdır",
                 "Benzerlikte kenarlar da eşittir"),
    "Dörtgenler ve Çokgenler": ("Her kare bir eşkenar dörtgendir, tersi doğru değildir",
                                "Her eşkenar dörtgen bir karedir"),
    "Çember ve Daire": ("Merkez açı, gördüğü çevre açının iki katıdır",
                        "Merkez açı, gördüğü çevre açıya eşittir"),
    "Çemberin Analitik İncelenmesi": ("Denklemdeki r² yarıçapın karesidir",
                                      "Denklemdeki r² yarıçapın kendisidir"),
    "Doğrunun Analitik İncelenmesi": ("Dik doğruların eğimleri çarpımı -1'dir",
                                      "Dik doğruların eğimleri birbirine eşittir"),
    "Analitik Geometri": ("İki nokta arası uzaklıkta farkların karesi alınır",
                          "İki nokta arası uzaklıkta farklar doğrudan toplanır"),
    "Katı Cisimler": ("Hacim uzunluğun küpüyle, yüzey alanı karesiyle ölçeklenir",
                      "Hacim ve yüzey alanı aynı oranda ölçeklenir"),
    "Uzay Geometri": ("Kesit alanı ile taban alanı farklı büyüklüklerdir",
                      "Kesit alanı ile taban alanı her zaman eşittir"),
    "Uzay Geometride Hacim": ("Koninin hacmi silindirin üçte biridir",
                              "Koninin hacmi silindirin yarısıdır"),
    "Geometrik Cisimler": ("Yüzey alanı iki boyutlu, hacim üç boyutlu ölçüdür",
                           "Yüzey alanı ile hacim aynı ölçüdür"),
    "Cebirsel İfadeler": ("Benzer terimler toplanabilir",
                          "Benzer olmayan terimler de toplanabilir"),
    "Denklemler": ("Denklemin iki yanına aynı sayı eklenebilir",
                   "Denklemin yalnız bir yanına sayı eklenebilir"),
    "Fonksiyonlar": ("Bir girdiye tek çıktı düşer",
                     "Bir girdiye birden çok çıktı düşebilir"),
    "Sayılar ve İşlemler": ("İşlem önceliğinde çarpma toplamadan öncedir",
                            "İşlem önceliğinde soldan sağa gidilir, çarpma beklemez"),

    # ---- Fizik ----
    "Newton'ın Hareket Yasaları": ("Etki ve tepki farklı cisimlere etkir",
                                   "Etki ve tepki aynı cisme etkir, dengelenir"),
    "Tork ve Denge": ("Tork, kuvvet ile dik uzaklığın çarpımıdır",
                      "Tork, kuvvet ile uzaklığın çarpımıdır, açı önemsizdir"),
    "Vektörler": ("Bileşke, vektörlerin yönü dikkate alınarak bulunur",
                  "Bileşke, büyüklüklerin doğrudan toplamıdır"),
    "Bağıl Hareket": ("Bağıl hız, hızların vektörel farkıdır",
                      "Bağıl hız, hızların sayısal toplamıdır"),
    "İş Güç Enerji": ("İş, kuvvetin hareket doğrultusundaki bileşeniyle hesaplanır",
                      "İş, kuvvet ile alınan mesafenin doğrudan çarpımıdır"),
    "Enerji": ("Kinetik enerji hızın karesiyle artar",
               "Kinetik enerji hızla doğru orantılı artar"),
    "Enerji Dönüşümleri": ("Sürtünmede mekanik enerji ısıya dönüşür, yok olmaz",
                           "Sürtünmede mekanik enerji yok olur"),
    "Atışlar": ("Yatay atışta düşey hareket ilk hızdan bağımsızdır",
                "Yatay atışta düşey hareket ilk hıza bağlıdır"),
    "Hareket ve Kuvvet": ("Sabit hızlı harekette net kuvvet sıfırdır",
                          "Sabit hızlı harekette net kuvvet sabit ve sıfırdan farklıdır"),
    "Basit Makineler": ("Basit makine işten kazandırmaz, kuvvetten kazandırır",
                        "Basit makine işten de kazandırır"),
    "Isı ve Sıcaklık": ("Isı aktarılan enerji, sıcaklık ise ölçülen düzeydir",
                        "Isı ile sıcaklık aynı büyüklüktür"),
    "Elektrostatik": ("Aynı işaretli yükler birbirini iter",
                      "Aynı işaretli yükler birbirini çeker"),
    "Elektriksel Kuvvet ve Alan": ("Elektriksel kuvvet uzaklığın karesiyle ters orantılıdır",
                                   "Elektriksel kuvvet uzaklıkla ters orantılıdır"),
    "Elektrik Akımı": ("Seri bağlamada akım şiddeti aynı, potansiyel fark bölünür",
                       "Seri bağlamada potansiyel fark aynı, akım şiddeti bölünür"),
    "Manyetizma": ("Manyetik alan hareketli yüke kuvvet uygular",
                   "Manyetik alan duran yüke de kuvvet uygular"),
    "Optik": ("Yansımada geliş açısı yansıma açısına eşittir",
              "Yansımada geliş açısı kırılma açısına eşittir"),
    "Dalgalar": ("Ortam değişince frekans korunur, dalga boyu değişir",
                 "Ortam değişince frekans da değişir"),
    "Modern Fizik": ("Foton enerjisi frekansla doğru orantılıdır",
                     "Foton enerjisi dalga boyuyla doğru orantılıdır"),
    "Madde ve Özellikleri": ("Kütle ayırt edici bir özellik değildir",
                             "Kütle ayırt edici bir özelliktir"),
    "Fizik Bilimine Giriş": ("Temel büyüklükler türetilmiş büyüklüklerden farklıdır",
                             "Bütün büyüklükler temel büyüklüktür"),

    # ---- Kimya ----
    "Atom ve Periyodik Sistem": ("Periyotta soldan sağa atom yarıçapı küçülür",
                                 "Periyotta soldan sağa atom yarıçapı büyür"),
    "Kimyasal Türler Arası Etkileşim": ("Hidrojen bağı bir moleküller arası etkileşimdir",
                                        "Hidrojen bağı bir kovalent bağdır"),
    "Maddenin Halleri": ("Hal değişimi sürerken kaynama noktası sabit kalır",
                         "Hal değişimi sürerken kaynama noktası sürekli yükselir"),
    "Karışımlar": ("Karışımın bileşenleri sabit oranda değildir",
                   "Karışımın bileşenleri sabit orandadır"),
    "Asitler ve Bazlar": ("pH düştükçe asitlik artar",
                          "pH düştükçe asitlik azalır"),
    "Kimyasal Tepkimeler": ("Denkleştirmede katsayılar değiştirilir, alt indisler değişmez",
                            "Denkleştirmede alt indisler de değiştirilebilir"),
    "Gazlar": ("Sabit sıcaklıkta basınç ile hacim ters orantılıdır",
               "Sabit sıcaklıkta basınç ile hacim doğru orantılıdır"),
    "Çözeltiler": ("Seyreltmede molarite azalır, çözünürlük değişmez",
                   "Seyreltmede çözünürlük de azalır"),
    "Kimya ve Enerji": ("Ekzotermik tepkimede entalpi değişimi negatiftir",
                        "Ekzotermik tepkimede entalpi değişimi pozitiftir"),
    "Kimya Bilimi": ("Nitel gözlem ölçüm gerektirmez, nicel gözlem gerektirir",
                     "Nitel gözlem de ölçüm gerektirir"),

    # ---- Biyoloji ----
    "Hücre Bölünmeleri (Mitoz)": ("Mitozda kromozom sayısı korunur",
                                  "Mitozda kromozom sayısı yarıya iner"),
    "Hücre Bölünmeleri": ("Mitoz sonunda iki özdeş hücre oluşur",
                          "Mitoz sonunda dört özdeş hücre oluşur"),
    "Mayoz ve Eşeyli Üreme": ("Mayozda kromozom sayısı yarıya iner",
                              "Mayozda kromozom sayısı korunur"),
    "Kalıtım": ("Çekinik fenotip yalnız aa genotipinde görülür",
                "Aa genotipinde de çekinik fenotip görülür"),
    "Modern Genetik Uygulamaları": ("Gen aktarımı genotipi değiştirir",
                                    "Gen aktarımı yalnız fenotipi değiştirir"),
    "Fotosentez": ("Işıktan bağımsız evre ışığa ihtiyaç duymaz",
                   "Işıktan bağımsız evre yalnız karanlıkta gerçekleşir"),
    "Solunum": ("Oksijenli solunum daha çok enerji açığa çıkarır",
                "Oksijensiz solunum daha çok enerji açığa çıkarır"),
    "Canlılar ve Enerji": ("Üreticiler enerjiyi kendileri üretir",
                           "Üreticiler enerjiyi tüketicilerden alır"),
    "Ekosistem Ekolojisi": ("Enerji piramitte yukarı çıkıldıkça azalır",
                            "Enerji piramitte yukarı çıkıldıkça artar"),
    "Madde Döngüleri": ("Madde döngüde yeniden kullanılır",
                        "Madde döngüde tükenir ve yeniden kullanılamaz"),
    "Bitki Biyolojisi": ("Terleme su taşınmasına katkı sağlar",
                         "Terleme su taşınmasını engeller"),
    "Hücre": ("Zar seçici geçirgendir",
              "Zar bütün maddeleri geçirir"),
    "Canlılar Dünyası": ("Sınıflandırmada tür en küçük birimdir",
                         "Sınıflandırmada tür en büyük birimdir"),
    "Yaşam Bilimi Biyoloji": ("Denetimli deneyde tek değişken değiştirilir",
                              "Denetimli deneyde bütün değişkenler birlikte değiştirilir"),
    "Sistemler": ("Sistemler birbirinden bağımsız çalışmaz",
                  "Sistemler birbirinden bağımsız çalışır"),

    # ---- Sözel dersler ----
    "Yazım Kuralları ve Noktalama": ("\"ve\" bağlacından önce virgül konmaz",
                                     "Her bağlaçtan önce virgül konur"),
    "Şiir": ("Redif ile kafiye farklı kavramlardır",
             "Redif ile kafiye aynı şeydir"),
    "Present Perfect": ("since + zaman noktası kullanılır",
                        "since + süre kullanılır"),
    "Türkiye'de Sanayi": ("Sanayinin en çok yoğunlaştığı bölge Marmara'dır",
                          "Sanayinin en çok yoğunlaştığı bölge İç Anadolu'dur"),
}


# --------------------------------------------------------------------------
# 6) Konu tablosunda karşılığı olmayan maddeler için GENEL tuzak kalıpları.
#    Kalıplar konunun KENDİ kavram havuzunu kullanır ({kavram}); böylece
#    konu-kavram denetimi ihlal edilmez ve metin her maddede farklılaşır.
# --------------------------------------------------------------------------

#: (doğru şık kalıbı, tuzak şık kalıbı) — ifade tipi şıklar için.
GENERIC_TRAPS_IFADE = [
    ("{kavram} artarsa {kavram2} da artar, ancak oran sabit kalmaz",
     "{kavram} artarsa {kavram2} da artar, oran her zaman sabit kalır"),
    ("{kavram} ile {kavram2} arasındaki ilişki koşula bağlıdır",
     "{kavram} ile {kavram2} arasındaki ilişki her koşulda aynıdır"),
    ("{kavram} tek başına belirleyici değildir",
     "{kavram} tek başına belirleyicidir"),
    ("{kavram} değişirken {kavram2} korunabilir",
     "{kavram} değişirse {kavram2} de mutlaka değişir"),
    ("{kavram} için verilen kural yalnız tanım aralığında geçerlidir",
     "{kavram} için verilen kural her aralıkta geçerlidir"),
    ("{kavram} ile {kavram2} birbirinin yerine kullanılamaz",
     "{kavram} ile {kavram2} birbirinin yerine kullanılabilir"),
    ("{kavram} değeri sıfır olabilir ama tanımsız olamaz",
     "{kavram} değeri sıfırsa tanımsızdır"),
    ("{kavram} artışı {kavram2} üzerinde gecikmeli görülür",
     "{kavram} artışı {kavram2} üzerinde anında görülür"),
    ("{kavram} ölçümü {kavram2} ölçümünden bağımsız yapılır",
     "{kavram} ölçümü {kavram2} ölçümünü de doğrudan verir"),
    ("{kavram} için tersi her zaman doğru değildir",
     "{kavram} için tersi de her zaman doğrudur"),
]

#: Sayısal köklerde tuzak: BİRİM ya da İŞARET hatası — sözel olarak
#: adlandırılmış hâliyle yazılır ki rubrik ölçütü karşılansın.
GENERIC_TRAPS_SAYISAL = [
    ("{n} {birim}", "{n} {birim} (birim çevrilmeden bırakıldı)"),
    ("{n} {birim}", "-{n} {birim} (işaret değişimi göz ardı edildi)"),
    ("{n},{r} {birim}", "{n} {birim} (ondalık kısım atıldı)"),
    ("{n} {birim}", "{m} {birim} (ara sonuç nihai sonuç sanıldı)"),
    ("{n}/{m} {birim}", "{m}/{n} {birim} (oran ters çevrildi)"),
    ("{n} {birim}", "{d} {birim} (iki katı alınarak hesaplandı)"),
]


def _trap_texts(rng, area, subject_name, choice_kind, pool):
    """Bir maddenin (doğru şık, tuzak şık) ikilisini üretir.

    Konuya özgü yanılgı varsa o kullanılır (yapısal ikiz, §4.5); yoksa genel
    kalıplardan biri konunun kendi kavramlarıyla doldurulur.
    """
    pair = MISCONCEPTIONS.get(subject_name)
    if pair is not None:
        return pair[0], pair[1]
    if choice_kind == "sayisal":
        tpl = GENERIC_TRAPS_SAYISAL[rng.randrange(len(GENERIC_TRAPS_SAYISAL))]
    else:
        tpl = GENERIC_TRAPS_IFADE[rng.randrange(len(GENERIC_TRAPS_IFADE))]
    # İki kalıp AYNI değişken değerleriyle doldurulmalı ki yapısal ikiz olsunlar.
    joined = _fill(rng, tpl[0] + "\x00" + tpl[1], area, subject_name, pool)
    right, wrong = joined.split("\x00", 1)
    return right, wrong


def apply_trap(rng, texts, area, subject_name, choice_kind, correct_index,
               misc_index, pool):
    """`dikkat_tuzagi = var` maddelerinde doğru şık ve tuzak şıkkı yerleştirir."""
    if correct_index == misc_index or len(texts) <= max(correct_index, misc_index):
        return texts
    right, wrong = _trap_texts(rng, area, subject_name, choice_kind, pool)
    out = list(texts)
    out[correct_index] = right
    out[misc_index] = wrong
    # Kalan şıklar tuzakla çakışmasın (aynı sorunun iki şıkkı aynı olamaz).
    seen = {right, wrong}
    for i, txt in enumerate(out):
        if i in (correct_index, misc_index):
            continue
        guard = 0
        while txt in seen and guard < 40:
            txt = _fill(rng, _choice_templates(area, choice_kind)[
                rng.randrange(len(_choice_templates(area, choice_kind)))],
                area, subject_name, pool)
            guard += 1
        out[i] = txt
        seen.add(txt)
    return out


# Geriye dönük ad: eski çağrı yeri kalmadı, ancak dış araçlar bu adı arıyor.
def apply_misconception(texts, subject_name, correct_index, misc_index):
    """ESKİ API — konuya özgü yanılgı çiftini doğrudan yerleştirir."""
    pair = MISCONCEPTIONS.get(subject_name)
    if not pair or correct_index == misc_index:
        return texts
    out = list(texts)
    if len(out) > max(correct_index, misc_index):
        out[correct_index] = pair[0]
        out[misc_index] = pair[1]
    return out


# --------------------------------------------------------------------------
# 7) Etiketlerden metin üreten asıl işlevler
# --------------------------------------------------------------------------

def _pick_level_stem(rng, area, level, multi_step):
    """Düzeye (ve çok adımlılığa) uygun kök şablonu seçer."""
    if multi_step and level != "hatirlama":
        pool = MULTISTEP_STEM_TEMPLATES[_group(area)][level]
        return pool[rng.randrange(len(pool))]
    pool = LEVEL_STEM_TEMPLATES[area][level]
    return pool[rng.randrange(len(pool))]


def _with_reading_context(rng, stem, area, subject_name, pool):
    """Kökün önüne 3-6 cümlelik bağlam (paragraf / tablo / grafik) ekler."""
    contexts = READING_CONTEXTS[_group(area)]
    head = _fill(rng, contexts[rng.randrange(len(contexts))], area, subject_name, pool)
    out = head + stem
    guard = 0
    while len(out) < READING_HIGH_MIN_CHARS and guard < len(READING_FILLERS):
        out = head + READING_FILLERS[guard] + stem
        head = head + READING_FILLERS[guard]
        guard += 1
    return out


def make_labeled_question(rng, area, subject_name, k, dims, correct_index,
                          misc_index, avoid=None):
    """Etiketlerden bir çoktan seçmeli soru üretir: (kök, şık metinleri).

    `dims` dört boyutun etiketini taşır (rubric.py ile birebir aynı adlar).
    Metin etiketleri GÖRÜNÜR kılar: düzeye özgü kök kalıbı, çok adımlıda
    "önce … sonra …" zinciri, yüksek okuma yükünde paragraf/tablo/grafik
    bağlamı, tuzaklı maddede doğru şıkkın yapısal ikizi olan bir çeldirici.
    """
    area = _area(area)
    pool = concept_pool(area, subject_name)
    level = dims["bilissel_talep"]
    multi = dims["adim_sayisi"] == "cok_adim"
    heavy = dims["okuma_yuku"] == "yuksek"
    trap = dims["dikkat_tuzagi"] == "var"

    def _make():
        template, choice_kind = _pick_level_stem(rng, area, level, multi)
        stem = _fill(rng, template, area, subject_name, pool)
        if heavy:
            stem = _with_reading_context(rng, stem, area, subject_name, pool)
        return stem, choice_kind

    stem, choice_kind = _unique_stem(rng, area, subject_name, pool, _make, avoid)
    texts = make_choices(rng, area, subject_name, k, choice_kind)
    if trap:
        texts = apply_trap(rng, texts, area, subject_name, choice_kind,
                           correct_index, misc_index, pool)
    return stem, texts


def make_labeled_stem(rng, area, subject_name, dims, avoid=None):
    """Açık uçlu (metin) soru kökü — bilişsel düzey ve okuma yükü uygulanır."""
    area = _area(area)
    pool = concept_pool(area, subject_name)
    level = dims["bilissel_talep"]
    heavy = dims["okuma_yuku"] == "yuksek"

    def _make():
        templates = TEXT_STEM_BY_LEVEL[level]
        stem = _fill(rng, templates[rng.randrange(len(templates))],
                     area, subject_name, pool)
        if heavy:
            stem = _with_reading_context(rng, stem, area, subject_name, pool)
        return stem, "ifade"

    stem, _kind = _unique_stem(rng, area, subject_name, pool, _make, avoid)
    return stem


# Tutarlılık denetimi: her ders için üç bilişsel düzeyin de şablonu olmalı.
for _area_name, _levels in LEVEL_STEM_TEMPLATES.items():
    assert tuple(_levels) == DIMENSION_LABELS["bilissel_talep"], _area_name
    assert all(_levels[_lv] for _lv in _levels), _area_name
assert set(LEVEL_STEM_TEMPLATES) >= set(STEM_TEMPLATES), \
    "Her ders için düzeye göre kök şablonu tanımlı olmalı."
