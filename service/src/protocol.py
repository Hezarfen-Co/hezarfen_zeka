"""`hab/2` kablo bicimi -- backend'in `src/ai/protocol.rs` dosyasinin Python karsiligi.

OTORITE: `hezarfen_backend-main/src/ai/protocol.rs`. Burada gecen her alan adi
orada gectigi gibi yazilmistir; bir alani yeniden adlandirmak sessizce her seyi
bozar (`protocol.rs:422-424` testi tam bunu pinliyor).

Cerceve bicimi (`protocol.rs:54-59`):
    u32 big-endian uzunluk + o kadar bayt UTF-8 JSON.

Akis disiplini (`protocol.rs:9-34`):
  * Kontrol akisi: ilk *istemci* baslatimli cift yonlu akis. Servis bir `Hello`
    yazar, backend bir `Greeting` yazar, akis omur boyu ACIK kalir. Kapanmasi
    kayittan dusme sinyalidir; heartbeat cercevesi yoktur.
  * Is: *sunucu* baslatimli her akis bir `Request` tasir, servis bir `Response`
    yazar ve akis kapanir.
  * API geri okumasi: servisin actigi (kontrol akisindan sonraki) her istemci
    baslatimli akis bir `ApiRequest` tasir, backend bir `ApiResponse` yazar.
  * Blob okumasi: ayni yon, bir `BlobRequest`; backend bir `BlobResponse`
    BASLIK cercevesi yazar, `ok` ise tam `size` HAM bayt onu izler -- bunlar
    cerceve DEGILDIR, dolayisiyla cerceve boyut kapagina tabi degildir
    (`protocol.rs:26-31`).

Iki istemci baslatimli sekil, zorunlu alaniyla ayirt edilir: `ApiRequest`'te
`path`, `BlobRequest`'te `file` vardir (`protocol.rs:34`, `server.rs:481-497`).

Okul kapsami (`protocol.rs:36-47`): her istek cercevesi okulunu slug ile
adlandirir, her cevap onu yankilar. `Hello` KASITLI olarak okul tasimaz --
filo tum okullar icin paylasilir. Varsayilan ya da geri dusme yoktur.

Korelasyon kimligi yoktur (`protocol.rs:48-52`): QUIC akis kimlikleri zaten
coklama yapar. `id` yalnizca iz kimligidir.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import struct
import time
from dataclasses import dataclass, field
from typing import Any

# --- backend'den turetilen sabitler ----------------------------------------
# Kopyalanmadi, TURETILDI: her birinin kaynak satiri yanindadir. Backend bu
# degerleri degistirirse burasi sapar; sapmayi yakalayan sey `tests/` icindeki
# sabit testleri ve `docs/BACKEND-GEREKSINIMLERI.md` icindeki sapma notudur.

AI_PROTOCOL = "hab/2"
"""`constant.rs:530` -- `pub const AI_PROTOCOL: &str = "hab/2";`

