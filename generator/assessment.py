"""Değerlendirme alanı: sınav, soru bankası, soru, deneme, cevap, sonuç.

Madde modeli (SENARYO §4):
    theta_ui = theta_u(t) + delta_u(ders) + delta_u(konu) + phi_u(sinav) + eps
    P(dogru)  = c_i + (1 - c_i) * sigmoid(a_i * (theta_ui - b_i))
    P(bos)    = clip(omega_u * sigmoid(1.40 * (b_i - theta_ui)) * tau, 0.01, 0.58)

`a_i`, `b_i`, `c_i` DB'ye yazılmaz; yalnız `_seed_manifest.json`'a gider.
Cevap satırının YOKLUĞU boş bırakmadır (§4.6) — satır yazılmaz.
"""

from __future__ import annotations

import datetime as _dt
import math

import config as C
import content_tr as TXT
import dists as D
import timeline as T
from ids import UlidFactory, random_ulid, rid, seq_key, substream


class Item:
    """Bir madde kimliği: ya bir banka şablonu ya da tek kullanımlık soru."""
    __slots__ = ("a", "b", "c", "k", "misconception", "w_m", "difficulty_band",
                 "quality_band", "uses", "exposure", "dims")

    def __init__(self):
        self.a = 1.0
        self.b = 0.0
        self.c = 0.0
        self.k = 4
        self.misconception = 0
        self.w_m = 0.34
        self.difficulty_band = "orta"
        self.quality_band = "iyi"
        self.uses = 0
        self.exposure = 0
        # Bilissel boyut etiketleri (zincir A/B): metin bunlardan uretildi,
        # `b` de bunlardan turer. Metin sorularinda da tanimlidir.
        self.dims = None


class Exam:
    __slots__ = ("key", "rid", "course", "plan", "kind", "mode", "date", "starts_at",
                 "ends_at", "duration_ms", "max_attempts", "allow_review", "allow_rejoin",
                 "draft", "n_questions", "past", "questions", "result_count", "created_ms",
                 "graded", "text_only")

    def __init__(self, key, course, plan_index):
        self.key = key
        self.rid = rid("exam", key)
        self.course = course
        self.plan = plan_index
        self.questions = []
        self.result_count = 0
        self.graded = True
        self.text_only = False


class Question:
    __slots__ = ("key", "rid", "exam", "subject", "kind", "points", "choices", "correct",
                 "from_bank", "banked_as", "item", "index", "text", "misc_choice", "dims")

    def __init__(self, key, exam, subject, kind, points, index):
        self.key = key
        self.rid = rid("exam_question", key)
        self.exam = exam
        self.subject = subject
        self.kind = kind
        self.points = points
        self.index = index
        self.choices = []
        self.correct = None
        self.from_bank = None
        self.banked_as = None
        self.item = None
        self.text = ""
        self.misc_choice = None
        self.dims = None


class BankTemplate:
    __slots__ = ("key", "rid", "owner", "subject", "text", "kind", "points", "choices",
                 "correct", "source_exam", "visibility", "created_at", "item", "area",
                 "deleted", "misc_index", "correct_index", "dims")

    def __init__(self, key, owner, subject, kind, points, created_at, area):
        self.key = key
        self.rid = rid("bank_question", key)
        self.owner = owner
        self.subject = subject
        self.kind = kind
        self.points = points
        self.created_at = created_at
        self.area = area
        self.choices = []
        self.correct = None
        self.source_exam = None
        self.visibility = "private"
        self.item = None
        self.deleted = False
        self.misc_index = 0
        self.correct_index = 0
        self.text = ""
        self.dims = None


def sample_dims(rng):
    """Bir maddenin GERÇEK bilişsel etiketlerini çeker (zincir A'nın başlangıcı).

    Tutarlılık kuralı: `hatirlama` düzeyinde çok adımlı soru üretilmez — tek
    olgu soran bir kökte "birinin çıktısı ötekinin girdisi" zinciri kurulamaz,
    üretilse etiket kendi içinde çelişirdi.
    """
    dims = {}
    for name in ("bilissel_talep", "adim_sayisi", "dikkat_tuzagi", "okuma_yuku"):
        dims[name] = D.pick_weighted(rng, C.DIM_PRIORS[name])
    if dims["bilissel_talep"] == "hatirlama":
        dims["adim_sayisi"] = "tek_adim"
    return dims


DIM_NAMES = ("bilissel_talep", "adim_sayisi", "dikkat_tuzagi", "okuma_yuku")


def dim_decks(rng, n):
    """Bir sinavin n sorusu icin etiket destesi (boyut -> n uzunlugunda liste).

    NEDEN: gercek bir ogretmen sinavi DENGELI kurar; hepsi analiz olan ya da
    hepsi hatirlama olan bir yazili yazmaz. Etiket sinav icinde orantili bir
    desteden dagitilirsa madde duzeyindeki etiket-zorluk bagi hic bozulmadan
    SINAVLAR ARASI ortalama zorluk oynamasi kucuk kalir. Bu oynama olculdu:
    dengeleme yokken sinif notlarinin sinavdan sinava savrulmasi `mark_trend`
    tetikleyicisini yanlis atesliyor ve dikkat listesi SENARYO 7.5 P21
    bandinin (32-48) ustune cikiyordu.
    """
    decks = {}
    for name in DIM_NAMES:
        deck = []
        for label, share in C.DIM_PRIORS[name]:
            deck += [label] * int(n * share)
        i = 0
        while len(deck) < n:
            deck.append(C.DIM_PRIORS[name][i % len(C.DIM_PRIORS[name])][0])
            i += 1
        deck = deck[:n]
        rng.shuffle(deck)
        decks[name] = deck
    return decks


