"""Kimlik alanı: kullanıcılar, arketipler, veli bağları, canlı oturumlar.

`user` satırları en SONDA yazılır (bütün sayaçlar hesaplandıktan sonra); bu modül
yalnız kullanıcı nesnelerini kurar ve `parent_link` / `session` satırlarını üretir.
"""

from __future__ import annotations

import datetime as _dt

import config as C
import dists as D
import timeline as T
from ids import UlidFactory, rid, substream

try:
    from argon2.low_level import Type, hash_secret
except ImportError:  # pragma: no cover
    hash_secret = None


# ---------------------------------------------------------------------------
# Kullanıcı nesnesi
# ---------------------------------------------------------------------------

class User:
    __slots__ = ("key", "rid", "role", "username", "name", "surname", "gender",
                 "created_ms", "profile", "area", "branch", "archetype", "arch",
                 "theta_base", "theta_shift", "break_ms", "gap_area", "gap_course_key",
                 "gap_subject_keys", "omega", "edge", "join_ms", "leave_ms",
                 "course_delta", "subject_delta", "counters", "index", "dim_delta")

    def __init__(self, key, role, username, name, surname, gender, created_ms):
        self.key = key
        self.rid = rid("user", key)
        self.role = role
        self.username = username
        self.name = name
        self.surname = surname
        self.gender = gender
        self.created_ms = created_ms
        self.profile = {}
        self.area = None
        self.branch = None
        self.archetype = None
        self.arch = None
        self.theta_base = 0.0
        self.theta_shift = 0.0
        self.break_ms = None
        self.gap_area = None
        self.gap_course_key = None
        self.gap_subject_keys = ()
        self.omega = 0.0
        self.edge = []
        self.join_ms = None
        self.leave_ms = None
        self.course_delta = {}
        self.subject_delta = {}
        self.counters = {}
        self.index = 0
        # Boyut bazında yetenek sapması (zincir C): boyut -> etiket -> logit.
        # Kontrol grubu arketiplerinde boştur.
        self.dim_delta = {}

    # -- arketip davranışı -------------------------------------------------

    def theta_at(self, ms: int) -> float:
        a = self.arch
        if a.get("rising"):
            raw = (a.get("rise_base", -0.70)
                   + a.get("rise_slope", 1.50) * T.progress(ms) + self.theta_shift)
        elif a.get("breaking") and self.break_ms is not None:
            if ms <= self.break_ms:
                raw = self.theta_base
            else:
                ramp_ms = a["break_ramp_days"] * C.DAY_MS
                frac = min(1.0, (ms - self.break_ms) / ramp_ms)
                raw = self.theta_base + a["break_drop"] * frac
        else:
            trend = a.get("trend", 0.0)
            raw = self.theta_base + trend * T.progress(ms) if trend else self.theta_base
        # Gurultunun urettigi ortalamaya sikismayi telafi eden yayilim
        return C.THETA_CENTER + C.THETA_SPREAD * (raw - C.THETA_CENTER)

    def after_break(self, ms: int) -> bool:
        return bool(self.arch.get("breaking")) and self.break_ms is not None and ms > self.break_ms

    def dim_ability(self, dims) -> float:
        """Maddenin boyut etiketlerine göre öğrencinin yetenek sapması (zincir C).

        Genel `theta` üstüne eklenir: hatırlamada güçlü / analizde zayıf bir
        öğrenci aynı `b` değerinde iki farklı maddede farklı başarı gösterir.
        """
        if not dims or not self.dim_delta:
            return 0.0
        total = 0.0
        for name, table in self.dim_delta.items():
            label = dims.get(name)
            if label is not None:
                total += table.get(label, 0.0)
        return total

    def param(self, name: str, ms: int):
        """A6'da kırılma sonrası `post_<name>` değeri geçerlidir."""
        if self.after_break(ms):
            post = self.arch.get("post_" + name)
            if post is not None:
                return post
        return self.arch.get(name)

    def active_at(self, ms: int) -> bool:
        if self.join_ms is not None and ms < self.join_ms:
            return False
        if self.leave_ms is not None and ms > self.leave_ms:
            return False
        return True


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------

