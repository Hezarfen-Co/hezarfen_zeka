#!/usr/bin/env python3
"""SIR TARAMASI -- depoya sizmis API anahtari / parola arar.

Neden var? `.env` `.gitignore` icinde, ama bu YALNIZCA yeni dosyalari korur:
bir kez `git add -f` ile eklenmis ya da `.gitignore`'dan once islenmis bir
dosya izlenmeye devam eder. Ayrica sirlar `.env` disinda da sizar: bir
`compose.yaml`'a gomulmus varsayilan, bir README ornegi, bir teste
yapistirilmis gercek anahtar.

Bu tarayici SALT OKURDUR ve HICBIR ZAMAN bulunan degeri tam basmaz;
yalnizca dosya, satir ve kirpilmis bir parca gosterir -- yoksa CI kaydinin
KENDISI sir sizdiran yer olurdu.

Kullanim:
    python scripts/ci-sir-tara.py

Cikis kodu 0 = temiz, 1 = supheli bulgu var.
"""

from __future__ import annotations

import io
import re
import sys
from fnmatch import fnmatch
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent

# --- taranmayacak yerler ---------------------------------------------------
# Kendi desenlerimiz bu dosyada duruyor; kendimizi yakalamamaliyiz.
ATLANAN_DIZINLER = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "work",
}
ATLANAN_DOSYALAR = {"ci-sir-tara.py"}
# Metin olmayan uzantilar: ayristirmaya calismak gurultu uretir.
IKILI_UZANTILAR = {
    ".pyc", ".pyo", ".so", ".dll", ".exe", ".png", ".jpg", ".jpeg", ".gif",
    ".pdf", ".zip", ".gz", ".tar", ".whl", ".ico", ".woff", ".woff2",
}

# --- desenler --------------------------------------------------------------
# Her desen (ad, regex, aciklama) uclusudur. Aciklama CI ciktisinda gorunur
# ki bulguyu goren kisi ne yapacagini bilsin.
DESENLER: list[tuple[str, re.Pattern[str], str]] = [
    (
        "saglayici-anahtari",
        # `sk-` / `sk_` onekli anahtarlar (DeepSeek, OpenAI ve turevleri).
        # En az 16 govde karakteri arayarak "sk-" gecen duz metni elemek.
        re.compile(r"\bsk[-_][A-Za-z0-9_\-]{16,}"),
        "LLM saglayici anahtari gorunumlu dizge",
    ),
    (
        "gomulu-deger",
        # `ANAHTAR=deger` bicimi -- YALNIZCA YAPILANDIRMA DOSYALARINDA
        # (bkz. YAPILANDIRMA_UZANTILARI). Kaynak kodda `token=` gibi bir
        # parametre adi ya da Turkce duz metinde gecen "token" kelimesi
        # sir DEGILDIR; ilk surumde bu ayrim yoktu ve tarayici 50'den fazla
        # yanlis pozitif uretti. Bagiran bir denetim kapatilir, kapatilmis
        # denetim de yoktur -- bu yuzden kapsam dar tutuluyor.
        #
        # `${...}` interpolasyonu ve bos deger MUAF: compose.yaml'in DOGRU
        # deseni tam olarak budur.
        re.compile(
            r"""(?x)
            ^\s*(?:export\s+)?
            (DEEPSEEK_API_KEY|LLM_API_KEY|SEGMENT_API_KEY|AI_SHARED_TOKEN
             |ZEKA_DB_PASSWORD|ZEKA_PG_DSN
             |[A-Z0-9_]*(?:API_KEY|SECRET|PASSWORD|TOKEN))
            \s*[:=]\s*
            (?!\$)                 # ${VAR} interpolasyonu degil
            ["']?([^\s"'#]{12,})["']?\s*$
            """
        ),
        "yapilandirma dosyasina duz sir gomulmus (interpolasyon kullanin)",
    ),
    (
        "ozel-anahtar",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
        "ozel anahtar govdesi",
    ),
    (
        "aws-anahtari",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "AWS erisim anahtari kimligi",
    ),
]

YAPILANDIRMA_UZANTILARI = {
    ".env", ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".conf",
    ".sh", ".bash", ".properties",
}
"""`gomulu-deger` deseni YALNIZCA bu uzantilarda ve uzantisiz yapilandirma
adlarinda (Containerfile, Dockerfile, .env.*) aranir. Kaynak kodu ve veri
dosyalari disaridadir; oralarda `token=` bir sir degil, bir parametredir."""

