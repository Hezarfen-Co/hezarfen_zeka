"""Dosya adları ve diske yazma.

Ad deseni **öngörülebilir** ve tarihlidir:

    {okul}_{tip}[_{kim}]_{YYYY-MM-DD}.{uzanti}

CSV çok dosyalıdır (her tablo bölümü bir dosya):

    {okul}_{tip}[_{kim}]_{YYYY-MM-DD}_{bolum}.csv

Kimlikler dosya adına **sadeleştirilerek** girer: `user:01K42...` gibi bir
kimlik iki nokta taşır ve Windows'ta geçerli bir dosya adı değildir.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import render, text
from .document import Report

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def slug(value: str | None) -> str:
    """Dosya adına girebilecek güvenli parça."""
    if not value:
        return ""
    cleaned = _UNSAFE.sub("-", str(value)).strip("-")
    return cleaned[:60]


def base_name(report: Report) -> str:
    parts = [slug(report.school), report.kind]
    if report.subject:
        parts.append(slug(report.subject))
    parts.append(text.date_key(report.generated_at))
    return "_".join(p for p in parts if p)


def write(report: Report, out_dir: str | Path, fmt: str) -> list[Path]:
    """Raporu istenen biçimde yazar; yazılan dosyaların yollarını döndürür."""
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    base = base_name(report)

    if fmt == "json":
        path = directory / f"{base}.json"
        path.write_text(render.to_json(report), encoding="utf-8")
        return [path]

    if fmt == "html":
        path = directory / f"{base}.html"
        path.write_text(render.to_html(report), encoding="utf-8")
        return [path]

    if fmt == "csv":
        written: list[Path] = []
        for section_id, body in render.csv_tables(report):
            path = directory / f"{base}_{slug(section_id)}.csv"
            # BOM zorunlu: Excel BOM'suz UTF-8 dosyayı yerel kod sayfasıyla
            # açar ve Türkçe karakterler bozulur.
            path.write_text(body, encoding=render.CSV_ENCODING, newline="")
            written.append(path)
        return written

    raise ValueError(f"bilinmeyen biçim: {fmt!r} (json|html|csv)")
