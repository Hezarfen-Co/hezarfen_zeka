"""Üretilen .surql çıktısını satır satır okuyup doğrular.

Kontroller:
  (a) çıktıdaki her tablo adı `schema.json`'da tanımlı mı,
  (b) her satırdaki her alan adı o tablonun şemasında tanımlı mı,
  (c) her enum değeri geçerli listede mi,
  (d) her `record<>` referansı daha önce üretilmiş bir kimliğe mi işaret ediyor,
  (e) sayaçlar gerçek satır sayımıyla uyuşuyor mu,
  (f) T_NOW sonrası "gerçekleşmiş" kayıt (oturum / cevap / yoklama) var mı,
  (g) kimlik kaçışlaması, seq=1 kuralı (E3), gün numarası (E2), para ve puan
      sınırları, rol kısıtı ve tekil indeks çakışmaları.

Kullanım:
    python selfcheck.py ../seed
"""

from __future__ import annotations

import json
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import config as C
import content_tr as TXT

LANGLE = "⟨"
RANGLE = "⟩"

# --------------------------------------------------------------------------
# Küçük ayrıştırıcı — yalnız bu üreticinin yazdığı biçimi okur
# --------------------------------------------------------------------------

TOKEN = re.compile(r"""
    (?P<record>[A-Za-z_][A-Za-z0-9_]*:⟨[^⟩]*⟩)
  | (?P<string>'(?:\\.|[^'\\])*')
  | (?P<dstring>"(?:\\.|[^"\\])*")
  | (?P<number>-?\d+(?:\.\d+)?)
  | (?P<none>\bNONE\b|\bNULL\b)
  | (?P<bool>\btrue\b|\bfalse\b)
  | (?P<punct>[\{\}\[\],:])
  | (?P<ident>[A-Za-z_][A-Za-z0-9_.*]*)
""", re.VERBOSE)


class Parser:
    def __init__(self, text):
        self.tokens = [m for m in TOKEN.finditer(text)]
        self.i = 0

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def next(self):
        m = self.tokens[self.i]
        self.i += 1
        return m

    def value(self):
        m = self.next()
        kind = m.lastgroup
        text = m.group()
        if kind == "record":
            table, key = text.split(":", 1)
            return ("record", table, key[1:-1])
        if kind in ("string", "dstring"):
            return _unescape(text[1:-1])
        if kind == "number":
            return float(text) if "." in text else int(text)
        if kind == "none":
            return None
        if kind == "bool":
            return text == "true"
        if kind == "punct" and text == "[":
            out = []
            while True:
                nxt = self.peek()
                if nxt is None:
                    break
                if nxt.group() == "]":
                    self.next()
                    break
                if nxt.group() == ",":
                    self.next()
                    continue
                out.append(self.value())
            return out
        if kind == "punct" and text == "{":
            return self.object_body()
        raise ValueError("beklenmeyen belirteç: %r" % text)

    def object_body(self):
        obj = {}
        while True:
            m = self.peek()
            if m is None:
                break
            if m.group() == "}":
                self.next()
                break
            if m.group() == ",":
                self.next()
                continue
            key = self.next().group()
            colon = self.next()
            assert colon.group() == ":", colon.group()
            obj[key] = self.value()
        return obj


def _unescape(text):
    return (text.replace("\\\\", "\x00").replace("\\'", "'").replace('\\"', '"')
            .replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t")
            .replace("\x00", "\\"))


def parse_row(line):
    p = Parser(line.strip().rstrip(","))
    first = p.next()
    assert first.group() == "{", first.group()
    return p.object_body()


# --------------------------------------------------------------------------
# Doğrulama
# --------------------------------------------------------------------------

