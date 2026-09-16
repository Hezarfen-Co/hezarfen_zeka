"""Sabitler, ölçek profilleri, takvim ve Türkçe içerik havuzları.

Buradaki her sayı SENARYO.md'den gelir; sihirli sayı başka dosyada bulunmaz.
Zaman değerleri unix-ms (UTC) cinsindendir; yerel saat Europe/Istanbul = UTC+3
(yaz saati uygulaması yok).
"""

from __future__ import annotations

import datetime as _dt

# --------------------------------------------------------------------------
# Genel
# --------------------------------------------------------------------------

SEED_DEFAULT = 20260413

SCHOOL_SLUG = "ataturk-anadolu"
SCHOOL_NAME = "Özel Hezarfen Anadolu Lisesi"

TZ_OFFSET_MS = 3 * 3600 * 1000  # Europe/Istanbul, DST yok
DAY_MS = 86_400_000
MIN_MS = 60_000
HOUR_MS = 3_600_000

# 1970-01-01 = 719163 (chrono NaiveDate::num_days_from_ce, domain/timestamp.rs:145)
DAY_NUMBER_EPOCH = 719_163

# T_NOW = 2026-04-13T08:00:00+03:00
T_NOW_MS = 1_776_056_400_000

# Parola (PAROLA.md)
PASSWORD_PLAIN = "Hezarfen2026!"
ARGON2_TIME_COST = 2
ARGON2_MEMORY_COST = 19_456
ARGON2_PARALLELISM = 1
ARGON2_HASH_LEN = 32

# Toplu INSERT başına kayıt sayısı (dosya boyutu / yükleme süresi dengesi)
BATCH_SIZE = 800

# --------------------------------------------------------------------------
# Takvim (SENARYO §2.1)
# --------------------------------------------------------------------------

T1_START = _dt.date(2025, 9, 8)
T1_END = _dt.date(2026, 1, 16)
T2_START = _dt.date(2026, 2, 2)
T2_END = _dt.date(2026, 6, 19)

# Tatil haftaları (Pazartesi-Cuma, kapalı)
BREAKS = [
    (_dt.date(2025, 11, 10), _dt.date(2025, 11, 14)),   # Kasım ara tatili
    (_dt.date(2026, 1, 19), _dt.date(2026, 1, 30)),     # Yarıyıl tatili (2 hafta)
    (_dt.date(2026, 4, 6), _dt.date(2026, 4, 10)),      # Nisan ara tatili
]

# Okulun kapalı olduğu tek günler
HOLIDAYS = [
    _dt.date(2025, 10, 29),   # Cumhuriyet Bayramı
    _dt.date(2026, 1, 1),     # Yılbaşı
    _dt.date(2026, 3, 20),    # Ramazan Bayramı (okul 1 gün kapalı)
]

# Gelecek resmi tatiller (üretim penceresinde ders yok)
FUTURE_HOLIDAYS = [
    _dt.date(2026, 4, 23),
    _dt.date(2026, 5, 1),
    _dt.date(2026, 5, 19),
    _dt.date(2026, 5, 26), _dt.date(2026, 5, 27),
    _dt.date(2026, 5, 28), _dt.date(2026, 5, 29),
]

FLU_WEEK = (_dt.date(2025, 12, 15), _dt.date(2025, 12, 19))

# Ders blokları — yerel saat, dakika cinsinden gün başlangıcından itibaren
BLOCK_MINUTES = [520, 580, 640, 700, 800, 860]  # 08:40 09:40 10:40 11:40 13:20 14:20
BLOCK_LENGTH_MIN = 40

# --------------------------------------------------------------------------
# Okul yapısı (SENARYO §1.1)
# --------------------------------------------------------------------------

# (şube adı, grade alanı, tam ölçekte öğrenci sayısı)
BRANCHES = [
    ("9-A", "9", 24),
    ("9-B", "9", 23),
    ("9-C", "9", 23),
    ("10-A", "10", 23),
    ("10-B", "10", 23),
    ("10-C", "10", 22),
    ("11-A", "11", 22),
    ("11-B", "11", 22),
    ("11-C", "11", 21),
    ("12-A", "12", 24),
    ("12-B", "12", 23),
]
# Kenar durum #10: 12-A'nın grade değeri kasten tutarsız yazılır.
INCONSISTENT_GRADE_BRANCH = "12-A"
INCONSISTENT_GRADE_VALUE = "12. Sınıf"

GRADES = ["9", "10", "11", "12"]

# --------------------------------------------------------------------------
# Ders kataloğu (SENARYO §1.4)
# --------------------------------------------------------------------------

# (ders adı, branş kodu, haftalık blok, konu sayısı, zorluk kayması b_i'ye eklenir)
CORE_SUBJECTS = [
    ("Matematik", "mat", 3, 10, 0.18),
    ("Türk Dili ve Edebiyatı", "edb", 2, 10, 0.0),
    ("Fizik", "fiz", 1, 10, 0.18),
    ("Kimya", "kim", 1, 10, 0.10),
    ("Biyoloji", "biy", 1, 10, 0.0),
    ("Tarih", "tar", 1, 10, 0.0),
    ("Coğrafya", "cog", 1, 10, 0.0),
    ("İngilizce", "ing", 2, 10, -0.12),
    ("Din Kültürü ve Ahlak Bilgisi", "din", 1, 5, -0.45),
    ("Beden Eğitimi ve Spor", "bed", 1, 5, -0.45),
]
GRADE_PREFIX = {"9": "9. Sınıf ", "10": "10. Sınıf ", "11": "11. Sınıf ", "12": "12. Sınıf "}
# 12. sınıfta Tarih dersinin adı değişir
GRADE12_TITLE_OVERRIDE = {"tar": "T.C. İnkılap Tarihi ve Atatürkçülük"}

# Branş başına öğretmen sayısı (SENARYO §1.5) — toplam 24 (23 branş + 1 rehber)
TEACHERS_PER_AREA = {
    "mat": 4, "edb": 3, "fiz": 2, "kim": 2, "biy": 2,
    "tar": 2, "cog": 2, "ing": 3, "din": 1, "bed": 2,
}
GUIDANCE_TEACHERS = 1  # rehber öğretmen, dersi yok

# Ek dersler: (başlık, kind, kayıtlı öğrenci, konu sayısı)
EXTRA_COURSES = [
    ("TYT Matematik Etüdü", "study", 32, 3),
    ("AYT Fizik Etüdü", "study", 28, 3),
    ("İngilizce Konuşma Etüdü", "study", 30, 3),
    ("Edebiyat Etüdü", "study", 30, 3),
    ("Satranç Kulübü", "club", 18, 3),
    ("Robotik Kulübü", "club", 22, 3),
    ("Münazara Kulübü", "club", 16, 3),
    ("Fotoğrafçılık Kulübü", "club", 20, 3),
    ("Tiyatro Kulübü", "club", 24, 3),
    ("Bilim Kulübü", "club", 18, 3),
]

CO_TAUGHT_COURSES = 6      # kenar durum #19: teachers dizisi 2 elemanlı
TEACHER_SWAP_COURSES = 2   # kenar durum #17: dönem ortası öğretmen değişimi
TEACHER_SWAP_DATE = _dt.date(2026, 2, 9)

# --------------------------------------------------------------------------
# Konu (subject) adları — §1.4'teki desende
# --------------------------------------------------------------------------

