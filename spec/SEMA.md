# Hezarfen Okul Veritabanı Şeması — Tohum Verisi (Seed) Referansı

> Kaynak: `hezarfen_backend-main/src/migration_sql.rs` (1518 satır, tamamı okundu), `src/domain/`, `src/db/`, `src/constant.rs`, `src/database.rs`, `src/tenant.rs`, `src/module.rs`, `tests/common/mod.rs`.  
> Bu belgedeki tüm `dosya:satır` referansları `hezarfen_backend-main/src/` köküne görelidir (`tests/` ile başlayanlar hariç).  
> Makine okunabilir eşdeğeri: `spec/schema.json`.  
> SurrealDB sürümü: **3.2** (`Cargo.toml:22`).

**Özet sayılar**

| | |
|---|---|
| Okul veritabanı tablosu | **60** |
| Kontrol (control) veritabanı tablosu | **4** |
| Toplam alan tanımı (iç içe olanlar dahil) | **409** |
| `DEFINE FIELD ... VALUE` sayısı | **0** |
| `DEFINE FIELD ... ASSERT` sayısı | **0** |
| `SCHEMAFULL` olmayan tablo | **0** (hepsi SCHEMAFULL) |

> **Not — tablo sayısı:** Görevde 71 tablo denmişti. `migration_sql.rs`'te fiilen **60 okul tablosu** + **4 kontrol tablosu** = **64** tablo tanımlıdır. Ayrıca `REMOVE TABLE IF EXISTS ai_worker` (`migration_sql.rs:255`) ve `REMOVE TABLE IF EXISTS migration_lock` (`migration_sql.rs:260`) ile iki tablo emekliye ayrılmıştır — bunlara **asla** yazmayın.

---

## 1. Tablo bazında tam alan şeması

Gösterim: `opsiyonel` sütunu `option<...>` tipini; `RO` sütunu `READONLY` olmayı; `OW` sütunu alanın `DEFINE FIELD OVERWRITE` ile (var olan bir veritabanında tip değiştirerek) tanımlandığını gösterir. Hiçbir alanda `VALUE` veya `ASSERT` yoktur — yani **yazdığınız değer asla ezilmez ve veritabanı hiçbir enum'u doğrulamaz**.

### 1.1 Okul veritabanı tabloları (yükleme sırasına göre)

### `kind_ref`

`SCHEMAFULL` — `migration_sql.rs:928`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `count` | `option<int>` | evet | `—` | — | — | migration_sql.rs:929 |
| `retired` | `option<bool>` | evet | `—` | — | — | migration_sql.rs:930 |

**Kayıt id'si:** `natural_key` — desen: `{exam_kind_name}` — (domain/exam_result.rs:25-27 / db/cap.rs:681)

> kind_ref:quiz - one row per exam-kind NAME, created by the first claim

### `migration_mark`

`SCHEMAFULL` — `migration_sql.rs:956`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `done_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:957 |
| `fingerprint` | `option<int>` | evet | `—` | — | — | migration_sql.rs:958 |

**Kayıt id'si:** `fixed` — sabit: `migration_mark:board_roster , migration_mark:profile_counters` — (migration_sql.rs:1354,1432)

> written by migrate(). Do NOT seed these unless you deliberately want to suppress the one-time backfills.

### `rate_limit`

`SCHEMAFULL` — `migration_sql.rs:268`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `hits` | `int` | **hayır** | `0` | — | — | migration_sql.rs:269 |
| `window_start` | `int` | **hayır** | `—` | — | — | migration_sql.rs:270 |

**Kayıt id'si:** `deterministic_opaque` — (migration_sql.rs:268)

> one row per tier+client+window, built in crate::rate_limit. NOT seed-relevant.

### `settings`

`SCHEMAFULL` — `migration_sql.rs:638`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `exam_kinds` | `array<object>` | **hayır** | `—` | — | — | migration_sql.rs:639 |
| `exam_kinds.*.name` | `string` | **hayır** | `—` | — | — | migration_sql.rs:640 |
| `exam_kinds.*.weight` | `int` | **hayır** | `—` | — | — | migration_sql.rs:641 |
| `attendance_statuses` | `array<string>` | **hayır** | `—` | — | — | migration_sql.rs:642 |
| `grade_bands` | `array<object>` | **hayır** | `—` | — | — | migration_sql.rs:643 |
| `grade_bands.*.min` | `int` | **hayır** | `—` | — | — | migration_sql.rs:644 |
| `grade_bands.*.label` | `string` | **hayır** | `—` | — | — | migration_sql.rs:645 |
| `max_file_bytes` | `option<int>` | evet | `—` | — | — | migration_sql.rs:646 |
| `chatbot_history_turns` | `option<int>` | evet | `—` | — | — | migration_sql.rs:647 |
| `max_chatbot_threads` | `option<int>` | evet | `—` | — | — | migration_sql.rs:648 |
| `max_chatbot_message_len` | `option<int>` | evet | `—` | — | — | migration_sql.rs:649 |
| `meal_slots` | `option<array<object>>` | evet | `—` | — | — | migration_sql.rs:660 |
| `meal_slots.*.name` | `string` | **hayır** | `—` | — | — | migration_sql.rs:661 |
| `meal_slots.*.serving_minute` | `option<int>` | evet | `—` | — | — | migration_sql.rs:667 |
| `dietary_tags` | `option<array<string>>` | evet | `—` | — | — | migration_sql.rs:668 |
| `meal_cancel_cutoff_minutes` | `option<int>` | evet | `—` | — | — | migration_sql.rs:669 |

**Kayıt id'si:** `fixed` — sabit: `settings:school` — (domain/settings.rs:239-241 (SETTINGS_TABLE constant.rs:893, SETTINGS_KEY constant.rs:805))

> singleton. An absent row reads as the built-in defaults, so seeding it is OPTIONAL - but required if you want non-default exam_kinds / meal_slots / dietary_tags.

### `slot_ref`

`SCHEMAFULL` — `migration_sql.rs:932`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `count` | `option<int>` | evet | `—` | — | — | migration_sql.rs:933 |
| `retired` | `option<bool>` | evet | `—` | — | — | migration_sql.rs:934 |

**Kayıt id'si:** `natural_key` — desen: `{meal_slot_name}` — (domain/menu.rs:30-32 / db/menu.rs:126)

> slot_ref:lunch - one row per meal-slot NAME

### `term`

`SCHEMAFULL` — `migration_sql.rs:305`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `name` | `string` | **hayır** | `—` | — | — | migration_sql.rs:306 |
| `starts_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:307 |
| `ends_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:308 |
| `archived_at` | `option<int>` | evet | `—` | — | — | migration_sql.rs:312 |
| `course_count` | `option<int>` | evet | `—` | — | — | migration_sql.rs:316 |
| `class_count` | `option<int>` | evet | `—` | — | — | migration_sql.rs:319 |

**Kayıt id'si:** `ulid_monotonic` — (domain/term.rs:26)

> domain::monotonic_id::next_ulid() - ms-monotonic ULID, 26 chars Crockford base32

### `user`

`SCHEMAFULL` — `migration_sql.rs:49`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `username` | `string` | **hayır** | `—` | — | — | migration_sql.rs:50 |
| `password_hash` | `string` | **hayır** | `—` | — | — | migration_sql.rs:51 |
| `role` | `string` | **hayır** | `'student'` | — | — | migration_sql.rs:52 |
| `name` | `option<string>` | evet | `—` | — | — | migration_sql.rs:53 |
| `surname` | `option<string>` | evet | `—` | — | — | migration_sql.rs:54 |
| `email` | `option<string>` | evet | `—` | — | — | migration_sql.rs:55 |
| `phone` | `option<string>` | evet | `—` | — | — | migration_sql.rs:56 |
| `birth_date` | `option<string>` | evet | `—` | — | — | migration_sql.rs:57 |
| `theme` | `option<string>` | evet | `—` | — | — | migration_sql.rs:58 |
| `language` | `option<string>` | evet | `—` | — | — | migration_sql.rs:59 |
| `palette_color` | `option<string>` | evet | `—` | — | — | migration_sql.rs:60 |
| `display_name` | `option<string>` | evet | `—` | — | — | migration_sql.rs:61 |
| `bio` | `option<string>` | evet | `—` | — | — | migration_sql.rs:62 |
| `avatar_file` | `option<string>` | evet | `—` | — | — | migration_sql.rs:63 |
| `avatar_content_type` | `option<string>` | evet | `—` | — | — | migration_sql.rs:64 |
| `avatar_size` | `option<int>` | evet | `—` | — | — | migration_sql.rs:65 |
| `chatbot_thread_count` | `option<int>` | evet | `—` | — | — | migration_sql.rs:66 |
| `board_count` | `option<int>` | evet | `—` | — | — | migration_sql.rs:67 |
| `homework_submitted_total` | `option<int>` | evet | `—` | — | — | migration_sql.rs:73 |
| `homework_on_time_total` | `option<int>` | evet | `—` | — | — | migration_sql.rs:74 |
| `exam_sat_total` | `option<int>` | evet | `—` | — | — | migration_sql.rs:75 |
| `pomodoro_finished_total` | `option<int>` | evet | `—` | — | — | migration_sql.rs:76 |
| `pomodoro_focus_ms_total` | `option<int>` | evet | `—` | — | — | migration_sql.rs:77 |
| `marks_given_total` | `option<int>` | evet | `—` | — | — | migration_sql.rs:84 |
| `lessons_held_total` | `option<int>` | evet | `—` | — | — | migration_sql.rs:85 |
| `pool_approved_total` | `option<int>` | evet | `—` | — | — | migration_sql.rs:86 |
| `pool_published_total` | `option<int>` | evet | `—` | — | — | migration_sql.rs:87 |
| `lessons_attended_total` | `option<int>` | evet | `—` | — | — | migration_sql.rs:88 |
| `high_mark_total` | `option<int>` | evet | `—` | — | — | migration_sql.rs:89 |
| `study_streak_longest` | `option<int>` | evet | `—` | — | — | migration_sql.rs:90 |
| `study_streak_current` | `option<int>` | evet | `—` | — | — | migration_sql.rs:91 |
| `study_streak_last_day` | `option<int>` | evet | `—` | — | — | migration_sql.rs:92 |
| `pomodoro_counted_day` | `option<int>` | evet | `—` | — | — | migration_sql.rs:98 |
| `pomodoro_counted_today` | `option<int>` | evet | `—` | — | — | migration_sql.rs:99 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `user_username` | `username` | **UNIQUE** | migration_sql.rs:100 |

**Kayıt id'si:** `ulid_monotonic` — (domain/user.rs:32)

> domain::monotonic_id::next_ulid() - ms-monotonic ULID, 26 chars Crockford base32

### `appointment_slot`

`SCHEMAFULL` — `migration_sql.rs:745`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `teacher` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:746 |
| `starts_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:747 |
| `ends_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:748 |
| `occupied` | `option<int>` | evet | `—` | — | — | migration_sql.rs:749 |
| `note` | `option<string>` | evet | `—` | — | — | migration_sql.rs:750 |
| `series` | `option<string>` | evet | `—` | — | — | migration_sql.rs:751 |
| `created_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:752 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `appointment_slot_teacher_starts` | `teacher, starts_at` | — | migration_sql.rs:753 |
| `appointment_slot_series` | `series` | — | migration_sql.rs:754 |

**Kayıt id'si:** `ulid_monotonic` — (domain/appointment_slot.rs:41-44)

> domain::monotonic_id::next_ulid() - ms-monotonic ULID, 26 chars Crockford base32

### `badge_award`

`SCHEMAFULL` — `migration_sql.rs:913`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `user` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:914 |
| `badge` | `string` | **hayır** | `—` | — | — | migration_sql.rs:915 |
| `earned_at` | `option<int>` | evet | `—` | — | — | migration_sql.rs:916 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `badge_award_user` | `user` | — | migration_sql.rs:919 |

**Kayıt id'si:** `composite` — desen: `{user_key}_{badge_id}` — (db/badge.rs:94-96)

> badge_id from the 34-entry BADGES catalog, constant.rs:1095

### `board`

`SCHEMAFULL` — `migration_sql.rs:142`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `creator` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:143 |
| `title` | `string` | **hayır** | `—` | — | — | migration_sql.rs:144 |
| `participants` | `array<record<user>>` | **hayır** | `—` | — | — | migration_sql.rs:145 |
| `locked` | `bool` | **hayır** | `false` | — | — | migration_sql.rs:146 |
| `locked_by` | `option<record<user>>` | evet | `—` | — | — | migration_sql.rs:147 |
| `locked_at` | `option<int>` | evet | `—` | — | — | migration_sql.rs:148 |
| `epoch` | `int` | **hayır** | `0` | — | — | migration_sql.rs:149 |
| `epoch_stroke_count` | `option<int>` | evet | `—` | — | — | migration_sql.rs:151 |
| `total_stroke_count` | `option<int>` | evet | `—` | — | — | migration_sql.rs:152 |
| `closed_at` | `option<int>` | evet | `—` | — | — | migration_sql.rs:154 |
| `created_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:155 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `board_creator` | `creator` | — | migration_sql.rs:156 |
| `board_participants` | `participants` | — | migration_sql.rs:160 |

**Kayıt id'si:** `ulid_monotonic` — (domain/board.rs:31)

> domain::monotonic_id::next_ulid() - ms-monotonic ULID, 26 chars Crockford base32

### `chatbot_thread`

`SCHEMAFULL` — `migration_sql.rs:224`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `user_id` | `record<user>` | **hayır** | `—` | **evet** | — | migration_sql.rs:225 |
| `title` | `option<string>` | evet | `—` | — | — | migration_sql.rs:226 |
| `created_at` | `int` | **hayır** | `—` | **evet** | — | migration_sql.rs:227 |
| `updated_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:228 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `chatbot_thread_user_updated` | `user_id, updated_at` | — | migration_sql.rs:229 |

**Kayıt id'si:** `ulid_monotonic` — (domain/chatbot_thread.rs:25)

> domain::monotonic_id::next_ulid() - ms-monotonic ULID, 26 chars Crockford base32

### `class_group`

`SCHEMAFULL` — `migration_sql.rs:346`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `name` | `string` | **hayır** | `—` | — | — | migration_sql.rs:347 |
| `grade` | `option<string>` | evet | `—` | — | — | migration_sql.rs:348 |
| `term` | `option<record<term>>` | evet | `—` | — | — | migration_sql.rs:349 |
| `creator` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:350 |
| `teacher` | `option<record<user>>` | evet | `—` | — | — | migration_sql.rs:351 |
| `class_member_count` | `option<int>` | evet | `—` | — | — | migration_sql.rs:352 |
| `class_course_count` | `option<int>` | evet | `—` | — | — | migration_sql.rs:353 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `class_group_grade` | `grade` | — | migration_sql.rs:356 |

**Kayıt id'si:** `ulid_monotonic` — (domain/class_group.rs:31)

> domain::monotonic_id::next_ulid() - ms-monotonic ULID, 26 chars Crockford base32

### `course`

`SCHEMAFULL` — `migration_sql.rs:321`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `creator` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:322 |
| `teachers` | `array<record<user>>` | **hayır** | `[]` | — | — | migration_sql.rs:323 |
| `teachers[*]` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:324 |
| `title` | `string` | **hayır** | `—` | — | — | migration_sql.rs:325 |
| `description` | `string` | **hayır** | `—` | — | — | migration_sql.rs:326 |
| `kind` | `string` | **hayır** | `'course'` | — | — | migration_sql.rs:327 |
| `term` | `option<record<term>>` | evet | `—` | — | — | migration_sql.rs:328 |
| `capacity` | `option<int>` | evet | `—` | — | — | migration_sql.rs:329 |
| `enrollment_count` | `option<int>` | evet | `—` | — | — | migration_sql.rs:330 |

**Kayıt id'si:** `ulid_monotonic` — (domain/course.rs:18)

> domain::monotonic_id::next_ulid() - ms-monotonic ULID, 26 chars Crockford base32

### `dietary_profile`

`SCHEMAFULL` — `migration_sql.rs:807`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `student` | `record<user>` | **hayır** | `—` | **evet** | — | migration_sql.rs:808 |
| `tags` | `array<string>` | **hayır** | `[]` | — | — | migration_sql.rs:809 |
| `tags[*]` | `string` | **hayır** | `—` | — | — | migration_sql.rs:810 |
| `note` | `option<string>` | evet | `—` | — | — | migration_sql.rs:811 |
| `updated_by` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:812 |
| `updated_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:813 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `dietary_profile_student` | `student` | **UNIQUE** | migration_sql.rs:814 |

**Kayıt id'si:** `natural_key` — desen: `{student_key}` — (domain/dietary_profile.rs:31)

### `fee_plan`

`SCHEMAFULL` — `migration_sql.rs:863`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `name` | `string` | **hayır** | `—` | — | — | migration_sql.rs:864 |
| `installments` | `array<object>` | **hayır** | `—` | — | — | migration_sql.rs:865 |
| `installments.*.amount_minor` | `int` | **hayır** | `—` | — | — | migration_sql.rs:866 |
| `installments.*.due_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:867 |
| `created_by` | `record<user>` | **hayır** | `—` | **evet** | — | migration_sql.rs:868 |
| `created_at` | `int` | **hayır** | `—` | **evet** | — | migration_sql.rs:869 |
| `assignment_count` | `option<int>` | evet | `—` | — | — | migration_sql.rs:875 |

**Kayıt id'si:** `ulid_monotonic` — (domain/fee_plan.rs:32)

> domain::monotonic_id::next_ulid() - ms-monotonic ULID, 26 chars Crockford base32

