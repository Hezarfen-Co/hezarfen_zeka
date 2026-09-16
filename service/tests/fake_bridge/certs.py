"""Test icin kendi kendine imzali sertifika uretimi.

Backend'in `src/ai/tls.rs:139-148` (`self_signed`) davranisini taklit eder:
`rcgen::generate_simple_self_signed(["localhost", "127.0.0.1"])` -- yani SAN
listesi bir DNS adi ve bir IP adresi tasir, sertifika CA DEGILDIR ve her
boot'ta yeniden uretilir.

Parmak izi `tls.rs:150-153` ile ayni sekilde hesaplanir:
`hex::encode(Sha256::digest(leaf.as_ref()))` -- yani DER'in SHA-256'si, kucuk
harf hex, iki nokta ayraci yok.

DIKKAT: bu modul YALNIZCA test altyapisidir. Uretim kodu sertifika URETMEZ;
onu backend'den `GET /ai/certificate` ile CEKER.
"""

from __future__ import annotations

import datetime
import hashlib
import ipaddress

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

#: Backend'in `self_signed()` fonksiyonundaki ad listesi (`tls.rs:140`).
SELF_SIGNED_NAMES = ("localhost", "127.0.0.1")


class SelfSignedCertificate:
    """Uretilmis bir sertifika: PEM govdeleri + backend'in bildirdigi parmak izi."""

    def __init__(self, cert_pem: str, key_pem: str, fingerprint: str) -> None:
        self.cert_pem = cert_pem
        self.key_pem = key_pem
        self.fingerprint = fingerprint


def generate(names: tuple[str, ...] = SELF_SIGNED_NAMES) -> SelfSignedCertificate:
    """Tek sertifikalik bir zincir uret.

    `is_ca=False`: rcgen'in `generate_simple_self_signed` fonksiyonu da CA
    isaretlemez. Istemci onu CA deposuna PINLEYEREK dogrular, zincir kurarak
    degil -- bu yuzden CA bayragi gerekmez ve backend'e sadik kalmak icin
    kasitli olarak verilmez.
    """
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0])])
    now = datetime.datetime.now(datetime.timezone.utc)

    alt_names: list[x509.GeneralName] = []
    for name in names:
        try:
            alt_names.append(x509.IPAddress(ipaddress.ip_address(name)))
        except ValueError:
            alt_names.append(x509.DNSName(name))

    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        # Saat kaymasini yutmak icin bir gun geriden baslar.
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    cert_pem = certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    # `tls.rs:150-153` ile ayni hesap: DER'in SHA-256'si.
    fingerprint = hashlib.sha256(
        certificate.public_bytes(serialization.Encoding.DER)
    ).hexdigest()
    return SelfSignedCertificate(cert_pem, key_pem, fingerprint)