def dims_from_deck(decks, index):
    """Desteden tek bir maddenin etiketleri; tutarlilik kurali uygulanir."""
    dims = {name: decks[name][index] for name in DIM_NAMES}
    if dims["bilissel_talep"] == "hatirlama":
        dims["adim_sayisi"] = "tek_adim"
    return dims


def dim_difficulty(dims):
    """Etiketlerin madde zorluğuna toplam katkısı (zincir B)."""
    if not dims:
        return 0.0
    return sum(C.DIM_B_EFFECT[name][label] for name, label in dims.items())


def difficulty_band_of(b):
    """`b` değerinden zorluk bandı adı (bant artık dağıtılmaz, okunur)."""
    raw = b - C.ITEM_B_OFFSET
    for name, upper in C.DIFFICULTY_BAND_CUTS:
        if upper is None or raw < upper:
            return name
    return C.DIFFICULTY_BAND_CUTS[-1][0]


# ---------------------------------------------------------------------------
# 1) Sınav takvimi
# ---------------------------------------------------------------------------

def schedule_exams(ctx) -> None:
    seed = ctx.seed
    rng = substream(seed, "exam.schedule")
    fac = UlidFactory(substream(seed, "ulid.exam"))
    ctx.exams = []
    ctx.exam_days_by_grade = {}
    per_grade_day = {}

    def pick_day(grade, start, end):
        days = [d for d in T.school_days(start, end)]
        rng.shuffle(days)
        for d in days:
            if per_grade_day.get((grade, d), 0) < 2:
                per_grade_day[(grade, d)] = per_grade_day.get((grade, d), 0) + 1
                return d
        return days[0] if days else start

    for co in ctx.core_courses:
        for pi, plan in enumerate(C.EXAM_PLAN):
            (_term, w0, w1, kind, mode, nq, duration, max_att, review_share,
             text_share) = plan
            day = pick_day(co.grade, w0, w1)
            if mode == "sync":
                start_minute = rng.choice([540, 600, 660, 800])
                starts = T.local_ms(day, start_minute)
                ends = starts + rng.choice([60, 90, 120]) * C.MIN_MS
            elif mode == "async":
                starts = T.local_ms(day, 480)
                ends = starts + 5 * C.DAY_MS
            else:
                starts = T.local_ms(day, 480)
                ends = starts + 10 * C.DAY_MS
            created = min(starts - 3 * C.DAY_MS, T.T_NOW - C.DAY_MS)
            ex = Exam(fac.make(created), co, pi)
            ex.created_ms = created
            ex.kind = kind
            ex.mode = mode
            ex.date = day
            ex.starts_at = starts
            ex.ends_at = ends
            ex.duration_ms = duration
            ex.max_attempts = max_att
            ex.allow_review = rng.random() < review_share
            ex.allow_rejoin = (rng.random() < C.EXAM_ALLOW_REJOIN_SYNC) if mode == "sync" else True
            ex.draft = (pi == 7 and rng.random() < C.EXAM_DRAFT_SHARE_LAST)
            ex.n_questions = nq
            ex.past = ends <= T.T_NOW
            ex.text_only = text_share >= 1.0
            ctx.exams.append(ex)
            if ex.past:
                ctx.exam_days_by_grade.setdefault(co.grade, set()).add(day)

    # etüt / kulüp sınavları: 1 geçmiş + 1 gelecek
    for co in ctx.extra_courses:
        for j, (w0, w1, past) in enumerate((
                (_dt.date(2026, 3, 2), _dt.date(2026, 3, 13), True),
                (_dt.date(2026, 5, 11), _dt.date(2026, 5, 22), False))):
            days = T.school_days(w0, w1)
            day = days[rng.randrange(len(days))] if days else w0
            starts = T.local_ms(day, 900)
            ends = starts + 90 * C.MIN_MS
            created = min(starts - 3 * C.DAY_MS, T.T_NOW - C.DAY_MS)
            ex = Exam(fac.make(created), co, 4)
            ex.created_ms = created
            ex.kind = "quiz"
            ex.mode = "sync"
            ex.date = day
            ex.starts_at = starts
            ex.ends_at = ends
            ex.duration_ms = 1_200_000
            ex.max_attempts = 1
            ex.allow_review = True
            ex.allow_rejoin = True
            ex.draft = False
            ex.n_questions = C.EXAM_EXTRA_QUESTIONS
            ex.past = ends <= T.T_NOW
            ex.text_only = False
            ctx.exams.append(ex)

    # Kimliklerin zaman öneki kronolojik kalsın diye sınavlar oluşturulma
    # zamanına göre sıralanır (arayüz listeleri kimliğe göre sıralıyor).
    ctx.exams.sort(key=lambda e: (e.created_ms, e.starts_at, e.course.key))

    # kenar durum #12: son 3 haftanın 26 sınavı hiç notlandırılmamış
    recent = [e for e in ctx.exams
              if e.past and e.ends_at >= T.T_NOW - 21 * C.DAY_MS]
    recent.sort(key=lambda e: e.key)
    target = C.EXAM_UNGRADED_RECENT
    for e in recent[:target]:
        e.graded = False
    ctx.ungraded_exams = [e.key for e in recent[:target]]


# ---------------------------------------------------------------------------
# 2) Soru bankası şablonları (yazılmış olanlar)
# ---------------------------------------------------------------------------