def _dim_delta_for(rng, archetype):
    """Arketipin boyut sapması tablosunu öğrenci bazında küçük dağılımla üretir.

    Kontrol grubu arketiplerinde tablo BOŞ kalır (tam sıfır); böylece
    doğrulamada karşılaştırılacak gerçek bir kontrol grubu bulunur.
    """
    spec = C.ARCHETYPE_DIM_DELTA.get(archetype) or {}
    out = {}
    for dim, table in spec.items():
        row = {}
        for label, value in table.items():
            if value:
                value += rng.gauss(0.0, C.DIM_DELTA_JITTER_SIGMA)
            row[label] = round(value, 4)
        out[dim] = row
    return out


def ascii_lower(text: str) -> str:
    return text.translate(C.TR_ASCII).lower()


class UsernamePool:
    def __init__(self):
        self._seen = {}

    def make(self, name: str, surname: str) -> str:
        base = "%s.%s" % (ascii_lower(name), ascii_lower(surname))
        base = "".join(ch for ch in base if ch.isalnum() or ch in "._-")
        n = self._seen.get(base, 0) + 1
        self._seen[base] = n
        return base if n == 1 else "%s%d" % (base, n)


def password_hash(rng) -> str:
    """PAROLA.md: argon2id, kullanıcı başına 16 baytlık ayrı salt."""
    salt = bytes(rng.getrandbits(8) for _ in range(16))
    if hash_secret is None:
        raise RuntimeError("argon2-cffi kurulu değil")
    return hash_secret(
        C.PASSWORD_PLAIN.encode("utf-8"), salt,
        time_cost=C.ARGON2_TIME_COST, memory_cost=C.ARGON2_MEMORY_COST,
        parallelism=C.ARGON2_PARALLELISM, hash_len=C.ARGON2_HASH_LEN, type=Type.ID,
    ).decode("ascii")


def _profile(rng, user: User, role: str) -> dict:
    p = {}
    fill = C.PROFILE_FILL
    dom = "hezarfen.k12.tr"
    if rng.random() < fill["email"]:
        p["email"] = "%s@%s" % (user.username, dom)
    if rng.random() < fill["phone"]:
        p["phone"] = "05%02d%03d%02d%02d" % (rng.randint(30, 59), rng.randint(100, 999),
                                             rng.randint(10, 99), rng.randint(10, 99))
    if rng.random() < fill["birth_date"]:
        if role == "student":
            year = rng.randint(2007, 2011)
        elif role == "parent":
            year = rng.randint(1972, 1988)
        else:
            year = rng.randint(1968, 1996)
        month = rng.randint(1, 12)
        day = rng.randint(1, 28)
        p["birth_date"] = "%04d-%02d-%02d" % (year, month, day)
    if rng.random() < fill["display_name"]:
        p["display_name"] = "%s %s." % (user.name, user.surname[0])
    if rng.random() < fill["bio"]:
        p["bio"] = rng.choice([
            "Sayısal derslere ilgi duyuyorum.", "Kitap okumayı seviyorum.",
            "Robotik kulübü üyesiyim.", "Basketbol oynuyorum.",
            "Matematik öğretmeniyim.", "Öğrencilerimle iletişimi önemserim.",
            "Müzik ve tiyatro ile ilgileniyorum.", "Doğa yürüyüşü yaparım.",
        ])
    if rng.random() < fill["avatar_file"]:
        p["avatar_file"] = "avatars/%s.png" % user.key.lower()
        p["avatar_content_type"] = "image/png"
        p["avatar_size"] = rng.randint(12_000, 240_000)
    if rng.random() < fill["palette_color"]:
        p["palette_color"] = "#%06x" % rng.randrange(0x1000000)
    if rng.random() < fill["theme"]:
        p["theme"] = "light" if rng.random() < C.THEME_LIGHT_SHARE else "dark"
    if rng.random() < fill["language"]:
        p["language"] = "tr"
    return p


