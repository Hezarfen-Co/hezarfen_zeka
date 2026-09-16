#!/usr/bin/env bash
# ZEKA'nin dokuz tablosunu MEVCUT okul veritabanlarina ekler.
#
# NEDEN AYRI BIR BETIK GEREKIYOR
# ------------------------------
# Migration dosyasini `migrations/school/` altina koymak yeni okullari ve
# sablonu kapsar; HALIHAZIRDA DURAN okullari kapsamaz. Backend'in kendi
# kaynagi bunu acikca soyluyor (`database.rs:126`):
#
#     "The schema is the caller's business — migrate_school for a mint,
#      nothing for a re-dial of an existing school."
#
# Ve `reconcile_provisioning` yalnizca `provisioning` durumundaki okullara
# bakar. Yani sunucuda zaten duran bir okul, dosya eklense bile `zeka_*`
# tablolarini ASLA kendiliginden almaz. Bu betik o bosluğu kapatir.
#
# GUVENLI: yalnizca `CREATE TABLE`/`CREATE INDEX` calistirir, hicbir mevcut
# tabloya dokunmaz, hicbir satiri degistirmez. Tablolari zaten olan bir okulu
# ATLAR, ikinci kez uygulamaya calismaz.
#
#   tools/apply_zeka_tables.sh [migration-dosyasi]
#
# Ortam: HEZARFEN_PG_CONTAINER, POSTGRES_USER, POSTGRES_DB (control)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DDL="${1:-$HERE/service/schema/postgres/school/20260916000001_zeka.sql}"
CONTAINER="${HEZARFEN_PG_CONTAINER:-hezarfen_backend_postgres}"
PGUSER_="${POSTGRES_USER:-hezarfen}"
CONTROL_DB="${POSTGRES_DB:-hezarfen_control}"

[ -f "$DDL" ] || { echo "!! migration dosyasi yok: $DDL"; exit 1; }

psql() { podman exec -i "$CONTAINER" psql -U "$PGUSER_" -v ON_ERROR_STOP=1 "$@"; }

echo "== control: $CONTROL_DB"
echo "== ddl    : $(basename "$DDL")"
echo

# Okul veritabanlarini control'deki kutukten cozuyoruz, ad deseninden DEGIL:
# ad uuid'den turuyor ve desene guvenmek, kutukte olmayan bir veritabanina
# yazmak demek olabilirdi.
okullar="$(psql -d "$CONTROL_DB" -tAc \
  "SELECT '${CONTROL_DB}_school_' || replace(id::text, '-', '') || '|' || slug
     FROM school ORDER BY created_at")"

[ -n "$okullar" ] || { echo "kutukte okul yok — yapilacak bir sey yok"; exit 0; }

eklendi=0
atlandi=0
while IFS='|' read -r db slug; do
    [ -n "$db" ] || continue
    var="$(psql -d "$CONTROL_DB" -tAc \
        "SELECT count(*) FROM pg_database WHERE datname='$db'")"
    if [ "$var" = "0" ]; then
        echo "   $slug: veritabani yok ($db) — atlandi"
        atlandi=$((atlandi + 1))
        continue
    fi
    zaten="$(psql -d "$db" -tAc \
        "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname='public' AND c.relkind='r' AND c.relname LIKE 'zeka\\_%'")"
    if [ "$zaten" != "0" ]; then
        echo "   $slug: $zaten zeka_ tablosu zaten var — atlandi"
        atlandi=$((atlandi + 1))
        continue
    fi
    psql -d "$db" -q -f - < "$DDL"
    say="$(psql -d "$db" -tAc \
        "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname='public' AND c.relkind='r' AND c.relname LIKE 'zeka\\_%'")"
    echo "   $slug: $say tablo eklendi"
    eklendi=$((eklendi + 1))
done <<< "$okullar"

echo
echo "== $eklendi okula eklendi, $atlandi atlandi"
