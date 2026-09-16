"""Görünürlük kapıları — bir satırın rapora **girip girmediğine** karar verir.

Dördü de `docs/CIKTI-SOZLESMESI.md`'den gelir ve tercih değildir:

1. **Kanıtsız satır girmez.** `evidence` yalnız `limitation` taşıyorsa o satır
   "neden?" sorusunu cevaplayamaz (§2.2, `MODULLER.md` §2.10 kural 1).
2. **Kapatılmış satır girmez** (`dismissed_at` dolu, §4.3 madde 3).
3. **Süresi geçmiş satır girmez** (`expires_at <= now`, §4.2).
4. **Rol kapısı**: `audience_role` rapor tipinin izin verdiği kümede olmalı
   (§5). Bu kapı `gate.py`'deki tip kapısının **ikinci** hattıdır; ilk hat
   verinin hiç okunmamasıdır.

Ayrıca segment profillerinde `confidence = none` (n < 30) satırları
gösterilmez: depoda durur, ekranda durmaz (§5 son satır).
"""

from __future__ import annotations

from typing import Any, Iterable

#: `evidence` içinde kanıt sayılmayan anahtarlar — `limitation` "Sınır"
#: satırıdır, olgu değildir.
EVIDENCE_META_KEYS = frozenset({"limitation"})


def evidence_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Satırın **olgu** kısmı: `limitation` dışındaki kanıt alanları."""
    evidence = row.get("evidence")
    if not isinstance(evidence, dict):
        return {}
    return {k: v for k, v in evidence.items() if k not in EVIDENCE_META_KEYS}


def has_evidence(row: dict[str, Any]) -> bool:
    """Kanıtı var mı? Yoksa satır rapora **girmez** (kural 3)."""
    return bool(evidence_payload(row))


def is_dismissed(row: dict[str, Any]) -> bool:
    """Kullanıcı kapatmış mı? `NONE` / `None` / boş metin kapatılmamış sayılır."""
    value = row.get("dismissed_at")
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in ("", "none", "null")
    return True


def is_expired(row: dict[str, Any], now_ms: int) -> bool:
    """Süresi geçmiş mi? `expires_at` yoksa satır **gösterilmez**.

    Eksik damga "süresiz geçerli" demek değildir: sözleşme her tavsiyenin
    düşme anını zorunlu kılar, damgasız satır bozuk satırdır.
    """
    value = row.get("expires_at")
    if value is None:
        return True
    try:
        return int(value) <= int(now_ms)
    except (TypeError, ValueError):
        return True


def visible_recommendations(
    rows: Iterable[dict[str, Any]],
    *,
    now_ms: int,
    allowed_roles: frozenset[str] | set[str],
) -> list[dict[str, Any]]:
    """Dört kapıdan geçen tavsiyeler. **Sıralama yapılmaz** (kural 2).

    Dönen liste `rule_id`, `about`, `course` üçlüsüne göre alfabetiktir;
    "en kötüden en iyiye" gibi bir düzen üretilmez.
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("audience_role") or "") not in allowed_roles:
            continue
        if is_dismissed(row):
            continue
        if is_expired(row, now_ms):
            continue
        if not has_evidence(row):
            continue
        out.append(row)
    out.sort(
        key=lambda r: (
            str(r.get("rule_id") or ""),
            str(r.get("about") or ""),
            str(r.get("course") or ""),
        )
    )
    return out


def visible_segment_profiles(
    rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """`confidence != none` olan segment satırları, alfabetik."""
    out = [
        row
        for row in rows
        if str(row.get("confidence") or "none") != "none"
        and int(row.get("n_answers") or 0) > 0
    ]
    out.sort(key=lambda r: (str(r.get("dimension") or ""), str(r.get("label") or "")))
    return out


def dropped_counts(
    rows: Iterable[dict[str, Any]], *, now_ms: int, allowed_roles: frozenset[str] | set[str]
) -> dict[str, int]:
    """Hangi kapıdan kaç satır düştü — raporun "neden boş" notunu besler.

    Sayılar **kişi taşımaz**; yalnız muhasebedir.
    """
    counts = {"rol": 0, "kapatilmis": 0, "suresi_gecmis": 0, "kanitsiz": 0}
    for row in rows:
        if str(row.get("audience_role") or "") not in allowed_roles:
            counts["rol"] += 1
        elif is_dismissed(row):
            counts["kapatilmis"] += 1
        elif is_expired(row, now_ms):
            counts["suresi_gecmis"] += 1
        elif not has_evidence(row):
            counts["kanitsiz"] += 1
    return counts
