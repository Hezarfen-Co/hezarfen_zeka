"""ZEKA servisinin ortam degiskeni katmani.

Desen podcast servisinin `src/config.py` dosyasindan alinmistir: ortamdan okuyan
kucuk yardimcilar, tek bir `Config` sinifi, ve hatali yapilandirmada `exit 2`.
Backend'in kendi kurali da ayni: yanlis yapilandirma boot'u cokertir, eksik
(opsiyonel) yapilandirma yalnizca bir ozelligi kapatir.

Sir hijyeni: `AI_SHARED_TOKEN` ve veritabani parolasi HICBIR ZAMAN loglanmaz.
`summary()` yalnizca "tanimli / TANIMSIZ" yazar.

Sabitlerin kaynagi backend'in `src/constant.rs` dosyasidir. Kopyalanan her
sayinin yaninda satir numarasi vardir; sapma riski
`docs/BACKEND-GEREKSINIMLERI.md` icinde ayrica anlatilir.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# --- gunlukleme ------------------------------------------------------------
# Podcast ile ayni desen: `logging` modulu yok, ASCII Turkce, `[zeka] ` onekli,
# `print(..., flush=True)`. Windows konsolu ASCII disini bozuyor.

LOG_LEVELS = {"debug": 10, "info": 20, "warn": 30, "warning": 30, "error": 40}
DEFAULT_LOG_LEVEL = "info"

_active_level = LOG_LEVELS[DEFAULT_LOG_LEVEL]


class ConfigError(Exception):
    """Yapilandirma hatasi. `load()` bunu yakalayip `exit 2` yapar."""


def set_log_level(name: str) -> None:
    global _active_level
    level = LOG_LEVELS.get(name.strip().lower())
    if level is None:
        raise ConfigError(
            f"LOG_LEVEL gecersiz: '{name}' (beklenen: {', '.join(sorted(LOG_LEVELS))})"
        )
    _active_level = level


def log(level: str, message: str) -> None:
    if LOG_LEVELS.get(level, LOG_LEVELS[DEFAULT_LOG_LEVEL]) >= _active_level:
        print(f"[zeka] {message}", flush=True)


# --- ortam okuyuculari -----------------------------------------------------


def env_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value is not None and value.strip() else default


def env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{name} bir tamsayi olmali, alinan: '{raw}'") from exc
    if value < minimum or value > maximum:
        raise ConfigError(f"{name} {minimum}..{maximum} araliginda olmali, alinan: {value}")
    return value


def env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{name} bir sayi olmali, alinan: '{raw}'") from exc
    if value < minimum or value > maximum:
        raise ConfigError(f"{name} {minimum}..{maximum} araliginda olmali, alinan: {value}")
    return value


def env_choice(name: str, default: str, choices: tuple[str, ...]) -> str:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value not in choices:
        raise ConfigError(
            f"{name} su degerlerden biri olmali: {', '.join(choices)}; alinan: '{raw}'"
        )
    return value


def env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """Virgulle ayrilmis liste. Bos ogeler atilir, sira korunur, tekrar silinir."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return tuple(default)
    seen: list[str] = []
    for piece in raw.split(","):
        item = piece.strip()
        if item and item not in seen:
            seen.append(item)
    if not seen:
        raise ConfigError(f"{name} verildi ama hicbir gecerli oge icermiyor: '{raw}'")
    return tuple(seen)


def _absolute(path: str) -> str:
    if not path:
        return path
    return str(Path(path).expanduser().resolve())


# --- sihirli sayilar -------------------------------------------------------
# Protokol disi butun esikler burada toplanir; kodda ciplak sayi birakilmaz.

CERT_FETCH_TIMEOUT_SECS = 10.0
"""`GET /ai/certificate` icin HTTP zaman asimi (saniye)."""

SOURCE_MODES = ("bridge", "file")
"""Veri erisim cephesinin arkasinda ne var: canli kopru mu, JSON fikstur mu."""

STUDENT_SOURCES = ("config", "file")
"""Ogrenci kimlik kaynagi. Backend'de kullanici listeleme yolu YOK (bkz.
`docs/BACKEND-GEREKSINIMLERI.md` madde 3); bu yuzden liste disaridan verilir."""