### `meal_ledger`

`SCHEMAFULL` — `migration_sql.rs:846`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `student` | `record<user>` | **hayır** | `—` | **evet** | — | migration_sql.rs:847 |
| `kind` | `string` | **hayır** | `—` | **evet** | — | migration_sql.rs:848 |
| `amount_minor` | `int` | **hayır** | `—` | **evet** | — | migration_sql.rs:849 |
| `source` | `option<record>` | evet | `—` | **evet** | — | migration_sql.rs:850 |
| `method` | `option<string>` | evet | `—` | **evet** | — | migration_sql.rs:851 |
| `note` | `option<string>` | evet | `—` | **evet** | — | migration_sql.rs:852 |
| `recorded_by` | `record<user>` | **hayır** | `—` | **evet** | — | migration_sql.rs:853 |
| `created_at` | `int` | **hayır** | `—` | **evet** | — | migration_sql.rs:854 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `meal_ledger_student` | `student` | — | migration_sql.rs:855 |

**Kayıt id'si:** `composite` — desen: `{booking_key}_c{attempt} (charge) | {booking_key}_r{attempt} (reversal) | {student_key}_k_{request_key} (idempotent credit) | <local ULID> (free credit)` — (domain/meal_ledger.rs:87-137)

> marker chars: c=charge, r=reversal, k=credit

### `menu`

`SCHEMAFULL` — `migration_sql.rs:781`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `date` | `string` | **hayır** | `—` | **evet** | — | migration_sql.rs:782 |
| `slot` | `string` | **hayır** | `—` | **evet** | — | migration_sql.rs:783 |
| `capacity` | `option<int>` | evet | `—` | — | — | migration_sql.rs:784 |
| `seats_booked` | `option<int>` | evet | `—` | — | — | migration_sql.rs:790 |
| `version` | `option<int>` | evet | `—` | — | — | migration_sql.rs:791 |
| `created_by` | `record<user>` | **hayır** | `—` | **evet** | — | migration_sql.rs:792 |
| `created_at` | `int` | **hayır** | `—` | **evet** | — | migration_sql.rs:793 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `menu_date_slot` | `date, slot` | **UNIQUE** | migration_sql.rs:794 |

**Kayıt id'si:** `natural_key` — desen: `{date}_{slot}   e.g.  2026-09-01_lunch` — (domain/menu.rs:44-49)

> date is YYYY-MM-DD text; slot text may not contain / \ ? # % (domain/menu.rs:138-164). Matches UNIQUE index menu_date_slot.

### `message`

`SCHEMAFULL` — `migration_sql.rs:116`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `sender` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:117 |
| `recipient` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:118 |
| `subject` | `string` | **hayır** | `—` | — | — | migration_sql.rs:119 |
| `body` | `string` | **hayır** | `—` | — | — | migration_sql.rs:120 |
| `label` | `option<string>` | evet | `—` | — | — | migration_sql.rs:121 |
| `sent_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:122 |
| `read` | `bool` | **hayır** | `false` | — | — | migration_sql.rs:123 |
| `sender_folder` | `string` | **hayır** | `'sent'` | — | — | migration_sql.rs:124 |
| `recipient_folder` | `string` | **hayır** | `'inbox'` | — | — | migration_sql.rs:125 |
| `sender_origin` | `option<string>` | evet | `—` | — | — | migration_sql.rs:130 |
| `recipient_origin` | `option<string>` | evet | `—` | — | — | migration_sql.rs:131 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `message_sender` | `sender` | — | migration_sql.rs:132 |
| `message_recipient` | `recipient` | — | migration_sql.rs:133 |

**Kayıt id'si:** `ulid_monotonic` — (domain/message.rs:108)

> domain::monotonic_id::next_ulid() - ms-monotonic ULID, 26 chars Crockford base32

### `note`

`SCHEMAFULL` — `migration_sql.rs:109`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `user` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:110 |
| `title` | `string` | **hayır** | `—` | — | — | migration_sql.rs:111 |
| `content` | `string` | **hayır** | `—` | — | — | migration_sql.rs:112 |
| `file_count` | `option<int>` | evet | `—` | — | — | migration_sql.rs:113 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `note_user` | `user` | — | migration_sql.rs:114 |

**Kayıt id'si:** `ulid_monotonic` — (domain/note.rs:17)

> domain::monotonic_id::next_ulid() - ms-monotonic ULID, 26 chars Crockford base32

### `parent_link`

`SCHEMAFULL` — `migration_sql.rs:417`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `parent` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:418 |
| `student` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:419 |
| `linked_by` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:420 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `parent_link_parent_student` | `parent, student` | **UNIQUE** | migration_sql.rs:421 |
| `parent_link_parent` | `parent` | — | migration_sql.rs:422 |
| `parent_link_student` | `student` | — | migration_sql.rs:423 |

**Kayıt id'si:** `composite` — desen: `{parent_key}_{student_key}` — (domain/parent_link.rs:15-18)

### `payment_ledger`

`SCHEMAFULL` — `migration_sql.rs:894`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `student` | `record<user>` | **hayır** | `—` | **evet** | — | migration_sql.rs:895 |
| `kind` | `string` | **hayır** | `—` | **evet** | — | migration_sql.rs:896 |
| `amount_minor` | `int` | **hayır** | `—` | **evet** | — | migration_sql.rs:897 |
| `source` | `option<record>` | evet | `—` | **evet** | — | migration_sql.rs:898 |
| `due_at` | `option<int>` | evet | `—` | **evet** | — | migration_sql.rs:899 |
| `method` | `option<string>` | evet | `—` | **evet** | — | migration_sql.rs:900 |
| `note` | `option<string>` | evet | `—` | **evet** | — | migration_sql.rs:901 |
| `recorded_by` | `record<user>` | **hayır** | `—` | **evet** | — | migration_sql.rs:902 |
| `created_at` | `int` | **hayır** | `—` | **evet** | — | migration_sql.rs:903 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `payment_ledger_student` | `student` | — | migration_sql.rs:904 |
| `payment_ledger_source` | `source` | — | migration_sql.rs:905 |

**Kayıt id'si:** `composite` — desen: `{assignment_key}_c{n} (charge, n 1-based) | {line_key}_r (reversal) | {line_key}_k_{request_key} (payment) | {line_key}_kr_{request_key} (refund) | <monotonic ULID> (free)` — (domain/payment_ledger.rs:66-116)

> '_' may never appear inside a request_key; ULID keys are [0-9A-Z] only, so the grammar parses uniquely

### `pomodoro_session`

`SCHEMAFULL` — `migration_sql.rs:456`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `user` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:457 |
| `started_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:458 |
| `finished_at` | `option<int>` | evet | `—` | — | — | migration_sql.rs:459 |
| `counted` | `option<bool>` | evet | `—` | — | — | migration_sql.rs:464 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `pomodoro_session_user` | `user` | — | migration_sql.rs:465 |

**Kayıt id'si:** `composite` — desen: `open_{user_key}  (WHILE OPEN)  |  <monotonic ULID>  (once closed)` — (domain/pomodoro.rs:17-20 (closed) / domain/pomodoro.rs:29-32 (open))

> same open_/closed split as work_entry

### `pool_question`

`SCHEMAFULL` — `migration_sql.rs:615`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `asker` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:616 |
| `title` | `string` | **hayır** | `—` | — | — | migration_sql.rs:617 |
| `body` | `string` | **hayır** | `—` | — | — | migration_sql.rs:618 |
| `status` | `string` | **hayır** | `'pending'` | — | — | migration_sql.rs:619 |
| `asked_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:620 |
| `approved_by` | `option<record<user>>` | evet | `—` | — | — | migration_sql.rs:621 |
| `image_file` | `option<string>` | evet | `—` | — | — | migration_sql.rs:622 |
| `image_content_type` | `option<string>` | evet | `—` | — | — | migration_sql.rs:623 |
| `image_size` | `option<int>` | evet | `—` | — | — | migration_sql.rs:624 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `pool_question_status` | `status` | — | migration_sql.rs:625 |
| `pool_question_asker` | `asker` | — | migration_sql.rs:626 |

**Kayıt id'si:** `ulid_monotonic` — (domain/pool_question.rs:36)

> domain::monotonic_id::next_ulid() - ms-monotonic ULID, 26 chars Crockford base32

### `session`

`SCHEMAFULL` — `migration_sql.rs:102`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `user` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:103 |
| `token` | `string` | **hayır** | `—` | — | — | migration_sql.rs:104 |
| `expires_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:105 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `session_token` | `token` | **UNIQUE** | migration_sql.rs:106 |
| `session_expires` | `expires_at` | — | migration_sql.rs:107 |

**Kayıt id'si:** `ulid_random` — (domain/session.rs:14)

> ulid::Ulid::new() - random low 80 bits

### `work_entry`

`SCHEMAFULL` — `migration_sql.rs:450`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `user` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:451 |
| `check_in` | `int` | **hayır** | `—` | — | — | migration_sql.rs:452 |
| `check_out` | `option<int>` | evet | `—` | — | — | migration_sql.rs:453 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `work_entry_user` | `user` | — | migration_sql.rs:454 |

**Kayıt id'si:** `composite` — desen: `open_{user_key}  (WHILE OPEN)  |  <monotonic ULID>  (once closed)` — (domain/work_entry.rs:28 (closed) / domain/work_entry.rs:37-40 (open))

> CRITICAL: an in-progress work entry lives at the fixed id open_<user ULID>; closing it moves the row to a fresh ULID id.

### `appointment`

`SCHEMAFULL` — `migration_sql.rs:756`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `slot` | `record<appointment_slot>` | **hayır** | `—` | — | — | migration_sql.rs:757 |
| `requester` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:758 |
| `status` | `string` | **hayır** | `'pending'` | — | — | migration_sql.rs:759 |
| `reason` | `string` | **hayır** | `—` | — | — | migration_sql.rs:760 |
| `proposed_starts_at` | `option<int>` | evet | `—` | — | — | migration_sql.rs:761 |
| `proposed_ends_at` | `option<int>` | evet | `—` | — | — | migration_sql.rs:762 |
| `proposed_by` | `option<record<user>>` | evet | `—` | — | — | migration_sql.rs:763 |
| `decided_by` | `option<record<user>>` | evet | `—` | — | — | migration_sql.rs:764 |
| `cancelled_by` | `option<record<user>>` | evet | `—` | — | — | migration_sql.rs:765 |
| `cancel_reason` | `option<string>` | evet | `—` | — | — | migration_sql.rs:766 |
| `reject_reason` | `option<string>` | evet | `—` | — | — | migration_sql.rs:767 |
| `created_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:768 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `appointment_slot_ref` | `slot` | — | migration_sql.rs:769 |
| `appointment_requester` | `requester` | — | migration_sql.rs:770 |
| `appointment_status` | `status` | — | migration_sql.rs:771 |

**Kayıt id'si:** `ulid_monotonic_local` — (domain/appointment.rs:67-72)

> file-local LazyLock<Mutex<Generator>>; semantics identical to next_ulid

### `board_stroke`

`SCHEMAFULL` — `migration_sql.rs:162`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `board` | `record<board>` | **hayır** | `—` | — | — | migration_sql.rs:163 |
| `author` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:164 |
| `kind` | `string` | **hayır** | `—` | — | — | migration_sql.rs:168 |
| `payload` | `option<string>` | evet | `—` | — | — | migration_sql.rs:169 |
| `count` | `option<int>` | evet | `—` | — | — | migration_sql.rs:170 |
| `epoch` | `int` | **hayır** | `—` | — | — | migration_sql.rs:171 |
| `created_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:172 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `board_stroke_board_epoch` | `board, epoch` | — | migration_sql.rs:175 |
| `board_stroke_board_kind` | `board, kind` | — | migration_sql.rs:177 |

**Kayıt id'si:** `ulid_monotonic` — (domain/board_stroke.rs:69)

> domain::monotonic_id::next_ulid() - ms-monotonic ULID, 26 chars Crockford base32

### `chatbot_message`

`SCHEMAFULL` — `migration_sql.rs:231`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `thread_id` | `record<chatbot_thread>` | **hayır** | `—` | **evet** | — | migration_sql.rs:232 |
| `user_id` | `record<user>` | **hayır** | `—` | **evet** | — | migration_sql.rs:233 |
| `role` | `string` | **hayır** | `—` | **evet** | — | migration_sql.rs:234 |
| `content` | `string` | **hayır** | `—` | — | — | migration_sql.rs:235 |
| `status` | `string` | **hayır** | `—` | — | — | migration_sql.rs:236 |
| `truncated` | `bool` | **hayır** | `false` | — | — | migration_sql.rs:237 |
| `error_code` | `option<string>` | evet | `—` | — | — | migration_sql.rs:238 |
| `created_at` | `int` | **hayır** | `—` | **evet** | — | migration_sql.rs:239 |
| `completed_at` | `option<int>` | evet | `—` | — | — | migration_sql.rs:240 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `chatbot_message_thread_created` | `thread_id, created_at` | — | migration_sql.rs:247 |
| `chatbot_message_user` | `user_id` | — | migration_sql.rs:248 |
| `chatbot_message_status_created` | `status, created_at` | — | migration_sql.rs:250 |

**Kaldırılmış alanlar (ASLA yazmayın):** `claimed_by` (migration_sql.rs:245), `claimed_at` (migration_sql.rs:246)

**Kayıt id'si:** `ulid_monotonic_local` — (domain/chatbot_message.rs:47)

> file-local LazyLock<Mutex<Generator>>; semantics identical to next_ulid

### `class_blueprint`

`SCHEMAFULL` — `migration_sql.rs:364`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `grade` | `string` | **hayır** | `—` | — | — | migration_sql.rs:365 |
| `courses` | `array<record<course>>` | **hayır** | `—` | — | — | migration_sql.rs:366 |
| `creator` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:367 |

**Kayıt id'si:** `natural_key` — desen: `{grade}` — (domain/class_blueprint.rs:41)

> the grade label IS the record key -> one blueprint per grade, by construction

### `class_member`

`SCHEMAFULL` — `migration_sql.rs:369`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `class` | `record<class_group>` | **hayır** | `—` | — | — | migration_sql.rs:370 |
| `user` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:371 |
| `added_by` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:372 |
| `added_at` | `option<int>` | evet | `—` | — | — | migration_sql.rs:380 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `class_member_class_user` | `class, user` | **UNIQUE** | migration_sql.rs:381 |
| `class_member_class` | `class` | — | migration_sql.rs:382 |
| `class_member_user` | `user` | — | migration_sql.rs:383 |

**Kayıt id'si:** `composite` — desen: `{class_key}_{user_key}` — (domain/class_member.rs:24 -> db/class_pump.rs:676)

### `course_note`

`SCHEMAFULL` — `migration_sql.rs:186`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `course` | `record<course>` | **hayır** | `—` | — | — | migration_sql.rs:187 |
| `author` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:188 |
| `title` | `string` | **hayır** | `—` | — | — | migration_sql.rs:189 |
| `content` | `string` | **hayır** | `—` | — | — | migration_sql.rs:190 |
| `file_count` | `option<int>` | evet | `—` | — | — | migration_sql.rs:191 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `course_note_course` | `course` | — | migration_sql.rs:192 |

**Kayıt id'si:** `ulid_monotonic` — (domain/course_note.rs:19)

> domain::monotonic_id::next_ulid() - ms-monotonic ULID, 26 chars Crockford base32

### `course_session`