def build_bank_templates(ctx) -> None:
    seed = ctx.seed
    rng = substream(seed, "bank.template")
    dims_rng = substream(seed, "item.dims.bank")
    fac = UlidFactory(substream(seed, "ulid.bank_question"))
    # Soru bankası YAPISAL bir büyüklüktür (24 öğretmen, 390 konu, 340 sınav);
    # öğrenci sayısıyla küçülmez — aksi halde from_bank payı çöker.
    total = C.BANK_QUESTIONS_FULL
    n_derived = max(1, round(C.BANKED_AS_SHARE * ctx.expected_question_count))
    n_derived = min(n_derived, total - 4)
    n_authored = total - n_derived
    ctx.bank_total_target = total
    ctx.bank_derived_target = n_derived

    # sahiplik log-normal ile 24 öğretmene dağılır
    teacher_weights = []
    for t in ctx.teachers:
        teacher_weights.append((t, D.lognormal_median(rng, 28.0, 0.9)))

    subjects_by_area = {}
    for co in ctx.core_courses:
        subjects_by_area.setdefault(co.area, []).extend(co.subjects)

    areas = list(subjects_by_area)
    ctx.bank_templates = []
    ctx.bank_by_area = {a: [] for a in areas}
    base_ms = T.local_ms(_dt.date(2025, 9, 15), 10 * 60)
    for i in range(n_authored):
        area = areas[i % len(areas)]
        subj_pool = subjects_by_area[area]
        subject = subj_pool[rng.randrange(len(subj_pool))]
        created = base_ms + i * 3 * 60_000
        if created > T.T_NOW:
            created = T.T_NOW - C.DAY_MS
        owner = D.pick_weighted(rng, teacher_weights)
        kind = "choice" if rng.random() >= C.TEXT_QUESTION_SHARE else "text"
        tpl = BankTemplate(fac.make(created), owner, subject, kind,
                           rng.randint(2, 20), created, area)
        tpl.visibility = "school" if rng.random() < C.BANK_VISIBILITY_SCHOOL else "private"
        # ÖNCE etiket, SONRA metin (zincir A): metni okuyan biri etiketi
        # çıkarabilmeli.
        tpl.dims = sample_dims(dims_rng)
        if kind == "choice":
            k = D.pick_weighted(rng, C.CHOICE_COUNT_WEIGHTS)
            tpl.correct_index = rng.randrange(k)
            tpl.misc_index = (tpl.correct_index + 1 + rng.randrange(max(1, k - 1))) % k
            tpl.text, texts = TXT.make_labeled_question(
                rng, area, subject.name, k, tpl.dims,
                tpl.correct_index, tpl.misc_index)
            tpl.choices = [{"id": random_ulid(rng, created), "text": txt}
                           for txt in texts]
            tpl.correct = tpl.choices[tpl.correct_index]["id"]
        else:
            tpl.dims["dikkat_tuzagi"] = "yok"
            tpl.text = TXT.make_labeled_stem(rng, area, subject.name, tpl.dims)
        ctx.bank_templates.append(tpl)
        ctx.bank_by_area[area].append(tpl)

    # kenar durum #22: konusu silinmiş şablonlar
    none_rng = substream(seed, "bank.subject_none")
    n_none = C.BANK_SUBJECT_NONE
    for tpl in D.take_share(none_rng, ctx.bank_templates,
                            n_none / max(1, len(ctx.bank_templates))):
        tpl.subject = None


# ---------------------------------------------------------------------------
# 3) Sınav soruları
# ---------------------------------------------------------------------------

def allocate_points(n, text_flags):
    """Toplam daima tam 100 (I45); her puan 1..100 arasında (I44)."""
    t = sum(1 for f in text_flags if f)
    pts = [0] * n
    if 0 < t < n and 100 - 12 * t >= (n - t):
        rest = 100 - 12 * t
        m = n - t
        base = rest // m
        extra = rest - base * m
        ci = 0
        for i in range(n):
            if text_flags[i]:
                pts[i] = 12
            else:
                pts[i] = base + (1 if ci < extra else 0)
                ci += 1
    else:
        base = 100 // n
        extra = 100 - base * n
        for i in range(n):
            pts[i] = base + (1 if i < extra else 0)
    return pts


