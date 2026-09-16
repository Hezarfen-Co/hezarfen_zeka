"""Üç biçim: JSON, HTML, CSV. Hepsi aynı `Report` belgesinden üretilir.

**Dış bağımlılık yoktur** ve olmayacaktır:

* HTML tek dosyadır; stil `<style>` içinde gömülüdür, betik yoktur, resim
  yoktur, yazı tipi indirilmez. Tarayıcıda açılıp **PDF'e basılabilir**
  (`@media print` düzeni). Ağa hiçbir istek çıkmaz: rapor kişisel veri taşır,
  bir CDN'e istek çıkması o verinin varlığını üçüncü tarafa bildirirdi.
* Şablon motoru **kurulmaz**; HTML elle üretilir ve her metin kaçırılır.
* CSV `utf-8-sig` (BOM) ile yazılır ve ayraç `;`'dir: Excel'in Türkçe
  yerelinde varsayılan liste ayracı budur; virgülle yazılan dosya tek sütuna
  düşer ve Türkçe karakterler BOM'suz bozulur.
"""

from __future__ import annotations

import csv
import io
import json
from html import escape
from typing import Any

from .document import Cards, Data, Note, Report, Table

CSV_DELIMITER = ";"
CSV_ENCODING = "utf-8-sig"


def display_value(value: Any) -> str:
    """Hücre değerini metne çevirir.

    `text.measure()` sözlükleri `display` alanından okunur: düşük güvende
    orada zaten «yeterli veri yok» yazar, sayı hiç görünmez.
    """
    if value is None:
        return ""
    if isinstance(value, dict):
        if "display" in value:
            return str(value["display"])
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "evet" if value else "hayır"
    if isinstance(value, list):
        return ", ".join(display_value(v) for v in value)
    return str(value)


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def to_json(report: Report) -> str:
    """Makine okunabilir biçim — sözleşmenin alan adları korunur."""
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2, default=str)


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def table_to_csv(table: Table) -> str:
    """Tek tabloyu CSV metnine çevirir (BOM'suz; dosyaya yazan ekler)."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=CSV_DELIMITER, lineterminator="\r\n")
    writer.writerow([c.label for c in table.columns])
    for row in table.rows:
        writer.writerow([display_value(row.get(c.key)) for c in table.columns])
    return buffer.getvalue()


def csv_tables(report: Report) -> list[tuple[str, str]]:
    """Rapordaki **tablo hâline gelebilen** bölümler: `(bölüm id, csv metni)`.

    Kart ve not bölümleri CSV'ye dönmez: beş bölümlü "Neden?" bir tablo değil,
    bir gerekçedir; hücreye sıkıştırılırsa okunmaz hale gelir.
    """
    return [(t.id, table_to_csv(t)) for t in report.tables()]


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_STYLE = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px;
  font-family: -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  font-size: 14px; line-height: 1.5; color: #1a1a1a; background: #f7f7f5;
}
main { max-width: 1000px; margin: 0 auto; background: #fff; padding: 28px;
       border: 1px solid #e2e2dd; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 17px; margin: 28px 0 8px; border-bottom: 2px solid #1a1a1a;
     padding-bottom: 4px; }
.meta { color: #555; font-size: 12px; margin-bottom: 16px; }
.note { background: #f1f4f8; border-left: 3px solid #4a6fa5; padding: 8px 12px;
        margin: 8px 0 14px; font-size: 12px; color: #333; }
.empty { background: #fff6e5; border-left: 3px solid #b8860b; padding: 10px 12px;
         margin: 12px 0; }
table { border-collapse: collapse; width: 100%; margin: 6px 0 4px; font-size: 13px; }
th, td { border: 1px solid #d8d8d2; padding: 5px 8px; text-align: left;
         vertical-align: top; }
th { background: #eeeee9; font-weight: 600; }
tbody tr:nth-child(even) { background: #fafaf7; }
td.num { text-align: right; }
.card { border: 1px solid #d8d8d2; padding: 10px 12px; margin: 8px 0; }
.card h3 { font-size: 14px; margin: 0 0 6px; }
.card dl { margin: 0; display: grid; grid-template-columns: 110px 1fr; gap: 2px 8px; }
.card dt { font-weight: 600; color: #444; }
.card dd { margin: 0; }
.tag { display: inline-block; font-size: 11px; border: 1px solid #b9b9b2;
       padding: 0 6px; margin-left: 6px; color: #444; }
.low { color: #8a5a00; }
footer { margin-top: 28px; font-size: 11px; color: #666;
         border-top: 1px solid #e2e2dd; padding-top: 10px; }
@media print {
  body { background: #fff; padding: 0; font-size: 11pt; }
  main { border: 0; padding: 0; max-width: none; }
  h2 { page-break-after: avoid; }
  table, .card { page-break-inside: avoid; }
  thead { display: table-header-group; }
  .note { background: none; border-left: 2px solid #666; }
  @page { margin: 16mm; }
}
"""