ENUM_FIELDS = {
    ("user", "role"): ["parent", "student", "teacher", "manager", "admin"],
    ("user", "theme"): ["light", "dark"],
    ("user", "language"): ["tr", "en"],
    ("message", "sender_folder"): ["sent", "archive", "trash"],
    ("message", "recipient_folder"): ["inbox", "archive", "trash"],
    ("message", "sender_origin"): ["sent", "inbox", "archive", "trash"],
    ("message", "recipient_origin"): ["sent", "inbox", "archive", "trash"],
    ("chatbot_message", "role"): ["user", "assistant"],
    ("chatbot_message", "status"): ["pending", "complete", "failed"],
    ("appointment", "status"): ["pending", "approved", "rejected", "cancelled"],
    ("meal_booking", "status"): ["booked", "cancelled"],
    ("meal_attendance", "status"): ["served", "missed"],
    ("meal_ledger", "kind"): ["charge", "credit", "reversal"],
    ("payment_ledger", "kind"): ["charge", "credit", "reversal", "refund"],
    ("course", "kind"): ["course", "study", "club"],
    ("exam", "mode"): ["sync", "async", "open"],
    ("exam", "kind"): C.EXAM_KINDS,
    ("exam_question", "kind"): ["choice", "text"],
    ("bank_question", "kind"): ["choice", "text"],
    ("bank_question", "visibility"): ["private", "school"],
    ("homework_result", "status"): ["done", "incomplete", "missing"],
    ("pool_question", "status"): ["pending", "approved"],
    ("board_stroke", "kind"): ["stroke", "clear"],
    ("attendance", "status"): ["present", "absent", "late", "excused"],
    ("session_attendance", "status"): ["present", "absent", "late", "excused"],
    ("menu", "slot"): C.MEAL_SLOTS,
    ("question_image", "content_type"): ["image/png", "image/jpeg", "image/webp",
                                         "image/gif"],
    ("bank_question_image", "content_type"): ["image/png", "image/jpeg", "image/webp",
                                              "image/gif"],
    ("badge_award", "badge"): [b[0] for b in C.BADGES],
}

# Sayaç -> (sayılan tablo, sayaç satırına işaret eden alan, ek filtre)
COUNTER_CHECKS = [
    ("course", "enrollment_count", "enrollment", "course", None),
    ("subject", "exam_question_count", "exam_question", "subject", None),
    ("subject", "homework_count", "homework", "subject", None),
    ("exam", "result_count", "exam_result", "exam", None),
    ("class_group", "class_member_count", "class_member", "class", None),
    ("class_group", "class_course_count", "class_course", "class", None),
    ("event", "registration_count", "registration", "event", None),
    ("note", "file_count", "note_file", "note", None),
    ("course_note", "file_count", "course_note_file", "course_note", None),
    ("homework_submission", "file_count", "homework_file", "submission", None),
    ("menu", "seats_booked", "meal_booking", "menu", ("status", "booked")),
    ("fee_plan", "assignment_count", "fee_plan_assignment", "plan", None),
    ("board", "total_stroke_count", "board_stroke", "board", None),
    ("user", "board_count", "board", "creator", None),
    ("user", "chatbot_thread_count", "chatbot_thread", "user_id", None),
]

MONEY_FIELDS = {("menu_dish", "price_minor"): C.MAX_DISH_PRICE_MINOR,
                ("meal_booking", "price_minor"): C.MAX_LEDGER_AMOUNT_MINOR,
                ("meal_ledger", "amount_minor"): C.MAX_LEDGER_AMOUNT_MINOR,
                ("payment_ledger", "amount_minor"): C.MAX_LEDGER_AMOUNT_MINOR}

# Şemadaki tek FLEXIBLE nesne (migration_sql.rs:211)
FLEXIBLE_FIELDS = {("rag_output", "payload")}

# ULID kimliğin zaman öneki, satırın kendi zaman damgasıyla aynı olmalıdır
# (schema.json -> id_syntax.ulid_time_consistency). tablo -> damga alanı
ULID_TIME_FIELDS = {
    "board": "created_at", "board_stroke": "created_at", "message": "sent_at",
    "pool_question": "asked_at", "solution": "offered_at",
    "chatbot_thread": "created_at", "chatbot_message": "created_at",
    "homework": "created_at", "homework_file": "created_at",
    "appointment": "created_at", "appointment_slot": "created_at",
    "menu_dish": "created_at", "bank_question": "created_at",
    "rag_output": "generated_at", "pomodoro_session": "started_at",
    "course_session": "starts_at",
}

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid_time(key):
    value = 0
    for ch in key[:10]:
        idx = CROCKFORD.find(ch)
        if idx < 0:
            return None
        value = value * 32 + idx
    return value


# --------------------------------------------------------------------------
# Metin kalitesi esikleri (koordinator denetimi, Kusur 1-3)
# --------------------------------------------------------------------------

# (1) exam_question.choices[*].text: en az bu kadar tekil metin olmali ve tek
#     bir metnin tum siklar icindeki payi bu orani gecmemeli
MIN_UNIQUE_CHOICE_TEXTS = 3000
MAX_CHOICE_TEXT_SHARE = 0.02

