"""`src/bridge.py` istemcisinin GERCEK bir QUIC baglantisi uzerindeki canli testi.

Buradaki her test gercek bir UDP soketi, gercek bir TLS 1.3 el sikismasi ve
gercek `hab/2` cerceveleri kullanir. Karsi taraf `tests/fake_bridge/` altindaki
sahte sunucudur -- GERCEK BACKEND DEGILDIR; neyin kanitlanip neyin
kanitlanmadigi `docs/KOPRU-KANITI.md` icinde tek tek yazilidir.

AG KAPSAMI: yalnizca 127.0.0.1. Hem QUIC hem sertifika HTTP ucu isletim
sisteminin verdigi bos bir porta baglanir; disariya HICBIR baglanti kurulmaz ve
hicbir sabit port isgal edilmez.

Bu testler `aioquic` GEREKTIRIR. Kurulu degilse butun modul atlanir -- geri
kalan 375+ testin saf `unittest` olma sozu bozulmasin diye.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from contextlib import contextmanager
from typing import Any, Iterator

try:
    import aioquic  # noqa: F401
except ImportError:  # pragma: no cover
    raise unittest.SkipTest("aioquic kurulu degil; canli kopru testleri atlaniyor")

from src import bridge as client
from src import config, protocol

from .fake_bridge.server import FakeBridge, FakeBridgeConfig

#: Testlerin kullandigi okul. Fikstur agacindakiyle ayni ad, kafa karismasin.
SCHOOL = "demo-okul"
TOKEN = "canli-test-sirri"
#: 64 KiB'lik blob parcalamasini (`server.rs:558-586`) gercekten tetiklemek icin
#: bir parcadan buyuk bir govde.
BIG_BLOB = bytes((i * 7 + 13) % 256 for i in range(200_000))


@contextmanager
def _environment(**values: str) -> Iterator[None]:
    """Ortami gecici olarak degistir; testler birbirini kirletmesin."""
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, old in previous.items():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old


class LiveBridgeCase(unittest.IsolatedAsyncioTestCase):
    """Sahte koprunun yasam dongusunu ve istemci ayarlarini kuran taban sinif."""

    async def start_bridge(self, fake_config: FakeBridgeConfig | None = None) -> FakeBridge:
        bridge = FakeBridge(fake_config or FakeBridgeConfig(token=TOKEN, schools=(SCHOOL,)))
        await bridge.start()
        self.addAsyncCleanup(bridge.stop)
        return bridge

    def settings_for(self, bridge: FakeBridge, **overrides: str) -> config.Config:
        """Sahte koprunun adreslerini gosteren bir `Config` uret.

        Parmak izi PINLENIR: TOFU yoluna dusmek, testin sessizce yanlis bir
        sertifikayi kabul etmesi demek olurdu.
        """
        values = {
            "AI_BRIDGE_HOST": "127.0.0.1",
            "AI_BRIDGE_PORT": str(bridge.quic_port),
            "AI_BACKEND_URL": bridge.backend_url,
            "AI_SHARED_TOKEN": TOKEN,
            "AI_TLS_SERVER_NAME": "localhost",
            "AI_TLS_FINGERPRINT": bridge.certificate.fingerprint,
            "ZEKA_SCHOOLS": SCHOOL,
            "AI_RECONNECT_SECS": "0.1",
            "AI_RECONNECT_MAX_SECS": "1.0",
            "LOG_LEVEL": "error",
        }
        values.update(overrides)
        with _environment(**values):
            return config.Config(require_token=True)

    async def connected(
        self,
        bridge: FakeBridge,
        body: Any,
        handler: client.RequestHandler | None = None,
        **overrides: str,
    ) -> Any:
        """Bir oturum ac, `body(connection)` calistir, sonucunu dondur.

        `run_once()` gercek uretim yolunun ta kendisidir: sertifikayi HTTP ile
        ceker, QUIC'e baglanir, kaydolur ve baglanti kapanana kadar bekler.
        """
        settings = self.settings_for(bridge, **overrides)
        finished: asyncio.Future = asyncio.get_running_loop().create_future()

        async def on_ready(connection: client.BridgeProtocol) -> None:
            try:
                finished.set_result(await body(connection))
            except Exception as exc:  # noqa: BLE001 -- testin kendisi degerlendirir
                if not finished.done():
                    finished.set_exception(exc)

        session = asyncio.ensure_future(
            client.run_once(settings, handler=handler, on_ready=on_ready)
        )
        try:
            return await asyncio.wait_for(asyncio.shield(finished), timeout=25)
        finally:
            session.cancel()
            await asyncio.gather(session, return_exceptions=True)


# --- el sikisma -------------------------------------------------------------


class HandshakeTest(LiveBridgeCase):
    async def test_handshake_registers_the_worker_and_its_capabilities(self) -> None:
        """El sikisma gercekten olur ve ilan edilen yetenekler kaydolur."""
        bridge = await self.start_bridge()
        worker_id = await self.connected(bridge, lambda conn: _identity(conn.worker_id))

        # `registrations` kucululmez: oturum kapandiktan sonra da el sikismanin
        # gerceklestigini gosterir (`workers` kayittan dusmeyle bosalir).
        self.assertEqual(len(bridge.registrations), 1)
        worker = bridge.registrations[0]
        self.assertEqual(worker.worker_id, worker_id)
        self.assertEqual(worker.service, "zeka")
        # Yetenekler `capabilities.names()` ile birebir aynidir; `Hello` onlari
        # oldugu gibi tasir (`protocol.rs:92-95`).
        from src import capabilities

        self.assertEqual(list(worker.capabilities), capabilities.names())
        self.assertTrue(worker.capabilities, "bos yetenek listesi reddedilirdi")

    async def test_hello_carries_the_wire_fields_the_backend_requires(self) -> None:
        """`Hello` cercevesi tel uzerinde backend'in bekledigi sekildedir."""
        bridge = await self.start_bridge()
        await self.connected(bridge, lambda conn: _identity(conn.worker_id))

        hello = bridge.hellos[0]
        self.assertEqual(hello["protocol"], "hab/2")
        self.assertIsInstance(hello["capabilities"], list)
        self.assertEqual(hello["token"], TOKEN)
        # `Hello` KASITLI olarak okul tasimaz (`protocol.rs:39-43`): filo
        # paylasimlidir, okul her cercevede ayrica adlandirilir.
        self.assertNotIn("school", hello)
        # `max_concurrent` 1..=64 arasina kirpilarak gonderilir (`constant.rs:547`).
        self.assertEqual(hello["max_concurrent"], 4)

    async def test_the_control_stream_stays_open_for_the_connection_life(self) -> None:
        """Kontrol akisi kapanmaz: kapanmasi kayittan dusme sinyalidir."""
        bridge = await self.start_bridge()

        async def body(connection: client.BridgeProtocol) -> None:
            await asyncio.sleep(0.3)
            # Hala kayitli: kontrol akisi acik oldugu surece worker yasar.
            self.assertEqual(len(bridge.workers), 1)

        await self.connected(bridge, body)


