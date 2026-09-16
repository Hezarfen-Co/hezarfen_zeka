"""`hab/2` kablo sozlesmesinin testleri.

Bu paket `aioquic` GEREKTIRMEZ ve ag kullanmaz: `src.protocol` saf Python'dur,
`src.bridge` buradan hic import edilmez.
"""

from __future__ import annotations

import json
import struct
import unittest

from src import protocol


class ProtocolVersionTests(unittest.TestCase):
    def test_protocol_is_hab_2_not_hab_1(self):
        # constant.rs:530-531. Podcast ve Celebi `hab/1` kullaniyor ve bu yuzden
        # ALPN muzakeresinde reddediliyorlar.
        self.assertEqual(protocol.AI_PROTOCOL, "hab/2")
        self.assertEqual(protocol.AI_ALPN, "hab/2")
        self.assertEqual(protocol.AI_PROTOCOL, protocol.AI_ALPN)

    def test_frame_cap_matches_backend(self):
        # constant.rs:536
        self.assertEqual(protocol.AI_MAX_FRAME_BYTES, 8 * 1024 * 1024)

    def test_worker_concurrency_bounds_match_backend(self):
        # constant.rs:547-548
        self.assertEqual(protocol.AI_MAX_CONCURRENT_PER_WORKER, 64)
        self.assertEqual(protocol.AI_DEFAULT_CONCURRENT_PER_WORKER, 8)

    def test_keepalive_is_below_idle_timeout(self):
        # constant.rs:554-555: saglikli ama sessiz bir servis dusurulmemeli.
        self.assertLess(protocol.AI_KEEPALIVE_SECS, protocol.AI_IDLE_TIMEOUT_SECS)

    def test_greeting_timeout_is_below_backend_handshake_timeout(self):
        # Reddi biz gormeliyiz; akis altimizdan kesilmemeli (constant.rs:643).
        self.assertLess(
            protocol.GREETING_TIMEOUT_SECS, protocol.AI_HANDSHAKE_TIMEOUT_SECS
        )


class FrameCodecTests(unittest.TestCase):
    def test_round_trip(self):
        payload = {"id": "01J", "school": "demo", "veri": "cok satirli\nmetin"}
        self.assertEqual(protocol.decode_frame(protocol.encode_frame(payload)), payload)

    def test_length_prefix_is_big_endian_u32(self):
        encoded = protocol.encode_frame({"a": 1})
        (length,) = struct.unpack(">I", encoded[:4])
        self.assertEqual(length, len(encoded) - 4)
        self.assertEqual(json.loads(encoded[4:]), {"a": 1})

    def test_back_to_back_frames_stay_aligned(self):
        first = protocol.encode_frame({"n": 1})
        second = protocol.encode_frame({"n": 2})
        buffer = first + second
        self.assertEqual(protocol.decode_frame(buffer), {"n": 1})
        self.assertEqual(protocol.decode_frame(buffer[len(first) :]), {"n": 2})

    def test_oversize_write_is_refused(self):
        with self.assertRaises(protocol.FrameTooLarge):
            protocol.encode_frame({"x": "a" * (protocol.AI_MAX_FRAME_BYTES + 1)})

    def test_oversize_length_header_is_refused_before_allocating(self):
        claimed = protocol.AI_MAX_FRAME_BYTES + 1
        with self.assertRaises(protocol.FrameTooLarge):
            protocol.decode_frame(struct.pack(">I", claimed))

    def test_garbage_body_is_malformed(self):
        body = b"hic de json degil"
        with self.assertRaises(protocol.FrameMalformed):
            protocol.decode_frame(struct.pack(">I", len(body)) + body)

    def test_non_ascii_survives_the_round_trip(self):
        payload = {"school": "ataturk-anadolu", "ad": "Ogrenci Cigdem Sisli"}
        self.assertEqual(protocol.decode_frame(protocol.encode_frame(payload)), payload)


class FrameStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_frame_split_across_chunks(self):
        stream = protocol.FrameStream()
        encoded = protocol.encode_frame({"id": "01J", "school": "demo"})
        for index in range(0, len(encoded), 3):
            stream.feed(encoded[index : index + 3], end=False)
        self.assertEqual(await stream.read_frame(), {"id": "01J", "school": "demo"})

    async def test_raw_bytes_after_a_header_are_not_frames(self):
        # Blob govdesi HAM bayttir (protocol.rs:26-31); cerceve kapagina tabi degil.
        stream = protocol.FrameStream()
        header = protocol.encode_frame(
            {
                "status": "ok",
                "id": "01J",
                "school": "demo",
                "name": "ozet.pdf",
                "content_type": "application/pdf",
                "size": 5,
            }
        )
        stream.feed(header + b"12345", end=True)
        parsed = protocol.parse_blob_response(await stream.read_frame())
        self.assertEqual(parsed.size, 5)
        self.assertEqual(await stream.read_exact(parsed.size), b"12345")

    async def test_truncated_stream_is_eof(self):
        stream = protocol.FrameStream()
        stream.feed(struct.pack(">I", 8) + b'{"a":', end=True)
        with self.assertRaises(EOFError):
            await stream.read_frame()