DIKKAT: podcast ve Celebi servisleri `hab/1` kullaniyor ve bu YANLIS. Sürüm
kapisi iki yerde birden reddeder: ALPN muzakeresi (TLS el sikismasinda) ve
`protocol.rs:323` `protocol_matches`. ZEKA `hab/2` konusur.
"""

AI_ALPN = "hab/2"
"""`constant.rs:531` -- `pub const AI_ALPN: &[u8] = b"hab/2";` Ayni dize."""

AI_MAX_FRAME_BYTES = 8 * 1024 * 1024
"""`constant.rs:536` -- tek bir cercevenin tavanı. Uzunluk oneki, govde
ayrilmadan ONCE denetlenir; boylece kotu bir uzunluk bellek tuketemez."""

AI_MAX_CONCURRENT_PER_WORKER = 64
"""`constant.rs:547` -- backend `Hello.max_concurrent` degerini 1..=64 arasina
kirpar."""

AI_DEFAULT_CONCURRENT_PER_WORKER = 8
"""`constant.rs:548` -- `max_concurrent` verilmezse kullanilan deger."""

AI_IDLE_TIMEOUT_SECS = 30
"""`constant.rs:554` -- QUIC bosta kalma zaman asimi."""

AI_KEEPALIVE_SECS = 10
"""`constant.rs:555` -- QUIC PING araligi; bosta kalma zaman asiminin cok
altinda ki saglikli ama sessiz bir servis dusurulmesin."""

AI_HANDSHAKE_TIMEOUT_SECS = 10
"""`constant.rs:643` -- el sikisma tek cerceve gidis-donustur; kimliksiz bir
baglanti dinleyiciyi sonsuza dek mesgul edemez."""

AI_BLOB_WRITE_STALL_SECS = 30
"""`constant.rs:563` -- blob govdesinin yazma basina ilerleme tavani. Aktarim
kapagi DEGIL, TIKANMA kapagi."""

AI_DEFAULT_REQUEST_TIMEOUT_SECS = 30
"""`constant.rs:542` -- backend bir AI istegini terk etmeden once bekledigi
varsayilan sure. Servis tarafinda yalnizca bilgi amaclidir; gercek sure her
`Request` cercevesinin kendi `deadline_ms` alanindadir."""

CERTIFICATE_PATH = "/ai/certificate"
"""`src/web/ai.rs` -- `certificate_pem` + `fingerprint_sha256` doner."""

DEADLINE_MARGIN_SECS = 0.25
"""Kendi degerimiz: backend'in `deadline_ms` suresi dolmadan hemen once
cevaplayabilmek icin butceden dusulen pay. Gec cevap yerine erken hata."""

GREETING_TIMEOUT_SECS = 8.0
"""Kendi degerimiz; backend'in `AI_HANDSHAKE_TIMEOUT_SECS` = 10 s degerinin
altinda tutulur ki reddi biz gorelim, akis altimizdan kesilmesin."""

AI_API_ALLOWLIST: tuple[str, ...] = (
    "/auth/me",
    "/users/me/profile",
    "/users/{id}/profile",
    "/notes",
    "/notes/{id}",
    "/course-notes",
    "/course-notes/{id}",
    "/course-notes/{id}/files",
    "/homework",
    "/homework/{id}",
    "/homework/{id}/result",
    "/homework/{id}/submission",
    "/homework/report/{user}",
    "/marks/me",
    "/marks/{user}",
    "/attendance/me",
    "/attendance/{user}",
    "/pomodoro/me",
    "/pomodoro/{user}",
)
"""`constant.rs:656-676` -- AI servislerinin okuyabilecegi TEK yol kumesi.

Reddet-varsayilan, segment segment eslesme (`ai/api.rs:39-60`): on-ek eslesmesi
ve kuyruk joker'i YOKTUR. `/notes` asla `/notes/{id}/files` kabul etmez. Bu
liste servislerin erisim kapsaminin ta kendisidir.

Bu demet backend'in listesinin AYNASIDIR. Sapma testi: `tests/test_protocol.py`
icindeki `test_allowlist_matches_backend_snapshot`.
"""


# --- hata kodlari ----------------------------------------------------------
# Backend'in tel uzerinde dondurdugu, makine okunabilir, kararli kodlar.


class RejectCode:
    """`Greeting{type:"rejected"}` icindeki `code` degerleri (`protocol.rs:123-130`)."""

    UNSUPPORTED_PROTOCOL = "unsupported_protocol"
    UNAUTHORIZED = "unauthorized"
    NO_CAPABILITIES = "no_capabilities"
    MALFORMED = "malformed"


class ApiErrorCode:
    """`ApiResponse{outcome:"err"}` / `BlobResponse{status:"err"}` kodlari.

    Kaynaklar: `ai/server.rs:75-99` (okul cozumleme), `ai/server.rs:719-731`
    (yontem ve izin listesi), `ai/server.rs:709` (kullanici), `ai/server.rs:628`
    ve `:650` (blob).
    """

    MALFORMED = "malformed"
    UNKNOWN_SCHOOL = "unknown_school"
    SCHOOL_SUSPENDED = "school_suspended"
    UNAVAILABLE = "unavailable"
    PATH_NOT_ALLOWED = "path_not_allowed"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    UNKNOWN_USER = "unknown_user"
    NOT_FOUND = "not_found"
    FORBIDDEN = "forbidden"


#: Yapilandirma degismeden yeniden denemenin anlamsiz oldugu red kodlari.
#: Yine de CIKMIYORUZ (bkz. `bridge.py`): backend yeniden dagitilabilir.
PERMANENT_REJECTS = (RejectCode.UNSUPPORTED_PROTOCOL, RejectCode.UNAUTHORIZED)

#: Daha sonra denemeye deger red kodlari (`server.rs:75-81` gerekcesi).
RETRYABLE_API_CODES = (ApiErrorCode.SCHOOL_SUSPENDED, ApiErrorCode.UNAVAILABLE)


# --- istisnalar ------------------------------------------------------------


class ProtocolError(Exception):
    """Kablo seviyesinde bir sorun. `code` makine okunabilirdir."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class FrameTooLarge(ProtocolError):
    """Cerceve `AI_MAX_FRAME_BYTES` kapagini asiyor."""

    def __init__(self, size: int) -> None:
        super().__init__(
            "frame_too_large",
            f"{size} bayt, {AI_MAX_FRAME_BYTES} baytlik cerceve sinirini asiyor",
        )
        self.size = size