`SCHEMAFULL` — `migration_sql.rs:425`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `course` | `record<course>` | **hayır** | `—` | — | — | migration_sql.rs:426 |
| `teacher` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:427 |
| `topic` | `string` | **hayır** | `—` | — | — | migration_sql.rs:428 |
| `starts_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:429 |
| `ends_at` | `option<int>` | evet | `—` | — | — | migration_sql.rs:430 |
| `held_counted_at` | `option<int>` | evet | `—` | — | — | migration_sql.rs:436 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `course_session_course` | `course` | — | migration_sql.rs:437 |

**Kayıt id'si:** `ulid_monotonic` — (domain/course_session.rs:20)

> domain::monotonic_id::next_ulid() - ms-monotonic ULID, 26 chars Crockford base32

### `enrollment`

`SCHEMAFULL` — `migration_sql.rs:406`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `course` | `record<course>` | **hayır** | `—` | — | — | migration_sql.rs:407 |
| `user` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:408 |
| `enrolled_by` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:409 |
| `source` | `option<record<class_group>>` | evet | `—` | — | — | migration_sql.rs:413 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `enrollment_course_user` | `course, user` | **UNIQUE** | migration_sql.rs:414 |
| `enrollment_user` | `user` | — | migration_sql.rs:415 |

**Kayıt id'si:** `composite` — desen: `{course_key}_{user_key}` — (domain/enrollment.rs:17-20)

### `event`

`SCHEMAFULL` — `migration_sql.rs:272`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `creator` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:273 |
| `title` | `string` | **hayır** | `—` | — | — | migration_sql.rs:274 |
| `description` | `string` | **hayır** | `—` | — | — | migration_sql.rs:275 |
| `audience` | `object` | **hayır** | `—` | — | — | migration_sql.rs:276 |
| `audience.kind` | `string` | **hayır** | `—` | — | — | migration_sql.rs:277 |
| `audience.role` | `option<string>` | evet | `—` | — | — | migration_sql.rs:278 |
| `audience.course` | `option<record<course>>` | evet | `—` | — | — | migration_sql.rs:279 |
| `audience.class` | `option<record<class_group>>` | evet | `—` | — | — | migration_sql.rs:280 |
| `audience.capacity` | `option<int>` | evet | `—` | — | — | migration_sql.rs:281 |
| `registration_count` | `option<int>` | evet | `—` | — | — | migration_sql.rs:285 |
| `starts_at` | `option<int>` | evet | `—` | — | — | migration_sql.rs:287 |
| `ends_at` | `option<int>` | evet | `—` | — | — | migration_sql.rs:288 |

**Kaldırılmış alanlar (ASLA yazmayın):** `audience.users` (migration_sql.rs:286)

**Kayıt id'si:** `ulid_monotonic` — (domain/event.rs:23)

> domain::monotonic_id::next_ulid() - ms-monotonic ULID, 26 chars Crockford base32

### `exam`

`SCHEMAFULL` — `migration_sql.rs:467`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `creator` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:468 |
| `course` | `record<course>` | **hayır** | `—` | — | — | migration_sql.rs:469 |
| `title` | `string` | **hayır** | `—` | — | — | migration_sql.rs:470 |
| `description` | `string` | **hayır** | `—` | — | — | migration_sql.rs:471 |
| `kind` | `string` | **hayır** | `—` | — | — | migration_sql.rs:472 |
| `mode` | `option<string>` | evet | `—` | — | — | migration_sql.rs:473 |
| `starts_at` | `option<int>` | evet | `—` | — | — | migration_sql.rs:474 |
| `ends_at` | `option<int>` | evet | `—` | — | — | migration_sql.rs:475 |
| `duration_ms` | `option<int>` | evet | `—` | — | — | migration_sql.rs:476 |
| `max_attempts` | `int` | **hayır** | `1` | — | — | migration_sql.rs:477 |
| `allow_rejoin` | `bool` | **hayır** | `true` | — | — | migration_sql.rs:478 |
| `allow_review` | `bool` | **hayır** | `false` | — | — | migration_sql.rs:479 |
| `draft` | `bool` | **hayır** | `false` | — | — | migration_sql.rs:480 |
| `result_count` | `option<int>` | evet | `—` | — | — | migration_sql.rs:484 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `exam_course` | `course` | — | migration_sql.rs:485 |

**Kayıt id'si:** `ulid_monotonic` — (domain/exam.rs:35)

> domain::monotonic_id::next_ulid() - ms-monotonic ULID, 26 chars Crockford base32

### `fee_plan_assignment`

`SCHEMAFULL` — `migration_sql.rs:880`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `plan` | `record<fee_plan>` | **hayır** | `—` | **evet** | — | migration_sql.rs:881 |
| `student` | `record<user>` | **hayır** | `—` | **evet** | — | migration_sql.rs:882 |
| `assigned_by` | `record<user>` | **hayır** | `—` | **evet** | — | migration_sql.rs:883 |
| `created_at` | `int` | **hayır** | `—` | **evet** | — | migration_sql.rs:884 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `fee_plan_assignment_plan` | `plan` | — | migration_sql.rs:885 |
| `fee_plan_assignment_student` | `student` | — | migration_sql.rs:886 |

**Kayıt id'si:** `composite` — desen: `{fee_plan_key}_{student_key}` — (domain/fee_plan_assignment.rs:34-38)

### `meal_attendance`

`SCHEMAFULL` — `migration_sql.rs:834`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `menu` | `record<menu>` | **hayır** | `—` | **evet** | — | migration_sql.rs:835 |
| `student` | `record<user>` | **hayır** | `—` | **evet** | — | migration_sql.rs:836 |
| `status` | `string` | **hayır** | `—` | — | — | migration_sql.rs:837 |
| `marked_by` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:838 |
| `marked_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:839 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `meal_attendance_menu_student` | `menu, student` | **UNIQUE** | migration_sql.rs:840 |

**Kayıt id'si:** `composite` — desen: `{menu_key}_{student_key}` — (domain/meal_attendance.rs:37-40)

### `meal_booking`

`SCHEMAFULL` — `migration_sql.rs:818`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `menu` | `record<menu>` | **hayır** | `—` | **evet** | — | migration_sql.rs:819 |
| `student` | `record<user>` | **hayır** | `—` | **evet** | — | migration_sql.rs:820 |
| `booked_by` | `record<user>` | **hayır** | `—` | **evet** | — | migration_sql.rs:821 |
| `status` | `string` | **hayır** | `'booked'` | — | — | migration_sql.rs:822 |
| `attempt` | `int` | **hayır** | `1` | — | — | migration_sql.rs:827 |
| `price_minor` | `option<int>` | evet | `—` | — | — | migration_sql.rs:828 |
| `cancelled_at` | `option<int>` | evet | `—` | — | — | migration_sql.rs:829 |
| `created_at` | `int` | **hayır** | `—` | **evet** | — | migration_sql.rs:830 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `meal_booking_menu` | `menu` | — | migration_sql.rs:831 |
| `meal_booking_student` | `student` | — | migration_sql.rs:832 |

**Kayıt id'si:** `composite` — desen: `{menu_key}_{student_key}  ->  {date}_{slot}_{student_ulid}` — (domain/meal_booking.rs:57-60)

### `menu_dish`

`SCHEMAFULL` — `migration_sql.rs:796`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `menu` | `record<menu>` | **hayır** | `—` | **evet** | — | migration_sql.rs:797 |
| `name` | `string` | **hayır** | `—` | — | — | migration_sql.rs:798 |
| `description` | `option<string>` | evet | `—` | — | — | migration_sql.rs:799 |
| `price_minor` | `int` | **hayır** | `—` | — | — | migration_sql.rs:801 |
| `tags` | `array<string>` | **hayır** | `[]` | — | — | migration_sql.rs:802 |
| `tags[*]` | `string` | **hayır** | `—` | — | — | migration_sql.rs:803 |
| `created_at` | `int` | **hayır** | `—` | **evet** | — | migration_sql.rs:804 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `menu_dish_menu` | `menu` | — | migration_sql.rs:805 |

**Kayıt id'si:** `ulid_monotonic_local` — (domain/menu_dish.rs:38-44)

> file-local LazyLock<Mutex<Generator>>; semantics identical to next_ulid

### `note_file`

`SCHEMAFULL` — `migration_sql.rs:179`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `note` | `record<note>` | **hayır** | `—` | — | — | migration_sql.rs:180 |
| `name` | `string` | **hayır** | `—` | — | — | migration_sql.rs:181 |
| `content_type` | `string` | **hayır** | `—` | — | — | migration_sql.rs:182 |
| `size` | `int` | **hayır** | `—` | — | — | migration_sql.rs:183 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `note_file_note` | `note` | — | migration_sql.rs:184 |

**Kayıt id'si:** `ulid_monotonic` — (domain/note_file.rs:24)

> domain::monotonic_id::next_ulid() - ms-monotonic ULID, 26 chars Crockford base32

### `solution`

`SCHEMAFULL` — `migration_sql.rs:628`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `question` | `record<pool_question>` | **hayır** | `—` | — | — | migration_sql.rs:629 |
| `author` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:630 |
| `body` | `string` | **hayır** | `—` | — | — | migration_sql.rs:631 |
| `offered_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:632 |
| `image_file` | `option<string>` | evet | `—` | — | — | migration_sql.rs:633 |
| `image_content_type` | `option<string>` | evet | `—` | — | — | migration_sql.rs:634 |
| `image_size` | `option<int>` | evet | `—` | — | — | migration_sql.rs:635 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `solution_question` | `question` | — | migration_sql.rs:636 |

**Kayıt id'si:** `ulid_monotonic` — (domain/solution.rs:31)

> domain::monotonic_id::next_ulid() - ms-monotonic ULID, 26 chars Crockford base32

### `subject`

`SCHEMAFULL` — `migration_sql.rs:332`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `course` | `record<course>` | **hayır** | `—` | — | — | migration_sql.rs:333 |
| `name` | `string` | **hayır** | `—` | — | — | migration_sql.rs:334 |
| `description` | `string` | **hayır** | `—` | — | — | migration_sql.rs:335 |
| `exam_question_count` | `option<int>` | evet | `—` | — | — | migration_sql.rs:339 |
| `homework_count` | `option<int>` | evet | `—` | — | — | migration_sql.rs:340 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `subject_course` | `course` | — | migration_sql.rs:341 |

**Kayıt id'si:** `ulid_monotonic` — (domain/subject.rs:18)

> domain::monotonic_id::next_ulid() - ms-monotonic ULID, 26 chars Crockford base32

### `attendance`

`SCHEMAFULL` — `migration_sql.rs:290`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `event` | `record<event>` | **hayır** | `—` | — | — | migration_sql.rs:291 |
| `user` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:292 |
| `status` | `string` | **hayır** | `—` | — | — | migration_sql.rs:293 |
| `marked_by` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:294 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `attendance_event_user` | `event, user` | **UNIQUE** | migration_sql.rs:295 |
| `attendance_user` | `user` | — | migration_sql.rs:296 |

**Kayıt id'si:** `composite` — desen: `{event_key}_{user_key}` — (domain/attendance.rs:17-20)

### `bank_question`

`SCHEMAFULL` — `migration_sql.rs:536`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `owner` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:537 |
| `subject` | `option<record<subject>>` | evet | `—` | — | evet | migration_sql.rs:541 |
| `text` | `string` | **hayır** | `—` | — | — | migration_sql.rs:542 |
| `kind` | `string` | **hayır** | `—` | — | — | migration_sql.rs:543 |
| `points` | `int` | **hayır** | `—` | — | — | migration_sql.rs:544 |
| `choices` | `option<array<object>>` | evet | `—` | — | evet | migration_sql.rs:548 |
| `choices.*.id` | `string` | **hayır** | `—` | — | evet | migration_sql.rs:551 |
| `choices.*.text` | `string` | **hayır** | `—` | — | evet | migration_sql.rs:552 |
| `correct` | `option<string>` | evet | `—` | — | evet | migration_sql.rs:553 |
| `source_exam` | `option<record<exam>>` | evet | `—` | — | — | migration_sql.rs:554 |
| `visibility` | `string` | **hayır** | `'private'` | — | — | migration_sql.rs:558 |
| `created_at` | `int` | **hayır** | `—` | **evet** | — | migration_sql.rs:559 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `bank_question_owner` | `owner` | — | migration_sql.rs:560 |
| `bank_question_subject` | `subject` | — | migration_sql.rs:561 |

**Kayıt id'si:** `ulid_monotonic` — (domain/bank_question.rs:73)

> domain::monotonic_id::next_ulid() - ms-monotonic ULID, 26 chars Crockford base32

### `class_course`

`SCHEMAFULL` — `migration_sql.rs:385`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `class` | `record<class_group>` | **hayır** | `—` | — | — | migration_sql.rs:386 |
| `course` | `record<course>` | **hayır** | `—` | — | — | migration_sql.rs:387 |
| `attached_by` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:388 |
| `attached_at` | `option<int>` | evet | `—` | — | — | migration_sql.rs:391 |
| `source` | `option<record<class_blueprint>>` | evet | `—` | — | — | migration_sql.rs:401 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `class_course_class_course` | `class, course` | **UNIQUE** | migration_sql.rs:402 |
| `class_course_class` | `class` | — | migration_sql.rs:403 |
| `class_course_course` | `course` | — | migration_sql.rs:404 |

**Kayıt id'si:** `composite` — desen: `{class_key}_{course_key}` — (domain/class_course.rs:27 -> db/class_pump.rs:676)

### `course_note_file`

`SCHEMAFULL` — `migration_sql.rs:194`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `course_note` | `record<course_note>` | **hayır** | `—` | — | — | migration_sql.rs:195 |
| `name` | `string` | **hayır** | `—` | — | — | migration_sql.rs:196 |
| `content_type` | `string` | **hayır** | `—` | — | — | migration_sql.rs:197 |
| `size` | `int` | **hayır** | `—` | — | — | migration_sql.rs:198 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `course_note_file_note` | `course_note` | — | migration_sql.rs:199 |

**Kayıt id'si:** `ulid_monotonic` — (domain/course_note_file.rs:28)

> domain::monotonic_id::next_ulid() - ms-monotonic ULID, 26 chars Crockford base32

### `exam_attempt`

`SCHEMAFULL` — `migration_sql.rs:487`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `exam` | `record<exam>` | **hayır** | `—` | — | — | migration_sql.rs:488 |
| `user` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:489 |
| `seq` | `int` | **hayır** | `1` | — | — | migration_sql.rs:490 |
| `started_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:491 |
| `finished_at` | `option<int>` | evet | `—` | — | — | migration_sql.rs:492 |
| `left_at` | `option<int>` | evet | `—` | — | — | migration_sql.rs:493 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `exam_attempt_exam_user_seq` | `exam, user, seq` | **UNIQUE** | migration_sql.rs:494 |
| `exam_attempt_exam` | `exam` | — | migration_sql.rs:495 |

**Kayıt id'si:** `composite` — desen: `{exam_key}_{user_key}   (seq==1)   |   {exam_key}_{user_key}_{seq}   (seq>1)` — (domain/exam_attempt.rs:19 -> domain/key.rs:16)

> the bare seq==1 form is migration law - do not number the first sitting

### `exam_result`

`SCHEMAFULL` — `migration_sql.rs:604`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `exam` | `record<exam>` | **hayır** | `—` | — | — | migration_sql.rs:605 |
| `user` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:606 |
| `mark` | `int` | **hayır** | `—` | — | — | migration_sql.rs:607 |
| `graded_by` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:608 |
| `seq` | `int` | **hayır** | `1` | — | — | migration_sql.rs:611 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `exam_result_exam_user_seq` | `exam, user, seq` | **UNIQUE** | migration_sql.rs:613 |

**Kaldırılmış indeksler:** `exam_result_exam_user` (migration_sql.rs:612)

**Kayıt id'si:** `composite` — desen: `{exam_key}_{user_key} (seq==1) | {exam_key}_{user_key}_{seq}` — (domain/exam_result.rs:48 -> domain/key.rs:16)

### `homework`

`SCHEMAFULL` — `migration_sql.rs:677`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `course` | `record<course>` | **hayır** | `—` | **evet** | — | migration_sql.rs:678 |
| `subject` | `record<subject>` | **hayır** | `—` | — | — | migration_sql.rs:679 |
| `title` | `string` | **hayır** | `—` | — | — | migration_sql.rs:680 |
| `description` | `option<string>` | evet | `—` | — | — | migration_sql.rs:681 |
| `due_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:682 |
| `assigned` | `option<array<record<user>>>` | evet | `—` | — | — | migration_sql.rs:683 |
| `assigned[*]` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:684 |
| `created_by` | `record<user>` | **hayır** | `—` | **evet** | — | migration_sql.rs:685 |
| `created_at` | `int` | **hayır** | `—` | **evet** | — | migration_sql.rs:686 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `homework_course` | `course` | — | migration_sql.rs:687 |

**Kayıt id'si:** `ulid_monotonic` — (domain/homework.rs:34)

> domain::monotonic_id::next_ulid() - ms-monotonic ULID, 26 chars Crockford base32

### `registration`

`SCHEMAFULL` — `migration_sql.rs:298`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `event` | `record<event>` | **hayır** | `—` | — | — | migration_sql.rs:299 |
| `user` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:300 |
| `registered_by` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:301 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `registration_event_user` | `event, user` | **UNIQUE** | migration_sql.rs:302 |
| `registration_event` | `event` | — | migration_sql.rs:303 |

**Kayıt id'si:** `composite` — desen: `{event_key}_{user_key}` — (domain/registration.rs:16-19)

### `session_attendance`

`SCHEMAFULL` — `migration_sql.rs:439`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `session` | `record<course_session>` | **hayır** | `—` | — | — | migration_sql.rs:440 |
| `course` | `record<course>` | **hayır** | `—` | — | — | migration_sql.rs:441 |
| `user` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:442 |
| `status` | `string` | **hayır** | `—` | — | — | migration_sql.rs:443 |
| `marked_by` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:444 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `session_attendance_session_user` | `session, user` | **UNIQUE** | migration_sql.rs:445 |
| `session_attendance_session` | `session` | — | migration_sql.rs:446 |
| `session_attendance_user` | `user` | — | migration_sql.rs:447 |
| `session_attendance_course` | `course` | — | migration_sql.rs:448 |

**Kayıt id'si:** `composite` — desen: `{course_session_key}_{user_key}` — (domain/session_attendance.rs:18-21)

### `bank_question_image`

`SCHEMAFULL` — `migration_sql.rs:563`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `bank_question` | `record<bank_question>` | **hayır** | `—` | — | — | migration_sql.rs:564 |
| `slot` | `option<string>` | evet | `—` | — | evet | migration_sql.rs:566 |
| `file` | `string` | **hayır** | `—` | — | — | migration_sql.rs:567 |
| `content_type` | `string` | **hayır** | `—` | — | — | migration_sql.rs:568 |
| `size` | `int` | **hayır** | `—` | — | — | migration_sql.rs:569 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `bank_question_image_question` | `bank_question` | — | migration_sql.rs:570 |

**Kayıt id'si:** `composite` — desen: `{bank_question_key}_q  |  {bank_question_key}_{choice_id}` — (domain/bank_question_image.rs:30-33 -> domain/key.rs:30)

### `exam_question`

`SCHEMAFULL` — `migration_sql.rs:497`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `exam` | `record<exam>` | **hayır** | `—` | — | — | migration_sql.rs:498 |
| `text` | `string` | **hayır** | `—` | — | — | migration_sql.rs:499 |
| `kind` | `string` | **hayır** | `—` | — | — | migration_sql.rs:500 |
| `points` | `int` | **hayır** | `—` | — | — | migration_sql.rs:501 |
| `choices` | `option<array<object>>` | evet | `—` | — | evet | migration_sql.rs:505 |
| `choices.*.id` | `string` | **hayır** | `—` | — | evet | migration_sql.rs:508 |
| `choices.*.text` | `string` | **hayır** | `—` | — | evet | migration_sql.rs:509 |
| `correct` | `option<string>` | evet | `—` | — | evet | migration_sql.rs:510 |
| `subject` | `record<subject>` | **hayır** | `—` | — | — | migration_sql.rs:511 |
| `from_bank` | `option<record<bank_question>>` | evet | `—` | — | evet | migration_sql.rs:519 |
| `banked_as` | `option<record<bank_question>>` | evet | `—` | — | evet | migration_sql.rs:520 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `exam_question_exam` | `exam` | — | migration_sql.rs:522 |
| `exam_question_subject` | `subject` | — | migration_sql.rs:523 |

**Kaldırılmış alanlar (ASLA yazmayın):** `source_bank` (migration_sql.rs:521)

**Kayıt id'si:** `ulid_monotonic` — (domain/exam_question.rs:25)

> domain::monotonic_id::next_ulid() - ms-monotonic ULID, 26 chars Crockford base32

### `homework_result`

`SCHEMAFULL` — `migration_sql.rs:726`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `homework` | `record<homework>` | **hayır** | `—` | **evet** | — | migration_sql.rs:727 |
| `user` | `record<user>` | **hayır** | `—` | **evet** | — | migration_sql.rs:728 |
| `status` | `string` | **hayır** | `—` | — | — | migration_sql.rs:729 |
| `mark` | `option<int>` | evet | `—` | — | — | migration_sql.rs:730 |
| `graded_by` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:731 |
| `created_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:732 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `homework_result_homework` | `homework` | — | migration_sql.rs:733 |