YAPILANDIRMA_ADLARI = {"Containerfile", "Dockerfile", "Makefile"}


def yapilandirma_mi(yol: Path) -> bool:
    return (
        yol.suffix.lower() in YAPILANDIRMA_UZANTILARI
        or yol.name in YAPILANDIRMA_ADLARI
        or yol.name.startswith(".env")
    )


# --- yanlis pozitif muafiyetleri -------------------------------------------
# Belirgin yer tutucular. Bunlari eleyemezsek tarayici "bagirip duran" bir
# denetime doner ve insanlar onu kapatir -- kapatilmis bir denetim yoktur.
YER_TUTUCULAR = re.compile(
    r"(?i)(xxx+|yyy+|zzz+|placeholder|example|ornek|degistir|changeme|your[-_]?key"
    r"|sahte|dummy|fake|test[-_]?token|redacted|<[^>]+>|\.\.\.)"
)


def kirp(deger: str) -> str:
    """Bulgunun yalnizca tanimaya yetecek kadarini goster."""
    if len(deger) <= 8:
        return deger[:2] + "***"
    return f"{deger[:4]}***{deger[-2:]} ({len(deger)} karakter)"


def gitignore_kurallari() -> list[str]:
    dosya = KOK / ".gitignore"
    if not dosya.exists():
        return []
    return [
        s.strip()
        for s in io.open(dosya, encoding="utf-8").read().splitlines()
        if s.strip() and not s.strip().startswith("#")
    ]


def yoksayiliyor_mu(goreli: str, kurallar: list[str]) -> bool:
    """Yol `.gitignore` tarafindan korunuyor mu?

    NEDEN ONEMLI: yoksayilan bir dosya depoya GIRMEZ, dolayisiyla icindeki
    sir sizmis sayilmaz. Yerelde `.env` icinde gercek bir anahtar bulunmasi
    normaldir ve CI'yi kirmamalidir -- kirsaydi, gelistiricinin tek makul
    tepkisi taramayi kapatmak olurdu.

    Buna karsilik dosyanin yoksayildigini VARSAYMIYORUZ: asagida `.env`
    ailesinin gercekten `.gitignore` kapsaminda oldugu AYRICA denetlenir.
    Yoksayilmiyorsa buradan da gecmez ve icerigi taranir.
    """
    for kural in kurallar:
        temiz = kural.rstrip("/")
        if fnmatch(goreli, temiz) or fnmatch(goreli, temiz + "/*"):
            return True
        if any(fnmatch(parca, temiz) for parca in Path(goreli).parts):
            return True
    return False


def taranacak_dosyalar(kurallar: list[str]) -> list[Path]:
    bulunan: list[Path] = []
    for yol in KOK.rglob("*"):
        if not yol.is_file():
            continue
        if any(parca in ATLANAN_DIZINLER for parca in yol.parts):
            continue
        if yol.name in ATLANAN_DOSYALAR:
            continue
        if yol.suffix.lower() in IKILI_UZANTILAR:
            continue
        if yoksayiliyor_mu(yol.relative_to(KOK).as_posix(), kurallar):
            continue
        bulunan.append(yol)
    return sorted(bulunan)


