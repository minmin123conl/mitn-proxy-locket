"""Quản lý Root CA — tự tạo nếu chưa có, cung cấp cert để cài trên thiết bị."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

import config


def _generate_ca():
    """Tạo Root CA mới. Chỉ chạy một lần khi chưa có cert."""
    config.CA_DIR.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    name = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, config.CA_SUBJECT["countryName"]),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, config.CA_SUBJECT["organizationName"]),
        x509.NameAttribute(NameOID.COMMON_NAME, config.CA_SUBJECT["commonName"]),
    ])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=config.CA_VALID_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    config.CA_DIR.mkdir(parents=True, exist_ok=True)
    config.CA_KEY.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    config.CA_CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return key, cert


def get_ca():
    """Trả về (private_key, cert) của Root CA, tự tạo nếu chưa có."""
    if not config.CA_KEY.exists() or not config.CA_CERT.exists():
        key, cert = _generate_ca()
    else:
        key = serialization.load_pem_private_key(config.CA_KEY.read_bytes(), password=None)
        cert = x509.load_pem_x509_certificate(config.CA_CERT.read_bytes())
    return key, cert


def ca_cert_pem() -> str:
    """Cert dạng PEM, dùng trong mobileconfig (base64)."""
    return config.CA_CERT.read_text() if config.CA_CERT.exists() else get_ca()[1].public_bytes(
        serialization.Encoding.PEM
    ).decode()


def cert_der_base64() -> str:
    """Cert dạng DER base64, dùng để nhúng vào mobileconfig (PayloadContent)."""
    from base64 import b64encode
    cert = x509.load_pem_x509_certificate(config.CA_CERT.read_bytes())
    return b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()