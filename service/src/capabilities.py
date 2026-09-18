"""ZEKA'nin ilan edecegi yetenekler ve payload sozlesmeleri.

IKI YON VARDIR; karistirilmamalidir:

1. **Sunucu-baslatimli (backend -> ZEKA).** The backend dispatches `Request`
   frames only for names its own dispatch table carries, and today
   `insight.student` and `insight.refresh` are there: `ai/insight.rs`
   `compute_student()` / `refresh()` send both, and the doors are in
   `web/insights.rs` (merged 2026-09-18). `insight.class` is advertised but
   never dispatched: its request names a course, and the bridge's read
   allowlist hands a service no roster to enumerate it with
   (`ai/insight.rs` module docs; `docs/BACKEND-GEREKSINIMLERI.md` item 3).
   Routing is an EXACT match (`ai/protocol.rs:91-94`): every advertised name
   gets its handler from `handlers.wire()`, and `verify_dispatchable()` checks
   the pair at startup -- if advertising and dispatch ever drift apart, the
   service REFUSES TO BOOT.

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

import logging
from typing import Any, Callable, TypedDict

from .protocol import CapabilityError

log = logging.getLogger(__name__)

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


#: The capability names the backend can send a `Request` FOR -- the half of
#: its dispatch table that concerns ZEKA. It does NOT cover the `insight.*`
#: storage operations the service calls (see the module docstring, direction
#: 2). Sources: `constant.rs:568,574` (chat.reply, rag.index) and
#: `ai/insight.rs::compute_student/refresh` + the `web/insights.rs` doors
#: (insight.student, insight.refresh; merged 2026-09-18). `insight.class` is
#: NOT in the set: the constant exists, the code that would send it does not.
#: `tests/test_capabilities.py` pins this.
BACKEND_CALLABLE_CAPABILITIES: tuple[str, ...] = (
    "chat.reply",
    "rag.index",
    "insight.student",
    "insight.refresh",
)

#: The `sections` vocabulary: the summary's four compute modules. A request
#: may name a subset; an unrequested module is NOT computed and reaches the
#: row as `null` -- the backend's `SummaryRow` keeps `null` ("not computed")
#: and `{}` ("read, and there was nothing") apart on purpose.
SECTIONS: tuple[str, ...] = ("marks", "attendance", "submission", "study")


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
    """`insight.student` cevap payload'i (`handlers.student` doldurur)."""

    user_id: str
    generated_at: str  # ISO-8601
    archetype: str  # BUGUN URETILMIYOR; alan gonderilmez (coverage.unavailable yazar)
    signals: list[dict[str, Any]]  # dikkat maddeleri: {trigger, course, fact, window_from, window_to, evidence}
    recommendations: list[dict[str, Any]]  # zeka_recommendation satirinin govdesi; `retain_until` gonderilmez
    coverage: dict[str, Any]  # okunan kaynak -> kayit sayisi + yazma muhasebesi + uretilemeyenler


class ClassRequest(TypedDict, total=False):
    """`insight.class` istek payload'i."""

    course_id: str  # zorunlu: hangi ders/sinif
    term: str  # donem anahtari; yoksa gecerli donem
    top_n: int  # dikkat listesi uzunlugu


class ClassResponse(TypedDict, total=False):
    """`insight.class` cevap payload'i (`handlers.klass` doldurur)."""

    course_id: str
    generated_at: str
    cohort_size: int
    topic_gaps: list[dict[str, Any]]  # BUGUN URETILMIYOR: bos liste + coverage.unavailable nedeni
    attention_list: list[dict[str, Any]]  # {user_id, trigger, fact, window_from, window_to, evidence} -- SKOR YOK
    coverage: dict[str, Any]


class RefreshRequest(TypedDict, total=False):
    """`insight.refresh` istek payload'i. Parti isi: ogrenci listesi verilmezse
    yapilandirmadaki liste kullanilir (backend'de kullanici listeleme yolu yok,
    bkz. `docs/BACKEND-GEREKSINIMLERI.md` madde 3)."""

    user_ids: list[str]
    force: bool  # onbellek gecerli olsa bile yeniden hesapla