# --- izin listesi ve api okumasi -------------------------------------------


class ApiReadTest(LiveBridgeCase):
    async def test_api_get_fetches_and_decodes_an_allowed_path(self) -> None:
        """Izinli yoldan veri gelir ve govde dogru cozumlenir."""
        payload = {"id": "user:abc", "role": "student", "tr": "ogrenci ç ğ ş"}
        bridge = await self.start_bridge(
            FakeBridgeConfig(
                token=TOKEN,
                schools=(SCHOOL,),
                api_bodies={(SCHOOL, "/marks/me"): (200, payload)},
            )
        )
        response = await self.connected(
            bridge, lambda conn: conn.api_get(SCHOOL, "/marks/me", on_behalf_of="user:abc")
        )

        self.assertIsInstance(response, protocol.ApiResponse)
        self.assertEqual(response.status, 200)
        self.assertTrue(response.ok)
        self.assertEqual(response.body, payload)
        self.assertEqual(response.school, SCHOOL)
        # Sunucu tarafi istegi gercekten gordu: kim adina soruldugu dahil.
        self.assertEqual(bridge.api_reads, [(SCHOOL, "/marks/me", None, "user:abc")])

    async def test_a_query_string_travels_in_its_own_field(self) -> None:
        """Query yolun icine GOMULMEZ: `?` iceren bir yol izin listesinde eslesmez."""
        bridge = await self.start_bridge(
            FakeBridgeConfig(
                token=TOKEN, schools=(SCHOOL,), api_bodies={(SCHOOL, "/notes"): (200, [])}
            )
        )
        await self.connected(
            bridge, lambda conn: conn.api_get(SCHOOL, "/notes", query="limit=10&offset=0")
        )
        self.assertEqual(bridge.api_reads, [(SCHOOL, "/notes", "limit=10&offset=0", None)])

    async def test_a_404_is_an_ok_carrying_that_status_not_a_refusal(self) -> None:
        """Router calisip 404 dediyse bu bir `ok`'tur (`protocol.rs:196-198`)."""
        bridge = await self.start_bridge(
            FakeBridgeConfig(
                token=TOKEN, schools=(SCHOOL,), api_bodies={(SCHOOL, "/notes/yok"): (404, None)}
            )
        )
        response = await self.connected(bridge, lambda conn: conn.api_get(SCHOOL, "/notes/yok"))
        self.assertEqual(response.status, 404)
        self.assertFalse(response.ok)

    async def test_a_forbidden_path_is_refused_and_never_returns_empty(self) -> None:
        """Izinsiz yol `path_not_allowed` ile REDDEDILIR; sessizce bos donmez."""
        bridge = await self.start_bridge()

        with self.assertRaises(protocol.ApiRefused) as caught:
            await self.connected(bridge, lambda conn: conn.api_get(SCHOOL, "/settings"))

        self.assertEqual(caught.exception.code, protocol.ApiErrorCode.PATH_NOT_ALLOWED)
        self.assertFalse(caught.exception.retryable)
        # Istemci yolu TELE HIC CIKARMADI: izin listesi `build_api_request()`
        # icinde, gonderimden once uygulaniyor.
        self.assertEqual(bridge.api_reads, [])

    async def test_a_path_the_client_would_let_through_is_still_refused_by_the_server(
        self,
    ) -> None:
        """Sunucu tarafi izin listesi BAGIMSIZ olarak da caliyor.

        Istemcinin on denetimini atlayip cerceveyi elle kurarsak, sahte sunucu
        (backend gibi) yine `path_not_allowed` doner. Bu, iki tarafin ayni
        listeyi bagimsiz uygulamasinin kanitidir.
        """
        bridge = await self.start_bridge()

        async def body(connection: client.BridgeProtocol) -> Any:
            # `build_api_request()` atlaniyor: ham cerceve.
            raw = {
                "id": protocol.new_trace_id(),
                "school": SCHOOL,
                "path": "/course-notes/n1/files/f1",  # bir segment fazla
            }
            sid = connection._quic.get_next_available_stream_id()
            stream = protocol.FrameStream()
            connection._streams[sid] = stream
            connection._send_frame(sid, raw, end=True)
            try:
                return await asyncio.wait_for(stream.read_frame(), timeout=10)
            finally:
                connection._streams.pop(sid, None)

        frame = await self.connected(bridge, body)
        self.assertEqual(frame["outcome"], "err")
        self.assertEqual(frame["code"], "path_not_allowed")

    async def test_a_missing_school_is_refused_before_the_request_is_sent(self) -> None:
        """`school` yoksa istek GONDERILMEZ (`protocol.rs:44-47`)."""
        bridge = await self.start_bridge()

        with self.assertRaises(protocol.ApiRefused) as caught:
            await self.connected(bridge, lambda conn: conn.api_get("", "/auth/me"))

        self.assertEqual(caught.exception.code, protocol.ApiErrorCode.MALFORMED)
        self.assertEqual(bridge.api_reads, [], "okulsuz istek tele cikmamaliydi")

    async def test_an_unknown_school_is_refused_by_the_server(self) -> None:
        """Bilinmeyen okul slug'i -> `unknown_school` (`server.rs:88-91`)."""
        bridge = await self.start_bridge()

        with self.assertRaises(protocol.ApiRefused) as caught:
            await self.connected(bridge, lambda conn: conn.api_get("yok-boyle-okul", "/auth/me"))

        self.assertEqual(caught.exception.code, protocol.ApiErrorCode.UNKNOWN_SCHOOL)
        self.assertEqual(caught.exception.school, "yok-boyle-okul")
        self.assertFalse(caught.exception.retryable)

    async def test_a_suspended_school_is_refused_but_worth_retrying(self) -> None:
        """Askidaki okul -> `school_suspended`, sonra denemeye deger."""
        bridge = await self.start_bridge(
            FakeBridgeConfig(
                token=TOKEN, schools=(SCHOOL,), suspended_schools=(SCHOOL,)
            )
        )
        with self.assertRaises(protocol.ApiRefused) as caught:
            await self.connected(bridge, lambda conn: conn.api_get(SCHOOL, "/auth/me"))

        self.assertEqual(caught.exception.code, protocol.ApiErrorCode.SCHOOL_SUSPENDED)
        self.assertTrue(caught.exception.retryable)


