"""Yetenek defterinin testleri.

Buradaki en onemli test bir EKSIKLIGI pinler: backend ZEKA'nin yeteneklerinin
hicbirini **cagiramaz** (dagitim tablosunda bu adlar yok), dolayisiyla ZEKA'ya
hic `Request` gondermez. Bu, servisin backend'i cagirdigi depo yolundan (2. yon,
`insight.*` -- calisir) AYRI bir yondur. Backend tarafi duzeldiginde bu test
guncellenecek ve degisiklik goze carpacak.
"""

from __future__ import annotations

import unittest

from src import capabilities
from src.protocol import CapabilityError


class CapabilityNameTests(unittest.TestCase):
    def test_declared_names(self):
        self.assertEqual(
            capabilities.NAMES,
            ("insight.student", "insight.class", "insight.refresh"),
        )

    def test_backend_can_call_none_of_them(self):
        # constant.rs:568 ve :574 -- backend'in cagirabildigi tek iki ad.
        self.assertEqual(
            capabilities.BACKEND_CALLABLE_CAPABILITIES, ("chat.reply", "rag.index")
        )
        self.assertEqual(
            set(capabilities.NAMES) & set(capabilities.BACKEND_CALLABLE_CAPABILITIES),
            set(),
            "backend artik bir ZEKA yetenegini cagirabiliyorsa bu testi ve "
            "docs/BACKEND-GEREKSINIMLERI.md madde 1'i guncelleyin",
        )

    def test_every_name_has_a_schema(self):
        self.assertEqual(set(capabilities.SCHEMAS), set(capabilities.NAMES))
        for request_type, response_type in capabilities.SCHEMAS.values():
            self.assertTrue(hasattr(request_type, "__annotations__"))
            self.assertTrue(hasattr(response_type, "__annotations__"))

    def test_student_payload_carries_no_school(self):
        # Okul cerceve seviyesindedir (ai/protocol.rs:36-47); payload'da ikinci
        # bir kaynak olmasi ikisinin celisebilecegi bir yer yaratirdi.
        self.assertNotIn("school", capabilities.StudentRequest.__annotations__)
        self.assertNotIn("school", capabilities.ClassRequest.__annotations__)
        self.assertNotIn("school", capabilities.RefreshRequest.__annotations__)


class DispatchTests(unittest.TestCase):
    def tearDown(self):
        capabilities._handlers.clear()

    def test_unknown_capability_is_refused(self):
        with self.assertRaises(CapabilityError) as caught:
            capabilities.dispatch("insight.student", "demo", {})
        self.assertEqual(caught.exception.code, "unknown_capability")

    def test_registering_an_undeclared_name_is_refused(self):
        with self.assertRaises(KeyError):
            capabilities.register("chat.reply", lambda school, payload: {})

    def test_handler_receives_the_school_from_the_frame(self):
        seen = {}

        def handler(school, payload):
            seen["school"] = school
            seen["payload"] = payload
            return {"user_id": payload["user_id"]}

        capabilities.register(capabilities.INSIGHT_STUDENT, handler)
        result = capabilities.dispatch("insight.student", "demo", {"user_id": "u1"})
        self.assertEqual(seen["school"], "demo")
        self.assertEqual(result, {"user_id": "u1"})

    def test_non_object_payload_is_refused(self):
        capabilities.register(capabilities.INSIGHT_CLASS, lambda school, payload: {})
        with self.assertRaises(CapabilityError) as caught:
            capabilities.dispatch("insight.class", "demo", ["liste"])
        self.assertEqual(caught.exception.code, "bad_request")

    def test_summary_names_the_callable_direction_only(self):
        text = capabilities.summary()
        # Liste backend'in CAGIRABILDIGIDIR ...
        self.assertIn("backend'in cagirabildigi yetenekler: chat.reply, rag.index", text)
        self.assertIn("HENUZ cagrilmiyor", text)
        # ... ve depo yolunu (2. yon) kapsamadigi acikca yazilidir.
        self.assertIn("servis->backend depo yolu: kopru/insight.*", text)
        # Eski hali depo yolu calismaya basladiktan sonra "backend insight'i
        # hic bilmiyor" diye okunuyordu.
        self.assertNotIn("TANIMSIZ", text)


if __name__ == "__main__":
    unittest.main()
