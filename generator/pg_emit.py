"""Uretilen satirlari PostgreSQL `INSERT` dosyalarina yazar.

`Emitter` ile **yan yana** calisir: ayni `add(table, row)` cagrilarini alir.
Metin ayristirmasi YOKTUR — `.surql` dosyalarini regex'le okumak yerine veriyi
uretildigi yerde, hala yapili haldeyken cevirir.

Bu bilincli bir tercih ve bedeli bir kez odendi: `\\'` kacisini anlamayan bir
regex, "47 kirik cevap" diye var olmayan bir sorun raporlamisti. Kayit
referanslari burada `Rid` nesnesidir; tablo ve anahtari ayri ayri tasir, yani
hangi tabloya baktigi tahmin edilmez, bilinir.

---------------------------------------------------------------------------
Sessiz dusurme yok
---------------------------------------------------------------------------
Bir alan `pg_map` kurallarinin hicbirine uymuyorsa cevirim HATA ile durur.
Alan atlamak, "cevirdik" deyip verinin bir parcasini kaybetmenin ta kendisi.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "service"))

from src.ids import mint_uuid7, ulid_to_uuid7  # noqa: E402

import pg_map as M  # noqa: E402
from ids import Rid  # noqa: E402

BATCH_SIZE = 500
_ULID_LEN = 26
_CROCKFORD = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
_CROCKFORD_INDEX = {c: i for i, c in enumerate("0123456789ABCDEFGHJKMNPQRSTVWXYZ")}

#: Hedef semanin kolon katalogu: `_pg_columns.txt`, backend'in kendi
#: migration'lari uygulanmis bir veritabanindan dokulmus.
#: (tablo, kolon) -> (tip, NOT NULL mi, varsayilan ifade)
#:
#: Katalog burada bir SUSLEME degil, cevirinin hakemidir. Iki isi var:
#:   1. Semada OLMAYAN bir kolona yazilmaya calisilirsa hata verdirir. Bir
#:      alanin adini yanlis eslemek, o alani sessizce kaybetmenin en kolay
#:      yolu; katalok o yolu kapatir.
#:   2. `NOT NULL DEFAULT <x>` kolonlara gelen None'i varsayilanina cevirir.
#:      SurrealDB'de "alan yok" ile "sifir" ayni seydi (absent-reads-as-zero);
#:      Postgres'te alan ya var ya yok. Backend'in kendi cevirisi de bu
#:      sayaclari `BIGINT NOT NULL DEFAULT 0` yapti.
CATALOG_PATH = os.path.join(os.path.dirname(__file__), "_pg_columns.txt")


def _load_catalog():
    catalog = {}
    with open(CATALOG_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip()
            if not line:
                continue
            table, column, kind, notnull, default = line.split("|", 4)
            catalog[(table, column)] = (kind, notnull == "t", default)
    return catalog


CATALOG = _load_catalog()


def id_strategy(pg_table: str) -> str:
    """Birincil anahtar stratejisini HEDEF SEMADAN turetir.

    Elle tutulan bir liste yerine katalogdan okunuyor, cunku elle tutulan
    liste iki kez yanildi (`dietary_profile` ve `pool_question_image`
    `id` kolonu olmadigi halde "uuid" sayilmisti). Sema zaten cevabi
    biliyor; ona sormak, hatirlamaya calismaktan guvenli.

      id kolonu var   -> tipi uuid ise "uuid", degilse "text"
      name kolonu var -> "name"  (kind_ref, slot_ref)
      ikisi de yok    -> "composite": Postgres'te dogal bilesik anahtar var,
                         `id` alani atilir, bilesenleri zaten satirda.
    """
    columns = {c for (t, c) in CATALOG if t == pg_table}
    if "id" in columns:
        kind, _notnull, _default = CATALOG[(pg_table, "id")]
        return "uuid" if kind == "uuid" else "text"
    if "name" in columns:
        return "name"
    return "composite"

#: Varsayilan ifadeyi Python degerine cevirmenin BILINEN yollari. Taninmayan
#: bir varsayilan tahmin edilmez, hata verilir.
_DEFAULTS = {"0": 0, "false": False, "true": True, "''::text": ""}


def apply_catalog(table: str, row: dict) -> dict:
    """Satiri hedef semaya gore denetler ve NOT NULL bosluklarini doldurur.

    Uc is yapar, ucu de sessiz kayba karsi:
      1. Semada olmayan bir kolon -> hata.
      2. NOT NULL kolona gelen None -> varsayilani (yoksa hata).
      3. NOT NULL ve varsayilansiz bir kolon satirda HIC YOKSA -> hata.

    Ucuncusu ilk denemede atlanmisti ve `app_user.created_at` INSERT listesine
    hic girmedi; Postgres onu NULL sayip reddetti. Kolonun eksikligi ancak
    veritabani reddettigi icin gorulebildi — reddetmeseydi satir eksik bir
    alanla yazilacakti.
    """
    out = {}
    for column, value in row.items():
        spec = CATALOG.get((table, column))
        if spec is None:
            raise ConversionError(
                "%s: hedef semada `%s` diye bir kolon yok" % (table, column)
            )
        kind, notnull, default = spec
        if isinstance(value, Raw):
            out[column] = value
            continue
        if value is None and notnull:
            if not default:
                raise ConversionError(
                    "%s.%s NOT NULL ve varsayilani yok, ama deger None"
                    % (table, column)
                )
            if default not in _DEFAULTS:
                raise ConversionError(
                    "%s.%s varsayilani cozulemedi: %r" % (table, column, default)
                )
            value = _DEFAULTS[default]
        out[column] = value

    eksik = [
        column
        for (t, column), (_kind, notnull, default) in CATALOG.items()
        if t == table and notnull and not default and column not in out
    ]
    if eksik:
        raise ConversionError(
            "%s: NOT NULL ve varsayilansiz kolon(lar) satirda yok: %s"
            % (table, sorted(eksik))
        )
    return out


class ConversionError(RuntimeError):
    """Eslenemeyen alan / tablo. Cevirim durur."""


class Raw(str):
    """SQL'e OLDUGU GIBI yazilacak parca (alt sorgu gibi).

    Tirnaklanmaz. Yalnizca bu dosyanin kendi urettigi sabit metinler icin
    kullanilir; disaridan gelen hicbir deger Raw'a sarilmaz.
    """


def is_ulid(text: str) -> bool:
    return len(text) == _ULID_LEN and all(c in _CROCKFORD for c in text)


def ulid_ms(key: str) -> int:
    """ULID'in ilk 10 karakterindeki 48 bitlik unix-ms damgasi."""
    value = 0
    for ch in key[:10]:
        value = value * 32 + _CROCKFORD_INDEX[ch]
    return value