class HelloAndGreetingTests(unittest.TestCase):
    def test_hello_carries_no_school(self):
        # protocol.rs:82-84: filo paylasimlidir, okul her frame'de gelir.
        wire = protocol.build_hello("zeka", ["insight.student"], "gizli", 4)
        self.assertNotIn("school", wire)
        self.assertEqual(wire["protocol"], "hab/2")
        self.assertEqual(wire["capabilities"], ["insight.student"])
        self.assertEqual(wire["max_concurrent"], 4)

    def test_hello_round_trip(self):
        wire = protocol.build_hello("zeka", ["insight.class"], "gizli", 99)
        parsed = protocol.Hello.from_wire(wire)
        self.assertEqual(parsed.service, "zeka")
        # Backend clamp'i 1..=64 (constant.rs:547); biz de kirpiyoruz.
        self.assertEqual(parsed.max_concurrent, protocol.AI_MAX_CONCURRENT_PER_WORKER)

    def test_max_concurrent_is_optional_on_the_wire(self):
        parsed = protocol.Hello.from_wire(
            {
                "protocol": "hab/2",
                "service": "zeka",
                "capabilities": ["insight.student"],
                "token": "gizli",
            }
        )
        self.assertIsNone(parsed.max_concurrent)

    def test_welcome_returns_worker_id(self):
        worker = protocol.parse_greeting(
            {"type": "welcome", "worker_id": "w1", "protocol": "hab/2"}
        )
        self.assertEqual(worker, "w1")

    def test_rejection_carries_its_code(self):
        with self.assertRaises(protocol.HandshakeRejected) as caught:
            protocol.parse_greeting(
                {"type": "rejected", "code": "unsupported_protocol", "message": "eski"}
            )
        self.assertEqual(caught.exception.code, protocol.RejectCode.UNSUPPORTED_PROTOCOL)
        self.assertTrue(caught.exception.permanent)

    def test_welcome_echoing_a_foreign_protocol_is_rejected(self):
        with self.assertRaises(protocol.HandshakeRejected) as caught:
            protocol.parse_greeting(
                {"type": "welcome", "worker_id": "w1", "protocol": "hab/1"}
            )
        self.assertEqual(caught.exception.code, protocol.RejectCode.UNSUPPORTED_PROTOCOL)


class ApiFrameTests(unittest.TestCase):
    def test_api_request_wire_names(self):
        wire = protocol.build_api_request(
            "01J", "demo", "/notes", query="limit=10", on_behalf_of="user:abc"
        )
        self.assertEqual(
            wire,
            {
                "id": "01J",
                "school": "demo",
                "path": "/notes",
                "query": "limit=10",
                "on_behalf_of": "user:abc",
            },
        )
        self.assertEqual(protocol.ApiRequest.from_wire(wire).path, "/notes")

    def test_school_is_required_with_no_default(self):
        with self.assertRaises(protocol.ApiRefused) as caught:
            protocol.build_api_request("01J", "", "/notes")
        self.assertEqual(caught.exception.code, protocol.ApiErrorCode.MALFORMED)

    def test_query_inside_the_path_is_refused(self):
        with self.assertRaises(protocol.ApiRefused):
            protocol.build_api_request("01J", "demo", "/notes?limit=10")

    def test_non_get_method_is_refused_locally(self):
        with self.assertRaises(protocol.ApiRefused) as caught:
            protocol.build_api_request("01J", "demo", "/notes", method="POST")
        self.assertEqual(
            caught.exception.code, protocol.ApiErrorCode.METHOD_NOT_ALLOWED
        )

    def test_api_response_tag_is_outcome_and_status_is_http(self):
        # protocol.rs:449-451: etiket `outcome`, `status` HTTP kodudur.
        parsed = protocol.parse_api_response(
            {"outcome": "ok", "id": "1", "school": "demo", "status": 404, "body": None}
        )
        self.assertEqual(parsed.status, 404)
        self.assertFalse(parsed.ok)

    def test_api_error_raises_with_its_code(self):
        with self.assertRaises(protocol.ApiRefused) as caught:
            protocol.parse_api_response(
                {
                    "outcome": "err",
                    "id": "1",
                    "school": "demo",
                    "code": "path_not_allowed",
                    "message": "olmaz",
                }
            )
        self.assertEqual(caught.exception.code, protocol.ApiErrorCode.PATH_NOT_ALLOWED)