class FrameMalformed(ProtocolError):
    """Cerceve govdesi beklenen mesaj icin gecerli JSON degil."""

    def __init__(self, message: str) -> None:
        super().__init__(ApiErrorCode.MALFORMED, message)


class HandshakeRejected(RuntimeError):
    """`Greeting{type:"rejected"}` alindi."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"backend kaydi reddetti ({code}): {message}")
        self.code = code
        self.message = message

    @property
    def permanent(self) -> bool:
        return self.code in PERMANENT_REJECTS


class ApiRefused(Exception):
    """Kopru seviyesinde red: `ApiResponse{outcome:"err"}`.

    HTTP 404 bu DEGILDIR: router calisip cevap verdiyse o bir `ok`'tur ve
    `status` alaninda tasinir (`protocol.rs:196-198`).
    """

    def __init__(self, code: str, message: str, school: str = "", request_id: str = "") -> None:
        super().__init__(f"kopru istegi reddetti ({code}): {message}")
        self.code = code
        self.message = message
        self.school = school
        self.request_id = request_id

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE_API_CODES


class BlobRefused(ApiRefused):
    """`BlobResponse{status:"err"}`."""


class CapabilityError(Exception):
    """Yetenek isleyicisinin ele alinmis hatasi; `Response{status:"err"}` olur."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# --- iz kimligi ------------------------------------------------------------

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_trace_id() -> str:
    """ULID uretir (48 bit zaman + 80 bit rastgelelik, Crockford base32).

    Backend `id` alanini ULID diye belgeler (`protocol.rs:136`) ama dogrulamaz;
    yine de ayni bicimde uretiyoruz ki iki tarafin loglari yan yana okunsun.
    Harici bagimlilik eklememek icin elle yazildi.
    """
    value = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    out = [""] * 26
    for index in range(25, -1, -1):
        out[index] = _CROCKFORD[value & 0x1F]
        value >>= 5
    return "".join(out)


# --- cerceveleme -----------------------------------------------------------


def encode_frame(obj: Any) -> bytes:
    """Bir nesneyi tek bir uzunluk onekli JSON cerceveye cevir.

    Boyut kapagi YAZARKEN de uygulanir (`protocol.rs:275-277`): sinirin ustunde
    bir cerceve yazmak, karsi tarafin onu okuyamayacagi bir akis birakmaktir.
    """
    body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > AI_MAX_FRAME_BYTES:
        raise FrameTooLarge(len(body))
    return struct.pack(">I", len(body)) + body


def decode_frame(data: bytes) -> Any:
    """Tek bir tam cerceveyi (uzunluk oneki dahil) coz. Testler icin."""
    if len(data) < 4:
        raise FrameMalformed("cerceve 4 baytlik uzunluk onegini bile tasimiyor")
    (length,) = struct.unpack(">I", data[:4])
    if length > AI_MAX_FRAME_BYTES:
        raise FrameTooLarge(length)
    body = data[4 : 4 + length]
    if len(body) != length:
        raise FrameMalformed(f"{length} bayt vaat edildi, {len(body)} bayt var")
    try:
        return json.loads(body)
    except ValueError as exc:
        raise FrameMalformed(f"cerceve govdesi gecerli JSON degil: {exc}") from exc