def key_to_uuid(table: str, key: str) -> str:
    """Bir kayit anahtarini uuid'ye cevirir.

    ULID ise damgasi ve milisaniye ici sirasi KORUNARAK cevrilir; degilse
    tablo adiyla nitelenmis metinden deterministik basilir. Niteleme sart:
    iki farkli tabloda ayni anahtar (`open_<user>` gibi) bulunabiliyor ve
    nitelenmeseydi ayni uuid'ye duserlerdi.

    ---------------------------------------------------------------------
    Cevirinin GIRDISI YALNIZCA ANAHTARDIR
    ---------------------------------------------------------------------
    Bir sure satirin kendi zaman alani (`starts_at` gibi) da basima
    katiliyordu; damgayi kimligin icine koymak `ORDER BY id` sirasini
    korudugu icin cazipti. Ama bu, ayni kaydin iki yerde iki FARKLI uuid
    almasina yol aciyordu: satirin kendisi yazilirken damga biliniyor, ona
    REFERANS veren satir yazilirken bilinmiyor. `term` satiri bir uuid,
    `class_group.term` baska bir uuid uretti ve yukleme yabanci anahtarda
    dustu.

    Damga hala korunuyor, ama yalnizca anahtardan OKUNABILDIGI olcude:
    kompozit anahtarlarin bası genellikle bir ULID'dir (`{odev}_{ogrenci}`)
    ve o ULID'in damgasi kullanilir. Okunamiyorsa sifir kalir; boyle
    satirlar kimlige gore sirasiz gorunur, ki bu yanlis siradan iyidir.
    """
    if is_ulid(key):
        return str(ulid_to_uuid7(key))
    head = key.split("_", 1)[0]
    ts = ulid_ms(head) if is_ulid(head) else 0
    return str(mint_uuid7("%s:%s" % (table, key), ts))