def build_questions(ctx) -> None:
    seed = ctx.seed
    rng = substream(seed, "question.build")
    dims_rng = substream(seed, "item.dims.fresh")
    bank_rng = substream(seed, "question.bank_pick")
    fac = UlidFactory(substream(seed, "ulid.exam_question"))

    # Çekilişlerin bir kısmı uygun şablon bulunamadığı için taze soruya düşer;
    # hedef %45 paya ulaşmak için gerçekleşme oranıyla düzeltilir (L18).
    bank_pick_share = min(0.98, C.FROM_BANK_SHARE / (1.0 - C.TEXT_QUESTION_SHARE)
                          / C.FROM_BANK_REALIZATION)
    ctx.questions = []
    ctx.items = {}          # identity -> Item
    ctx.item_of_question = {}
    used_in_exam = {}

    for ex in ctx.exams:
        co = ex.course
        n = ex.n_questions
        plan = C.EXAM_PLAN[ex.plan]
        text_share = 1.0 if ex.text_only else plan[9]
        text_flags = [rng.random() < text_share for _ in range(n)]
        if ex.text_only:
            text_flags = [True] * n
        pts = allocate_points(n, text_flags)
        subj_pool = co.subjects
        # Bir sınavın soru kökleri kendi içinde TEKİL olmalı (gerçek sınavda
        # aynı soru iki kez sorulmaz). Sınavlar ARASI yeniden kullanım ise
        # bilinçlidir (§4.8 banka şablonu paylaşımı) ve korunur.
        exam_stems = set()
        decks = dim_decks(dims_rng, n)
        for i in range(n):
            subject = subj_pool[i % len(subj_pool)]
            kind = "text" if text_flags[i] else "choice"
            key = fac.make(ex.created_ms + i * 1000)
            q = Question(key, ex, subject, kind, pts[i], i)
            template = None
            # from_bank payi TUM sorular uzerinden %45 olmali; yalniz coktan
            # secmeli sorular bankadan gelebildigi icin oran duzeltilir.
            if kind == "choice" and bank_rng.random() < bank_pick_share:
                pool = ctx.bank_by_area.get(co.area) or []
                pool = [t for t in pool if t.kind == "choice"]
                want = decks["bilissel_talep"][i]
                if pool:
                    # Sınav içi kök tekilliği ve "aynı şablon iki kez" kuralı
                    # bazı adayları eler; 20 deneme ile uygun aday aranır.
                    # Sinav dengesi: once ISTENEN bilissel duzeydeki sablon
                    # aranir; 20 denemede bulunamazsa duzey serbest birakilir.
                    fallback = None
                    for attempt in range(20):
                        cand = pool[bank_rng.randrange(len(pool))]
                        if (ex.key, cand.key) in used_in_exam:
                            continue
                        if cand.text in exam_stems:
                            continue       # aynı sınavda aynı kök olmasın
                        if fallback is None:
                            fallback = cand
                        if (cand.dims or {}).get("bilissel_talep") != want:
                            continue
                        template = cand
                        break
                    if template is None:
                        template = fallback
                    if template is not None:
                        used_in_exam[(ex.key, template.key)] = True
            if template is not None:
                q.from_bank = template
                identity = "bank:" + template.key
                q.choices = [{"id": random_ulid(bank_rng, ex.created_ms + i),
                              "text": ch["text"]} for ch in template.choices]
                q.correct = q.choices[template.correct_index]["id"]
                q.misc_choice = q.choices[template.misc_index]["id"]
                q.dims = template.dims
                diverged = bank_rng.random() < C.BANK_TEXT_DIVERGENCE
                q.text = (template.text + " (uyarlanmış)") if diverged else template.text
                ctx.text_diverged[q.key] = diverged
            else:
                identity = "q:" + key
                # ÖNCE etiket, SONRA metin (zincir A).
                q.dims = dims_from_deck(decks, i)
                if kind == "choice":
                    k = D.pick_weighted(rng, C.CHOICE_COUNT_WEIGHTS)
                    ci = rng.randrange(k)
                    mi = (ci + 1 + rng.randrange(max(1, k - 1))) % k
                    q.text, texts = TXT.make_labeled_question(
                        rng, co.area, subject.name, k, q.dims, ci, mi,
                        avoid=exam_stems)
                    q.choices = [{"id": random_ulid(rng, ex.created_ms + i),
                                  "text": txt} for txt in texts]
                    q.correct = q.choices[ci]["id"]
                    q.misc_choice = q.choices[mi]["id"]
                else:
                    q.dims["dikkat_tuzagi"] = "yok"
                    q.text = TXT.make_labeled_stem(rng, co.area, subject.name,
                                                   q.dims, avoid=exam_stems)
            exam_stems.add(q.text)
            if q.from_bank is not None:
                # Iraksamış kopyada da şablonun ham metni tekrar kullanılmasın
                exam_stems.add(q.from_bank.text)
            item = ctx.items.get(identity)
            if item is None:
                item = Item()
                item.k = len(q.choices) if q.choices else 0
                item.dims = q.dims
                ctx.items[identity] = item
            item.uses += 1
            item.exposure += len(co.students)
            q.item = item
            ctx.item_of_question[q.key] = identity
            ex.questions.append(q)
            ctx.questions.append(q)
            subject.exam_question_count += 1

    _assign_item_parameters(ctx)
    _build_derived_templates(ctx)


