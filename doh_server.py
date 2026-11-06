"""DNS over HTTPS (DoH) — cho iOS điều hướng traffic MITM về proxy.

Khi thiết bị hỏi tên miền nằm trong PINNED_DOMAINS -> trả về IP của server này
để toàn bộ request tới Locket/RevenueCat/Firebase chạy qua proxy patch.
Tên miền khác -> resolve bình thường qua upstream (1.1.1.1 / 8.8.8.8).

Hỗ trợ 2 chuẩn:
  - `?dns=...`  (base64url DNS wire, chuẩn RFC 8484)
  - `?name=...&type=...` (chuẩn JSON của Google)
"""
import base64
import struct

import dns.message
import dns.query
import dns.rdatatype
import dns.resolver

import config


class DohError(Exception):
    pass


def _base64url_decode(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded)


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _pin(host: str) -> bool:
    """Chỉ pin các tên miền chính xác Locket/RevenueCat/Firebase (không pin hết google)."""
    h = host.rstrip(".")
    exact = {d for d in config.PINNED_DOMAINS if not d.startswith("*.")}
    wild = {d[2:] for d in config.PINNED_DOMAINS if d.startswith("*.")}
    if h in exact:
        return True
    # wildcard: *.locketcamera.com, *.googlevideo.com, *.youtube.com ...
    for w in wild:
        if h.endswith("." + w) or h == w:
            return True
    return False


def _wire_query_to_dict(qdata: bytes) -> dict:
    msg = dns.message.from_wire(qdata)
    q = msg.question[0]
    return {"name": q.name.to_text(), "qtype": q.rdtype}


def resolve_wire(qdata: bytes):
    """Nhận DNS wire (RFC 8484), trả về (wire_response, is_pinned_answer).

    Nếu câu hỏi thuộc domain bị pin -> dựng câu trả lời trỏ về PUBLIC_IP.
    Nếu không -> upstream thật.
    """
    try:
        qdict = _wire_query_to_dict(qdata)
    except Exception:
        raise DohError("Cannot parse DNS query")
    return _respond(qdict["name"], qdict["qtype"])


def _respond(name: str, qtype: int):
    """Xây DNS response (wire) cho một câu hỏi."""
    try:
        rtype = dns.rdatatype.to_text(qtype)
    except Exception:
        rtype = "A"
    request = dns.message.make_query(name, rtype)

    if _pin(name) and qtype in (dns.rdatatype.A, dns.rdatatype.AAAA):
        # Pin -> trả về IP proxy của chúng ta (địa chỉ mà thiết bị sẽ gọi)
        return _pinned_response(request, name, rtype), True
    # Không pin -> hỏi upstream thật
    return _upstream_response(request), False


def _pinned_response(request, name: str, rtype: str) -> bytes:
    """Dựng response A/AAAA trỏ về PUBLIC_IP (dùng để MITM)."""
    msg = dns.message.make_response(request)
    if rtype == "AAAA":
        # Nếu chỉ có IP v4, ta trả A. PUBLig_IP chỉ dùng v4.
        pass
    # Luôn trả A record
    msg.answer.append(
        dns.rrset.from_text(name, 30, "IN", "A", config.PUBLIC_IP)
    )
    return msg.to_wire()


def _upstream_response(request) -> bytes:
    """Resolver thật qua dns.resolver/query, fallback nhiều upstream."""
    name = request.question[0].name.to_text()
    rtype = dns.rdatatype.to_text(request.question[0].rdtype)
    last = None
    for server in config.UPSTREAM_DNS:
        try:
            q = dns.query.udp(request, server, timeout=3.0)
            return q.to_wire()
        except Exception as e:
            last = e
    if last is not None:
        # Trả response rỗng (SERVFAIL / name error) để không treo thiết bị
        resp = dns.message.make_response(request)
        resp.set_rcode(dns.rcode.SERVFAIL)
        return resp.to_wire()
    raise DohError("All upstream DNS failed")


def parse_wire_to_answer(qdata: bytes) -> tuple:
    """Trả (list_of_ips, pinned) — phục vụ for debug/CLI."""
    qdict = _wire_query_to_dict(qdata)
    return _respond(qdict["name"], qdict["qtype"])


# --- Chuẩn JSON (Google) cho DoH: /dns-query?name=X&type=A ---
def resolve_json(name: str, qtype: str = "A") -> dict:
    """Chuẩn JSON response, không nhất thiết dùng cho iOS nhưng tiện debug."""
    if qtype.upper() == "AAAA":
        qtype = "A"
    q = dns.rdatatype.from_text(qtype)
    if _pin(name) and qtype.upper() in ("A",):
        return {
            "Status": 0,
            "Question": [{"name": name, "type": qtype.upper()}],
            "Answer": [
                {
                    "name": name,
                    "type": qtype.upper(),
                    "TTL": 30,
                    "data": config.PUBLIC_IP,
                }
            ],
        }
    # upstream
    try:
        txt = _upstream_response(dns.message.make_query(name, q)).decode("utf-8", "ignore")
        return {"Status": 0, "Answer": [{"name": name, "type": qtype.upper(), "data": txt}]}
    except Exception as e:
        return {"Status": 2, "Question": [{"name": name, "type": qtype.upper()}], "error": str(e)}


def decode_question(qdata: bytes) -> str:
    """Hiển thị tên miền câu hỏi (phục vụ CLI/debug)."""
    q = _wire_query_to_dict(qdata)
    return f"{q['name']} {dns.rdatatype.to_text(q['qtype'])}"