class Config:
    """Tek seferde okunan, sonra degismeyen yapilandirma."""

    def __init__(self, require_token: bool = True) -> None:
        self.log_level = env_str("LOG_LEVEL", DEFAULT_LOG_LEVEL)
        set_log_level(self.log_level)

        # --- kopru adresi --------------------------------------------------
        # Backend QUIC *sunucusudur*, servis ona dial-out eder
        # (`ai/protocol.rs:5-7`). Bu yuzden ZEKA port acmaz.
        self.host = env_str("AI_BRIDGE_HOST", "hezarfen-backend")
        self.port = env_int("AI_BRIDGE_PORT", 8090, 1, 65535)
        # Sertifikayi cektigimiz HTTP adresi; QUIC adresinden ayridir.
        self.backend_url = env_str("AI_BACKEND_URL", "http://hezarfen-backend:8080").rstrip("/")
        self.server_name = env_str("AI_TLS_SERVER_NAME", "localhost")

        # --- kimlik ---------------------------------------------------------
        self.service = env_str("AI_SERVICE_NAME", "zeka")
        # `${VAR:?}` mantigi: bos ise acilista reddet.
        self.token = env_str("AI_SHARED_TOKEN", "")
        self.has_token = bool(self.token)

        # --- TLS pinleme -----------------------------------------------------
        # Bos birakilirsa TOFU: `GET /ai/certificate` ne donerse ona guvenilir.
        # Podcast ve Celebi tam olarak bunu yapiyor ve denetimde zafiyet olarak
        # isaretlendi. Doldurulursa dogrulanir, uyusmazsa baglanilmaz.
        self.tls_fingerprint = env_str("AI_TLS_FINGERPRINT", "").strip().lower().replace(":", "")

        # --- kopru davranisi -------------------------------------------------
        # Backend clamp'i: 1..=AI_MAX_CONCURRENT_PER_WORKER (`constant.rs:547`).
        self.max_concurrent = env_int("AI_MAX_CONCURRENT", 4, 1, 64)
        # Ustel geri cekilme. Podcast `unsupported_protocol` alinca `exit 2`
        # yapiyor; biz yapmiyoruz (bkz. `bridge.py`), tavana kadar bekleyip
        # yeniden deniyoruz -- backend yeniden dagitilinca kendiliginden toparlar.
        self.reconnect_secs = env_float("AI_RECONNECT_SECS", 3.0, 0.1, 300.0)
        self.reconnect_max_secs = env_float("AI_RECONNECT_MAX_SECS", 120.0, 1.0, 3600.0)

        # --- kapsam -----------------------------------------------------------
        # Her frame kendi okulunu adlandirir (`ai/protocol.rs:36-47`); `Hello`
        # okul tasimaz. Filo paylasimlidir, bu yuzden hangi okullari isleyecegimizi
        # yapilandirmadan ogreniyoruz -- backend'de okul listeleme yolu yok.
        self.schools = env_list("ZEKA_SCHOOLS", ("hezarfen-demo",))
        self.student_source = env_choice("ZEKA_STUDENT_SOURCE", "config", STUDENT_SOURCES)
        self.students = env_list("ZEKA_STUDENTS", ())
        self.student_file = _absolute(env_str("ZEKA_STUDENT_FILE", ""))

        # --- veri cephesi ------------------------------------------------------
        self.source_mode = env_choice("ZEKA_SOURCE", "bridge", SOURCE_MODES)
        self.fixture_root = _absolute(env_str("ZEKA_FIXTURE_ROOT", "/data/zeka/fixtures"))
        self.api_timeout_secs = env_float("ZEKA_API_TIMEOUT_SECS", 15.0, 1.0, 300.0)
        self.blob_timeout_secs = env_float("ZEKA_BLOB_TIMEOUT_SECS", 60.0, 1.0, 3600.0)

        # --- zamanlama ---------------------------------------------------------
        # Hesap turlarinin ne siklikla kosacagi. 0 = periyodik kosu kapali,
        # yalnizca `insight.refresh` cagrisiyla calisir.
        self.refresh_interval_secs = env_float(
            "ZEKA_REFRESH_INTERVAL_SECS", 3600.0, 0.0, 604800.0
        )
        self.refresh_jitter_secs = env_float("ZEKA_REFRESH_JITTER_SECS", 60.0, 0.0, 3600.0)
        self.refresh_batch = env_int("ZEKA_REFRESH_BATCH", 25, 1, 5000)

        # --- ZEKA'nin kendi veritabani ------------------------------------------
        # Hesap ciktilari burada durur. Okulun veritabanina ZEKA yazmaz; kopru
        # zaten salt-okumadir (`ai/server.rs:719-726` -> `method_not_allowed`).
        self.db_url = env_str("ZEKA_DB_URL", "ws://hezarfen-surrealdb:8000/rpc")
        self.db_namespace = env_str("ZEKA_DB_NS", "hezarfen")
        self.db_database = env_str("ZEKA_DB_NAME", "zeka")
        self.db_user = env_str("ZEKA_DB_USER", "")
        self.db_password = env_str("ZEKA_DB_PASSWORD", "")
        self.has_db_password = bool(self.db_password)

        if require_token and not self.has_token:
            raise ConfigError(
                "AI_SHARED_TOKEN tanimli degil; backend ile ayni sir olmadan kayit yapilamaz"
            )
        if self.student_source == "file" and not self.student_file:
            raise ConfigError("ZEKA_STUDENT_SOURCE=file ama ZEKA_STUDENT_FILE bos")
        if self.tls_fingerprint and len(self.tls_fingerprint) != 64:
            raise ConfigError(
                "AI_TLS_FINGERPRINT 64 karakterlik SHA-256 hex olmali "
                f"(iki nokta ayraclari atilir), alinan uzunluk: {len(self.tls_fingerprint)}"
            )

    def summary(self) -> str:
        """Tek satirlik acilis ozeti. Sir icermez."""
        students = str(len(self.students)) if self.student_source == "config" else "?"
        tazeleme = "kapali" if self.refresh_interval_secs <= 0 else f"{self.refresh_interval_secs}s"
        return (
            f"servis='{self.service}' hedef={self.host}:{self.port} "
            f"backend={self.backend_url} tls_ad={self.server_name} "
            f"tls_parmak_izi={'PINLI' if self.tls_fingerprint else 'TOFU(pinsiz)'} "
            f"token={'tanimli' if self.has_token else 'TANIMSIZ'} "
            f"max_es_zamanli={self.max_concurrent} "
            f"yeniden_baglanma={self.reconnect_secs}s..{self.reconnect_max_secs}s "
            f"okullar={','.join(self.schools)} "
            f"ogrenci_kaynagi={self.student_source} ogrenci_sayisi={students} "
            f"veri_cephesi={self.source_mode} fikstur_kok={self.fixture_root} "
            f"api_zaman_asimi={self.api_timeout_secs}s "
            f"tazeleme={tazeleme} parti={self.refresh_batch} "
            f"{self._depo_ozeti()} "
            f"log={self.log_level}"
        )


