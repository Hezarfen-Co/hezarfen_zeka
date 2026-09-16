"""Boyut tanimlari, yonergeler (rubric) ve derse ozgu eylem fiilleri.

NEDEN 4 BOYUT (bulgu 4):
  Bulgu 4, insan uzman taban cizgisinin bilissel duzey etiketlemede dusuk ve cok
  degiskken oldugunu (ham uyum ~%54; Krippendorff alpha 0,25'ten Fleiss kappa
  0,765'e) gosteriyor ve PRATIK SONUC olarak "boyut sayisini 6 yerine 3-4'e
  indir, rubrik kalibrasyonu yap" diyor. Bu yuzden 6 duzeyli Bloom SEMASI
  KULLANILMIYOR; yerine 4 boyut var ve en genis boyut yalnizca 3 duzeyli.

NEDEN BU 4 BOYUT:
  1. bilissel_talep  — Bloom'un 6 duzeyi 3'e indirgenmis hali (bulgu 4).
  2. adim_sayisi     — ikili; sorunun cozum zinciri uzunlugu.
  3. dikkat_tuzagi   — ikili; BU VERIDE DIS DOGRULAMA HEDEFI OLAN TEK BOYUT
                       (741 madde, `content_tr.py::MISCONCEPTIONS`).
  4. okuma_yuku      — ikili; metin/dil yuku.
  Uc boyutun ikili olmasi, kategori sayisini bulgu 4'un istedigi yonde tutar.

NEDEN EYLEM FIILI LISTESI (bulgu 3):
  Bulgu 3: "uzman secimi ornek + duzeye ozgu eylem fiili listesi ham ornek
  sayisini artirmaktan daha degerlidir; bu ucuz tasarim dersi bizde CALISIR (ek
  ajan/token gerektirmez, yalnizca daha uzun istem)". Bu yuzden her duzey icin
  fiil listesi ve DERSE OZGU fiil listeleri asagida.
  KAYIT: bulgu 3'un sayilari Ingilizce Bloom gorevlerinden; Turkce'ye sayisal
  transfer YAPILAMAZ, yalnizca niteliksel tasarim sinyalidir.

NEDEN AZ SAYIDA, SECILMIS ORNEK:
  Bulgu 3 karsi kanit da tasiyor: egitsel soru siniflandirmasinda
  "sifir-ornekli + tanimlar" few-shot'i gecmis. Bu yuzden yonergede TANIMLAR ve
  SINIR DURUMLARI agirliktadir; ornek sayisi kasitli olarak azdir (<=2/boyut) ve
  `prompts.py` icinde ornekli/ornekisiz istem surumleri AYRI AYRI vardir ki
  hangisinin daha iyi oldugu olculebilsin.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Dimension:
    """Tek bir segmentasyon boyutu."""

    name: str
    #: Izinli etiketler (nominal; sira anlam tasimaz).
    labels: tuple[str, ...]
    #: Boyutun bir cumlelik tanimi.
    definition: str
    #: Etiket -> o etiketin operasyonel olcutu.
    criteria: dict[str, str]
    #: Sinir durumlari: karar kurallari (rubrik kalibrasyonu, bulgu 4).
    boundaries: tuple[str, ...] = ()
    #: Kisa, secilmis ornekler (bulgu 3). Bilerek az.
    examples: tuple[tuple[str, str], ...] = ()
    #: Bu boyutun bu veride DIS dogrulama hedefi var mi?
    externally_validated: bool = False
    #: DENEYSEL mi? Deneysel boyut etiketlenir ve RAPORLANIR, ancak
    #: (a) Asama 0 kapisini BLOKE ETMEZ, (b) ogrenci profili / tavsiye gibi
    #: asagi akis hesaplarina GIRMEZ. Gerekcesi `downgrade_note` alanindadir.
    experimental: bool = False
    #: Deneysel boyutlar icin: neden indirildi, hangi olcumle, ne zaman geri alinir.
    downgrade_note: str = ""


# --------------------------------------------------------------------------
# 1) bilissel_talep
# --------------------------------------------------------------------------

VERBS_BY_LEVEL: dict[str, tuple[str, ...]] = {
    "hatirlama": (
        "tanimla", "belirt", "listele", "adlandir", "hangisidir", "kimdir",
        "ne zaman", "nedir", "esles", "hatirla", "soyle",
    ),
    "uygulama": (
        "hesapla", "bul", "cozumle", "uygula", "yerine koy", "kac", "kactir",
        "elde et", "donustur", "cizin", "yaz", "tamamla", "kullanarak bul",
    ),
    "analiz": (
        "karsilastir", "ayirt et", "hangisi yanlistir", "hangisi soylenemez",
        "cikarim yap", "yorumla", "degerlendir", "iliskilendir", "neden-sonuc",
        "gerekcelendir", "genelle", "elestir", "sinifla",
    ),
}

# Derse ozgu eylem fiilleri (bulgu 3). Ders adlari `items_enriched.json`
# icindeki `course_name`/`subject_name` ile kaba eslesir; eslesme yoksa yalnizca
# genel liste kullanilir.
VERBS_BY_COURSE: dict[str, dict[str, tuple[str, ...]]] = {
    "Matematik": {
        "hatirlama": ("tanimi nedir", "hangi kume", "sembolu nedir"),
        "uygulama": ("kok bul", "turevini al", "integralini hesapla",
                     "denklemi coz", "sadelestir", "acikla-carpanlara ayir",
                     "esitsizligi coz", "limitini bul"),
        "analiz": ("grafigi yorumla", "hangi kosulda gecerlidir",
                   "ters onermesi", "genel terimi cikar", "ispatla"),
    },
    "Fizik": {
        "hatirlama": ("birimi nedir", "yasayi belirt"),
        "uygulama": ("kuvveti hesapla", "ivmeyi bul", "torku hesapla",
                     "isi hesapla", "hizi bul"),
        "analiz": ("serbest cisim diyagramini yorumla", "degisken degisirse ne olur",
                   "hangi kuvvet dengelenir"),
    },
    "Kimya": {
        "hatirlama": ("formulu nedir", "grup adini belirt"),
        "uygulama": ("mol hesapla", "denklestir", "derisimi bul", "pH hesapla"),
        "analiz": ("tepkime yonunu yorumla", "denge kayar mi"),
    },
    "Biyoloji": {
        "hatirlama": ("organel adi", "evre adi"),
        "uygulama": ("capraz yap", "oran hesapla", "fenotip bul"),
        "analiz": ("evreleri karsilastir", "dongude kesinti olursa",
                   "kalitim deseni cikar"),
    },
    "Turk Dili ve Edebiyati": {
        "hatirlama": ("donemi belirt", "yazari kimdir", "terimi tanimla"),
        "uygulama": ("noktalamayi uygula", "yazim kuralini uygula",
                     "olcuyu bul", "kafiyeyi goster"),
        "analiz": ("parcayi yorumla", "anlatici bakisini ayirt et",
                   "uslup farkini belirt"),
    },
    "Ingilizce": {
        "hatirlama": ("kelime anlami", "kurali belirt"),
        "uygulama": ("bosluk doldur", "dogru zamani sec", "cumleyi donustur"),
        "analiz": ("baglami yorumla", "ima edileni bul"),
    },
    "Tarih": {
        "hatirlama": ("tarihi belirt", "antlasma adi"),
        "uygulama": ("kronoloji kur", "haritada yerini bul"),
        "analiz": ("neden-sonuc iliskisi kur", "kaynaklari karsilastir"),
    },
    "Cografya": {
        "hatirlama": ("bolge adi", "iklim tipi"),
        "uygulama": ("yerel saat hesapla", "egim hesapla", "nufus yogunlugu bul"),
        "analiz": ("dagilisi yorumla", "grafigi okuyup cikarim yap"),
    },
    "Din Kulturu ve Ahlak Bilgisi": {
        "hatirlama": ("kavrami tanimla", "sure adi"),
        "uygulama": ("ilkeyi ornege uygula",),
        "analiz": ("ilkeler arasi iliskiyi yorumla",),
    },
}


BILISSEL_TALEP = Dimension(
    name="bilissel_talep",
    labels=("hatirlama", "uygulama", "analiz"),
    definition=(
        "Sorunun ogrenciden istedigi en ust bilissel islem. Bloom'un alti duzeyi "
        "uc duzeye indirgenmistir (bulgu 4: kategori sayisini azalt)."
    ),
    criteria={
        "hatirlama": (
            "Dogru cevap dogrudan ezber/bellek erisimiyle verilebilir. Hicbir "
            "donusum, hesap ya da karsilastirma gerekmez. Bilgi soruda hazir "
            "verilmemistir ama ogrencinin bildigi tek bir olguyu geri cagirmak "
            "yeterlidir."
        ),
        "uygulama": (
            "Bilinen bir kural, formul ya da yordam verilen bir duruma "
            "uygulanir. Hangi kuralin uygulanacagi acik ya da kolayca "
            "sezilir; asil is o kurali yurutmektir."
        ),
        "analiz": (
            "Ogrenci once hangi bilginin/iliskinin gerektigine KARAR vermeli, "
            "birden fazla bilgiyi karsilastirmali, ayirt etmeli ya da bir "
            "cikarim kurmalidir. 'Hangisi yanlistir', 'hangisi soylenemez', "
            "'nedeni asagidakilerden hangisidir' kaliplarini icerir."
        ),
    },
    boundaries=(
        "Formul soruda VERILMISSE ve yalnizca yerine koyuluyorsa 'uygulama'dir, "
        "'hatirlama' degil.",
        "Hesap iceriyor diye otomatik 'analiz' deme; tek formullu duz hesap "
        "'uygulama'dir.",
        "Olumsuz kok ('hangisi YANLISTIR') tek basina 'analiz' yapmaz; eger "
        "secenekler tek tek bilinen olgularla eslestiriliyorsa 'hatirlama' kalir.",
        "Ikiden fazla duzey akla geliyorsa EN UST duzeyi sec.",
    ),
    examples=(
        ("Mitoz bolunmede kromozom sayisi nasil degisir?", "hatirlama"),
        ("Delta<0 olan denklemin kok durumu hakkinda hangisi dogrudur?", "analiz"),
    ),
)


# --------------------------------------------------------------------------
# 2) adim_sayisi
# --------------------------------------------------------------------------

ADIM_SAYISI = Dimension(
    name="adim_sayisi",
    labels=("tek_adim", "cok_adim"),
    definition=(
        "Dogru cevaba ulasmak icin birbirine BAGLI kac ara sonuc uretilmesi "
        "gerektigi. Adim = bir onceki ciktinin girdi olarak kullanildigi islem."
    ),
    criteria={
        "tek_adim": (
            "Tek bir kural/formul/olgu dogrudan cevabi verir. Ara sonuc "
            "saklamaya gerek yoktur."
        ),
        "cok_adim": (
            "En az iki bagli islem vardir: birinin ciktisi digerinin girdisidir "
            "(orn. once diskriminant, sonra kokler; once mol, sonra kutle; once "
            "parcayi oku, sonra iki bilgiyi birlestir)."
        ),
    },
    boundaries=(
        "Secenekleri tek tek elemek 'cok_adim' SAYILMAZ — bu bir cozum zinciri "
        "degil, secim stratejisidir.",
        "Birim donusumu tek basina ayri bir adim sayilmaz; ancak donusum "
        "yapilmadan formul uygulanamiyorsa sayilir.",
        # OLCULDU: onceki surumde burada "kararsiz kalirsan tek_adim sec"
        # yaziyordu. Model bunu harfiyen uyguladi ve sinama kumesindeki 15
        # cok_adim maddesinin 11'ini tek_adim'a cekti; boyut dogrulugu %60'ta,
        # intra-alpha 0,684'te kaldi (kapiyi kapatan tek boyut buydu).
        # Beraberlik kurali kaldirildi: karar OLCUTE birakiliyor.
        "Beraberlik durumunda varsayilan bir etiket YOKTUR. Karari yukaridaki "
        "olcute gore ver: iki islem arasinda girdi-cikti bagi KURULABILIYORSA "
        "'cok_adim', kurulamiyorsa 'tek_adim'."
    ),
    experimental=True,
    downgrade_note=(
        "DENEYSEL — 2026-09-14'te uretim kumesinden CIKARILDI.\n"
        "\n"
        "NEDEN: `fixtures/probe_tr` (30 elle yazilmis, dort boyutta da tam "
        "dengeli madde) uzerinde iki kez olculdu ve iki kez de kapinin altinda "
        "kaldi:\n"
        "  * beraberlik kurali VARKEN : intra-alpha 0,684 / dogruluk %60,0 "
        "(15 cok_adim maddesinin 11'i tek_adim sayildi)\n"
        "  * beraberlik kurali YOKKEN : intra-alpha 0,607 / dogruluk %63,3 "
        "(15 cok_adim maddesinin 9'u tek_adim sayildi)\n"
        "Kurali kaldirmak dogrulugu 30 maddede tek bir madde oynatti (gurultu "
        "duzeyinde) ama KARARLILIGI DUSURDU. Yani eski kural gercek bir ayirim "
        "uretmiyor, YAPAY TUTARLILIK uretiyordu: model hep ayni yanlisi verdigi "
        "icin alpha yuksek cikiyordu. Kural kalkinca yapay tutarlilik gitti, "
        "dogruluk gelmedi.\n"
        "SONUC: sorun istemde ya da beraberlik kuralinda degil, BOYUTUN "
        "KENDISINDEDIR — 'birbirine bagli ara sonuc' olcutu bu model icin "
        "guvenilir bicimde isletilemiyor.\n"
        "\n"
        "DAYANAK: bulgu 4 zaten 'boyut sayisini 3-4'e indir, rubrik "
        "kalibrasyonu yap' diyor ve insan uzman taban cizgisinin de dusuk ve "
        "cok degiskken oldugunu gosteriyor (ham uyum ~%54). Uc saglam boyut, "
        "dorduncusu gurultu olan dortluden iyidir.\n"
        "\n"
        "GERI ALMA KOSULU: gercek soru bankasinda (sablon uretimi olmayan, "
        "dogal varyansli bir kume) yeniden olculdugunde intra-PSS alpha >= 0,70 "
        "cikarsa bu boyut uretim kumesine geri alinir. O zamana kadar etiket "
        "URETILMEYE DEVAM EDER ve ciktida gorunur; yalnizca kapiyi bloke etmez "
        "ve asagi akisa (ogrenci profili / tavsiye) girmez.\n"
        "\n"
        "2026-09-15 EK OLCUM — GERI ALINMADI, GEREKCESIYLE:\n"
        "Tohum verisi bilissel desen tasiyacak bicimde yeniden uretildikten "
        "sonra bu boyut o veride intra-alpha 0,845 / inter-alpha 0,850 verdi, "
        "yani kapiyi RAHATCA GECTI. Buna ragmen uretime ALINMADI.\n"
        "NEDEN: iki olcum celisiyor ve ZOR OLANI kaybediyor.\n"
        "  * `fixtures/probe_tr` (elle yazilmis, dogal dilli)      -> 0,607  KALDI\n"
        "  * yeniden uretilen tohum (sablonla uretilmis)           -> 0,845  GECTI\n"
        "Fark boyutun duzelmesinden degil, VERININ KOLAYLASMASINDAN geliyor: "
        "`content_tr.py::MULTISTEP_STEM_TEMPLATES` cok adimliligi koke ACIKCA "
        "yaziyor ('once ... sonra ...'), yani model cikarim yapmiyor, kalibi "
        "okuyor. Gercek ogretmen sorulari `probe_tr`'ye benzer, sablona degil.\n"
        "Kendi kolaylastirdigimiz sinavi gecmek, geri alma icin kanit sayilmaz. "
        "Geri alma kosulu yukarida yazildigi gibi kalir: olcum GERCEK soru "
        "bankasinda yapilmalidir."
    ),
)


# --------------------------------------------------------------------------
# 3) dikkat_tuzagi — BU VERIDE DIS DOGRULAMA HEDEFI OLAN TEK BOYUT
# --------------------------------------------------------------------------

DIKKAT_TUZAGI = Dimension(
    name="dikkat_tuzagi",
    labels=("var", "yok"),
    definition=(
        "Siklardan birinin, YAYGIN VE ADLANDIRILABILIR bir kavram yanilgisinin "
        "tam karsiligi olmasi. Bu yalnizca 'yanlis sik' demek DEGILDIR: sikkin "
        "kendisi ogrencinin kafasindaki hatali kurali soze dokmelidir."
    ),
    criteria={
        "var": (
            "Siklardan biri, dogru sikkin YAPISAL IKIZIDIR: ayni kavrami, ayni "
            "sozcuk kalibiyla, fakat kurali bozacak sekilde ifade eder "
            "(orn. dogru: '(a·b)^n = a^n·b^n' — tuzak: '(a+b)^n = a^n+b^n'). "
            "Tuzak sik, o konuda ogretmenlerin bildigi klasik yanilgidir."
        ),
        "yok": (
            "Celdiriciler yalnizca yanlis deger/ilgisiz ifade/rastgele "
            "sayidir; hicbiri adlandirilabilir bir yanilgiyi soze dokmez."
        ),
    },
    boundaries=(
        "Sayisal celdirici (yanlis islem sonucu, yakin sayi, isaret hatasi) TEK "
        "BASINA 'var' YAPMAZ — yanilgi SOZEL olarak ifade edilmis olmali.",
        "Iki sik birbirinin olumsuzu/ikizi gibi duruyorsa bu guclu bir 'var' "
        "isaretidir; hangisinin dogru oldugunu bilmen gerekmez.",
        "Yalnizca bir sikki isaretleyebilirsin. Birden fazla aday varsa dogru "
        "sikkin kaliben EN YAKIN ikizini sec.",
        "Emin degilsen 'yok' sec ve guveni dusur — bu boyutta yanlis pozitif, "
        "yanlis negatiften pahalidir (asagi akista ogrenciye yanilgi atfedilir).",
    ),
    examples=(
        ("Siklar: 'sin^2x + cos^2x = 1' / 'sin x + cos x = 1' / '(12, 5)' / "
         "'(7, -3)'", "var (ikinci sik klasik trigonometri yanilgisi)"),
        ("Siklar: '24' / '18' / '36' / '12'", "yok (yalnizca sayisal celdirici)"),
    ),
    externally_validated=True,
)


# --------------------------------------------------------------------------
# 4) okuma_yuku
# --------------------------------------------------------------------------

OKUMA_YUKU = Dimension(
    name="okuma_yuku",
    labels=("dusuk", "yuksek"),
    definition=(
        "Sorunun cozumune baslamadan once okunup ayiklanmasi gereken metin "
        "miktari ve dil karmasikligi."
    ),
    criteria={
        "dusuk": (
            "Kok tek cumle ya da kisa; siklar kisa; gereksiz baglam yok. "
            "Ogrenci ne istendigini ilk okumada anlar."
        ),
        "yuksek": (
            "Uzun kok/paragraf, ic ice cumle, birden fazla kosul ya da uzun "
            "sik metinleri; ilgili bilgiyi ayiklamak ayri bir istir."
        ),
    },
    boundaries=(
        "Uzunluk tek olcut degil: kisa ama ic ice sartli bir cumle 'yuksek' "
        "olabilir.",
        "Sik metinlerinin uzunlugu koke DAHILDIR.",
        "Alan terimlerinin cokluğu tek basina 'yuksek' yapmaz; cumle yapisi "
        "duzse 'dusuk' kalir.",
    ),
)


DIMENSION_ORDER: tuple[str, ...] = (
    "bilissel_talep", "adim_sayisi", "dikkat_tuzagi", "okuma_yuku",
)

DIMENSIONS: dict[str, Dimension] = {
    d.name: d for d in (BILISSEL_TALEP, ADIM_SAYISI, DIKKAT_TUZAGI, OKUMA_YUKU)
}

assert tuple(DIMENSIONS) == DIMENSION_ORDER, "Boyut sirasi sozluk ile uyusmuyor."

# --------------------------------------------------------------------------
# URETIM / DENEYSEL ayrimi
# --------------------------------------------------------------------------
# Dort boyutun HEPSI etiketlenir ve HEPSI raporlanir. Fark su:
#   URETIM   -> Asama 0 kapisi bunlara bakar; ogrenci profili bunlari kullanir.
#   DENEYSEL -> alpha'si hesaplanir ve ciktida `deneysel_boyutlar` altinda
#               AYRICA gosterilir, ama kapiyi BLOKE ETMEZ ve asagi akisa GIRMEZ.
#
# Bu bir basarisizligi gizleme degil, KAPSAMI DURUSTCE DARALTMA'dir: indirilen
# boyutun gerekcesi ve olcumu `Dimension.downgrade_note` icinde acikca durur ve
# her kosu raporuna basilir.

PRODUCTION_DIMENSIONS: tuple[str, ...] = tuple(
    d for d in DIMENSION_ORDER if not DIMENSIONS[d].experimental)
EXPERIMENTAL_DIMENSIONS: tuple[str, ...] = tuple(
    d for d in DIMENSION_ORDER if DIMENSIONS[d].experimental)

assert PRODUCTION_DIMENSIONS, "En az bir uretim boyutu kalmali."
assert set(PRODUCTION_DIMENSIONS) | set(EXPERIMENTAL_DIMENSIONS) == set(DIMENSION_ORDER)
assert all(DIMENSIONS[d].downgrade_note for d in EXPERIMENTAL_DIMENSIONS), \
    "Deneysel her boyut gerekcesini (downgrade_note) tasimak zorundadir."


def experimental_report() -> dict[str, str]:
    """Deneysel boyut -> indirilme gerekcesi. Kosu raporuna aynen basilir."""
    return {d: DIMENSIONS[d].downgrade_note for d in EXPERIMENTAL_DIMENSIONS}


def course_verbs(course_name: str | None) -> dict[str, tuple[str, ...]]:
    """Derse ozgu fiil listesi; ders bilinmiyorsa bos sozluk (bulgu 3)."""
    if not course_name:
        return {}
    return VERBS_BY_COURSE.get(course_name.strip(), {})


def render_rubric(dimension: str, *, with_examples: bool = True) -> str:
    """Tek boyutun yonergesini isteme gomulecek metne cevirir."""
    spec = DIMENSIONS[dimension]
    parts = [f"BOYUT: {spec.name}", f"Tanim: {spec.definition}",
             f"Izinli etiketler: {', '.join(spec.labels)}"]
    for label in spec.labels:
        parts.append(f"  - {label}: {spec.criteria[label]}")
    if spec.boundaries:
        parts.append("Sinir durumlari:")
        parts.extend(f"  * {b}" for b in spec.boundaries)
    if with_examples and spec.examples:
        parts.append("Ornekler:")
        parts.extend(f"  * {q} -> {a}" for q, a in spec.examples)
    return "\n".join(parts)


def render_verbs(course_name: str | None = None) -> str:
    """Duzeye ozgu (ve varsa derse ozgu) eylem fiili listesi — bulgu 3."""
    lines = ["EYLEM FIILLERI (bilissel_talep icin yon gostericidir, kural degil):"]
    extra = course_verbs(course_name)
    for level in BILISSEL_TALEP.labels:
        verbs = list(VERBS_BY_LEVEL[level])
        if level in extra:
            verbs += list(extra[level])
        lines.append(f"  {level}: {', '.join(verbs)}")
    if extra:
        lines.append(f"  (son gruptaki fiiller '{course_name}' dersine ozgudur)")
    return "\n".join(lines)


def render_full_rubric(course_name: str | None = None, *,
                       with_examples: bool = True) -> str:
    """Dort boyutun tam yonergesi + fiil listesi."""
    blocks = [render_rubric(name, with_examples=with_examples)
              for name in DIMENSION_ORDER]
    blocks.append(render_verbs(course_name))
    return "\n\n".join(blocks)
