#!/usr/bin/env bash
# COMPOSE DENETIMI -- yapilandirmanin gecerli VE guvenli oldugunu dogrular.
#
# Uc sey denetlenir ve UCU DE cift yonludur; yalnizca "gecerli mi" diye
# sormak, asil kusurlari kacirir:
#
#   1. Zorunlu sirlar gercekten zorunlu mu?
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
if env -u AI_SHARED_TOKEN -u DEEPSEEK_API_KEY "${COMPOSE[@]}" config >/dev/null 2>&1; then
  kal "zorunlu sirlar olmadan gecti -- \${VAR:?} yerine \${VAR:-} yazilmis olabilir"
else
  gec "zorunlu sirlar olmadan REDDEDILDI (AI_SHARED_TOKEN / DEEPSEEK_API_KEY)"
fi

# --- 1b. zorunlu env VARKEN gecerli olmali --------------------------------
CIKTI="$(AI_SHARED_TOKEN=ci-sahte DEEPSEEK_API_KEY=ci-sahte "${COMPOSE[@]}" config 2>&1)"
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
  OZEL="$(HEZARFEN_NET=baska_ag AI_SHARED_TOKEN=x DEEPSEEK_API_KEY=x "${COMPOSE[@]}" config 2>/dev/null | grep -A2 '^networks:' | grep 'name:')"
  if echo "$OZEL" | grep -q 'baska_ag'; then
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