# --- blob okumasi -----------------------------------------------------------


class BlobReadTest(LiveBridgeCase):
    async def test_blob_get_reads_every_raw_byte(self) -> None:
        """Ham govde eksiksiz gelir; boyut baslikla birebir tutar."""
        bridge = await self.start_bridge(
            FakeBridgeConfig(
                token=TOKEN,
                schools=(SCHOOL,),
                blobs={(SCHOOL, "file-01"): ("ozet.pdf", "application/pdf", BIG_BLOB)},
            )
        )
        blob = await self.connected(
            bridge, lambda conn: conn.blob_get(SCHOOL, "file-01", on_behalf_of="user:abc")
        )

        self.assertEqual(blob.header.name, "ozet.pdf")
        self.assertEqual(blob.header.content_type, "application/pdf")
        # Baslik ne vaat ettiyse tam o kadar bayt okundu (`protocol.rs:253-255`).
        self.assertEqual(blob.header.size, len(BIG_BLOB))
        self.assertEqual(len(blob.data), blob.header.size)
        self.assertEqual(blob.data, BIG_BLOB)
        # Tek bir cerceveye sigmayacak kadar buyuk degil ama tek bir QUIC
        # yazmasina da sigmayan bir govde: parcalanip yeniden birlestirildi.
        self.assertGreater(len(BIG_BLOB), 64 * 1024)

    async def test_an_empty_blob_is_read_as_zero_bytes_not_a_hang(self) -> None:
        """`size: 0` bir hata degildir; okuma hemen biter."""
        bridge = await self.start_bridge(
            FakeBridgeConfig(
                token=TOKEN,
                schools=(SCHOOL,),
                blobs={(SCHOOL, "bos"): ("bos.txt", "text/plain", b"")},
            )
        )
        blob = await self.connected(
            bridge, lambda conn: conn.blob_get(SCHOOL, "bos", on_behalf_of="user:abc")
        )
        self.assertEqual(blob.header.size, 0)
        self.assertEqual(blob.data, b"")

    async def test_a_missing_blob_is_refused_with_not_found(self) -> None:
        bridge = await self.start_bridge()
        with self.assertRaises(protocol.BlobRefused) as caught:
            await self.connected(
                bridge, lambda conn: conn.blob_get(SCHOOL, "yok", on_behalf_of="user:abc")
            )
        self.assertEqual(caught.exception.code, protocol.ApiErrorCode.NOT_FOUND)

    async def test_without_on_behalf_of_the_ai_role_earns_forbidden(self) -> None:
        """`ai` rolu hicbir dersi goremez (`protocol.rs:236-239`)."""
        bridge = await self.start_bridge(
            FakeBridgeConfig(
                token=TOKEN,
                schools=(SCHOOL,),
                blobs={(SCHOOL, "file-01"): ("a.pdf", "application/pdf", b"x")},
            )
        )
        with self.assertRaises(protocol.BlobRefused) as caught:
            await self.connected(bridge, lambda conn: conn.blob_get(SCHOOL, "file-01"))
        self.assertEqual(caught.exception.code, protocol.ApiErrorCode.FORBIDDEN)

    async def test_a_blob_request_without_a_school_never_reaches_the_wire(self) -> None:
        bridge = await self.start_bridge()
        with self.assertRaises(protocol.BlobRefused) as caught:
            await self.connected(bridge, lambda conn: conn.blob_get("", "file-01"))
        self.assertEqual(caught.exception.code, protocol.ApiErrorCode.MALFORMED)
        self.assertEqual(bridge.blob_reads, [])


