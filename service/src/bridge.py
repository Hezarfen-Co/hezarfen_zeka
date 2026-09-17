"""ZEKA'nin QUIC istemcisi -- backend'in AI koprusune dial-out eder.

Sekil (`ai/protocol.rs:3-7`): backend QUIC SUNUCUSUDUR, servisler ona baglanir.
Bu yuzden ZEKA hicbir port acmaz; NAT ardinda yasayabilir ve serbestce yeniden
baslayabilir.

Desen podcast'in `src/bridge.py` dosyasindan alinmistir; UC yerde kasitli olarak
ayrilir:

1. **Protokol `hab/2`** (`constant.rs:530-531`). Podcast ve Celebi `hab/1`
   kullaniyor; bu ALPN muzakeresinde reddedilir, baglanti hic kurulmaz.
2. **Her cerceve okulunu adlandirir.** `hab/1` istemcilerinde `school` alani
   yoktu; `hab/2`'de zorunludur ve varsayilani yoktur (`protocol.rs:36-47`).
3. **Red halinde CIKMIYORUZ.** Podcast `unsupported_protocol` alinca `exit 2`
   yapiyor; `restart: unless-stopped` ile bu sonsuz bir crash-loop uretir ve
   backend duzeltildiginde servis kendiliginden toparlanmaz. Biz kodu loglayip
   USTEL GERI CEKILMEYLE yeniden deniyoruz.

Ayrica bir de TLS notu vardir; `fetch_certificate()` docstring'ine bakin.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import inspect
import json
import random
import ssl
import sys
import urllib.error
import urllib.request
from functools import partial
from typing import Any, Callable

from aioquic.asyncio import connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import ConnectionTerminated, QuicEvent, StreamDataReceived

from . import capabilities, config, protocol
from .protocol import (
    ApiRefused,
    ApiResponse,
    Blob,
    BlobRefused,
    CapabilityError,
    FrameStream,
    HandshakeRejected,
)

RequestHandler = Callable[[protocol.Request], Any]
"""Backend'den gelen bir `Request`'i karsilayan kanca.

Es zamanli (`def`) ya da es zamansiz (`async def`) olabilir; `_handle()` ikisini
de kabul eder. Varsayilani `capabilities.dispatch`'e giden bir koprudir.