class FrameStream:
    """Tek bir QUIC akisindan cerceve okuyan tampon.

    `feed()` aioquic'in `StreamDataReceived` olayindan beslenir; `read_frame()`
    bir tam cerceve, `read_exact()` ham bayt dondurur (blob govdesi icin).
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._eof = False

    def feed(self, data: bytes, end: bool) -> None:
        if data:
            self._queue.put_nowait(data)
        if end:
            self._queue.put_nowait(None)

    async def read_exact(self, n: int) -> bytes:
        """Tam `n` bayt oku. Akis erken biterse `EOFError`.

        Blob govdesi bu yoldan gelir: cerceve degil, ham bayt
        (`protocol.rs:26-31`), dolayisiyla cerceve kapagina tabi degildir.
        """
        while len(self._buf) < n:
            if self._eof:
                raise EOFError("cerceve/govde tamamlanmadan akis bitti")
            chunk = await self._queue.get()
            if chunk is None:
                self._eof = True
                continue
            self._buf.extend(chunk)
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    async def read_frame(self) -> Any:
        header = await self.read_exact(4)
        (length,) = struct.unpack(">I", header)
        # Uzunluk, govde AYRILMADAN once denetlenir (`protocol.rs:286-289`).
        if length > AI_MAX_FRAME_BYTES:
            raise FrameTooLarge(length)
        body = await self.read_exact(length)
        try:
            return json.loads(body)
        except ValueError as exc:
            raise FrameMalformed(f"cerceve govdesi gecerli JSON degil: {exc}") from exc


# --- cerceve tipleri -------------------------------------------------------
# Alan adlari birebir telde gecen adlardir. `to_wire()` cikti, `from_wire()`
# giris; ikisi arasindaki gidis-donus testte pinlenir.


def _require_str(raw: Any, name: str) -> str:
    if not isinstance(raw, dict):
        raise FrameMalformed("cerceve bir nesne degil")
    value = raw.get(name)
    if not isinstance(value, str) or not value:
        raise FrameMalformed(f"'{name}' bos olmayan bir metin olmali")
    return value


def _optional_str(raw: dict, name: str) -> str | None:
    value = raw.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise FrameMalformed(f"'{name}' metin ya da yok olmali")
    return value


@dataclass(frozen=True)
class Hello:
    """Servisin kontrol akisindaki acilis cercevesi (`protocol.rs:85-103`).

    KASITLI olarak okul tasimaz: filo paylasimlidir, tek baglanti dagitimdaki
    her okula hizmet eder ve her frame kendi okulunu adlandirir.
    """

    protocol: str
    service: str
    capabilities: tuple[str, ...]
    token: str
    max_concurrent: int | None = None

    def to_wire(self) -> dict[str, Any]:
        wire: dict[str, Any] = {
            "protocol": self.protocol,
            "service": self.service,
            "capabilities": list(self.capabilities),
            "token": self.token,
        }
        # `#[serde(default)]`: yoklugu varsayilan demektir (`protocol.rs:101`).
        if self.max_concurrent is not None:
            wire["max_concurrent"] = int(self.max_concurrent)
        return wire

    @staticmethod
    def from_wire(raw: Any) -> "Hello":
        protocol = _require_str(raw, "protocol")
        service = _require_str(raw, "service")
        caps = raw.get("capabilities")
        if not isinstance(caps, list) or not all(isinstance(c, str) for c in caps):
            raise FrameMalformed("'capabilities' metin listesi olmali")
        token = _require_str(raw, "token")
        max_concurrent = raw.get("max_concurrent")
        if max_concurrent is not None and not isinstance(max_concurrent, int):
            raise FrameMalformed("'max_concurrent' tamsayi ya da yok olmali")
        return Hello(protocol, service, tuple(caps), token, max_concurrent)


def build_hello(
    service: str, capabilities: tuple[str, ...] | list[str], token: str, max_concurrent: int
) -> dict[str, Any]:
    """Kontrol akisina yazilacak `Hello` cercevesi. Protokol her zaman `hab/2`."""
    clamped = max(1, min(int(max_concurrent), AI_MAX_CONCURRENT_PER_WORKER))
    return Hello(AI_PROTOCOL, service, tuple(capabilities), token, clamped).to_wire()


@dataclass(frozen=True)
class Greeting:
    """Backend'in kontrol akisi cevabi (`protocol.rs:106-119`).

    Etiket alani `type`; degerler `welcome` / `rejected` (`protocol.rs:425-437`).
    """

    type: str
    worker_id: str = ""
    protocol: str = ""
    code: str = ""
    message: str = ""

    @staticmethod
    def from_wire(raw: Any) -> "Greeting":
        if not isinstance(raw, dict):
            raise FrameMalformed("greeting bir nesne degil")
        kind = raw.get("type")
        if kind == "welcome":
            return Greeting(
                "welcome",
                worker_id=str(raw.get("worker_id", "")),
                protocol=str(raw.get("protocol", "")),
            )
        if kind == "rejected":
            return Greeting(
                "rejected",
                code=str(raw.get("code", RejectCode.MALFORMED)),
                message=str(raw.get("message", "")),
            )
        raise FrameMalformed(f"bilinmeyen greeting type: {kind!r}")


def parse_greeting(raw: Any) -> str:
    """`Greeting`'i coz ve `worker_id` dondur; red ise `HandshakeRejected` firlat."""
    greeting = Greeting.from_wire(raw)
    if greeting.type == "rejected":
        raise HandshakeRejected(greeting.code, greeting.message)
    if greeting.protocol != AI_PROTOCOL:
        # Backend hosgeldin dedi ama baska bir surum yankiladi: eslesmeyen bir
        # surumle devam etmek, yanlis ayrisacak cerceveler yazmak demektir.
        raise HandshakeRejected(
            RejectCode.UNSUPPORTED_PROTOCOL,
            f"backend '{greeting.protocol}' yankiladi, biz '{AI_PROTOCOL}' konusuyoruz",
        )
    return greeting.worker_id or "?"