# ---------------------------------------------------------------------------
# Ana üretim
# ---------------------------------------------------------------------------

def build_people(ctx) -> None:
    scale = ctx.scale
    seed = ctx.seed
    fac = UlidFactory(substream(seed, "ulid.user"))
    names_rng = substream(seed, "people.names")
    prof_rng = substream(seed, "people.profile")
    pw_rng = substream(seed, "people.password")
    unames = UsernamePool()

    ctx.users = []
    ctx.students = []
    ctx.teachers = []
    ctx.managers = []
    ctx.parents = []

    def new_user(role, gender, created_ms, name=None, surname=None, username=None):
        if name is None:
            pool = C.MALE_NAMES if gender == "m" else C.FEMALE_NAMES
            name = names_rng.choice(pool)
        if surname is None:
            surname = names_rng.choice(C.SURNAMES)
        uname = username or unames.make(name, surname)
        key = fac.make(created_ms)
        u = User(key, role, uname, name, surname, gender, created_ms)
        u.index = len(ctx.users)
        u.profile = _profile(prof_rng, u, role)
        u.profile["password_hash"] = password_hash(pw_rng)
        ctx.users.append(u)
        return u

    staff_ms = T.local_ms(_dt.date(2025, 8, 20), 9 * 60)

    # admin + yöneticiler
    admin = new_user("admin", "m", staff_ms, name="Yönetici", surname="Hesabı",
                     username="yonetici")
    ctx.admin = admin
    for i in range(C.N_MANAGERS):
        m = new_user("manager", "m" if i % 2 == 0 else "f", staff_ms + (i + 1) * 60_000)
        ctx.managers.append(m)

    # öğretmenler: branş sırası + rehber
    areas = []
    for code, count in C.TEACHERS_PER_AREA.items():
        areas.extend([code] * count)
    areas.extend([None] * C.GUIDANCE_TEACHERS)
    for i, area in enumerate(areas):
        t = new_user("teacher", "m" if i % 2 == 0 else "f", staff_ms + (10 + i) * 60_000)
        t.area = area
        ctx.teachers.append(t)
    ctx.guidance_teacher = ctx.teachers[-1]

    # ------------------------------------------------------------------
    # Öğrenciler: şube ve arketip dağıtımı
    # ------------------------------------------------------------------
    branch_sizes = D.largest_remainder(scale.n_students, [b[2] for b in C.BRANCHES])
    ctx.branch_sizes = branch_sizes
    arch_names = list(C.ARCHETYPE_COUNTS_FULL)
    arch_counts = D.largest_remainder(
        scale.n_students, [C.ARCHETYPE_COUNTS_FULL[a] for a in arch_names])
    remaining = {a: n for a, n in zip(arch_names, arch_counts)}
    ctx.archetype_counts = dict(remaining)

    assign_rng = substream(seed, "people.archetype")
    per_branch = [[] for _ in C.BRANCHES]

    def take(arch):
        if remaining.get(arch, 0) > 0:
            remaining[arch] -= 1
            return True
        return False

    # 1) bilinçli yoğunlaşmalar
    for bi, (bname, _, _) in enumerate(C.BRANCHES):
        cluster = C.ARCHETYPE_CLUSTERS.get(bname)
        if not cluster:
            continue
        arch, count = cluster
        count = max(1, round(count * scale.n_students / C.N_STUDENTS_FULL))
        for _ in range(count):
            if len(per_branch[bi]) < branch_sizes[bi] and take(arch):
                per_branch[bi].append(arch)
    # 2) her şubede her arketipten en az 1 (arz yettiği sürece)
    for bi in range(len(C.BRANCHES)):
        for arch in arch_names:
            if len(per_branch[bi]) >= branch_sizes[bi]:
                break
            if arch in per_branch[bi]:
                continue
            take(arch) and per_branch[bi].append(arch)
    # 3) kalanları ağırlıklı doldur
    for bi in range(len(C.BRANCHES)):
        while len(per_branch[bi]) < branch_sizes[bi]:
            pairs = [(a, n) for a, n in remaining.items() if n > 0]
            if not pairs:
                pairs = [(arch_names[0], 1)]
            arch = D.pick_weighted(assign_rng, pairs)
            remaining[arch] = max(0, remaining.get(arch, 0) - 1)
            per_branch[bi].append(arch)

    student_ms = T.local_ms(_dt.date(2025, 9, 1), 10 * 60)
    theta_rng = substream(seed, "people.theta")
    edge_rng = substream(seed, "people.edge")

    for bi, (bname, _grade, _n) in enumerate(C.BRANCHES):
        assign_rng.shuffle(per_branch[bi])
        for k, arch in enumerate(per_branch[bi]):
            s = new_user("student", "m" if (bi + k) % 2 == 0 else "f",
                         student_ms + (bi * 40 + k) * 30_000)
            s.branch = bname
            s.archetype = arch
            s.arch = C.ARCHETYPES[arch]
            ctx.students.append(s)

    # arketip parametreleri
    for s in ctx.students:
        a = s.arch
        mu, sigma = a["theta"]
        lo, hi = a["clip"]
        s.theta_base = D.clip(theta_rng.gauss(mu, sigma), lo, hi)
        s.theta_shift = theta_rng.gauss(0.0, 0.25) if a.get("rising") else 0.0
        s.omega = a["omega"]
        if a.get("breaking"):
            d = C.A6_BREAK_DATES[theta_rng.randrange(len(C.A6_BREAK_DATES))]
            s.break_ms = T.local_ms(d, 8 * 60)
        if s.archetype == "A3":
            s.gap_area = D.pick_weighted(theta_rng, C.A3_GAP_COURSE_WEIGHTS)
        s.dim_delta = _dim_delta_for(theta_rng, s.archetype)

    # kenar durumlar #1, #2, #7
    pool = [s for s in ctx.students]
    edge_rng.shuffle(pool)
    n_join = max(1, round(len(C.EDGE_MIDTERM_JOIN_DATES) * scale.ratio))
    n_leave = max(1, round(len(C.EDGE_LEAVER_DATES) * scale.ratio))
    n_cold = max(1, round(C.EDGE_COLD_START_EXTRA * scale.ratio))
    cursor = 0
    for i in range(n_join):
        s = pool[cursor]; cursor += 1
        d = C.EDGE_MIDTERM_JOIN_DATES[i % len(C.EDGE_MIDTERM_JOIN_DATES)]
        s.join_ms = T.local_ms(d, 8 * 60)
        s.created_ms = s.join_ms
        s.edge.append("mid_term_join")
        s.edge.append("cold_start")
    for i in range(n_leave):
        s = pool[cursor]; cursor += 1
        d = C.EDGE_LEAVER_DATES[i % len(C.EDGE_LEAVER_DATES)]
        s.leave_ms = T.local_ms(d, 18 * 60)
        s.edge.append("leaver")
    for _ in range(n_cold):
        s = pool[cursor]; cursor += 1
        s.edge.append("cold_start")
        s.edge.append("passive")

    # ULID kendi zaman damgasından türemeli: dönem ortası kaydolanların
    # kimliği kayıt tarihine göre yeniden üretilir.
    rekey = UlidFactory(substream(seed, "ulid.user.join"))
    for s in ctx.students:
        if "mid_term_join" in s.edge:
            s.key = rekey.make(s.created_ms)
            s.rid = rid("user", s.key)

    # kenar durum #9: bir derste hiç ödev teslim etmeyen
    n_nohw = max(1, round(C.EDGE_NO_HOMEWORK_COURSE * scale.ratio))
    for _ in range(n_nohw):
        s = pool[cursor]; cursor += 1
        s.edge.append("no_homework_course")

    # ------------------------------------------------------------------
    # Veliler ve parent_link (SENARYO §1.2)
    # ------------------------------------------------------------------
    parent_ms = T.local_ms(_dt.date(2025, 9, 3), 11 * 60)
    n_parents = max(1, round(C.N_PARENTS_FULL * scale.ratio))
    for i in range(n_parents):
        p = new_user("parent", "m" if i % 2 == 0 else "f", parent_ms + i * 20_000)
        ctx.parents.append(p)

    link_rng = substream(seed, "people.parent_link")
    students = list(ctx.students)
    link_rng.shuffle(students)
    n_no_parent = max(0, round(C.PARENT_NO_PARENT_STUDENTS * scale.ratio))
    linked = students[:max(0, len(students) - n_no_parent)]
    for s in students[len(linked):]:
        s.edge.append("no_parent")

    n_sibling = max(0, round(C.PARENT_SIBLING_COUNT * scale.ratio))
    n_sibling = min(n_sibling, len(ctx.parents), len(linked) // 2)
    links = []            # (parent, student)
    parents = list(ctx.parents)
    link_rng.shuffle(parents)
    p_cursor = 0
    s_cursor = 0
    for _ in range(n_sibling):
        p = parents[p_cursor]; p_cursor += 1
        for _ in range(2):
            if s_cursor < len(linked):
                links.append((p, linked[s_cursor])); s_cursor += 1
    while s_cursor < len(linked) and p_cursor < len(parents):
        p = parents[p_cursor]; p_cursor += 1
        links.append((p, linked[s_cursor])); s_cursor += 1
    # kalan veliler ikinci veli (anne/baba) olarak eklenir
    second = 0
    while p_cursor < len(parents) and second < len(linked):
        p = parents[p_cursor]; p_cursor += 1
        links.append((p, linked[second])); second += 1
    # vasi eklemeleri
    n_guardian = max(0, round(C.PARENT_EXTRA_GUARDIAN * scale.ratio))
    for i in range(n_guardian):
        if not parents or not linked:
            break
        p = parents[i % len(parents)]
        target = linked[(second + i) % len(linked)]
        if (p, target) not in links:
            links.append((p, target))

    ctx.parent_links = links
    ctx.parents_of = {}
    for p, s in links:
        ctx.parents_of.setdefault(s.key, []).append(p)

    link_fac = UlidFactory(substream(seed, "ulid.parent_link"))
    for p, s in links:
        ctx.emitter.add("parent_link", {
            "id": rid("parent_link", "%s_%s" % (p.key, s.key)),
            "parent": p.rid,
            "student": s.rid,
            "linked_by": ctx.admin.rid,
        })
    del link_fac

    # ------------------------------------------------------------------
    # Canlı giriş oturumları (session)
    # ------------------------------------------------------------------
    sess_rng = substream(seed, "people.session")
    sess_fac = UlidFactory(substream(seed, "ulid.session"))
    n_sessions = max(2, round(C.LIVE_SESSIONS * scale.ratio))
    candidates = ([ctx.admin] + ctx.managers + ctx.teachers[:8]
                  + ctx.students[:max(1, n_sessions)] + ctx.parents[:4])
    sess_rng.shuffle(candidates)
    for i in range(min(n_sessions, len(candidates))):
        u = candidates[i]
        created = T.T_NOW - sess_rng.randint(0, 3 * C.DAY_MS)
        token = "%064x" % sess_rng.getrandbits(256)
        ctx.emitter.add("session", {
            "id": rid("session", sess_fac.make(created)),
            "user": u.rid,
            "token": token,
            "expires_at": created + C.SESSION_DURATION_MS,
        })
