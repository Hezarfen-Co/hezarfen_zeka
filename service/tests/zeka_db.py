"""Entegrasyon testlerinin ortak altyapisi: gercek SurrealDB + fikstur uretimi.

`tests/test_store.py`, `tests/test_scheduler.py` ve `tests/test_pipeline.py`
buradan beslenir.

---------------------------------------------------------------------------
KONTEYNER YOKSA ATLANIR, VARSA KOSAR
---------------------------------------------------------------------------
Adres `ZEKA_TEST_DB_URL` ortam degiskeninden gelir (orn.
`http://hzk-zeka:8000`). Degisken yoksa ya da adres cevap vermiyorsa
entegrasyon testleri `skipUnless` ile **atlanir** -- birim testleri etkilenmez.
CI'da degisken tanimlandigi anda ayni testler kosar.

Neden ortam degiskeni: podman'da host'a port yonlendirmesi bu makinede
calismiyor; testler `hzk` agindaki bir konteynerden kosuluyor ve veritabanina
`hzk-zeka:8000` adiyla ulasiyor. Adresi koda gommek, tek bir topolojiye
baglanmak olurdu.
"""

from __future__ import annotations

import json
import os
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from src.compute import clock
from src.store import SurrealHttpClient, apply_schema

from .fakes import (
    course_attendance,
    course_marks,
    homework,
    pomodoro,
    profile,
    report_entry,
)

DAY = clock.DAY_MS
HOUR = 3_600_000

#: Testlerin ortak "simdi"si: 2023-11-14 12:00 UTC.
NOW = 1_699_963_200_000
TERM_START = NOW - 150 * DAY

DB_URL = os.environ.get("ZEKA_TEST_DB_URL", "").strip()
DB_NS = os.environ.get("ZEKA_TEST_DB_NS", "hezarfen_test")
DB_USER = os.environ.get("ZEKA_TEST_DB_USER", "root")
DB_PASSWORD = os.environ.get("ZEKA_TEST_DB_PASSWORD", "root")


def _probe(url: str) -> bool:
    """Adres gercekten cevap veriyor mu? Tek seferlik, kisa zaman asimi."""
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=5):
            return True
    except urllib.error.HTTPError:
        # 4xx da "sunucu ayakta" demektir.
        return True
    except Exception:
        return False


DB_AVAILABLE = bool(DB_URL) and _probe(DB_URL)

SKIP_REASON = (
    "ZEKA_TEST_DB_URL tanimsiz ya da SurrealDB ulasilamaz durumda; "
    "entegrasyon testi atlandi"
)

requires_db = unittest.skipUnless(DB_AVAILABLE, SKIP_REASON)


def fresh_client(prefix: str = "t") -> SurrealHttpClient:
    """Her test icin **yeni ve bos** bir veritabani acar.

    Testler birbirinin satirini gormez; "tabloyu temizlemeyi unutmak" diye bir
    hata sinifi olusmaz.
    """
    client = SurrealHttpClient(
        DB_URL,
        namespace=DB_NS,
        database=f"{prefix}_{uuid.uuid4().hex[:10]}",
        user=DB_USER,
        password=DB_PASSWORD,
    )
    client.ensure_namespace()
    return client


def fresh_schema_client(prefix: str = "t") -> SurrealHttpClient:
    """`fresh_client` + semayi yukle. Yukleme duserse test **patlar**."""
    client = fresh_client(prefix)
    report = apply_schema(client)
    if not report.ok:
        raise AssertionError(f"sema yuklenemedi: {report.errors}")
    return client


def count_rows(client: SurrealHttpClient, table: str, where: str = "") -> int:
    """`SELECT count() ... GROUP ALL` -- SurrealDB 3'te HAVING yok, bu yeter."""
    clause = f" WHERE {where}" if where else ""
    rows = client.query_sync(f"SELECT count() FROM {table}{clause} GROUP ALL;")
    result = rows[0].get("result") or []
    return int(result[0]["count"]) if result else 0


def select(client: SurrealHttpClient, sql: str, variables: dict | None = None) -> list:
    rows = client.query_sync(sql, variables or {})
    return rows[-1].get("result") or []


# ---------------------------------------------------------------------------
# Fikstur uretimi -- `FileSource`'un okudugu dizin duzeni
# ---------------------------------------------------------------------------


def student_payload(
    uid: str,
    class_id: str,
    marks_list: list[int],
    present: int,
    absent: int,
    *,
    now_ms: int = NOW,
) -> dict[str, Any]:
    """Tek ogrencinin butun kaynak verisi (`FakeSource` ile ayni sekil)."""
    base = now_ms - 100 * DAY
    return {
        "profile": profile(uid, [class_id], ["course-1"]),
        "marks": [course_marks("course-1", marks_list, base, teachers=["teacher-1"])],
        "attendance": [course_attendance("course-1", present=present, absent=absent)],
        "pomodoro": [
            pomodoro(
                (clock.tr_day(now_ms) - d) * DAY + 10 * HOUR - clock.TR_OFFSET_MS
            )
            for d in range(1, 7)
        ],
        "homework_report": [
            report_entry(
                f"hw-{uid}-{i}", "course-1", now_ms - (i + 1) * DAY, submitted=True
            )
            for i in range(6)
        ],
        "homework_list": [homework("upcoming", "course-1", now_ms + 6 * HOUR, [uid])],
    }


def dataset(count: int = 12, *, now_ms: int = NOW) -> dict[str, dict]:
    """Bir sube, bir ders, `count` ogrenci; ilki belirgin bicimde dusuk."""
    data: dict[str, dict] = {}
    for i in range(count):
        uid = f"student-{i:02d}"
        if i == 0:
            data[uid] = student_payload(
                uid, "class-A", [40, 41, 39, 42, 40, 38], 60, 40, now_ms=now_ms
            )
        else:
            data[uid] = student_payload(
                uid, "class-A", [70, 72, 71, 69, 70, 71], 95, 5, now_ms=now_ms
            )
    data["_school"] = {
        "homework_list": [
            homework("hw-school", "course-1", now_ms + DAY, list(data.keys()))
        ]
    }
    return data


def write_fixtures(root: Path, school: str, data: dict[str, dict]) -> list[str]:
    """`data` sozlugunu `FileSource`'un bekledigi dizin duzenine yazar.

    Donen deger: okul-genelinde islenecek ogrenci kimlikleri.
    """
    base = root / school
    #: yontem -> (alt dizin, zarf anahtari veya None)
    layout = {
        "profile": ("profile", None),
        "marks": ("marks", "courses"),
        "attendance": ("attendance", "courses"),
        "pomodoro": ("pomodoro", "items"),
        "homework_report": ("homework_report", "items"),
        "homework_list": ("homework", "items"),
    }
    for directory, _ in layout.values():
        (base / directory).mkdir(parents=True, exist_ok=True)

    students: list[str] = []
    for key, payload in data.items():
        name = "_service" if key == "_school" else key
        if key != "_school":
            students.append(key)
        for method, (directory, envelope) in layout.items():
            if method not in payload:
                continue
            body = payload[method]
            if envelope is None:
                out: Any = body
            elif method == "homework_report":
                out = {"items": body, "total": len(body), "limit": None, "offset": 0}
            else:
                out = {envelope: body}
            (base / directory / f"{name}.json").write_text(
                json.dumps(out, ensure_ascii=False), encoding="utf-8"
            )
    return students
