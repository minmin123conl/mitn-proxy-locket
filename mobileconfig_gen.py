"""Sinh ra file .mobileconfig cho iOS: (1) Root CA + DNS DoH, (2) Profile Service enroll.

Giống hệt cấu trúc 2 file đã phân tích:
  - com.apple.security.root   -> Root CA
  - com.apple.dnsSettings.managed -> DNS over HTTPS (DoH) trỏ về server này
  - Profile Service (enroll)  -> đăng ký thiết bị lấy bản quyền
"""
import uuid
from xml.sax.saxutils import escape

import config
import ca_manager


def _plist(inner: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n' + inner + "</plist>\n"
    )


def _domains() -> str:
    """Danh sách SupplementalMatchDomains (các tên miền bị MITM)."""
    seen = set()
    parts = []
    for d in sorted(config.PINNED_DOMAINS):
        if d in seen:
            continue
        if d.startswith("*."):
            continue  # supplemental match dùng tên cụ thể
        seen.add(d)
        parts.append(f"        <string>{escape(d)}</string>")
    return "\n".join(parts)


def _dns_payload(uuid_val: str) -> str:
    """Payload com.apple.dnsSettings.managed."""
    return f"""
    <dict>
        <key>PayloadType</key>
        <string>com.apple.dnsSettings.managed</string>
        <key>PayloadVersion</key>
        <integer>1</integer>
        <key>PayloadIdentifier</key>
        <string>com.locketgold.dns.{uuid_val}</string>
        <key>PayloadUUID</key>
        <string>{uuid_val}</string>
        <key>PayloadDisplayName</key>
        <string>Locket Gold Network DNS</string>
        <key>PayloadDescription</key>
        <string>DNS qua proxy MITM Locket Gold</string>
        <key>DNSSettings</key>
        <dict>
            <key>DNSProtocol</key>
            <string>HTTPS</string>
            <key>ServerURL</key>
            <string>https://{config.PUBLIC_HOST}/dns-query/{{token}}</string>
            <key>SupplementalMatchDomains</key>
            <array>
{_domains()}
            </array>
        </dict>
    </dict>
    """


def _ca_payload(uuid_val: str) -> str:
    """Payload com.apple.security.root."""
    der = ca_manager.cert_der_base64()
    return f"""
    <dict>
        <key>PayloadType</key>
        <string>com.apple.security.root</string>
        <key>PayloadVersion</key>
        <integer>1</integer>
        <key>PayloadIdentifier</key>
        <string>com.locketgold.ca.{uuid_val}</string>
        <key>PayloadUUID</key>
        <string>{uuid_val}</string>
        <key>PayloadDisplayName</key>
        <string>Locket Gold Network</string>
        <key>PayloadDescription</key>
        <string>Root CA de giai ma traffic Locket</string>
        <key>PayloadContent</key>
        <data>
{der}
        </data>
    </dict>
    """


def build_dns_ca_profile(token: str) -> str:
    """Profile cấu hình: Root CA + DNS DoH. Link này cài thường xuyên nhất."""
    ca_uuid = str(uuid.uuid4()).upper()
    dns_uuid = str(uuid.uuid4()).upper()
    top_uuid = str(uuid.uuid4()).upper()
    body = _ca_payload(ca_uuid).replace("{token}", token)
    body += _dns_payload(dns_uuid).replace("{token}", token)
    inner = f"""
<dict>
    <key>PayloadDisplayName</key>
    <string>Locket Gold Network ({token})</string>
    <key>PayloadDescription</key>
    <string>Cau hinh DNS + Root CA cho {token}</string>
    <key>PayloadIdentifier</key>
    <string>com.locketgold.profile.{token}</string>
    <key>PayloadOrganization</key>
    <string>Locket Gold Network</string>
    <key>PayloadRemovalDisallowed</key>
    <false/>
    <key>PayloadType</key>
    <string>Configuration</string>
    <key>PayloadUUID</key>
    <string>{top_uuid}</string>
    <key>PayloadVersion</key>
    <integer>1</integer>
    <key>PayloadContent</key>
    <array>{body}
    </array>
</dict>
"""
    return _plist(inner)


def build_enroll_profile(token: str) -> str:
    """Profile Service enroll — chỉ dùng một lần để đăng ký thiết bị (UDID/IMEI)."""
    challenge = uuid.uuid4().hex
    top_uuid = str(uuid.uuid4()).upper()
    callback = f"https://{config.PUBLIC_HOST}/api/profile/callback/{challenge}"
    inner = f"""
<dict>
    <key>PayloadDisplayName</key>
    <string>Locket Gold Enrollment</string>
    <key>PayloadDescription</key>
    <string>Dang ky thiet bi {escape(token)}</string>
    <key>PayloadIdentifier</key>
    <string>com.locketgold.profile-service.{challenge}</string>
    <key>PayloadOrganization</key>
    <string>Locket Gold Network</string>
    <key>PayloadType</key>
    <string>Profile Service</string>
    <key>PayloadUUID</key>
    <string>{top_uuid}</string>
    <key>PayloadVersion</key>
    <integer>1</integer>
    <key>PayloadContent</key>
    <dict>
        <key>URL</key>
        <string>{callback}</string>
        <key>DeviceAttributes</key>
        <array>
            <string>UDID</string>
            <string>PRODUCT</string>
            <string>VERSION</string>
            <string>SERIAL</string>
            <string>IMEI</string>
        </array>
        <key>Challenge</key>
        <string>{challenge}</string>
    </dict>
</dict>
"""
    return _plist(inner)