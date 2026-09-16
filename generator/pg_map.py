"""SurrealDB tohumu -> PostgreSQL semasi esleme KURALLARI.

Burada yalnizca **tablo** vardir, kod yok. `pg_emit.py` bunu okur.

---------------------------------------------------------------------------
Tasarim: sessiz dusurme YASAK
---------------------------------------------------------------------------
Her alan ya eslenir, ya cocuk tabloya acilir, ya duzlestirilir, ya da ACIKCA
"dusurulecek" diye yazilir. Eslenmemis bir alan cevirici tarafindan HATA olarak
bildirilir ve cevirim durur.

Bu katilik bir tercih degil, bedeli odenmis bir ders: SurrealDB surumunde
SCHEMAFULL tablolar tanimsiz alani tek kelime etmeden atiyordu ve bes alanin
hic yazilmadigi ancak aylar sonra fark edildi. Postgres de tanimsiz kolona
yazmaya calisirsa hata verir; ama cevirici alani kendi atarsa hata VERMEZ.
Tek koruma, atmayi imkansiz kilmak.
"""

# --- tablo adlari -----------------------------------------------------------
#
# PostgreSQL `user` ve `session` sozcuklerini kolon/tablo adi olarak kabul
# etmiyor. Backend'in kendi cevirisi ne yaptiysa aynisi yapilir
# (migrations/school/20260912000001_identity.sql bas aciklamasi).
TABLE_RENAME = {
    "user": "app_user",
    "session": "user_session",
}

#: `user` adli HER kolon. `session_attendance.session` kolonu KALIR —
#: PostgreSQL'de `session` ayrilmis sozcuk degil (backend de birakti).
COLUMN_RENAME = {"user": "app_user"}

#: Postgres'te karsiligi OLMAYAN ve olmamasi gereken tablolar.
DROP_TABLES = {
    # Backend cevirisinde kasten atildi: "migration_mark + every REMOVE
    # retirement line, PRE_REPAIR, BACKFILL ... all dead, preproduction".
    "migration_mark",
}

#: Tablo basina dusurulecek alanlar ve GEREKCESI.
DROP_COLUMNS = {
    # Parola artik okul veritabaninda degil, control'deki `person` satirinda.
    # `app_user.person` birlestirme anahtaridir.
    ("user", "password_hash"): "control.person.password_hash'e tasindi",
}

# --- gomulu nesne -> duz kolon ----------------------------------------------
#
# `event.audience` bir nesneydi; Postgres onu `audience_*` kolonlarina acti.
FLATTEN = {
    ("event", "audience"): "audience_",
}

# --- gomulu dizi -> cocuk tablo ---------------------------------------------
#
# (kaynak tablo, alan) -> (cocuk tablo, sahip kolonu, deger kolonu, ord var mi)
#
# `ord` yalnizca SIRASI anlamli olan listelerde var; backend hangilerine
# koyduysa aynisi (menu_dish_tag ve dietary_profile_tag'de var, uyelik
# tablolarinda yok — kume onlar, liste degil).
CHILD_TABLES = {
    ("course", "teachers"): ("course_teacher", "course", "teacher", False),
    ("board", "participants"): ("board_participant", "board", "participant", False),
    ("class_blueprint", "courses"): ("blueprint_course", "blueprint", "course", False),
    ("homework", "assigned"): ("homework_assignment", "homework", "student", False),
    ("rag_output", "sources"): ("rag_output_source", "output", "source", False),
    ("dietary_profile", "tags"): ("dietary_profile_tag", "student", "tag", True),
    ("menu_dish", "tags"): ("menu_dish_tag", "dish", "tag", True),
    ("school", "modules"): ("school_module", "school", "module", False),
    ("settings", "attendance_statuses"): (
        "settings_attendance_status", "settings", "status", False),
    ("settings", "dietary_tags"): ("settings_dietary_tag", "settings", "tag", False),
}

# --- gomulu resim alanlari -> kendi tablosu ---------------------------------
#
# `pool_question.image_file/.image_content_type/.image_size` uclusu Postgres'te
# ayri bir tabloya tasindi. Ucu de NONE ise satir HIC yazilmaz.
IMAGE_CHILD = {
    "pool_question": ("pool_question_image", "question"),
    "solution": ("solution_image", "solution"),
}
IMAGE_FIELDS = ("image_file", "image_content_type", "image_size")
IMAGE_COLUMNS = ("file", "content_type", "size")

# --- (kaldirildi) birincil anahtar stratejisi -------------------------------
#
# Elle tutulan bir tablo->strateji listesi vardi ve iki kez yanildi
# (, ). Strateji artik HEDEF SEMADAN
# turetiliyor: bkz. pg_emit.id_strategy(). Sema zaten cevabi biliyor.

# --- (kaldirildi) kimlik basiminda kullanilacak zaman alani ----------------
#
# Bir sure burada tablo -> zaman alani eslemesi vardi; kimlik basimina satirin
# kendi damgasi katiliyordu. KALDIRILDI: ayni kayit, yazilirken bir uuid,
# kendisine referans verilirken baska bir uuid aliyordu (referans veren taraf o
# damgayi bilmiyor). Damga artik YALNIZCA anahtarin kendisinden okunuyor
# (bkz. pg_emit.key_to_uuid).

