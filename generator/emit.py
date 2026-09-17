"""SurrealQL yazıcı: akışlı, toplu INSERT üretir ve her alanı şemaya karşı doğrular.

Tasarım:
  * Her tablo kendi geçici parça dosyasına akıtılır (`_parts/<tablo>.part`).
    Böylece 250.000 satırlık `exam_answer` bellekte tutulmaz.
  * Üretim bittiğinde parçalar `load_order` sırasına göre numaralı `.surql`
    dosyalarına birleştirilir; her dosyanın başına yorum bloğu yazılır.
  * SCHEMAFULL tabloda tanımsız alan sessizce silindiği için, her satırın her
    alanı yazılmadan önce `schema.json` ile doğrulanır; hata varsa üretim durur.
"""

from __future__ import annotations

import json
import os
import shutil

from config import BATCH_SIZE
from ids import Rid

_SCHEMA = None


def load_schema(path: str) -> dict:
    global _SCHEMA
    with open(path, "r", encoding="utf-8") as fh:
        _SCHEMA = json.load(fh)
    return _SCHEMA


def schema() -> dict:
    if _SCHEMA is None:
        raise RuntimeError("schema.json yüklenmedi")
    return _SCHEMA


def table_fields(table: str) -> dict:
    sch = schema()
    if table in sch["tables"]:
        return sch["tables"][table]["fields"]
    if table in sch["control_tables"]:
        return sch["control_tables"][table]["fields"]
    raise KeyError("Şemada olmayan tablo: %s" % table)


def removed_fields(table: str) -> set:
    sch = schema()
    src = sch["tables"].get(table) or sch["control_tables"].get(table) or {}
    return {r["field"] for r in src.get("removed_fields", [])}


# ---------------------------------------------------------------------------
# Değer serileştirme
# ---------------------------------------------------------------------------

# Dize kaçışlaması TEK yerde toplanır; başka hiçbir modül tırnak yazmaz.
#
# Neden ters bölü ile tırnak kaçışlaması (\') KULLANILMIYOR:
# Türkçe metinde kesme işareti çok sık geçer (Ali'nin, 2026'da, Atatürk'ün).
# `\'` dizisinin SurrealQL tarafından kabul edildiği bu ortamda ÇALIŞTIRILARAK
# doğrulanamadı; yanlışsa tüm yükleme patlar. Bu yüzden risk varsayıma
# bırakılmaz, tamamen ortadan kaldırılır:
#
#   * tek tırnak YOK          -> 'tek tırnaklı dize'
#   * tek tırnak var, çift yok -> "çift tırnaklı dize"   (kaçış gerekmez)
#   * ikisi de var (çok nadir) -> çift tırnaklıda \" kaçışı + sayaca yazılır
#   * ters bölü metinde geçerse her iki biçimde de \\ olarak kaçışlanır
#
# Satır sonu / sekme karakterleri üretimde hiç kullanılmaz; yine de kaçışlanır
# ve sayılır ki fark edilmeden içeri sızmasınlar.

ESCAPE_STATS = {"tek_tirnakli": 0, "cift_tirnakli": 0, "her_iki_tirnak": 0,
                "ters_bolu": 0, "kontrol_karakteri": 0}

_CONTROL = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _escape_common(value: str) -> str:
    """Ters bölü ve kontrol karakterleri — tırnak türünden bağımsız."""
    if "\\" in value:
        ESCAPE_STATS["ters_bolu"] += 1
        value = value.replace("\\", "\\\\")
    for ch, esc in _CONTROL.items():
        if ch in value:
            ESCAPE_STATS["kontrol_karakteri"] += 1
            value = value.replace(ch, esc)
    return value


def sq_string(value: str) -> str:
    """Bir Python dizesini güvenli bir SurrealQL dize sabitine çevirir."""
    body = _escape_common(value)
    if "'" not in body:
        ESCAPE_STATS["tek_tirnakli"] += 1
        return "'" + body + "'"
    if '"' not in body:
        ESCAPE_STATS["cift_tirnakli"] += 1
        return '"' + body + '"'
    ESCAPE_STATS["her_iki_tirnak"] += 1
    return '"' + body.replace('"', '\\"') + '"'


