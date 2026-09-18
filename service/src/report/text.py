"""Rapor metni: Türkçe etiketler, sayı biçimi, güven ibaresi, karşıtlık cümlesi.

Üç kural burada tek yerde uygulanır:

* **Güven düşükse sayı tek başına gösterilmez.** `confidence = none` olan bir
  ölçü "yeterli veri yok" ibaresiyle döner ve sayısal değeri `None`'dır
  (`CIKTI-SOZLESMESI.md` §5, `MODULLER.md` §0 kural 3). `exploratory` kademe
  sayıyı gösterir ama yanına **"ön bulgu"** yazar.
* **Segment sonucu karşıtlık olarak anlatılır.** Ham `accuracy` bir ayrım
  ölçüsü değildir: iyi öğrenci her segmentte yüksek çıkar. Rapor yalnız
  `contrast` cümlesi kurar (§2.5).
* **"zayıf" kelimesi yoktur.** `Band.REVIEW` karşılığı "tekrar önerilir"dir
  (`compute/model.py` başı, `[T§3 Ö1]`).
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from ..compute import clock

#: Düşük güvende sayının yerine geçen ibare.
LOW_CONFIDENCE_TEXT = "yeterli veri yok"

#: Ön bulgu kademesinin eki.
EXPLORATORY_SUFFIX = "ön bulgu"

#: Şube kimliğinin ADI bilinmediğinde gösterilen etiket. Ham kimlik ASLA
#: yazılmaz: canlı raporda yöneticiye `01a0b1a6-…` gitti ve okunamadı
#: (2026-09-18). Ad haritası payload'da gelir (`insight.report.classes`);
#: gelmezse etiket budur — uydurulmuş bir ad değil.
CLASS_LABEL_UNKNOWN = "Adı bilinmeyen şube"

#: Sayı gösterilmeyen güven kademeleri.
LOW_CONFIDENCE = frozenset({"none", "", "None"})

BAND_LABELS = {
    "review": "tekrar önerilir",
    "on_track": "sınıf düzeyinde",
    "strong": "güçlü",
    "insufficient_data": LOW_CONFIDENCE_TEXT,
}

CONFIDENCE_LABELS = {
    "none": LOW_CONFIDENCE_TEXT,
    "exploratory": "ön bulgu",
    "stable": "kararlı",
}

DIMENSION_LABELS = {
    "bilissel_talep": "Bilişsel talep",
    "dikkat_tuzagi": "Dikkat tuzağı",
    "okuma_yuku": "Okuma yükü",
    "adim_sayisi": "Adım sayısı (deneysel)",
}

LABEL_LABELS = {
    "hatirlama": "hatırlama",
    "uygulama": "uygulama",
    "analiz": "analiz",
    "var": "tuzak var",
    "yok": "tuzak yok",
    "dusuk": "düşük",
    "yuksek": "yüksek",
    "tek_adim": "tek adım",
    "cok_adim": "çok adım",
}

TRIGGER_LABELS = {
    "attendance": "Derse katılım",
    "homework": "Ödev teslimi",
    "mark_trend": "Not eğilimi",
    "exam_missed": "Sınav kaçırma",
}

RULE_LABELS = {
    "O1.review_band": "Bu derste tekrar önerilir",
    "O2.segment_cognitive_gap": "Bu tür sorularda kendi genel düzeyinin gerisindesin",
    "O2.segment_trap_prone": "Dikkat tuzağı taşıyan sorularda kayıp var",
    "O3.pattern": "Çalışma düzenin",
    "O4.deadline": "Yaklaşan teslim",
    "T3.class_gap": "Sınıf düzeyinde boşluk",
    "T3.individual_gap": "Bireysel destek önerisi",
    "T3.segment_class_gap": "Sınıf bu bilişsel segmentte geride",
    "T4.attendance": "Dikkat: derse katılım",
    "T4.homework": "Dikkat: ödev teslimi",
    "T4.mark_trend": "Dikkat: not eğilimi",
}


def num(value: Any, digits: int = 1) -> str:
    """Türkçe ondalık ayracıyla sayı. `None` → boş metin."""
    if value is None:
        return ""
    try:
        text = f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)
    return text.replace(".", ",")


def signed(value: Any, digits: int = 3) -> str:
    """İşaretli sayı — karşıtlık gibi yönü anlamlı ölçüler için."""
    if value is None:
        return ""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    return ("+" if f > 0 else "−" if f < 0 else "") + num(abs(f), digits)


def date_tr(ms: Any) -> str:
    """`unix ms` → `GG.AA.YYYY` (TR günü)."""
    if ms is None:
        return ""
    try:
        stamp = int(ms)
    except (TypeError, ValueError):
        return ""
    local = _dt.datetime.fromtimestamp(
        (stamp + clock.TR_OFFSET_MS) / 1000.0, tz=_dt.UTC
    )
    return local.strftime("%d.%m.%Y")


def date_key(ms: int) -> str:
    """Dosya adlarında kullanılan `YYYY-MM-DD` (TR günü)."""
    return clock.tr_date_key(int(ms))


def measure(value: Any, confidence: Any, *, digits: int = 1, unit: str = "") -> dict:
    """Bir ölçüyü **güven kademesiyle birlikte** paketler.

    Dönen sözlük her üç biçime de aynı şekilde girer:

    * `value` — düşük güvende **None**'dır; sayı tek başına dolaşmasın diye.
    * `display` — ekranda/CSV'de görünen metin.
    * `confidence` — kademe adı.

    Bu, "güven düşükse söylenir" kuralının tek uygulama noktasıdır.
    """
    level = str(confidence or "none")
    if value is None or level in LOW_CONFIDENCE:
        return {"value": None, "display": LOW_CONFIDENCE_TEXT, "confidence": level}
    text = num(value, digits)
    if unit:
        text = f"{text}{unit}"
    if level == "exploratory":
        text = f"{text} ({EXPLORATORY_SUFFIX})"
    return {"value": value, "display": text, "confidence": level}


def band_text(placement: dict[str, Any] | None) -> str:
    """Bant metni. Bant yoksa "yeterli veri yok" — sayı uydurulmaz."""
    if not isinstance(placement, dict):
        return LOW_CONFIDENCE_TEXT
    return BAND_LABELS.get(str(placement.get("band") or ""), LOW_CONFIDENCE_TEXT)


def trend_text(trend: dict[str, Any] | None) -> str:
    """Eğilim yönü: yükseliyor / düşüyor / belirgin değil / veri yok."""
    if not isinstance(trend, dict) or not trend.get("available"):
        return LOW_CONFIDENCE_TEXT
    if trend.get("rising"):
        return "yükseliyor"
    if trend.get("dropped"):
        return "düşüyor"
    return "belirgin değişim yok"


def dimension_label(dimension: Any) -> str:
    key = str(dimension or "")
    return DIMENSION_LABELS.get(key, key)


def label_label(label: Any) -> str:
    key = str(label or "")
    return LABEL_LABELS.get(key, key)


def contrast_sentence(row: dict[str, Any]) -> str:
    """Segment satırının **karşıtlık** cümlesi — ham doğruluk asla geçmez.

    `contrast = accuracy − overall_accuracy`: öğrencinin bu segmentteki
    başarısının **kendi genel düzeyine** göre sapması. Cümle akran
    sıralaması içermez; karşılaştırma öğrencinin kendisiyledir.
    """
    dim = dimension_label(row.get("dimension"))
    lbl = label_label(row.get("label"))
    confidence = str(row.get("confidence") or "none")
    if confidence in LOW_CONFIDENCE or row.get("contrast") is None:
        return f"{dim} · {lbl}: {LOW_CONFIDENCE_TEXT}"
    points = float(row.get("contrast") or 0.0) * 100.0
    if points <= -1.0:
        yon = f"kendi genel düzeyinin {num(abs(points), 1)} puan altında"
    elif points >= 1.0:
        yon = f"kendi genel düzeyinin {num(points, 1)} puan üstünde"
    else:
        yon = "kendi genel düzeyiyle aynı çizgide"
    ek = f" ({EXPLORATORY_SUFFIX})" if confidence == "exploratory" else ""
    return f"{dim} · {lbl}: {yon}{ek}"


def why_block(row: dict[str, Any], evidence: dict[str, Any]) -> list[dict[str, str]]:
    """Beş bölümlü "Neden?": Olgu · Karşılaştırma · Kural · Sınır · Tarih.

    `CIKTI-SOZLESMESI.md` §2.2: **Sınır** satırı zorunludur; o satır olmadan
    ürün olduğundan çok şey bildiğini ima eder.
    """
    limitation = ""
    raw_evidence = row.get("evidence")
    if isinstance(raw_evidence, dict):
        limitation = str(raw_evidence.get("limitation") or "")
    fact_keys = [k for k in evidence if k not in ("rule", "reference_mean_contrast")]
    olgu = "; ".join(f"{k}: {_short(evidence[k])}" for k in sorted(fact_keys))
    karsilastirma = ""
    if "reference_mean_contrast" in evidence:
        karsilastirma = (
            "kohort ortalama kontrastı: "
            f"{signed(evidence.get('reference_mean_contrast'))}"
        )
    kural = str(evidence.get("rule") or row.get("rule_id") or "")
    sürüm = row.get("rule_version")
    if sürüm is not None:
        kural = f"{kural} (kural sürümü {sürüm})"
    return [
        {"label": "Olgu", "text": olgu or "—"},
        {"label": "Karşılaştırma", "text": karsilastirma or "—"},
        {"label": "Kural", "text": kural or "—"},
        {"label": "Sınır", "text": limitation or "—"},
        {"label": "Tarih", "text": date_tr(row.get("created_at"))},
    ]


def _short(value: Any, limit: int = 120) -> str:
    if isinstance(value, float):
        return num(value, 3)
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def rule_title(rule_id: Any) -> str:
    key = str(rule_id or "")
    return RULE_LABELS.get(key, key)