def _esc(value: Any) -> str:
    return escape(display_value(value), quote=True)


def _table_html(table: Table) -> str:
    parts = [f"<h2>{escape(table.title)}</h2>"]
    if table.note:
        parts.append(f'<p class="note">{escape(table.note)}</p>')
    if not table.rows:
        parts.append('<p class="empty">Bu bölümde gösterilecek satır yok.</p>')
        return "\n".join(parts)
    head = "".join(f"<th>{escape(c.label)}</th>" for c in table.columns)
    body = []
    for row in table.rows:
        cells = []
        for column in table.columns:
            value = row.get(column.key)
            css = ""
            if isinstance(value, dict) and value.get("value") is None:
                css = ' class="low"'
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                css = ' class="num"'
            cells.append(f"<td{css}>{_esc(value)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    parts.append(
        "<table><thead><tr>"
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )
    return "\n".join(parts)


def _cards_html(cards: Cards) -> str:
    parts = [f"<h2>{escape(cards.title)}</h2>"]
    if cards.note:
        parts.append(f'<p class="note">{escape(cards.note)}</p>')
    if not cards.items:
        parts.append('<p class="empty">Gösterilecek tavsiye yok.</p>')
        return "\n".join(parts)
    for item in cards.items:
        head = escape(str(item.get("title") or ""))
        tags = [str(item.get("rule_id") or ""), str(item.get("confidence_label") or "")]
        if item.get("course"):
            tags.append(str(item["course"]))
        if item.get("about"):
            tags.append(str(item["about"]))
        tag_html = "".join(f'<span class="tag">{escape(t)}</span>' for t in tags if t)
        rows = "".join(
            f"<dt>{escape(str(part.get('label')))}</dt>"
            f"<dd>{escape(str(part.get('text')))}</dd>"
            for part in item.get("why") or []
        )
        parts.append(
            f'<div class="card"><h3>{head}{tag_html}</h3><dl>{rows}</dl></div>'
        )
    return "\n".join(parts)


def _note_html(note: Note) -> str:
    body = "<br>".join(escape(line) for line in note.text.splitlines())
    return f"<h2>{escape(note.title)}</h2>\n<p class=\"note\">{body}</p>"


def _data_html(data: Data) -> str:
    """Ham gövde HTML'de **basılmaz**; satır sayıları özetlenir.

    Ham çıktının yeri JSON'dur. Binlerce satırı HTML'e gömmek ne okunur ne
    basılır; sayfayı da kullanışsız kılardı.
    """
    rows = "".join(
        f"<tr><td>{escape(str(name))}</td>"
        f"<td class=\"num\">{len(value) if isinstance(value, (list, dict)) else 1}</td></tr>"
        for name, value in sorted(data.data.items())
    )
    note = f'<p class="note">{escape(data.note)}</p>' if data.note else ""
    return (
        f"<h2>{escape(data.title)}</h2>{note}"
        "<table><thead><tr><th>Tablo</th><th>Satır</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        '<p class="note">Ham gövde JSON biçimindedir; bu sayfada yalnız '
        "muhasebesi gösterilir.</p>"
    )


def to_html(report: Report) -> str:
    """Tek dosyalık HTML. Dış kaynak yok, betik yok, ağ isteği yok."""
    from . import text as text_mod

    body: list[str] = []
    for section in report.sections:
        if isinstance(section, Table):
            body.append(_table_html(section))
        elif isinstance(section, Cards):
            body.append(_cards_html(section))
        elif isinstance(section, Note):
            body.append(_note_html(section))
        elif isinstance(section, Data):
            body.append(_data_html(section))

    subject = f" · {escape(report.subject)}" if report.subject else ""
    empty_html = (
        '<p class="empty">Bu rapor <strong>boş</strong> üretildi: '
        "gösterilecek satır bulunamadı.</p>"
        if report.empty
        else ""
    )
    notes_html = "".join(f"<li>{escape(n)}</li>" for n in report.notes)
    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(report.title)}</title>
<style>{_STYLE}</style>
</head>
<body>
<main>
<h1>{escape(report.title)}</h1>
<p class="meta">Okul: {escape(report.school)}{subject} · Üretim:
{escape(text_mod.date_tr(report.generated_at))} · Rapor tipi:
{escape(report.kind)}</p>
{empty_html}
{"".join(body)}
<footer>
<strong>Bu rapor nasıl okunur</strong>
<ul>{notes_html}</ul>
Kaynak: ZEKA'nın kendi veritabanı (beş tablo). Okul veritabanına yazılmaz,
hiçbir kayıt değiştirilmez.
</footer>
</main>
</body>
</html>
"""
