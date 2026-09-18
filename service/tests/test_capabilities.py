"""Yetenek defterinin testleri.

Buradaki en onemli test bir GERCEGI pinler: backend'in ZEKA'ya gonderebildigi
adlar `chat.reply`, `rag.index`, `insight.student`, `insight.refresh`tir;
`insight.class` ilan edilir ama backend'de onu gonderen bir yol yoktur. Bu,
servisin backend'i cagirdigi depo yolundan (2. yon, `insight.*` -- calisir)
AYRI bir yondur. Iki taraf da degistiginde bu testler ve
`docs/BACKEND-GEREKSINIMLERI.md` madde 1 birlikte guncellenir.
"""

from __future__ import annotations

import unittest

from src import capabilities, handlers
from src.protocol import CapabilityError


class CapabilityNameTests(unittest.TestCase):
    def test_declared_names(self):
        self.assertEqual(
            capabilities.NAMES,
            ("insight.student", "insight.class", "insight.refresh", "insight.report"),
        )

    def test_backend_callable_set_is_the_dispatch_table(self):
        # constant.rs:568,574 (chat.reply, rag.index) + ai/insight.rs
        # (compute_student/refresh/**report**) ve web/insights.rs kapilari --
        # 2026-09-18. `insight.report`in sabiti (constant.rs:645), dagitimi ve
        # `POST /runs/{run_day}/report` kapisi ayni gun landedi.
        self.assertEqual(
            capabilities.BACKEND_CALLABLE_CAPABILITIES,
            (
                "chat.reply",
                "rag.index",
                "insight.student",
                "insight.refresh",
                "insight.report",
            ),
        )
        # `insight.class` ilan edilir ama backend GONDERMEZ (kadro listeleme
        # yolu yok). Backend tarafi acildiginda bu satiri ve
        # docs/BACKEND-GEREKSINIMLERI.md Madde 1'i birlikte guncelleyin.
        self.assertEqual(
            set(capabilities.NAMES) - set(capabilities.BACKEND_CALLABLE_CAPABILITIES),
            {"insight.class"},
        )

    def test_sections_vocabulary_is_the_summary_modules(self):
        self.assertEqual(
            capabilities.SECTIONS, ("marks", "attendance", "submission", "study")
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
        # Kayit defteri modul genelidir ve baska testler `handlers.wire()`
        # cagirir; bu test BOS bir defteri sart kosar.
        capabilities._handlers.clear()
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

    def test_summary_separates_the_three_facts(self):
        handlers.wire()
        text = capabilities.summary()
        # 1) backend'in GONDEREBILDIGI adlar ...
        self.assertIn(
            "backend'in cagirabildigi yetenekler: "
            "chat.reply, rag.index, insight.student, insight.refresh, "
            "insight.report",
            text,
        )
        # 2) ... depo yolunu (2. yon) kapsamadigi ...
        self.assertIn("servis->backend depo yolu: kopru/insight.*", text)
        # 3) ... ve ilan edilen her adin bir isleyicisi oldugu.
        self.assertIn("servis tarafi isleyiciler: 4/4 kayitli", text)
        self.assertIn("backend'in dagitim tablosunda olmayan: insight.class", text)
        # Eski hali "TANIMSIZ" diyordu ve isleyici kayitliyken bile servisin
        # bir sey yapmadigini ima ediyordu.
        self.assertNotIn("TANIMSIZ", text)


if __name__ == "__main__":
    unittest.main()
