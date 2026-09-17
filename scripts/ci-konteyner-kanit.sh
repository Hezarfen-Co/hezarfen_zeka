#!/usr/bin/env bash
# KONTEYNER KOSU KANITI -- imajin DERLENDIGINI degil, KOSTUGUNU dogrular.
#
# NEDEN VAR: bu filoda yapilan denetimde kardes servis RAG'in konteynerinin hic
# ayaga kalkmadigi bulundu -- komut bir metin basip cikiyordu ve
# `restart: unless-stopped` ile sonsuz bir crash-loop'a giriyordu. "Derlendi"
# demek "kosuyor" demek DEGILDIR. Bu betik farki olcer.
#
# Dogrulanan bes sey:
#   1. Kap backend YOKKEN de CIKMIYOR (geri cekilerek yeniden deniyor).
#   1b. Kap ZORUNLU UC ORTAM DEGISKENIYLE gercekten ACILIYOR ve depo baglantisi
#       kuruluyor (bkz. asagidaki "neden gercek Postgres").
#   2. Geri cekilme gercekten USTEL: bekleme suresi buyuyor.
#   3. Surec NON-ROOT (uid 10002) kosuyor.
#   4. Saglik kontrolu HEM gecer (kopru yasarken) HEM kalir (kopru yokken).
#
# ---------------------------------------------------------------------------
# NEDEN GERCEK POSTGRES (ve bir adet YEREL AG)
# ---------------------------------------------------------------------------
# Bu betik bir zamanlar kabi YALNIZCA `AI_*` ile kaldiriyordu. `compose.yaml`
# ise uc sirri `${VAR:?}` ile ZORUNLU tutar (AI_SHARED_TOKEN, ZEKA_PG_DSN,
# DEEPSEEK_API_KEY) ve servis acilista `open_store()` cagirir: DSN yoksa
# `RuntimeError` ile CIKAR. Sonuc: kap hemen oluyor, ardindan gelen HER
# iddia -- uid, geri cekilme, saglik kontrolu -- bosluga dusuyordu ve
# yalnizca "kopru yokken kontrol kalir" gecip (o da hicbir sey kosmadigi icin)
# kirmizi bir kanit uretiyordu. Iki surumde de ayni imza:
#   RuntimeError: Ne ZEKA_PG_DSN ne ZEKA_DB_HTTP_URL tanimli...
#
# DUZ METIN BIR DSN YETMEZ: sahte ama ULASILAMAZ bir DSN de ayni yerde patlar
# (psycopg baglanamaz). Bu yuzden kanit gercek bir Postgres kaldirir, kendi
# agina koyar ve kaba ULASILABILIR bir DSN verir. Boylece kanit, servisin
# URETIMDEKI acilis yolunu (depo acilisi + zamanlayici) olcer; "env'i gectim,
# calisti sayilir" demez.
#
# Kullanim: scripts/ci-konteyner-kanit.sh [podman|docker] [imaj]

set -uo pipefail

MOTOR="${1:-podman}"
IMAJ="${2:-hezarfen-zeka:ci}"
KAP="zeka-ci-kanit-$$"
PG_KAP="zeka-ci-pg-$$"
AG="zeka-ci-ag-$$"
# Aile imaji: backend compose'u da bunu kullaniyor (compose.yaml:20).
PG_IMAJ="${PG_IMAJ:-docker.io/library/postgres:18-alpine}"
GOZLEM_SANIYE="${GOZLEM_SANIYE:-50}"
# 50 sn: bir yeniden deneme turu, cozulemeyen DNS'in kendi zaman asimini da
# (config.CERT_FETCH_TIMEOUT_SECS = 10 sn) icerir. 30 sn ile olculdu ve
# pencereye YALNIZCA BIR deneme sigdi; ustel buyumeyi gormek icin en az iki
# deneme gerekir.

HATA=0
gec()  { echo "  [ok]   $1"; }
kal()  { echo "  [HATA] $1"; HATA=1; }

