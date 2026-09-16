"""Backend'in AI koprusunu taklit eden sahte bir QUIC sunucusu.

BU URETIM KODU DEGILDIR. `service/tests/` altinda yasar ve yalnizca
`test_bridge_live.py` tarafindan kullanilir. Amaci tek bir sey: `src/bridge.py`
istemcisini GERCEK bir QUIC baglantisinda, GERCEK bir TLS el sikismasinda ve
GERCEK bir cerceve alisverisinde kosturmak.

Taklit edilen kaynak dosyalar:
  * `hezarfen_backend-main/src/ai/server.rs`   -- kabul dongusu, el sikisma,
    red kodlari, istemci baslatimli akis ayrimi, blob govdesi
  * `hezarfen_backend-main/src/ai/tls.rs`      -- ALPN, kendi kendine imzali
    sertifika, parmak izi
  * `hezarfen_backend-main/src/ai/api.rs`      -- yol izin listesi eslesmesi
  * `hezarfen_backend-main/src/constant.rs`    -- sabitler

KASITLI BAGIMSIZLIK: cerceveleme, izin listesi eslesmesi ve kod dizeleri burada
`src/protocol.py`'den ITHAL EDILMEZ, elle yeniden yazilir. Ayni modulu iki
tarafta da kullanmak, bir alan adi hatasini gorunmez kilardi -- test o zaman
kendi hatasiyla kendini dogrular.

Ne TAKLIT EDILMEZ: veritabani, okul kiracilari, kullanici yetkilendirme, modul
yetkilendirmesi, metrikler, izleme. Bunlarin listesi
`docs/KOPRU-KANITI.md` icindedir.
"""

from __future__ import annotations

import asyncio
import json
import struct
import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.asyncio.server import serve
from aioquic.quic.configuration import QuicConfiguration
from aioquic.tls import load_pem_private_key, load_pem_x509_certificates
from aioquic.quic.events import (
    ConnectionTerminated,
    QuicEvent,
    StreamDataReceived,
)

from .certs import generate

# --- backend'den turetilen sabitler ---------------------------------------
# Istemcinin kendi sabitlerinden BAGIMSIZ olarak burada yeniden yazildi.

AI_PROTOCOL = "hab/2"
"""`constant.rs:530`"""

AI_ALPN = "hab/2"
"""`constant.rs:531`"""

AI_MAX_FRAME_BYTES = 8 * 1024 * 1024
"""`constant.rs:536`"""

AI_IDLE_TIMEOUT_SECS = 30
"""`constant.rs:554`"""

AI_MAX_CONCURRENT_PER_WORKER = 64
"""`constant.rs:547`"""

AI_DEFAULT_CONCURRENT_PER_WORKER = 8
"""`constant.rs:548`"""