def _assign_item_parameters(ctx) -> None:
    """Zorluk ve ayırt edicilik bantlarını madde kimliklerine dağıtır (§4.2, §4.3)."""
    seed = ctx.seed
    rng = substream(seed, "item.params")
    identities = sorted(ctx.items)
    rng.shuffle(identities)
    choice_ids = [i for i in identities if ctx.items[i].k > 0]

    # ZINCIR B — zorluk artık rastgele bir banttan çekilmez, maddenin
    # BILISSEL TALEBINDEN türer: analiz > uygulama > hatırlama, çok adımlı
    # daha zor, yüksek okuma yükü daha zor. Üstüne madde bazında gürültü
    # kalır; bant adı sonuçtan OKUNUR.
    total_q = sum(ctx.items[i].uses for i in choice_ids)
    for ident in choice_ids:
        item = ctx.items[ident]
        item.b = (C.ITEM_B_OFFSET + dim_difficulty(item.dims)
                  + rng.gauss(0.0, C.ITEM_B_NOISE_SIGMA))
        item.difficulty_band = difficulty_band_of(item.b)
        item.c = (1.0 / item.k) * C.GUESS_FACTOR if item.k else 0.0
        trap = (item.dims or {}).get("dikkat_tuzagi", "yok")
        w_m = C.DIM_W_M.get(trap)
        # `yok` maddelerde çeldiriciler EŞIT ağırlıklıdır: böylece "tuzak
        # şıkkın çekiciliği" yalnız tuzaklı maddelerde oluşur.
        item.w_m = w_m if w_m is not None else (
            1.0 / max(1, item.k - 1) if item.k > 1 else 1.0)

    # Ayırt edicilik: negatif ve bozuk bantlar ÖNCELİKLE çok kullanılan
    # şablonlara verilir (T2'nin n>=30 kapısının açılabilmesi için, §4.3).
    shared = [i for i in choice_ids if ctx.items[i].uses >= 2]
    single = [i for i in choice_ids if ctx.items[i].uses < 2]
    shared.sort(key=lambda i: -ctx.items[i].exposure)
    q_targets = {name: share * total_q for name, share, *_ in C.QUALITY_BANDS}
    assigned = set()

    def take(names, count, pool):
        out = []
        for ident in pool:
            if ident in assigned:
                continue
            out.append(ident)
            assigned.add(ident)
            if sum(ctx.items[i].uses for i in out) >= count:
                break
        return out

    neg_single_target = 12
    neg_pool = take("negatif", q_targets["negatif"] - neg_single_target, shared)
    neg_pool += take("negatif", neg_single_target, single)
    broken_pool = take("bozuk", q_targets["bozuk"], shared)

    def set_band(ident, band):
        item = ctx.items[ident]
        item.quality_band = band
        spec = next(b for b in C.QUALITY_BANDS if b[0] == band)
        if spec[2] == "normal":
            item.a = D.clip(rng.gauss(spec[3], spec[4]), spec[5], spec[6])
        else:
            item.a = rng.uniform(spec[3], spec[4])

    for ident in neg_pool:
        set_band(ident, "negatif")
    for ident in broken_pool:
        set_band(ident, "bozuk")
    rest = [i for i in choice_ids if i not in assigned]
    rest_bands = [(b[0], b[1]) for b in C.QUALITY_BANDS if b[0] in ("iyi", "kabul", "zayif")]
    total_rest = sum(w for _, w in rest_bands)
    acc2 = {n: 0.0 for n, _ in rest_bands}
    tot_rest_q = sum(ctx.items[i].uses for i in rest)
    for ident in rest:
        band = min(rest_bands, key=lambda p: acc2[p[0]] / max(1e-9, p[1] / total_rest))[0]
        acc2[band] += ctx.items[ident].uses / max(1, tot_rest_q)
        set_band(ident, band)

    # metin maddeleri: doğruluk tutulmaz, yine de b ataması yapılır (puanlama için)
    for ident in identities:
        item = ctx.items[ident]
        if item.k == 0:
            item.b = (C.ITEM_B_OFFSET + dim_difficulty(item.dims)
                      + rng.gauss(0.0, C.ITEM_B_NOISE_SIGMA))
            item.a = 1.0
            item.c = 0.0
            item.quality_band = "metin"
            item.difficulty_band = difficulty_band_of(item.b)

    # ders bazlı zorluk kayması b_i'ye eklenir; bant değerden yeniden okunur
    for q in ctx.questions:
        shift = q.exam.course.difficulty_shift
        if shift and ctx.item_of_question[q.key].startswith("q:"):
            q.item.b += shift
            q.item.difficulty_band = difficulty_band_of(q.item.b)


def _build_derived_templates(ctx) -> None:
    """`banked_as`: öğretmenin sınavda yazdığı soruyu bankaya kaydetmesi."""
    seed = ctx.seed
    rng = substream(seed, "bank.derived")
    fac = UlidFactory(substream(seed, "ulid.bank_question.derived"))
    fresh = [q for q in ctx.questions
             if q.from_bank is None and q.kind == "choice" and q.exam.past]
    rng.shuffle(fresh)
    n = min(ctx.bank_derived_target, len(fresh))
    for q in fresh[:n]:
        created = q.exam.ends_at + rng.randint(1, 5) * C.DAY_MS
        if created > T.T_NOW:
            created = T.T_NOW - C.DAY_MS
        tpl = BankTemplate(fac.make(created), q.exam.course.teachers[0], q.subject,
                           q.kind, min(100, max(1, q.points)), created,
                           q.exam.course.area)
        tpl.text = q.text
        tpl.choices = [{"id": ch["id"], "text": ch["text"]} for ch in q.choices]
        tpl.correct = q.correct
        tpl.source_exam = q.exam
        tpl.visibility = "school" if rng.random() < C.BANK_VISIBILITY_SCHOOL else "private"
        tpl.item = q.item
        ctx.bank_templates.append(tpl)
        q.banked_as = tpl


# ---------------------------------------------------------------------------
# 4) Denemeler, cevaplar, sonuçlar
# ---------------------------------------------------------------------------

