#!/usr/bin/env bash
# DEMO tohumunu yeni (PostgreSQL) backend'e yukler.
#
# Ne yapar:
#   1. Okul veritabanini backend'in KENDI adlandirma kuraliyla kurar
#      (`tenant::school_db_name` -> "{control}_school_{uuid.simple}")
#   2. Backend'in `migrations/school` semasini + ZEKA'nin migration'ini uygular
#   3. `pg_school.sql`'i doker
#   4. Control veritabanina okul kaydini ve kisi satirlarini yazar
#
# Neden bu sira: okul veritabaninin ADI okulun uuid'sinden tureniyor, slug'dan
# degil. Yani uuid onceden bilinmek zorunda; tohum onu sabitliyor
# (`generator/pg_map.DEMO_SCHOOL_ID`). Control satiri EN SONA birakiliyor:
# backend acilir acilmaz okulu `active` gorup istek kabul etmeye baslar, o
# yuzden okul verisi hazir olmadan kaydi yazmak yarim bir okul acmak olurdu.
#
# Tohumu iki kez yuklemek: her iki dosya da tek transaction'da kosar ve
# birincil anahtarlar deterministiktir, yani ikinci yukleme catisma verir ve
# HICBIR SEY yazmaz. Yeniden yuklemek icin veritabanini dusurmek gerekir.
#
#   tools/load_pg_seed.sh /yol/pgseed
#
# Ortam:
#   PGC   psql'i kosturan komut (varsayilan: podman exec -i <konteyner> psql)
#   CONTROL_DB  control veritabani adi (varsayilan hezarfen_control)
#   BACKEND     yeni backend checkout'u
set -euo pipefail

SEED_DIR="${1:-}"
[ -n "$SEED_DIR" ] || { echo "kullanim: $0 <tohum-dizini>"; exit 1; }

# Canlida konteyner adi `hezarfen_backend_postgres`, kullanici ve control
# veritabani adi `hezarfen_backend.env` icindeki POSTGRES_USER / POSTGRES_DB
# ile ayni olmali. Uctaki degerler gelistirme icindir.
CONTAINER="${HEZARFEN_PG_CONTAINER:-zeka_pg}"
PGUSER_="${POSTGRES_USER:-hezarfen}"
CONTROL_DB="${CONTROL_DB:-${POSTGRES_DB:-hezarfen_control}}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="${BACKEND:-$HERE/../hezarfen_backend-main-yeni/hezarfen_backend-main}"

# Tohumun sabitledigi okul kimligi — tek kaynak `generator/pg_map.py`.
SCHOOL_ID="$(cd "$HERE/generator" && python -c "import pg_map;print(pg_map.DEMO_SCHOOL_ID)")"
SCHOOL_DB="${CONTROL_DB}_school_$(echo "$SCHOOL_ID" | tr -d '-')"

psql() { podman exec -i "$CONTAINER" psql -U "$PGUSER_" -v ON_ERROR_STOP=1 "$@"; }

echo "== okul   : $SCHOOL_ID"
echo "== okul db: $SCHOOL_DB"
echo "== control: $CONTROL_DB"

psql -d postgres -q <<SQL
SELECT 'control var' WHERE EXISTS (SELECT 1 FROM pg_database WHERE datname='$CONTROL_DB');
SQL
psql -d postgres -q -c "CREATE DATABASE $CONTROL_DB" 2>/dev/null || echo "   (control zaten var)"
psql -d postgres -q -c "CREATE DATABASE $SCHOOL_DB"

echo "== control semasi"
for f in "$BACKEND"/migrations/control/*.sql; do psql -d "$CONTROL_DB" -q -f - < "$f" 2>/dev/null || true; done

echo "== okul semasi (+ ZEKA)"
for f in "$BACKEND"/migrations/school/*.sql; do
    echo "   $(basename "$f")"
    psql -d "$SCHOOL_DB" -q -f - < "$f"
done

echo "== okul verisi"
podman cp "$SEED_DIR/pg_school.sql" "$CONTAINER:/tmp/pg_school.sql"
podman exec "$CONTAINER" psql -U "$PGUSER_" -d "$SCHOOL_DB" -q -v ON_ERROR_STOP=1 -f /tmp/pg_school.sql

echo "== control verisi (okul kaydi EN SON)"
psql -d "$CONTROL_DB" -q -f - < "$SEED_DIR/pg_control.sql"

echo "== butunluk sinavi (48 denetim)"
if [ -f "$SEED_DIR/pg_dogrula.sql" ]; then
    podman cp "$SEED_DIR/pg_dogrula.sql" "$CONTAINER:/tmp/pg_dogrula.sql"
    # ON_ERROR_STOP: bir denetim ihlal bulursa betik burada duser. Yuklendi
    # deyip bozuk veriyle devam etmek, hic yuklememekten kotudur.
    podman exec "$CONTAINER" psql -U "$PGUSER_" -d "$SCHOOL_DB" -q         -v ON_ERROR_STOP=1 -f /tmp/pg_dogrula.sql
else
    echo "   !! pg_dogrula.sql yok — tohum --postgres ile uretilmemis"
    exit 1
fi

echo
echo "== satir sayilari"
psql -d "$SCHOOL_DB" -tAc "SELECT 'okul: ' || sum(n_live_tup) FROM pg_stat_user_tables;"
psql -d "$CONTROL_DB" -tAc "SELECT 'control: ' || sum(n_live_tup) FROM pg_stat_user_tables;"
echo "== bitti"
