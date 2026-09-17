#!/usr/bin/env bash
# COMPOSE DENETIMI -- yapilandirmanin gecerli VE guvenli oldugunu dogrular.
#
# Uc sey denetlenir ve UCU DE cift yonludur; yalnizca "gecerli mi" diye
# sormak, asil kusurlari kacirir:
#
#   1. Zorunlu sirlar gercekten zorunlu mu? (AI_SHARED_TOKEN, DEEPSEEK_API_KEY,
#      ZEKA_PG_DSN -- tam liste compose.yaml'da.)
#      `${VAR:?}` yerine `${VAR:-}` yazilirsa compose yine gecerli olur ama
#      servis bos bir token'la ayaga kalkar ve backend'e kaydolamaz. Bu
#      yuzden env YOKKEN `config`in PATLAMASINI da sinariz.
#
#   2. Port aciliyor mu? ACILMAMALI. ZEKA backend'in QUIC'ine DIAL-OUT eden
#      bir istemcidir (`ai/protocol.rs:3-7`); port acmak NAT ardinda
#      yasamasini engeller ve gereksiz bir saldiri yuzeyi acar.
#
#   3. Ag adi parametrik mi? Kardes serviste sabit yazildigi icin ag baska
#      bir adla kuruldugunda compose patliyordu.

set -uo pipefail

KOK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVIS="$KOK/service"

# `podman compose` bu makinede docker-compose'a devrediyor; ikisi de yoksa
# denetim atlanir (yalan soylemek yerine atladigini soyler).
if command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then
  COMPOSE=(podman compose)
elif command -v docker >/dev/null 2>&1; then
  COMPOSE=(docker compose)
else
  echo "  [not]  compose bulunamadi; denetim ATLANDI"
  exit 0
fi

cd "$SERVIS" || exit 1
HATA=0
gec() { echo "  [ok]   $1"; }
kal() { echo "  [HATA] $1"; HATA=1; }

# --- 1a. zorunlu env EKSIKKEN patlamali -----------------------------------
# ZORUNLU SIRLAR LISTESI compose.yaml'DAN OKUNUR -- su an uctur
# (AI_SHARED_TOKEN, DEEPSEEK_API_KEY, ZEKA_PG_DSN). Ucuncusu eklendiginde bu
# betik ve `ci.yml`'in konteyner katmani iki sirla kalmis, ikisi de "sirlar
# verilse bile patliyor" diyerek KIRMIZI kalmisti. Sir eklerseniz bu listeyi
# ve ci.yml/main.yml adimini BIRLIKTE guncelleyin.
if env -u AI_SHARED_TOKEN -u DEEPSEEK_API_KEY -u ZEKA_PG_DSN \
     "${COMPOSE[@]}" config >/dev/null 2>&1; then
  kal "zorunlu sirlar olmadan gecti -- \${VAR:?} yerine \${VAR:-} yazilmis olabilir"
else
  gec "zorunlu sirlar olmadan REDDEDILDI (AI_SHARED_TOKEN / DEEPSEEK_API_KEY / ZEKA_PG_DSN)"
fi

# --- 1b. zorunlu env VARKEN gecerli olmali --------------------------------
ZORUNLU_ENV=(AI_SHARED_TOKEN=ci-sahte DEEPSEEK_API_KEY=ci-sahte ZEKA_PG_DSN=postgres://ci:ci@127.0.0.1:5432/ci)
CIKTI="$(env "${ZORUNLU_ENV[@]}" "${COMPOSE[@]}" config 2>&1)"
if [ $? -ne 0 ]; then
  kal "zorunlu sirlar verildiginde bile config basarisiz:"
  echo "$CIKTI" | tail -10
  exit 1
fi
gec "zorunlu sirlar verildiginde gecerli yapilandirma uretiyor"

# --- 2. port acilmamali ----------------------------------------------------
if echo "$CIKTI" | grep -qE '^\s+ports:'; then
  kal "compose PORT ACIYOR; ZEKA dial-out eden bir istemcidir, port ACMAZ"
else
  gec "hicbir port yayimlanmiyor (disa arama servisi)"
fi

# --- 3. ag adi parametrik mi ----------------------------------------------
if grep -q 'name: ${HEZARFEN_NET:-' compose.yaml; then
  gec "dis ag adi parametrik: \${HEZARFEN_NET:-hezarfen_backend_default}"
  # SIRA BAGIMSIZ arama: `networks:` blogunda anahtar sirasi saglayiciya gore
  # degisir (podman-compose `external`i `name`den ONCE basar). Ilk surum
  # `grep -A2 '^networks:'` ile pencere aciyordu ve ad satirini kacirip HATA
  # veriyordu -- probe'un kendisi yanlisti, yapilandirma degil.
  OZEL="$(env HEZARFEN_NET=baska_ag "${ZORUNLU_ENV[@]}" "${COMPOSE[@]}" config 2>/dev/null \
          | grep -E '^[[:space:]]+name:[[:space:]]*baska_ag[[:space:]]*$' | head -1)"
  if [ -n "$OZEL" ]; then
    gec "HEZARFEN_NET gecersiz kilinabiliyor (test: baska_ag ->$OZEL)"
  else
    kal "HEZARFEN_NET gecersiz kilinamadi; parametre ise yaramiyor"
  fi
else
  kal "dis ag adi SABIT yazilmis; dagitimdan dagitima kirilir"
fi

echo ""
[ "$HATA" -eq 0 ] && echo "COMPOSE DENETIMI GECTI" || echo "COMPOSE DENETIMI BASARISIZ"
exit "$HATA"