def build_attempts(ctx) -> None:
    seed = ctx.seed
    em = ctx.emitter
    rng = substream(seed, "attempt.core")
    ans_rng = substream(seed, "answer.core")
    txt_rng = substream(seed, "answer.text")
    grade_rng = substream(seed, "result.grade")
    img_rng = substream(seed, "answer.image")

    qstats = ctx.question_stats
    stats = ctx.answer_stats
    arch_stats = ctx.archetype_stats

    n_abandon_target = max(1, round(31 * ctx.scale.ratio))
    n_blank_target = max(1, round(C.EDGE_BLANK_ATTEMPTS * ctx.scale.ratio))
    abandoned = 0
    blanks = 0

    past_exams = [e for e in ctx.exams if e.past and not e.draft]
    past_exams.sort(key=lambda e: e.starts_at)

    second_pool = []   # (exam, student) ikinci deneme adayları

    for ex in past_exams:
        co = ex.course
        for s in co.students:
            if not s.active_at(ex.starts_at):
                continue
            if "passive" in s.edge and rng.random() < 0.75:
                continue
            part = s.param("exam_participation", ex.starts_at)
            if s.gap_course_key == co.key:
                part = s.arch.get("gap_participation", part)
            if rng.random() >= part:
                continue
            phi = rng.gauss(0.0, C.DAY_FORM_SIGMA)
            started = ex.starts_at + rng.randint(0, 15) * C.MIN_MS
            base_key = "%s_%s" % (ex.key, s.key)

            blank = False
            abandon = False
            if blanks < n_blank_target and rng.random() < 0.0009:
                blank = True
                blanks += 1
            elif (ex.mode == "sync" and abandoned < n_abandon_target
                  and rng.random() < C.EXAM_ABANDON_SHARE * 0.05):
                abandon = True
                abandoned += 1

            if abandon:
                finished = None
                left = started + rng.randint(4, 22) * C.MIN_MS
            else:
                finished = started + int((ex.duration_ms or 40 * C.MIN_MS)
                                         * rng.uniform(0.45, 0.98))
                if finished > ex.ends_at:
                    finished = ex.ends_at
                left = None

            em.add("exam_attempt", {
                "id": rid("exam_attempt", base_key),
                "exam": ex.rid, "user": s.rid, "seq": 1,
                "started_at": started, "finished_at": finished, "left_at": left,
            })
            ctx.bump(s, "exam_sat_total")

            earned = 0
            first_wrong = set()
            if not blank:
                limit = (int(len(ex.questions) * C.EXAM_ABANDON_PREFIX)
                         if abandon else len(ex.questions))
                earned, first_wrong = _write_answers(
                    ctx, em, ex, s, phi, 1, base_key, started, limit,
                    ans_rng, txt_rng, img_rng, qstats, stats, arch_stats)

            if ex.graded and grade_rng.random() < C.EXAM_GRADED_SHARE:
                mark = 0 if blank else _to_mark(earned)
                em.add("exam_result", {
                    "id": rid("exam_result", base_key),
                    "exam": ex.rid, "user": s.rid, "mark": mark,
                    "graded_by": co.teachers[0].rid, "seq": 1,
                })
                ex.result_count += 1
                ctx.kind_ref_counts[ex.kind] = ctx.kind_ref_counts.get(ex.kind, 0) + 1
                ctx.bump(co.teachers[0], "marks_given_total")
                ctx.mark_values.append(mark)

            if ex.max_attempts > 1 and rng.random() < C.EXAM_SECOND_ATTEMPT_SHARE \
                    and s.archetype != "A7" and not blank and not abandon:
                second_pool.append((ex, s, phi, first_wrong))

    # ikinci oturumlar (seq = 2) — E3: id `{exam}_{user}_2`
    for ex, s, phi, first_wrong in second_pool:
        base_key = seq_key("%s_%s" % (ex.key, s.key), 2)
        started = ex.ends_at - rng.randint(1, 20) * C.MIN_MS
        finished = min(ex.ends_at, started + int((ex.duration_ms or 40 * C.MIN_MS) * 0.8))
        em.add("exam_attempt", {
            "id": rid("exam_attempt", base_key),
            "exam": ex.rid, "user": s.rid, "seq": 2,
            "started_at": started, "finished_at": finished, "left_at": None,
        })
        earned, _ = _write_answers(
            ctx, em, ex, s, phi + C.EXAM_SECOND_ATTEMPT_THETA_BONUS, 2, base_key,
            started, len(ex.questions), ans_rng, txt_rng, img_rng, qstats, stats,
            arch_stats, first_wrong=first_wrong)
        if ex.graded and grade_rng.random() < C.EXAM_GRADED_SHARE:
            mark = _to_mark(earned)
            em.add("exam_result", {
                "id": rid("exam_result", base_key),
                "exam": ex.rid, "user": s.rid, "mark": mark,
                "graded_by": ex.course.teachers[0].rid, "seq": 2,
            })
            ex.result_count += 1
            ctx.kind_ref_counts[ex.kind] = ctx.kind_ref_counts.get(ex.kind, 0) + 1
            ctx.bump(ex.course.teachers[0], "marks_given_total")
            ctx.mark_values.append(mark)

    ctx.stats["abandoned_attempts"] = abandoned
    ctx.stats["blank_attempts"] = blanks
    ctx.stats["second_attempts"] = len(second_pool)