# --- sunucu baslatimli is akisi ---------------------------------------------


class ServerInitiatedRequestTest(LiveBridgeCase):
    async def test_a_capability_call_round_trips(self) -> None:
        """Backend'in actigi akista `Request` gelir, `Response` doner.

        Bu yol BUGUN uretimde hic kullanilmaz -- backend ZEKA'nin yeteneklerini
        tanimiyor -- ama sozlesme dogru kurulmus mu, ancak boyle anlasilir.
        """
        bridge = await self.start_bridge()
        seen: list[protocol.Request] = []

        def handler(request: protocol.Request) -> dict[str, Any]:
            seen.append(request)
            return {"echo": request.payload, "capability": request.capability}

        async def body(connection: client.BridgeProtocol) -> Any:
            return await bridge.call("insight.student", SCHOOL, {"student": "s-1"})

        frame = await self.connected(bridge, body, handler=handler)

        self.assertEqual(frame["status"], "ok")
        # Okul YANKILANIR (`protocol.rs:157-159`).
        self.assertEqual(frame["school"], SCHOOL)
        self.assertEqual(frame["payload"], {"echo": {"student": "s-1"}, "capability": "insight.student"})
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].capability, "insight.student")
        self.assertEqual(seen[0].school, SCHOOL)
        self.assertEqual(seen[0].deadline_ms, 30_000)
        # `id` yankilanir: backend eslesmeyen bir id'yi cevabin baska bir istege
        # ait oldugu anlamina alir (`server.rs:295-305`).
        self.assertEqual(frame["id"], seen[0].id)

    async def test_a_slow_synchronous_capability_does_not_block_the_event_loop(self) -> None:
        """Islemci yogun senkron bir yetenek, koprunun geri kalanini durdurmaz.

        Yetenekler ogrenci verisi uzerinde senkron hesap yapar. Olay dongusunde
        kosarlarsa `keepalive()` PING'leri de durur ve backend'in 30 saniyelik
        bosta kalma penceresi (`constant.rs:554`) baglantiyi dusurur. Bu test
        bir api okumasinin, suren bir yetenek cagrisinin ALTINDAN gectigini
        gosterir.
        """
        import time

        bridge = await self.start_bridge(
            FakeBridgeConfig(
                token=TOKEN,
                schools=(SCHOOL,),
                api_bodies={(SCHOOL, "/auth/me"): (200, {"ok": True})},
            )
        )

        def slow_handler(request: protocol.Request) -> dict[str, Any]:
            time.sleep(1.5)  # gercek, iptal edilemez islemci/IO beklemesi
            return {"done": True}

        async def body(connection: client.BridgeProtocol) -> float:
            call = asyncio.ensure_future(bridge.call("insight.student", SCHOOL, {}))
            # Yetenek daha basladi bile denmeden bir okuma yolla.
            await asyncio.sleep(0.2)
            started = asyncio.get_running_loop().time()
            response = await connection.api_get(SCHOOL, "/auth/me")
            elapsed = asyncio.get_running_loop().time() - started
            self.assertEqual(response.status, 200)
            frame = await call
            self.assertEqual(frame["status"], "ok")
            self.assertEqual(frame["payload"], {"done": True})
            return elapsed

        elapsed = await self.connected(bridge, body, handler=slow_handler)
        # Donguyu bloke etse, okuma 1.5 saniyelik uykunun bitmesini beklerdi.
        self.assertLess(elapsed, 1.0, f"olay dongusu bloke oldu ({elapsed:.2f}s)")

    async def test_going_over_the_declared_concurrency_answers_busy(self) -> None:
        """`Hello.max_concurrent` bir VAATTIR; asilirsa acik bir `busy` doner.

        Gec cevap yerine acik bir red: backend istegi baska bir worker'a
        yollayabilsin diye. `AI_MAX_CONCURRENT=1` ile ikinci istek beklemez.
        """
        bridge = await self.start_bridge()
        release = asyncio.Event()

        async def blocking_handler(request: protocol.Request) -> dict[str, Any]:
            await release.wait()
            return {"ok": True}

        async def body(connection: client.BridgeProtocol) -> Any:
            first = asyncio.ensure_future(bridge.call("insight.student", SCHOOL, {"n": 1}))
            await asyncio.sleep(0.3)  # ilk istek isleyiciye girsin
            second = await bridge.call("insight.student", SCHOOL, {"n": 2})
            release.set()
            return await first, second

        first, second = await self.connected(
            bridge, body, handler=blocking_handler, AI_MAX_CONCURRENT="1"
        )
        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "err")
        self.assertEqual(second["code"], "busy")
        # Reddedilen istek de okulunu yankilar.
        self.assertEqual(second["school"], SCHOOL)

    async def test_a_handled_failure_comes_back_as_an_err_response(self) -> None:
        """`CapabilityError` bir `Response{status:"err"}` olur, akis dusmez."""
        bridge = await self.start_bridge()

        def handler(request: protocol.Request) -> dict[str, Any]:
            raise protocol.CapabilityError("unsupported_image", "bu gorsel okunamiyor")

        async def body(connection: client.BridgeProtocol) -> Any:
            return await bridge.call("insight.student", SCHOOL, {})

        frame = await self.connected(bridge, body, handler=handler)
        self.assertEqual(frame["status"], "err")
        self.assertEqual(frame["code"], "unsupported_image")
        self.assertEqual(frame["school"], SCHOOL)