AI_API_ALLOWLIST: tuple[str, ...] = (
    # `constant.rs:656-676` -- birebir, ayni sirada.
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

CERTIFICATE_PATH = "/ai/certificate"
"""`src/web/ai.rs:80-81` -- `certificate_pem` + `fingerprint_sha256`."""


# --- izin listesi ----------------------------------------------------------
# `ai/api.rs:20-61` mantiginin bagimsiz yeniden yazimi.


def path_allowed(path: str) -> bool:
    """Bir AI servisi bu yolu GET edebilir mi? (`api.rs:20-22`)"""
    return route_template(path) is not None


def route_template(path: str) -> str | None:
    """Eslesen SABLON, somut yol degil (`api.rs:28-36`)."""
    if not path.startswith("/") or "?" in path:
        return None
    for pattern in AI_API_ALLOWLIST:
        if _pattern_matches(pattern, path):
            return pattern
    return None


def _pattern_matches(pattern: str, path: str) -> bool:
    """`api.rs:40-61`: segment segment; `{x}` tam olarak bir BOS OLMAYAN segment."""
    expected = pattern[1:].split("/")
    actual = path[1:].split("/")
    if len(expected) != len(actual):
        # Farkli segment sayisi = farkli rota; sondaki `/` ayri bir yoldur.
        return False
    for segment, given in zip(expected, actual):
        if segment.startswith("{") and segment.endswith("}"):
            if not given:
                return False
        elif segment != given:
            return False
    return True


# --- cerceveleme -----------------------------------------------------------
# `protocol.rs:267-304` -- u32 big-endian uzunluk + o kadar bayt JSON.


def encode_frame(obj: Any) -> bytes:
    body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > AI_MAX_FRAME_BYTES:
        raise ValueError(f"{len(body)} bayt cerceve sinirini asiyor")
    return struct.pack(">I", len(body)) + body


class _Reader:
    """Tek bir akisin gelen baytlari; cerceve ve ham bayt okur."""

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
        while len(self._buf) < n:
            if self._eof:
                raise EOFError("akis erken bitti")
            chunk = await self._queue.get()
            if chunk is None:
                self._eof = True
                continue
            self._buf.extend(chunk)
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    async def read_frame(self) -> Any:
        (length,) = struct.unpack(">I", await self.read_exact(4))
        if length > AI_MAX_FRAME_BYTES:
            raise ValueError(f"cerceve {length} bayt, sinir {AI_MAX_FRAME_BYTES}")
        return json.loads(await self.read_exact(length))


# --- sunucu ayarlari -------------------------------------------------------


class FakeBridgeConfig:
    """Sahte sunucunun davranis dugmeleri.

    Her dugme bir backend davranisini ya oldugu gibi ya da bilerek BOZULMUS
    haliyle uretmek icindir; testler senaryolari bunlarla kurar.
    """

    def __init__(
        self,
        token: str = "test-token",
        protocol: str = AI_PROTOCOL,
        schools: tuple[str, ...] = ("demo-okul",),
        api_bodies: dict[tuple[str, str], tuple[int, Any]] | None = None,
        blobs: dict[tuple[str, str], tuple[str, str, bytes]] | None = None,
        suspended_schools: tuple[str, ...] = (),
        silent_paths: tuple[str, ...] = (),
    ) -> None:
        #: Bu yollar okunur ama ASLA cevaplanmaz. Istemcinin zaman asimi ve
        #: akis terk etme davranisini kanitlamak icin.
        self.silent_paths = silent_paths
        #: `Hello.token` bununla SABIT ZAMANDA karsilastirilir (`server.rs:1057`).
        self.token = token
        #: Sunucunun konustugu surum. `hab/2` disi bir deger vermek,
        #: istemcinin `unsupported_protocol` alma yolunu acar.
        self.protocol = protocol
        #: Bilinen okul slug'lari; disindaki her sey `unknown_school`.
        self.schools = schools
        #: Askiya alinmis okullar -> `school_suspended`.
        self.suspended_schools = suspended_schools
        #: (okul, yol) -> (http_status, govde). Izinli ama tanimsiz bir yol
        #: `ok` + 404 doner: router calisti ve cevap verdi (`protocol.rs:196-198`).
        self.api_bodies = dict(api_bodies or {})
        #: (okul, dosya) -> (ad, icerik_tipi, ham_baytlar)
        self.blobs = dict(blobs or {})


class WorkerRecord:
    """Kaydolmus bir servis -- backend'in `AiRegistry` kaydinin kucugu."""

    def __init__(self, worker_id: str, hello: dict[str, Any], connection: Any) -> None:
        self.worker_id = worker_id
        self.service = str(hello.get("service", ""))
        self.capabilities = tuple(hello.get("capabilities", ()))
        self.max_concurrent = _clamp_concurrency(hello.get("max_concurrent"))
        self.hello = hello
        self.connection = connection


def _clamp_concurrency(value: Any) -> int:
    """`registry.rs` / `constant.rs:547-548`: yoksa varsayilan, varsa 1..=64."""
    if not isinstance(value, int) or isinstance(value, bool):
        return AI_DEFAULT_CONCURRENT_PER_WORKER
    return max(1, min(value, AI_MAX_CONCURRENT_PER_WORKER))


# --- baglanti basina protokol ----------------------------------------------


class _BridgeConnection(QuicConnectionProtocol):
    """Tek bir servis baglantisi. `server.rs:serve_connection` karsiligi."""

    def __init__(self, *args: Any, bridge: "FakeBridge", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._bridge = bridge
        self._readers: dict[int, _Reader] = {}
        self._control_sid: int | None = None
        self._tasks: set[asyncio.Future] = set()
        self.worker: WorkerRecord | None = None
        self.terminated = asyncio.Event()

    # -- olay dagitimi --

    def quic_event_received(self, event: QuicEvent) -> None:
        if isinstance(event, StreamDataReceived):
            sid = event.stream_id
            reader = self._readers.get(sid)
            if reader is None:
                # Sunucu tarafinda istemci baslatimli cift yonlu akislar
                # sid % 4 == 0; ILKI kontrol akisidir (`protocol.rs:11-14`),
                # sonrakiler api/blob okumalaridir (`server.rs:427-433`).
                if sid % 4 != 0:
                    return
                reader = _Reader()
                self._readers[sid] = reader
                if self._control_sid is None:
                    self._control_sid = sid
                    self._spawn(self._serve_control(sid, reader))
                else:
                    self._spawn(self._serve_client_stream(sid, reader))
            reader.feed(event.data, event.end_stream)
        elif isinstance(event, ConnectionTerminated):
            for reader in self._readers.values():
                reader.feed(b"", end=True)
            if self.worker is not None:
                self._bridge._deregister(self.worker)
                self.worker = None
            self.terminated.set()

    def _spawn(self, coro: Any) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _send(self, sid: int, obj: Any, end: bool) -> None:
        self._quic.send_stream_data(sid, encode_frame(obj), end_stream=end)
        self.transmit()

    def _send_raw(self, sid: int, data: bytes, end: bool) -> None:
        self._quic.send_stream_data(sid, data, end_stream=end)
        self.transmit()

    # -- kontrol akisi: `server.rs:register` --

    async def _serve_control(self, sid: int, reader: _Reader) -> None:
        config = self._bridge.config
        try:
            hello = await reader.read_frame()
        except (EOFError, ValueError, json.JSONDecodeError) as exc:
            # `server.rs:940-947`: okunamayan bir Hello `malformed` ile reddedilir.
            self._refuse(sid, "malformed", str(exc))
            return
        if not isinstance(hello, dict):
            self._refuse(sid, "malformed", "Hello bir nesne degil")
            return
        self._bridge.hellos.append(hello)

        # Sira backend'inkiyle AYNI: surum, sonra token, sonra yetenekler
        # (`server.rs:949-991`). Sira degisirse hangi redde ugradigi degisir.
        if hello.get("protocol") != config.protocol:
            self._refuse(
                sid,
                "unsupported_protocol",
                f"this backend speaks {config.protocol}, "
                f"the service announced {hello.get('protocol')}",
            )
            return
        # `server.rs:1052-1059` sabit zamanli karsilastirma; burada yalnizca
        # SONUC onemli, zamanlama degil -- bu bir test sunucusu.
        if str(hello.get("token", "")) != config.token:
            self._refuse(sid, "unauthorized", "invalid token")
            return
        capabilities = hello.get("capabilities")
        if not isinstance(capabilities, list) or not capabilities:
            # DIKKAT: tel uzerindeki kod `no_capabilities`'tir
            # (`protocol.rs:125-130`, `#[serde(rename_all = "snake_case")]`).
            # `server.rs:976`'daki `"bad_capabilities"` bir METRIK etiketidir,
            # tel kodu degildir.
            self._refuse(sid, "no_capabilities", "declare at least one capability")
            return

        # Sayac KAYITTAN DUSMEYLE geri gitmez: yeniden baglanan bir servis
        # her zaman YENI bir worker id alir, backend'de de oyle (ULID).
        worker_id = f"FAKEWORKER{len(self._bridge.registrations) + 1:04d}"
        # `server.rs:1000-1008`: hosgeldin TELE CIKTIKTAN SONRA kaydedilir.
        self._send(
            sid,
            {"type": "welcome", "worker_id": worker_id, "protocol": config.protocol},
            end=False,  # Kontrol akisi omur boyu ACIK kalir.
        )
        self.worker = WorkerRecord(worker_id, hello, self)
        self._bridge._register(self.worker)

    def _refuse(self, sid: int, code: str, message: str) -> None:
        """`server.rs:1030-1046`: red cercevesini yaz, akisi bitir, baglantiyi kapat."""
        self._bridge.rejects.append(code)
        try:
            self._send(sid, {"type": "rejected", "code": code, "message": message}, end=True)
        except Exception:
            pass
        # Backend cerceveye 200 ms tanir, sonra baglantiyi kapatir. Burada da
        # kapanisi geciktiriyoruz ki istemci gercek sebebi gorsun, ciplak bir
        # sifirlama degil.
        self._spawn(self._close_after_refusal(message))

    async def _close_after_refusal(self, message: str) -> None:
        await asyncio.sleep(0.2)
        self._quic.close(error_code=1, reason_phrase=message[:100])
        self.transmit()

    # -- istemci baslatimli akislar: `server.rs:serve_client_stream` --

    async def _serve_client_stream(self, sid: int, reader: _Reader) -> None:
        try:
            raw = await reader.read_frame()
        except (EOFError, ValueError, json.JSONDecodeError) as exc:
            self._send(sid, _api_err("", "", "malformed", str(exc)), end=True)
            return
        if not isinstance(raw, dict):
            self._send(sid, _api_err("", "", "malformed", "cerceve bir nesne degil"), end=True)
            return
        # Red cercevesi `id` ve `school`'u OLDUGU GIBI yankilar, daha slug
        # oldugu bilinmeden (`server.rs:477-482`).
        request_id = raw.get("id") if isinstance(raw.get("id"), str) else ""
        school = raw.get("school") if isinstance(raw.get("school"), str) else ""

        # Sekil, ZORUNLU alaniyla ayirt edilir; `path` her zaman kazanir
        # (`server.rs:484-497`).
        if "path" in raw:
            if raw.get("path") in self._bridge.config.silent_paths:
                # Cevapsiz kalan bir akis: istemci zaman asimina ugramali ve
                # akisi birakmali, sonsuza kadar beklememeli.
                self._bridge.silent_reads.append(str(raw.get("path")))
                return
            self._send(sid, self._read_api(request_id, school, raw), end=True)
            return
        if "file" in raw:
            await self._serve_blob(sid, request_id, school, raw)
            return
        self._send(sid, _api_err(request_id, school, "malformed", "ne path ne file"), end=True)

    def _school_error(self, school: str) -> tuple[str, str] | None:
        """`server.rs:80-100`: slug cozumlemesinin uc ayri kodu.

        `malformed` servisin kendi hatasidir (o dize bir slug degil),
        `unknown_school` dagitimda oyle bir musteri yoktur, `school_suspended`
        vardir ama kapalidir -- ilk ikisini sonsuza dek yeniden denemek bir sey
        ogretmez, ucuncusu sonra denemeye degerdir.
        """
        if not school or "/" in school or " " in school:
            return ("malformed", f"`{school}` is not a school slug")
        if school in self._bridge.config.suspended_schools:
            return ("school_suspended", f"the `{school}` school is suspended")
        if school not in self._bridge.config.schools:
            return ("unknown_school", f"this deployment serves no `{school}` school")
        return None

    def _read_api(self, request_id: str, school: str, raw: dict) -> dict[str, Any]:
        """`server.rs:read_api` + `dispatch_api`."""
        path = raw.get("path")
        if not isinstance(path, str) or not path:
            return _api_err(request_id, school, "malformed", "'path' metin olmali")
        method = raw.get("method")

        # SIRA SOZLESMEDIR (`server.rs:715-733`): once yontem, sonra izin
        # listesi. Reddedilen bir yol router'a HIC verilmez.
        if method is not None and method != "GET":
            return _api_err(
                request_id,
                school,
                "method_not_allowed",
                f"the api bridge reads only — `{method}` is never dispatched",
            )
        if not path_allowed(path):
            return _api_err(
                request_id,
                school,
                "path_not_allowed",
                f"`{path}` is not a path AI services may read",
            )
        # Okul, izin listesinden SONRA cozulur -- backend'de de oyle: yol
        # reddiyse hicbir okul veritabanina dokunulmaz.
        refusal = self._school_error(school)
        if refusal is not None:
            return _api_err(request_id, school, refusal[0], refusal[1])

        self._bridge.api_reads.append((school, path, raw.get("query"), raw.get("on_behalf_of")))
        status, body = self._bridge.config.api_bodies.get(
            (school, path), (404, {"error": "not found"})
        )
        return {
            "outcome": "ok",
            "id": request_id,
            "school": school,
            "status": status,
            "body": body,
        }

    async def _serve_blob(self, sid: int, request_id: str, school: str, raw: dict) -> None:
        """`server.rs:serve_blob` + `open_blob`."""
        file_id = raw.get("file")
        if not isinstance(file_id, str) or not file_id:
            self._send(sid, _blob_err(request_id, school, "malformed", "'file' metin olmali"), True)
            return
        refusal = self._school_error(school)
        if refusal is not None:
            self._send(sid, _blob_err(request_id, school, refusal[0], refusal[1]), True)
            return
        entry = self._bridge.config.blobs.get((school, file_id))
        if entry is None:
            self._send(
                sid,
                _blob_err(request_id, school, "not_found", f"no course note file `{file_id}`"),
                True,
            )
            return
        if not raw.get("on_behalf_of"):
            # `protocol.rs:236-239`: `ai` rolu hicbir dersi goremez, dolayisiyla
            # `on_behalf_of` olmadan HER ZAMAN `forbidden` alinir.
            self._send(
                sid,
                _blob_err(
                    request_id, school, "forbidden", "`ai_service` may not view the course"
                ),
                True,
            )
            return

        name, content_type, data = entry
        self._bridge.blob_reads.append((school, file_id, raw.get("on_behalf_of")))
        header = {
            "status": "ok",
            "id": request_id,
            "school": school,
            "name": name,
            "content_type": content_type,
            # `size` diskteki dosyadan alinir; tam bu kadar bayt YAZILIR
            # (`server.rs:640-650`).
            "size": len(data),
        }
        self._send(sid, header, end=False)
        # Govde HAM bayt olarak, 64 KiB'lik parcalar halinde akar
        # (`server.rs:558-586`); cerceve DEGILDIR.
        chunk = 64 * 1024
        for offset in range(0, len(data), chunk):
            piece = data[offset : offset + chunk]
            self._send_raw(sid, piece, end=False)
            await asyncio.sleep(0)
        self._send_raw(sid, b"", end=True)

    # -- sunucu baslatimli akis: `AiBridge::dispatch_with_timeout` --

    async def call(
        self,
        school: str,
        capability: str,
        payload: Any,
        deadline_ms: int = 30_000,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Bir `Request` gonder, bir `Response` oku (`server.rs:258-283`)."""
        sid = self._quic.get_next_available_stream_id(is_unidirectional=False)
        reader = _Reader()
        self._readers[sid] = reader
        request_id = f"FAKEREQ{len(self._bridge.dispatches) + 1:04d}"
        self._bridge.dispatches.append((school, capability))
        # FIN, servise istegin tamamlandigini soyler (`server.rs:265-268`).
        self._send(
            sid,
            {
                "id": request_id,
                "school": school,
                "capability": capability,
                "deadline_ms": deadline_ms,
                "payload": payload,
            },
            end=True,
        )
        try:
            return await asyncio.wait_for(reader.read_frame(), timeout=timeout)
        finally:
            self._readers.pop(sid, None)

    async def send_oversize_frame_header(self, timeout: float = 10.0) -> dict[str, Any]:
        """Yalnizca 4 baytlik, sinirdan BUYUK bir uzunluk oneki yaz ve cevabi oku.

        Backend BUNU YAPMAZ -- `write_frame` boyutu yazmadan once denetler
        (`protocol.rs:275-277`). Kotu niyetli ya da bozuk bir es taklit edilir:
        istemci govdeyi AYIRMADAN reddetmeli (`protocol.rs:286-289`) ve akisi
        asili birakmak yerine bir hata cercevesiyle kapatmalidir.

        Govde HIC YAZILMAZ: istemci bir bayt govde beklemeden karar vermelidir.
        """
        sid = self._quic.get_next_available_stream_id(is_unidirectional=False)
        reader = _Reader()
        self._readers[sid] = reader
        self._send_raw(sid, struct.pack(">I", AI_MAX_FRAME_BYTES + 1), end=False)
        try:
            return await asyncio.wait_for(reader.read_frame(), timeout=timeout)
        finally:
            self._readers.pop(sid, None)


def _api_err(request_id: str, school: str, code: str, message: str) -> dict[str, Any]:
    """`ApiResponse::Err` -- etiket `outcome` (`protocol.rs:200`)."""
    return {
        "outcome": "err",
        "id": request_id,
        "school": school,
        "code": code,
        "message": message,
    }


def _blob_err(request_id: str, school: str, code: str, message: str) -> dict[str, Any]:
    """`BlobResponse::Err` -- etiket `status` (`protocol.rs:246`)."""
    return {
        "status": "err",
        "id": request_id,
        "school": school,
        "code": code,
        "message": message,
    }


# --- sertifika HTTP ucu ----------------------------------------------------


class _CertificateHandler(BaseHTTPRequestHandler):
    """`GET /ai/certificate` -- `src/web/ai.rs:76-83`."""

    payload: bytes = b"{}"

    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler sozlesmesi)
        if self.path != CERTIFICATE_PATH:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, *args: Any) -> None:
        """Test ciktisini kirletmesin."""


# --- sunucu --------------------------------------------------------------


class FakeBridge:
    """Ayaga kaldirilip indirilebilen sahte bir kopru.

    `start()` iki soket acar: QUIC (UDP) ve sertifika icin duz HTTP (TCP).
    Ikisi de 127.0.0.1 uzerinde ve isletim sisteminin verdigi bos porttadir --
    disariya HICBIR baglanti kurulmaz.
    """

    def __init__(self, config: FakeBridgeConfig | None = None) -> None:
        self.config = config or FakeBridgeConfig()
        self.certificate = generate()
        #: SU AN kayitli olan servisler; baglanti kopunca kucululur.
        self.workers: list[WorkerRecord] = []
        #: Simdiye kadar kaydolmus HER servis; asla kucululmez. Testler oturum
        #: kapandiktan sonra da el sikismanin olduguna buradan bakar.
        self.registrations: list[WorkerRecord] = []
        self.hellos: list[dict[str, Any]] = []
        self.rejects: list[str] = []
        self.api_reads: list[tuple[str, str, Any, Any]] = []
        self.blob_reads: list[tuple[str, str, Any]] = []
        self.silent_reads: list[str] = []
        self.dispatches: list[tuple[str, str]] = []
        self._server: Any = None
        self._http: ThreadingHTTPServer | None = None
        self._http_thread: threading.Thread | None = None
        self._connections: set[_BridgeConnection] = set()
        self._worker_event = asyncio.Event()

    # -- yasam dongusu --

    async def start(self) -> None:
        quic_config = QuicConfiguration(
            is_client=False,
            # ALPN SURUM KAPISIDIR (`tls.rs:80-83`): farkli bir kimlik
            # bildiren servis TLS el sikismasinda reddedilir.
            alpn_protocols=[AI_ALPN],
            idle_timeout=AI_IDLE_TIMEOUT_SECS,
        )
        # `QuicConfiguration.load_cert_chain()` yalnizca DOSYADAN okur ve PEM'i
        # `\n` sinirlarina gore boler; Windows'ta metin kipinde yazilan bir
        # dosya CRLF tasir ve ozel anahtar SESSIZCE bulunamaz. Bu yuzden dosya
        # hic kullanilmiyor: alanlar dogrudan dolduruluyor.
        chain = load_pem_x509_certificates(self.certificate.cert_pem.encode("ascii"))
        quic_config.certificate = chain[0]
        quic_config.certificate_chain = chain[1:]
        quic_config.private_key = load_pem_private_key(
            self.certificate.key_pem.encode("ascii")
        )

        self._server = await serve(
            "127.0.0.1",
            0,
            configuration=quic_config,
            create_protocol=partial(_BridgeConnection, bridge=self),
        )
        self._start_http()

    def _start_http(self) -> None:
        body = json.dumps(
            {
                "certificate_pem": self.certificate.cert_pem,
                "fingerprint_sha256": self.certificate.fingerprint,
            }
        ).encode("utf-8")
        handler = type("_Handler", (_CertificateHandler,), {"payload": body})
        self._http = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._http_thread = threading.Thread(target=self._http.serve_forever, daemon=True)
        self._http_thread.start()

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        if self._http is not None:
            http, thread = self._http, self._http_thread
            self._http, self._http_thread = None, None

            def _shutdown() -> None:
                http.shutdown()
                http.server_close()
                if thread is not None:
                    thread.join(timeout=5)

            # Olay dongusunu bloke etmemek icin ayri bir is parcaciginda:
            # `shutdown()` sunucu dongusunun durmasini BEKLER.
            await asyncio.get_running_loop().run_in_executor(None, _shutdown)
        # Olay dongusunun kapanis datagramlarini yollamasina izin ver.
        await asyncio.sleep(0)

    # -- adresler --

    @property
    def quic_port(self) -> int:
        sock = self._server._transport.get_extra_info("socket")
        return int(sock.getsockname()[1])

    @property
    def http_port(self) -> int:
        assert self._http is not None
        return int(self._http.server_address[1])

    @property
    def backend_url(self) -> str:
        return f"http://127.0.0.1:{self.http_port}"

    # -- kayit defteri --

    def _register(self, worker: WorkerRecord) -> None:
        self.workers.append(worker)
        self.registrations.append(worker)
        self._connections.add(worker.connection)
        self._worker_event.set()

    def _deregister(self, worker: WorkerRecord) -> None:
        self._connections.discard(worker.connection)
        # Kontrol akisinin olumu kayittan dusme sinyalidir (`protocol.rs:12-14`).
        self.workers = [w for w in self.workers if w.worker_id != worker.worker_id]
        if not self.workers:
            self._worker_event.clear()

    async def wait_for_worker(self, timeout: float = 10.0) -> WorkerRecord:
        """Bir servis kaydolana kadar bekle."""
        await asyncio.wait_for(self._worker_event.wait(), timeout=timeout)
        return self.workers[-1]

    async def wait_for_reject(self, timeout: float = 10.0) -> str:
        """Bir el sikisma reddi uretilene kadar bekle ve kodunu dondur."""
        deadline = asyncio.get_running_loop().time() + timeout
        while not self.rejects:
            if asyncio.get_running_loop().time() > deadline:
                raise asyncio.TimeoutError("hicbir red uretilmedi")
            await asyncio.sleep(0.02)
        return self.rejects[-1]

    def drop_connections(self) -> None:
        """Her servis baglantisini kopar -- backend'in cokmesini taklit eder."""
        for connection in list(self._connections):
            connection.close()
            connection.transmit()
        self._connections.clear()

    async def call(
        self, capability: str, school: str, payload: Any, deadline_ms: int = 30_000
    ) -> dict[str, Any]:
        """Kayitli son worker'a sunucu baslatimli bir istek yolla."""
        worker = self.workers[-1]
        return await worker.connection.call(school, capability, payload, deadline_ms)


async def run_fake_bridge(
    config: FakeBridgeConfig | None = None,
) -> tuple[FakeBridge, Callable[[], Any]]:
    """Kolaylik: ayaga kaldir ve kapatma cagrisiyla birlikte dondur."""
    bridge = FakeBridge(config)
    await bridge.start()
    return bridge, bridge.stop