**Kayıt id'si:** `composite` — desen: `{homework_key}_{user_key}` — (domain/homework_result.rs:34-39)

> shares its key with homework_submission - that is how graded_by_result is addressed without a search

### `rag_output`

`SCHEMAFULL` — `migration_sql.rs:206`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `course_note` | `record<course_note>` | **hayır** | `—` | — | — | migration_sql.rs:207 |
| `course` | `record<course>` | **hayır** | `—` | — | — | migration_sql.rs:208 |
| `sources` | `array<record<course_note_file>>` | **hayır** | `—` | — | — | migration_sql.rs:209 |
| `payload` | `object` **FLEXIBLE** | **hayır** | `—` | — | — | migration_sql.rs:210 |
| `generated_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:211 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `rag_output_note` | `course_note` | — | migration_sql.rs:212 |
| `rag_output_source` | `sources` | — | migration_sql.rs:217 |

**Kaldırılmış indeksler:** `rag_output_course` (migration_sql.rs:214)

**Kayıt id'si:** `ulid_monotonic` — (domain/rag_output.rs:34)

> domain::monotonic_id::next_ulid() - ms-monotonic ULID, 26 chars Crockford base32

### `answer_image`

`SCHEMAFULL` — `migration_sql.rs:591`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `exam` | `record<exam>` | **hayır** | `—` | — | — | migration_sql.rs:592 |
| `question` | `record<exam_question>` | **hayır** | `—` | — | — | migration_sql.rs:593 |
| `user` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:594 |
| `file` | `string` | **hayır** | `—` | — | — | migration_sql.rs:595 |
| `content_type` | `string` | **hayır** | `—` | — | — | migration_sql.rs:596 |
| `size` | `int` | **hayır** | `—` | — | — | migration_sql.rs:597 |
| `seq` | `int` | **hayır** | `1` | — | — | migration_sql.rs:600 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `answer_image_exam` | `exam` | — | migration_sql.rs:601 |
| `answer_image_user` | `user` | — | migration_sql.rs:602 |

**Kayıt id'si:** `composite` — desen: `{exam_question_key}_{user_key} (seq==1) | {exam_question_key}_{user_key}_{seq}` — (domain/answer_image.rs:34 -> domain/key.rs:16)

### `exam_answer`

`SCHEMAFULL` — `migration_sql.rs:572`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `exam` | `record<exam>` | **hayır** | `—` | — | — | migration_sql.rs:573 |
| `question` | `record<exam_question>` | **hayır** | `—` | — | — | migration_sql.rs:574 |
| `user` | `record<user>` | **hayır** | `—` | — | — | migration_sql.rs:575 |
| `selected` | `option<string>` | evet | `—` | — | evet | migration_sql.rs:577 |
| `text` | `option<string>` | evet | `—` | — | — | migration_sql.rs:578 |
| `updated_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:579 |
| `seq` | `int` | **hayır** | `1` | — | — | migration_sql.rs:583 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `exam_answer_question_user_seq` | `question, user, seq` | **UNIQUE** | migration_sql.rs:587 |
| `exam_answer_exam_user` | `exam, user` | — | migration_sql.rs:588 |
| `exam_answer_exam` | `exam` | — | migration_sql.rs:589 |

**Kaldırılmış indeksler:** `exam_answer_question_user` (migration_sql.rs:586)

**Kayıt id'si:** `composite` — desen: `{exam_question_key}_{user_key} (seq==1) | {exam_question_key}_{user_key}_{seq}` — (domain/exam_answer.rs:22 -> domain/key.rs:16)

### `homework_submission`

`SCHEMAFULL` — `migration_sql.rs:689`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `homework` | `record<homework>` | **hayır** | `—` | **evet** | — | migration_sql.rs:690 |
| `user` | `record<user>` | **hayır** | `—` | **evet** | — | migration_sql.rs:691 |
| `text` | `option<string>` | evet | `—` | — | — | migration_sql.rs:692 |
| `submitted_at` | `int` | **hayır** | `—` | **evet** | — | migration_sql.rs:693 |
| `updated_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:694 |
| `file_count` | `option<int>` | evet | `—` | — | — | migration_sql.rs:695 |
| `counted_on_time` | `option<bool>` | evet | `—` | — | — | migration_sql.rs:707 |
| `graded_by_result` | `option<record<homework_result>>` | evet | `—` | — | — | migration_sql.rs:714 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `homework_submission_homework` | `homework` | — | migration_sql.rs:715 |

**Kayıt id'si:** `composite` — desen: `{homework_key}_{user_key}` — (domain/homework_submission.rs:35-38)

### `question_image`

`SCHEMAFULL` — `migration_sql.rs:525`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `exam` | `record<exam>` | **hayır** | `—` | — | — | migration_sql.rs:526 |
| `question` | `record<exam_question>` | **hayır** | `—` | — | — | migration_sql.rs:527 |
| `slot` | `option<string>` | evet | `—` | — | evet | migration_sql.rs:529 |
| `file` | `string` | **hayır** | `—` | — | — | migration_sql.rs:530 |
| `content_type` | `string` | **hayır** | `—` | — | — | migration_sql.rs:531 |
| `size` | `int` | **hayır** | `—` | — | — | migration_sql.rs:532 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `question_image_exam` | `exam` | — | migration_sql.rs:533 |
| `question_image_question` | `question` | — | migration_sql.rs:534 |

**Kayıt id'si:** `composite` — desen: `{exam_question_key}_q  (question illustration)  |  {exam_question_key}_{choice_id}` — (domain/question_image.rs:29-32 -> domain/key.rs:30)

### `homework_file`

`SCHEMAFULL` — `migration_sql.rs:717`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `submission` | `record<homework_submission>` | **hayır** | `—` | **evet** | — | migration_sql.rs:718 |
| `name` | `string` | **hayır** | `—` | — | — | migration_sql.rs:719 |
| `content_type` | `string` | **hayır** | `—` | — | — | migration_sql.rs:720 |
| `size` | `int` | **hayır** | `—` | — | — | migration_sql.rs:721 |
| `file` | `string` | **hayır** | `—` | **evet** | — | migration_sql.rs:722 |
| `created_at` | `int` | **hayır** | `—` | **evet** | — | migration_sql.rs:723 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `homework_file_submission` | `submission` | — | migration_sql.rs:724 |

**Kayıt id'si:** `ulid_monotonic` — (domain/homework_file.rs:30)

> domain::monotonic_id::next_ulid() - ms-monotonic ULID, 26 chars Crockford base32

### 1.2 Kontrol (control) veritabanı tabloları

Bunlar okul veritabanında **değil**, dağıtım başına tek olan kontrol veritabanındadır (`migration_sql.rs:1471-1512`). 250 öğrencilik tohum verisi için yalnızca `school` satırı ilgilidir.

### `builder`

`SCHEMAFULL` — `migration_sql.rs:1493`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `username` | `string` | **hayır** | `—` | — | — | migration_sql.rs:1494 |
| `password_hash` | `string` | **hayır** | `—` | — | — | migration_sql.rs:1495 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `builder_username` | `username` | **UNIQUE** | migration_sql.rs:1496 |

### `builder_session`

`SCHEMAFULL` — `migration_sql.rs:1498`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `builder` | `record<builder>` | **hayır** | `—` | — | — | migration_sql.rs:1499 |
| `token` | `string` | **hayır** | `—` | — | — | migration_sql.rs:1500 |
| `created_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:1501 |
| `expires_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:1502 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `builder_session_token` | `token` | **UNIQUE** | migration_sql.rs:1503 |
| `builder_session_expires` | `expires_at` | — | migration_sql.rs:1504 |

### `rate_limit`

`SCHEMAFULL` — `migration_sql.rs:1507`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `hits` | `int` | **hayır** | `0` | — | — | migration_sql.rs:1508 |
| `window_start` | `int` | **hayır** | `—` | — | — | migration_sql.rs:1509 |

**Kayıt id'si:** `deterministic_opaque` — (migration_sql.rs:268)

> one row per tier+client+window, built in crate::rate_limit. NOT seed-relevant.

### `school`

`SCHEMAFULL` — `migration_sql.rs:1475`

| alan | tip | opsiyonel | DEFAULT | RO | OW | kaynak |
|---|---|---|---|---|---|---|
| `slug` | `string` | **hayır** | `—` | — | — | migration_sql.rs:1476 |
| `name` | `string` | **hayır** | `—` | — | — | migration_sql.rs:1477 |
| `status` | `string` | **hayır** | `—` | — | — | migration_sql.rs:1478 |
| `created_at` | `int` | **hayır** | `—` | — | — | migration_sql.rs:1479 |
| `modules` | `array<string>` | **hayır** | `[]` | — | — | migration_sql.rs:1483 |

**İndeksler**

| ad | alanlar | UNIQUE | kaynak |
|---|---|---|---|
| `school_slug` | `slug` | **UNIQUE** | migration_sql.rs:1491 |

---

## 2. ID üretim kuralları (KRİTİK)

### 2.1 Üç üretim yöntemi

| yöntem | kod | anlamı |
|---|---|---|
| **monotonik ULID** | `domain::monotonic_id::next_ulid()` — `domain/monotonic_id.rs:16-32` | Süreç genelinde tek bir `ulid::Generator`. Aynı milisaniye içinde bile **kesin artan** id üretir (rastgele biti yeniden çekmek yerine artırır). Tabloların büyük çoğunluğu bunu kullanır. |
| **rastgele ULID** | `ulid::Ulid::new()` | Düşük 80 bit rastgele. Yalnızca `session`, `exam_question.choices[*].id`, `builder`, `builder_session`. |
| **dosya-yerel monotonik ULID** | dosyaya özel `LazyLock<Mutex<Generator>>` | `chatbot_message`, `appointment`, `menu_dish`, `meal_ledger` (serbest kredi). Semantiği `next_ulid` ile aynıdır. |

**Sıralama gerektiren tablolar:** `monotonic_id.rs` başlığı gerekçeyi açıkça yazar — listelemeler eşitliği `id` ile bozar veya doğrudan 'en yeni önce' anlamında kullanır. `class_member.rs:44` ve `class_course.rs:55` bunun *başarısız* olduğu iki yeri belgeler (bu iki tabloda id bir çift olduğu için `added_at` / `attached_at` sütunları eklenmiştir).

### 2.2 Kompozit ve doğal anahtarlar

`domain/key.rs` iki yardımcıyı tanımlar:

```rust
// domain/key.rs:16-22  — oturum (sitting) anahtarı
pub fn sitting(scope: &str, user: &str, seq: i64) -> String {
    if seq == 1 {
        format!("{scope}_{user}")        // İLK OTURUM ÇIPLAKTIR — _1 EKLENMEZ
    } else {
        format!("{scope}_{user}_{seq}")
    }
}

// domain/key.rs:31  — görsel yuvası anahtarı
pub fn slot(owner: &str, slot: Option<&str>) -> String {
    format!("{owner}_{}", slot.unwrap_or("q"))
}

// db/class_pump.rs:676-678  — sınıf bağı anahtarı
pub(crate) fn link_id(table: &str, class: &ClassGroupId, other: &str) -> RecordId {
    RecordId::new(table, format!("{}_{}", class.key(), other))
}
```

> `sitting()`'in `seq == 1` çıplak biçimi **göç yasasıdır** (`domain/key.rs:9-15`): değiştirilirse tarih öncesi her satır erişilemez hale gelir.

**Tam liste:**

| tablo | id deseni | kaynak |
|---|---|---|
| `kind_ref` | doğal anahtar `{exam_kind_name}` | domain/exam_result.rs:25-27 / db/cap.rs:681 |
| `migration_mark` | **SABİT** `migration_mark:board_roster , migration_mark:profile_counters` | migration_sql.rs:1354,1432 |
| `rate_limit` | deterministic_opaque | migration_sql.rs:268 |
| `settings` | **SABİT** `settings:school` | domain/settings.rs:239-241 (SETTINGS_TABLE constant.rs:893, SETTINGS_KEY constant.rs:805) |
| `slot_ref` | doğal anahtar `{meal_slot_name}` | domain/menu.rs:30-32 / db/menu.rs:126 |
| `term` | monotonik ULID | domain/term.rs:26 |
| `user` | monotonik ULID | domain/user.rs:32 |
| `appointment_slot` | monotonik ULID | domain/appointment_slot.rs:41-44 |
| `badge_award` | `{user_key}_{badge_id}` | db/badge.rs:94-96 |
| `board` | monotonik ULID | domain/board.rs:31 |
| `chatbot_thread` | monotonik ULID | domain/chatbot_thread.rs:25 |
| `class_group` | monotonik ULID | domain/class_group.rs:31 |
| `course` | monotonik ULID | domain/course.rs:18 |
| `dietary_profile` | doğal anahtar `{student_key}` | domain/dietary_profile.rs:31 |
| `fee_plan` | monotonik ULID | domain/fee_plan.rs:32 |
| `meal_ledger` | `{booking_key}_c{attempt} (charge) | {booking_key}_r{attempt} (reversal) | {student_key}_k_{request_key} (idempotent credit) | <local ULID> (free credit)` | domain/meal_ledger.rs:87-137 |
| `menu` | doğal anahtar `{date}_{slot}   e.g.  2026-09-01_lunch` | domain/menu.rs:44-49 |
| `message` | monotonik ULID | domain/message.rs:108 |
| `note` | monotonik ULID | domain/note.rs:17 |
| `parent_link` | `{parent_key}_{student_key}` | domain/parent_link.rs:15-18 |
| `payment_ledger` | `{assignment_key}_c{n} (charge, n 1-based) | {line_key}_r (reversal) | {line_key}_k_{request_key} (payment) | {line_key}_kr_{request_key} (refund) | <monotonic ULID> (free)` | domain/payment_ledger.rs:66-116 |
| `pomodoro_session` | `open_{user_key}  (WHILE OPEN)  |  <monotonic ULID>  (once closed)` | domain/pomodoro.rs:17-20 (closed) / domain/pomodoro.rs:29-32 (open) |
| `pool_question` | monotonik ULID | domain/pool_question.rs:36 |
| `session` | **rastgele** ULID | domain/session.rs:14 |
| `work_entry` | `open_{user_key}  (WHILE OPEN)  |  <monotonic ULID>  (once closed)` | domain/work_entry.rs:28 (closed) / domain/work_entry.rs:37-40 (open) |
| `appointment` | dosya-yerel monotonik ULID | domain/appointment.rs:67-72 |
| `board_stroke` | monotonik ULID | domain/board_stroke.rs:69 |
| `chatbot_message` | dosya-yerel monotonik ULID | domain/chatbot_message.rs:47 |
| `class_blueprint` | doğal anahtar `{grade}` | domain/class_blueprint.rs:41 |
| `class_member` | `{class_key}_{user_key}` | domain/class_member.rs:24 -> db/class_pump.rs:676 |
| `course_note` | monotonik ULID | domain/course_note.rs:19 |
| `course_session` | monotonik ULID | domain/course_session.rs:20 |
| `enrollment` | `{course_key}_{user_key}` | domain/enrollment.rs:17-20 |
| `event` | monotonik ULID | domain/event.rs:23 |
| `exam` | monotonik ULID | domain/exam.rs:35 |
| `fee_plan_assignment` | `{fee_plan_key}_{student_key}` | domain/fee_plan_assignment.rs:34-38 |
| `meal_attendance` | `{menu_key}_{student_key}` | domain/meal_attendance.rs:37-40 |
| `meal_booking` | `{menu_key}_{student_key}  ->  {date}_{slot}_{student_ulid}` | domain/meal_booking.rs:57-60 |
| `menu_dish` | dosya-yerel monotonik ULID | domain/menu_dish.rs:38-44 |
| `note_file` | monotonik ULID | domain/note_file.rs:24 |
| `solution` | monotonik ULID | domain/solution.rs:31 |
| `subject` | monotonik ULID | domain/subject.rs:18 |
| `attendance` | `{event_key}_{user_key}` | domain/attendance.rs:17-20 |
| `bank_question` | monotonik ULID | domain/bank_question.rs:73 |
| `class_course` | `{class_key}_{course_key}` | domain/class_course.rs:27 -> db/class_pump.rs:676 |
| `course_note_file` | monotonik ULID | domain/course_note_file.rs:28 |
| `exam_attempt` | `{exam_key}_{user_key}   (seq==1)   |   {exam_key}_{user_key}_{seq}   (seq>1)` | domain/exam_attempt.rs:19 -> domain/key.rs:16 |
| `exam_result` | `{exam_key}_{user_key} (seq==1) | {exam_key}_{user_key}_{seq}` | domain/exam_result.rs:48 -> domain/key.rs:16 |
| `homework` | monotonik ULID | domain/homework.rs:34 |
| `registration` | `{event_key}_{user_key}` | domain/registration.rs:16-19 |
| `session_attendance` | `{course_session_key}_{user_key}` | domain/session_attendance.rs:18-21 |
| `bank_question_image` | `{bank_question_key}_q  |  {bank_question_key}_{choice_id}` | domain/bank_question_image.rs:30-33 -> domain/key.rs:30 |
| `exam_question` | monotonik ULID | domain/exam_question.rs:25 |
| `homework_result` | `{homework_key}_{user_key}` | domain/homework_result.rs:34-39 |
| `rag_output` | monotonik ULID | domain/rag_output.rs:34 |
| `answer_image` | `{exam_question_key}_{user_key} (seq==1) | {exam_question_key}_{user_key}_{seq}` | domain/answer_image.rs:34 -> domain/key.rs:16 |
| `exam_answer` | `{exam_question_key}_{user_key} (seq==1) | {exam_question_key}_{user_key}_{seq}` | domain/exam_answer.rs:22 -> domain/key.rs:16 |
| `homework_submission` | `{homework_key}_{user_key}` | domain/homework_submission.rs:35-38 |
| `question_image` | `{exam_question_key}_q  (question illustration)  |  {exam_question_key}_{choice_id}` | domain/question_image.rs:29-32 -> domain/key.rs:30 |
| `homework_file` | monotonik ULID | domain/homework_file.rs:30 |
| `exam_question.choices[*].id` | **rastgele** ULID | domain/exam_question.rs:122 |
| `appointment_slot.series` | monotonik ULID | domain/appointment_slot.rs:70 |
| `_control_school` | doğal anahtar `{slug}` | tenant.rs:151-153 |
| `_control_builder` | **rastgele** ULID | domain/builder.rs:27 |
| `_control_builder_session` | **rastgele** ULID | db/builder.rs:44 |
| `_user_ai_principal` | **SABİT** `user:ai_service` | constant.rs:762 |

**Sabit id'ler:**

- `settings:school` — okul ayarları tekil satırı (`domain/settings.rs:239-241`; `SETTINGS_KEY = "school"`, `constant.rs:805`). **Satır yoksa kod gömülü varsayılanları okur** (`db/settings.rs:9-12`), yani tohumlamak zorunlu değildir.
- `migration_mark:board_roster`, `migration_mark:profile_counters` — `migrate()` yazar (`migration_sql.rs:1354, 1432`). **Tohumlamayın.**
- `user:ai_service` — `AI_PRINCIPAL_KEY` (`constant.rs:762`). Satır **hiç yazılmaz**; rezerve bir anahtardır.
- `work_entry:open_<user ULID>` ve `pomodoro_session:open_<user ULID>` — **devam eden** mesai/pomodoro kaydının sabit id'si (`domain/work_entry.rs:37-40`, `domain/pomodoro.rs:29-32`). Kapandığında satır taze bir ULID id'sine taşınır.
- `kind_ref:<sınav türü adı>`, `slot_ref:<öğün adı>` — id, adın **kendisidir**.
- `class_blueprint:<sınıf düzeyi>` — id, grade etiketidir.
- `school:<slug>` (kontrol db) — id, slug'ın kendisidir (`tenant.rs:151-153`).

### 2.3 SurrealQL'de id sözdizimi — KESİN BİÇİM

Üretilen her anahtar bir ULID'dir (26 karakter, Crockford base32) veya bir ULID ile başlar; yani **rakamla başlar**. Bu, SurrealQL'de çıplak bir tanımlayıcı olarak güvenli değildir.

```sql
-- ÖNERİLEN (köşeli açı parantezleri, U+27E8 / U+27E9):
CREATE user:⟨01JGQ8Z0000000000000000⟩ CONTENT { ... };