SUBJECT_NAMES = {
    ("9", "mat"): ["Kümeler", "Denklem ve Eşitsizlikler", "Üslü ve Köklü İfadeler",
                   "Mutlak Değer", "Sayı Kümeleri", "Üçgenler", "Veri Analizi",
                   "Fonksiyon Kavramı", "Olasılık", "Doğrunun Analitik İncelenmesi"],
    ("10", "mat"): ["Sayma ve Olasılık", "Fonksiyonlarla İşlemler", "Polinomlar",
                    "İkinci Dereceden Denklemler", "Dörtgenler ve Çokgenler",
                    "Çemberin Analitik İncelenmesi", "Katı Cisimler", "Veri Analizi",
                    "Basit Olayların Olasılığı", "Trigonometriye Giriş"],
    ("11", "mat"): ["Trigonometri", "Analitik Geometri", "Fonksiyonlarda Uygulamalar",
                    "Denklem ve Eşitsizlik Sistemleri", "Çember ve Daire", "Uzay Geometri",
                    "Olasılık", "Diziler", "Limit Kavramına Giriş", "İstatistik"],
    ("12", "mat"): ["Üstel ve Logaritmik Fonksiyonlar", "Diziler ve Seriler", "Limit",
                    "Türev", "Türevin Uygulamaları", "İntegral", "Belirli İntegral",
                    "Analitik Geometri", "Uzay Geometride Hacim", "İstatistik ve Olasılık"],
    ("11", "fiz"): ["Vektörler", "Bağıl Hareket", "Newton'ın Hareket Yasaları",
                    "Tork ve Denge", "Basit Makineler", "İş Güç Enerji", "Atışlar",
                    "Enerji Dönüşümleri", "Elektriksel Kuvvet ve Alan", "Manyetizma"],
    ("10", "biy"): ["Hücre Bölünmeleri (Mitoz)", "Mayoz ve Eşeyli Üreme", "Kalıtım",
                    "Modern Genetik Uygulamaları", "Ekosistem Ekolojisi", "Madde Döngüleri",
                    "Bitki Biyolojisi", "Canlılar ve Enerji", "Fotosentez", "Solunum"],
    ("9", "edb"): ["Giriş (Edebiyatın Tanımı)", "Hikâye", "Şiir", "Masal/Fabl", "Roman",
                   "Tiyatro", "Biyografi ve Otobiyografi", "Mektup/E-posta", "Günlük",
                   "Yazım Kuralları ve Noktalama"],
    ("12", "cog"): ["Ekonomik Faaliyetler", "Türkiye'de Tarım", "Türkiye'de Sanayi",
                    "Ulaşım Sistemleri", "Türkiye'nin İşlevsel Bölgeleri", "Küresel Ticaret",
                    "Doğal Kaynak Yönetimi", "Çevre Sorunları", "Bölgesel Kalkınma Projeleri",
                    "Jeopolitik Konum"],
}

# Listelenmeyen (seviye, branş) çiftleri için desen havuzu
SUBJECT_FALLBACK = {
    "mat": ["Sayılar ve İşlemler", "Cebirsel İfadeler", "Denklemler", "Fonksiyonlar",
            "Geometrik Cisimler", "Analitik Geometri", "Olasılık", "İstatistik",
            "Diziler", "Trigonometri"],
    "edb": ["Giriş", "Şiir", "Hikâye", "Roman", "Tiyatro", "Deneme", "Makale",
            "Anı ve Gezi Yazısı", "Söylev", "Yazım ve Noktalama"],
    "fiz": ["Fizik Bilimine Giriş", "Madde ve Özellikleri", "Hareket ve Kuvvet",
            "Enerji", "Isı ve Sıcaklık", "Elektrostatik", "Elektrik Akımı",
            "Optik", "Dalgalar", "Modern Fizik"],
    "kim": ["Kimya Bilimi", "Atom ve Periyodik Sistem", "Kimyasal Türler Arası Etkileşim",
            "Maddenin Halleri", "Karışımlar", "Asitler ve Bazlar", "Kimyasal Tepkimeler",
            "Gazlar", "Çözeltiler", "Kimya ve Enerji"],
    "biy": ["Yaşam Bilimi Biyoloji", "Hücre", "Canlılar Dünyası", "Hücre Bölünmeleri",
            "Kalıtım", "Ekosistem Ekolojisi", "Bitki Biyolojisi", "Sistemler",
            "Fotosentez", "Solunum"],
    "tar": ["Tarih ve Zaman", "İlk Uygarlıklar", "İlk Türk Devletleri",
            "İslam Medeniyeti", "Selçuklular", "Osmanlı Kuruluş", "Osmanlı Yükselme",
            "Değişim Çağı", "Devrimler Çağı", "Yakın Dönem"],
    "cog": ["Doğa ve İnsan", "Harita Bilgisi", "İklim Bilgisi", "Yer Şekilleri",
            "Nüfus", "Göç", "Yerleşme", "Ekonomik Faaliyetler", "Doğal Afetler",
            "Çevre ve Toplum"],
    "ing": ["Studying Abroad", "My Environment", "Movies", "Human in Nature",
            "Inspirational People", "Technology", "Sports", "Travel",
            "Present Perfect", "Reported Speech"],
    "din": ["Bilgi ve İnanç", "Din ve İslam", "İslam ve İbadet", "Ahlak ve Değerler",
            "Gençlik ve Din"],
    "bed": ["Hareket Yetkinliği", "Aktif ve Sağlıklı Hayat", "Takım Sporları",
            "Bireysel Sporlar", "Spor Kültürü"],
}

EXTRA_SUBJECT_NAMES = ["Temel Kavramlar", "Uygulama ve Problem Çözme", "Genel Tekrar"]

SUBJECT_DESCRIPTION_FILL = 0.78  # %78 dolu, kalanı boş string

# --------------------------------------------------------------------------
# Türkçe isim havuzu (SENARYO §1.3)
# --------------------------------------------------------------------------

MALE_NAMES = ["Ahmet", "Mehmet", "Mustafa", "Ali", "Hüseyin", "Hasan", "İbrahim", "Osman",
              "Yusuf", "Murat", "Emre", "Burak", "Kerem", "Eymen", "Çınar", "Arda",
              "Deniz", "Efe", "Kaan", "Mert", "Poyraz", "Alp", "Ömer", "Halil",
              "Ramazan", "Selim", "Barış", "Onur", "Serkan", "Tolga", "Umut", "Volkan",
              "Yiğit", "Berk", "Cem", "Doruk", "Ege", "Furkan", "Görkem", "Levent"]

FEMALE_NAMES = ["Ayşe", "Fatma", "Emine", "Hatice", "Zeynep", "Elif", "Meryem", "Şerife",
                "Zehra", "Sultan", "Hanife", "Merve", "Esra", "Büşra", "Rabia", "Aleyna",
                "Nisanur", "Ecrin", "Defne", "Azra", "Asya", "Duru", "İrem", "Selin",
                "Ceren", "Damla", "Ebru", "Gamze", "Hande", "Işıl", "Jale", "Kübra",
                "Lale", "Melis", "Nehir", "Özge", "Pınar", "Seda", "Tuğçe", "Yasemin"]

SURNAMES = ["Yılmaz", "Kaya", "Demir", "Şahin", "Çelik", "Yıldız", "Yıldırım", "Öztürk",
            "Aydın", "Özdemir", "Arslan", "Doğan", "Kılıç", "Aslan", "Çetin", "Kara",
            "Koç", "Kurt", "Özkan", "Şimşek", "Polat", "Korkmaz", "Çakır", "Erdoğan",
            "Güneş", "Aksoy", "Bulut", "Turan", "Avcı", "Bozkurt", "Kaplan", "Tekin",
            "Sarı", "Duman", "Ateş", "Taş", "Güler", "Uçar", "Keskin", "Yalçın",
            "Balcı", "Ergin", "Soydan", "Karaca", "Aktaş", "Başaran", "Çakmak",
            "Demirci", "Erdem", "Sezer"]

TR_ASCII = str.maketrans({
    "ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g", "ı": "i", "I": "i", "İ": "i",
    "ö": "o", "Ö": "o", "ş": "s", "Ş": "s", "ü": "u", "Ü": "u", "â": "a", "î": "i",
})

# Profil doluluk oranları (SENARYO §1.3)
PROFILE_FILL = {
    "email": 0.86, "phone": 0.71, "birth_date": 0.63, "display_name": 0.28,
    "bio": 0.19, "avatar_file": 0.34, "palette_color": 0.41, "theme": 0.52,
    "language": 0.96,
}
THEME_LIGHT_SHARE = 0.58