# --- cerceve boyut kapagi ---------------------------------------------------


class FrameCapTest(LiveBridgeCase):
    async def test_an_oversized_length_prefix_is_refused_before_allocating(self) -> None:
        """Sinirdan buyuk bir uzunluk oneki, govde beklenmeden reddedilir.

        Sunucu yalnizca 4 bayt yazar, tek bir govde bayti yazmaz. Istemci yine de
        cevap vermeli: asili kalan bir akis, backend'i kendi zaman asimina
        birakirdi (`protocol.rs:286-289`, `server.rs:393-404`).
        """
        bridge = await self.start_bridge()

        async def body(connection: client.BridgeProtocol) -> Any:
            return await bridge.workers[-1].connection.send_oversize_frame_header()

        frame = await self.connected(bridge, body)
        self.assertEqual(frame["status"], "err")
        self.assertEqual(frame["code"], "frame_too_large")

    async def test_the_client_refuses_to_write_an_oversized_frame(self) -> None:
        """Kapak YAZARKEN de uygulanir (`protocol.rs:275-277`)."""
        with self.assertRaises(protocol.FrameTooLarge):
            protocol.encode_frame({"payload": "x" * (protocol.AI_MAX_FRAME_BYTES + 1)})

    async def test_an_oversized_capability_answer_becomes_an_error_frame(self) -> None:
        """Cevap kapagi asarsa sessizce dusurulmez, kucuk bir hata cercevesi yazilir."""
        bridge = await self.start_bridge()

        def handler(request: protocol.Request) -> dict[str, Any]:
            return {"big": "x" * (protocol.AI_MAX_FRAME_BYTES + 10)}

        async def body(connection: client.BridgeProtocol) -> Any:
            return await bridge.call("insight.student", SCHOOL, {})

        frame = await self.connected(bridge, body, handler=handler)
        self.assertEqual(frame["status"], "err")
        self.assertEqual(frame["code"], "frame_too_large")