-- EŞDEĞER (ters tırnak):
CREATE user:`01JGQ8Z0000000000000000` CONTENT { ... };

-- KURŞUN GEÇİRMEZ (fonksiyon çağrısı — anahtar hesaplanıyorsa zorunlu):
CREATE type::record('user', '01JGQ8Z0000000000000000') CONTENT { ... };

-- ASLA:
-- CREATE user:01JGQ8Z0000000000000000 ...   <-- yapmayın
```

**Kodda nasıl üretiliyor (kanıt):**
- The codebase NEVER spells a ULID id into SQL text: ids are bound as surrealdb::types::RecordId parameters, e.g. db/enrollment.rs:96 'CREATE $id CONTENT $row'.
- type::record(...) is used whenever the key is computed inside a query: db/badge.rs:122, db/class_pump.rs:436, db/course.rs:312, migration_sql.rs:996/1167/1265/1269.
- Literal table:key appears ONLY for known-safe keys: migration_mark:board_roster (migration_sql.rs:1354), settings:school (db/chatbot_thread.rs:123), and in unit tests with hand-written keys like user:t.
- Backticks are used in this codebase for DATABASE NAMES only (tenant.rs:109-111), never for record ids - the comment there explains that an unquoted 2024school parses as a duration and 12345 as a number in SurrealDB 3.2.

> *(doğrulanmadı)* Whether SurrealDB 3.2 happens to accept a bare digit-leading alphanumeric record id was not executed. Always wrap.

### 2.4 ULID'den zaman türetilebilir mi?

Evet — ULID'in ilk 10 karakteri, milisaniye cinsinden üretim zamanıdır. **Kod bunu hiçbir yerde türetmez**, ancak birden çok listeleme `ORDER BY id` yapar ve bunu 'en yeni önce' olarak belgeler (`domain/monotonic_id.rs` başlığı, `class_member.rs:44`, `class_course.rs:55`).

> **Tohum kuralı:** Her satırın ULID'ini o satırın kendi `created_at` / `*_at` milisaniye değerinden üretin. Aksi halde arayüzdeki her 'en yeni önce' listesi karışır.

---

## 3. Enum ve kısıtlı string değerleri

> **Çok önemli:** Şemada **tek bir `ASSERT` yoktur**. Veritabanı hiçbir enum'u doğrulamaz — geçersiz bir string sorunsuz kaydedilir. Ancak Rust newtype'ı geri okuyamayınca API 500 döner. Yani aşağıdaki listeler **zorunludur**, veritabanı zorlamasa bile.

### 3.1 Koda gömülü enum'lar (okul ayarlarından bağımsız)

| alan | geçerli değerler | DEFAULT | kaynak |
|---|---|---|---|
| `user.role` | `parent`, `student`, `teacher`, `manager`, `admin` | — | constant.rs:752 / domain/role.rs:29 |
| `user.theme` | `light`, `dark` | — | constant.rs:764 / domain/preferences.rs:18 |
| `user.language` | `tr`, `en` | — | constant.rs:766 / domain/preferences.rs:48 |
| `user.palette_color` | regex ^#[0-9a-fA-F]{6}$ - stored lowercased, exactly 7 chars | — | constant.rs:770-781 |
| `message.sender_folder` | `sent`, `archive`, `trash` | `sent` | constant.rs:784 |
| `message.recipient_folder` | `inbox`, `archive`, `trash` | `inbox` | constant.rs:786 |
| `message.sender_origin / message.recipient_origin` | `sent`, `inbox`, `archive`, `trash`, `NONE` | — | migration_sql.rs:132-133 |
| `chatbot_message.role` | `user`, `assistant` | — | domain/chatbot_message.rs:75-87 |
| `chatbot_message.status` | `pending`, `complete`, `failed` | — | domain/chatbot_message.rs:94-106 |
| `appointment.status` | `pending`, `approved`, `rejected`, `cancelled` | `pending` | domain/appointment.rs:95-110 |
| `meal_booking.status` | `booked`, `cancelled` | `booked` | constant.rs:297 / domain/meal_booking.rs:98-110 |
| `meal_attendance.status` | `served`, `missed` | — | constant.rs:303 |
| `meal_ledger.kind` | `charge`, `credit`, `reversal` | — | constant.rs:309 |
| `payment_ledger.kind` | `charge`, `credit`, `reversal`, `refund` | — | constant.rs:318 |
| `course.kind` | `course`, `study`, `club` | `course` | constant.rs:278 |
| `exam.mode` | `sync`, `async`, `open`, `NONE` | — | constant.rs:285 |
| `exam_question.kind / bank_question.kind` | `choice`, `text` | — | constant.rs:486 |
| `homework_result.status` | `done`, `incomplete`, `missing` | — | constant.rs:292 |
| `bank_question.visibility` | `private`, `school` | `private` | constant.rs:798-799 |
| `pool_question.status` | `pending`, `approved` | `pending` | constant.rs:792-794 |
| `board_stroke.kind` | `stroke`, `clear` | — | constant.rs:398 |
| `event.audience.kind` | `school`, `role`, `course`, `class`, `registration` | — | domain/event.rs:77-102 |
| `question_image.content_type / bank_question_image.content_type` | `image/png`, `image/jpeg`, `image/webp`, `image/gif` | — | constant.rs:96-97 |
| `badge_award.badge` | `homework_submitted_1`, `homework_submitted_10`, `homework_submitted_50`, `homework_on_time_10`, `homework_on_time_25`, `exam_sat_1`, `exam_sat_10`, `exam_sat_25`, `pomodoro_finished_10`, `pomodoro_finished_50`, `pomodoro_finished_200`, `pomodoro_focus_ms_36000000`, `pomodoro_focus_ms_180000000`, `marks_given_10`, `marks_given_50`, `marks_given_250`, `lessons_held_10`, `lessons_held_50`, `lessons_held_200`, `pool_approved_5`, `pool_approved_25`, `pool_approved_100`, `pool_published_1`, `pool_published_10`, `pool_published_50`, `lessons_attended_10`, `lessons_attended_50`, `lessons_attended_200`, `high_mark_1`, `high_mark_10`, `high_mark_25`, `study_streak_3`, `study_streak_7`, `study_streak_30` | — | constant.rs:1095-1142 (BADGES, 34 entries) |
| `school.status  (CONTROL DB)` | `active`, `suspended` | — | tenant.rs:117-131 |
| `school.modules[*]  (CONTROL DB)` | `chatbot`, `notes`, `messages`, `events`, `appointments`, `courses`, `course_notes`, `classes`, `sessions`, `exams`, `marks`, `meals`, `payments`, `work`, `pomodoro`, `questions`, `bank_questions`, `attendance`, `subjects`, `homework`, `boards` | — | module.rs:26-52 + module.rs:67-115 (Module::ALL, 21) |
| `Package (API only, never stored)` | `academics`, `communication`, `operations`, `ai` | — | module.rs:57-64 / module.rs:203-217 |

- **`user.role`** — Role::Ai ('ai') exists but is NOT assignable and is never stored on a user row (constant.rs:747-751). DEFAULT on the column is 'student'.
- **`message.sender_folder`** — DEFAULT 'sent' (the sender's home folder)
- **`message.recipient_folder`** — DEFAULT 'inbox'
- **`message.sender_origin / message.recipient_origin`** — where the copy sat before it was filed; NONE while in its home folder. The full Folder enum also has 'deleted' (domain/message.rs:30-49).
- **`appointment.status`** — DEFAULT 'pending'
- **`meal_booking.status`** — DEFAULT 'booked'
- **`meal_attendance.status`** — deliberately NOT the school's attendance_statuses
- **`course.kind`** — DEFAULT 'course'
- **`exam.mode`** — NONE = an offline-graded draft that cannot be sat
- **`bank_question.visibility`** — DEFAULT 'private'
- **`pool_question.status`** — DEFAULT 'pending'. Rejection is not a state - the question is deleted.
- **`event.audience.kind`** — internally tagged on 'kind'. capacity may be omitted = unlimited. audience.users was REMOVED (migration_sql.rs:286).
- **`badge_award.badge`** — a badge_award row must be consistent with the user's counter: db/badge.rs only ever awards when counter >= threshold
- **`school.modules[*]  (CONTROL DB)`** — stored SORTED (module.rs:284). Dependencies: subjects/course_notes/sessions/classes require courses; exams+homework require courses+subjects; marks requires exams; attendance requires events+sessions.

#### `EventAudience` — etiketli obje (tam yapı)

`domain/event.rs:80-102`, `#[surreal(tag = "kind", rename_all = "lowercase")]`. `event.audience` bir `object`'tir ve alt alanları şemada ayrı ayrı tanımlıdır (`migration_sql.rs:276-281`). Tam saklanan biçimler:

```
{ kind: 'school' }
{ kind: 'role',         role: 'student' }          -- role: Role enum'u
{ kind: 'course',       course: course:⟨ULID⟩ }
{ kind: 'class',        class: class_group:⟨ULID⟩ }
{ kind: 'registration', capacity: 30 }             -- capacity yoksa sınırsız
```

Şemadaki alt alanlar: `audience.kind` (`string`, zorunlu), `audience.role`, `audience.course`, `audience.class`, `audience.capacity` (hepsi `option<...>`). **`audience.users` KALDIRILMIŞTIR** (`migration_sql.rs:286`) — yazarsanız SCHEMAFULL sessizce siler.

> SurrealDB 3, değeri `NONE` olan bir obje anahtarını **düşürür**. Bu yüzden `{kind:'school'}` gerçekten yalnızca tek anahtarlı bir objedir; `role`/`course`/`class`/`capacity` yazmayın.

#### `BadgeStat` — 12 istatistik ve sütunları

`domain/badge.rs:32-49` (enum), `:55-70` (`field()`), `:79-94` (`as_str()`). **Tel üzerindeki ad ile sütun adı kasten farklıdır** (`domain/badge.rs:72-78`, test `:222-241`).

| # | Variant | tel adı (`as_str`) | `user` sütunu (`field`) | sabit |
|---|---|---|---|---|
| 1 | `HomeworkSubmitted` | `homework_submitted` | `homework_submitted_total` | constant.rs:1012 |
| 2 | `HomeworkOnTime` | `homework_on_time` | `homework_on_time_total` | constant.rs:1013 |
| 3 | `ExamSat` | `exam_sat` | `exam_sat_total` | constant.rs:1014 |
| 4 | `PomodoroFinished` | `pomodoro_finished` | `pomodoro_finished_total` | constant.rs:1015 |
| 5 | `PomodoroFocusMs` | `pomodoro_focus_ms` | `pomodoro_focus_ms_total` | constant.rs:1016 |
| 6 | `MarksGiven` | `marks_given` | `marks_given_total` | constant.rs:1051 |
| 7 | `LessonsHeld` | `lessons_held` | `lessons_held_total` | constant.rs:1052 |
| 8 | `PoolApproved` | `pool_approved` | `pool_approved_total` | constant.rs:1053 |
| 9 | `PoolPublished` | `pool_published` | `pool_published_total` | constant.rs:1054 |
| 10 | `LessonsAttended` | `lessons_attended` | `lessons_attended_total` | constant.rs:1055 |
| 11 | `HighMark` | `high_mark` | `high_mark_total` | constant.rs:1056 |
| 12 | `StudyStreak` | `study_streak` | `study_streak_longest` | constant.rs:1066 |

Rozet katalogu `BADGES: [(&str, BadgeStat, i64); 34]` — `constant.rs:1095-1142`. Bir `badge_award` satırı ancak kullanıcının ilgili sayacı eşiğe ulaşmışsa tutarlıdır.

#### `Module` (21) ve `Package` (4) — kontrol veritabanı

`Module::ALL` (`module.rs:67-115`), `#[serde(rename_all = "snake_case")]`, `school.modules` içinde **sıralanmış** olarak saklanır (`module.rs:284`):

```
chatbot, notes, messages, events, appointments, courses, course_notes, classes, sessions, exams, marks, meals, payments, work, pomodoro, questions, bank_questions, attendance, subjects, homework, boards
```

Bağımlılıklar (`module.rs:131-159`): `subjects`, `course_notes`, `sessions`, `classes` → `courses`; `exams`, `homework` → `courses` + `subjects`; `marks` → `exams`; `attendance` → `events` + `sessions`.

`Package` (saklanmaz, yalnızca API): `academics`, `communication`, `operations`, `ai` (`module.rs:57-64`). Üyelik: academics = courses, subjects, sessions, exams, marks, homework, classes, course_notes, attendance, bank_questions; communication = notes, messages, events, appointments, questions, boards; operations = meals, payments, work, pomodoro; ai = chatbot.

`SchoolStatus`: `active`, `suspended` (`tenant.rs:117-131`).

### 3.2 `settings` tablosuna karşı doğrulanan değerler

Bunlar okul tarafından düzenlenebilir sözlüklerdir. `constant.rs`'teki diziler yalnızca **varsayılandır** ve `settings:school` satırı yokken geçerli olan değerlerdir.