# --------------------------------------------------------------------------
# Roller ve sayılar (tam ölçek; küçük ölçekte oranla küçülür)
# --------------------------------------------------------------------------

N_STUDENTS_FULL = 250
N_PARENTS_FULL = 285
N_MANAGERS = 3
N_ADMIN = 1

# parent_link üretim kuralı (SENARYO §1.2)
PARENT_SIBLING_COUNT = 12       # 2 öğrenciye bağlı veli
PARENT_NO_PARENT_STUDENTS = 20  # velisi olmayan öğrenci
PARENT_EXTRA_GUARDIAN = 2       # ikinci veli (vasi) eklenen öğrenci

# --------------------------------------------------------------------------
# Arketipler (SENARYO §3)
# --------------------------------------------------------------------------

ARCHETYPES = {
    "A1": dict(
        share=0.120, theta=(1.25, 0.30), clip=(0.55, 2.10), trend=0.0,
        d_course=0.22, d_subject=0.18,
        absence=0.030, absent_share=0.42, late=0.021,
        hw_submit=0.99, on_time=0.97,
        hw_weights=(0.10, 0.30, 0.58, 0.02),
        pomo_days=5.2, pomo_lambda=3.1, pomo_median=27.0, pomo_sigma=0.38, pomo_night=0.14,
        chat_user=0.63, chat_msgs_month=4,
        appointments=0.8, pool_ask=0.4, pool_solve=2.1,
        omega=0.25, exam_participation=0.99, board_strokes_week=6.0, badges=(6, 9),
    ),
    "A2": dict(
        share=0.280, theta=(0.05, 0.35), clip=(-0.70, 0.85), trend=0.0,
        d_course=0.30, d_subject=0.26,
        absence=0.080, absent_share=0.78, late=0.055,
        hw_submit=0.88, on_time=0.79,
        hw_weights=(0.46, 0.27, 0.15, 0.12),
        pomo_days=2.4, pomo_lambda=2.2, pomo_median=22.0, pomo_sigma=0.45, pomo_night=0.28,
        chat_user=0.58, chat_msgs_month=3,
        appointments=0.4, pool_ask=1.1, pool_solve=0.7,
        omega=0.55, exam_participation=0.95, board_strokes_week=3.0, badges=(3, 5),
    ),
    "A3": dict(
        share=0.140, theta=(0.45, 0.30), clip=(-0.15, 1.20), trend=0.0,
        d_course=0.24, d_subject=0.24,
        absence=0.070, absent_share=0.75, late=0.048,
        hw_submit=0.90, on_time=0.85,
        hw_weights=(0.48, 0.26, 0.13, 0.13),
        pomo_days=2.8, pomo_lambda=2.4, pomo_median=24.0, pomo_sigma=0.42, pomo_night=0.30,
        chat_user=0.60, chat_msgs_month=3,
        appointments=1.2, pool_ask=2.3, pool_solve=0.5,
        omega=0.60, exam_participation=0.94, board_strokes_week=3.0, badges=(3, 6),
        # SENARYO 3.6 -1.60 / -0.90 verir; madde-ici gurultu ve bos birakma
        # secilimi farki daraltiyor, 7.3 A6 olcutu (>=30 puan) icin derinlestirildi.
        gap_delta=-2.40, gap_subject_delta=-1.40, gap_omega=1.15,
        gap_hw_submit=0.71, gap_participation=0.88, other_course_mu=0.10,
    ),
    "A4": dict(
        share=0.128, theta=(-0.10, 0.40), clip=(-1.00, 0.70), trend=-0.10,
        d_course=0.32, d_subject=0.28,
        absence=0.110, absent_share=0.84, late=0.124,
        hw_submit=0.82, on_time=0.48,
        hw_weights=(0.52, 0.10, 0.01, 0.37),
        pomo_days=2.1, pomo_lambda=2.0, pomo_median=41.0, pomo_sigma=0.55, pomo_night=0.47,
        chat_user=0.66, chat_msgs_month=5,
        appointments=0.6, pool_ask=1.0, pool_solve=0.3,
        omega=0.75, exam_participation=0.91, board_strokes_week=2.0, badges=(2, 4),
        monday_absence_mult=1.8, exam_rush=1.8,
    ),
    "A5": dict(
        share=0.100, theta=(-0.70, 0.25), clip=(-1.60, 1.60), trend=1.50,
        d_course=0.28, d_subject=0.24,
        absence=0.095, absent_share=0.72, late=0.050,
        hw_submit=0.825, on_time=0.72,
        hw_weights=(0.44, 0.30, 0.14, 0.12),
        pomo_days=2.6, pomo_lambda=2.2, pomo_median=25.0, pomo_sigma=0.44, pomo_night=0.24,
        chat_user=0.72, chat_msgs_month=4,
        appointments=2.1, pool_ask=1.6, pool_solve=0.6,
        omega=0.55, exam_participation=0.935, board_strokes_week=3.0, badges=(3, 6),
rising=True, rise_base=-1.85, rise_slope=2.75,
    ),
    "A6": dict(
        share=0.088, theta=(0.55, 0.28), clip=(-1.60, 1.40), trend=0.0,
        d_course=0.28, d_subject=0.26,
        absence=0.060, absent_share=0.70, late=0.040,
        hw_submit=0.92, on_time=0.85,
        hw_weights=(0.44, 0.30, 0.14, 0.12),
        pomo_days=3.4, pomo_lambda=2.4, pomo_median=24.0, pomo_sigma=0.44, pomo_night=0.26,
        chat_user=0.70, chat_msgs_month=4,
        appointments=0.5, pool_ask=1.4, pool_solve=0.6,
        omega=0.50, exam_participation=0.97, board_strokes_week=4.0, badges=(2, 5),
        breaking=True, break_drop=-2.20, break_ramp_days=10,
        post_absence=0.27, post_absent_share=0.88, post_late=0.14,
        post_hw_submit=0.48, post_on_time=0.31,
        post_hw_weights=(0.36, 0.12, 0.02, 0.50),
        post_pomo_days=0.25, post_omega=0.85, post_participation=0.74,
        post_board_strokes_week=0.5,
    ),
    "A7": dict(
        share=0.072, theta=(-0.75, 0.35), clip=(-1.80, -0.05), trend=-0.15,
        d_course=0.34, d_subject=0.30,
        absence=0.310, absent_share=0.86, late=0.098,
        hw_submit=0.52, on_time=0.29,
        hw_weights=(0.40, 0.12, 0.02, 0.46),
        pomo_days=0.15, pomo_lambda=1.4, pomo_median=18.0, pomo_sigma=0.50, pomo_night=0.35,
        chat_user=0.167, chat_msgs_month=1,
        appointments=0.1, pool_ask=0.05, pool_solve=0.0,
        omega=1.10, exam_participation=0.78, board_strokes_week=0.4, badges=(0, 2),
        monday_absence_mult=1.55, friday_absence_mult=1.50,
    ),
    "A8": dict(
        share=0.072, theta=(-0.25, 0.30), clip=(-0.95, 0.45), trend=0.20,
        d_course=0.28, d_subject=0.25,
        absence=0.090, absent_share=0.72, late=0.050,
        hw_submit=0.91, on_time=0.81,
        hw_weights=(0.44, 0.31, 0.14, 0.11),
        pomo_days=3.1, pomo_lambda=2.6, pomo_median=19.0, pomo_sigma=0.50, pomo_night=0.34,
        chat_user=1.0, chat_msgs_month=22,
        appointments=4.2, pool_ask=7.5, pool_solve=0.4,
        omega=0.60, exam_participation=0.96, board_strokes_week=3.0, badges=(4, 6),
        help_seeker=True,
    ),
}

# Tam ölçekte arketip başına öğrenci sayısı (toplam 250)
ARCHETYPE_COUNTS_FULL = {
    "A1": 30, "A2": 70, "A3": 35, "A4": 32, "A5": 25, "A6": 22, "A7": 18, "A8": 18,
}

