#!/usr/bin/env bash
# CI'nin YEREL esdegeri -- GitHub Actions ile AYNI katmanlari ayni sirada kosar.
#
# NEDEN VAR: depo su an GitHub'da olmayabilir. Yalnizca `.github/workflows/`
# yazmak, kimsenin kosturamadigi bir CI demektir. Bu betik tek dogruluk
# kaynagidir: is akislari da bunun kosturdugu ayni komutlari cagirir, boylece
# "yerelde geciyordu ama CI'da kaldi" ayrismasi olusmaz.
#
# Kullanim:
#   scripts/ci-yerel.sh            # konteyner haric butun katmanlar
#   scripts/ci-yerel.sh --konteyner  # konteyner derlemesi + kosu kaniti dahil
#   scripts/ci-yerel.sh --hizli      # yalnizca sozdizimi + testler
#
# Cikis kodu 0 = butun katmanlar gecti.

set -uo pipefail

KOK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVIS="$KOK/service"
PYTHON="${PYTHON:-python}"

KONTEYNER=0
HIZLI=0
for arg in "$@"; do
  case "$arg" in
    --konteyner) KONTEYNER=1 ;;
    --hizli) HIZLI=1 ;;
    -h|--help) sed -n '2,18p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "bilinmeyen secenek: $arg" >&2; exit 2 ;;
  esac
done

BASARISIZ=()

katman() {
  # katman <ad> <aciklama> -- sonraki komutlar bu baslik altinda kosar
  echo ""
  echo "=================================================================="
  echo "KATMAN: $1"
  echo "  ne denetler: $2"
  echo "=================================================================="
}

kosu() {
  local ad="$1"; shift
  if "$@"; then
    echo ">>> $ad: GECTI"
  else
    echo ">>> $ad: BASARISIZ"
    BASARISIZ+=("$ad")
  fi
}

# --------------------------------------------------------------------------
katman "1/5 sozdizimi" \
  "her .py dosyasi ayristirilabiliyor mu (bozuk bir dosya testlerden once yakalanir)"
# `compileall -q` yalnizca hatalari basar. `-x` ile onbellek ve sanal ortam
# disarida: orada bizim olmayan kod da bulunabilir.
kosu "sozdizimi" "$PYTHON" -m compileall -q -x '(__pycache__|\.venv|venv)' \
  "$SERVIS/src" "$SERVIS/tests" "$KOK/scripts"

# --------------------------------------------------------------------------
katman "2/5 testler" \
  "375+ birim testi; saf unittest, HICBIR bagimlilik gerektirmez"
# `-t .` onemli: test kokunu servise sabitler, `src.` import'lari boylece cozulur.
#
# `set -o pipefail` ICERIDE: `bash -c` yeni bir kabuk acar ve dis script'in
# `pipefail` secenegi oraya GECMEZ. Onsuz boru hattinin cikis durumu `tail`in
# durumudur -- yani 686 testten 3'u patlarken bile bu satir GECTI basardi
# (olculdu: `Ran 686 tests ... FAILED`, katman yine yesil). Yesil gorunen ama
# olcmeyen kapi, kapi degildir.
kosu "birim testleri" bash -c "set -o pipefail; cd '$SERVIS' && '$PYTHON' -m unittest discover -s tests -t . -v 2>&1 | tail -20"

if [ "$HIZLI" -eq 1 ]; then
  echo ""
  echo "--hizli: kalan katmanlar atlandi."
else

# --------------------------------------------------------------------------
katman "3/5 sozlesme" \
  "model adlari fiyat tablosunda mi; source.py yollari backend izin listesiyle ayni mi"
kosu "sozlesme denetimi" "$PYTHON" "$KOK/scripts/ci-sozlesme.py"

# --------------------------------------------------------------------------
katman "4/5 sir taramasi" \
  "depoya sizmis API anahtari / parola; compose sirlarinin zorunlu ve interpolasyonlu olmasi"
kosu "sir taramasi" "$PYTHON" "$KOK/scripts/ci-sir-tara.py"

fi

# --------------------------------------------------------------------------
if [ "$KONTEYNER" -eq 1 ]; then
  katman "5/5 konteyner" \
    "imaj gercekten derleniyor mu; kap cikmadan kosuyor mu; non-root mu; saglik kontrolu geciyor mu"
  if command -v podman >/dev/null 2>&1; then
    MOTOR=podman
  elif command -v docker >/dev/null 2>&1; then
    MOTOR=docker
  else
    echo ">>> konteyner: ATLANDI (podman/docker bulunamadi)"
    MOTOR=""
  fi
  if [ -n "$MOTOR" ]; then
    kosu "imaj derlemesi" bash -c \
      "cd '$SERVIS' && MSYS_NO_PATHCONV=1 $MOTOR build -t hezarfen-zeka:ci -f Containerfile ."
    kosu "kosu kaniti" bash -c "'$KOK/scripts/ci-konteyner-kanit.sh' '$MOTOR' hezarfen-zeka:ci"
    kosu "compose denetimi" bash -c "'$KOK/scripts/ci-compose.sh'"
  fi
else
  echo ""
  echo "(konteyner katmani atlandi -- dahil etmek icin: scripts/ci-yerel.sh --konteyner)"
fi

# --------------------------------------------------------------------------
echo ""
echo "=================================================================="
if [ ${#BASARISIZ[@]} -eq 0 ]; then
  echo "BUTUN KATMANLAR GECTI"
  exit 0
fi
echo "BASARISIZ KATMANLAR (${#BASARISIZ[@]}):"
for ad in "${BASARISIZ[@]}"; do echo "  - $ad"; done
exit 1
