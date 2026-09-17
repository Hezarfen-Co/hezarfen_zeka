#!/usr/bin/env bash
# KONTEYNER KOSU KANITI -- imajin DERLENDIGINI degil, KOSTUGUNU dogrular.
#
# NEDEN VAR: bu filoda yapilan denetimde kardes servis RAG'in konteynerinin hic
# ayaga kalkmadigi bulundu -- komut bir metin basip cikiyordu ve
# `restart: unless-stopped` ile sonsuz bir crash-loop'a giriyordu. "Derlendi"
# demek "kosuyor" demek DEGILDIR. Bu betik farki olcer.
#
# ---------------------------------------------------------------------------
# NEDEN VERITABANI YOK (ve bu neden kanitin KENDISI)
# ---------------------------------------------------------------------------
# Bu betik bir zamanlar kabi ayaga kaldirmak icin GERCEK bir Postgres kurardi:
# o zamanki servis acilista bir depo baglantisi aciyor ve adressiz kalirsa
# `RuntimeError` ile CIKIYORDU. O yol KALDIRILDI. ZEKA uygulama veritabanina
# ulasmaz (daimi kural): tek bagimliligi backend'in QUIC kopruSÜ. Backend
# YOKKEN dogru davranis cokmek degil, geri cekilerek yeniden denemektir.
#
# Bu yuzden kanit artik HICBIR DSN VERMEZ. Kabin acilmasi ve ayakta kalmasi
# basli basina "veritabani gerekmiyor" iddiasinin olcumudur: eksik bir
# zorunlu veritabani degiskeni olsaydi surec daha kopru dongusu baslamadan
# cikardi ve asagidaki iddialarin HEPSI bosluga dusardi.
#
# Dogrulanan bes sey:
#   1. Kap backend YOKKEN de ACILIYOR ve CIKMIYOR (geri cekilerek yeniden
#      deniyor) -- hicbir veritabani ortam degiskeni verilmeden.
#   2. Geri cekilme gercekten USTEL: bekleme suresi buyuyor.
#   3. Saglik kontrolu HEM gecer (kopru yasarken) HEM kalir (kopru yokken).
#   4. Surec NON-ROOT (uid 10002) kosuyor.
#   5. Kab sinirli bir pencere boyunca AYAKTA kaliyor.
#
# Kullanim: scripts/ci-konteyner-kanit.sh [podman|docker] [imaj]

set -uo pipefail

MOTOR="${1:-podman}"
IMAJ="${2:-hezarfen-zeka:ci}"
KAP="zeka-ci-kanit-$$"
GOZLEM_SANIYE="${GOZLEM_SANIYE:-50}"
# 50 sn: bir yeniden deneme turu, cozulemeyen DNS'in kendi zaman asimini da
# (config.CERT_FETCH_TIMEOUT_SECS = 10 sn) icerir. 30 sn ile olculdu ve
# pencereye YALNIZCA BIR deneme sigdi; ustel buyumeyi gormek icin en az iki
# deneme gerekir.

HATA=0
gec()  { echo "  [ok]   $1"; }
kal()  { echo "  [HATA] $1"; HATA=1; }

temizle() {
  MSYS_NO_PATHCONV=1 "$MOTOR" rm -f "$KAP" >/dev/null 2>&1 || true
}
trap temizle EXIT

echo "konteyner kosu kaniti: motor=$MOTOR imaj=$IMAJ"

# Backend'e BILEREK cozulemeyen bir ad veriyoruz: dogru davranis, cokmek degil
# geri cekilerek yeniden denemektir.
# `ZEKA_REFRESH_INTERVAL_SECS` ACIKCA 3600: varsayilan da 3600, ama kanit
# URETIM acilis yolunu (kopru + zamanlayici) kostursun diye yazili duruyor.
#
# DIKKAT: asagidaki ortam listesinde HICBIR veritabani degiskeni yoktur. Bu
# bilinclidir; basligin "neden veritabani yok" bolumune bakin.
MSYS_NO_PATHCONV=1 "$MOTOR" run -d --name "$KAP" \
  --health-cmd "python scripts/saglik.py" \
  --health-interval 10s --health-timeout 5s --health-start-period 5s --health-retries 3 \
  -e AI_SHARED_TOKEN=ci-sahte-token \
  -e ZEKA_REFRESH_INTERVAL_SECS=3600 \
  -e AI_BRIDGE_HOST=ulasilamaz.gecersiz \
  -e AI_BACKEND_URL=http://ulasilamaz.gecersiz:7656 \
  -e AI_RECONNECT_SECS=1 \
  -e AI_RECONNECT_MAX_SECS=8 \
  -e LOG_LEVEL=debug \
  "$IMAJ" >/dev/null || { echo "  [HATA] kap baslatilamadi"; exit 1; }

echo "  ... $GOZLEM_SANIYE saniye gozleniyor"
sleep "$GOZLEM_SANIYE"

# --- 1. hala kosuyor mu? --------------------------------------------------
DURUM="$(MSYS_NO_PATHCONV=1 "$MOTOR" inspect "$KAP" --format '{{.State.Status}}' 2>/dev/null)"
if [ "$DURUM" = "running" ]; then
  gec "kap $GOZLEM_SANIYE saniye sonra hala kosuyor (durum=$DURUM)"