@dataclass(frozen=True)
class Request:
    """Backend'in sunucu baslatimli akista yazdigi tek is birimi
    (`protocol.rs:134-148`)."""

    id: str
    school: str
    capability: str
    deadline_ms: int
    payload: Any = None

    @staticmethod
    def from_wire(raw: Any) -> "Request":
        if not isinstance(raw, dict):
            raise FrameMalformed("istek cercevesi bir nesne degil")
        request_id = _require_str(raw, "id")
        school = _require_str(raw, "school")
        capability = _require_str(raw, "capability")
        deadline = raw.get("deadline_ms")
        if isinstance(deadline, bool) or not isinstance(deadline, (int, float)):
            raise FrameMalformed("'deadline_ms' sayi olmali")
        if isinstance(deadline, float) and (math.isnan(deadline) or math.isinf(deadline)):
            raise FrameMalformed("'deadline_ms' sonlu olmali")
        return Request(request_id, school, capability, int(deadline), raw.get("payload"))

    @property
    def timeout_secs(self) -> float | None:
        """Isleyiciye verilecek butce. Backend'in tavanindan pay dusulur."""
        if self.deadline_ms <= 0:
            return None
        budget = self.deadline_ms / 1000.0
        return max(budget - DEADLINE_MARGIN_SECS, budget * 0.5)


def ok_response(request_id: str, school: str, payload: Any) -> dict[str, Any]:
    """`Response{status:"ok"}` (`protocol.rs:155-161`). `school` YANKILANIR."""
    return {"status": "ok", "id": request_id, "school": school, "payload": payload}


def err_response(request_id: str, school: str, code: str, message: str) -> dict[str, Any]:
    """`Response{status:"err"}` (`protocol.rs:162-169`). Ele alinmis hata; bir
    servis istegin ortasinda olurse akisi birakir, bu cerceveyi yazmaz."""
    return {
        "status": "err",
        "id": request_id,
        "school": school,
        "code": code,
        "message": message,
    }


@dataclass(frozen=True)
class ApiRequest:
    """Servisin actigi akista okulun kendi API'sine yaptigi okuma
    (`protocol.rs:174-194`)."""

    id: str
    school: str
    path: str
    query: str | None = None
    on_behalf_of: str | None = None
    method: str | None = None

    def to_wire(self) -> dict[str, Any]:
        wire: dict[str, Any] = {"id": self.id, "school": self.school, "path": self.path}
        # Opsiyoneller `#[serde(default)]`; yoklari yazilmaz.
        if self.query:
            wire["query"] = self.query
        if self.on_behalf_of:
            wire["on_behalf_of"] = self.on_behalf_of
        if self.method:
            wire["method"] = self.method
        return wire

    @staticmethod
    def from_wire(raw: Any) -> "ApiRequest":
        path = _require_str(raw, "path")
        return ApiRequest(
            _require_str(raw, "id"),
            _require_str(raw, "school"),
            path,
            _optional_str(raw, "query"),
            _optional_str(raw, "on_behalf_of"),
            _optional_str(raw, "method"),
        )