# (2) exam_question.text: en az bu kadar tekil soru koku
MIN_UNIQUE_QUESTION_STEMS = 2500

# (2b) AYNI SINAV icinde tekrar eden soru koku sayisi. Gercek bir sinavda ayni
#      soru iki kez sorulmaz. Sinavlar ARASI yeniden kullanim (banka sablonu
#      paylasimi, SENARYO 4.8) bilinclidir ve bu esige girmez.
MAX_SAME_EXAM_DUPLICATE_STEMS = 0

# (3) exam_answer.text: azami uzunluk ve "tam cumle" kurali
MAX_ANSWER_TEXT_LEN = 400
ANSWER_TEXT_ENDINGS = (".", "!", "?", ")", "\u2026")

# (4) Ters bolulu tirnak kacisi cikti dosyalarinda HIC bulunmamali.
#     (emit.sq_string tek tirnak iceren degeri cift tirnakli yazar.)
BACKSLASH_QUOTE = "\\'"

# (5) Konu-kavram uyumu: sayisal derslerde kokte gecen konu adi ile kokte /
#     siklarda gecen kavram ayni konu havuzundan olmali. Ihlal orani esigi:
MAX_TOPIC_MISMATCH_SHARE = 0.02

_SUBJECT_POOLS = TXT.SUBJECT_CONCEPTS
# Uzun adlar once: "Hucre Bolunmeleri (Mitoz)" ile "Hucre" karismasin
_SUBJECT_NAMES_BY_LEN = sorted(_SUBJECT_POOLS, key=len, reverse=True)
_ALL_TOPIC_CONCEPTS = set()
for _pool in _SUBJECT_POOLS.values():
    _ALL_TOPIC_CONCEPTS.update(_pool)
# Birim sozcukleri kavram taramasindan cikarilir ("44 birim" bir kavram degildir)
_UNIT_WORDS = {u for lst in TXT.UNITS.values() for u in lst}
_UNIT_WORDS |= {u for lst in TXT.SUBJECT_UNITS.values() for u in lst}
_ALL_TOPIC_CONCEPTS -= _UNIT_WORDS

# Kavram aramasi SOZCUK SINIRINA duyarli olmali: "gen" kavrami
# "genisletilmistir" icinde gecmis sayilmaz, "is" da "islem" icinde.
_CONCEPT_RE = {c: re.compile(r"(?<!\w)%s(?!\w)" % re.escape(c), re.IGNORECASE)
               for c in _ALL_TOPIC_CONCEPTS}


def _has_concept(blob, concept):
    return _CONCEPT_RE[concept].search(blob) is not None

FUTURE_FORBIDDEN = [("course_session", "starts_at"), ("exam_answer", "updated_at"),
                    ("pomodoro_session", "started_at"), ("homework_submission", "submitted_at"),
                    ("exam_attempt", "started_at")]