# --- red ve dayaniklilik ----------------------------------------------------


class RejectionTest(LiveBridgeCase):
    async def _run_forever_until(
        self, bridge: FakeBridge, condition: Any, timeout: float = 20.0
    ) -> asyncio.Future:
        """`run_forever()` baslat ve `condition()` dogru olana kadar bekle."""
        settings = self.settings_for(bridge)
        task = asyncio.ensure_future(client.run_forever(settings))
        self.addAsyncCleanup(_cancel, task)
        deadline = asyncio.get_running_loop().time() + timeout
        while not condition():
            if task.done():
                # CIKMAMALIYDI: cikan bir istemci, `restart: unless-stopped`
                # altinda sonsuz bir crash-loop demektir.
                raise AssertionError(f"run_forever() cikti: {task.exception()!r}")
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("kosul zaman asimina ugradi")
            await asyncio.sleep(0.05)
        return task

    async def test_a_protocol_mismatch_is_rejected_and_the_client_keeps_retrying(
        self,
    ) -> None:
        """Yanlis surumde reddedilir ama istemci CIKMAZ, geri cekilerek dener.

        Podcast servisi burada `exit 2` yapiyor; `restart: unless-stopped` ile bu
        sonsuz bir crash-loop uretir. ZEKA kodu loglar ve tavana cekilip bekler.
        """
        bridge = await self.start_bridge(
            # Sunucu `hab/3` konusuyor: ALPN ayni kaldigi icin TLS gecer, red
            # `Hello` seviyesinde gelir (`server.rs:949-958`).
            FakeBridgeConfig(token=TOKEN, schools=(SCHOOL,), protocol="hab/3")
        )
        task = await self._run_forever_until(bridge, lambda: len(bridge.rejects) >= 2)

        self.assertTrue(all(code == "unsupported_protocol" for code in bridge.rejects))
        self.assertFalse(task.done(), "istemci cikmamali")
        self.assertEqual(bridge.workers, [], "reddedilen servis kaydolmamali")

    async def test_a_bad_token_is_rejected_and_the_client_keeps_retrying(self) -> None:
        """Yanlis token -> `unauthorized`; yine cikilmaz."""
        bridge = await self.start_bridge(
            FakeBridgeConfig(token="baska-bir-sir", schools=(SCHOOL,))
        )
        task = await self._run_forever_until(bridge, lambda: len(bridge.rejects) >= 2)

        self.assertTrue(all(code == "unauthorized" for code in bridge.rejects))
        self.assertFalse(task.done())
        self.assertEqual(bridge.workers, [])

    async def test_an_empty_capability_list_is_rejected(self) -> None:
        """Bos yetenek listesi -> `no_capabilities` (`protocol.rs:128`).

        DIKKAT: `server.rs:976`'daki `"bad_capabilities"` bir METRIK etiketidir;
        TEL uzerindeki kod `serde(rename_all="snake_case")` geregi
        `no_capabilities`'tir (`protocol.rs:123-130`).
        """
        bridge = await self.start_bridge()
        settings = self.settings_for(bridge)

        original = client.capabilities.names
        client.capabilities.names = lambda: []  # type: ignore[assignment]
        try:
            with self.assertRaises(protocol.HandshakeRejected) as caught:
                await client.run_once(settings)
        finally:
            client.capabilities.names = original  # type: ignore[assignment]

        self.assertEqual(caught.exception.code, protocol.RejectCode.NO_CAPABILITIES)
        # Yeniden denemeye deger degil ama KALICI listesinde de degil: yetenek
        # defteri kod degisikligiyle duzelir.
        self.assertFalse(caught.exception.permanent)

    async def test_the_client_reconnects_after_the_connection_drops(self) -> None:
        """Baglanti koparsa yeniden baglanilir ve yeniden kaydolunur."""
        bridge = await self.start_bridge()
        task = await self._run_forever_until(bridge, lambda: len(bridge.registrations) >= 1)
        first = bridge.registrations[-1].worker_id

        bridge.drop_connections()

        deadline = asyncio.get_running_loop().time() + 20
        while len(bridge.registrations) < 2:
            if task.done():
                raise AssertionError(f"run_forever() cikti: {task.exception()!r}")
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("yeniden baglanma gerceklesmedi")
            await asyncio.sleep(0.05)

        # Yeni bir KAYIT olustu: yalnizca soket degil, el sikisma da tekrarlandi.
        self.assertNotEqual(bridge.registrations[-1].worker_id, first)
        self.assertEqual(len(bridge.workers), 1, "tam olarak bir canli baglanti")
        self.assertFalse(task.done())

    async def test_a_hab1_client_is_refused_at_the_alpn_gate(self) -> None:
        """`hab/1` konusan bir istemci TLS el sikismasini bile gecemez.

        ALPN SURUM KAPISIDIR (`tls.rs:80-83`): eski bir servis farkli bir
        kimlik bildirir ve iki taraf birbirinin baytlarini yanlis okuyamadan
        reddedilir. Podcast ve Celebi servisleri `hab/1` kullaniyor -- bu test
        onlarin bu koprude CALISAMAYACAGININ kanitidir.
        """
        from aioquic.asyncio import connect as raw_connect
        from aioquic.quic.configuration import QuicConfiguration

        bridge = await self.start_bridge()
        stale = QuicConfiguration(is_client=True, alpn_protocols=["hab/1"])
        stale.server_name = "localhost"
        stale.load_verify_locations(cadata=bridge.certificate.cert_pem.encode("ascii"))

        with self.assertRaises((ConnectionError, asyncio.TimeoutError)):
            async with raw_connect(
                "127.0.0.1", bridge.quic_port, configuration=stale
            ) as connection:
                await asyncio.wait_for(connection.wait_connected(), timeout=10)

        # Tek bir `Hello` bile tele cikmadi: red uygulama katmanindan ONCE.
        self.assertEqual(bridge.hellos, [])

    async def test_the_client_announces_the_hab2_alpn(self) -> None:
        """Istemcinin ALPN'i backend'in `AI_ALPN` sabitiyle ayni (`constant.rs:531`)."""
        bridge = await self.start_bridge()
        settings = self.settings_for(bridge)
        quic_config = client.build_quic_configuration(settings, bridge.certificate.cert_pem)
        self.assertEqual(quic_config.alpn_protocols, ["hab/2"])
        # Bosta kalma suresi de backend'inkiyle ayni (`constant.rs:554`).
        self.assertEqual(quic_config.idle_timeout, 30)

    async def test_a_pinned_fingerprint_mismatch_stops_the_connection(self) -> None:
        """Parmak izi tutmuyorsa BAGLANILMAZ -- TOFU'ya geri dusulmez."""
        bridge = await self.start_bridge()
        settings = self.settings_for(bridge, AI_TLS_FINGERPRINT="0" * 64)

        with self.assertRaises(RuntimeError) as caught:
            await client.run_once(settings)

        self.assertIn("parmak izi", str(caught.exception))
        self.assertEqual(bridge.hellos, [], "hicbir Hello gonderilmemeliydi")