def _depo_ozeti_impl(self) -> str:
    """Yazma hedefini ozetler — DSN ASLA loglanmaz.

    Eskiden bu satir kosulsuz SurrealDB adresini basiyordu ve Postgres'e
    yazilirken bile "db=ws://hezarfen-surrealdb:8000/rpc" diyordu. Acilis
    logunun yanlis depoyu gostermesi, bir arizayi tesbit ederken insani
    saatlerce yanlis yere baktirir.
    """
    import os

    dsn = os.environ.get("ZEKA_PG_DSN", "").strip()
    if dsn:
        try:
            import urllib.parse

            parsed = urllib.parse.urlsplit(dsn)
            yer = f"{parsed.hostname or '?'}{parsed.path}"
        except Exception:  # noqa: BLE001
            yer = "<cozumlenemedi>"
        return f"depo=postgres {yer}"
    return (
        f"depo=surrealdb(eski) {self.db_url} ns={self.db_namespace} "
        f"db_ad={self.db_database} "
        f"db_parola={'tanimli' if self.has_db_password else 'TANIMSIZ'}"
    )


Config._depo_ozeti = _depo_ozeti_impl


def load(require_token: bool = True) -> Config:
    """Yapilandirmayi oku; hataliysa tek satir basip `exit 2`."""
    try:
        return Config(require_token=require_token)
    except ConfigError as exc:
        print(f"[zeka] yapilandirma hatasi: {exc}", flush=True)
        sys.exit(2)
