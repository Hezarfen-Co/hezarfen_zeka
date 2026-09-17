"""ZEKA'nin ilan edecegi yetenekler ve payload sozlesmeleri.

IKI YON VARDIR; karistirilmamalidir:

1. **Sunucu-baslatimli (backend -> ZEKA).** Backend'in ZEKA'ya `Request`
   gondermesi icin asagidaki adlari DAGITIM tablosunda tanimasi gerekir.
   Bugun backend'in cagirabildigi tek iki ad `chat.reply` ve `rag.index`'tir
   (`constant.rs:568` ve `constant.rs:574`); asagidaki `insight.*` adlarinin
   hicbiri orada YOKTUR. Yonlendirme TAM ESLESME iledir (`ai/protocol.rs:91-94`,
   `ai/registry.rs`): ZEKA baglanip bu adlari ilan etse bile backend onlara
   hicbir `Request` gondermez. Bu yon HALA ACIKTIR. Kopru tarafi (`bridge.py`)
   gelen cerceveleri karsilamaya hazirdir ki backend bu adlari tanidigi gun
   tek satir degisiklik gereksin.

2. **Istemci-baslatimli (ZEKA -> backend, depo yolu).** ZEKA'nin kendi `zeka_*`
   satirlarini yazip okudugu yol budur: `store.BridgeStore`,
   `BridgeProtocol.call_capability` ile `insight.schools.list`,
   `insight.pending.list`, `insight.retention.sweep` gibi operasyonlari cagirir.
   Bu yon backend'de 2026-09-17'de ACILDI (f84c29d) ve calisir.
   `BACKEND_CALLABLE_CAPABILITIES` kumesi onu KAPSAMAZ: o kume yalnizca 1. yonu,
   yani backend'in cagirabildigi adlari anlatir.

Bu dosya 1. yon icin **sozlesme**dir (calisan bir yol degil); 2. yonun
sozlesmesi `store.py` ve `protocol.py` icindedir.

Gereksinim backend ekibine `docs/BACKEND-GEREKSINIMLERI.md` madde 1 ile
iletilir.

--- ilan disi kullanim ----------------------------------------------------
`insight.refresh` ayrica ZEKA'nin KENDI zamanlayicisi tarafindan da cagrilir
(`config.ZEKA_REFRESH_INTERVAL_SECS`). Yani hesaplar backend cagirmasa da
kosar; backend'in yetenegi tanimasi yalnizca "istege bagli tetikleme"yi acar.
"""

from __future__ import annotations

from typing import Any, Callable, TypedDict

from .protocol import CapabilityError

# --- yetenek adlari --------------------------------------------------------
# Ad alani `<servis>.<eylem>` desenini izler; backend'in `chat.reply` ve
# `rag.index` adlari da boyledir.

INSIGHT_STUDENT = "insight.student"
"""Tek ogrenci icin analiz/tavsiye uret."""

INSIGHT_CLASS = "insight.class"
"""Bir sinif (ya da ders) icin toplu analiz uret."""

INSIGHT_REFRESH = "insight.refresh"
"""Bir okul icin hesaplari yeniden kosturur; parti isidir."""

NAMES: tuple[str, ...] = (INSIGHT_STUDENT, INSIGHT_CLASS, INSIGHT_REFRESH)


#: Backend'in ZEKA'ya `Request` GONDEREBILDIGI yetenek adlari
#: (`constant.rs:568,574`) -- dagitim tablosunun tamami. Servisin cagirdigi
#: `insight.*` depo operasyonlarini KAPSAMAZ (bkz. modul dokumani, 2. yon).
#: ZEKA'nin hicbiri bu kumede degildir; kesisim bos oldugu surece backend
#: ZEKA'yi cagiramaz. `tests/test_capabilities.py` bu gercegi pinler.
BACKEND_CALLABLE_CAPABILITIES: tuple[str, ...] = ("chat.reply", "rag.index")


# --- payload sozlesmeleri --------------------------------------------------
# `Request.payload` ve `Response.payload` tasima icin OPAK'tir
# (`ai/protocol.rs:146-147`); bicimi bu dosya tanimlar.


class StudentRequest(TypedDict, total=False):
    """`insight.student` istek payload'i.

    `school` PAYLOAD'DA DEGILDIR: okul cerceve seviyesinde `Request.school`
    alaninda gelir (`ai/protocol.rs:36-47`). Payload'a ikinci bir okul alani
    koymak, iki kaynagin celisebilecegi bir yer yaratirdi.
    """

    user_id: str  # zorunlu
    since: str  # ISO-8601 tarih; yoksa donem basi
    sections: list[str]  # istenen bolumler; yoksa hepsi


class StudentResponse(TypedDict, total=False):
    """`insight.student` cevap payload'i."""

    user_id: str
    generated_at: str  # ISO-8601
    archetype: str  # tespit edilen calisma profili
    signals: list[dict[str, Any]]  # {kind, severity, evidence, ...}
    recommendations: list[dict[str, Any]]  # {action, rationale, weight}
    coverage: dict[str, Any]  # hangi veri kaynagindan kac kayit okundu