class RefreshResponse(TypedDict, total=False):
    """`insight.refresh` cevap payload'i (`handlers.refresh` doldurur)."""

    started_at: str
    requested: int
    computed: int
    skipped: int
    failed: list[dict[str, Any]]  # {user_id, code, message} -- code: unavailable|internal
    #: Sozlesme disi ek alan: kosunun hukmu (`running|ok|partial|failed`).
    #: Backend'in struct'i bunu tasimaz ve serde bilinmeyen alani yok sayar;
    #: onsuz "0 istendi, 0 hesaplandi" temiz bir sifir gibi okunurdu.
    status: str


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
    dagitimin ayrisabilecegi tek yer burasi, o yuzden kapatiliyor.

    Isleyici es zamanli (async) olabilir: `bridge._handle` boyle bir kancayi
    olay dongusunde bekler, senkron olani is parcacigina verir
    (`bridge.py:495-515`). ZEKA'nin isleyicileri async'tir cunku her okuma
    kendi kopru cagrisidir (`handlers.py`)."""
    if name not in NAMES:
        raise KeyError(f"ilan edilmeyen yetenek kaydedilemez: {name!r}")
    _handlers[name] = handler


class RegistrationError(RuntimeError):
    """Ilan edilen bir adin isleyicisi yok. Acilista, bilerek patlar."""


def dispatchable_names() -> list[str]:
    """Isleyicisi KAYITLI adlar. `names()` ne ilan edilecegini soyler."""
    return [name for name in NAMES if name in _handlers]


def verify_dispatchable() -> None:
    """Ilani hak etmeyen tek bir ad varsa ACILISI durdur.

    `bridge.run_once()` `Hello` cercevesini yazmadan hemen once cagirir, yani
    ilan eden her yol bu denetimden gecmistir. Defter haftalarca BOSTU ve
    `Hello` uc ad ilan ediyordu: backend'in gonderdigi her istek, ilan edilen
    adi ayni cumlede sayan bir `unknown_capability` ile donuyordu. Bu sinifin
    tekrar uretilmesini imkansiz kilan sey, ilan ile defterin ayni anda
    dogrulanmasidir -- sonradan ozur dilemek degil.
    """
    missing = [name for name in NAMES if name not in _handlers]
    if not missing:
        return
    message = (
        f"ilan edilen yeteneklerin isleyicisi yok: {', '.join(missing)} "
        f"(kayitli: {', '.join(dispatchable_names()) or 'yok'}) -- "
        "servis bunlari ILAN EDEMEZ; handlers.wire() cagrildi mi?"
    )
    log.error(message)
    raise RegistrationError(message)


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

    Onceki hali "backend'in tanidigi: chat.reply, rag.index; N yetenek
    TANIMSIZ" idi; depo yolu (2. yon) acildiktan ve backend `insight.student`
    / `insight.refresh`i gonderdikten sonra bu cumle bayatladi. Uc gercek
    ayri ayri yazilir: backend'in gonderebildigi adlar, servisin kayitli
    isleyicileri, ve backend'in dagitim tablosunda hala olmayan adlar.
    """
    served = dispatchable_names()
    unsent = [name for name in NAMES if name not in BACKEND_CALLABLE_CAPABILITIES]
    return (
        f"backend'in cagirabildigi yetenekler: "
        f"{', '.join(BACKEND_CALLABLE_CAPABILITIES)} "
        f"(servis->backend depo yolu: kopru/insight.* -- bu liste onu kapsamaz); "
        f"servis tarafi isleyiciler: {len(served)}/{len(NAMES)} kayitli "
        f"({', '.join(served) or 'yok'}); "
        f"backend'in dagitim tablosunda olmayan: {', '.join(unsent) or 'yok'}"
    )