def main() -> int:
    print("ZEKA sir taramasi", flush=True)
    print(f"depo: {KOK}", flush=True)

    bulgular: list[str] = []
    uyarilar: list[str] = []
    kurallar = gitignore_kurallari()
    dosyalar = taranacak_dosyalar(kurallar)

    for yol in dosyalar:
        try:
            metin = io.open(yol, encoding="utf-8", errors="strict").read()
        except (UnicodeDecodeError, OSError):
            # Metin degil ya da okunamiyor: ikili sayip geciyoruz.
            continue
        goreli = yol.relative_to(KOK).as_posix()
        for satir_no, satir in enumerate(metin.splitlines(), start=1):
            for ad, desen, aciklama in DESENLER:
                # `gomulu-deger` yalnizca yapilandirma dosyalarinda anlamli.
                if ad == "gomulu-deger" and not yapilandirma_mi(yol):
                    continue
                eslesme = desen.search(satir)
                if not eslesme:
                    continue
                ham = eslesme.group(0)
                if YER_TUTUCULAR.search(ham):
                    continue
                bulgular.append(f"{goreli}:{satir_no} [{ad}] {aciklama} -- {kirp(ham)}")

    # --- .env hijyeni -------------------------------------------------------
    # Dosyanin VARLIGI sorun degil (yerel gelistirme icin normaldir);
    # `.gitignore` disinda kalmasi sorundur.
    # --- .env hijyeni -------------------------------------------------------
    # Dosyanin VARLIGI sorun degil (yerel gelistirme icin normaldir);
    # `.gitignore` disinda kalmasi sorundur. Yukaridaki tarama yoksayilan
    # dosyalari atladigi icin bu denetim o atlamanin MESRULUGUNU dogrular:
    # korumasi olmayan bir `.env` hem burada rapor edilir hem de icerigi
    # taranmis olur.
    env_sayisi = 0
    for env_dosyasi in KOK.rglob(".env*"):
        if not env_dosyasi.is_file():
            continue
        if any(parca in ATLANAN_DIZINLER for parca in env_dosyasi.parts):
            continue
        goreli = env_dosyasi.relative_to(KOK).as_posix()
        # `.env.example` / `.env.sample` SABLONDUR ve commit EDILMELIDIR:
        # degeri degil, anahtar adini ve aciklamasini tasir. Bunlari
        # "gitignore'da yok" diye isaretlemek, backend ekibine verilecek tek
        # yapilandirma rehberini depodan cikarmaya zorlardi.
        #
        # Muaf degil, YOLU DEGISTI: icerigi asagidaki normal sir taramasindan
        # gecer. Yani sablona yanlislikla gercek bir anahtar yazilirsa yine
        # yakalanir -- yalnizca "dosya ignore'lu mu" kurali atlanir.
        if env_dosyasi.name.endswith((".example", ".sample", ".template")):
            print(f"  [ok]   {goreli} sablon (icerigi taraniyor)", flush=True)
            continue
        env_sayisi += 1
        if yoksayiliyor_mu(goreli, kurallar):
            print(f"  [ok]   {goreli} .gitignore ile korunuyor (icerigi taranmadi)", flush=True)
        else:
            bulgular.append(
                f"{goreli} [env-hijyeni] ortam dosyasi .gitignore'da YOK -- "
                "islenirse sir depoya girer"
            )
    if env_sayisi == 0:
        print("  [ok]   depoda .env dosyasi yok", flush=True)

    # --- compose sirlarinin bicimi ------------------------------------------
    # Zorunlu sirlar `${VAR:?...}` ile gelmeli; duz deger ya da `:-varsayilan`
    # bir sirri dosyaya gomer.
    #
    # LISTE compose.yaml'DAN OKUNUR: `ZEKA_PG_DSN` ucuncu sir olarak
    # eklendiginde burasi ve `scripts/ci-compose.sh` iki sirla kalmisti.
    # DSN bir parola tasir -- duz deger yazilabilseydi sir dosyaya girerdi.
    compose = KOK / "service" / "compose.yaml"
    if compose.exists():
        icerik = io.open(compose, encoding="utf-8").read()
        for degisken in ("AI_SHARED_TOKEN", "LLM_API_KEY", "ZEKA_PG_DSN"):
            satirlar = [s for s in icerik.splitlines() if s.strip().startswith(degisken + ":")]
            if not satirlar:
                uyarilar.append(f"compose.yaml icinde {degisken} tanimli degil")
            elif f"${{{degisken}:?" not in satirlar[0]:
                bulgular.append(
                    f"service/compose.yaml [compose-sir] {degisken} `${{{degisken}:?...}}` "
                    "bicimiyle ZORUNLU kilinmamis"
                )
            else:
                print(f"  [ok]   compose.yaml: {degisken} zorunlu ve interpolasyonlu", flush=True)

    print(f"  [ok]   {len(dosyalar)} dosya tarandi", flush=True)

    print("\n" + "=" * 62, flush=True)
    for u in uyarilar:
        print(f"  [uyari] {u}", flush=True)
    if bulgular:
        print(f"\nSIR TARAMASI BASARISIZ -- {len(bulgular)} supheli bulgu:", flush=True)
        for b in bulgular:
            print(f"  - {b}", flush=True)
        print(
            "\nBulgu gercek bir sir ise: anahtari DERHAL iptal edin, gecmisten "
            "temizleyin ve degeri ortam degiskenine tasiyin.\n"
            "Yanlis pozitif ise: yer tutucuyu belirgin yapin (ornegin 'ornek-anahtar') "
            "ya da scripts/ci-sir-tara.py icindeki YER_TUTUCULAR desenini genisletin.",
            flush=True,
        )
        return 1
    print("SIR TARAMASI GECTI -- sizmis anahtar bulunamadi.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