def build_api_request(
    request_id: str,
    school: str,
    path: str,
    query: str | None = None,
    on_behalf_of: str | None = None,
    method: str | None = None,
) -> dict[str, Any]:
    """`ApiRequest` cercevesi kur; kablonun kendi kurallarini burada uygula.

    - `school` zorunludur; yoksa backend `malformed` doner (`server.rs:472`)
      ama daha da onemlisi, YANLIS okulun verisini okuma ihtimali bu alanla
      imkansiz kilinir (`protocol.rs:44-47`). Bu yuzden burada da zorunlu.
    - `path` `/` ile baslamali ve `?` ICERMEMELI: query kendi alaninda gider ve
      icinde `?` gecen bir yol izin listesinde ESLESMEZ (`ai/api.rs:29-31`).
    - Yol izin listesinde olmali (`constant.rs:656-676`). Bunu burada
      denetliyoruz ki izinsiz bir yol tele HIC cikmasin.
    """
    if not isinstance(school, str) or not school:
        raise ApiRefused(ApiErrorCode.MALFORMED, "okul slug'i zorunlu; varsayilan yok")
    if not isinstance(path, str) or not path.startswith("/") or "?" in path:
        raise ApiRefused(
            ApiErrorCode.MALFORMED,
            f"yol / ile baslamali ve ? icermemeli (query ayri alanda gider): {path!r}",
            school=school,
        )
    if method is not None and method.upper() != "GET":
        # Kopru salt-okumadir (`server.rs:719-726`).
        raise ApiRefused(
            ApiErrorCode.METHOD_NOT_ALLOWED,
            f"kopru yalnizca GET dagitir, istenen: {method!r}",
            school=school,
        )
    if not path_allowed(path):
        raise ApiRefused(
            ApiErrorCode.PATH_NOT_ALLOWED,
            f"'{path}' AI servislerinin okuyabildigi bir yol degil",
            school=school,
        )
    return ApiRequest(
        request_id,
        school,
        path,
        query.lstrip("?") if query else None,
        on_behalf_of or None,
        method,
    ).to_wire()


@dataclass(frozen=True)
class ApiResponse:
    """Backend'in tek cevap cercevesi (`protocol.rs:199-221`).

    Etiket alani `outcome` -- `status` DEGIL; `status` HTTP kodudur
    (`protocol.rs:449-451`).
    """

    id: str
    school: str
    status: int
    body: Any

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @staticmethod
    def from_wire(raw: Any) -> "ApiResponse":
        if not isinstance(raw, dict):
            raise ApiRefused(ApiErrorCode.MALFORMED, "api cevabi bir nesne degil")
        outcome = raw.get("outcome")
        school = str(raw.get("school", ""))
        request_id = str(raw.get("id", ""))
        if outcome == "err":
            raise ApiRefused(
                str(raw.get("code", "?")),
                str(raw.get("message", "")),
                school=school,
                request_id=request_id,
            )
        if outcome != "ok":
            raise ApiRefused(
                ApiErrorCode.MALFORMED, f"bilinmeyen outcome: {outcome!r}", school=school
            )
        return ApiResponse(request_id, school, _coerce_status(raw.get("status", 0)), raw.get("body"))


def parse_api_response(raw: Any) -> ApiResponse:
    return ApiResponse.from_wire(raw)


