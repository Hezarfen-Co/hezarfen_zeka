"""LLM tabanli soru segmentasyonu — bagimsiz alt sistem.

Bu paket `service/src/` altindaki mevcut ZEKA borusundan (config/protocol/bridge/
source/compute/store/pipeline/scheduler/cli) TAMAMEN AYRIDIR. Oradaki hicbir
dosyayi ice aktarmaz ve degistirmez; kendi yapilandirmasi, kendi CLI'si vardir.

TEK ISTISNA: `persist.py`. Segmentasyon ciktisinin bir yere yazilmasi gerekiyor
ve o koprunun bir yerde durmasi lazim; ayri bir modul olmasinin sebebi tam da
istisnayi GORUNUR kilmaktir. `runner.py` onu yalnizca `--persist` verildiginde
ve GEC ice aktarir; `labelers.py`, `validate.py`, `rubric.py` depo katmanindan
haberdar degildir. Yon tek taraflidir: `compute/` ve `store/` bu paketten
hicbir sey ice aktarmaz.

Amac: sinav sorularini bilissel boyutlara ayirmak ve bunu ogrenci cevap verisiyle
dogrulamak.

Tasarimin anayasasi `spec/ARASTIRMA-SEGMENTASYON.md` icindeki 11 dogrulanmis
bulgudur. Her esik ve tasarim karari yorumda "bulgu N" ile kaynagina baglanir.

Asama sirasi (bulgu 11 — cikarimsal protokol):
  Asama 0  kararlilik (intra/inter-PSS, Krippendorff alpha)   -> KAPI
  Asama 1  tek modelli taban cizgi (zorunlu kontrol grubu)
  Asama 2  cok ajanli varyantlar, ESIT TOKEN BUTCESINDE
  Asama 3  A/B karsilastirma + karar kurali
  Asama 4  ogrenci tarafi (ayri ve durust)

ONEMLI METODOLOJIK KAYIT (tohum verisine ozgu):
  Tohum uretecinde soru METNI ile ZORLUK birbirinden BAGIMSIZ uretilmistir
  (`spec/SENARYO.md` §4.2/§4.4: b_i once bant oranlarina gore cekilir, metin
  ureticisine bu bilgi hic verilmez). Bu nedenle LLM etiketlerini `p_value` ile
  korele etmek bu veride GECERSIZDIR — sifir korelasyon cikar ve yontem hakkinda
  hicbir sey soylemez. `validate.py` bu olcumu hesaplarsa bile daima
  `gecerli=False` / "bu veride anlamsiz" olarak isaretler.

  Gecerli olan tek soru-tarafi hedef: 741 maddede `content_tr.py` icindeki
  MISCONCEPTIONS tablosundan gelen GERCEK anlamsal kavram yanilgisi celdiricisi
  vardir; `gold.misconception_choice_text` tam olarak o sikki gosterir. Kalan
  ~3.637 madde temiz negatiftir.
"""

from .schema import (  # noqa: F401
    DIMENSIONS,
    DimensionResult,
    ItemSegmentation,
    SchemaError,
    parse_label_json,
)

__all__ = [
    "DIMENSIONS",
    "DimensionResult",
    "ItemSegmentation",
    "SchemaError",
    "parse_label_json",
]
