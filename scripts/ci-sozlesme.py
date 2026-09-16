#!/usr/bin/env python3
"""SOZLESME DENETIMI -- iki sessiz kusur sinifini yakalar.

Bu betik neden var? Testler yesilken de kirilabilen IKI sozlesme var ve
ikisi de bu tur projelerde gercekten sessizce kirilir:

  (1) MODEL ADI <-> FIYAT TABLOSU
      `src/segment/provider.py` icindeki `cost_usd()` bilinmeyen bir model
      adi gorunce HATA VERMEZ; sessizce tablodaki EN PAHALI tarifeye duser
      (provider.py:124-125). Yani bir model adi degisirse bir sey patlamaz,
      yalnizca butce raporu yanlis cikar. Ayrica dosya basindaki `assert`
      `python -O` ile kapanir, ona guvenilemez.

  (2) YOL IZIN LISTESI <-> BACKEND
      `src/protocol.py:AI_API_ALLOWLIST`, backend'in
      `src/constant.rs:656-676` listesinin elle tutulan bir kopyasidir.
      Backend'de bir yol eklenip burada eklenmezse cagri `path_not_allowed`
      ile TELE CIKMADAN reddedilir: ZEKA veriyi goremez ama hicbir test
      kirilmaz, cunku testler de ayni kopyayi dogrular.

Betik SALT OKURDUR; hicbir dosyayi degistirmez.

Kullanim:
    python scripts/ci-sozlesme.py
    HEZARFEN_BACKEND=/yol/hezarfen_backend-main python scripts/ci-sozlesme.py

Cikis kodu 0 = butun sozlesmeler saglam, 1 = en az bir sapma.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import os
import re
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
SERVIS = KOK / "service"

_hatalar: list[str] = []
_notlar: list[str] = []


def hata(mesaj: str) -> None:
    _hatalar.append(mesaj)
    print(f"  [HATA] {mesaj}", flush=True)


def tamam(mesaj: str) -> None:
    print(f"  [ok]   {mesaj}", flush=True)


def notu(mesaj: str) -> None:
    _notlar.append(mesaj)
    print(f"  [not]  {mesaj}", flush=True)


def baslik(mesaj: str) -> None:
    print(f"\n--- {mesaj} ---", flush=True)


def modul_yukle(nokta_yolu: str):
    """Servis modulunu PAKET olarak yukle (`src.segment.provider` gibi).

    `src/` icine hicbir sey yazmadan gercek nesneleri okumak icin: string
    ayristirmak yerine Python'un kendi degerlerini kullaniyoruz, boylece
    bir fiyat satiri hesaplanarak uretilse bile dogru sonucu goruruz.

    Dosyayi dogrudan yol vererek yuklemek ISE YARAMAZ: modullerin ici
    goreli import kullanir (`from .protocol import ...`) ve paket baglami
    olmadan `ImportError` alinir. Bu yuzden `service/` dizinini `sys.path`
    basina koyup normal import mekanizmasini kullaniyoruz -- testlerin
    (`python -m unittest discover -t .`) kullandigi baglamin aynisi.
    """
    if str(SERVIS) not in sys.path:
        sys.path.insert(0, str(SERVIS))
    return importlib.import_module(nokta_yolu)


# ===========================================================================
# SOZLESME 1: model adlari fiyat tablosunda var mi?
# ===========================================================================

OLU_MODELLER = ("deepseek-chat", "deepseek-reasoner", "deepseek-v4-flash")
"""Bir zamanlar kullanilan, ARTIK GECERSIZ model adlari. Bunlardan biri
geri sizarsa `cost_usd()` sessizce en pahali tarifeye duser."""


def sozlesme_model() -> None:
    baslik("SOZLESME 1: model adi <-> fiyat tablosu")
    try:
        provider = modul_yukle("src.segment.provider")
        seg_config = modul_yukle("src.segment.config")
    except Exception as exc:
        hata(f"segment modulleri yuklenemedi: {exc!r}")
        return

    try:
        pricing = provider.PRICING
        live = tuple(provider.LIVE_MODELS)
        aliases = provider.MODEL_ALIASES
        varsayilan = seg_config.DEFAULT_MODEL_IDS
    except AttributeError as exc:
        hata(
            f"beklenen sabit bulunamadi ({exc}); provider.py/config.py yeniden "
            "adlandirildiysa bu betik de guncellenmeli"
        )
        return

    # (a) Uctaki her canli model bir fiyat satirina sahip olmali.
    for model in live:
        anahtar = aliases.get(model, model)
        if anahtar not in pricing:
            hata(
                f"LIVE_MODELS icindeki '{model}' (takma ad cozumu: '{anahtar}') "
                "PRICING tablosunda YOK -- cost_usd() sessizce en pahali tarifeye duser"
            )
        else:
            tamam(f"LIVE_MODELS '{model}' -> PRICING['{anahtar}'] mevcut")

    # (b) config.py'nin rol -> model esleminde gecen her model de fiyatlanmali.
    #     Aranan sessiz kusur tam budur: rol tablosu bir model adina isaret
    #     ederken fiyat tablosu eski adi tasiyabilir.
    for rol, model in sorted(varsayilan.items()):
        anahtar = aliases.get(model, model)
        if anahtar not in pricing:
            hata(
                f"DEFAULT_MODEL_IDS['{rol}'] = '{model}' PRICING'de YOK "
                "-- butce hesabi yanlis cikar ve hicbir sey patlamaz"
            )
        elif model not in live and model != "mock":
            hata(
                f"DEFAULT_MODEL_IDS['{rol}'] = '{model}' LIVE_MODELS icinde degil "
                "-- uretimde secilemeyecek bir model varsayilan yapilmis"
            )
        else:
            tamam(f"DEFAULT_MODEL_IDS['{rol}'] = '{model}' fiyatli ve canli")

    # (c) Fiyat satirlarinin bicimi. Eksik bir alan KeyError ile uctaki
    #     hesabi kirar; burada ucuza yakalanir.
    for model, satir in sorted(pricing.items()):
        eksik = [alan for alan in ("in_hit", "in_miss", "out") if alan not in satir]
        if eksik:
            hata(f"PRICING['{model}'] su alanlari tasimiyor: {', '.join(eksik)}")

    # (d) Olu adlar geri sizmis mi?
    her_yerde = set(pricing) | set(aliases) | set(aliases.values()) | set(varsayilan.values())
    sizan = [olu for olu in OLU_MODELLER if olu in her_yerde]
    for olu in sizan:
        hata(f"GECERSIZ model adi '{olu}' yapilandirmaya geri sizmis")
    if not sizan:
        tamam(f"olu model adlari ({', '.join(OLU_MODELLER)}) hicbir tabloda yok")

    # (e) Fiyat tablosunun kendisi dogrulanmis mi? Bu bir HATA degil, NOT.
    #     Fiyatlar upstream'de degisir; CI bunu bilemez ama unutturmamali.
    if getattr(provider, "PRICING_VERIFIED", True) is False:
        notu(
            f"PRICING_VERIFIED=False -- fiyatlar {getattr(provider, 'PRICING_UPDATED', '?')} "
            f"tarihli ve elle dogrulanmamis (kaynak: {getattr(provider, 'PRICING_SOURCE', '?')})"
        )


# ===========================================================================
# SOZLESME 2: source.py yollari <-> backend izin listesi
# ===========================================================================


def _cagri_yollari(dosya: Path) -> list[tuple[int, str]]:
    """`source.py` icinde TELE CIKAN yol ifadelerini AST ile topla.

    Neden AST? `_TEMPLATES` sozlugu yalnizca BEYANDIR; gercek istekler
    cagri yerlerindeki ayri f-string'lerden kurulur (source.py:315, 350,
    403, 441, 476 ...). Beyani dogrulamak yetmez; ikisi ayrisabilir ve
    ayrismasi tam olarak sessiz kusurun kendisidir.

    f-string delikleri tek bir segmentlik somut bir degere (`X`) cevrilir;
    boylece sonuc `path_allowed()` ile gercek bir yol gibi sinanabilir.
    """
    agac = ast.parse(io.open(dosya, encoding="utf-8").read())

    # Bir f-string'in ICINDEKI sabit parcalar ayrica sayilmamali; yoksa
    # "/users/" gibi yarim parcalar yol sanilir.
    fstring_icindekiler: set[int] = set()
    for dugum in ast.walk(agac):
        if isinstance(dugum, ast.JoinedStr):
            for alt in ast.walk(dugum):
                if isinstance(alt, ast.Constant):
                    fstring_icindekiler.add(id(alt))

    bulunan: list[tuple[int, str]] = []
    for dugum in ast.walk(agac):
        if isinstance(dugum, ast.JoinedStr):
            parca = "".join(
                p.value if isinstance(p, ast.Constant) and isinstance(p.value, str) else "X"
                for p in dugum.values
            )
            if parca.startswith("/"):
                bulunan.append((dugum.lineno, parca))
        elif isinstance(dugum, ast.Constant) and isinstance(dugum.value, str):
            if id(dugum) in fstring_icindekiler:
                continue
            deger = dugum.value
            # Tek "/" bir yol degil, birlestirme ayracidir.
            if deger.startswith("/") and len(deger) > 1 and "\n" not in deger:
                bulunan.append((dugum.lineno, deger))
    return bulunan


def sozlesme_yol() -> None:
    baslik("SOZLESME 2: source.py yollari <-> AI_API_ALLOWLIST")
    try:
        protocol = modul_yukle("src.protocol")
    except Exception as exc:
        hata(f"protocol.py yuklenemedi: {exc!r}")
        return

    izinli = tuple(protocol.AI_API_ALLOWLIST)
    path_allowed = protocol.path_allowed

    # (a) Her cagri yeri izin listesine uymali.
    yollar = _cagri_yollari(SERVIS / "src" / "source.py")
    if not yollar:
        hata("source.py icinde hicbir yol ifadesi bulunamadi -- betik kor kalmis olabilir")
    sapan = 0
    for satir, yol in yollar:
        if not path_allowed(yol):
            hata(
                f"source.py:{satir} '{yol}' yolunu uretiyor ama bu yol "
                "AI_API_ALLOWLIST'te YOK -- cagri path_not_allowed ile reddedilir"
            )
            sapan += 1
    if sapan == 0:
        tamam(f"source.py icindeki {len(yollar)} yol ifadesinin tamami izin listesinde")

    # (b) `source.py` ACILISTA kendi yol defterini izin listesine karsi
    #     dogruluyor (source.py:120-127 -> RuntimeError). Modulu import
    #     etmek bu guvenligi de kosturur; sessizce atlamak yerine acikca
    #     cagiriyoruz ki CI ciktisinda gorunsun.
    try:
        modul_yukle("src.source")
        tamam("source.py acilis guvenligi (yol defteri <-> izin listesi) gecti")
    except RuntimeError as exc:
        hata(f"source.py acilis guvenligi BASARISIZ: {exc}")

    # (c) Depo icindeki PINLI kopya (tests/test_protocol.py:BACKEND_SNAPSHOT)
    #     ile karsilastir. Bu, protocol.py degisip testin unutuldugu
    #     durumu yakalar.
    anlik = _test_anlik_goruntusu()
    if anlik is None:
        notu("tests/test_protocol.py icinde BACKEND_SNAPSHOT bulunamadi; bu denetim atlandi")
    elif tuple(anlik) != izinli:
        hata(
            "protocol.py:AI_API_ALLOWLIST ile tests/test_protocol.py:BACKEND_SNAPSHOT "
            f"ayristi (yalniz protokolde: {sorted(set(izinli) - set(anlik))}; "
            f"yalniz anlik goruntude: {sorted(set(anlik) - set(izinli))})"
        )
    else:
        tamam(f"AI_API_ALLOWLIST ({len(izinli)} yol) depo ici anlik goruntuyle ayni")

    # (d) GERCEK backend ile karsilastir -- yalnizca checkout varsa.
    #     GitHub kosucusunda backend deposu YOKTUR; bu yuzden bulunamamasi
    #     hata degil nottur. Yerelde ise gercek dogrulama budur.
    backend = _backend_yolu()
    if backend is None:
        notu(
            "backend deposu bulunamadi -- gercek constant.rs karsilastirmasi ATLANDI. "
            "Yerelde kosturmak icin: HEZARFEN_BACKEND=/yol/hezarfen_backend-main"
        )
        return
    gercek = _backend_izin_listesi(backend)
    if gercek is None:
        hata(f"{backend} icinde AI_API_ALLOWLIST ayristirilamadi")
        return
    if tuple(gercek) != izinli:
        hata(
            f"IZIN LISTESI SAPMASI -- backend ({backend}) ile protocol.py ayri: "
            f"yalniz backend'de: {sorted(set(gercek) - set(izinli))}; "
            f"yalniz ZEKA'da: {sorted(set(izinli) - set(gercek))}"
        )
    else:
        tamam(f"AI_API_ALLOWLIST ({len(gercek)} yol) GERCEK backend constant.rs ile ayni")


def _test_anlik_goruntusu() -> list[str] | None:
    dosya = SERVIS / "tests" / "test_protocol.py"
    if not dosya.exists():
        return None
    metin = io.open(dosya, encoding="utf-8").read()
    eslesme = re.search(r"BACKEND_SNAPSHOT\s*(?::[^=]+)?=\s*\((.*?)\)", metin, re.S)
    if not eslesme:
        return None
    return re.findall(r'"([^"]+)"', eslesme.group(1))


def _backend_yolu() -> Path | None:
    aday = os.environ.get("HEZARFEN_BACKEND")
    adaylar = [Path(aday)] if aday else []
    # Kardes dizin: filo tek bir calisma alaninda yan yana duruyor.
    adaylar.append(KOK.parent / "hezarfen_backend-main")
    for yol in adaylar:
        if (yol / "src" / "constant.rs").exists():
            return yol
    return None


def _backend_izin_listesi(backend: Path) -> list[str] | None:
    """`constant.rs` icindeki `AI_API_ALLOWLIST` dizisini ayristir.

    Rust'i ayristirmiyoruz; yalnizca sabitin govdesindeki string
    literallerini aliyoruz. Yorum satirlari once atilir ki yorumdaki bir
    ornek yol listeye karismasin.
    """
    metin = io.open(backend / "src" / "constant.rs", encoding="utf-8").read()
    eslesme = re.search(r"AI_API_ALLOWLIST[^=]*=\s*&\[(.*?)\];", metin, re.S)
    if not eslesme:
        return None
    govde = re.sub(r"//[^\n]*", "", eslesme.group(1))
    return re.findall(r'"([^"]+)"', govde)


# ===========================================================================


def main() -> int:
    print("ZEKA sozlesme denetimi", flush=True)
    print(f"depo: {KOK}", flush=True)
    sozlesme_model()
    sozlesme_yol()

    print("\n" + "=" * 62, flush=True)
    if _notlar:
        print(f"{len(_notlar)} not (hata degil):", flush=True)
        for n in _notlar:
            print(f"  - {n}", flush=True)
    if _hatalar:
        print(f"\nSOZLESME DENETIMI BASARISIZ -- {len(_hatalar)} sapma:", flush=True)
        for h in _hatalar:
            print(f"  - {h}", flush=True)
        return 1
    print("SOZLESME DENETIMI GECTI -- butun sozlesmeler saglam.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