else
  kal "kap kosmuyor (durum=$DURUM) -- RAG'in crash-loop kusuru tekrarlanmis olabilir"
  MSYS_NO_PATHCONV=1 "$MOTOR" logs "$KAP" 2>&1 | tail -30
fi

LOGLAR="$(MSYS_NO_PATHCONV=1 "$MOTOR" logs "$KAP" 2>&1)"

# --- 2. kopru yeniden deneme turu (veritabani YOKKEN) ---------------------
# Kanitin kalbi: hicbir depo adresi verilmedi, backend de yok. Beklenen tek
# davranis `run_forever`in geri cekilerek yeniden denemesidir. Bir depo
# baglantisi zorunlu olsaydi surec bu satiri HIC yazamazdi.
if echo "$LOGLAR" | grep -q "sonra yeniden denenecek"; then
  gec "veritabani OLMADAN kap acildi ve yeniden deneme turunu yazdi"
else
  kal "yeniden deneme kaydi yok -- kap daha kopru dongusu baslamadan cikmis olabilir"
  echo "$LOGLAR" | tail -20
fi

# --- 3. kalici red halinde bile cikmiyor mu? ------------------------------
if echo "$LOGLAR" | grep -q "yeniden denenecek"; then
  gec "backend ulasilamazken CIKMIYOR, yeniden deniyor (RAG kusurunun tersi)"
else
  kal "yeniden deneme kaydi yok"
fi

# --- 4. geri cekilme ustel mi? --------------------------------------------
# Log satiri: "[zeka] 3.5s sonra yeniden denenecek"
mapfile -t BEKLEMELER < <(echo "$LOGLAR" | grep -oE '[0-9]+\.[0-9]+s sonra yeniden denenecek' | grep -oE '^[0-9]+\.[0-9]+')
if [ "${#BEKLEMELER[@]}" -lt 2 ]; then
  kal "yeterli yeniden deneme gozlenmedi (${#BEKLEMELER[@]} adet); geri cekilme dogrulanamadi"
else
  ILK="${BEKLEMELER[0]}"
  SON="${BEKLEMELER[-1]}"
  if awk "BEGIN{exit !($SON > $ILK)}"; then
    gec "ustel geri cekilme gozlendi: ${ILK}s -> ${SON}s (${#BEKLEMELER[@]} deneme)"
  else
    kal "bekleme suresi buyumedi (${ILK}s -> ${SON}s); geri cekilme calismiyor olabilir"
  fi
fi

# --- 5. non-root mu? -------------------------------------------------------
KIMLIK="$(MSYS_NO_PATHCONV=1 "$MOTOR" exec "$KAP" id -u 2>/dev/null | tr -d '\r')"
if [ "$KIMLIK" = "0" ]; then
  kal "surec ROOT olarak kosuyor (uid=0)"
elif [ -n "$KIMLIK" ]; then
  gec "non-root dogrulandi (uid=$KIMLIK)"
else
  kal "uid okunamadi"
fi

# --- 6. saglik kontrolu: POZITIF -----------------------------------------
if MSYS_NO_PATHCONV=1 "$MOTOR" exec "$KAP" python scripts/saglik.py; then
  gec "saglik kontrolu kopru yasarken GECIYOR"
else
  kal "saglik kontrolu kopru yasarken kaldi"
fi

# --- 7. saglik kontrolu: NEGATIF -----------------------------------------
# Kanitin en onemli yarisi: her zaman 0 donen bir kontrol hicbir sey
# kanitlamaz. Kopru KOSMAYAN bir kapta kontrolun BASARISIZ olmasi gerekir.
if MSYS_NO_PATHCONV=1 "$MOTOR" run --rm "$IMAJ" python scripts/saglik.py >/dev/null 2>&1; then
  kal "saglik kontrolu kopru YOKKEN de gecti -- kontrol anlamsiz, her zaman 0 donuyor"
else
  gec "saglik kontrolu kopru yokken BASARISIZ oluyor (yani gercekten olcuyor)"
fi

# --- 8. motorun kendi saglik durumu --------------------------------------
SAGLIK="$(MSYS_NO_PATHCONV=1 "$MOTOR" inspect "$KAP" --format '{{.State.Health.Status}}' 2>/dev/null | tr -d '\r')"
if [ "$DURUM" != "running" ]; then
  # Olu bir kabin SON saglik damgasi 'healthy' kalabilir -- ona bakmak
  # yanlis bir "gecti" uretirdi. Once yasiyor olmali.
  kal "motor saglik durumu olculemez: kap kosmuyor (durum=$DURUM)"
elif [ "$SAGLIK" = "healthy" ]; then
  gec "motor kabi 'healthy' isaretledi"
else
  echo "  [not]  motor saglik durumu: '${SAGLIK:-yok}' (ilk aralik henuz dolmamis olabilir)"
fi

echo ""
if [ "$HATA" -eq 0 ]; then
  echo "KONTEYNER KOSU KANITI GECTI"
else
  echo "KONTEYNER KOSU KANITI BASARISIZ"
fi
exit "$HATA"
