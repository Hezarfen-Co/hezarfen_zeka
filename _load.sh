#!/bin/bash
DB=zeka
IMG=docker.io/surrealdb/surrealdb:v3
run() { MSYS_NO_PATHCONV=1 podman run --rm -i --network hzk --entrypoint /surreal $IMG \
  sql --endpoint http://hzk-surreal:8000 -u root -p root --namespace hezarfen --database "$1" --hide-welcome; }
START=$(date +%s)
for f in seed/0[1-9]_*.surql seed/1[0-2]_*.surql; do
  t0=$(date +%s)
  ERR=$(run $DB < "$f" 2>&1 | grep -icE "error|expected|failed" )
  t1=$(date +%s)
  printf "%-28s %5ss  hata_satiri=%s\n" "$(basename $f)" "$((t1-t0))" "$ERR"
done
echo "TOPLAM: $(( $(date +%s) - START )) saniye"
