# ZEKA -- gelistirme ve CI hedefleri.
#
# CI'nin yerel esdegeri buradan kosturulur. `.github/workflows/ci.yml` ile
# AYNI komutlari cagirir; depo GitHub'da olmasa bile butun denetimler
# kosturulabilir olsun diye. Tek dogruluk kaynagi `scripts/` altindaki
# betiklerdir -- hem Makefile hem is akislari onlari cagirir, boylece ikisi
# ayrisamaz.
#
# `make` yoksa betikler dogrudan da kosturulabilir:
#   bash scripts/ci-yerel.sh --konteyner

SHELL := /bin/bash
PYTHON ?= python
MOTOR ?= podman
IMAJ ?= hezarfen-zeka:dev

.DEFAULT_GOAL := yardim

.PHONY: yardim ci ci-hizli testler sozdizimi sozlesme sirlar derle kanit compose kos loglar dur temizle

yardim:  ## Hedefleri listele
	@echo "ZEKA hedefleri:"
	@echo ""
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Degiskenler: PYTHON=$(PYTHON) MOTOR=$(MOTOR) IMAJ=$(IMAJ)"

# --- butun CI --------------------------------------------------------------

ci:  ## CI'nin tamami (konteyner katmani dahil) -- is akislariyla ayni
	bash scripts/ci-yerel.sh --konteyner

ci-hizli:  ## Yalnizca sozdizimi + testler (saniyeler icinde)
	bash scripts/ci-yerel.sh --hizli

# --- tek tek katmanlar -----------------------------------------------------

sozdizimi:  ## Katman 1: her .py ayristirilabiliyor mu
	$(PYTHON) -m compileall -q -x '(__pycache__|\.venv|venv)' service/src service/tests scripts

testler:  ## Katman 2: birim testleri (saf unittest, bagimliliksiz)
	cd service && $(PYTHON) -m unittest discover -s tests -t .

sozlesme:  ## Katman 3: model<->fiyat ve yol<->izin listesi sozlesmeleri
	$(PYTHON) scripts/ci-sozlesme.py

sirlar:  ## Katman 4: sizmis API anahtari taramasi
	$(PYTHON) scripts/ci-sir-tara.py

# --- konteyner -------------------------------------------------------------

derle:  ## Imaji derle
	cd service && MSYS_NO_PATHCONV=1 $(MOTOR) build -t $(IMAJ) -f Containerfile .

kanit: derle  ## Kap gercekten kosuyor mu: cikmiyor, non-root, saglik kontrolu olcuyor
	bash scripts/ci-konteyner-kanit.sh $(MOTOR) $(IMAJ)

compose:  ## compose.yaml gecerli mi; zorunlu sirlar zorunlu mu; port acik mi
	bash scripts/ci-compose.sh

# --- gunluk kullanim -------------------------------------------------------

kos:  ## Servisi compose ile kaldir (zorunlu: AI_SHARED_TOKEN, LLM_API_KEY)
	cd service && $(MOTOR) compose up -d

loglar:  ## Servis gunluklerini izle
	cd service && $(MOTOR) compose logs -f

dur:  ## Servisi durdur
	cd service && $(MOTOR) compose down

temizle:  ## Derleme artiklarini ve gecici kaplari sil
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	-$(MOTOR) rm -f $$($(MOTOR) ps -aq --filter "name=zeka-ci-kanit") 2>/dev/null
