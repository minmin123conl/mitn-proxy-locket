"""Ứng dụng FastAPI: Web enroll + CA + DoH + MITM proxy patch.

Deploy:
  PUBLIC_HOST=proxy.example.com PUBLIC_IP=1.2.3.4 uvicorn main:app --host 0.0.0.0 --port 80

Cần đặt phía sau reverse proxy (nginx/caddy) để:
  - TLS cho PUBLIC_HOST (bắt buộc vì mobileconfig dùng https:// cho DoH)
  - trỏ mọi request về app này
"""
import base64
import json
import logging
import uuid

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse

import config
import ca_manager
import doh_server
import mobileconfig_gen
import patcher

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("mitm")

app = FastAPI(title="Locket Gold Network MITM", version="1.0.0")

# Biến chung proxy
_upstream = httpx.AsyncClient(
    timeout=15.0,
    follow_redirects=False,
    headers={
        "User-Agent": "LocketGold/1.0",
    },
)
_devices = {}  # challenge -> {udid, product, version, serial, imei, token}


# ============================================================
# Trang chủ + cài đặt hướng dẫn
# ============================================================
INDEX_HTML = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Locket Gold Network</title>
<style>
  body { font-family: -apple-system, sans-serif; margin: 0; padding: 24px; background: #0f1220; color: #e8e8f0; }
  .card { max-width: 560px; margin: 0 auto; background: #1b2038; border-radius: 16px; padding: 24px; }
  h1 { font-size: 22px; margin: 0 0 8px; }
  p { color: #a9b0d0; line-height: 1.6; }
  .row { background: #242b4a; border-radius: 10px; padding: 16px; margin: 12px 0; }
  .row h3 { margin: 0 0 6px; font-size: 16px; }
  a.btn { display: inline-block; margin-top: 8px; padding: 10px 18px; border-radius: 10px;
          background: #4f6ef2; color: #fff; text-decoration: none; font-weight: 600; }
  a.btn.alt { background: #2f385e; }
  code { background: #0f1220; padding: 2px 6px; border-radius: 6px; font-size: 13px; }
  .token { color: #f2c94c; font-size: 15px; }
  input { padding: 8px 10px; border-radius: 8px; border: 1px solid #39406b; background: #0f1220; color: #fff; width: 180px; }
  table { width: 100%%; border-collapse: collapse; margin-top: 8px; font-size: 13px; }
  td, th { padding: 6px 8px; text-align: left; border-bottom: 1px solid #2a3150; color: #a9b0d0; }
</style>
</head>
<body>
<div class="card">
  <h1>🔐 Locket Gold Network</h1>
  <p>Server proxy MITM tự cập nhật photobooth/filter theo phiên bản Locket mới.
     Cài profile dưới đây để đưa toàn bộ traffic Locket/RevenueCat/Firebase qua proxy này.</p>

  <div class="row">
    <h3>Bước 1 — Đăng ký thiết bị (bản quyền)</h3>
    <p>Cài profile này để iOS gửi UDID/IMEI xác thực. Chỉ cần làm một lần.</p>
    <a class="btn" href="/api/enroll">Cài profile Đăng ký thiết bị</a>
  </div>

  <div class="row">
    <h3>Bước 2 — Cài cấu hình DNS + Root CA</h3>
    <p>Profile này trỏ DNS (DoH) về server + cài Root CA để giải mã traffic Locket.</p>
    <a class="btn alt" href="/profile/dns">Cài profile DNS + CA</a>
  </div>

  <div class="row">
    <h3>Bước 3 — Sau khi dùng</h3>
    <p>Nhớ <b>trong phần cài đặt certificate, bật "Bật tin cậy đầy đủ"</b> cho Root CA,
       nếu không traffic sẽ không được giải mã sửa payload.</p>
  </div>

  <p style="font-size:12px;color:#6f7699;">Server: <code>{host}</code> · Root CA: <code>Locket Gold Network Root CA</code></p>
</div>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return INDEX_HTML.replace("{host}", config.PUBLIC_HOST)


# ============================================================
# Web enroll — sinh profile theo token
# ============================================================
@app.get("/api/enroll")
async def enroll():
    token = uuid.uuid4().hex[:12]
    return Response(
        content=mobileconfig_gen.build_enroll_profile(token),
        media_type="application/x-apple-aspen-config",
    )


@app.get("/profile/dns")
async def profile_dns():
    token = uuid.uuid4().hex[:12]
    return Response(
        content=mobileconfig_gen.build_dns_ca_profile(token),
        media_type="application/x-apple-aspen-config",
    )


@app.post("/api/profile/callback/{challenge}")
async def profile_callback(challenge: str, request: Request):
    """iOS gọi lại đây sau khi xác nhận cài profile enroll (chứa UDID/IMEI)."""
    try:
        body = await request.json()
    except Exception:
        try:
            form = await request.form()
            body = dict(form)
        except Exception:
            body = {}
    _devices[challenge] = _devices.get(challenge, {})
    _devices[challenge].update(body)
    _devices[challenge]["challenge"] = challenge
    log.info("Enroll device: %s", body)
    return {"status": "ok", "provisioned": False}


# ============================================================
# CA endpoint — tải root CA trực tiếp
# ============================================================
@app.get("/ca.pem", response_class=PlainTextResponse)
async def ca_pem():
    return ca_manager.ca_cert_pem()


@app.get("/ca.crt")
async def ca_crt():
    return Response(
        content=ca_manager.ca_cert_pem(),
        media_type="application/x-x509-ca-cert",
    )


# ============================================================
# DoH
# ============================================================
@app.get("/dns-query/{token}")
async def dns_query(token: str, request: Request, dns: str = "", name: str = "", type: str = ""):
    # check token cho phép
    if config.ALLOWED_TOKENS and token not in config.ALLOWED_TOKENS:
        return Response("Forbidden", status_code=403)

    if dns:
        # RFC 8484: wire format
        try:
            qdata = doh_server._base64url_decode(dns)
            wire, _pinned = doh_server.resolve_wire(qdata)
        except doh_server.DohError as e:
            return Response(str(e), status_code=400)
        except Exception as e:
            return Response(f"Bad request: {e}", status_code=400)
        return Response(
            content=wire,
            media_type="application/dns-message",
        )
    if name:
        res = doh_server.resolve_json(name, type or "A")
        return Response(content=json.dumps(res), media_type="application/dns-json")

    return Response("Missing dns/name param", status_code=400)


# ============================================================
# MITM proxy — thiết bị gọi qua host được pin
# ============================================================
@app.api_route("/proxy/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
async def proxy_pass(path: str, request: Request):
    """Proxy chuyển tiếp: đọc upstream THẬT, patch (nếu cần), trả về.

    iOS chỉ gửi Host gốc (api.revenuecat.com...) đến IP proxy. Phần lớn reverse
    proxy chuyển Host đó vào đây theo path /proxy/... Dù vậy, ta dùng lại giá trị
    Host gốc (lấy từ header) để gọi upstream cho đúng.
    """
    host_header = request.headers.get("host") or config.PUBLIC_HOST
    scheme = "https"
    # Host header có thể là tên miền thật (proxy đặt sau reverse cho phép SNI).
    # Nếu là PUBLIC_HOST và path bắt đầu /proxy/, ta phục hồi host thật từ query
    # (kỹ thuật "fake host" điển hình) hoặc từ subdomain.
    upstream_host = host_header.split(":")[0]
    url = f"{scheme}://{upstream_host}/{path}"
    if upstream_host.lower() in (config.PUBLIC_HOST.split(':')[0], "localhost", "127.0.0.1"):
        # Chưa biết host thật -> thử lấy từ query param thêm khi cấu hình reverse
        # (người deploy nên dùng cách dưới: /m/{host}/{path})
        return Response("Unresolved upstream host. Use /m/{host}/{path}", status_code=502)

    return await _do_proxy(url, request, upstream_host, f"/{path}")


@app.api_route("/m/{host}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
async def mitm(host: str, path: str, request: Request):
    """Endpoint MITM chính (khuyên dùng): /m/{host}/{path}.

    Gọi upstream thật, áp patch theo (host, path), trả response về thiết bị.
    Reverse proxy (nginx/caddy) sẽ dẫn các domain bị pin vào đây:
        location /m/ { proxy_pass http://127.0.0.1:8000/m/; }
    """
    url = f"https://{host}/{path}"
    return await _do_proxy(url, request, host, f"/{path}")


async def _do_proxy(url: str, request: Request, upstream_host: str, upstream_path: str):
    strategy = patcher.should_patch(upstream_host, upstream_path)
    log.info("MITM %s -> %s (patch=%s)", request.method, url, strategy)

    headers = dict(request.headers)
    headers["Host"] = upstream_host
    headers.pop("content-length", None)
    headers.pop("transfer-encoding", None)
    # Firebase cần tham số/header android; giữ nguyên toàn bộ header gốc
    body = await request.body()

    try:
        upstream = await _upstream.request(
            request.method, url, headers=headers, content=body or None
        )
    except httpx.HTTPError as e:
        log.error("upstream error %s: %s", url, e)
        return Response("Upstream error", status_code=502)

    # Nếu có patch -> biến đổi body
    resp_headers = dict(upstream.headers)
    rbody = upstream.content
    if strategy:
        rbody, resp_headers = patcher.apply_patch(
            strategy, rbody, resp_headers, upstream_host, upstream_path
        )
        resp_headers.pop("content-length", None)
        resp_headers.pop("content-encoding", None)
        resp_headers.pop("transfer-encoding", None)

    return Response(
        content=rbody,
        status_code=upstream.status_code,
        headers=resp_headers,
    )


# ============================================================
# Health / debug
# ============================================================
@app.get("/healthz")
async def health():
    return {"ok": True, "host": config.PUBLIC_HOST, "pinned": len(config.PINNED_DOMAINS)}


# ============================================================
# CLI
# ============================================================
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(config.PUBLIC_IP and 8000 or 8000))