def _coerce_status(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ApiRefused(ApiErrorCode.MALFORMED, f"status sayisal degil: {value!r}")
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as exc:
            raise ApiRefused(
                ApiErrorCode.MALFORMED, f"status sayisal degil: {value!r}"
            ) from exc
    raise ApiRefused(ApiErrorCode.MALFORMED, f"status sayisal degil: {value!r}")


@dataclass(frozen=True)
class BlobRequest:
    """Bir ders notu dosyasinin BAYTLARINI okuma istegi (`protocol.rs:226-240`).

    `ApiRequest`'ten zorunlu `file` alaniyla ayrilir. `on_behalf_of` pratikte
    zorunludur: `ai` rolu hicbir dersi goremez, dolayisiyla onsuz her zaman
    `forbidden` alinir (`protocol.rs:236-239`).
    """

    id: str
    school: str
    file: str
    on_behalf_of: str | None = None

    def to_wire(self) -> dict[str, Any]:
        wire: dict[str, Any] = {"id": self.id, "school": self.school, "file": self.file}
        if self.on_behalf_of:
            wire["on_behalf_of"] = self.on_behalf_of
        return wire

    @staticmethod
    def from_wire(raw: Any) -> "BlobRequest":
        return BlobRequest(
            _require_str(raw, "id"),
            _require_str(raw, "school"),
            _require_str(raw, "file"),
            _optional_str(raw, "on_behalf_of"),
        )


def build_blob_request(
    request_id: str, school: str, file_id: str, on_behalf_of: str | None = None
) -> dict[str, Any]:
    if not isinstance(school, str) or not school:
        raise BlobRefused(ApiErrorCode.MALFORMED, "okul slug'i zorunlu; varsayilan yok")
    if not isinstance(file_id, str) or not file_id:
        raise BlobRefused(
            ApiErrorCode.MALFORMED, "'file' bos olmayan bir metin olmali", school=school
        )
    return BlobRequest(request_id, school, file_id, on_behalf_of or None).to_wire()


@dataclass(frozen=True)
class BlobResponse:
    """Blob akisini acan (ya da reddeden) BASLIK cercevesi (`protocol.rs:245-265`).

    Etiket alani `status` -- `outcome` DEGIL; bir blob basliginda carpisacagi
    bir HTTP kodu yoktur (`protocol.rs:509-511`).
    `ok` ise bu cerceveden sonra tam `size` HAM bayt gelir, sonra FIN.
    """

    id: str
    school: str
    name: str
    content_type: str
    size: int

    @staticmethod
    def from_wire(raw: Any) -> "BlobResponse":
        if not isinstance(raw, dict):
            raise BlobRefused(ApiErrorCode.MALFORMED, "blob basligi bir nesne degil")
        status = raw.get("status")
        school = str(raw.get("school", ""))
        request_id = str(raw.get("id", ""))
        if status == "err":
            raise BlobRefused(
                str(raw.get("code", "?")),
                str(raw.get("message", "")),
                school=school,
                request_id=request_id,
            )
        if status != "ok":
            raise BlobRefused(
                ApiErrorCode.MALFORMED, f"bilinmeyen blob status: {status!r}", school=school
            )
        size = raw.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise BlobRefused(
                ApiErrorCode.MALFORMED, f"'size' negatif olmayan tamsayi olmali: {size!r}",
                school=school,
            )
        return BlobResponse(
            request_id,
            school,
            str(raw.get("name", "")),
            str(raw.get("content_type", "application/octet-stream")),
            size,
        )


def parse_blob_response(raw: Any) -> BlobResponse:
    return BlobResponse.from_wire(raw)


@dataclass
class Blob:
    """Bir blob okumasinin sonucu: baslik + ham baytlar."""

    header: BlobResponse
    data: bytes = field(repr=False, default=b"")


# --- izin listesi eslesmesi ------------------------------------------------
# `ai/api.rs:39-60` mantiginin birebir kopyasi: segment segment, on-ek YOK,
# kuyruk joker'i YOK, `{x}` tam olarak bir BOS OLMAYAN segment.


def route_template(path: str) -> str | None:
    """Bu yolun eslestigi izin listesi SABLONU; somut yol degil.

    Somut yol kayit kimligi tasir; log ve olcum etiketi olarak sablon kullanilir
    (`ai/api.rs:24-28`).
    """
    if not isinstance(path, str) or not path.startswith("/") or "?" in path:
        return None
    for pattern in AI_API_ALLOWLIST:
        if _pattern_matches(pattern, path):
            return pattern
    return None


def path_allowed(path: str) -> bool:
    """Bir AI servisi bu yolu GET edebilir mi?"""
    return route_template(path) is not None


def _pattern_matches(pattern: str, path: str) -> bool:
    expected = pattern[1:].split("/")
    actual = path[1:].split("/")
    # Farkli segment sayisi = farkli rota. Sondaki `/` ayri bir yoldur.
    if len(expected) != len(actual):
        return False
    for segment, given in zip(expected, actual):
        if segment.startswith("{") and segment.endswith("}"):
            if not given:
                return False
        elif segment != given:
            return False
    return True