# --- akis yasam dongusu -----------------------------------------------------


class StreamLifecycleTest(LiveBridgeCase):
    async def test_concurrent_reads_multiplex_over_their_own_streams(self) -> None:
        """Es zamanli okumalar birbirini beklemez ve karismaz.

        Korelasyon kimligi YOKTUR (`protocol.rs:48-52`): eslesmeyi QUIC akis
        kimlikleri yapar. Uc okuma ayni anda ucar, her biri kendi cevabini alir.
        """
        bridge = await self.start_bridge(
            FakeBridgeConfig(
                token=TOKEN,
                schools=(SCHOOL,),
                api_bodies={
                    (SCHOOL, "/auth/me"): (200, {"which": "auth"}),
                    (SCHOOL, "/notes"): (200, {"which": "notes"}),
                    (SCHOOL, "/marks/me"): (200, {"which": "marks"}),
                },
            )
        )

        async def body(connection: client.BridgeProtocol) -> Any:
            return await asyncio.gather(
                connection.api_get(SCHOOL, "/auth/me"),
                connection.api_get(SCHOOL, "/notes"),
                connection.api_get(SCHOOL, "/marks/me"),
            )

        auth, notes, marks = await self.connected(bridge, body)
        self.assertEqual(auth.body, {"which": "auth"})
        self.assertEqual(notes.body, {"which": "notes"})
        self.assertEqual(marks.body, {"which": "marks"})
        self.assertEqual(len(bridge.api_reads), 3)

    async def test_a_completed_read_leaves_no_stream_behind(self) -> None:
        """Biten her okuma kendi tamponunu birakir; yalnizca kontrol akisi kalir."""
        bridge = await self.start_bridge(
            FakeBridgeConfig(
                token=TOKEN, schools=(SCHOOL,), api_bodies={(SCHOOL, "/auth/me"): (200, {})}
            )
        )

        async def body(connection: client.BridgeProtocol) -> int:
            for _ in range(5):
                await connection.api_get(SCHOOL, "/auth/me")
            await asyncio.sleep(0.2)
            return len(connection._streams)

        # Geriye TEK bir akis kalir: omur boyu acik duran kontrol akisi.
        self.assertEqual(await self.connected(bridge, body), 1)

    async def test_an_unanswered_read_times_out_and_abandons_its_stream(self) -> None:
        """Cevapsiz bir okuma sonsuza kadar beklemez; akis da sizdirilmaz."""
        bridge = await self.start_bridge(
            FakeBridgeConfig(token=TOKEN, schools=(SCHOOL,), silent_paths=("/auth/me",))
        )

        async def body(connection: client.BridgeProtocol) -> int:
            with self.assertRaises(asyncio.TimeoutError):
                await connection.api_get(SCHOOL, "/auth/me", timeout=1.0)
            await asyncio.sleep(0.2)
            return len(connection._streams)

        streams_left = await self.connected(bridge, body)
        self.assertEqual(bridge.silent_reads, ["/auth/me"])
        # Terk edilen akis unutuldu: yalnizca kontrol akisi kaldi.
        self.assertEqual(streams_left, 1)

    async def test_a_refused_read_leaves_no_stream_behind(self) -> None:
        """Sunucu reddederse de tampon birakilmaz."""
        bridge = await self.start_bridge()

        async def body(connection: client.BridgeProtocol) -> int:
            with self.assertRaises(protocol.ApiRefused):
                await connection.api_get("yok-boyle-okul", "/auth/me")
            await asyncio.sleep(0.2)
            return len(connection._streams)

        self.assertEqual(await self.connected(bridge, body), 1)