# A6 kırılma tarihleri
A6_BREAK_DATES = [_dt.date(2026, 2, 9), _dt.date(2026, 2, 16),
                  _dt.date(2026, 2, 23), _dt.date(2026, 3, 2)]

# A3 boşluk dersi dağılımı (branş kodu -> pay)
A3_GAP_COURSE_WEIGHTS = [("mat", 0.34), ("fiz", 0.20), ("kim", 0.14),
                         ("biy", 0.11), ("ing", 0.11), ("edb", 0.10)]

# Bilinçli yoğunlaşmalar (SENARYO §3.1)
ARCHETYPE_CLUSTERS = {"9-B": ("A6", 5), "11-C": ("A7", 6)}

# --------------------------------------------------------------------------
# Yoklama çarpanları (SENARYO §5.1)
# --------------------------------------------------------------------------

ABSENCE_DAY_MULT = {0: 1.35, 1: 0.90, 2: 0.85, 3: 0.95, 4: 1.30}  # Pzt..Cum
ABSENCE_EXAM_DAY_MULT = 0.55
ABSENCE_BEFORE_BREAK_MULT = 1.60
ABSENCE_AFTER_BREAK_MULT = 1.45
ABSENCE_FLU_MULT = 2.40
LATE_MONDAY_MULT = 1.8
LATE_FIRST_BLOCK_MULT = 2.2
# Gun/blok carpanlari uygulandiktan sonra okul geneli 'late' payini D3'teki
# %4,6 hedefine oturtan olcek.
LATE_SCALE = 0.70

def season_mult(month: int) -> float:
    """M_mevsim — Aralık-Şubat 1,20 · Eylül-Kasım 0,95 · Mart-Nisan 1,05."""
    if month in (12, 1, 2):
        return 1.20
    if month in (9, 10, 11):
        return 0.95
    return 1.05

SESSION_HELD_COUNTED_SHARE = 0.96   # held_counted_at dolu oranı
SESSION_ATTENDANCE_SHARE = 0.902    # yoklama girilmiş oturum oranı
EXTRA_COURSE_ATTENDANCE_SHARE = 0.78

# --------------------------------------------------------------------------
# Sınav takvimi (SENARYO §2.5)
# --------------------------------------------------------------------------

# (dönem, pencere_başı, pencere_sonu, kind, mode, soru, duration_ms, max_attempts,
#  allow_review, text_oranı)
EXAM_PLAN = [
    ("T1", _dt.date(2025, 10, 6), _dt.date(2025, 10, 17), "quiz", "sync", 10, 1_200_000, 1, 1.0, 0.08),
    ("T1", _dt.date(2025, 11, 17), _dt.date(2025, 11, 28), "midterm", "sync", 25, 2_400_000, 1, 1.0, 0.08),
    ("T1", _dt.date(2025, 12, 8), _dt.date(2025, 12, 19), "project", "async", 6, None, 1, 0.0, 1.0),
    ("T1", _dt.date(2026, 1, 5), _dt.date(2026, 1, 16), "final", "sync", 30, 3_600_000, 1, 1.0, 0.08),
    ("T2", _dt.date(2026, 2, 23), _dt.date(2026, 3, 6), "quiz", "sync", 12, 1_200_000, 2, 1.0, 0.08),
    ("T2", _dt.date(2026, 3, 23), _dt.date(2026, 4, 3), "midterm", "sync", 25, 2_400_000, 1, 0.62, 0.08),
    ("T2", _dt.date(2026, 4, 27), _dt.date(2026, 5, 8), "oral", "open", 5, None, 1, 0.0, 1.0),
    ("T2", _dt.date(2026, 5, 25), _dt.date(2026, 6, 5), "final", "sync", 30, 3_600_000, 1, 0.0, 0.08),
]
EXAM_DRAFT_SHARE_LAST = 0.35       # 8 numaralı sınavların %35'i draft
EXAM_ALLOW_REJOIN_SYNC = 0.72
EXAM_SECOND_ATTEMPT_SHARE = 0.21   # max_attempts=2 sınavlarda ikinci oturum oranı
EXAM_SECOND_ATTEMPT_THETA_BONUS = 0.45
EXAM_ABANDON_SHARE = 0.06          # sync sınavlarda yarıda bırakma
EXAM_ABANDON_PREFIX = 0.35         # yarıda bırakanda yazılan cevap payı
EXAM_GRADED_SHARE = 0.92
EXAM_UNGRADED_RECENT = 26          # son 3 haftanın notlandırılmamış sınavı
EXAM_EXTRA_QUESTIONS = 12          # etüt/kulüp sınavlarında soru sayısı

EXAM_KINDS = ["homework", "quiz", "midterm", "final", "project", "oral"]
EXAM_KIND_WEIGHTS = {"homework": 1, "quiz": 1, "midterm": 2, "final": 3, "project": 2, "oral": 1}

# --------------------------------------------------------------------------
# Madde modeli (SENARYO §4)
# --------------------------------------------------------------------------

DIFFICULTY_BANDS = [
    ("cok_kolay", 0.08, -2.60, -1.90),
    ("kolay", 0.18, -1.85, -0.95),
    ("orta", 0.44, -0.90, 0.60),
    ("zor", 0.22, 0.65, 1.60),
    ("cok_zor", 0.08, 1.65, 2.80),
]

# Zorluk bandı artık DAĞITILMAZ, `b`'den OKUNUR (zincir B): `b` bilişsel
# etiketlerden türediği için bant da onun sonucudur. Üst sınırlar
# `ITEM_B_OFFSET` çıkarıldıktan sonraki ham değere uygulanır; son bandın
# sınırı yoktur.
DIFFICULTY_BAND_CUTS = [
    ("cok_kolay", -1.88),
    ("kolay", -0.93),
    ("orta", 0.62),
    ("zor", 1.62),
    ("cok_zor", None),
]

# --------------------------------------------------------------------------
# BİLİŞSEL BOYUTLAR (zincir A / B / C)
#
# NEDEN: Önceki sürümde soru metni ile madde zorluğu bağımsızdı; metinden
# çıkarılabilen hiçbir desen yoktu (ölçülen korelasyon ~0). Artık:
#   A) metin etiketlerden üretilir  (`content_tr.make_labeled_question`)
#   B) `b` etiketlerden türer       (`DIM_B_EFFECT` + madde gürültüsü)
#   C) öğrenci yeteneği boyut bazında sapar (`ARCHETYPE_DIM_DELTA`)
# Etiket adları/değerleri `service/src/segment/rubric.py` ile BİREBİR aynıdır.
# --------------------------------------------------------------------------

#: Etiket önselleri. `hatirlama` düzeyinde çok adım üretilmez (tutarsız
#: etiket olurdu), bu yüzden `cok_adim` gerçekleşen payı ~%20'dir.
DIM_PRIORS = {
    "bilissel_talep": [("hatirlama", 0.32), ("uygulama", 0.42), ("analiz", 0.26)],
    "adim_sayisi": [("tek_adim", 0.70), ("cok_adim", 0.30)],
    "dikkat_tuzagi": [("yok", 0.55), ("var", 0.45)],
    "okuma_yuku": [("dusuk", 0.72), ("yuksek", 0.28)],
}

#: Etiketin madde zorluğuna (logit) katkısı. Analiz > uygulama > hatırlama;
#: çok adımlı ve yüksek okuma yüklü madde daha zor. Toplam beklenen değer
#: ~0 olacak biçimde merkezlendi ki `ITEM_B_OFFSET` anlamını korusun.
DIM_B_EFFECT = {
    "bilissel_talep": {"hatirlama": -0.75, "uygulama": 0.00, "analiz": 0.85},
    "adim_sayisi": {"tek_adim": -0.20, "cok_adim": 0.45},
    "okuma_yuku": {"dusuk": -0.18, "yuksek": 0.50},
    "dikkat_tuzagi": {"yok": -0.06, "var": 0.16},
}

