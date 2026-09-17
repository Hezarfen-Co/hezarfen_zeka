"""Yapilandirma katmaninin testleri. Ortam degiskenleri test basina izole edilir."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from src import config

#: Testleri makinenin ortamindan yalitmak icin temizlenen degiskenler.
_CLEARED = {
    name: ""
    for name in (
        "LOG_LEVEL",
        "AI_BRIDGE_HOST",
        "AI_BRIDGE_PORT",
        "AI_BACKEND_URL",
        "AI_SHARED_TOKEN",
        "AI_TLS_FINGERPRINT",
        "AI_MAX_CONCURRENT",
        "ZEKA_SCHOOLS",
        "ZEKA_STUDENTS",
        "ZEKA_STUDENT_SOURCE",
        "ZEKA_STUDENT_FILE",
        "ZEKA_SOURCE",
        "ZEKA_DB_PASSWORD",
        "ZEKA_MAX_SCHOOL_POOLS",
        "ZEKA_SCHOOL_POOL_TTL_SECS",
        "ZEKA_SCHOOL_REGISTRY_TTL_SECS",
        "ZEKA_SCHOOL_CONNECT_TIMEOUT_SECS",
    )
}


def _env(**overrides):
    values = dict(_CLEARED)
    values.update(overrides)
    return mock.patch.dict(os.environ, values, clear=False)


class TokenTests(unittest.TestCase):
    def test_missing_token_is_refused_at_boot(self):
        # `${VAR:?}` mantigi.
        with _env(AI_SHARED_TOKEN=""):
            with self.assertRaises(config.ConfigError):
                config.Config(require_token=True)

    def test_token_may_be_skipped_for_offline_validation(self):
        with _env(AI_SHARED_TOKEN=""):
            self.assertFalse(config.Config(require_token=False).has_token)

    def test_secrets_never_reach_the_summary(self):
        with _env(AI_SHARED_TOKEN="cok-gizli-sir", ZEKA_DB_PASSWORD="parola123"):
            summary = config.Config().summary()
        self.assertNotIn("cok-gizli-sir", summary)
        self.assertNotIn("parola123", summary)
        self.assertIn("token=tanimli", summary)
        self.assertIn("db_parola=tanimli", summary)


class FingerprintTests(unittest.TestCase):
    def test_absent_fingerprint_means_tofu(self):
        with _env(AI_SHARED_TOKEN="t"):
            settings = config.Config()
        self.assertEqual(settings.tls_fingerprint, "")
        self.assertIn("TOFU", settings.summary())

    def test_colons_are_stripped_and_case_normalized(self):
        digest = "AB" * 32
        with _env(AI_SHARED_TOKEN="t", AI_TLS_FINGERPRINT=":".join(["AB"] * 32)):
            settings = config.Config()
        self.assertEqual(settings.tls_fingerprint, digest.lower())
        self.assertIn("PINLI", settings.summary())

    def test_a_short_fingerprint_is_refused(self):
        with _env(AI_SHARED_TOKEN="t", AI_TLS_FINGERPRINT="abc123"):
            with self.assertRaises(config.ConfigError):
                config.Config()


class ParsingTests(unittest.TestCase):
    def test_school_list_is_split_deduplicated_and_ordered(self):
        with _env(AI_SHARED_TOKEN="t", ZEKA_SCHOOLS=" a , b ,a, "):
            self.assertEqual(config.Config().schools, ("a", "b"))

    def test_out_of_range_port_is_refused(self):
        with _env(AI_SHARED_TOKEN="t", AI_BRIDGE_PORT="99999"):
            with self.assertRaises(config.ConfigError):
                config.Config()

    def test_unknown_choice_is_refused(self):
        with _env(AI_SHARED_TOKEN="t", ZEKA_SOURCE="sihir"):
            with self.assertRaises(config.ConfigError):
                config.Config()

    def test_file_student_source_needs_a_file(self):
        with _env(AI_SHARED_TOKEN="t", ZEKA_STUDENT_SOURCE="file"):
            with self.assertRaises(config.ConfigError):
                config.Config()

    def test_no_school_list_means_every_school(self):
        # Okul listesi artik kontrol veritabanindan gelir; buradaki degisken
        # yalnizca bir FILTREdir. Sabit bir varsayilan okul olmamali.
        with _env(AI_SHARED_TOKEN="t", ZEKA_SCHOOLS=""):
            self.assertEqual(config.Config().schools, ())

    def test_school_pool_knobs_are_parsed_and_bounded(self):
        with _env(AI_SHARED_TOKEN="t", ZEKA_MAX_SCHOOL_POOLS="3", ZEKA_SCHOOL_POOL_TTL_SECS="60"):
            settings = config.Config()
        self.assertEqual(settings.max_school_pools, 3)
        self.assertEqual(settings.school_pool_ttl_secs, 60.0)
        self.assertEqual(settings.school_registry_ttl_secs, 30.0)
        self.assertEqual(settings.school_connect_timeout_secs, 10.0)
        with _env(ZEKA_MAX_SCHOOL_POOLS="0"):
            with self.assertRaises(config.ConfigError):
                config.Config(require_token=False)

    def test_defaults_are_the_documented_ones(self):
        with _env(AI_SHARED_TOKEN="t"):
            settings = config.Config()
        self.assertEqual(settings.host, "hezarfen_backend")
        self.assertEqual(settings.port, 8090)
        self.assertEqual(settings.service, "zeka")
        self.assertEqual(settings.source_mode, "bridge")


if __name__ == "__main__":
    unittest.main()
