#!/usr/bin/env bash
# COMPOSE DENETIMI -- yapilandirmanin gecerli VE guvenli oldugunu dogrular.
#
# Dort sey denetlenir ve DORDU DE cift yonludur; yalnizca "gecerli mi" diye
# sormak, asil kusurlari kacirir:
#
#   1. Zorunlu sirlar gercekten zorunlu mu? LISTE compose.yaml'DAN OKUNUR
#      (`${VAR:?}` ile gecen her degisken). `${VAR:?}` yerine `${VAR:-}`
#      yazilirsa compose yine gecerli olur ama servis bos bir token'la ayaga
#      kalkar ve backend'e kaydolamaz. Bu yuzden env YOKKEN `config`in
#      PATLAMASINI da sinariz. Liste elle yazilmaz: sir ekleyen kisi bu
#      betigi de guncellemek zorunda kalmasin (bu tam olarak bir kez yasandi).
#
#   2. Port aciliyor mu? ACILMAMALI. ZEKA backend'in QUIC'ine DIAL-OUT eden
#      bir istemcidir (`ai/protocol.rs:3-7`); port acmak NAT ardinda
#      yasamasini engeller ve gereksiz bir saldiri yuzeyi acar.
#
#   3. Ag adi parametrik mi? Kardes serviste sabit yazildigi icin ag baska
#      bir adla kuruldugunda compose patliyordu.
#
#   4. VERITABANI IZI YOK MU? ZEKA uygulama veritabanina ULASMAZ (daimi
#      kural): ne bir DSN, ne bir veritabani parolasi. Ayrica
#      `env_file:` de YASAK -- operator ayarlari ORTAMDAN gelir; deploy
#      tarafi TEK bir `--env-file` (stack.env) verir ve bu saglayicida ikinci
#      dosya zaten sessizce duser (podman_compose.py:2941-2946, :2559).

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

# --- zorunlu sirlar: LISTE compose.yaml'DAN OKUNUR -------------------------
mapfile -t SIRLAR < <(
  grep -oE '\$\{[A-Za-z_][A-Za-z0-9_]*:\?' compose.yaml \
    | sed -E 's/^\$\{//; s/:\?$//' | sort -u
)
if [ "${#SIRLAR[@]}" -eq 0 ]; then
  kal "compose.yaml hicbir sirri \${VAR:?} ile zorunlu tutmuyor"
fi

EKSIK=()
for degisken in "${SIRLAR[@]}"; do EKSIK+=(-u "$degisken"); done

# --- 1a. zorunlu env EKSIKKEN patlamali -----------------------------------
if env "${EKSIK[@]}" "${COMPOSE[@]}" config >/dev/null 2>&1; then
  kal "zorunlu sirlar olmadan gecti -- \${VAR:?} yerine \${VAR:-} yazilmis olabilir"
else
  gec "zorunlu sirlar olmadan REDDEDILDI (${SIRLAR[*]})"
fi

# --- 1b. zorunlu env VARKEN gecerli olmali --------------------------------
DOLU=()
for degisken in "${SIRLAR[@]}"; do DOLU+=("$degisken=ci-sahte"); done

if ! CIKTI="$(env "${DOLU[@]}" "${COMPOSE[@]}" config 2>&1)"; then
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
  OZEL="$(env HEZARFEN_NET=baska_ag "${DOLU[@]}" "${COMPOSE[@]}" config 2>/dev/null \
          | grep -E '^[[:space:]]+name:[[:space:]]*baska_ag[[:space:]]*$' | head -1)"
  if [ -n "$OZEL" ]; then
    gec "HEZARFEN_NET gecersiz kilinabiliyor (test: baska_ag ->$OZEL)"
  else
    kal "HEZARFEN_NET gecersiz kilinamadi; parametre ise yaramiyor"
  fi
else
  kal "dis ag adi SABIT yazilmis; dagitimdan dagitima kirilir"
fi

# --- 4a. veritabani izi yok ------------------------------------------------
# Adlar yazilmaz, DESEN aranir: hangi DSN/parola adiyla gelirse gelsin yakalanir.
if grep -nEi 'postgres|PG_DSN|_DB_DSN|ZEKA_DB' compose.yaml; then
  kal "compose.yaml'da veritabani izi var; ZEKA uygulama veritabanina ULASMAZ"
else
  gec "compose.yaml'da DSN/parola izi yok (kopru deposu)"
fi

# --- 4b. `env_file:` yok: operator ayarlari TEK kanaldan --------------------
if grep -qE '^[[:space:]]+env_file:' compose.yaml; then
  kal "compose env_file: kullaniyor; operator ayarlari ORTAMDAN gelmeli (deploy TEK --env-file verir)"
else
  gec "compose env_file: kullanmiyor (ayarlar ortamdan, tek --env-file deploy tarafinda)"
fi

echo ""
[ "$HATA" -eq 0 ] && echo "COMPOSE DENETIMI GECTI" || echo "COMPOSE DENETIMI BASARISIZ"
exit "$HATA"
