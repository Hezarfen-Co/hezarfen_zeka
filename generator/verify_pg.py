"""`pg_dogrula.sql` — yuklenmis tohumun butunluk sinavini URETIR.

`tools/verify_pg_seed.sql` sablonundaki `-- @ROZET_KATALOGU@` isareti, burada
`config.BADGES`'ten uretilen bir katalog tablosuyla degistirilir.

Neden uretiliyor da elle yazilmiyor: ilk denemede rozet deseni elle yazilmisti
ve YANLISTI — onek `pomodoro_focus_hours` saniliyordu, oysa `pomodoro_focus_ms`
ve esik milisaniye cinsinden. Sinav 450 sahte ihlal bildirdi. Katalog tek bir
yerde (`config.BADGES`) tanimli; iki kez yazilan her sey er ya da gec ayrisir.
"""

from __future__ import annotations

import os

import config as C

MARKER = "-- @ROZET_KATALOGU@"


def _catalog_sql() -> str:
    rows = ",\n    ".join(
        "('%s', '%s', %d)" % (name, counter, threshold)
        for name, counter, threshold in C.BADGES
    )
    counters = sorted({counter for _n, counter, _t in C.BADGES})
    unpivot = "\n    UNION ALL ".join(
        "SELECT id AS app_user, '%s' AS sayac, %s AS deger FROM app_user" % (c, c)
        for c in counters
    )
    return """-- Rozet katalogu — `generator/config.BADGES`'ten URETILDI (%d rozet).
-- Elle duzenlemeyin: kaynagi config.py'dir.
CREATE TEMP TABLE rozet_katalog (rozet text PRIMARY KEY, sayac text, esik bigint);
INSERT INTO rozet_katalog VALUES
    %s;

-- Kullanici sayaclari uzun bicimde: rozet katalogu sayaci ADIYLA taniyor,
-- yani her rozet icin ayri bir CASE dali yazmak gerekmiyor. Yeni bir rozet
-- turu eklenirse bu sorgu degismeden calisir.
CREATE TEMP TABLE kullanici_sayac AS
    %s;
CREATE INDEX ON kullanici_sayac (app_user, sayac);

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I21', 'badge_award.badge katalog disi', count(*)
  FROM badge_award WHERE badge NOT IN (SELECT rozet FROM rozet_katalog);

INSERT INTO sonuc (kod, baslik, ihlal)
SELECT 'I22', 'rozet var ama ilgili sayac esigin altinda', count(*)
  FROM badge_award b
  JOIN rozet_katalog k ON k.rozet = b.badge
  LEFT JOIN kullanici_sayac s ON s.app_user = b.app_user AND s.sayac = k.sayac
 WHERE s.deger IS NULL OR s.deger < k.esik;""" % (len(C.BADGES), rows, unpivot)


def write(template_path: str, out_path: str) -> int:
    with open(template_path, encoding="utf-8") as fh:
        text = fh.read()
    if MARKER not in text:
        raise RuntimeError("sablonda %s isareti yok: %s" % (MARKER, template_path))
    text = text.replace(MARKER, _catalog_sql())
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return os.path.getsize(out_path)
