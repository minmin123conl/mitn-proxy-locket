"""Cấu hình trung tâm cho server proxy MITM (kiến trúc giống uplocket.io.vn)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# ===== Cấu hình cơ bản =====
# Domain công khai trỏ về server này (bắt buộc cấu hình đúng).
# Với domain mindev.site (Cloudflare proxy / đám mây cam): để nguyên "mindev.site"
# là đủ — Cloudflare cấp TLS cho trang chủ, DoH và enroll callback.
PUBLIC_HOST = os.environ.get("PUBLIC_HOST", "mindev.site")
# IP public thật của VPS (KHÔNG phải IP Cloudflare). DoH trả IP này cho các domain
# bị pin (api.revenuecat.com, *.locketcamera.com, firebase...) để thiết bị gọi thẳng
# về VPS bằng SNI thật. Nên truyền qua biến môi trường lúc chạy, ví dụ:
#   PUBLIC_IP=<IP_VPS> uvicorn main:app ...
PUBLIC_IP = os.environ.get("PUBLIC_IP", "127.0.0.1")

# Với DoH: khi thiết bị hỏi các domain dưới đây, ta trả về IP của server này
# (thay vì IP thật) để toàn bộ traffic MITM đi qua proxy. Không nằm trong danh sách
# này sẽ được resolve bình thường về IP thật (tránh đụng các dịch vụ khác).
PINNED_DOMAINS = {
    "firebaseremoteconfig.googleapis.com",
    "firebaseremoteconfigrealtime.googleapis.com",
    "firebaseremoteconfigrealtime.googleapis.com:443",
    "firebasestorage.googleapis.com",
    "firebaselogging.googleapis.com",
    "*.firebaseremoteconfig.googleapis.com",
    "*.firebaseremoteconfigrealtime.googleapis.com",
    "api.revenuecat.com",
    "api.locketcamera.com",
    "*.locketcamera.com",
    "locketcamera.com",
    "spclient.wg.spotify.com",
    "apresolve.spotify.com",
    "youtubei.googleapis.com",
    "redirector.googlevideo.com",
    "*.googlevideo.com",
    "*.youtube.com",
    "youtube.com",
    "googleads.g.doubleclick.net",
    "pagead2.googlesyndication.com",
    "static.doubleclick.net",
    "ad.youtube.com",
    "ads.youtube.com",
    "s0.2mdn.net",
}

# ===== CA =====
CA_DIR = BASE_DIR / "ca"
CA_KEY = CA_DIR / "ca.key"
CA_CERT = CA_DIR / "ca.crt"
CA_SUBJECT = {
    "countryName": "US",
    "organizationName": "Locket Gold Network",
    "commonName": "Locket Gold Network Root CA",
}
CA_VALID_DAYS = 3650  # 10 năm

# ===== DNS over HTTPS =====
# Upstream resolver thật để resolve các domain không bị "pin".
UPSTREAM_DNS = ["1.1.1.1", "8.8.8.8"]
# Định danh từng thiết bị (token trong URL /dns-query/{token}). Mỗi token có thể
# được cấp để bật/tắt riêng; nếu rỗng thì cho phép mọi token (chế độ mở).
ALLOWED_TOKENS = set()  # rỗng = cho phép tất cả (dùng khi tự deploy)

# ===== MITM patch =====
# Các tuyến đường (path prefix) mà proxy sẽ chủ động: đọc upstream thật, patch rồi trả về.
REMOTE_CONFIG_PATHS = [
    "/v1/fetchConfig",
    "/v1/fetchConfigs",
    "/v1/config",
    "/getConfig",
]
REVENUECAT_PATHS = ["/v1/subscribers", "/v1/receipts", "/v2/subscribers"]
PROFILE_PATHS = [
    "/v1/users/me/profile",
    "/v1/user/profile",
    "/profile",
    "/v1/users",
]

# Cờ bật/tắt từng phần patch (để dễ thử nghiệm).
ENABLE_REMOTE_CONFIG = True
ENABLE_REVENUECAT = True
ENABLE_PROFILE = True

# Có "merge" (giữ key gốc thật + thêm key mới) hay "thay thế" toàn payload.
# Mặc định merge: an toàn với bản Locket mới, không vỡ cấu trúc.
REMOTE_CONFIG_MERGE = True

# ===== Thời gian =====
SUB_EXPIRY_YEAR = 2099
SUB_PURCHASE_DATE = "2024-05-18T08:30:00Z"