#: Etiketlerin üstüne binen madde bazlı gürültü. Etiketlerin açıkladığı
#: değişkenlik payı ~%45'te kalsın diye seçildi: desen ölçülebilir, ama
#: madde hâlâ tek tek farklı.
ITEM_B_NOISE_SIGMA = 0.85

#: Çekici çeldiricinin seçilme ağırlığı. `yok` maddelerde çeldiriciler EŞİT
#: ağırlıklıdır (None = 1/(k-1)); `var` maddelerde tuzak şık öne çıkar.
DIM_W_M = {"var": 0.62, "yok": None}

# --------------------------------------------------------------------------
# Öğrenci boyut profilleri (zincir C)
#
# Her öğrencinin genel `theta`'sına EK olarak boyut sapması vardır: cevap
# olasılığı `theta_genel + boyut_sapmasi - b_madde` ile hesaplanır.
# Üç arketip belirgin bilişsel profil taşır, beşi kontrol grubudur (sapma 0).
# Büyüklükler 0,6-1,2 logit bandındadır: ölçülebilir ama gerçekçi.
# --------------------------------------------------------------------------

ARCHETYPE_DIM_DELTA = {
    # Kontrol grubu — hiçbir boyutta sapma yok.
    "A1": {}, "A2": {}, "A3": {}, "A5": {}, "A6": {},
    # Aceleci: analizde iyi, ama dikkat tuzağına düşüyor.
    "A4": {
        "bilissel_talep": {"hatirlama": -0.35, "uygulama": 0.0, "analiz": 0.60},
        "dikkat_tuzagi": {"var": -0.95, "yok": 0.0},
    },
    # Okuma güçlüğü: yüksek okuma yükünde belirgin düşüş.
    "A7": {
        "okuma_yuku": {"dusuk": 0.10, "yuksek": -1.10},
    },
    # Ezberci: hatırlamada güçlü, analizde zayıf.
    "A8": {
        "bilissel_talep": {"hatirlama": 0.90, "uygulama": 0.0, "analiz": -1.00},
    },
}

#: Sapma taşıyan arketiplerde öğrenci bazlı küçük dağılım (kontrol grubu
#: TAM sıfır kalsın diye yalnız sıfırdan farklı girdilere uygulanır).
DIM_DELTA_JITTER_SIGMA = 0.15

#: Tuzak şıkkın çekiciliğini arketipe göre büyüten çarpan (aceleci profil
#: yanlış cevap verdiğinde tuzağa daha sık düşer).
ARCHETYPE_TRAP_PULL = {"A4": 1.45}
MAX_TRAP_PULL_W_M = 0.90

QUALITY_BANDS = [
    ("iyi", 0.62, "normal", 1.15, 0.20, 0.80, 1.80),
    ("kabul", 0.20, "uniform", 0.50, 0.79, None, None),
    ("zayif", 0.10, "uniform", 0.18, 0.49, None, None),
    ("bozuk", 0.05, "uniform", 0.00, 0.10, None, None),
    ("negatif", 0.03, "uniform", -0.90, -0.35, None, None),
]

CHOICE_COUNT_WEIGHTS = [(4, 0.78), (5, 0.19), (3, 0.03)]
GUESS_FACTOR = 0.85
TEXT_QUESTION_SHARE = 0.15
TEXT_OMISSION_SHARE = 0.18
TEXT_ANSWER_MEDIAN_CHARS = 165
TEXT_ANSWER_SIGMA = 0.62
ANSWER_IMAGE_SHARE = 0.06          # metin cevaplarının %6'sı çizimli
QUESTION_IMAGE_SHARE = 0.06
BANK_QUESTION_IMAGE_SHARE = 0.04

OMISSION_TAU_LAST = 1.55           # sync sınavın son %20 sorusu
# Kalibrasyon: §4.6'daki omega değerleri hedef %12,5 boş bırakma oranına göre
# verilmiştir; üretilen b_i / theta dağılımında aynı hedefi tutturan çarpan.
OMISSION_SCALE = 0.33
# Notlandırma cömertliği: ham kazanılan puan ile öğretmen notu arasındaki fark
# (§7 L7 hedefi 62,8 ortalama). 1.0 = ham puan.
# Ham kazanilan puandan ogretmen notuna dogrusal donusum: SENARYO 7 L7/L8
# hedefleri (ortalama 62,8 / standart sapma 17,4) bu iki katsayiyla tutturulur.
MARK_SLOPE = 0.845
MARK_INTERCEPT = 23.6
# Madde zorluğu genel kayması: §4.2'deki b_i bantları okul yetenek dağılımına
# göre hedef p ortalaması 0,585'i tutturacak biçimde kaydırılır.
ITEM_B_OFFSET = 0.62
# Yetenek yayilimi: madde-ici gurultu (phi + eps + delta) ortalamaya dogru
# sikistirma yapar; SENARYO 7.3'teki A1-A7 farki (>=28 puan) bu carpanla korunur.
THETA_CENTER = 0.06
THETA_SPREAD = 1.35
DAY_FORM_SIGMA = 0.28              # phi_u(sinav)
ITEM_NOISE_SIGMA = 0.22

FROM_BANK_SHARE = 0.45
# Banka cekilislerinin bir kismi (uygun sablon kalmadigi icin) taze soruya
# duser; olculen gerceklesme orani. L18 hedefini tutturmak icin kullanilir.
FROM_BANK_REALIZATION = 0.95
BANKED_AS_SHARE = 0.06
BANK_TEXT_DIVERGENCE = 0.12
BANK_QUESTIONS_FULL = 900
BANK_VISIBILITY_SCHOOL = 0.38
BANK_SUBJECT_NONE = 54             # kenar durum #22
DELETED_BANK_TEMPLATES = 15        # kenar durum #14
BROKEN_FROM_BANK_TARGET = 48       # kopan exam_question.from_bank sayisi (L19)
ANSWER_KEY_EDITS = 5               # kenar durum #13

# --------------------------------------------------------------------------
# Ödev (SENARYO §2.6, §5.2)
# --------------------------------------------------------------------------

HOMEWORK_PAST_PER_COURSE = 12
HOMEWORK_FUTURE_PER_COURSE = 2
HOMEWORK_EXTRA_PER_COURSE = 3
HOMEWORK_ASSIGNED_SUBSET = 0.22    # %22'sinde assigned dolu
HOMEWORK_ASSIGNED_RATIO = 0.55
MAX_HOMEWORK_ASSIGNED = 200
HOMEWORK_DUE_2359_SHARE = 0.86
HOMEWORK_DUE_SHIFT_SHARE = 0.07    # due_at +48 saat ileri alınan ödev
HOMEWORK_FUTURE_NEAR_SUBMIT = 0.34
HOMEWORK_FUTURE_FAR_SUBMIT = 0.06
HOMEWORK_GRADED_SHARE = 0.878
HOMEWORK_MISSING_RESULT_SHARE = 0.05
HOMEWORK_FILE_SHARE = 0.26
HOMEWORK_FILE_MEAN = 1.4
MAX_HOMEWORK_FILES = 10
HOMEWORK_UPDATED_SHARE = 0.22
HOMEWORK_UPDATED_LATE_SHARE = 0.13
HOMEWORK_STATUS_SHARES = [("done", 0.88), ("incomplete", 0.07), ("missing", 0.05)]

# --------------------------------------------------------------------------
# Pomodoro (SENARYO §5.3)
# --------------------------------------------------------------------------