class BlobFrameTests(unittest.TestCase):
    def test_blob_request_wire_names(self):
        wire = protocol.build_blob_request("01J", "demo", "01FILE", "user:abc")
        self.assertEqual(
            wire,
            {"id": "01J", "school": "demo", "file": "01FILE", "on_behalf_of": "user:abc"},
        )

    def test_blob_and_api_shapes_never_parse_as_each_other(self):
        # protocol.rs:34: ayirici alan `path` / `file`.
        blob = protocol.build_blob_request("01J", "demo", "01FILE")
        self.assertNotIn("path", blob)
        with self.assertRaises(protocol.FrameMalformed):
            protocol.ApiRequest.from_wire(blob)

    def test_blob_tag_is_status_not_outcome(self):
        # protocol.rs:509-511
        parsed = protocol.parse_blob_response(
            {
                "status": "ok",
                "id": "1",
                "school": "demo",
                "name": "ozet.pdf",
                "content_type": "application/pdf",
                "size": 204800,
            }
        )
        self.assertEqual(parsed.size, 204800)

    def test_blob_error_raises(self):
        with self.assertRaises(protocol.BlobRefused) as caught:
            protocol.parse_blob_response(
                {
                    "status": "err",
                    "id": "1",
                    "school": "demo",
                    "code": "not_found",
                    "message": "yok",
                }
            )
        self.assertEqual(caught.exception.code, protocol.ApiErrorCode.NOT_FOUND)


class RequestResponseTests(unittest.TestCase):
    def test_request_round_trip_and_deadline_budget(self):
        request = protocol.Request.from_wire(
            {
                "id": "01J",
                "school": "demo",
                "capability": "insight.student",
                "deadline_ms": 30000,
                "payload": {"user_id": "u1"},
            }
        )
        self.assertEqual(request.capability, "insight.student")
        # Butceden pay dusulur; gec cevap yerine erken hata.
        self.assertLess(request.timeout_secs, 30.0)
        self.assertGreater(request.timeout_secs, 15.0)

    def test_request_without_a_school_is_malformed(self):
        with self.assertRaises(protocol.FrameMalformed):
            protocol.Request.from_wire(
                {"id": "01J", "capability": "insight.student", "deadline_ms": 1000}
            )

    def test_responses_echo_the_school(self):
        # protocol.rs:155-169: her cevap okulunu yankilar.
        self.assertEqual(
            protocol.ok_response("01J", "demo", {"n": 1}),
            {"status": "ok", "id": "01J", "school": "demo", "payload": {"n": 1}},
        )
        self.assertEqual(
            protocol.err_response("01J", "demo", "bad_input", "olmaz"),
            {
                "status": "err",
                "id": "01J",
                "school": "demo",
                "code": "bad_input",
                "message": "olmaz",
            },
        )


class AllowlistTests(unittest.TestCase):
    #: `constant.rs:656-676` anlik goruntusu. Backend degisirse bu test kirilir
    #: ve sapma fark edilir -- sessizce `path_not_allowed` toplamak yerine.
    BACKEND_SNAPSHOT = (
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

    def test_allowlist_matches_backend_snapshot(self):
        self.assertEqual(protocol.AI_API_ALLOWLIST, self.BACKEND_SNAPSHOT)
        self.assertEqual(len(protocol.AI_API_ALLOWLIST), 19)

    def test_literal_path_matches_exactly(self):
        self.assertTrue(protocol.path_allowed("/auth/me"))
        self.assertFalse(protocol.path_allowed("/auth/m"))
        self.assertFalse(protocol.path_allowed("/AUTH/ME"))

    def test_placeholder_takes_exactly_one_segment(self):
        self.assertTrue(protocol.path_allowed("/notes/note123"))
        self.assertFalse(protocol.path_allowed("/notes/note123/files"))

    def test_trailing_slash_is_a_different_path(self):
        self.assertFalse(protocol.path_allowed("/notes/"))
        self.assertFalse(protocol.path_allowed("/auth/me/"))

    def test_empty_segments_never_fill_a_placeholder(self):
        self.assertFalse(protocol.path_allowed("/users//profile"))
        self.assertFalse(protocol.path_allowed("//notes"))

    def test_course_note_blobs_are_not_readable_over_the_api(self):
        self.assertTrue(protocol.path_allowed("/course-notes/n1/files"))
        self.assertFalse(protocol.path_allowed("/course-notes/n1/files/f1"))

    def test_forbidden_data_paths_are_not_on_the_list(self):
        for path in ("/meals", "/payments", "/messages", "/chatbot", "/meals/menu"):
            self.assertFalse(protocol.path_allowed(path), path)

    def test_template_is_the_pattern_not_the_path(self):
        self.assertEqual(protocol.route_template("/marks/u1"), "/marks/{user}")
        self.assertIsNone(protocol.route_template("/users"))

    def test_unlisted_path_never_reaches_the_wire(self):
        # Reddi tel USTUNDE degil, tele CIKMADAN once veriyoruz.
        with self.assertRaises(protocol.ApiRefused) as caught:
            protocol.build_api_request("01J", "demo", "/meals")
        self.assertEqual(
            caught.exception.code, protocol.ApiErrorCode.PATH_NOT_ALLOWED
        )


class TraceIdTests(unittest.TestCase):
    def test_ulid_shape_and_uniqueness(self):
        first, second = protocol.new_trace_id(), protocol.new_trace_id()
        self.assertEqual(len(first), 26)
        self.assertNotEqual(first, second)
        self.assertTrue(set(first) <= set("0123456789ABCDEFGHJKMNPQRSTVWXYZ"))


if __name__ == "__main__":
    unittest.main()