def sq(value) -> str:
    if value is None:
        return "NONE"
    if isinstance(value, Rid):
        return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value == int(value):
            return str(int(value))
        return repr(round(value, 6))
    if isinstance(value, str):
        return sq_string(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(sq(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join("%s: %s" % (k, sq(v)) for k, v in value.items()) + " }"
    raise TypeError("Serileştirilemeyen değer: %r" % (value,))


# ---------------------------------------------------------------------------
# Alan doğrulama
# ---------------------------------------------------------------------------

def validate_row(table: str, row: dict, flexible_fields=()) -> None:
    fields = table_fields(table)
    gone = removed_fields(table)
    for key, value in row.items():
        if key == "id":
            continue
        if key in gone:
            raise ValueError("%s.%s kaldırılmış bir kolon (yazılamaz)" % (table, key))
        if key not in fields:
            raise ValueError("%s tablosunda tanımsız alan: %s" % (table, key))
        if key in flexible_fields:
            continue
        _validate_nested(table, key, value, fields)


def _validate_nested(table: str, prefix: str, value, fields: dict) -> None:
    if isinstance(value, dict):
        for sub, subval in value.items():
            path = "%s.%s" % (prefix, sub)
            if path not in fields:
                raise ValueError("%s tablosunda tanımsız alt alan: %s" % (table, path))
            _validate_nested(table, path, subval, fields)
    elif isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, dict):
                for sub in item:
                    path = "%s.*.%s" % (prefix, sub)
                    if path not in fields:
                        raise ValueError(
                            "%s tablosunda tanımsız dizi alt alanı: %s" % (table, path))


# ---------------------------------------------------------------------------
# Akışlı yazıcı
# ---------------------------------------------------------------------------

class PartWriter:
    """Tablo başına bir parça dosyası; toplu INSERT ile akıtır."""

    def __init__(self, directory: str, table: str, flexible_fields=()):
        self.table = table
        self.path = os.path.join(directory, "%s.part" % table)
        self._fh = open(self.path, "w", encoding="utf-8", newline="\n")
        self._buf = []
        self.count = 0
        self._flexible = set(flexible_fields)

    def add(self, row: dict) -> None:
        validate_row(self.table, row, self._flexible)
        parts = []
        if "id" in row:
            parts.append("id: %s" % sq(row["id"]))
        for key, value in row.items():
            if key == "id":
                continue
            parts.append("%s: %s" % (key, sq(value)))
        self._buf.append("{ " + ", ".join(parts) + " }")
        self.count += 1
        if len(self._buf) >= BATCH_SIZE:
            self._flush()

    def _flush(self) -> None:
        if not self._buf:
            return
        self._fh.write("INSERT INTO %s [\n" % self.table)
        self._fh.write(",\n".join(self._buf))
        self._fh.write("\n];\n")
        self._buf.clear()

    def close(self) -> None:
        self._flush()
        self._fh.close()


class Emitter:
    """Tüm parça dosyalarını yönetir ve sonunda numaralı .surql dosyalarını kurar."""

    FLEXIBLE = {"rag_output": ("payload",)}

    def __init__(self, out_dir: str):
        self.out_dir = out_dir
        self.parts_dir = os.path.join(out_dir, "_parts")
        os.makedirs(self.parts_dir, exist_ok=True)
        self._writers = {}
        self.counts = {}

    def writer(self, table: str) -> PartWriter:
        w = self._writers.get(table)
        if w is None:
            w = PartWriter(self.parts_dir, table, self.FLEXIBLE.get(table, ()))
            self._writers[table] = w
        return w

    def add(self, table: str, row: dict) -> None:
        self.writer(table).add(row)

    def add_many(self, table: str, rows) -> None:
        # DİKKAT: `self.add()` üzerinden geçer; doğrudan `w.add(row)` çağırmak
        # yazıcıyı atlar ve satır sessizce düşer. Toplam sayı yazıcıdan
        # okunduğu için eksiklik ancak yükleme sırasında görülürdü.
        for row in rows:
            self.add(table, row)

    def close_all(self) -> None:
        for table, w in self._writers.items():
            w.close()
            self.counts[table] = w.count

    def assemble(self, layout, descriptions) -> list:
        """Parçaları numaralı dosyalara birleştirir; dosya listesini döndürür."""
        files = []
        prev_name = None
        for number, name, tables in layout:
            present = [t for t in tables if t in self._writers]
            if not present:
                continue
            fname = "%02d_%s.surql" % (number, name)
            path = os.path.join(self.out_dir, fname)
            with open(path, "w", encoding="utf-8", newline="\n") as out:
                total = sum(self.counts.get(t, 0) for t in present)
                out.write("-- ---------------------------------------------------------------\n")
                out.write("-- Hezarfen tohum verisi — %s\n" % fname)
                out.write("-- %s\n" % descriptions.get(number, ""))
                out.write("-- Tablolar ve satır sayıları:\n")
                for t in present:
                    out.write("--   %-22s %8d satır\n" % (t, self.counts.get(t, 0)))
                out.write("--   %-22s %8d satır (dosya toplamı)\n" % ("TOPLAM", total))
                if prev_name is None:
                    out.write("-- Yükleme sırası: bu dosya 00_control.surql'den SONRA,\n")
                    out.write("--   okul veritabanında (USE DB <slug>) yüklenir.\n")
                else:
                    out.write("-- Yükleme sırası: %s dosyasından SONRA yüklenmelidir.\n" % prev_name)
                out.write("-- UYARI: SCHEMAFULL tablolar — alan adları schema.json ile doğrulanmıştır.\n")
                out.write("-- ---------------------------------------------------------------\n\n")
                for t in present:
                    part = os.path.join(self.parts_dir, "%s.part" % t)
                    out.write("-- >>> %s (%d satır)\n" % (t, self.counts.get(t, 0)))
                    with open(part, "r", encoding="utf-8") as src:
                        shutil.copyfileobj(src, out)
                    out.write("\n")
            files.append((fname, os.path.getsize(path)))
            prev_name = fname
        return files

    def cleanup(self) -> None:
        shutil.rmtree(self.parts_dir, ignore_errors=True)