POMO_DAY_MULT = {0: 1.00, 1: 1.05, 2: 1.00, 3: 1.10, 4: 0.65, 5: 0.85, 6: 1.25}
POMO_BREAK_MULT = {"semester": 0.28, "short": 0.45, "holiday": 0.55}
POMO_EXAM_COEF = 1.90
POMO_EXAM_DECAY = 2.5
POMO_MAX_PER_DAY = 18
MIN_COUNTED_POMODORO_MS = 300_000
MAX_COUNTED_POMODORO_PER_DAY = 16
POMO_UNFINISHED_SHARE = 0.06
POMO_OPEN_USERS = 8
POMO_OVERFLOW_STUDENTS = 3         # kenar durum #16
# A7'de 18 ogrencinin 13'unde hic pomodoro yoktur (3.10 / A21)
POMO_A7_ZERO_STUDENTS = 13
# A8'de 11 ogrencide son 14 gunde >=3 failed sohbet mesaji olur (T5c)
CHAT_A8_FAILED_STUDENTS = 11
POMO_FINISHED_TOTAL_INFLATION = 0.08
# Başlangıç saati karma dağılımı (yerel saat dakikası aralığı, pay)
POMO_START_WINDOWS = [((420, 510), 0.05), ((750, 810), 0.06), ((960, 1140), 0.40),
                      ((1200, 1410), 0.41), ((1440, 1590), 0.08)]

# --------------------------------------------------------------------------
# Sohbet (SENARYO §5.4)
# --------------------------------------------------------------------------

CHAT_STUDENT_USERS_FULL = 155
CHAT_TEACHER_USERS = 19
CHAT_THREADS_PER_STUDENT = 9
CHAT_THREADS_PER_TEACHER = 4
CHAT_TURNS_LAMBDA = 2.1
# SENARYO 5.4 asistan mesaji paylari. `pending` payi 7 D20'deki 270 satirlik
# hedefi tutturacak bicimde yukseltilmistir (oradaki payda tum mesajlardir).
CHAT_STATUS_SHARES = [("complete", 0.894), ("failed", 0.046), ("pending", 0.060)]
CHAT_ERROR_CODES = [("ai_unavailable", 0.55), ("timeout", 0.30),
                    ("module_disabled", 0.08), ("rate_limited", 0.07)]
CHAT_TRUNCATED_SHARE = 0.03
CHAT_TITLE_SHARE = 0.82
CHAT_LATENCY_MEDIAN_MS = 1400
CHAT_LATENCY_SIGMA = 0.60
MAX_CHATBOT_THREADS = 20
MAX_CHATBOT_MESSAGE_LEN = 4000

CHAT_SYSTEM_PROMPTS = [
    "ödevimi nasıl teslim ederim",
    "teslim ettiğim ödevi sonradan değiştirebilir miyim",
    "ödevi geç teslim edersem ne olur",
    "sınav sonucum ne zaman açıklanır",
    "sınavda geri dönüp cevabımı değiştirebilir miyim",
    "sınava girdim ama internetim gitti, tekrar girebilir miyim",
    "sınavı iki kez yapabilir miyim",
    "devamsızlığımı nereden görebilirim",
    "yoklamam yanlış girilmiş, kime yazmalıyım",
    "pomodoro sayacım neden sayılmadı",
    "günde kaç pomodoro sayılıyor",
    "şifremi nasıl değiştiririm",
    "profil fotoğrafımı nasıl değiştiririm",
    "veli hesabım nasıl bağlanır",
    "soru havuzuna nasıl soru sorarım",
    "sorduğum soru neden onaylanmadı",
    "yemek rezervasyonumu nasıl iptal ederim",
    "öğretmenimden nasıl randevu alırım",
    "randevum onaylandı mı",
    "notlarım nerede görünüyor",
    "ders notlarına nereden ulaşırım",
    "tahtaya nasıl katılırım",
    "mesaj kutumdaki mesajı nasıl arşivlerim",
    "rozetleri nasıl kazanıyorum",
    "etkinliğe nasıl kaydolurum",
]

CHAT_CONTENT_PROMPTS = [
    "türev nasıl alınır",
    "mitoz ve mayoz farkı nedir",
    "present perfect ne zaman kullanılır",
    "ikinci dereceden denklem çözümünü anlatır mısın",
    "tork formülü neydi",
    "fotosentez denklemini yazar mısın",
    "bu soruyu çözemiyorum yardım eder misin",
    "matematik sınavına nasıl çalışmalıyım",
]
CHAT_CONTENT_SHARE = 0.22

CHAT_SYSTEM_REPLIES = [
    "Bu işlemi menüdeki ilgili bölümden yapabilirsin. Adımları sırasıyla izlemen yeterli.",
    "Panelindeki ilgili kartı açtığında gerekli düğmeyi göreceksin.",
    "Bu ayar profil sayfandan değiştirilebilir. Kaydetmeyi unutma.",
    "Yetkin varsa bu ekranda işlemi tamamlayabilirsin; yoksa öğretmenine yazman gerekir.",
    "Kayıtların listelendiği ekranda filtreleri kullanarak aradığını bulabilirsin.",
]
CHAT_CONTENT_REPLIES = [
    "Ders içeriğine ilişkin sorular için öğretmenine ya da ders notlarına başvurmanı öneririm.",
    "Bu konuda içerik bilgisi veremiyorum; ilgili dersin notlarına bakabilirsin.",
    "Konu anlatımı yapamıyorum, ama ders notları ve soru havuzu bu konuda yardımcı olabilir.",
]

# --------------------------------------------------------------------------
# Havuz soruları (SENARYO §5.6)
# --------------------------------------------------------------------------

POOL_APPROVED_SHARE = 0.78
POOL_SOLVED_SHARE = 0.64
POOL_SOLUTIONS_PER_SOLVED = 2.44
POOL_SOLUTION_TEACHER_SHARE = 0.41
POOL_IMAGE_SHARE = 0.12
POOL_UNSOLVED_OLD_TARGET = 180

# --------------------------------------------------------------------------
# Randevu (SENARYO §5.5)
# --------------------------------------------------------------------------

APPOINTMENT_TEACHERS = 15
APPOINTMENT_SLOT_MINUTES = [930, 960]   # 15:30 ve 16:00 yerel
APPOINTMENT_SLOT_DAYS = [1, 3]          # Salı, Perşembe
APPOINTMENT_SLOT_LEN_MIN = 20
APPOINTMENT_FUTURE_WEEKS = 9
APPOINTMENT_SERIES_SHARE = 0.64
APPOINTMENT_REQUEST_SHARE = 0.65
APPOINTMENT_STATUS_SHARES = [("approved", 0.58), ("pending", 0.17),
                             ("rejected", 0.09), ("cancelled", 0.16)]
APPOINTMENT_STUDENT_SHARE = 0.61
APPOINTMENT_PROPOSED_SHARE = 0.14
APPOINTMENT_CANCEL_REASON_SHARE = 0.72
APPOINTMENT_OLD_PENDING_SHARE = 0.51
MAX_APPOINTMENT_REASON_LEN = 1000

APPOINTMENT_REASONS = [
    "Matematik dersinde son konularda zorlanıyorum, birlikte bakabilir miyiz?",
    "Oğlumun devamsızlığı hakkında görüşmek istiyorum.",
    "Sınav sonucumu değerlendirmek için randevu almak istiyorum.",
    "Kızımın ders çalışma düzeni konusunda fikrinizi almak istiyorum.",
    "Ödev teslimlerimde sorun yaşıyorum, kısa bir görüşme rica ediyorum.",
    "Üniversite tercih süreci hakkında bilgi almak istiyorum.",
    "Son sınavdaki sorularla ilgili birkaç sorum olacak.",
    "Konu tekrarı için nasıl bir plan yapmalıyım, danışmak istiyorum.",
]
APPOINTMENT_REJECT_REASONS = [
    "Bu saatte kurul toplantım var, başka bir saate alalım.",
    "Belirtilen saatte okulda olmayacağım.",
    "Aynı saatte başka bir randevu onaylandı.",
]
APPOINTMENT_CANCEL_REASONS = [
    "Rahatsızlandığım için katılamayacağım.",
    "Planlarım değişti, ileri bir tarihe almak istiyorum.",
    "Konu telefonda çözüldü, randevuya gerek kalmadı.",
]