| alan | doğrulandığı yer | varsayılanlar | kaynak |
|---|---|---|---|
| `attendance.status / session_attendance.status` | settings.attendance_statuses | `present`, `absent`, `late`, `excused` | constant.rs:157 / domain/attendance.rs:40-52 |
| `exam.kind` | settings.exam_kinds[*].name | `homework`, `quiz`, `midterm`, `final`, `project`, `oral` | constant.rs:165-172 / domain/exam.rs:87-104 |
| `menu.slot` | settings.meal_slots[*].name | `breakfast`, `lunch`, `snack` | constant.rs:207 / domain/menu.rs:138-164 |
| `menu_dish.tags[*] / dietary_profile.tags[*]` | settings.dietary_tags | `vegetarian`, `vegan`, `gluten_free`, `lactose_free`, `nut_allergy` | constant.rs:212-218 / domain/dietary_profile.rs:52-66 |
| `settings.grade_bands[*].label` | free text, school-defined | *(boş)* | domain/settings.rs:255 |
| `class_group.grade / class_blueprint.grade` | NOT an enum and NOT a settings list - FREE TEXT | — | constant.rs:117-118 |

- **`attendance.status / session_attendance.status`** — these four are the MANDATORY CORE and can never be removed; a school may add more, max 20 entries, each <= 50 chars
- **`exam.kind`** — each default weight = 1; weight range 1..=100. Every exam.kind used must also have a kind_ref row once a mark exists under it.
- **`menu.slot`** — snapshotted as TEXT on the menu row (not a link) and used verbatim in the record id, so / \ ? # % are refused
- **`menu_dish.tags[*] / dietary_profile.tags[*]`** — max 10 tags per dish / per profile
- **`settings.grade_bands[*].label`** — default is an EMPTY list. If non-empty: min in 0..=100, mins unique, one band must start at 0.
- **`class_group.grade / class_blueprint.grade`** — class_blueprint uses it as the record key, so it must be a legal record-id key

**Sınırlar:** `MAX_SETTINGS_LIST_LEN = 20`, `MAX_SETTINGS_ITEM_LEN = 50` (`constant.rs:176-177`); `MAX_GRADE_BANDS = 20`, `MAX_GRADE_LABEL_LEN = 20` (`constant.rs:180-181`); sınav türü ağırlığı `1..=100` (`constant.rs:508-509`); `MAX_MEAL_SERVING_MINUTE = 1439` (`constant.rs:272`).

---

## 4. Sayaç alanları ve değişmezleri (ÇOK KRİTİK)

### 4.1 Mekanizma — `db/cap.rs`

`db/cap.rs:1-31` tezini şöyle koyar: SurrealDB, tablolar arası bir `count()` ile eşzamanlı bir insert arasında çakışma denetimi yapmaz (write-skew), dolayısıyla 'çocukları say, sonra ekle' `BEGIN...COMMIT` içinde bile güvensizdir. Ayakta kalan tek koruma, **ebeveyn satırı üzerinde tek kayıtlık koşullu yazımdır**:

```sql
UPDATE $parent SET n = (n ?? 0) + 1 WHERE (n ?? 0) < $cap RETURN VALUE id
```

Sonuç: **sayaç otoritedir, alt satırlar onu takip eder.** Tüm sayaçlar ebeveynde `option<int>`'tir; **yokluk sıfır demektir**, bu sayede hiçbir Rust struct'ı onları taşımaz ve tam-satır yazımları ezmez.

### 4.2 Tam sayaç kataloğu

| sütun | neyi sayar | hangi koşulla | yazım yerleri | boot onarımı |
|---|---|---|---|---|
| `course.enrollment_count` | `enrollment` | course = <this course> | `db/enrollment.rs:91 (+1)`<br>`db/enrollment.rs:232 (-1)`<br>`db/class_pump.rs:442 (+1 class pump)`<br>`db/class_pump.rs:628 (-1 detach)`<br>`db/user.rs:307 (-1 delete/demote)` | **her boot'ta yeniden hesaplanır** (migration_sql.rs:1068 + 1181) |
| `term.course_count` | `course` | term = <this term> | `db/course.rs:51 (+1)`<br>`db/course.rs:171 (move)`<br>`db/course.rs:305 (-1)` | bir kez (migration_sql.rs:1189) |
| `term.class_count` | `class_group` | term = <this term> | `db/class_group.rs:49 (+1)`<br>`db/class_group.rs:129 (move)`<br>`db/class_group.rs:204 (-1)` | **YOK — kendiniz yazmalısınız** |
| `subject.exam_question_count` | `exam_question` | subject = <this subject> | `db/exam_question.rs:110 (+1)`<br>`db/exam_question.rs:255 (retag +-1)`<br>`db/exam_question.rs:370 (-1)` | bir kez (migration_sql.rs:1241) |
| `subject.homework_count` | `homework` | subject = <this subject> | `db/homework.rs:66 (+1)`<br>`db/homework.rs:198 (move)`<br>`db/homework.rs:225 (-1)` | bir kez (migration_sql.rs:1245) |
| `class_group.class_member_count` | `class_member` | class = <this class> | `db/class_pump.rs:427 (+1)`<br>`db/user.rs:299 (-1)` | **YOK — kendiniz yazmalısınız** |
| `class_group.class_course_count` | `class_course` | class = <this class> | `db/class_pump.rs:427 (+1)`<br>`db/course.rs:328 (-1)` | **YOK — kendiniz yazmalısınız** |
| `exam.result_count` | `exam_result` | exam = <this exam>  (ALL seq values) | `db/exam_result.rs:146 (+1, only when the sitting had no mark)`<br>`db/exam_result.rs:309 (-len(gone))` | bir kez (migration_sql.rs:1276) |
| `event.registration_count` | `registration` | event = <this event> | `service/registration.rs:56 (+1)`<br>`db/registration.rs:46 (-1)`<br>`db/user.rs:326 (-n)` | bir kez (migration_sql.rs:1194) |
| `note.file_count` | `note_file` | note = <this note> | `db/note_file.rs:23 (+1)`<br>`db/note_file.rs:75 (-1)` | bir kez (migration_sql.rs:1199) |
| `course_note.file_count` | `course_note_file` | course_note = <this note> | `db/course_note_file.rs:22 (+1)`<br>`db/course_note_file.rs:115 (-1)` | **YOK — kendiniz yazmalısınız** |
| `homework_submission.file_count` | `homework_file` | submission = <this submission> | `db/homework_file.rs:44 (+1)`<br>`db/homework_file.rs:192 (-1)` | bir kez (migration_sql.rs:1204) |
| `menu.seats_booked` | `meal_booking` | menu = <this menu> AND status = 'booked'   (cancelled rows EXCLUDED) | `db/meal_booking.rs:128 (+1, fenced on version)`<br>`db/meal_booking.rs:272 (-n)` | bir kez (migration_sql.rs:1226) |
| `menu.version` | *(sayım değil)* | NOT a row count - monotonic revision. Starts 0, +1 on every price / capacity / dish change. | `db/menu.rs:121 (init 0)`<br>`db/menu.rs:196`<br>`db/menu.rs:64`<br>`db/menu_dish.rs:53` | *(sayım değil — backfill yok)* |
| `appointment_slot.occupied` | `appointment` | slot = <this slot> AND status IN ['pending','approved'] | `service/appointment.rs:115 (+1)`<br>`db/appointment.rs:176 (-1)` | bir kez (migration_sql.rs:1214) |
| `user.chatbot_thread_count` | `chatbot_thread` | user_id = <this user> | `db/chatbot_thread.rs:119 (+1)`<br>`db/chatbot_thread.rs:235 (-n)` | bir kez (migration_sql.rs:1209) |
| `user.board_count` | `board` | creator = <this user> | `db/board.rs:37 (+1)`<br>`db/board.rs:187 (-n)`<br>`db/user.rs:341 (user delete)` | **YOK — kendiniz yazmalısınız** |
| `board.epoch` | *(sayım değil)* | monotonic epoch index, DEFAULT 0, +1 on every clear | `db/board_stroke.rs:158` | *(sayım değil — backfill yok)* |
| `board.epoch_stroke_count` | `board_stroke` | board = <this board> AND epoch = board.epoch | `db/board_stroke.rs:58 (+1)`<br>`db/board_stroke.rs:158 (reset to 0 on clear)` | **YOK — kendiniz yazmalısınız** |
| `board.total_stroke_count` | `board_stroke` | board = <this board>  (ALL rows, clear markers INCLUDED) | `db/board_stroke.rs:58 (+1)`<br>`db/board_stroke.rs:158 (+1 for the clear marker itself)` | **her boot'ta yeniden hesaplanır** (migration_sql.rs:1311) |
| `kind_ref.count` | `exam_result` | exam.kind = <the row id> | `db/exam_result.rs:143 (+1)`<br>`db/exam_result.rs:307 (-n)`<br>`db/course.rs:312 (-n)` | bir kez (migration_sql.rs:1265) |
| `slot_ref.count` | `menu` | slot = <the row id> | `db/menu.rs:126 (+1)`<br>`db/menu.rs:252 (-1)` | bir kez (migration_sql.rs:1270) |
| `kind_ref.retired / slot_ref.retired` | *(sayım değil)* | a bit, not a count. Flipped true by cap::retire_name only while (count ?? 0) = 0. | `db/cap.rs:765`<br>`db/cap.rs:788` | *(sayım değil — backfill yok)* |
| `fee_plan.assignment_count` | `fee_plan_assignment` | plan = <this plan> | `service/fee_plan_assignment.rs:64 (+1)` | bir kez (migration_sql.rs:1296) |
| `user.homework_submitted_total` | `homework_submission` | user = <this user> | `db/homework_submission.rs:110 (+1 on first hand-in)`<br>`db/homework_submission.rs:262 (-1)` | bir kez (migration_mark:profile_counters (migration_sql.rs:1437)) |
| `user.homework_on_time_total` | `homework_submission` | user = <this user> AND counted_on_time = true  (i.e. submitted_at <= homework.due_at) | `db/homework_submission.rs:111`<br>`db/homework_submission.rs:264` | bir kez (migration_mark:profile_counters (migration_sql.rs:1440)) |
| `user.exam_sat_total` | `exam_attempt` | user = <this user> AND (seq ?? 1) = 1   (one per exam - a retake credits nothing) | `service/exam_attempt.rs:208` | bir kez (migration_mark:profile_counters (migration_sql.rs:1449)) |
| `user.pomodoro_finished_total` | `pomodoro_session` | user = <this user> AND counted = true  (>= MIN_COUNTED_POMODORO_MS 300000 and within MAX_COUNTED_POMODORO_PER_DAY 16) | `db/pomodoro.rs:165` | bir kez (migration_mark:profile_counters (migration_sql.rs:1453) - the SEED counts finished_at != NONE, which is looser than the live rule) |
| `user.pomodoro_focus_ms_total` | `pomodoro_session` | sum over counted stints of max(finished_at - started_at, 0) | `db/pomodoro.rs:167` | bir kez (migration_mark:profile_counters) |
| `user.marks_given_total` | `exam_result + homework_result` | graded_by = <this user>, SUMMED ACROSS BOTH TABLES | `db/exam_result.rs:148 (+1)`<br>`db/homework_result.rs:118 (+1)`<br>`db/exam_result.rs:318 (-1)`<br>`db/homework_result.rs:236 (-1)` | **YOK — kendiniz yazmalısınız** |
| `user.lessons_held_total` | `course_session` | teacher = <this user> AND held_counted_at != NONE | `db/session_attendance.rs:148` | **YOK — kendiniz yazmalısınız** |
| `user.pool_approved_total` | `pool_question` | approved_by = <this user> AND asker != <this user> | `db/pool_question.rs:171` | **YOK — kendiniz yazmalısınız** |
| `user.pool_published_total` | `pool_question` | asker = <this user> AND status = 'approved' AND approved_by != asker | `db/pool_question.rs:174` | **YOK — kendiniz yazmalısınız** |
| `user.lessons_attended_total` | `session_attendance` | user = <this user> AND status IN ['present','late']  (students only) | `db/session_attendance.rs:142 (+-delta)`<br>`db/session_attendance.rs:254 (-1)` | **YOK — kendiniz yazmalısınız** |
| `user.high_mark_total` | `exam_result` | user = <this user> AND mark >= HIGH_MARK_MIN (90), per graded sitting | `db/exam_result.rs:154`<br>`db/exam_result.rs:313` | **YOK — kendiniz yazmalısınız** |
| `user.study_streak_longest` | *(sayım değil)* | max value study_streak_current has ever reached | `db/pomodoro.rs:180` | *(sayım değil — backfill yok)* |
| `user.study_streak_current` | *(sayım değil)* | consecutive UTC days with >= 1 counted pomodoro stint | `db/pomodoro.rs:172` | *(sayım değil — backfill yok)* |
| `user.study_streak_last_day` | *(sayım değil)* | Timestamp::day_number() of the last counted stint - DAYS FROM THE COMMON ERA EPOCH, not unix ms. 1970-01-01 = 719163. | `db/pomodoro.rs:178` | *(sayım değil — backfill yok)* |
| `user.pomodoro_counted_day` | *(sayım değil)* | day_number() of the day the daily quota bucket belongs to | `db/pomodoro.rs:158` | *(sayım değil — backfill yok)* |
| `user.pomodoro_counted_today` | `pomodoro_session` | stints counted on pomodoro_counted_day; cap MAX_COUNTED_POMODORO_PER_DAY = 16 | `db/pomodoro.rs:155 (reset)`<br>`db/pomodoro.rs:169 (+1)` | — |
| `meal_booking.attempt` | *(sayım değil)* | NOT a count - booking revision. Starts 1, +1 on every re-book after a cancel. Keys the ledger charge id. | `db/meal_booking.rs:133` | *(sayım değil — backfill yok)* |
| `homework_submission.counted_on_time` | *(sayım değil)* | frozen bool: submitted_at <= homework.due_at, decided once at submit time | `db/homework_submission.rs:108` | bir kez (migration_sql.rs:1443) |
| `homework_submission.graded_by_result` | *(sayım değil)* | freeze pointer -> homework_result:<the SAME key>. NONE while the submission is still editable. | `db/homework_result.rs:114 (set)`<br>`db/homework_result.rs:232 (clear)` | bir kez (migration_sql.rs:1166) |
| `course_session.held_counted_at` | *(sayım değil)* | stamp: non-NONE <=> this lesson has already credited its teacher's lessons_held_total exactly once | `db/session_attendance.rs:145` | *(sayım değil — backfill yok)* |
| `bank_question.used_count` | *(sayım değil)* | DOES NOT EXIST AS A STORED COLUMN. It is a response-only field computed per request from a GROUP BY over exam_question.from_bank. | `web/bank_questions.rs:220 (read only)` | *(sayım değil — backfill yok)* |

### 4.3 Tohum verisi için mutlak kurallar

1. **Her boot'ta yeniden hesaplanan yalnızca ikisi vardır:** `course.enrollment_count` (`migration_sql.rs:1068` + `1181`) ve `board.total_stroke_count` (`migration_sql.rs:1311`). Bunlarda yanlış yazsanız bile sistem kendini düzeltir.
2. **Bir kez tohumlanan (`= NONE` korumalı) sayaçlar:** `term.course_count`, `subject.exam_question_count`, `subject.homework_count`, `exam.result_count`, `event.registration_count`, `note.file_count`, `homework_submission.file_count`, `user.chatbot_thread_count`, `appointment_slot.occupied`, `menu.seats_booked`, `kind_ref.count`, `slot_ref.count`, `fee_plan.assignment_count`. Bunları **hiç yazmazsanız** bir sonraki boot doğru değerle doldurur. Yanlış yazarsanız sonsuza dek yanlış kalır.
3. **Hiçbir backfill'i olmayan, mutlaka elle yazılması gereken sayaçlar:**
   - `term.class_count`
   - `class_group.class_member_count`, `class_group.class_course_count`
   - `course_note.file_count`
   - `user.board_count`
   - `user.marks_given_total`, `user.lessons_held_total`, `user.pool_approved_total`, `user.pool_published_total`, `user.lessons_attended_total`, `user.high_mark_total`, `user.study_streak_longest` / `_current` / `_last_day`
   - `board.epoch`, `board.epoch_stroke_count`
4. **`migration_mark:profile_counters` bloğu** (`migration_sql.rs:1432-1461`) beş öğrenci rozet sayacını **önce sıfırlar** sonra satırlardan yeniden sayar: `homework_submitted_total`, `homework_on_time_total`, `exam_sat_total`, `pomodoro_finished_total`, `pomodoro_focus_ms_total`. Okul zaten bir kez boot olduysa bu mark yazılmıştır ve bir daha çalışmaz — o durumda bu beşini de kendiniz yazmalısınız.
5. **`bank_question.used_count` diye saklanan bir sütun YOKTUR.** Bu, istek başına `exam_question.from_bank` üzerinden `GROUP BY` ile hesaplanan bir yanıt alanıdır (`web/bank_questions.rs:220`).
6. **`fee_plan.assignment_count` monotoniktir** — azaltan bir yol yoktur (atama kaldırma rotası yok). Sıfırdan büyükse planın düzenlenmesi ve silinmesi kalıcı olarak dondurulur (`FEE_PLAN_UNASSIGNED_GUARD`, `constant.rs:965`).

---

## 5. Zaman ve değer formatları

### 5.1 Zaman damgaları — `int`, `datetime` DEĞİL

- **Temsil:** i64 unix MILLISECONDS, UTC, stored as SurrealDB TYPE int - NEVER a datetime
- **Kaynak:** `domain/timestamp.rs:1-13, :30-41`
- `domain/timestamp.rs:1-13`: *"Her an bir unix-milisaniye `i64`'tür, daima UTC — `int` olarak saklanır. Hiçbir zaman dilimi saklanmaz veya ayrıştırılmaz."* `Timestamp::now()` kod tabanındaki **tek** duvar saati okumasıdır; clippy `disallowed-methods` diğer tüm `now()` kaynaklarını reddeder.
- **SurrealQL'de:** düz bir tamsayı literali yazın.