def _write_answers(ctx, em, ex, s, phi, seq, base_key, started, limit,
                   ans_rng, txt_rng, img_rng, qstats, stats, arch_stats,
                   first_wrong=None):
    """Bir oturumun cevaplarını yazar; kazanılan puanı döndürür."""
    earned = 0.0
    wrong = set()
    n_total = len(ex.questions)
    theta_t = s.theta_at(ex.starts_at)
    arch = s.archetype
    astat = arch_stats.setdefault(arch, {"asked": 0, "answered": 0, "correct": 0,
                                         "t1_asked": 0, "t1_correct": 0,
                                         "t2_asked": 0, "t2_correct": 0,
                                         "gap_asked": 0, "gap_correct": 0,
                                         "other_asked": 0, "other_correct": 0,
                                         "pre_asked": 0, "pre_correct": 0,
                                         "post_asked": 0, "post_correct": 0})
    is_t2 = ex.starts_at >= T.local_ms(C.T2_START, 0)
    after_break = s.after_break(ex.starts_at)
    for i, q in enumerate(ex.questions):
        if i >= limit:
            break
        item = q.item
        # ZINCIR C — genel theta üstüne maddenin BOYUTUNA özgü sapma eklenir:
        # ezberci öğrenci hatırlama maddesinde yükselir, analizde düşer.
        theta_ui = (theta_t
                    + s.dim_ability(item.dims)
                    + s.course_delta.get(ex.course.key, 0.0)
                    + s.subject_delta.get(q.subject.key, 0.0)
                    + phi
                    + ans_rng.gauss(0.0, C.ITEM_NOISE_SIGMA))
        qs = qstats.setdefault(q.key, [0, 0, 0, {}])
        if q.kind == "text":
            stats["text_asked"] += 1
            if txt_rng.random() < C.TEXT_OMISSION_SHARE:
                continue
            stats["text_answered"] += 1
            # Cevabın doluluğu arketipe bağlıdır: A1 dolu ve terimli, A7 ile
            # kırılma sonrası A6 kısa ve eksik (SENARYO 4.7).
            if arch == "A1":
                quality = "strong"
            elif arch == "A7" or after_break:
                quality = "weak"
            else:
                quality = "normal" if txt_rng.random() < 0.82 else "weak"
            body = TXT.make_answer(txt_rng, ex.course.area, q.subject.name, quality)
            em.add("exam_answer", {
                "id": rid("exam_answer", seq_key("%s_%s" % (q.key, s.key), seq)),
                "exam": ex.rid, "question": q.rid, "user": s.rid,
                "selected": None, "text": body,
                "updated_at": started + (i + 1) * 30_000, "seq": seq,
            })
            got = D.clip(int(round(q.points * (0.42 + 0.30 * theta_ui
                                               + txt_rng.gauss(0.0, 0.12)))), 0, q.points)
            earned += got
            if img_rng.random() < C.ANSWER_IMAGE_SHARE:
                em.add("answer_image", {
                    "id": rid("answer_image", seq_key("%s_%s" % (q.key, s.key), seq)),
                    "exam": ex.rid, "question": q.rid, "user": s.rid,
                    "file": "answers/%s.png" % q.key.lower(),
                    "content_type": "image/png",
                    "size": img_rng.randint(8_000, 400_000), "seq": seq,
                })
            continue

        # çoktan seçmeli
        tau = C.OMISSION_TAU_LAST if (ex.mode == "sync" and i >= 0.8 * n_total) else 1.0
        omega = s.param("omega", ex.starts_at)
        if q.subject.key in s.gap_subject_keys:
            omega = s.arch.get("gap_omega", omega)
        p_omit = D.clip(omega * C.OMISSION_SCALE
                        * D.sigmoid(1.40 * (item.b - theta_ui)) * tau, 0.01, 0.58)
        stats["choice_asked"] += 1
        astat["asked"] += 1
        qs[0] += 1
        if ans_rng.random() < p_omit:
            continue
        stats["choice_answered"] += 1
        astat["answered"] += 1
        qs[1] += 1
        p_correct = item.c + (1.0 - item.c) * D.sigmoid(item.a * (theta_ui - item.b))
        correct = ans_rng.random() < p_correct
        if correct:
            selected = q.correct
            earned += q.points
            stats["choice_correct"] += 1
            astat["correct"] += 1
            qs[2] += 1
            if first_wrong is not None and q.key in first_wrong:
                ctx.stats["improved_items"] = ctx.stats.get("improved_items", 0) + 1
        else:
            wrong.add(q.key)
            selected = _pick_distractor(ans_rng, q, item, theta_ui,
                                        C.ARCHETYPE_TRAP_PULL.get(arch, 1.0))
            qs[3][selected] = qs[3].get(selected, 0) + 1
        if is_t2:
            astat["t2_asked"] += 1
            astat["t2_correct"] += 1 if correct else 0
        else:
            astat["t1_asked"] += 1
            astat["t1_correct"] += 1 if correct else 0
        if s.gap_course_key == ex.course.key and q.subject.key in s.gap_subject_keys:
            astat["gap_asked"] += 1
            astat["gap_correct"] += 1 if correct else 0
        elif arch == "A3":
            astat["other_asked"] += 1
            astat["other_correct"] += 1 if correct else 0
        if q.subject.key in ctx.all_gap_subjects and q.subject.key not in s.gap_subject_keys:
            # A3 boşluk konularında SINIF ortalaması (A7 kontrolü)
            ctx.gap_class_stats["asked"] += 1
            ctx.gap_class_stats["correct"] += 1 if correct else 0
        if s.arch.get("breaking"):
            if after_break:
                astat["post_asked"] += 1
                astat["post_correct"] += 1 if correct else 0
            else:
                astat["pre_asked"] += 1
                astat["pre_correct"] += 1 if correct else 0
        em.add("exam_answer", {
            "id": rid("exam_answer", seq_key("%s_%s" % (q.key, s.key), seq)),
            "exam": ex.rid, "question": q.rid, "user": s.rid,
            "selected": selected, "text": None,
            "updated_at": started + (i + 1) * 20_000, "seq": seq,
        })
    return earned, wrong


def _to_mark(earned):
    """Ham kazanilan puan -> ogretmen notu (0..100, E19)."""
    return D.clip(int(round(C.MARK_SLOPE * earned + C.MARK_INTERCEPT)), 0, 100)


def _pick_distractor(rng, q, item, theta_ui, trap_pull=1.0):
    ids = [ch["id"] for ch in q.choices if ch["id"] != q.correct]
    if not ids:
        return q.correct
    misc = q.misc_choice if q.misc_choice in ids else ids[0]
    w_m = item.w_m
    if trap_pull != 1.0 and (item.dims or {}).get("dikkat_tuzagi") == "var":
        # Aceleci profil yanlış cevap verdiğinde tuzağa daha sık düşer.
        w_m = min(C.MAX_TRAP_PULL_W_M, w_m * trap_pull)
    if item.a < 0:
        w_m = D.clip(0.45 + 0.22 * theta_ui, 0.20, 0.90)
    if len(ids) == 1:
        return ids[0]
    rest_w = (1.0 - w_m) / (len(ids) - 1)
    pairs = [(cid, w_m if cid == misc else rest_w) for cid in ids]
    return D.pick_weighted(rng, pairs)


# ---------------------------------------------------------------------------
# 5) Satırların yazımı (sayaçlar hesaplandıktan sonra)
# ---------------------------------------------------------------------------