def pg_literal(value) -> str:
    """Bir Python degerini PostgreSQL sabitine cevirir.

    Metin kacisi tek kural: `''`. SurrealQL'in `\\'` bicimi Postgres'te
    varsayilan olarak GECERSIZ (`standard_conforming_strings = on`) ve ters
    boluyu oldugu gibi birakmak, iceren her satiri bozardi.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Raw):
        return str(value)
    if isinstance(value, Rid):
        raise ConversionError("Rid dogrudan yazilamaz: %r" % (value,))
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    if isinstance(value, (list, tuple, dict)):
        import json

        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return "'" + text.replace("'", "''") + "'::jsonb"
    raise ConversionError("Serilestirilemeyen deger: %r" % (value,))


class PgTableWriter:
    """Tablo basina bir parca dosyasi. Kolon kumesi ILK satirdan sabitlenir."""

    def __init__(self, directory: str, table: str) -> None:
        self.table = table
        self.path = os.path.join(directory, "%s.pgpart" % table)
        self._fh = open(self.path, "w", encoding="utf-8", newline="\n")
        self._columns: tuple[str, ...] | None = None
        self._buf: list[str] = []
        self.count = 0
        #: Verilirse INSERT'e `ON CONFLICT <bu> ` eklenir. Yalnizca control
        #: tarafindaki okul kaydi icin: backend okulu kendisi yaratmis
        #: olabilir ve tohum onun uzerine yazmamali.
        self.on_conflict: str | None = None

    def add(self, row: dict) -> None:
        columns = tuple(row)
        if self._columns is None:
            self._columns = columns
        elif columns != self._columns:
            # Kolon kumesi satirdan satira degisirse toplu INSERT kurulamaz.
            # Sessizce NULL doldurmak yerine hata: eksik kolon, eksik veridir.
            missing = set(self._columns) ^ set(columns)
            raise ConversionError(
                "%s: satirlar farkli kolon kumesi tasiyor; fark=%s"
                % (self.table, sorted(missing))
            )
        self._buf.append(
            "(" + ", ".join(pg_literal(row[c]) for c in self._columns) + ")"
        )
        self.count += 1
        if len(self._buf) >= BATCH_SIZE:
            self._flush()

    def _flush(self) -> None:
        if not self._buf or self._columns is None:
            return
        self._fh.write(
            "INSERT INTO %s (%s) VALUES\n"
            % (self.table, ", ".join(self._columns))
        )
        self._fh.write(",\n".join(self._buf))
        if self.on_conflict:
            self._fh.write("\nON CONFLICT %s" % self.on_conflict)
        self._fh.write(";\n")
        self._buf.clear()

    def close(self) -> None:
        self._flush()
        self._fh.close()


class PgEmitter:
    """`Emitter.add()` cagrilarini Postgres satirlarina cevirir."""

    def __init__(self, out_dir: str) -> None:
        self.out_dir = out_dir
        self.parts_dir = os.path.join(out_dir, "_pgparts")
        os.makedirs(self.parts_dir, exist_ok=True)
        self._writers: dict[str, PgTableWriter] = {}
        self.counts: dict[str, int] = {}
        self.dropped: dict[str, int] = {}

    # -- yardimcilar --------------------------------------------------------

    def _writer(self, table: str) -> PgTableWriter:
        w = self._writers.get(table)
        if w is None:
            w = PgTableWriter(self.parts_dir, table)
            self._writers[table] = w
        return w

    def _ref(self, value: Rid) -> str:
        """Kayit referansini hedef tablosunun uuid'sine cevirir.

        Hedef tablonun anahtar stratejisi "text"/"name" ise referans da metin
        kalir — `settings` ve `kind_ref` boyle.
        """
        strategy = id_strategy(M.TABLE_RENAME.get(value.table, value.table))
        if strategy in ("text", "name"):
            return value.key
        return key_to_uuid(value.table, value.key)

    def _value(self, value):
        if isinstance(value, Rid):
            return self._ref(value)
        if isinstance(value, (list, tuple)):
            return [self._value(v) for v in value]
        if isinstance(value, dict):
            return {k: self._value(v) for k, v in value.items()}
        return value

    # -- ana yol ------------------------------------------------------------

    def add(self, table: str, row: dict) -> None:
        if table in M.DROP_TABLES:
            self.dropped[table] = self.dropped.get(table, 0) + 1
            return

        pg_table = M.TABLE_RENAME.get(table, table)
        strategy = id_strategy(pg_table)
        out: dict = {}

        # 1) birincil anahtar
        rid_value = row.get("id")
        key = rid_value.key if isinstance(rid_value, Rid) else rid_value
        if strategy == "uuid":
            if key is None:
                raise ConversionError("%s: id yok ama uuid bekleniyor" % table)
            out["id"] = key_to_uuid(table, key)
        elif strategy == "text":
            out["id"] = key
        elif strategy == "name":
            out["name"] = key
        # "composite" -> id hic yazilmaz; bilesenleri asagida geliyor.

        # 2) alanlar
        children: list[tuple[str, dict]] = []
        for field, value in row.items():
            if field == "id":
                continue
            if (table, field) in M.DROP_COLUMNS:
                continue
            child = M.CHILD_TABLES.get((table, field))
            if child is not None:
                children.extend(self._child_rows(table, row, value, child))
                continue
            prefix = M.FLATTEN.get((table, field))
            if prefix is not None:
                if value is None:
                    continue
                if not isinstance(value, dict):
                    raise ConversionError(
                        "%s.%s duzlestirilecekti ama nesne degil" % (table, field)
                    )
                for inner, inner_value in value.items():
                    out[prefix + inner] = self._value(inner_value)
                continue
            if table in M.IMAGE_CHILD and field in M.IMAGE_FIELDS:
                continue  # asagida toplu isleniyor
            out[M.COLUMN_RENAME.get(field, field)] = self._value(value)

        # 3) kimlik: kullanici satiri control tarafinda bir `person` dogurur
        #
        # Yeni backend'de parola okul veritabaninda DEGIL, control'deki
        # `person` satirinda duruyor; giris `person` -> `person_school` ->
        # `app_user.person` zincirinden geciyor. Bu zincir kurulmazsa tohum
        # yuklenir ama HIC KIMSE GIRIS YAPAMAZ — veri gorunur, sistem
        # kullanilamaz.
        if table == "user":
            person_id = str(mint_uuid7("%s:%s" % (M.PERSON_NS, row["username"])))
            out["person"] = person_id
            created = ulid_ms(key) if key and is_ulid(key) else 0
            children.append(("person", {
                "id": person_id,
                "username": row["username"],
                # Parola ozeti okul tarafindan control'e TASINIYOR; kopya
                # birakilmiyor, cunku yeni semada `app_user`in boyle bir
                # kolonu yok.
                "password_hash": row["password_hash"],
                "created_at": created,
            }))
            children.append(("person_school", {
                "person": person_id,
                # DEGER DEGIL IFADE: okul kaydini backend kendisi yaratmis
                # olabilir ve o zaman uuid bizim sabitledigimiz degildir.
                # Slug'a bakan bir alt sorgu iki akisi da calistirir:
                # tohum okulu kendisi kaydettiyse de, backend kaydettiyse de
                # uyelik dogru okula baglanir.
                "school": Raw(
                    "(SELECT id FROM school WHERE slug = '%s')"
                    % M.DEMO_SCHOOL_SLUG),
                "created_at": created,
            }))

        # 4) yeni semanin istedigi, eski semada olmayan kolonlar
        for (t, column), rule in M.DERIVED_COLUMNS.items():
            if t != table:
                continue
            if rule == "id_ulid_ms":
                out[column] = ulid_ms(key) if key and is_ulid(key) else 0
            elif rule.startswith("ulid_ms:"):
                ref = row.get(rule.split(":", 1)[1])
                if not isinstance(ref, Rid) or not is_ulid(ref.key):
                    raise ConversionError(
                        "%s.%s turetilemedi: %s bir ULID referansi degil"
                        % (table, column, rule)
                    )
                out[column] = ulid_ms(ref.key)
            else:
                raise ConversionError("bilinmeyen turetme kurali: %r" % rule)

        # 5) resim ucluleri
        if table in M.IMAGE_CHILD:
            child_table, owner = M.IMAGE_CHILD[table]
            values = [row.get(f) for f in M.IMAGE_FIELDS]
            if any(v is not None for v in values):
                if any(v is None for v in values):
                    raise ConversionError(
                        "%s: resim ucusu yarim (%r)" % (table, values)
                    )
                child_row = {owner: out.get("id") or self._value(rid_value)}
                child_row.update(dict(zip(M.IMAGE_COLUMNS, values)))
                children.append((child_table, child_row))

        self._writer(pg_table).add(apply_catalog(pg_table, out))
        for child_table, child_row in children:
            self._writer(child_table).add(apply_catalog(child_table, child_row))

    def _child_rows(self, table: str, row: dict, value, child) -> list:
        child_table, owner_col, value_col, has_ord = child
        if not value:
            return []
        if not isinstance(value, (list, tuple)):
            raise ConversionError(
                "%s.%s cocuk tabloya acilacakti ama dizi degil" % (table, value_col)
            )
        owner = row.get("id")
        owner_key = self._ref(owner) if isinstance(owner, Rid) else owner
        out = []
        for index, item in enumerate(value):
            child_row = {owner_col: owner_key, value_col: self._value(item)}
            if has_ord:
                child_row["ord"] = index
            out.append((child_table, child_row))
        return out

    # -- kapanis ------------------------------------------------------------

    def close_all(self) -> None:
        for table, writer in self._writers.items():
            writer.close()
            self.counts[table] = writer.count

    def order(self, layout) -> list:
        """Yukleme sirasi. Postgres yabanci anahtarlari GERCEKTEN zorluyor.

        Uretici satirlari bagimlilik sirasinda uretmiyor: kullanici satirlari
        en SONDA yaziliyor, cunku sayaclar once doldurulup sonra dokuluyor.
        SurrealQL tarafinda bu onemsizdi (FK yok) ve `FILE_LAYOUT` zaten dogru
        sirayi veriyordu. Postgres tarafinda ayni sirayi kullanmak SART: aksi
        halde `parent_link` kullanicidan once gelir ve yukleme ilk satirda
        duser.

        Cocuk tablolar ebeveyninin HEMEN ardina konur.
        """
        children: dict[str, list[str]] = {}
        for (parent, _field), spec in M.CHILD_TABLES.items():
            children.setdefault(parent, []).append(spec[0])
        for parent, (child, _owner) in M.IMAGE_CHILD.items():
            children.setdefault(parent, []).append(child)

        # Control tablolari FILE_LAYOUT'ta gecmez (o duzen okul veritabanina
        # aittir). Sirasi sabit ve bagimlilik yonunde: okul -> moduller ->
        # kisi -> uyelik.
        ordered: list[str] = []
        seen: set[str] = set()
        for table in ("school", "school_module", "person", "person_school"):
            if table in self._writers:
                ordered.append(table)
                seen.add(table)
        for _number, _name, tables in layout:
            for table in tables:
                candidates = [M.TABLE_RENAME.get(table, table)]
                candidates.extend(children.get(table, []))
                for candidate in candidates:
                    if candidate in self._writers and candidate not in seen:
                        ordered.append(candidate)
                        seen.add(candidate)

        # Duzende adi gecmeyen tablo kalmamali. Kalirsa sirasi BILINMIYOR
        # demektir; sessizce sona atmak, FK hatasini yukleme anina ertelemek
        # olurdu ve o an bu dosyadan cok uzakta.
        artik = [t for t in self._writers if t not in seen]
        if artik:
            raise ConversionError(
                "yukleme sirasinda yeri belli olmayan tablo(lar): %s"
                % sorted(artik)
            )
        return ordered

    def school_rows(self, created_ms: int, modules) -> None:
        """Control tarafindaki okul satiri ve modulleri.

        Okul KAYITLI olmadan veritabani erisilemez: `Tenants::get` once bu
        satiri arar. Tohum kendi okulunu kendisi kaydeder ki yukleme tek
        yonlu olsun — backend acildiginda okulu hazir ve `active` bulur.
        """
        # Okul kaydi zaten varsa (backend yaratmissa) dokunulmaz.
        self._writer("school").on_conflict = "(slug) DO NOTHING"
        self._writer("school_module").on_conflict = "(school, module) DO NOTHING"
        self._writer("school").add({
            "id": M.DEMO_SCHOOL_ID,
            "slug": M.DEMO_SCHOOL_SLUG,
            "name": M.DEMO_SCHOOL_NAME,
            "status": "active",
            "created_at": created_ms,
        })
        for module in modules:
            self._writer("school_module").add({
                "school": M.DEMO_SCHOOL_ID,
                "module": module,
            })

    def assemble(self, layout) -> list:
        """Parcalari `control` ve `school` dosyalarina birlestirir."""
        ordered = self.order(layout)
        files = []
        groups = (
            ("control", [t for t in ordered if t in M.CONTROL_TABLES]),
            ("school", [t for t in ordered if t not in M.CONTROL_TABLES]),
        )
        for name, tables in groups:
            if not tables:
                continue
            path = os.path.join(self.out_dir, "pg_%s.sql" % name)
            with open(path, "w", encoding="utf-8", newline="\n") as out:
                total = sum(self.counts.get(t, 0) for t in tables)
                out.write("-- Hezarfen tohum verisi (PostgreSQL) - %s\n" % name)
                out.write("-- Uretici: generator/pg_emit.py\n")
                out.write("-- SurrealQL ciktisiyla AYNI gecisten, ayni satirlardan.\n")
                out.write("--\n-- Tablolar, YUKLEME SIRASINDA:\n")
                for table in tables:
                    out.write(
                        "--   %-28s %8d satir\n" % (table, self.counts.get(table, 0))
                    )
                out.write("--   %-28s %8d satir\n" % ("TOPLAM", total))
                out.write("--\n")
                out.write("-- Tek transaction: yarim yuklenmis bir tohum,\n")
                out.write("-- hic yuklenmemis olandan daha kotudur.\n")
                out.write("BEGIN;\n\n")
                for table in tables:
                    part = os.path.join(self.parts_dir, "%s.pgpart" % table)
                    with open(part, encoding="utf-8") as fh:
                        out.write(fh.read())
                    out.write("\n")
                out.write("COMMIT;\n")
            files.append((os.path.basename(path), os.path.getsize(path)))
        return files