BUGUN CAGRILMAZ: backend ZEKA'nin yeteneklerini tanimiyor (bkz.
`capabilities.py` basi). Sozlesme yine de dogru kuruludur.
"""


# --- sertifika -------------------------------------------------------------


def _leaf_der_from_pem(pem: str) -> bytes:
    """PEM zincirinin ILK sertifikasini DER olarak cikar.

    Backend'in parmak izi tam olarak bunun SHA-256'sidir (`ai/tls.rs:150-153`:
    `hex::encode(Sha256::digest(leaf.as_ref()))`) -- kucuk harf hex, iki nokta
    yok.
    """
    marker_begin = "-----BEGIN CERTIFICATE-----"
    marker_end = "-----END CERTIFICATE-----"
    start = pem.find(marker_begin)
    end = pem.find(marker_end, start + 1)
    if start < 0 or end < 0:
        raise RuntimeError("sertifika PEM govdesi bulunamadi")
    body = pem[start + len(marker_begin) : end]
    try:
        return base64.b64decode("".join(body.split()))
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError(f"sertifika PEM govdesi base64 degil: {exc}") from exc


def fetch_certificate(settings: config.Config) -> str:
    """`GET /ai/certificate` ile kopru sertifikasini cek.

    HER YENIDEN BAGLANMADA cagrilir, yalnizca acilista degil: `AI_TLS_CERT` ve
    `AI_TLS_KEY` ikisi de bos ise backend her boot'ta kendi sertifikasini
    YENIDEN uretir (`ai/tls.rs:37-46`), yani eski PEM'e guvenmek baglantiyi
    kirar.

    --- GUVENLIK GEREKCESI ---
    Bu cagri DUZ HTTP'dir. Podcast ve Celebi tam olarak bunu yapiyor ve bu
    denetimde TOFU (trust-on-first-use) zafiyeti olarak isaretlendi: adres
    dogrulanmadigi icin ag icinde araya giren biri kendi sertifikasini servise
    pinletebilir ve butun QUIC trafigini okuyabilir. Sertifikayi PINLEMEK tek
    basina yetmiyor; DOGRU sertifikayi pinledigimizi bilmemiz gerekiyor.

    Cozum, geriye donuk uyumlulugu kirmadan: `AI_TLS_FINGERPRINT` verilmemisse
    eski (TOFU) davranis aynen surer -- yeni servisin dagitimi eskisinden zor
    olmasin diye. Verilmisse, PEM'den DER'i cikarip SHA-256'sini KENDIMIZ
    hesaplar ve beklenenle karsilastiririz; uyusmazsa BAGLANMAYIZ.

    Sunucunun bildirdigi `fingerprint_sha256` alani dogrulama icin KULLANILMAZ:
    sertifikayi uyduran taraf onun yanindaki parmak izini de uydurur. O alan
    yalnizca loglanir ve bizim hesabimizla capraz denetlenir.
    """
    url = f"{settings.backend_url}{protocol.CERTIFICATE_PATH}"
    with urllib.request.urlopen(url, timeout=config.CERT_FETCH_TIMEOUT_SECS) as resp:
        data = json.loads(resp.read())
    pem = data.get("certificate_pem")
    if not pem:
        raise RuntimeError(f"{url} beklenen certificate_pem alanini dondurmedi")

    computed = hashlib.sha256(_leaf_der_from_pem(pem)).hexdigest()
    reported = str(data.get("fingerprint_sha256", "")).strip().lower().replace(":", "")
    if reported and reported != computed:
        # Sunucunun kendi beyani kendi PEM'iyle tutmuyor: ya bozuk bir dagitim
        # ya da yolda degistirilmis bir cevap. Ikisinde de baglanmiyoruz.
        raise RuntimeError(
            "sertifika tutarsiz: bildirilen parmak izi PEM'den hesaplananla uyusmuyor "
            f"(bildirilen {reported[:12]}, hesaplanan {computed[:12]})"
        )

    if settings.tls_fingerprint:
        if computed != settings.tls_fingerprint:
            raise RuntimeError(
                "sertifika parmak izi PINLENEN degerle uyusmuyor; baglanilmiyor "
                f"(beklenen {settings.tls_fingerprint[:12]}, gelen {computed[:12]})"
            )
        config.log("info", f"sertifika alindi ve PINLENDI (fingerprint {computed[:12]})")
    else:
        # Bilinci acik bir taviz, sessiz bir varsayilan degil: her acilista
        # loglanir ki operator neyi kapali biraktigini bilsin.
        config.log(
            "warn",
            f"sertifika alindi (fingerprint {computed[:12]}) -- AI_TLS_FINGERPRINT "
            "tanimsiz, TOFU ile guveniliyor; uretimde parmak izini pinleyin",
        )
    return pem


def build_quic_configuration(settings: config.Config, cert_pem: str) -> QuicConfiguration:
    """ALPN `hab/2`, sertifika dogrulamasi ACIK, bosta kalma suresi backend'inki."""
    quic_config = QuicConfiguration(is_client=True, alpn_protocols=[protocol.AI_ALPN])
    quic_config.server_name = settings.server_name
    quic_config.verify_mode = ssl.CERT_REQUIRED
    # `cadata` BAYT olmali: aioquic onu dogrudan `load_pem_x509_certificates`e
    # verir ve orada `bytes.split(b"-----BEGIN CERTIFICATE-----")` cagrilir
    # (aioquic/tls.py:211). Metin gecirmek `TypeError: must be str or None, not
    # bytes` ile HER baglantiyi dusurur -- sessizce degil, ama hicbir zaman
    # kosulmadigi icin de hic gorulmemisti.
    quic_config.load_verify_locations(cadata=cert_pem.encode("ascii"))
    quic_config.idle_timeout = protocol.AI_IDLE_TIMEOUT_SECS
    return quic_config


# --- baglanti --------------------------------------------------------------