# --------------------------------------------------------------------------
# Yemek (SENARYO §5.5, E5-E7, E9)
# --------------------------------------------------------------------------

MEAL_SLOTS = ["breakfast", "lunch", "snack"]
MEAL_SLOT_SERVING_MINUTE = {"breakfast": 480, "lunch": 735, "snack": 930}
MENU_CAPACITY = {"breakfast": 60, "lunch": 180, "snack": 90}
MENU_LUNCH_EVERY_SCHOOL_DAY = True
MENU_SNACK_DAYS_PER_WEEK = 4
MENU_BREAKFAST_DAYS_PER_WEEK = 2.5  # her ikinci okul günü
MENU_DISHES_PER_MENU = 4
DISH_PRICE_MINOR = (1500, 6500)
DISH_TAG_SHARE = 0.38
DIETARY_TAGS = ["vegetarian", "vegan", "gluten_free", "lactose_free", "nut_allergy"]
DIETARY_PROFILE_SHARE = 0.22
MEAL_BOOKING_LUNCH_PER_DAY = 75
MEAL_BOOKING_SNACK_PER_DAY = 16
MEAL_BOOKING_BREAKFAST_PER_DAY = 8
MEAL_BOOKING_CANCEL_SHARE = 0.11
MEAL_BOOKING_ATTEMPT2_SHARE = 0.06
MEAL_ATTENDANCE_SHARE = 0.94
MEAL_ATTENDANCE_SERVED = 0.91
MEAL_CREDIT_ROWS = 580
MEAL_REVERSAL_ROWS = 20
MEAL_CANCEL_CUTOFF_MINUTES = 720
MAX_DISH_PRICE_MINOR = 1_000_000
MAX_LEDGER_AMOUNT_MINOR = 10_000_000

DISH_NAMES = [
    "Mercimek Çorbası", "Ezogelin Çorbası", "Etli Kuru Fasulye", "Tavuk Sote",
    "Izgara Köfte", "Fırın Makarna", "Sebzeli Pilav", "Bulgur Pilavı",
    "Mevsim Salata", "Cacık", "Ayran", "Sütlaç", "Kemalpaşa Tatlısı",
    "Zeytinyağlı Taze Fasulye", "Karnıyarık", "Pide", "Poğaça", "Simit",
    "Peynirli Omlet", "Meyve Tabağı", "Kek", "Meyveli Yoğurt",
]

# --------------------------------------------------------------------------
# Ödeme (SENARYO §5.5)
# --------------------------------------------------------------------------

FEE_PLANS = [
    ("Peşin Ödeme", 22, 1, 1_800_000),
    ("9 Taksit", 168, 9, 220_000),
    ("6 Taksit", 42, 6, 325_000),
    ("Burslu", 18, 9, 55_000),
]
FEE_FIRST_DUE = _dt.date(2025, 9, 10)
PAYMENT_ON_TIME_SHARE = 0.89
PAYMENT_LATE_MEDIAN_DAYS = 12
PAYMENT_REFUNDS = 20
PAYMENT_METHODS = [("havale", 0.52), ("kredi_karti", 0.38), ("nakit", 0.10)]

# --------------------------------------------------------------------------
# Etkinlik (SENARYO §2.7)
# --------------------------------------------------------------------------

EVENT_PAST = 43
EVENT_FUTURE = 15
EVENT_AUDIENCE_SHARES = [("school", 0.31), ("role", 0.10), ("class", 0.26),
                         ("course", 0.21), ("registration", 0.12)]
EVENT_REGISTRATION_SHARE = 0.62
EVENT_ATTENDANCE_EVENTS = 35
EVENT_FULL_CAPACITY = 5

EVENT_TITLES = [
    "Veli Toplantısı", "Bilim Şenliği", "Kariyer Günü", "Kitap Kulübü Buluşması",
    "Satranç Turnuvası", "Tiyatro Gösterimi", "Müze Gezisi", "Üniversite Tanıtım Günü",
    "Spor Şenliği", "Şiir Dinletisi", "Robotik Atölyesi", "Fotoğraf Sergisi",
    "Münazara Finali", "Sınav Stratejileri Semineri", "Sağlıklı Beslenme Semineri",
    "Mezuniyet Hazırlık Toplantısı", "Okul Gazetesi Toplantısı", "Doğa Yürüyüşü",
]

# --------------------------------------------------------------------------
# Tahta, not, mesaj, ders notu (SENARYO §5.7)
# --------------------------------------------------------------------------

BOARD_TEACHER_COUNT = 192
BOARD_STUDENT_COUNT = 88
BOARD_STROKES_TOTAL = 9000
BOARD_CLOSED = 12
BOARD_LOCKED = 8
BOARD_EPOCH2 = 3
BOARD_CLEAR_SHARE = 0.03
BOARD_PARTICIPANT_SHARES = [((1, 1), 0.22), ((2, 3), 0.36), ((4, 8), 0.28), ((9, 25), 0.14)]
MAX_EPOCH_STROKES = 5000
MAX_BOARD_STROKES = 50000
MAX_BOARDS_PER_CREATOR = 200

NOTE_STUDENT_SHARE = 0.55
NOTE_PER_STUDENT = 9
NOTE_PER_TEACHER = 12
NOTE_FILE_SHARE = 0.27
MAX_NOTE_FILES = 10

MESSAGE_TOTAL_FULL = 6800
MESSAGE_DIRECTION_SHARES = [("student_teacher", 0.38), ("teacher_student", 0.24),
                            ("parent_teacher", 0.19), ("teacher_parent", 0.11),
                            ("staff_all", 0.08)]
MESSAGE_SENDER_FOLDERS = [("sent", 0.86), ("archive", 0.10), ("trash", 0.04)]
MESSAGE_RECIPIENT_FOLDERS = [("inbox", 0.78), ("archive", 0.16), ("trash", 0.06)]
MESSAGE_READ_SHARE = 0.66
MESSAGE_LABEL_SHARE = 0.12

MESSAGE_SUBJECTS = [
    "Ödev hakkında", "Devamsızlık bilgisi", "Sınav sonucu", "Randevu talebi",
    "Ders materyali", "Konu tekrarı", "Veli görüşmesi", "Etkinlik duyurusu",
    "Proje teslimi", "Sınıf duyurusu", "Rehberlik görüşmesi", "Kulüp çalışması",
]
MESSAGE_BODIES = [
    "Merhaba, konuyla ilgili kısa bir bilgi rica ediyorum. İyi çalışmalar.",
    "Bu haftaki çalışma planını paylaşıyorum, sorularınız olursa yazabilirsiniz.",
    "Geçen dersteki konuyu tekrar etmemiz gerekiyor, uygun olduğunuzda görüşelim.",
    "Ödev teslim tarihiyle ilgili bir sorum olacaktı, yardımcı olabilir misiniz?",
    "Devamsızlık kaydında bir hata olabilir, kontrol edebilir misiniz?",
    "Bilgilendirme için teşekkür ederim, gereğini yapacağım.",
    "Sınav sonucunu değerlendirmek için kısa bir görüşme yapabilir miyiz?",
    "Etkinlik programını ekte paylaşıyorum, katılımınızı bekliyoruz.",
]
MESSAGE_LABELS = ["önemli", "takip", "veli", "sınav", "ödev"]

COURSE_NOTE_PER_COURSE = 9
COURSE_NOTE_FILE_SHARE = 0.72
RAG_MODELS = ["hezarfen-embed-tr-v1", "hezarfen-embed-tr-v2", "mini-embed-384"]

WORK_ENTRY_DAY_SHARE = 0.94
WORK_ENTRY_OPEN_STAFF = 4
WORK_CHECK_IN_MINUTE = (465, 510)     # 07:45 - 08:30 yerel
WORK_CHECK_OUT_MINUTE = (960, 1080)   # 16:00 - 18:00 yerel

LIVE_SESSIONS = 40
SESSION_DURATION_MS = 7 * DAY_MS

# --------------------------------------------------------------------------
# Rozetler (constant.rs:1095, 34 kod)
# --------------------------------------------------------------------------