def emit_exam_rows(ctx) -> None:
    em = ctx.emitter
    rng = substream(ctx.seed, "exam.emit")
    for ex in ctx.exams:
        em.add("exam", {
            "id": ex.rid,
            "creator": ex.course.teachers[0].rid,
            "course": ex.course.rid,
            "title": "%s — %s" % (ex.course.title, _kind_title(ex.kind)),
            "description": "%s dersinin %s sınavı." % (ex.course.title,
                                                       _kind_title(ex.kind).lower()),
            "kind": ex.kind,
            "mode": ex.mode,
            "starts_at": ex.starts_at,
            "ends_at": ex.ends_at,
            "duration_ms": ex.duration_ms,
            "max_attempts": ex.max_attempts,
            "allow_rejoin": ex.allow_rejoin,
            "allow_review": ex.allow_review,
            "draft": ex.draft,
            "result_count": ex.result_count,
        })

    img_rng = substream(ctx.seed, "question.image")
    for q in ctx.questions:
        row = {
            "id": q.rid,
            "exam": q.exam.rid,
            "text": q.text,
            "kind": q.kind,
            "points": q.points,
            "choices": q.choices if q.kind == "choice" else None,
            "correct": q.correct if q.kind == "choice" else None,
            "subject": q.subject.rid,
            "from_bank": (q.from_bank.rid
                          if q.from_bank is not None and not q.from_bank.deleted
                          else None),
            "banked_as": q.banked_as.rid if q.banked_as is not None else None,
        }
        em.add("exam_question", row)
        if q.kind == "choice" and img_rng.random() < C.QUESTION_IMAGE_SHARE:
            em.add("question_image", {
                "id": rid("question_image", "%s_q" % q.key),
                "exam": q.exam.rid, "question": q.rid, "slot": None,
                "file": "questions/%s.png" % q.key.lower(),
                "content_type": "image/png",
                "size": img_rng.randint(10_000, 500_000),
            })

    bimg_rng = substream(ctx.seed, "bank.image")
    for tpl in ctx.bank_templates:
        if tpl.deleted:
            continue
        em.add("bank_question", {
            "id": tpl.rid,
            "owner": tpl.owner.rid,
            "subject": tpl.subject.rid if tpl.subject is not None else None,
            "text": tpl.text,
            "kind": tpl.kind,
            "points": tpl.points,
            "choices": tpl.choices if tpl.kind == "choice" else None,
            "correct": tpl.correct if tpl.kind == "choice" else None,
            "source_exam": tpl.source_exam.rid if tpl.source_exam is not None else None,
            "visibility": tpl.visibility,
            "created_at": tpl.created_at,
        })
        if tpl.kind == "choice" and bimg_rng.random() < C.BANK_QUESTION_IMAGE_SHARE:
            em.add("bank_question_image", {
                "id": rid("bank_question_image", "%s_q" % tpl.key),
                "bank_question": tpl.rid, "slot": None,
                "file": "bank/%s.png" % tpl.key.lower(),
                "content_type": "image/png",
                "size": bimg_rng.randint(10_000, 500_000),
            })
    del rng


def _kind_title(kind):
    return {"quiz": "Kısa Sınav", "midterm": "Yazılı", "final": "Dönem Sonu Sınavı",
            "project": "Proje", "oral": "Sözlü", "homework": "Ödev Sınavı"}.get(kind, kind)


def apply_sabotage(ctx) -> None:
    """Ek A adım 26 — bilinçli bozma adımı (kenar durum #13, #14)."""
    seed = ctx.seed
    rng = substream(seed, "sabotage")
    # 15 banka şablonu silinir -> ona işaret eden from_bank alanları NONE olur
    n_del = C.DELETED_BANK_TEMPLATES
    candidates = [t for t in ctx.bank_templates if t.source_exam is None and not t.deleted]
    rng.shuffle(candidates)
    # L19 kesin 48 satir ister: kullanim sayilari toplami 48 olacak bicimde
    # n_del sablon secilir (acgozlu yaklasim, hedefe en yakin adaydan gider).
    usage = {}
    for q in ctx.questions:
        if q.from_bank is not None:
            usage[q.from_bank.key] = usage.get(q.from_bank.key, 0) + 1
    target = C.BROKEN_FROM_BANK_TARGET
    deleted = []
    remaining = target
    for step in range(n_del):
        left = n_del - step
        want = remaining / left if left else 0
        best = None
        for t in candidates:
            if t in deleted:
                continue
            u = usage.get(t.key, 0)
            if u > remaining - (left - 1) * 0:
                pass
            score = abs(u - want)
            if best is None or score < best[0]:
                best = (score, t, u)
        if best is None:
            break
        deleted.append(best[1])
        remaining -= best[2]
        if remaining < 0:
            remaining = 0
    for tpl in deleted:
        tpl.deleted = True
    ctx.deleted_bank_templates = [t.key for t in deleted]
    broken = 0
    for q in ctx.questions:
        if q.from_bank is not None and q.from_bank.deleted:
            broken += 1
            ctx.broken_origin.append(q.key)
    ctx.stats["broken_from_bank"] = broken

    # 5 sorunun cevap anahtarı değiştirilir; eski değer yalnız manifest'te
    n_edit = C.ANSWER_KEY_EDITS
    pool = [q for q in ctx.questions if q.kind == "choice" and len(q.choices) > 1
            and q.exam.past]
    rng.shuffle(pool)
    for q in pool[:n_edit]:
        old = q.correct
        new = q.choices[1]["id"]
        q.correct = new
        ctx.answer_key_edits.append({"question": "exam_question:" + q.key,
                                     "old_correct": old, "new_correct": new})