class BackoffOrderingTest(unittest.IsolatedAsyncioTestCase):
    """`run_forever()` istisna siralamasinin dogrulugu.

    Python 3.11'den beri `asyncio.TimeoutError` yerlesik `TimeoutError`'dir ve o
    da `OSError`'in alt sinifidir; zaman asimi yakalayicisi OSError'dan SONRA
    yazilirsa hic calismaz. Bu test o siralamayi pinler.
    """

    async def test_a_handshake_timeout_is_reported_as_a_timeout(self) -> None:
        self.assertTrue(
            issubclass(asyncio.TimeoutError, OSError),
            "bu testin varlik sebebi: zaman asimi bir OSError'dir",
        )
        lines: list[str] = []
        attempts = 0

        async def failing_run_once(*args: Any, **kwargs: Any) -> None:
            nonlocal attempts
            attempts += 1
            if attempts >= 2:
                raise asyncio.CancelledError
            raise asyncio.TimeoutError

        settings = _offline_settings()
        original_run_once, original_log = client.run_once, config.log
        client.run_once = failing_run_once  # type: ignore[assignment]
        config.log = lambda level, message: lines.append(message)  # type: ignore[assignment]
        try:
            with self.assertRaises(asyncio.CancelledError):
                await client.run_forever(settings)
        finally:
            client.run_once = original_run_once  # type: ignore[assignment]
            config.log = original_log  # type: ignore[assignment]

        self.assertIn("el sikisma zaman asimina ugradi", lines)
        self.assertFalse(
            any(line.startswith("backend'e ulasilamadi") for line in lines),
            "zaman asimi 'ulasilamadi' diye raporlanmamali",
        )


def _offline_settings() -> config.Config:
    """Hicbir ag islemi yapmayan, yalnizca geri cekilme alanlari icin ayar."""
    with _environment(
        AI_SHARED_TOKEN=TOKEN,
        AI_RECONNECT_SECS="0.1",
        AI_RECONNECT_MAX_SECS="1.0",
        LOG_LEVEL="error",
    ):
        return config.Config(require_token=True)


# --- yardimcilar ------------------------------------------------------------


async def _identity(value: Any) -> Any:
    return value


async def _cancel(task: asyncio.Future) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