BADGES = [
    ("homework_submitted_1", "homework_submitted_total", 1),
    ("homework_submitted_10", "homework_submitted_total", 10),
    ("homework_submitted_50", "homework_submitted_total", 50),
    ("homework_on_time_10", "homework_on_time_total", 10),
    ("homework_on_time_25", "homework_on_time_total", 25),
    ("exam_sat_1", "exam_sat_total", 1),
    ("exam_sat_10", "exam_sat_total", 10),
    ("exam_sat_25", "exam_sat_total", 25),
    ("pomodoro_finished_10", "pomodoro_finished_total", 10),
    ("pomodoro_finished_50", "pomodoro_finished_total", 50),
    ("pomodoro_finished_200", "pomodoro_finished_total", 200),
    ("pomodoro_focus_ms_36000000", "pomodoro_focus_ms_total", 36_000_000),
    ("pomodoro_focus_ms_180000000", "pomodoro_focus_ms_total", 180_000_000),
    ("marks_given_10", "marks_given_total", 10),
    ("marks_given_50", "marks_given_total", 50),
    ("marks_given_250", "marks_given_total", 250),
    ("lessons_held_10", "lessons_held_total", 10),
    ("lessons_held_50", "lessons_held_total", 50),
    ("lessons_held_200", "lessons_held_total", 200),
    ("pool_approved_5", "pool_approved_total", 5),
    ("pool_approved_25", "pool_approved_total", 25),
    ("pool_approved_100", "pool_approved_total", 100),
    ("pool_published_1", "pool_published_total", 1),
    ("pool_published_10", "pool_published_total", 10),
    ("pool_published_50", "pool_published_total", 50),
    ("lessons_attended_10", "lessons_attended_total", 10),
    ("lessons_attended_50", "lessons_attended_total", 50),
    ("lessons_attended_200", "lessons_attended_total", 200),
    ("high_mark_1", "high_mark_total", 1),
    ("high_mark_10", "high_mark_total", 10),
    ("high_mark_25", "high_mark_total", 25),
    ("study_streak_3", "study_streak_longest", 3),
    ("study_streak_7", "study_streak_longest", 7),
    ("study_streak_30", "study_streak_longest", 30),
]
# §5.3 kasıtlı eksik sayaç: bu iki sayaç NONE bırakılır, rozetleri de verilmez
UNWRITTEN_COUNTERS = {"lessons_attended_total", "high_mark_total"}

# --------------------------------------------------------------------------
# Ayarlar (SENARYO §1.6 + E5/E6/E16)
# --------------------------------------------------------------------------

SETTINGS = {
    "exam_kinds": [{"name": k, "weight": EXAM_KIND_WEIGHTS[k]} for k in EXAM_KINDS],
    "attendance_statuses": ["present", "absent", "late", "excused"],
    "grade_bands": [
        {"min": 85, "label": "Pekiyi"},
        {"min": 70, "label": "İyi"},
        {"min": 55, "label": "Orta"},
        {"min": 45, "label": "Geçer"},
        {"min": 0, "label": "Geçmez"},
    ],
    "max_file_bytes": 5_242_880,
    "chatbot_history_turns": 8,
    "max_chatbot_threads": MAX_CHATBOT_THREADS,
    "max_chatbot_message_len": MAX_CHATBOT_MESSAGE_LEN,
    "meal_slots": [{"name": s, "serving_minute": MEAL_SLOT_SERVING_MINUTE[s]}
                   for s in MEAL_SLOTS],
    "dietary_tags": DIETARY_TAGS,
    "meal_cancel_cutoff_minutes": MEAL_CANCEL_CUTOFF_MINUTES,
}

MODULES_ALL = sorted([
    "chatbot", "notes", "messages", "events", "appointments", "courses", "course_notes",
    "classes", "sessions", "exams", "marks", "meals", "payments", "work", "pomodoro",
    "questions", "bank_questions", "attendance", "subjects", "homework", "boards",
])

# --------------------------------------------------------------------------
# Kenar durumlar (SENARYO §6)
# --------------------------------------------------------------------------

EDGE_MIDTERM_JOIN_DATES = [_dt.date(2026, 2, 16), _dt.date(2026, 2, 23),
                           _dt.date(2026, 3, 2), _dt.date(2026, 3, 9),
                           _dt.date(2026, 3, 9), _dt.date(2026, 3, 23)]
EDGE_LEAVER_DATES = [_dt.date(2025, 11, 21), _dt.date(2025, 12, 19),
                     _dt.date(2026, 1, 16), _dt.date(2026, 2, 27)]
EDGE_COLD_START_EXTRA = 2       # #1 ile örtüşmeyen pasif öğrenci
EDGE_NO_HOMEWORK_COURSE = 3     # #9: bir derste hiç ödev teslim etmeyen
EDGE_BLANK_ATTEMPTS = 9         # #8: tüm soruları boş bırakılan oturum
EDGE_UNMEASURED_SUBJECTS = 22   # #11: hiç ölçülmemiş konu

# --------------------------------------------------------------------------
# Dosya düzeni — schema.json.load_order sırasına birebir uyar
# --------------------------------------------------------------------------

# (dosya numarası, dosya adı eki, bu dosyada yazılacak tablolar)
# Tablolar load_order'daki mutlak sırayı korur; dosya sınırları yalnız gruplamadır.
FILE_LAYOUT = [
    (1, "temel", ["kind_ref", "migration_mark", "settings", "slot_ref", "term"]),
    (2, "kullanicilar", ["user"]),
    (3, "profil_ve_yapi", ["appointment_slot", "badge_award", "board", "chatbot_thread",
                           "class_group", "course"]),
    (4, "operasyon", ["dietary_profile", "fee_plan", "meal_ledger", "menu", "message",
                      "note"]),
    (5, "kisisel_kayitlar", ["parent_link", "payment_ledger", "pomodoro_session",
                             "pool_question", "session", "work_entry"]),
    (6, "iliskiler", ["appointment", "board_stroke", "chatbot_message", "class_blueprint",
                      "class_member", "course_note", "course_session", "enrollment",
                      "event"]),
    (7, "akademik", ["exam", "fee_plan_assignment", "meal_attendance", "meal_booking",
                     "menu_dish", "note_file", "solution", "subject"]),
    (8, "degerlendirme", ["attendance", "bank_question", "class_course",
                          "course_note_file", "exam_attempt", "exam_result", "homework",
                          "registration", "session_attendance"]),
    (9, "sorular", ["bank_question_image", "exam_question", "homework_result",
                    "rag_output"]),
    (10, "cevap_gorselleri", ["answer_image"]),
    (11, "exam_answer", ["exam_answer"]),
    (12, "teslimler", ["homework_submission", "question_image", "homework_file"]),
]

# Çıktı dosyası başına yorum bloğu için tablo açıklamaları
FILE_DESCRIPTIONS = {
    1: "Ayarlar, dönemler ve sayaç referans tabloları",
    2: "Tüm kullanıcılar (admin, yönetici, öğretmen, öğrenci, veli) ve profil sayaçları",
    3: "Randevu slotları, rozetler, tahtalar, sohbet başlıkları, şubeler ve dersler",
    4: "Yemek/ödeme operasyonu, mesajlar ve kişisel notlar",
    5: "Veli bağları, ödeme hareketleri, pomodoro, soru havuzu, oturumlar, mesai",
    6: "Randevular, tahta vuruşları, sohbet mesajları, sınıf/ders ilişkileri, oturumlar",
    7: "Sınavlar, yemek rezervasyonları, konular ve çözümler",
    8: "Yoklamalar, soru bankası, sınav denemeleri, sonuçlar, ödevler",
    9: "Sınav soruları, ödev notları, RAG çıktıları",
    10: "Cevap görselleri",
    11: "Sınav cevapları (en büyük tablo)",
    12: "Ödev teslimleri, soru görselleri ve teslim dosyaları",
}