class ClassRequest(TypedDict, total=False):
    """`insight.class` istek payload'i."""

    course_id: str  # zorunlu: hangi ders/sinif
    term: str  # donem anahtari; yoksa gecerli donem
    top_n: int  # dikkat listesi uzunlugu


class ClassResponse(TypedDict, total=False):
    """`insight.class` cevap payload'i."""

    course_id: str
    generated_at: str
    cohort_size: int
    topic_gaps: list[dict[str, Any]]  # {topic, mastery, cohort_share}
    attention_list: list[dict[str, Any]]  # {user_id, reason, score}
    coverage: dict[str, Any]


class RefreshRequest(TypedDict, total=False):
    """`insight.refresh` istek payload'i. Parti isi: ogrenci listesi verilmezse
    yapilandirmadaki liste kullanilir (backend'de kullanici listeleme yolu yok,
    bkz. `docs/BACKEND-GEREKSINIMLERI.md` madde 3)."""

    user_ids: list[str]
    force: bool  # onbellek gecerli olsa bile yeniden hesapla


class RefreshResponse(TypedDict, total=False):
    """`insight.refresh` cevap payload'i."""

    started_at: str
    requested: int
    computed: int
    skipped: int
    failed: list[dict[str, Any]]  # {user_id, code, message}


#: Yetenek adi -> (istek tipi, cevap tipi). Belge ve dogrulama icin.
SCHEMAS: dict[str, tuple[type, type]] = {
    INSIGHT_STUDENT: (StudentRequest, StudentResponse),
    INSIGHT_CLASS: (ClassRequest, ClassResponse),
    INSIGHT_REFRESH: (RefreshRequest, RefreshResponse),
}


# --- isleyici defteri ------------------------------------------------------

Handler = Callable[[str, dict[str, Any]], dict[str, Any]]
"""(`school`, `payload`) -> cevap payload'i. Okul cerceveden gelir."""

_handlers: dict[str, Handler] = {}

#: Servisin deposu (`store.BridgeStore`). Isleyiciler okulun deposunu
#: BURADAN cozer: `capabilities.store().store_for(school)`. Cercevenin
#: `school` alani tek kimlik kaynagidir; ikinci bir yol (ortam degiskeni,
#: varsayilan okul) olmamasi bilincli -- yanlis okula yazan bir isleyici,
#: bu alanin kapatmak istedigi tek arizadir.
_store: Any = None


def bind_store(store: Any) -> None:
    """Acilista bir kez cagrilir (`bridge._serve`); testler de kullanir."""
    global _store
    _store = store


def store() -> Any:
    """Bagli depo. Baglanmamisken okul cozulemez -- sessizce bos bir depo
    uydurmak, yazilan her seyi kaybederdi."""
    if _store is None:
        raise CapabilityError(
            "unavailable",
            "depo bagli degil; isleyici okul deposunu cozemez",
        )
    return _store


def names() -> list[str]:
    """`Hello.capabilities` icine yazilacak adlar."""
    return list(NAMES)


def register(name: str, handler: Handler) -> None:
    """Bir yetenegi kaydet. Ilan edilmeyen ada kayit kabul edilmez -- ilan ile
    dagitimin ayrisabilecegi tek yer burasi, o yuzden kapatiliyor."""
    if name not in NAMES:
        raise KeyError(f"ilan edilmeyen yetenek kaydedilemez: {name!r}")
    _handlers[name] = handler


def dispatch(name: str, school: str, payload: Any) -> dict[str, Any]:
    """Gelen `Request`'i isleyicisine ver.

    Kayitli isleyici yoksa `unknown_capability` -- tam eslesme kurali burada da
    gecerlidir; yaklasik eslesme ya da geri dusme YOKTUR.
    """
    handler = _handlers.get(name)
    if handler is None:
        raise CapabilityError(
            "unknown_capability",
            f"'{name}' bu serviste tanimli degil (ilan edilenler: {', '.join(NAMES)})",
        )
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise CapabilityError("bad_request", "payload bir nesne olmali")
    return handler(school, payload)


def require_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError("bad_request", f"'{key}' bos olmayan bir metin olmali")
    return value.strip()


def summary() -> str:
    """Acilis logu icin tek satir: iki yonu AYRI soyler.

    Onceki hali "(backend'in tanidigi: chat.reply, rag.index; N yetenek
    TANIMSIZ, istek gelmeyecek)" idi ve depo yolu (2. yon) calismaya
    basladiktan sonra backend'in `insight` hakkinda hicbir sey bilmedigi
    okunuyordu. Liste backend'in **cagirabildikleridir**; servisin
    **cagirdigi** operasyonlari kapsamaz.
    """
    not_callable = [n for n in NAMES if n not in BACKEND_CALLABLE_CAPABILITIES]
    return (
        f"backend'in cagirabildigi yetenekler: "
        f"{', '.join(BACKEND_CALLABLE_CAPABILITIES)} "
        f"(servis->backend depo yolu: kopru/insight.* -- bu liste onu kapsamaz); "
        f"servis tarafi isler ({', '.join(NAMES)}) backend tarafindan HENUZ "
        f"cagrilmiyor ({len(not_callable)} ad dagitim tablosunda yok)"
    )