class BridgeProtocol(QuicConnectionProtocol):
    """Tek bir QUIC baglantisi: kontrol akisi + istek/okuma akislari."""

    def __init__(
        self,
        *args: Any,
        settings: config.Config,
        handler: RequestHandler | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._settings = settings
        self._handler = handler or _default_handler
        self._streams: dict[int, FrameStream] = {}
        self._control_sid: int | None = None
        self._ping_uid = 0
        self._inflight = 0
        self._tasks: set[asyncio.Future] = set()
        self.worker_id = ""

    # -- olay dongusu --

    def quic_event_received(self, event: QuicEvent) -> None:
        if isinstance(event, StreamDataReceived):
            sid = event.stream_id
            stream = self._streams.get(sid)
            if stream is None:
                # QUIC akis kimligi: alt iki bit yonu ve tipi soyler.
                # 0 = istemci baslatimli cift yonlu (bizim actigimiz),
                # 1 = sunucu baslatimli cift yonlu (backend'in is akisi).
                # Tek yonlu akislar (2, 3) bu protokolde kullanilmaz.
                #
                # Istemci baslatimli bir akisi YALNIZCA BIZ aciyoruz ve okuyucusunu
                # acarken kaydediyoruz. Kaydi yoksa o akis TERK EDILMISTIR (zaman
                # asimi ya da hata) -- gec gelen baytlar icin yeni bir okuyucu
                # kurmak, kimsenin okumayacagi bir tamponu baglantinin omru
                # boyunca tutmak olurdu. Duser.
                if sid % 4 != 1:
                    return
                stream = FrameStream()
                self._streams[sid] = stream
                task = asyncio.ensure_future(self._serve_request(sid, stream))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
            stream.feed(event.data, event.end_stream)
        elif isinstance(event, ConnectionTerminated):
            # Bekleyen her okuyucuya EOF ver; yoksa sonsuza kadar beklerler.
            for stream in self._streams.values():
                stream.feed(b"", end=True)

    def _send_frame(self, sid: int, obj: Any, end: bool) -> None:
        self._quic.send_stream_data(sid, protocol.encode_frame(obj), end_stream=end)
        self.transmit()

    def _abandon(self, sid: int) -> None:
        """Yarida birakilan bir okuma akisini kapat.

        Okuyucuyu unutmak tek basina yetmez: backend hala YAZIYOR olabilir.
        Blob yolunda bu, akis penceresi dolana kadar bir acik dosyayi ve bir
        gorevi bagli tutar; backend zaten tam bunun icin tikanma kapagi koymus
        (`ai/server.rs:558-586`, `constant.rs:563`). STOP_SENDING gondermek,
        karsi tarafa hemen birakmasini soyler.
        """
        self._streams.pop(sid, None)
        try:
            self._quic.stop_stream(sid, error_code=0)
            self.transmit()
        except Exception:
            # Akis coktan kapanmis olabilir; terk etme en iyi caba isidir ve
            # asil hatanin ustune yeni bir hata bindirmemelidir.
            pass

    # -- kontrol akisi --

    async def register(self) -> str:
        """Ilk istemci baslatimli akisi ac, `Hello` yaz, `Greeting` oku.

        Akis KAPATILMAZ (`end=False`): omur boyu acik kalir ve kapanmasi
        backend icin kayittan dusme sinyalidir (`ai/protocol.rs:11-14`).
        """
        sid = self._quic.get_next_available_stream_id()
        self._control_sid = sid
        stream = FrameStream()
        self._streams[sid] = stream
        hello = protocol.build_hello(
            self._settings.service,
            capabilities.names(),
            self._settings.token,
            self._settings.max_concurrent,
        )
        self._send_frame(sid, hello, end=False)
        greeting = await asyncio.wait_for(
            stream.read_frame(), timeout=protocol.GREETING_TIMEOUT_SECS
        )
        self.worker_id = protocol.parse_greeting(greeting)
        config.log(
            "info",
            f"kayit basarili: worker_id={self.worker_id} protokol={protocol.AI_PROTOCOL} "
            f"yetenekler={','.join(capabilities.names())}",
        )
        return self.worker_id

    async def keepalive(self) -> None:
        """QUIC PING. Uygulama seviyesinde heartbeat CERCEVESI yoktur
        (`ai/protocol.rs:13-14`); bosta kalma zaman asimini bu onler."""
        while True:
            await asyncio.sleep(protocol.AI_KEEPALIVE_SECS)
            self._ping_uid += 1
            try:
                self._quic.send_ping(self._ping_uid)
                self.transmit()
            except Exception:
                return

    # -- okuma yonu: servisin actigi akislar --

    async def api_get(
        self,
        school: str,
        path: str,
        query: str | None = None,
        on_behalf_of: str | None = None,
        timeout: float | None = None,
    ) -> ApiResponse:
        """Okulun kendi API'sinden bir GET oku.

        Yeni bir istemci baslatimli cift yonlu akis acilir, tek bir `ApiRequest`
        yazilir, gonderme tarafi kapatilir (`end=True`) ve tek bir `ApiResponse`
        okunur (`ai/protocol.rs:19-23`).

        `school` ZORUNLUDUR ve varsayilani yoktur: yanlis okulun veritabanindan
        cevaplanan bir okuma, bu alanin var olma sebebidir (`protocol.rs:44-47`).

        Yol izin listesi denetimi `build_api_request()` icinde, tele CIKMADAN
        once yapilir; izinsiz bir yol icin `ApiRefused(path_not_allowed)` firlar.

        HTTP 404 hata DEGILDIR: router calisti ve cevap verdi, bu bir `ok`'tur
        ve `response.status` alaninda tasinir.
        """
        budget = self._settings.api_timeout_secs if timeout is None else timeout
        request = protocol.build_api_request(
            protocol.new_trace_id(), school, path, query, on_behalf_of
        )
        sid = self._quic.get_next_available_stream_id()
        stream = FrameStream()
        self._streams[sid] = stream
        answered = False
        try:
            self._send_frame(sid, request, end=True)
            frame = await asyncio.wait_for(stream.read_frame(), timeout=budget)
            answered = True
        finally:
            if answered:
                self._streams.pop(sid, None)
            else:
                self._abandon(sid)
        response = protocol.parse_api_response(frame)
        config.log(
            "debug",
            f"api okul={school} {path} -> status={response.status} "
            f"kim={on_behalf_of or 'servis(ai rolu)'}",
        )
        return response

    async def call_capability(
        self,
        capability: str,
        school: str,
        payload: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Backend'in bir operasyonunu cagir (`insight.*`) ve payload'ini don.

        ZEKA'nin veritabani erisimi YOKTUR; hesapladigi satirlari ve okudugu
        listeleri bu metot tasir. `store.BridgeStore` bu metodun TEK
        kullanicisidir; depo onu `BridgeCaller` protokolu uzerinden gorur.

        `api_get` ile ayni desen: taze istemci baslatimli cift yonlu akis, tek
        cerceve yaz, gonderim tarafini kapat (`end=True`), tek cerceve oku,
        akisi dusur. Korelasyonu AKIS yapar; `id` yalniz iz kimligidir.

        `school` BOS olabilir: deployment olcekli tek operasyon
        (`insight.schools.list`) okul adlandirmaz.

        Red (`status: "err"`) `protocol.CapabilityRefused` olarak yukselir --
        `status` ONCE okunur, cunku reddi basari saymak sessiz yazma kaybidir.
        """
        budget = self._settings.api_timeout_secs if timeout is None else timeout
        request = protocol.build_capability_request(
            protocol.new_trace_id(), capability, school, payload or {}
        )
        sid = self._quic.get_next_available_stream_id()
        stream = FrameStream()
        self._streams[sid] = stream
        answered = False
        try:
            self._send_frame(sid, request, end=True)
            frame = await asyncio.wait_for(stream.read_frame(), timeout=budget)
            answered = True
        finally:
            if answered:
                self._streams.pop(sid, None)
            else:
                self._abandon(sid)
        response = protocol.parse_capability_response(frame)
        result = response.raise_for_status(capability)
        config.log(
            "debug",
            f"yetenek {capability} okul={school or '(deployment)'} -> ok",
        )
        return result

    async def blob_get(
        self,
        school: str,
        file: str,
        on_behalf_of: str | None = None,
        timeout: float | None = None,
    ) -> Blob:
        """Bir ders notu dosyasinin BAYTLARINI oku.

        Ayni yon, kendi akisinda: bir `BlobRequest` yazilir, bir `BlobResponse`
        BASLIK cercevesi okunur, `ok` ise tam `size` HAM bayt onu izler ve akis
        biter (`ai/protocol.rs:25-31`). Bu baytlar cerceve DEGILDIR, bu yuzden
        `AI_MAX_FRAME_BYTES` onlari sinirlamaz -- bir PDF hicbir cerceveye
        sigmaz, bu yol tam bunun icin vardir.

        `on_behalf_of` pratikte zorunludur: `ai` rolu hicbir dersi goremez ve
        onsuz her zaman `forbidden` alinir (`ai/protocol.rs:236-239`).
        """
        budget = self._settings.blob_timeout_secs if timeout is None else timeout
        request = protocol.build_blob_request(
            protocol.new_trace_id(), school, file, on_behalf_of
        )
        sid = self._quic.get_next_available_stream_id()
        stream = FrameStream()
        self._streams[sid] = stream
        complete = False
        try:
            self._send_frame(sid, request, end=True)
            header_frame = await asyncio.wait_for(stream.read_frame(), timeout=budget)
            header = protocol.parse_blob_response(header_frame)
            # Baslik ne vaat ettiyse TAM o kadar bayt okunur; eksik okumak
            # sessizce kirpilmis bir dosya demektir (`ai/server.rs:546-552`).
            data = await asyncio.wait_for(stream.read_exact(header.size), timeout=budget)
            complete = True
        finally:
            if complete:
                self._streams.pop(sid, None)
            else:
                # Govde yarida kaldi: backend'in yazicisini bosuna bekletme.
                self._abandon(sid)
        config.log(
            "debug",
            f"blob okul={school} dosya={file} -> {header.size} bayt "
            f"tip={header.content_type} kim={on_behalf_of or 'servis(ai rolu)'}",
        )
        return Blob(header=header, data=data)

    # -- is yonu: backend'in actigi akislar --

    async def _serve_request(self, sid: int, stream: FrameStream) -> None:
        """Sunucu baslatimli bir akista gelen tek `Request`'i karsila.

        BUGUN BURAYA HIC GELINMEZ: backend ZEKA'nin yeteneklerini tanimiyor,
        dolayisiyla ZEKA'ya `Request` gondermez (bkz. `capabilities.py` basi).
        Sozlesme yine de eksiksiz kurulur ki backend adlari tanidigi gun bu
        dosyada degisiklik gerekmesin.
        """
        request_id = ""
        school = ""
        try:
            frame = await stream.read_frame()
            if isinstance(frame, dict):
                # Ayristirma basarisiz olsa bile `id` ve `school` yankilanabilsin.
                request_id = str(frame.get("id", "") or "")
                school = str(frame.get("school", "") or "")
            request = protocol.Request.from_wire(frame)
        except EOFError as exc:
            config.log("warn", f"istek {sid} okunamadi: {exc}")
            self._streams.pop(sid, None)
            return
        except (protocol.ProtocolError, ValueError) as exc:
            code = getattr(exc, "code", protocol.ApiErrorCode.MALFORMED)
            config.log("warn", f"istek {sid} ayristirilamadi: {exc}")
            self._finish(sid, protocol.err_response(request_id, school, code, str(exc)))
            return

        request_id, school = request.id, request.school
        if self._inflight >= self._settings.max_concurrent:
            # `Hello.max_concurrent` bir vaattir; asildiginda gec cevap yerine
            # acik bir `busy` donuyoruz.
            self._finish(
                sid,
                protocol.err_response(
                    request_id, school, "busy", "worker es zamanli istek sinirinda"
                ),
            )
            return

        self._inflight += 1
        try:
            config.log(
                "debug",
                f"istek {request_id} okul={school} yetenek={request.capability}",
            )
            result = await asyncio.wait_for(
                self._handle(request), timeout=request.timeout_secs
            )
            response = protocol.ok_response(request_id, school, result)
        except (CapabilityError, protocol.ApiRefused) as exc:
            # Disariya cikan yetenek cagrisinin redleri (`ApiRefused`,
            # dolayisiyla `CapabilityRefused`) ve isleyicinin kendi redleri
            # backend'e AYNEN gider: `unavailable`, `timed_out` gibi kodlar
            # backend'in yeniden deneme kararini etkiler. `internal` yalnizca
            # TANINMAYAN hatalar icin.
            response = protocol.err_response(request_id, school, exc.code, str(exc))
        except asyncio.TimeoutError:
            response = protocol.err_response(
                request_id, school, "timed_out", "istek sure icinde tamamlanamadi"
            )
        except Exception as exc:
            config.log("error", f"istek {request_id} islenemedi: {exc}")
            response = protocol.err_response(
                request_id, school, "internal", "beklenmeyen hata"
            )
        finally:
            self._inflight -= 1
        self._finish(sid, response)

    async def _handle(self, request: protocol.Request) -> Any:
        """Kancayi cagir. Es zamanli kanca varsayilan executor'a ATILIR.

        Es zamansiz (`async def`) kanca dogrudan beklenir. Es zamanli (`def`)
        kanca ise bir is parcacigina verilir -- cunku ZEKA'nin yetenekleri
        ogrenci verisi uzerinde ISLEMCI YOGUN hesaplardir ve olay dongusunde
        kosarlarsa `keepalive()` PING'lerini de durdururlar. Backend'in bosta
        kalma penceresi 30 s (`constant.rs:554`), PING araligi 10 s
        (`constant.rs:555`): 30 saniyeden uzun suren tek bir senkron yetenek,
        cevabini yazamadan baglantinin dusurulmesine yol acardi.
        """
        # `inspect` kullaniliyor: `asyncio.iscoroutinefunction` 3.16'da kalkiyor.
        if inspect.iscoroutinefunction(self._handler):
            return await self._handler(request)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, self._handler, request)
        # Senkron gorunup coroutine donduren bir kanca (ornegin `async def`
        # sarmalayan bir `partial`) da desteklenir.
        if asyncio.iscoroutine(result):
            return await result
        return result

    def _finish(self, sid: int, response: dict[str, Any]) -> None:
        try:
            self._send_frame(sid, response, end=True)
        except protocol.FrameTooLarge as exc:
            # Cevap kapagi asti: sessizce dusurmek yerine kucuk bir hata yaz,
            # yoksa backend akisi bekleyip zaman asimina ugrar.
            config.log("warn", f"cevap cerceve sinirini asti: {exc}")
            try:
                self._send_frame(
                    sid,
                    protocol.err_response(
                        str(response.get("id", "")),
                        str(response.get("school", "")),
                        "frame_too_large",
                        str(exc),
                    ),
                    end=True,
                )
            except Exception as inner:
                config.log("error", f"cevap yazilamadi: {inner}")
        except Exception as exc:
            config.log("error", f"cevap yazilamadi: {exc}")
        finally:
            self._streams.pop(sid, None)


def _default_handler(request: protocol.Request) -> Any:
    """Varsayilan kanca: yetenek defterine yonlendirir."""
    return capabilities.dispatch(request.capability, request.school, request.payload)


# --- yasam dongusu ---------------------------------------------------------


async def run_once(
    settings: config.Config,
    handler: RequestHandler | None = None,
    on_ready: Callable[[BridgeProtocol], Any] | None = None,
) -> None:
    """Sertifikayi cek, bagla, kaydol, baglanti kapanana kadar bekle."""
    cert_pem = fetch_certificate(settings)
    quic_config = build_quic_configuration(settings, cert_pem)
    config.log(
        "info",
        f"{settings.host}:{settings.port} adresine baglaniliyor (ALPN {protocol.AI_ALPN})",
    )
    create = partial(BridgeProtocol, settings=settings, handler=handler)
    async with connect(
        settings.host,
        settings.port,
        configuration=quic_config,
        create_protocol=create,
    ) as connection:
        assert isinstance(connection, BridgeProtocol)
        await connection.wait_connected()
        await connection.register()
        keepalive_task = asyncio.ensure_future(connection.keepalive())
        ready_task: asyncio.Future | None = None
        if on_ready is not None:
            result = on_ready(connection)
            if asyncio.iscoroutine(result):
                ready_task = asyncio.ensure_future(result)
        try:
            await connection.wait_closed()
        finally:
            keepalive_task.cancel()
            if ready_task is not None:
                ready_task.cancel()
    config.log("info", "baglanti kapandi")


async def one_shot(
    settings: config.Config, work: Callable[[BridgeProtocol], Any]
) -> Any:
    """Baglan, kaydol, `work(proto)` kos, baglantiyi KAPAT, sonucu don.

    Gelistirme araclari icin (`cli sweep`, `cli schedule`): uretim dongusu
    `run_forever` bir daha cikmaz, ama bir CLI komutu isini bitirip donmelidir.
    Bu yardimci tam olarak o farki kapatir ve AYNI istemciyi kullanir --
    ikinci bir tasima yazilmaz.

    Baglantiyi `work` icinde kapatmak yerine burada, `finally` ile kapatmak
    yanlis olurdu: `work` sirasinda kopru hala canli olmalidir.
    """
    box: dict[str, Any] = {}

    async def runner(proto: BridgeProtocol) -> None:
        try:
            box["result"] = await work(proto)
        finally:
            # Kayitli akisi kapatmak backend icin "duser" sinyalidir; komut
            # bitti, baglanti da bitmeli.
            proto.close()

    await run_once(settings, on_ready=runner)
    return box.get("result")


class OneShotCaller:
    """Her çağrı için taze bir köprü oturumu açan `BridgeCaller`.

    Geliştirme araçları için (`segment` hattının `--persist` yolu): araç
    senkron çalışır ve elinde yaşayan bir bağlantı yoktur. Çağrı başına
    bağlan-kaydol-kapat maliyeti bir araç için önemsizdir; ikinci bir taşıma
    yazmaktan iyidir — aynı `BridgeProtocol.call_capability` kullanılır.
    """

    def __init__(self, settings: config.Config) -> None:
        self._settings = settings

    async def call(
        self, capability: str, school: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        async def work(proto: BridgeProtocol) -> dict[str, Any]:
            return await proto.call_capability(
                capability,
                school,
                payload,
                timeout=self._settings.api_timeout_secs,
            )

        result = await one_shot(self._settings, work)
        if result is None:  # pragma: no cover - one_shot isi bitirmeden donmez
            raise RuntimeError("köprü oturumu sonuç döndürmedi")
        return result


def next_backoff(current: float, settings: config.Config) -> float:
    """Ustel geri cekilme: ikiye katla ve tavanda dur.

    JITTER BURADA EKLENMEZ -- `run_forever()` icinde, uyumadan hemen once
    eklenir. Sebebi: jitter bir sonraki beklemenin TABANINI kaydirmamalidir,
    yoksa rastgelelik birikerek gercek tavani asar. Bu fonksiyon deterministik
    kalir; rastgelelik yalnizca o anki uykuya uygulanir.

    Jitter'in kendisi, birden cok ZEKA ornegi ayni anda dusup ayni anda geri
    gelirse backend'i es zamanli bir dalgayla karsilamamak icindir.
    """
    doubled = min(current * 2.0, settings.reconnect_max_secs)
    return doubled


async def run_forever(
    settings: config.Config,
    handler: RequestHandler | None = None,
    on_ready: Callable[[BridgeProtocol], Any] | None = None,
) -> int:
    """Baglantiyi surekli ayakta tutar. HICBIR HATADA CIKMAZ.

    Podcast `unsupported_protocol` ya da `unauthorized` alinca `exit 2` yapiyor
    (`hezarfen_podcast_service/src/bridge.py`); `restart: unless-stopped` ile bu
    sonsuz bir crash-loop uretir ve backend duzeltildikten sonra servis
    kendiliginden toparlanmaz -- operatorun elle mudahalesi gerekir. Biz kodu
    loglayip beklemeyi tavana cekiyoruz: kalici bir red sirasinda gurultu
    yapmadan bekler, sorun duzelince kendiliginden baglaniriz.
    """
    config.log("info", f"ZEKA koprusu basliyor: {settings.summary()}")
    config.log("info", capabilities.summary())
    backoff = settings.reconnect_secs
    while True:
        try:
            await run_once(settings, handler=handler, on_ready=on_ready)
            # Saglikli bir oturumdan sonra bekleme sifirlanir.
            backoff = settings.reconnect_secs
        # SIRA ONEMLI: Python 3.11'den beri `asyncio.TimeoutError` yerlesik
        # `TimeoutError`'dir ve o da `OSError`'in alt sinifidir. Bu yuzden
        # zaman asimi yakalayicisi OSError'DAN ONCE gelmek zorunda; altina
        # konursa ERISILEMEZ olur ve el sikisma zaman asimi "backend'e
        # ulasilamadi" diye loglanir.
        except asyncio.TimeoutError:
            config.log("warn", "el sikisma zaman asimina ugradi")
            backoff = next_backoff(backoff, settings)
        except (urllib.error.URLError, ConnectionError, OSError) as exc:
            config.log("warn", f"backend'e ulasilamadi: {exc}")
            backoff = next_backoff(backoff, settings)
        except HandshakeRejected as exc:
            if exc.permanent:
                config.log(
                    "error",
                    f"{exc} -- yapilandirma degismeden duzelmez; "
                    "yine de cikmiyoruz, geri cekilerek yeniden denenecek",
                )
                backoff = settings.reconnect_max_secs
            else:
                config.log("error", str(exc))
                backoff = next_backoff(backoff, settings)
        except Exception as exc:
            config.log("error", f"baglanti hatasi: {exc}")
            backoff = next_backoff(backoff, settings)
        delay = backoff + random.uniform(0.0, min(backoff, 5.0))
        config.log("info", f"{delay:.1f}s sonra yeniden denenecek")
        await asyncio.sleep(delay)


async def _serve(settings: config.Config) -> int:
    """Kopruyu ve GECE ZAMANLAYICISINI birlikte kosturur.

    -----------------------------------------------------------------------
    ACILISTA ACILAN HICBIR SEY YOKTUR
    -----------------------------------------------------------------------
    ZEKA'nin veritabani erisimi yoktur (degismez kural: bir AI servisi
    uygulama veritabanina asla dogrudan erismez). Bu yuzden acilis bir
    baglanti KURMAZ: ne DSN, ne havuz, ne okul dizini. Okul listesi ilk tikte
    backend'den istenir (`insight.schools.list`).

    BACKEND YOKKEN DAVRANIS (uygulanan politika):
      * Acilis DUSER DEGIL. `run_forever` hicbir hatada cikmaz; ustel geri
        cekilmeyle yeniden dener (`bridge.run_forever`).
      * Zamanlayici turu okulsuz kosar: okul listesi okunamazsa `warn`
        loglanir ve tur bos doner (`scheduler._listing`). Crash-loop yok.
      * SESSIZ YAZMA YOK. Kopru kapaliyken bir yazma cagrisi
        `BridgeUnavailable` -> `CapabilityRefused("unavailable")` olur; grup
        `MAX_ATTEMPTS` kez denenir, sonra atlanir ve `WriteReport.status`
        `partial` olur -> kosu defterine `store` diye yazilir. "Basarili
        gorunen ama hicbir sey yazmamis" bir kosu uretilemez.

    -----------------------------------------------------------------------
    NEDEN IKISI BIRDEN
    -----------------------------------------------------------------------
    Kopru tek basina yalnizca BAGLANTIYI ayakta tutar ve backend'den gelen
    `Request` cercevesini karsilar. Ama backend bugun ZEKA'ya yalnizca
    `insight.student` / `insight.refresh` isleri yolluyor; zamanlayici
    bagli olmasaydi servis baglanir, kaydolur, "calisiyor" gorunur ve HICBIR
    SEY URETMEZDI -- `zeka_*` tablolari bos kalirdi.

    Ikisi ayri gorevde kosar: koprunun yeniden baglanmasi zamanlayiciyi
    durdurmaz, zamanlayicinin bir okulda dusmesi baglantiyi koparmaz.
    Okumalar da yazmalar da KOPRUDEN gider (`BridgeSource` -> `ApiRequest`,
    depo -> `CapabilityRequest`); REST'e ya da bir veritabanina cikan yol
    YOKTUR.
    """
    from .scheduler import Scheduler
    from .source import BridgeSource
    from .store import BridgeStore, ProtocolCaller

    #: Baglanti nesnesi. Acilista `None`: hicbir sey kurulmaz.
    kopru: dict[str, Any] = {"protocol": None}

    def hazir(proto: BridgeProtocol) -> None:
        kopru["protocol"] = proto

    def caller_for() -> Any:
        """Su an bagli tasima; YOKSA `None` -> depo `BridgeUnavailable` der.

        `None` dondurmek dogru cevaptir: "henuz bagli degil" bir hata degil,
        beklenen bir durumdur ve sessizce bos yazmaya donusmemelidir.
        """
        proto = kopru["protocol"]
        if proto is None:
            return None
        return ProtocolCaller(proto, timeout_secs=settings.api_timeout_secs)

    # Tek depo nesnesi; okul her cagrinin kimligindedir (`store_for`).
    store = BridgeStore(caller_for, timeout_secs=settings.api_timeout_secs)
    capabilities.bind_store(store)
    config.log("info", "depo: kopru (insight.*) -- yerel veritabani yok")
    config.log("info", capabilities.summary())
    if settings.refresh_interval_secs <= 0:
        config.log("info", "gece zamanlayicisi KAPALI (ZEKA_REFRESH_INTERVAL_SECS=0)")
        return await run_forever(settings)

    # Zamanlayici her okul icin bir `Source` ister. Baglanti kopmussa
    # `BridgeSource` cagrisi hata verir ve zamanlayici o okulu duser --
    # dogru davranis: veri cekilemeden hesap yapilmaz.
    def source_for(_school: str) -> Any:
        proto = kopru["protocol"]
        if proto is None:
            raise RuntimeError("kopru henuz bagli degil")
        return BridgeSource(proto)

    scheduler = Scheduler(
        source_for,
        store,
        only=settings.schools,
        budget_ms=int(settings.refresh_interval_secs * 1000),
    )
    await asyncio.gather(
        run_forever(settings, on_ready=hazir),
        scheduler.serve(tick_seconds=settings.refresh_interval_secs),
    )
    return 0


def main() -> int:
    settings = config.load(require_token=True)
    try:
        return asyncio.run(_serve(settings))
    except KeyboardInterrupt:
        config.log("info", "durduruldu")
        return 0


if __name__ == "__main__":
    sys.exit(main())