class Checker:
    def __init__(self, seed_dir, schema_path):
        self.dir = seed_dir
        with open(schema_path, "r", encoding="utf-8") as fh:
            self.schema = json.load(fh)
        with open(os.path.join(seed_dir, "MANIFEST.json"), "r", encoding="utf-8") as fh:
            self.manifest = json.load(fh)
        self.t_now = self.manifest["uretim"]["t_now_ms"]
        self.errors = []
        self.warnings = []
        self.seen_ids = set()
        self.counts = {}
        self.counter_values = {}     # (tablo, alan) -> {id: değer}
        self.ref_counts = {}         # (tablo, alan) -> {hedef: adet}
        self.user_roles = {}
        self.choice_texts = {}       # metin -> adet
        self.stem_texts = {}
        self.exam_stem_pairs = {}    # (sınav, kök) -> adet
        self.answer_len_sum = 0
        self.answer_len_n = 0
        self.answer_len_max = 0
        self.answer_lens = []
        self.subject_names = {}      # subject:<id> -> ad
        self.topic_checked = 0
        self.topic_violations = 0
        self.topic_examples = []
        self.topic_by_concept = {}
        self.syntax_stats = {"dosya": 0, "tek_tirnakli": 0, "cift_tirnakli": 0,
                             "ters_bolu_tirnak": 0, "kacisli_cift_tirnak": 0}

    def fail(self, msg):
        if len(self.errors) < 60:
            self.errors.append(msg)

    # -- (a)(b)(c)(d)(f)(g) --------------------------------------------
    def run(self):
        files = sorted(f for f in os.listdir(self.dir)
                       if f.endswith(".surql") and f[0].isdigit())
        for name in files:
            # Sözdizimi taraması TÜM .surql dosyalarını kapsar (00 ve 99 dahil)
            self.check_syntax(os.path.join(self.dir, name))
        for name in files:
            if name.startswith("00_") or name.startswith("99_"):
                continue
            self.scan_file(os.path.join(self.dir, name))
        self.check_counters()
        self.check_text_quality()
        self.check_topic_match()
        self.check_manifest_counts()
        return self.errors

    # -- (k) dize kaçışlaması ve sözdizimi -------------------------------
    def check_syntax(self, path):
        """Dize-farkında tarama: `\\'` yok mu, dizeler kapanıyor mu, parantezler dengeli mi.

        Yükleme öncesi elimizdeki tek sözdizimi güvencesi budur; SurrealDB'yi
        çalıştırmadan yakalanabilecek hataların tamamı buradan geçer.
        """
        fname = os.path.basename(path)
        self.syntax_stats["dosya"] += 1
        depth_sq = 0        # [ ]
        depth_br = 0        # { }
        with open(path, "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                if BACKSLASH_QUOTE in line:
                    self.fail("%s:%d ters bölülü tırnak kaçışı (\\') bulundu — "
                              "kaçış varsayıma bırakılmamalı" % (fname, lineno))
                    self.syntax_stats["ters_bolu_tirnak"] += 1
                i = 0
                n = len(line)
                in_str = None
                while i < n:
                    ch = line[i]
                    if in_str is None:
                        if ch == "-" and line[i:i + 2] == "--":
                            break                     # satır sonuna kadar yorum
                        if ch in ("'", '"'):
                            in_str = ch
                            self.syntax_stats["tek_tirnakli" if ch == "'"
                                              else "cift_tirnakli"] += 1
                        elif ch == "[":
                            depth_sq += 1
                        elif ch == "]":
                            depth_sq -= 1
                        elif ch == "{":
                            depth_br += 1
                        elif ch == "}":
                            depth_br -= 1
                        if depth_sq < 0 or depth_br < 0:
                            self.fail("%s:%d fazladan kapanış parantezi" % (fname, lineno))
                            return
                    else:
                        if ch == "\\":
                            if in_str == '"' and line[i + 1:i + 2] == '"':
                                self.syntax_stats["kacisli_cift_tirnak"] += 1
                            i += 2                    # kaçışlanan karakteri atla
                            continue
                        if ch == in_str:
                            in_str = None
                    i += 1
                if in_str is not None:
                    self.fail("%s:%d satır sonunda kapanmamış dize (%s)"
                              % (fname, lineno, in_str))
                    return
        if depth_sq != 0 or depth_br != 0:
            self.fail("%s: dosya sonunda dengesiz parantez ([]=%d, {}=%d)"
                      % (fname, depth_sq, depth_br))

    def scan_file(self, path):
        table = None
        fields = None
        with open(path, "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                stripped = line.strip()
                if stripped.startswith("INSERT INTO "):
                    table = stripped[len("INSERT INTO "):].split()[0]
                    if (table not in self.schema["tables"]
                            and table not in self.schema["control_tables"]):
                        self.fail("%s: bilinmeyen tablo %s" % (os.path.basename(path), table))
                        fields = {}
                    else:
                        fields = self.schema["tables"].get(table) or \
                            self.schema["control_tables"][table]
                        fields = fields["fields"]
                    continue
                if not stripped.startswith("{"):
                    continue
                try:
                    row = parse_row(stripped)
                except Exception as exc:      # pragma: no cover
                    self.fail("%s:%d ayrıştırma hatası: %s" % (path, lineno, exc))
                    continue
                self.check_row(os.path.basename(path), lineno, table, fields, row)

    def check_row(self, fname, lineno, table, fields, row):
        self.counts[table] = self.counts.get(table, 0) + 1
        rid = row.get("id")
        if not isinstance(rid, tuple):
            self.fail("%s:%d %s satırında id yok veya kaçışlanmamış" % (fname, lineno, table))
            return
        _, rtable, rkey = rid
        if rtable != table:
            self.fail("%s:%d id tablosu (%s) satır tablosuyla (%s) uyuşmuyor"
                      % (fname, lineno, rtable, table))
        full_id = "%s:%s" % (rtable, rkey)
        if full_id in self.seen_ids:
            self.fail("%s:%d yinelenen kimlik %s" % (fname, lineno, full_id))
        self.seen_ids.add(full_id)

        # E3: seq = 1 kaydın id'sinde _1 eki olmaz
        if table in ("exam_attempt", "exam_answer", "exam_result", "answer_image"):
            if rkey.endswith("_1"):
                self.fail("%s:%d E3 ihlali: seq=1 kimliğinde _1 eki (%s)"
                          % (fname, lineno, full_id))
            seq = row.get("seq")
            if seq == 1 and rkey.count("_") > 1 and rkey.split("_")[-1].isdigit():
                self.fail("%s:%d seq=1 ama kimlikte sıra eki var (%s)"
                          % (fname, lineno, full_id))
            if isinstance(seq, int) and seq > 1 and not rkey.endswith("_%d" % seq):
                self.fail("%s:%d seq=%s ama kimlik eki yok (%s)"
                          % (fname, lineno, seq, full_id))

        for key, value in row.items():
            if key == "id":
                continue
            if key not in fields:
                self.fail("%s:%d %s.%s şemada yok" % (fname, lineno, table, key))
                continue
            self.check_value(fname, lineno, table, key, value, fields)

        if table == "user":
            self.user_roles[full_id] = row.get("role")
        if table == "message":
            s = row.get("sender")
            r = row.get("recipient")
            if isinstance(s, tuple) and isinstance(r, tuple):
                sr = self.user_roles.get("user:%s" % s[2])
                rr = self.user_roles.get("user:%s" % r[2])
                if sr in ("student", "parent") and rr in ("student", "parent"):
                    self.fail("%s:%d rol kısıtı ihlali: %s -> %s" % (fname, lineno, sr, rr))

        # (f) T_NOW sonrası gerçekleşmiş kayıt
        for tname, field in FUTURE_FORBIDDEN:
            if table == tname and isinstance(row.get(field), int) and row[field] > self.t_now:
                self.fail("%s:%d %s.%s T_NOW sonrası (%d)"
                          % (fname, lineno, table, field, row[field]))
        if table == "user":
            for field in ("study_streak_last_day", "pomodoro_counted_day"):
                v = row.get(field)
                if isinstance(v, int) and v > 1_000_000:
                    self.fail("%s:%d E2 ihlali: %s ms gibi görünüyor (%d)"
                              % (fname, lineno, field, v))
                if isinstance(v, int) and 0 < v < 700_000:
                    self.fail("%s:%d E2 ihlali: %s gün numarası değil (%d)"
                              % (fname, lineno, field, v))
        if table == "exam_question":
            pts = row.get("points")
            if not isinstance(pts, int) or not (1 <= pts <= 100):
                self.fail("%s:%d exam_question.points aralık dışı: %r" % (fname, lineno, pts))
        if table in ("exam_result", "homework_result"):
            mark = row.get("mark")
            if mark is not None and not (0 <= mark <= 100):
                self.fail("%s:%d %s.mark aralık dışı: %r" % (fname, lineno, table, mark))
        if table == "subject":
            self.subject_names[full_id] = row.get("name")

        # Metin kalitesi toplayicilari (Kusur 1-3)
        if table == "exam_question":
            stem = row.get("text")
            if isinstance(stem, str):
                self.stem_texts[stem] = self.stem_texts.get(stem, 0) + 1
                self._check_topic(fname, lineno, stem, row.get("choices"))
                exam = row.get("exam")
                if isinstance(exam, tuple):
                    pair = ("%s:%s" % (exam[1], exam[2]), stem)
                    self.exam_stem_pairs[pair] = self.exam_stem_pairs.get(pair, 0) + 1
            choices = row.get("choices")
            if isinstance(choices, list):
                local = set()
                for ch in choices:
                    txt = ch.get("text") if isinstance(ch, dict) else None
                    if not isinstance(txt, str):
                        continue
                    self.choice_texts[txt] = self.choice_texts.get(txt, 0) + 1
                    if txt in local:
                        self.fail("%s:%d aynı sorunun iki şıkkı aynı metne sahip: %r"
                                  % (fname, lineno, txt[:40]))
                    local.add(txt)
        if table == "exam_answer":
            txt = row.get("text")
            if isinstance(txt, str):
                n = len(txt)
                self.answer_len_sum += n
                self.answer_len_n += 1
                self.answer_len_max = max(self.answer_len_max, n)
                if len(self.answer_lens) < 400000:
                    self.answer_lens.append(n)
                if n > MAX_ANSWER_TEXT_LEN:
                    self.fail("%s:%d exam_answer.text %d karakter (üst sınır %d)"
                              % (fname, lineno, n, MAX_ANSWER_TEXT_LEN))
                if not txt.rstrip().endswith(ANSWER_TEXT_ENDINGS):
                    self.fail("%s:%d exam_answer.text kelime ortasından kesilmiş: %r"
                              % (fname, lineno, txt[-30:]))

        if table == "menu" and len(row.get("date") or "") != 10:
            self.fail("%s:%d menu.date 10 karakter değil" % (fname, lineno))

        # (h) ULID zaman öneki tutarlılığı
        ts_field = ULID_TIME_FIELDS.get(table)
        if ts_field and not rkey.startswith("open_") and len(rkey) == 26:
            want = row.get(ts_field)
            got = ulid_time(rkey)
            if isinstance(want, int) and got is not None and got != want:
                self.fail("%s:%d %s kimliğinin zaman öneki %s ile uyuşmuyor (%d != %d)"
                          % (fname, lineno, table, ts_field, got, want))

        # sayaç ve referans toplama
        for t, field, _c, _r, _f in COUNTER_CHECKS:
            if table == t and field in row and row[field] is not None:
                self.counter_values.setdefault((t, field), {})[full_id] = row[field]
        for _t, _field, counted, ref_field, extra in COUNTER_CHECKS:
            if table == counted:
                if extra and row.get(extra[0]) != extra[1]:
                    continue
                target = row.get(ref_field)
                if isinstance(target, tuple):
                    k = "%s:%s" % (target[1], target[2])
                    d = self.ref_counts.setdefault((_t, _field), {})
                    d[k] = d.get(k, 0) + 1

    def check_value(self, fname, lineno, table, key, value, fields):
        spec = fields[key]
        ftype = spec["type"]
        if value is None:
            if not spec["optional"] and spec.get("default") is None:
                self.fail("%s:%d %s.%s zorunlu ama NONE" % (fname, lineno, table, key))
            return
        if isinstance(value, tuple) and value[0] == "record":
            target = "%s:%s" % (value[1], value[2])
            if "record<" in ftype:
                want = ftype.split("record<")[1].split(">")[0]
                if value[1] != want:
                    self.fail("%s:%d %s.%s %s bekleniyordu, %s geldi"
                              % (fname, lineno, table, key, want, value[1]))
                if target not in self.seen_ids:
                    self.fail("%s:%d %s.%s henüz üretilmemiş kimliğe işaret ediyor: %s"
                              % (fname, lineno, table, key, target))
            else:
                # option<record> (tipsiz) — ileri referansa izin verilir
                if target not in self.seen_ids:
                    self.warnings.append("%s.%s ileri referans: %s" % (table, key, target))
            return
        enum = ENUM_FIELDS.get((table, key))
        if enum is not None and isinstance(value, str) and value not in enum:
            self.fail("%s:%d %s.%s geçersiz enum: %r" % (fname, lineno, table, key, value))
        limit = MONEY_FIELDS.get((table, key))
        if limit is not None and isinstance(value, int) and not (0 <= value <= limit):
            self.fail("%s:%d %s.%s para sınırı dışı: %d" % (fname, lineno, table, key, value))
        if ftype.replace("option<", "").rstrip(">") == "int" and isinstance(value, float):
            self.fail("%s:%d %s.%s int olmalı, ondalık yazıldı" % (fname, lineno, table, key))
        if isinstance(value, list):
            for item in value:
                if isinstance(item, tuple) and item[0] == "record":
                    target = "%s:%s" % (item[1], item[2])
                    if target not in self.seen_ids:
                        self.fail("%s:%d %s.%s dizi öğesi üretilmemiş kimliğe işaret ediyor: %s"
                                  % (fname, lineno, table, key, target))
        if isinstance(value, dict):
            if (table, key) in FLEXIBLE_FIELDS:
                return          # rag_output.payload — tek FLEXIBLE nesne
            for sub, subval in value.items():
                path = "%s.%s" % (key, sub)
                if path not in fields:
                    self.fail("%s:%d %s.%s şemada yok" % (fname, lineno, table, path))

    def check_counters(self):
        for table, field, counted, _ref, _extra in COUNTER_CHECKS:
            values = self.counter_values.get((table, field), {})
            actual = self.ref_counts.get((table, field), {})
            for rid, value in values.items():
                real = actual.get(rid, 0)
                if value != real:
                    self.fail("SAYAÇ: %s.%s = %s, gerçek %s (%s)"
                              % (table, field, value, real, rid))
            for rid, real in actual.items():
                if rid not in values and real > 0:
                    self.fail("SAYAÇ: %s.%s yazılmamış ama %d satır var (%s)"
                              % (table, field, real, rid))

    def _check_topic(self, fname, lineno, stem, choices):
        """Kökte geçen konu adı ile kullanılan kavramlar aynı havuzdan mı?

        Banka kökenli sorularda `subject` alanı başka bir seviyenin konusunu
        gösterebilir (§4.8 çapraz-seviye kullanımı bilinçlidir); bu yüzden
        ölçüt, kaydın konusu değil **kökün içinde geçen konu adıdır**.
        """
        topic = None
        for name in _SUBJECT_NAMES_BY_LEN:
            if name in stem:
                topic = name
                break
        if topic is None:
            return                      # sözel ders ya da konu-nötr kök
        own = set(_SUBJECT_POOLS[topic])
        blob = stem
        if isinstance(choices, list):
            for ch in choices:
                if isinstance(ch, dict) and isinstance(ch.get("text"), str):
                    blob += " " + ch["text"]
        # Konu ADI kavram taramasından çıkarılır: "Hücre Bölünmeleri" başlığı
        # "hücre" kavramını içeriyor diye uyumsuzluk sayılmamalı.
        blob = blob.replace(topic, " ")
        self.topic_checked += 1
        for concept in _ALL_TOPIC_CONCEPTS - own:
            if not _has_concept(blob, concept):
                continue
            # Kendi havuzundaki daha uzun bir kavramın parçasıysa ihlal sayılmaz
            if any(concept in o and _has_concept(blob, o) for o in own):
                continue
            self.topic_violations += 1
            self.topic_by_concept[concept] = self.topic_by_concept.get(concept, 0) + 1
            if len(self.topic_examples) < 5:
                self.topic_examples.append("%s:%d [%s] yabancı kavram: %r"
                                           % (fname, lineno, topic, concept))
            return

    def check_topic_match(self):
        if not self.topic_checked:
            return
        share = self.topic_violations / self.topic_checked
        self.topic_share = share
        if share > MAX_TOPIC_MISMATCH_SHARE:
            self.fail("KONU: kavram uyumsuzluğu %%%.2f (eşik %%%.1f) — %d / %d soru"
                      % (share * 100, MAX_TOPIC_MISMATCH_SHARE * 100,
                         self.topic_violations, self.topic_checked))
            top = sorted(self.topic_by_concept.items(), key=lambda kv: -kv[1])[:8]
            self.fail("KONU en sık uyumsuz kavramlar: %s"
                      % ", ".join("%s (%d)" % (c, n) for c, n in top))
            for ex in self.topic_examples:
                self.fail("KONU örneği: %s" % ex)

    def check_text_quality(self):
        """Kusur 1-3: sik metni cesitliligi, soru koku cesitliligi, cevap uzunlugu."""
        total_choices = sum(self.choice_texts.values())
        uniq = len(self.choice_texts)
        if total_choices:
            if uniq < MIN_UNIQUE_CHOICE_TEXTS:
                self.fail("METİN: tekil şık metni %d, eşik %d"
                          % (uniq, MIN_UNIQUE_CHOICE_TEXTS))
            top_text, top_n = max(self.choice_texts.items(), key=lambda kv: kv[1])
            share = top_n / total_choices
            if share > MAX_CHOICE_TEXT_SHARE:
                self.fail("METİN: en sık şık metni payı %%%.2f (eşik %%%.1f) — %r"
                          % (share * 100, MAX_CHOICE_TEXT_SHARE * 100, top_text[:50]))
            self.text_stats = {
                "sik_toplam": total_choices, "sik_tekil": uniq,
                "sik_en_sik_pay_pct": round(share * 100, 3),
                "sik_en_sik_metin": top_text,
            }
        uniq_stems = len(self.stem_texts)
        if self.stem_texts and uniq_stems < MIN_UNIQUE_QUESTION_STEMS:
            self.fail("METİN: tekil soru kökü %d, eşik %d"
                      % (uniq_stems, MIN_UNIQUE_QUESTION_STEMS))
        total_stems = sum(self.stem_texts.values())
        # Aynı sınav içinde tekrar (olmamalı) ve sınavlar arası yeniden
        # kullanım (bilinçli: banka şablonu paylaşımı) ayrı ayrı sayılır.
        same_exam_dups = sum(n - 1 for n in self.exam_stem_pairs.values() if n > 1)
        cross_exam_reuse = total_stems - uniq_stems
        self.stem_stats = {"kok_toplam": total_stems, "kok_tekil": uniq_stems,
                           "sinav_ici_tekrar": same_exam_dups,
                           "sinavlar_arasi_yeniden_kullanim": cross_exam_reuse}
        if same_exam_dups > MAX_SAME_EXAM_DUPLICATE_STEMS:
            self.fail("METİN: aynı sınav içinde tekrar eden soru kökü %d (eşik %d)"
                      % (same_exam_dups, MAX_SAME_EXAM_DUPLICATE_STEMS))
            worst = sorted((kv for kv in self.exam_stem_pairs.items() if kv[1] > 1),
                           key=lambda kv: -kv[1])[:3]
            for (exam, stem), n in worst:
                self.fail("METİN örneği: %s içinde %d kez: %r" % (exam, n, stem[:60]))

    def check_manifest_counts(self):
        for table, expected in self.manifest["tablo_satir_sayilari"].items():
            got = self.counts.get(table, 0)
            if got != expected:
                self.fail("MANIFEST: %s %d satır bildiriyor, dosyada %d var"
                          % (table, expected, got))


def main(argv):
    seed_dir = argv[1] if len(argv) > 1 else os.path.normpath(
        os.path.join(BASE, "..", "seed"))
    schema = argv[2] if len(argv) > 2 else os.path.normpath(
        os.path.join(BASE, "..", "spec", "schema.json"))
    checker = Checker(seed_dir, schema)
    errors = checker.run()
    total = sum(checker.counts.values())
    print("Denetlenen dizin : %s" % seed_dir)
    print("Tablo / satır    : %d / %d" % (len(checker.counts), total))
    print("Tekil kimlik     : %d" % len(checker.seen_ids))
    stats = getattr(checker, "text_stats", None)
    if stats:
        print("Şık metni        : %d şık / %d tekil / en sık %%%.3f"
              % (stats["sik_toplam"], stats["sik_tekil"], stats["sik_en_sik_pay_pct"]))
    stems = getattr(checker, "stem_stats", None)
    if stems:
        print("Soru kökü        : %d soru / %d tekil kök"
              % (stems["kok_toplam"], stems["kok_tekil"]))
        print("  sınav içi tekrar: %d (eşik %d) / sınavlar arası yeniden kullanım: %d"
              % (stems["sinav_ici_tekrar"], MAX_SAME_EXAM_DUPLICATE_STEMS,
                 stems["sinavlar_arasi_yeniden_kullanim"]))
    if checker.answer_len_n:
        lens = sorted(checker.answer_lens)
        med = lens[len(lens) // 2]
        print("Metin cevabı     : %d cevap / ortanca %d / azami %d karakter"
              % (checker.answer_len_n, med, checker.answer_len_max))
    if checker.topic_checked:
        print("Konu-kavram uyumu: %d sayısal soru / %d uyumsuz (%%%.2f)"
              % (checker.topic_checked, checker.topic_violations,
                 100.0 * checker.topic_violations / checker.topic_checked))
    st = checker.syntax_stats
    print("Sözdizimi        : %d dosya dengeli / %d tek tırnaklı, %d çift tırnaklı dize"
          % (st["dosya"], st["tek_tirnakli"], st["cift_tirnakli"]))
    print("Tırnak kaçışı    : \\' sayısı %d (sıfır olmalı) / çift tırnakta kaçış %d"
          % (st["ters_bolu_tirnak"], st["kacisli_cift_tirnak"]))
    if checker.warnings:
        print("Uyarı            : %d ileri referans (tipsiz option<record>)"
              % len(checker.warnings))
        for w in checker.warnings[:3]:
            print("    %s" % w)
    if errors:
        print("\nHATA (%d):" % len(errors))
        for e in errors:
            print("  - %s" % e)
        return 1
    print("\nTEMİZ: şema, enum, referans, sayaç ve zaman kontrolleri geçti.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
