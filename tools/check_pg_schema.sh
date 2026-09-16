#!/usr/bin/env bash
# Applies the backend's own school+control migrations AND ZEKA's migration to a
# throwaway Postgres, then asserts the result.
#
# TOUCHES NOTHING LIVE. It creates its own database, applies files read-only,
# and drops the database at the end. No backend file is written.
#
# Why it exists: a migration that is only read looks fine. The SurrealDB
# version of this schema passed review twice and still dropped five fields
# silently, because `FLEXIBLE TYPE object` parses as garbage and SCHEMAFULL
# discards undefined fields without a word. The only defence is running it.
#
#   tools/check_pg_schema.sh
#
# Env: HEZARFEN_PG_CONTAINER (default zeka_pg_test), BACKEND (path to the new
# backend checkout).
set -euo pipefail

CONTAINER="${HEZARFEN_PG_CONTAINER:-zeka_pg_test}"
DB="${HEZARFEN_CHECK_DB:-zeka_schema_check}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="${BACKEND:-$HERE/../hezarfen_backend-main-yeni/hezarfen_backend-main}"

psql() { podman exec -i "$CONTAINER" psql -U hezarfen -v ON_ERROR_STOP=1 "$@"; }

echo "== backend: $BACKEND"
[ -d "$BACKEND/migrations/school" ] || { echo "!! migrations/school yok"; exit 1; }

psql -d postgres -q <<SQL
DROP DATABASE IF EXISTS $DB;
CREATE DATABASE $DB;
SQL

for file in "$BACKEND"/migrations/control/*.sql "$BACKEND"/migrations/school/*.sql; do
    echo "== backend  $(basename "$file")"
    psql -d "$DB" -q -f - < "$file"
done

# ZEKA'nin migration'i backend deposuna da KOPYALANDI (orasi artik gercek
# evi). Ayni dosyayi iki kez uygulamak "relation already exists" verir, o
# yuzden backend'de ayni adla bir dosya varsa burada atlanir. Bu bir susturma
# degil: backend'deki kopyanin uygulandigi zaten yukaridaki dongude yaziyor.
for file in "$HERE"/service/schema/postgres/school/*.sql; do
    ad="$(basename "$file")"
    if [ -f "$BACKEND/migrations/school/$ad" ]; then
        echo "== ZEKA     $ad  (backend kopyasi uygulandi, atlandi)"
        continue
    fi
    echo "== ZEKA     $ad"
    psql -d "$DB" -q -f - < "$file"
done

echo
echo "== zeka_* tablolari"
psql -d "$DB" -tAc "
SELECT c.relname || '  (' || count(a.attname) || ' kolon)'
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
LEFT JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
WHERE c.relkind = 'r' AND c.relname LIKE 'zeka\\_%'
GROUP BY c.relname ORDER BY c.relname;"

echo
echo "== disa giden yabanci anahtarlar (ZEKA -> okul)"
psql -d "$DB" -tAc "
SELECT src.relname || '.' || con.conname || ' -> ' || tgt.relname
FROM pg_constraint con
JOIN pg_class src ON src.oid = con.conrelid
JOIN pg_class tgt ON tgt.oid = con.confrelid
WHERE con.contype = 'f' AND src.relname LIKE 'zeka\\_%'
  AND tgt.relname NOT LIKE 'zeka\\_%'
ORDER BY 1;"

echo
echo "== ZEKA okul tablolarina yaziyor mu? (ters yonlu FK olmamali)"
ters=$(psql -d "$DB" -tAc "
SELECT count(*) FROM pg_constraint con
JOIN pg_class src ON src.oid = con.conrelid
JOIN pg_class tgt ON tgt.oid = con.confrelid
WHERE con.contype = 'f' AND src.relname NOT LIKE 'zeka\\_%'
  AND tgt.relname LIKE 'zeka\\_%';")
if [ "$ters" != "0" ]; then echo "!! $ters adet ters FK — okul semasi ZEKA'ya bagimli olmus"; exit 1; fi
echo "   yok (0) — okul semasi ZEKA'dan bagimsiz kaldi"

echo
echo "== ad cakismasi (DISJOINTNESS)"
cak=$(psql -d "$DB" -tAc "
SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND c.relkind='r' AND c.relname LIKE 'zeka\\_%'
  AND c.relname IN ('app_user','course','subject','exam','exam_question');")
[ "$cak" = "0" ] && echo "   yok (0)"

echo
echo "== toplam tablo"
psql -d "$DB" -tAc "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r';"

# Semanin YUKLENMESI ile CALISMASI ayri seyler. Asagisi gercek sekilli satirlar
# yazar ve reddedilmesi gerekenlerin reddedildigini kanitlar; duserse betik de
# duser (ON_ERROR_STOP).
psql -d "$DB" -f - < "$HERE"/tools/check_pg_rows.sql

psql -d postgres -q -c "DROP DATABASE $DB;"
echo "== $DB dusuruldu. Canliya dokunulmadi."
