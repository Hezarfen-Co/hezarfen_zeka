#!/usr/bin/env python3
"""Konteyner saglik kontrolu -- KASITLI OLARAK COK HAFIF.

--- NEDEN BU KADAR AZ IS YAPIYOR ---
Bu filoda yapilan denetimde bir servisin saglik kontrolunun her 30 saniyede
BUTUN hatti (`import pipeline`) yeniden yukledigi bulundu: her kontrol onlarca
megabayt ayirip CPU yakiyordu ve agir yuk altinda kontrolun KENDISI servisi
zaman asimina dusuruyordu. Buradaki kontrol hicbir proje modulunu import etmez;
yalnizca `os` ve `sys` kullanir ve `/proc` altinda birkac kucuk dosya okur.
Tipik maliyeti bir kac milisaniyedir.

--- NE KANITLAR ---
Kopru surecinin (`python -m src.bridge`) hala YASADIGINI ve zombi
olmadigini. Yani: surec cokmedi, `exit` etmedi, ve init tarafindan
toplanmayi bekleyen bir ceset degil.

--- NE KANITLAMAZ (durustce) ---
Backend'e KAYITLI oldugunu kanitlamaz. Bu bilincli bir karardir:
`bridge.py` backend'e ulasamadiginda CIKMAZ, ustel geri cekilmeyle yeniden
dener (bkz. `run_forever` docstring'i). Bu DOGRU davranistir -- backend
bakimdayken ZEKA'nin bekliyor olmasi bir ariza degildir. Eger saglik
kontrolu "backend'e bagli" sartini arasaydi, backend'in her yeniden
dagitimi ZEKA'yi `unhealthy` isaretler ve restart politikasi gereksiz
yere sureci oldururdu -- tam da kacinmaya calistigimiz crash-loop.

Hazir olma (readiness) sinyali icin koprunun kendi durumunu bir yere
yazmasi gerekir; bu `src/` icinde bir degisiklik ister ve bu is kapsaminda
DEGILDIR. `docs/DAGITIM.md` "Kanitlanmayanlar" bolumunde ayrica yazilidir.
"""

from __future__ import annotations

import os
import sys

BEKLENEN = "src.bridge"
"""Kopru surecinin komut satirinda gecmesi gereken imza."""


def kopru_surecleri() -> list[int]:
    """`/proc` altinda komut satiri `src.bridge` iceren PID'leri dondur."""
    bulunan: list[int] = []
    for giris in os.listdir("/proc"):
        if not giris.isdigit():
            continue
        try:
            with open(f"/proc/{giris}/cmdline", "rb") as dosya:
                # cmdline argumanlari NUL ile ayirir; bosluga cevirip ariyoruz.
                komut = dosya.read().replace(b"\0", b" ").decode("utf-8", "replace")
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            # Surec tam biz okurken oldu ya da bize ait degil: bu bir hata
            # degil, yarista kaybettik. Digerlerine bakmaya devam.
            continue
        if BEKLENEN in komut:
            bulunan.append(int(giris))
    return bulunan


def zombi_mi(pid: int) -> bool:
    """`/proc/<pid>/stat` uzerinden surecin zombi (Z) olup olmadigini soyle.

    Zombi bir surec `/proc` altinda hala gorunur ama COKMUSTUR; yalnizca
    varligina bakan bir kontrol bunu saglikli sanir. `init: true` ile
    zombiler hizlica toplanir, yine de acikta birakmiyoruz.
    """
    try:
        with open(f"/proc/{pid}/stat", "rb") as dosya:
            ham = dosya.read().decode("utf-8", "replace")
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return True
    # stat bicimi: "PID (komut adi) DURUM ...". Komut adi bosluk ve parantez
    # icerebilir, bu yuzden SON ')' karakterinden sonrasini ayristiriyoruz.
    kapanis = ham.rfind(")")
    if kapanis < 0:
        return True
    alanlar = ham[kapanis + 1 :].split()
    return bool(alanlar) and alanlar[0] == "Z"


def main() -> int:
    if not os.path.isdir("/proc"):
        # Bu kontrol Linux konteyneri icin yazildi. /proc yoksa yanlis yerde
        # kosuyoruz demektir; "saglikli" demek yerine acikca basarisiz ol.
        print("saglik: /proc yok, bu kontrol Linux konteyneri icindir", flush=True)
        return 1

    pidler = [pid for pid in kopru_surecleri() if not zombi_mi(pid)]
    if not pidler:
        print(f"saglik: BASARISIZ -- '{BEKLENEN}' sureci yasamiyor", flush=True)
        return 1
    print(f"saglik: TAMAM -- kopru yasiyor (pid {', '.join(map(str, pidler))})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