# --- control / okul ayrimi --------------------------------------------------
#
# Backend artik iki veritabani tutuyor: `control` (okul kutugu + kimlik) ve
# okul basina bir veritabani. Tohum ikisini de doldurmali.
CONTROL_TABLES = {
    "school", "school_module", "builder", "builder_session",
    "person", "person_school", "person_session", "rate_limit",
}


# --- yeni semanin istedigi, eski semada OLMAYAN kolonlar --------------------
#
# Backend'in Postgres cevirisi birkac kolon EKLEDI. Ornegi `app_user.created_at`:
# eski `user` tablosunda boyle bir alan yoktu, yenisinde `BIGINT NOT NULL`.
#
# Uydurmuyoruz, TURETIYORUZ: kayit kimligi ULID'dir ve ULID'in ilk 48 biti
# kaydin kendi olusturma damgasidir. Backend de ayni sozlesmeyi suruyor
# (uuid v7'nin ilk 48 biti unix-ms). Yani buradaki deger, satirin gercekten
# olusturuldugu andir; yer doldurmak icin konmus bir sabit degil.
#
# (tablo, kolon) -> turetme kurali
# Kural bicimleri:
#   "id_ulid_ms"        -> satirin KENDI kimliginden (ULID) damga.
#   "ulid_ms:<alan>"    -> satirin <alan> referansinin ULID damgasi.
#
# ⚠️ YAKLASIKLIK UYARISI. Bunlarin hepsi ayni dogrulukta DEGIL:
#
#   TAM  `app_user.created_at`          — kullanicinin kendi ULID'i.
#   TAM  `session_attendance.marked_at` — dersin kendi ULID'i; yoklama o derste
#                                         alinir, yani damga gercekten o an.
#   YAKLASIK `attendance.marked_at`     — etkinligin damgasi. Yoklama etkinlik
#                                         sirasinda alinir; sapma saatler
#                                         mertebesinde.
#   YAKLASIK `registration.created_at`  — etkinligin damgasi. Kayit etkinlikten
#                                         ONCE olur, yani bu deger gercek
#                                         kayittan SONRAYA dusebilir.
#   YAKLASIK `enrollment.created_at`    — dersin damgasi. Ders donem basinda
#                                         acilir ve kayitlar da o siralarda
#                                         yapilir; donem ortasinda kaydolan
#                                         ogrenci icin YANLIS.
#   YAKLASIK `exam_result.graded_at`    — sinavin damgasi. Notlandirma sinavdan
#                                         GUNLER sonra olur; bu deger
#                                         "notlandirma gecikmesi" gibi bir olcum
#                                         icin KULLANILAMAZ.
#
# Neden yine de konuyor: kolonlar `NOT NULL` ve bos birakilamaz. Yaklasik bir
# damga, uydurma bir sabitten iyidir — ama hangisinin yaklasik oldugu
# yazilmadan kullanilmasi tehlikelidir, o yuzden burada yaziyor.
#
# ZEKA bu bes alanin HICBIRINI okumuyor: kopru izin listesinde sinav ve
# yoklama-zaman yolu yok. Yani bugun hicbir analizi etkilemiyorlar.
DERIVED_COLUMNS = {
    ("user", "created_at"): "id_ulid_ms",
    ("session_attendance", "marked_at"): "ulid_ms:session",
    ("attendance", "marked_at"): "ulid_ms:event",
    ("registration", "created_at"): "ulid_ms:event",
    ("enrollment", "created_at"): "ulid_ms:course",
    ("exam_result", "graded_at"): "ulid_ms:exam",
}


# --- DEMO okulunun kimligi --------------------------------------------------
#
# Okul veritabaninin ADI okulun uuid'sinden turetiliyor
# (`tenant::school_db_name` -> "{control}_school_{uuid.simple}"), slug'dan
# DEGIL. Yani tohumu yuklemek icin okulun uuid'sinin ONCEDEN bilinmesi gerek;
# aksi halde hangi veritabanina yazacagimizi backend okulu yaratana kadar
# bilemeyiz.
#
# Demo icin uuid SABITLENDI. Boylece yukleme tek yonlu ve tekrarlanabilir:
# veritabanini bu addan kur, semayi uygula, tohumu dok, control satirini yaz.
# Backend acildiginda okulu `active` ve semasi yuklenmis bulur.
#
# Ayri bir okul olarak duruyor: baska bir okulun verisine dokunmaz, slug'i ve
# uuid'si kendine ozeldir.
DEMO_SCHOOL_ID = "01930000-0000-7000-8000-00000000de70"

#: Kullanicinin control tarafindaki `person` satirinin kimligi kullanici
#: adindan deterministik uretilir. Ayni kullanici her uretimde ayni person
#: uuid'sini alir; tohumu iki kez yuklemek cift kayit dogurmaz.
PERSON_NS = "person"
DEMO_SCHOOL_SLUG = "hezarfen-demo"
DEMO_SCHOOL_NAME = "Hezarfen Demo Lisesi"