```sql
-- DOĞRU
CREATE exam:⟨...⟩ CONTENT { starts_at: 1767225600000, ends_at: 1767232800000, ... };

-- YANLIŞ — datetime değeri TYPE int'e dönüşemez, yazım reddedilir
-- CREATE exam:... CONTENT { starts_at: d'2026-01-01T00:00:00Z' };
-- CREATE exam:... CONTENT { starts_at: time::now() };

-- Migrasyonun kendi 'şimdi' deyimi (migration_sql.rs:1360):
time::unix(time::now()) * 1000
```

### 5.2 Gün numaraları — unix ms DEĞİL

`user.study_streak_last_day`, `user.pomodoro_counted_day` sütunları **milisaniye değildir**.

- **Temsil:** chrono NaiveDate::num_days_from_ce() - days from the Common Era epoch
- **Çıpa:** 1970-01-01 = 719163 (pinned by the test at domain/timestamp.rs:145)
- **Formül:** `day_number = floor(unix_ms / 86400000) + 719163`
- **Kaynak:** `domain/timestamp.rs:78-97`

### 5.3 Para — minor unit (kuruş)

- **Temsil:** integer MINOR UNITS (kurus). Never decimal.
- **Alanlar:** `menu_dish.price_minor`, `meal_booking.price_minor`, `meal_ledger.amount_minor`, `payment_ledger.amount_minor`, `fee_plan.installments[*].amount_minor`
- **Sınırlar:** MAX_DISH_PRICE_MINOR = 1000000, MAX_LEDGER_AMOUNT_MINOR = 10000000
- **Kaynak:** `migration_sql.rs:800 / constant.rs:239-240` — şemadaki yorum aynen: *"Money is minor units (kuruş) as an integer, everywhere. Never decimal."*

### 5.4 Metin tarihler

- **`menu.date`** — `YYYY-MM-DD`, takvim günü, zaman dilimi yok (`migration_sql.rs:770-782`). Tam 10 karakterdir ve **kaydın id'sinin bir parçasıdır** (`menu:<date>_<slot>`). Şemadaki gerekçe: benzersiz indeks bir eşitlik testidir ve 'gece yarısı milisaniye' yalnızca tek bir zaman diliminde benzersizdir.
- **`user.birth_date`** — `option<string>`, takvim tarihi metni (`migration_sql.rs:57`). *(tam doğrulayıcı regex doğrulanmadı — `src/validate.rs`'e bakınız)*. Doğrulama bugünün UTC tarihi etrafında bir günlük tolerans bırakır (UTC+14'e kadar olan istemciler için).

### 5.5 `grade` alanı

