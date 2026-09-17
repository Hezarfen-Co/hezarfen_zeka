"""Segment hattinin LLM yapilandirma adlari (`src/segment/config.py`).

TEK AD KURALI (2026-09-17 temiz kesim): `LLM_API_KEY`, `LLM_BASE_URL`,
`LLM_MODEL_FLASH/PRO/REASONER`, `LLM_MODEL_ROLE`. Eski adlar (DEEPSEEK_API_KEY,
SEGMENT_API_KEY, SEGMENT_BASE_URL, SEGMENT_MODEL_*) DESTEKLENMEZ ve dolu
bulunurlarsa yapilandirma REDDEDILIR -- "yarim kalan bir adi sessizce yok
saymak", operatorun kendi dosyasinin artik okunmadigini fark etmemesi olurdu.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from src.segment.config import ESKI_LLM_ADLARI, SegmentConfig, SegmentConfigError
from src.segment.provider import build_provider

#: LLM ile ilgili butun adlar: testleri makinenin ortamindan yalitir.
_CLEARED = {
    name: ""
    for name in (
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_MODEL_FLASH",
        "LLM_MODEL_PRO",
        "LLM_MODEL_REASONER",
        "LLM_MODEL_ROLE",
    )
}


def _env(**overrides):
    values = dict(_CLEARED)
    values.update(overrides)
    return mock.patch.dict(os.environ, values, clear=False)


class CleanBreakTests(unittest.TestCase):
    def test_the_new_names_work(self):
        with _env(LLM_API_KEY="anahtar", LLM_BASE_URL="https://gecit.ornek/v1"):
            cfg = SegmentConfig.from_env()
        self.assertEqual(cfg.api_key, "anahtar")
        self.assertEqual(cfg.base_url, "https://gecit.ornek/v1")

    def test_every_removed_name_is_refused(self):
        for eski in ESKI_LLM_ADLARI:
            with self.subTest(eski=eski):
                with _env(**{eski: "deger"}):
                    with self.assertRaises(SegmentConfigError) as caught:
                        SegmentConfig.from_env()
                self.assertIn(eski, str(caught.exception))
                self.assertIn("LLM_API_KEY", str(caught.exception))

    def test_the_old_key_does_not_silently_work(self):
        # Kanit: eski ad tek basina ne anahtari doldurur ne de sessiz gecer.
        with _env(DEEPSEEK_API_KEY="eski-anahtar"):
            with self.assertRaises(SegmentConfigError):
                SegmentConfig.from_env()

    def test_a_mixed_environment_is_refused_too(self):
        # Yeni ad verilmis olsa bile eski ad duruyorsa ortam TEMIZ DEGILDIR.
        with _env(LLM_API_KEY="anahtar", DEEPSEEK_API_KEY="eski"):
            with self.assertRaises(SegmentConfigError):
                SegmentConfig.from_env()

    def test_no_key_at_all_means_no_key(self):
        with _env():
            self.assertFalse(SegmentConfig.from_env().api_key)


class ModelKnobTests(unittest.TestCase):
    def test_per_role_model_overrides(self):
        with _env(LLM_MODEL_FLASH="gpt-x-mini", LLM_MODEL_PRO="gpt-x"):
            cfg = SegmentConfig.from_env()
        self.assertEqual(cfg.model_ids["flash"], "gpt-x-mini")
        self.assertEqual(cfg.model_ids["pro"], "gpt-x")

    def test_role_selection_is_validated(self):
        with _env(LLM_MODEL_ROLE="yok-boyle-rol"):
            with self.assertRaises(SegmentConfigError):
                SegmentConfig.from_env()
        with _env(LLM_MODEL_ROLE="pro"):
            self.assertEqual(SegmentConfig.from_env().model_role, "pro")


class GatewayTests(unittest.TestCase):
    def test_the_default_gateway_can_be_replaced(self):
        with _env():
            self.assertEqual(SegmentConfig.from_env().base_url, "https://api.deepseek.com")

    def test_a_base_url_without_a_key_never_selects_a_real_gateway(self):
        with _env(LLM_BASE_URL="https://gecit.ornek/v1", LLM_API_KEY=""):
            cfg = SegmentConfig.from_env()
            self.assertFalse(cfg.api_key)
            self.assertEqual(build_provider(cfg, mock=False).name, "mock")

    def test_a_key_selects_the_real_gateway(self):
        with _env(LLM_API_KEY="anahtar", LLM_BASE_URL="https://gecit.ornek/v1"):
            self.assertNotEqual(build_provider(SegmentConfig.from_env(), mock=False).name, "mock")


if __name__ == "__main__":
    unittest.main()