temizle() {
  "$MOTOR" rm -f "$KAP" >/dev/null 2>&1 || true
  "$MOTOR" rm -f "$PG_KAP" >/dev/null 2>&1 || true
  "$MOTOR" network rm "$AG" >/dev/null 2>&1 || true
}
trap temizle EXIT

echo "konteyner kosu kaniti: motor=$MOTOR imaj=$IMAJ"

# --- 0. gercek Postgres: zorunlu env'in ve acilis yolunun ta kendisi --------
MSYS_NO_PATHCONV=1 "$MOTOR" network create "$AG" >/dev/null 2>&1 \
  || { echo "  [HATA] kanit agi kurulamadi ($AG)"; exit 1; }
MSYS_NO_PATHCONV=1 "$MOTOR" run -d --name "$PG_KAP" --network "$AG" \
  -e POSTGRES_PASSWORD=ci-sahte -e POSTGRES_DB=ci \
  "$PG_IMAJ" >/dev/null || { echo "  [HATA] Postgres kaldirilamadi"; exit 1; }

pg_hazir=0
for _ in $(seq 1 60); do
  if MSYS_NO_PATHCONV=1 "$MOTOR" exec "$PG_KAP" pg_isready -U postgres -d ci >/dev/null 2>&1; then
    pg_hazir=1
    break
  fi
  sleep 1
done
if [ "$pg_hazir" -ne 1 ]; then
  echo "  [HATA] Postgres hazir olmadi ($PG_IMAJ); kanit calistirilamaz" >&2
  MSYS_NO_PATHCONV=1 "$MOTOR" logs "$PG_KAP" >&2 || true
  exit 1
fi
# IP ile baglaniyoruz, konteyner adiyla DEGIL: ad cozumu netavark DNS'ine
# bagli, IP ise agin kendisinden geliyor -- kanit DNS aksakligina takilmasin.
PG_IP="$(MSYS_NO_PATHCONV=1 "$MOTOR" inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$PG_KAP" | tr -d '\r')"
if [ -z "$PG_IP" ]; then
  echo "  [HATA] Postgres IP'si okunamadi" >&2
  exit 1
fi
DSN="postgres://postgres:ci-sahte@$PG_IP:5432/ci"
gec "kanit Postgres'i ayakta (adres $PG_IP, sifre kaynakta gizli degil: atil bir kanit kabi)"

# Backend'e BILEREK cozulemeyen bir ad veriyoruz: dogru davranis, cokmek degil
# geri cekilerek yeniden denemektir. `ZEKA_PG_DSN` artik GERCEK ve
# ULASILABILIR: compose'un ZORUNLU UCUNCU siri budur ve bu satir olmadan
# servis acilista cikar (yukaridaki baslik yorumu).
# `ZEKA_REFRESH_INTERVAL_SECS` ACIKCA 3600: varsayilan da 3600, ama kanit
# URETIM acilis yolunu (depo + zamanlayici) kostursun diye yazili duruyor.
MSYS_NO_PATHCONV=1 "$MOTOR" run -d --name "$KAP" \
  --network "$AG" \
  --health-cmd "python scripts/saglik.py" \
  --health-interval 10s --health-timeout 5s --health-start-period 5s --health-retries 3 \
  -e AI_SHARED_TOKEN=ci-sahte-token \
  -e ZEKA_PG_DSN="$DSN" \
  -e ZEKA_REFRESH_INTERVAL_SECS=3600 \
  -e ZEKA_SCHOOLS=hezarfen-demo \
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