- **Alanlar:** `class_group.grade` (`option<string>`), `class_blueprint.grade` (`string`, **id'nin kendisi**)
- **Biçim:** FREE TEXT, 1..=20 chars, no enum and no settings list
- **Kaynak:** `constant.rs:117-118`
- class_blueprint uses it as its record key. Typical Turkish school values would be like 9, 10, 11, 12 or 9-A - but nothing in the code prescribes any.
- `class_group_grade` indeksi (`migration_sql.rs:358`) vardır çünkü bir blueprint'in pompaladığı şey 'bu düzeydeki her sınıftır' — grade etiketi o okumanın tüm `WHERE`'idir. Yani `class_group.grade` ile `class_blueprint.grade` **birebir aynı metin** olmalıdır.

### 5.6 Diğer sayısal aralıklar

| alan | aralık | kaynak |
|---|---|---|
| `exam_result.mark`, `homework_result.mark` | `0..=100` | constant.rs:502-503 |
| `exam_question.points`, `bank_question.points` | `1..=100` | constant.rs:491-492 |
| `exam_question.choices` uzunluğu | `2..=10` | constant.rs:495-497 |
| `exam.duration_ms` | `60000..=86400000` | constant.rs:409-410 |
| `exam.max_attempts` | `0` (sınırsız) veya `1..=100` | constant.rs:415-416 |
| `settings.grade_bands[*].min` | `0..=100`, benzersiz, biri 0 olmalı | domain/settings.rs:162-180 |
| `menu.capacity` | `<= 10000` | constant.rs:228 |
| yüksek not eşiği `HIGH_MARK_MIN` | `90` | constant.rs:1081 |

---

## 6. Parola ve oturum

### 6.1 Parola hash'i

- **Algoritma:** Argon2id, sürüm 0x13 (19)
- **Parametreler:** Argon2::default() -> m_cost = 19456 KiB (19 MiB), t_cost = 2, p_cost = 1, 32-byte output
- **Tuz (salt):** 16 random bytes, base64 without padding (22 chars)
- **Kaynak:** `domain/user.rs:95-104, Cargo.toml:26 (argon2 0.5.3)`

```rust
// domain/user.rs:95-104
let mut salt_bytes = [0u8; 16];
getrandom::fill(&mut salt_bytes)...;
let salt = SaltString::encode_b64(&salt_bytes)...;
let hash = Argon2::default()
    .hash_password(self.0.as_bytes(), &salt)?
    .to_string();
```

`Argon2::default()` — hiçbir yerde açık `Params` verilmez. argon2 0.5.x varsayılanı: **Argon2id, v=19, m_cost = 19456 KiB (19 MiB), t_cost = 2, p_cost = 1, 32 bayt çıktı**. `domain/user.rs:70-71`'deki yorum bellek rakamını bağımsız olarak doğrular: *"argon2's default `m_cost` is 19 MiB"*.

**PHC dizgesi biçimi:**

```
$argon2id$v=19$m=19456,t=2,p=1$<22-char-b64-salt>$<43-char-b64-hash>
```

### 6.2 Testler kullanıcıyı nasıl oluşturuyor? Hazır bir hash var mı?

> **HAYIR — depoda hiçbir yerde gömülü bir argon2 hash'i yoktur.** `$argon2`, `argon2id`, `argon2i` için `*.rs`, `*.md`, `*.toml`, `*.yaml` taraması sıfır sonuç verir.

- `tests/common/mod.rs` kullanıcıları **yalnızca HTTP üzerinden** oluşturur: `POST /auth/register` (`tests/common/mod.rs:209-223`, `:389-396`), parola `"secret1"`. Rolü sonradan tek doğrudan SQL yazımıyla zorlar: `db.query("UPDATE user SET role = $role WHERE username = $u")` (`tests/common/mod.rs:190-198`).
- `src/**` içindeki birim testlerinin tüm doğrudan kullanıcı insert'leri yer tutucu `password_hash = 'x'` kullanır (`database.rs:568`, `tenant.rs:668`, `db/enrollment.rs:265-267`, `db/board.rs:217-219`, `db/cap.rs:932`). Böyle bir satır **asla giriş yapamaz** — `'x'` bir PHC dizgesi olarak ayrıştırılamaz, `verify` false döner (`domain/user.rs:144-151`).

> **Tohum kuralı:** Giriş yapabilmesi gereken her hesap için gerçek bir argon2id hash'i üretin. 250 öğrenci için **tek bir ortak hash** kullanmak hem geçerlidir hem de hızlıdır (hash üretimi hesap başına ~19 MiB bellek ve gözle görülür CPU ister). Bilinen tek açık parola `secret1`'dir ve onun da saklanmış bir hash'i yoktur.

### 6.3 Oturum

- **`session.token`** — 64 lowercase hex chars (32 random bytes) (`domain/session.rs:30-39`). `getrandom` ile 32 bayt, `hex::encode`. `session_token` UNIQUE indekslidir.
- **`session.expires_at`** — `Timestamp::now() + 7 * 86400000` (`db/session.rs:10-19, constant.rs:511 SESSION_DURATION_DAYS = 7`), yani `SESSION_DURATION_DAYS = 7`.
- **`session.user`** — `record<user>`.
- **Çerez biçimi:** `session=<school_slug>.<token>` (`tests/common/mod.rs:66-72`).
- `session` id'si **rastgele** `Ulid::new()`'dir (monotonik değil) — `domain/session.rs:14`.

### 6.4 Kimlik kısıtları

- **Kullanıcı adı:** 3..=32 chars; separators . _ -. Rezerve: `admin`, `administrator`, `root`, `support`, `system`, `moderator`, `staff` (`constant.rs:17-35`). reserved names are refused at /auth/register only, not on a direct DB write or the builder's admin seed
- **Parola (düz metin):** 6..=128 chars (`constant.rs:37-38`)
- **Okul slug'ı:** ^[a-z0-9][a-z0-9-]{1,31}$, 2..=32 chars, rezerve `builder`, `control` (`tenant.rs:49-96, constant.rs:11-12`). the slug is simultaneously the cookie prefix, the SurrealDB DATABASE name, and the blob directory. school:<slug> is the control-db record id.
- Diğer uzunluklar: ad/soyad 100, görünen ad 50, biyografi 500, e-posta 254, telefon 7-15 hane (`constant.rs:40-58`).

---

## 7. Yükleme sırası (topolojik)

`record<...>` alanlarından türetilmiş bağımlılık grafiği üzerinde hesaplanmıştır. **Döngüsel bağımlılık yoktur.**

Yakın-döngüler ve nasıl çözüldükleri:

- `exam_question.from_bank` / `.banked_as` → `bank_question` → `bank_question.source_exam` → `exam`. Sıra `exam` → `bank_question` → `exam_question` olduğu için düğüm çözülür. İkisi de `option<>` olduğundan istenirse boş bırakılabilir.
- `homework_submission.graded_by_result` → `homework_result` → `homework`. `homework` → `homework_result` → `homework_submission` sırası bunu çözer. `graded_by_result` `option<>`'tur; notlanmamış ödevlerde `NONE` bırakın.
- `class_course.source` → `class_blueprint`. `class_blueprint` `class_course`'tan önce gelir.
- `enrollment.source` → `class_group`. `class_group` önce gelir.

**Sıra:**

1. `kind_ref` — bağımlılık: *(bağımsız)*
2. `migration_mark` — bağımlılık: *(bağımsız)*
3. `rate_limit` — bağımlılık: *(bağımsız)*
4. `settings` — bağımlılık: *(bağımsız)*
5. `slot_ref` — bağımlılık: *(bağımsız)*
6. `term` — bağımlılık: *(bağımsız)*
7. `user` — bağımlılık: *(bağımsız)*
8. `appointment_slot` — bağımlılık: `user`
9. `badge_award` — bağımlılık: `user`
10. `board` — bağımlılık: `user`
11. `chatbot_thread` — bağımlılık: `user`
12. `class_group` — bağımlılık: `term`, `user`
13. `course` — bağımlılık: `term`, `user`
14. `dietary_profile` — bağımlılık: `user`
15. `fee_plan` — bağımlılık: `user`
16. `meal_ledger` — bağımlılık: `user`
17. `menu` — bağımlılık: `user`
18. `message` — bağımlılık: `user`
19. `note` — bağımlılık: `user`
20. `parent_link` — bağımlılık: `user`
21. `payment_ledger` — bağımlılık: `user`
22. `pomodoro_session` — bağımlılık: `user`
23. `pool_question` — bağımlılık: `user`
24. `session` — bağımlılık: `user`
25. `work_entry` — bağımlılık: `user`
26. `appointment` — bağımlılık: `appointment_slot`, `user`
27. `board_stroke` — bağımlılık: `board`, `user`
28. `chatbot_message` — bağımlılık: `chatbot_thread`, `user`
29. `class_blueprint` — bağımlılık: `course`, `user`
30. `class_member` — bağımlılık: `class_group`, `user`
31. `course_note` — bağımlılık: `course`, `user`
32. `course_session` — bağımlılık: `course`, `user`
33. `enrollment` — bağımlılık: `class_group`, `course`, `user`
34. `event` — bağımlılık: `class_group`, `course`, `user`
35. `exam` — bağımlılık: `course`, `user`
36. `fee_plan_assignment` — bağımlılık: `fee_plan`, `user`
37. `meal_attendance` — bağımlılık: `menu`, `user`
38. `meal_booking` — bağımlılık: `menu`, `user`
39. `menu_dish` — bağımlılık: `menu`
40. `note_file` — bağımlılık: `note`
41. `solution` — bağımlılık: `pool_question`, `user`
42. `subject` — bağımlılık: `course`
43. `attendance` — bağımlılık: `event`, `user`
44. `bank_question` — bağımlılık: `exam`, `subject`, `user`
45. `class_course` — bağımlılık: `class_blueprint`, `class_group`, `course`, `user`
46. `course_note_file` — bağımlılık: `course_note`
47. `exam_attempt` — bağımlılık: `exam`, `user`
48. `exam_result` — bağımlılık: `exam`, `user`
49. `homework` — bağımlılık: `course`, `subject`, `user`
50. `registration` — bağımlılık: `event`, `user`
51. `session_attendance` — bağımlılık: `course`, `course_session`, `user`
52. `bank_question_image` — bağımlılık: `bank_question`
53. `exam_question` — bağımlılık: `bank_question`, `exam`, `subject`
54. `homework_result` — bağımlılık: `homework`, `user`
55. `rag_output` — bağımlılık: `course`, `course_note`, `course_note_file`
56. `answer_image` — bağımlılık: `exam`, `exam_question`, `user`
57. `exam_answer` — bağımlılık: `exam`, `exam_question`, `user`
58. `homework_submission` — bağımlılık: `homework`, `homework_result`, `user`
59. `question_image` — bağımlılık: `exam`, `exam_question`
60. `homework_file` — bağımlılık: `homework_submission`

> **Not:** `rate_limit`, `migration_mark`, `kind_ref`, `slot_ref` uygulama tarafından yönetilen yardımcı tablolardır; `rate_limit` ve `migration_mark` tohumlanmamalıdır.

> **FK zorlaması yoktur** (bkz. §8). Sıra, veritabanı zorladığı için değil, uygulama katmanı kırık bağlantılarda patladığı için gereklidir.

---

## 8. Tohum verisi için tuzaklar

### 1. `DEFAULT []` sorunu — YÜKSEK  <sub>`default-empty-array`</sub>

**Yer:** `migration_sql.rs:645-657 (settings), also migration_sql.rs:369-372 (class_blueprint.courses)`

**Ne oluyor:** SCHEMAFULL bir satırda `DEFAULT []` taşıyan **zorunlu** bir dizi alanı. `DEFAULT` yalnızca `CREATE` anında tetiklenir. Sonraki herhangi bir tam-satır yazımı (`UPDATE ... CONTENT`) anahtarı atlarsa değer `NONE`'a zorlanır ve yazım **kalıcı olarak başarısız olur**. Şemadaki yorum (`migration_sql.rs:645-657`) bunu aynen anlatır: *"a required-with-default field a writer omits coerces to NONE and fails every settings write"* — her `PATCH /settings` çağrısını bozan hata buydu. Bu yüzden `settings.meal_slots` / `dietary_tags` `option<>`'tur ve **DEFAULT taşımaz**; `class_blueprint.courses` de aynı nedenle DEFAULT'suzdur (`migration_sql.rs:364-368`).

**Tohum kuralı:** Her dizi alanını **açıkça** yazın, `DEFAULT []`'e asla güvenmeyin. Hâlâ `DEFAULT []` taşıyan üç alan: `course.teachers`, `menu_dish.tags`, `dietary_profile.tags` — bunları da yine de açıkça yazın.

### 2. `READONLY` tablolar INSERT edilebilir mi? — YÜKSEK  <sub>`readonly-tables`</sub>

**Yer:** `meal_ledger (migration_sql.rs:846-856), payment_ledger (migration_sql.rs:894-903), plus READONLY columns on chatbot_thread/chatbot_message/homework*/menu*/meal_*/fee_plan*`

**Ne oluyor:** **Evet.** `READONLY` tablo düzeyinde değil, **alan düzeyindedir**. Alanı **ilk kez** değerleyen bir `CREATE`/`INSERT` kabul edilir; sonraki her `UPDATE` reddedilir. `meal_ledger` ve `payment_ledger` tasarım gereği yalnızca-ekleme (append-only) tablolardır ve bu yüzden **her alanları** READONLY'dir.

**Tohum kuralı:** `meal_ledger` ve `payment_ledger` satırları **eklenebilir** — sadece her değeri ilk seferde doğru yazın ve sonra asla UPDATE etmeyin. Aynı kural şu READONLY sütunlar için de geçerlidir: `menu.date`/`slot`/`created_by`/`created_at`, `homework.course`/`created_by`/`created_at`, `meal_booking.menu`/`student`/`booked_by`/`created_at`, `fee_plan_assignment.*`, `bank_question.created_at`, `homework_file.file`/`created_at`, `homework_submission.homework`/`user`/`submitted_at`, `chatbot_thread.user_id`/`created_at`, `chatbot_message.thread_id`/`user_id`/`role`/`created_at`, `dietary_profile.student`, `menu_dish.menu`/`created_at`, `meal_attendance.menu`/`student`, `homework_result.homework`/`user`, `fee_plan.created_by`/`created_at`.

### 3. `SCHEMAFULL` + tanımsız alan yazma davranışı — YÜKSEK  <sub>`schemafull-strips`</sub>

**Yer:** `every table (all 60 are SCHEMAFULL)`

**Ne oluyor:** Tanımsız bir anahtar yazımda **sessizce silinir** — hata değildir. Tek istisna: tanımı kaldırılmış bir sütunu hâlâ taşıyan bir satıra yazım SurrealDB tarafından reddedilir (`migration_sql.rs:14-29`, `PRE_REPAIR`'in var olma nedeni). `rag_output.payload` şemadaki **tek** `FLEXIBLE` objedir (`migration_sql.rs:211`) — içindeki anahtarlar korunur; diğer tüm objelerde (`event.audience`, `exam_question.choices[*]`, `settings.exam_kinds[*]`, `fee_plan.installments[*]`) yalnızca şemada tanımlı alt anahtarlar yaşar.

**Tohum kuralı:** Alan adındaki tek harflik bir hata değeri **hatasız** kaybettirir. Her alan adını `schema.json`'a karşı karakter karakter doğrulayın.

### 4. Aynı batch'te DEFINE FIELD + UPDATE sorunu — ORTA  <sub>`ddl-plus-dml-same-batch`</sub>

**Yer:** `migration_sql.rs:41-47 (doc comment)`

**Ne oluyor:** Tek bir sorgu batch'i içindeki ifadeler şemayı **batch başladığı andaki hâliyle** görür. Taze bir `DEFINE FIELD`'ın yanındaki bir `UPDATE`, eski alan kümesine yazar ve SCHEMAFULL, backfill'in yazmaya çalıştığı anahtarları sessizce siler. `MIGRATION_BATCHES`'in üç **ayrı** sorgu olmasının tek nedeni budur (`migration_sql.rs:41-47`, `:1513-1518`).

**Tohum kuralı:** Tohumu, herhangi bir şema işinden **ayrı** bir sorgu olarak çalıştırın — yani `migrate()` tamamen bittikten sonra.

### 5. `VALUE` ifadesi olan alanlar — hiç yok — BİLGİ  <sub>`value-and-assert`</sub>

**Yer:** `whole DDL`

**Ne oluyor:** Şemada **tek bir `DEFINE FIELD ... VALUE` veya `... ASSERT` yoktur** (grep ile doğrulandı). Dosyadaki 7 adet ` VALUE ` geçişinin hepsi `SELECT VALUE`'dur. Repo konvansiyonu bunu açıkça söyler (`domain/homework_result.rs:55-58`): *enum'lar Rust newtype'larında yaşar, şemada değil*.

**Tohum kuralı:** Yazdığınız hiçbir değer ezilmez — bu iyi haber. Kötü haber: veritabanı hiçbir enum'u doğrulamaz, geçersiz bir string sorunsuz kaydedilir ve hata ancak Rust newtype'ı satırı geri okuyamadığında **500** olarak patlar. §3'teki listeler bu yüzden zorunludur.

### 6. `record<x>` — var olmayan hedefe referans — YÜKSEK  <sub>`no-fk-enforcement`</sub>

**Yer:** `whole DDL`

**Ne oluyor:** `record<x>` yalnızca bir **tip** kontrolüdür: SurrealDB değerin `x` tablosuna işaret eden bir kayıt işaretçisi olduğunu doğrular, **hedef satırın var olduğunu doğrulamaz**. Şemada hiçbir `REFERENCE` veya `ON DELETE` yan tümcesi yoktur. Sarkan bir bağ sessizce kabul edilir ve sonra uygulama katmanında kırılır — örneğin `homework_submission` → `homework.due_at` geçişi değer üretmez ve karşılaştırma başarısız olur (`migration_sql.rs:1399-1401`).

**Tohum kuralı:** Kesinlikle §7'deki topolojik sırayla ekleyin. *(kısmen doğrulanmadı: var olmayan bir hedefe yazımın SurrealDB 3.2'deki kesin davranışı çalıştırılarak test edilmedi — ancak hiçbir `REFERENCE` yan tümcesi bulunmadığından zorlayacak bir mekanizma yoktur.)*

### 7. UNIQUE indeksler — çakışma riski — YÜKSEK  <sub>`unique-indexes`</sub>

**Yer:** `see indexes in each table`

**Ne oluyor:** Çakışma riski taşıyan UNIQUE indeksler: `user_username`, `session_token`, `menu_date_slot` (date+slot), `dietary_profile_student`, `attendance_event_user`, `registration_event_user`, `class_member_class_user`, `class_course_class_course`, `enrollment_course_user`, `parent_link_parent_student`, `session_attendance_session_user`, `meal_attendance_menu_student`, `exam_attempt_exam_user_seq`, `exam_answer_question_user_seq`, `exam_result_exam_user_seq`; kontrol veritabanında `school_slug`, `builder_username`, `builder_session_token`.

**Tohum kuralı:** Bunların çoğu zaten kompozit kayıt id'sinin ima ettiği şeydir — yani mükerrer id ile mükerrer indeks girdisi aynı hatadır. İd tarafından **ima edilmeyen** ikisi `user_username` ve `session_token`'dır; onları ayrıca güvenceye alın. 250 öğrenci için kullanıcı adlarının global benzersizliğini bir küme ile takip edin.

### 8. Sayaçlar tutarsızsa ne olur — KRİTİK  <sub>`counters-must-match`</sub>

**Yer:** `see counters section`

**Ne oluyor:** Her sayaç bir önbellek değil, **otoritedir** (`db/cap.rs:1-31`). `enrollment_count`'u yanlış olan bir ders gerçek bir öğrenciye yer vermez **ve asla silinemez** — `Course::delete` koruması `(enrollment_count ?? 0) = 0`'dır (`db/course.rs:301`). Aynı şekilde `assignment_count`'u sıfırdan büyük bir `fee_plan` kalıcı olarak düzenlenemez ve silinemez.

**Tohum kuralı:** Her sayacı tutarlı yazın; ya da **yalnızca** boot backfill'inin yeniden hesaplayacağı yerlerde (yokluk = sıfır olduğu için) atlayın. §4.3'teki üç listeye bakın: her boot'ta onarılan yalnızca `course.enrollment_count` ve `board.total_stroke_count`'tur.

### 9. `migration_mark:profile_counters` tuzağı — YÜKSEK  <sub>`profile-counters-mark`</sub>

**Yer:** `migration_sql.rs:1432-1461`

**Ne oluyor:** Beş öğrenci rozet sayacı volume başına **bir kez** tohumlanır ve bloğun ilk satırı tam bir sıfırlamadır: `UPDATE user SET homework_submitted_total = 0, homework_on_time_total = 0, exam_sat_total = 0, pomodoro_finished_total = 0, pomodoro_focus_ms_total = 0;` (`migration_sql.rs:1434-1436`). Blok, metninin FNV-1a parmak izi (`$fp_profile_counters`) ile kapılanır.

**Tohum kuralı:** Okul **ilk boot'undan önce** tohumlanırsa `migrate()` bu beşini sizin satırlarınızdan yeniden hesaplar (istenen davranış). Okul zaten bir kez boot olduysa mark yazılmıştır, blok bir daha çalışmaz ve yazdığınız değerler olduğu gibi kalır. **Önerilen akış:** okulu oluşturun (migrate çalışsın), sonra tohumlayın ve **tüm** sayaçları kendiniz yazın.

### 10. ID kaçışı (escaping) — KRİTİK  <sub>`id-escaping`</sub>

**Yer:** `hand-written .surql only`

**Ne oluyor:** Üretilen her anahtar bir ULID'dir veya bir ULID ile başlar, yani **rakamla başlar**. Kod tabanı hiçbir id'yi SQL metnine yazmaz — `RecordId` olarak bağlar — dolayısıyla bu sorun elle yazılan bir `.surql` dosyasına özgüdür. Repodaki tek literal id'ler güvenli olanlardır: `migration_mark:board_roster`, `settings:school`, ve birim testlerindeki `user:t` gibi el yapımı anahtarlar.

**Tohum kuralı:** `user:⟨01J...⟩` (açı parantezi), `user:` + ters tırnaklı biçim, ya da `type::record('user','01J...')` kullanın. **Asla** çıplak `user:01J...` yazmayın.

### 11. `??` operatörü parantezlenmeli — ORTA  <sub>`parenthesise-nullish`</sub>

**Yer:** `db/cap.rs:554, db/cap.rs:766, db/board_stroke.rs:155`

**Ne oluyor:** SurrealQL'de `n ?? 0 < $cap` ifadesi `n ?? (0 < $cap)` olarak ayrıştırılır ve her satır için doğrudur — yani kapasite kontrolü tamamen devre dışı kalır. Doğrusu `(n ?? 0) < $cap`'tir. Kod bunu üç ayrı yerde uyarı olarak not eder (`db/cap.rs:554-555`, `db/cap.rs:766-767`, `db/board_stroke.rs:155-156`).

**Tohum kuralı:** Yalnızca tohum betiği kendi korumalı `UPDATE`'lerini yazıyorsa geçerlidir — ama o zaman kritiktir.

### 12. Gün numarası sütunları milisaniye değildir — ORTA  <sub>`day-number-not-millis`</sub>

**Yer:** `user.study_streak_last_day, user.pomodoro_counted_day`

**Ne oluyor:** `user.study_streak_last_day` ve `user.pomodoro_counted_day` `int`'tir ama **unix ms değildir**. Bunlar `chrono`'nun `num_days_from_ce()` değeridir — Miladi çağ başlangıcından itibaren gün sayısı; 1970-01-01 = **719163** (`domain/timestamp.rs:78-97`, test `:145` ile sabitlenmiş).

**Tohum kuralı:** `gun_numarasi = floor(unix_ms / 86400000) + 719163`. Buraya milisaniye yazmak streak mantığını sessizce bozar.

### 13. Devam eden (open) satırların sabit id'si — ORTA  <sub>`open-row-ids`</sub>

**Yer:** `work_entry, pomodoro_session`

**Ne oluyor:** Devam etmekte olan bir mesai kaydı veya pomodoro seansı **sabit** `open_<kullanıcı ULID>` id'sinde yaşar; kapandığında satır taze bir ULID id'sine taşınır (`domain/work_entry.rs:37-40`, `domain/pomodoro.rs:29-32`). Bir kullanıcı için ikinci bir açık satır yapısal olarak imkânsızdır.

**Tohum kuralı:** Bir kullanıcıya id'si `open_<ulid>` olan iki satır vermeyin ve `finished_at = NONE` / `check_out = NONE` olan bir satıra **asla** ULID id'si vermeyin.

### 14. İlk oturumun id'si çıplaktır — YÜKSEK  <sub>`seq-1-bare`</sub>

**Yer:** `domain/key.rs:16-22`

**Ne oluyor:** `exam_attempt`, `exam_answer`, `exam_result`, `answer_image` için **ilk** oturumun id'si `_1` soneki olmadan çıplak `{scope}_{user}`'dır — `seq` **sütunu** ise yine `1`'dir (`domain/key.rs:16-22`). Bu, göç yasasıdır: değiştirilirse tarih öncesi her satır erişilemez olur.

**Tohum kuralı:** Asla `..._1` biçiminde bir id yazmayın. `seq = 1` → çıplak anahtar; `seq = 2` → `anahtar_2`. Ayrıca `seq` sütununu **her zaman** açıkça yazın: `DEFAULT 1` yalnızca `CREATE`'te tetiklenir ve eksik `seq` hem deserializasyonu hem de sonraki her yazımı bozar (`migration_sql.rs:1128-1140`).

### 15. Hazır parola hash'i yok — YÜKSEK  <sub>`no-password-hash-literal`</sub>

**Yer:** `whole repo`

**Ne oluyor:** Depoda hiçbir yerde gömülü bir argon2 hash'i yoktur. Repodaki tüm doğrudan SQL kullanıcı insert'leri `password_hash = 'x'` yer tutucusunu kullanır ve böyle bir satır asla giriş yapamaz.

**Tohum kuralı:** Giriş yapması gereken her hesap için gerçek bir `$argon2id$v=19$m=19456,t=2,p=1$...$...` hash'i üretin. 250 öğrenci için **tek bir ortak hash** kullanmak geçerlidir ve çok daha hızlıdır (hash başına ~19 MiB bellek).

### 16. `settings:school` tembel yaratılır — ORTA  <sub>`settings-lazy`</sub>

**Yer:** `db/settings.rs:9-12, tenant.rs:390-447`

**Ne oluyor:** Okul oluşturma bir `settings` satırı **yazmaz** (`tenant.rs:390-447`). Satır yokken her okuma `constant.rs`'teki varsayılanlara düşer (`db/settings.rs:9-12`). Satır, ilk `PATCH /settings` sırasında `INSERT IGNORE INTO settings $expected` ile maddileşir (`db/settings.rs:55`).

**Tohum kuralı:** Yalnızca varsayılan olmayan bir sözlüğe ihtiyacınız varsa `settings:school`'u tohumlayın. Yazacaksanız **zorunlu alanların hepsini** yazın: `exam_kinds` (+ `.*.name`, `.*.weight`), `attendance_statuses`, `grade_bands` — bunlar `option<>` değildir ve eksik biri yazımı reddettirir. `attendance_statuses` dört çekirdek değeri (`present`, `absent`, `late`, `excused`) **mutlaka** içermelidir.

### 17. `kind_ref` / `slot_ref` referans sayaçları — YÜKSEK  <sub>`kind-ref-slot-ref`</sub>

**Yer:** `migration_sql.rs:1265-1271`

**Ne oluyor:** `kind_ref:<sınav türü>` ve `slot_ref:<öğün>` satırları ilk `exam_result` / `menu` ile tembel yaratılır. Boot backfill'i bunları tohumlar ama yalnızca `count = NONE` iken (`migration_sql.rs:1265-1271`). Bir ismin ayarlardan kaldırılabilmesi tam olarak sayacının sıfır okumasına bağlıdır.

**Tohum kuralı:** Ya kendiniz tohumlayın (`count` = eşleşen satır sayısı) ya da boot backfill'ine bırakın — ama ikisini farklı sayılarla yapmayın. `retired` alanını tohumlamayın.

### 18. `event.audience.users` kaldırılmıştır — DÜŞÜK  <sub>`audience-users-removed`</sub>

**Yer:** `migration_sql.rs:286`

**Ne oluyor:** `REMOVE FIELD IF EXISTS audience.users ON TABLE event` (`migration_sql.rs:286`). Yazarsanız SCHEMAFULL sessizce siler ve etkinlik bozuk bir hedef kitleyle okunur. Eski `users` hedef kitlesi `registration` tablosuna göç ettirilmiştir (`migration_sql.rs:992-1004`).

**Tohum kuralı:** Elle seçilmiş katılımcı listesi için `{kind:'registration'}` + `registration` satırları kullanın ve `event.registration_count`'u da yazın.

### 19. `exam_question.subject` zorunludur — ORTA  <sub>`exam-question-subject-required`</sub>

**Yer:** `migration_sql.rs:511, migration_sql.rs:987`

**Ne oluyor:** `exam_question.subject` zorunlu bir `record<subject>`'tir (`migration_sql.rs:511`). Boot backfill'i `subject = NONE` olan **her** `exam_question`'ı — ve önce onların cevaplarını — **siler** (`migration_sql.rs:986-988`).

**Tohum kuralı:** Her `exam_question` gerçek bir `subject`'e işaret etmeli ve o subject'in `course`'u sınavın `course`'u ile aynı olmalıdır. `bank_question.subject` ise `option<>`'tur (`OVERWRITE` ile öyle yapıldı).

### 20. HTTP üzerinden tohumlama ve hız sınırları — DÜŞÜK  <sub>`rate-limit-and-http-seeding`</sub>

**Yer:** `constant.rs:681-683`

**Ne oluyor:** `DEFAULT_AUTH_RATE_LIMIT = 10`/dk/IP ve `DEFAULT_API_RATE_LIMIT = 300`/dk/IP (`constant.rs:681-683`). Ayrıca `REQUEST_TIMEOUT_SECS = 30` (`constant.rs:436`). 250 öğrencilik bir tohum HTTP üzerinden sürülürse 429 alır.

**Tohum kuralı:** Toplu tohumlama için doğrudan SurrealQL tercih edin; ya da env anahtarlarını yükseltin. Depoda hiçbir seed/import CLI'ı yoktur.

---

## Ek: okul veritabanı nasıl hazırlanır

- Bir okul `Tenants::create` ile oluşturulur (`tenant.rs:390-447`): kontrol veritabanına `school:<slug>` satırı yazılır, `DEFINE DATABASE \`<slug>\`` çalıştırılır, sonra `migrate(&db)` üç batch'i (`PRE_REPAIR`, `MIGRATION`, `BACKFILL`) **ayrı sorgular** olarak uygular (`database.rs:366-375`, `migration_sql.rs:1518`).
- **Okul oluşturma bir `settings` satırı yazmaz** ve `Tenants::create` doğrudan çağrıldığında **hiç kullanıcı da yaratmaz**. İlk admin, builder ucundan gelir: `POST /schools` (`web/builder.rs:338-374`) → `service::user::create_with_role(..., Role::Admin)`, id taze bir ULID.
- Migrasyon bağlama parametreleri (`database.rs:398-462`): `$stale_ms = 300000`, `$fp_board_roster`, `$fp_profile_counters` (blok metninin FNV-1a parmak izi), `$all_modules` (yalnızca kontrol veritabanı).
- **Depoda hiçbir seed/import CLI'ı yoktur.** Tohum verisi ya HTTP API üzerinden ya da doğrudan SurrealQL ile okul veritabanına yazılmalıdır. HTTP yolunda hız sınırları devreye girer (`DEFAULT_AUTH_RATE_LIMIT = 10`/dk/IP, `DEFAULT_API_RATE_LIMIT = 300`/dk/IP — `constant.rs:681-683`), bu yüzden 250 öğrencilik bir yük için **doğrudan SurrealQL önerilir**.
- Bağlantı: uzak modda `use_ns(<ns>).use_db(<slug>)` (`tenant.rs:605`), bellek modunda `use_ns("hezarfen").use_db(<slug>)` (`tenant.rs:610`).