# --- 1b. ZORUNLU ENV: kap GERCEKTEN acildi mi, DEPO aciliyor mu? -----------
# `ZEKA_PG_DSN` verilmemis ya da ulasilamaz olsaydi surec daha kopru dongusu
# baslamadan `RuntimeError`/baglanti hatasi ile cikardi (bkz. baslik yorumu:
# `_serve` once `open_store()` cagirir). Bu iki iddia o boslukla "servis o
# env ile ACILIYOR ve depo ACILIYOR" arasindaki farki olcer.
#
# NOT: `pg_client`'in "okul veritabanina baglanildi" satiri ARANMAZ cunku
# kopru sureci logging'i yapilandirmaz (yalnizca `cli.py` basicConfig yapar);
# o modul-logger INFO satiri hicbir yere basilmaz. Aranan satir koprunun
# KENDI actigi acilis satiridir (`[zeka] depo: PostgreSQL (...)`).
if echo "$LOGLAR" | grep -q "depo: PostgreSQL"; then
  gec "ZEKA_PG_DSN kabul edildi: kopru Postgres yolunu secti (acilis satiri logda)"
else
  kal "kopru Postgres yolunu secmedi -- zorunlu env eksik/yanlis olabilir"
fi

# Kopru surecinin KENDI icinden depo yolunu bir kez daha aciyoruz: "env'i
# gectim" degil, "O env ile depo ACILIYOR" kaniti budur (ayni `open_store`).
DEPO_CIKTI="$(MSYS_NO_PATHCONV=1 "$MOTOR" exec -i "$KAP" python - 2>&1 <<'PY'
import asyncio

from src.store_factory import open_store


async def main() -> None:
    _store, db = await open_store()
    await db.close()
    print("DEPO_ACILDI")


asyncio.run(main())
PY
)"
case "$DEPO_CIKTI" in
  *DEPO_ACILDI*) gec "zorunlu env ile depo GERCEKTEN aciliyor (open_store -> kapat)" ;;
  *) kal "depo acilamadi: $(echo "$DEPO_CIKTI" | tail -2 | tr '\n' ' ')" ;;
esac

# --- 2. geri cekilme ustel mi? --------------------------------------------
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

# --- 3. kalici red halinde bile cikmiyor mu? ------------------------------
if echo "$LOGLAR" | grep -q "yeniden denenecek"; then
  gec "backend ulasilamazken CIKMIYOR, yeniden deniyor (RAG kusurunun tersi)"
else
  kal "yeniden deneme kaydi yok"
fi

# --- 4. non-root mu? -------------------------------------------------------
KIMLIK="$(MSYS_NO_PATHCONV=1 "$MOTOR" exec "$KAP" id -u 2>/dev/null | tr -d '\r')"
if [ "$KIMLIK" = "0" ]; then
  kal "surec ROOT olarak kosuyor (uid=0)"
elif [ -n "$KIMLIK" ]; then
  gec "non-root dogrulandi (uid=$KIMLIK)"
else
  kal "uid okunamadi"
fi

# --- 5. saglik kontrolu: POZITIF -----------------------------------------
if MSYS_NO_PATHCONV=1 "$MOTOR" exec "$KAP" python scripts/saglik.py; then
  gec "saglik kontrolu kopru yasarken GECIYOR"
else
  kal "saglik kontrolu kopru yasarken kaldi"
fi

# --- 6. saglik kontrolu: NEGATIF -----------------------------------------
# Kanitin en onemli yarisi: her zaman 0 donen bir kontrol hicbir sey
# kanitlamaz. Kopru KOSMAYAN bir kapta kontrolun BASARISIZ olmasi gerekir.
if MSYS_NO_PATHCONV=1 "$MOTOR" run --rm "$IMAJ" python scripts/saglik.py >/dev/null 2>&1; then
  kal "saglik kontrolu kopru YOKKEN de gecti -- kontrol anlamsiz, her zaman 0 donuyor"
else
  gec "saglik kontrolu kopru yokken BASARISIZ oluyor (yani gercekten olcuyor)"
fi

# --- 7. motorun kendi saglik durumu --------------------------------------
SAGLIK="$(MSYS_NO_PATHCONV=1 "$MOTOR" inspect "$KAP" --format '{{.State.Health.Status}}' 2>/dev/null | tr -d '\r')"
if [ "$SAGLIK" = "healthy" ]; then
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
