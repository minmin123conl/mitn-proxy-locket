# Locket Gold Network — Server Proxy MITM

Server chạy nhiều vai trò:
1. **Web enroll** — trang cài đặt, sinh `.mobileconfig` (Root CA + DNS DoH, và Profile Service enroll).
2. **CA** — tự tạo Root CA, phục vụ cert để cài trên iOS.
3. **DoH (DNS over HTTPS)** — pin tên miền Locket/RevenueCat/Firebase về IP server; domain khác resolve bình thường.
4. **MITM proxy** — nhận traffic domain bị pin, gọi upstream THẬT, **patch động**:
   - **Firebase Remote Config**: merge photobooth/filter/friends_v2 keys vào payload gốc.
   - **RevenueCat**: chèn subscriptions + entitlements (Gold/pro/photobooth/filters...) giữ `app_user_id` thật.
   - **Profile (api.locketcamera.com)**: chèn badge `gold`, bật photobooth/filters.
5. **Enroll callback** — nhận UDID/IMEI thiết bị để quản lý bản quyền.

## Cấu trúc thư mục

```
mitm-proxy/
├── requirements.txt        # Python deps
├── config.py               # CẤU HÌNH CHÍNH (PUBLIC_HOST, PUBLIC_IP, PINNED_DOMAINS)
├── ca_manager.py           # Tạo/load Root CA
├── mobileconfig_gen.py     # Sinh .mobileconfig
├── doh_server.py           # DNS over HTTPS
├── patcher.py              # Lõi patch remote config/revenuecat/profile
├── main.py                 # FastAPI app (chạy bằng uvicorn)
└── ca/                     # (tự tạo) chứa ca.key + ca.crt
```

## Cài đặt trên VPS

### 1. Cài Python + deps
```bash
cd mitm-proxy
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Cấu hình
Sửa `config.py`:
```python
PUBLIC_HOST = "proxy.example.com"   # domain trỏ về server (bắt buộc)
PUBLIC_IP   = "1.2.3.4"             # IP public (DoH trả IP này cho domain bị pin)
```
Nên đặt `ALLOWED_TOKENS` khi public server cho nhiều người.

### 3. Chạy app
```bash
PUBLIC_HOST=proxy.example.com PUBLIC_IP=1.2.3.4 uvicorn main:app --host 0.0.0.0 --port 8000
```

### 4. Reverse proxy (bắt buộc: TLS + dẫn MITM)
Cần TLS cho PUBLIC_HOST (DoH trong mobileconfig bắt buộc https).

#### Caddy (đơn giản nhất)
```caddyfile
proxy.example.com {
    reverse_proxy 127.0.0.1:8000
}
```
Các domain bị pin (api.revenuecat.com, firebaseremoteconfig...) phải trỏ A record → PUBLIC_IP. DoH trong mobileconfig sẽ làm việc này tự động.

#### nginx
```nginx
server {
    listen 80;
    listen [::]:80;
    server_name proxy.example.com;
    location / { proxy_pass http://127.0.0.1:8000; }
}
```

### 5. Truy cập trang chủ
Mở `https://proxy.example.com/`:
- **Bước 1**: Cài profile Đăng ký thiết bị (gửi UDID/IMEI, dùng 1 lần).
- **Bước 2**: Cài profile DNS + CA (cấu hình DoH + Root CA; profile chính dùng hằng ngày).

## Luồng hoạt động (iOS)
1. iPhone cài profile DNS → mọi DNS query đi qua `doh_server.py` (DoH).
2. DoH trả IP của server cho các domain bị pin (`api.revenuecat.com`, `firebaseremoteconfig`...), resolve thật cho phần còn lại.
3. Traffic tới domain bị pin → MITM proxy nhận, mở kết nối TLS tới upstream.
4. `patcher.py` kiểm tra host/path và **sửa response** trước khi trả về app:
   - Remote Config: merge `photobooth`, `filters`, `friends_v2` + email verify + facebook prefix.
   - RevenueCat `/subscribers/*`: chèn packages + entitlements (Gold/pro, photobooth, filters...).
   - Locket `/v1/me` và `/v1/profile/*`: chèn `badge: "gold"`, `is_pro`, bật photobooth/filters.
5. App nhận data "đã patch" và mở khóa các tính năng Premium.

## Kiểm thử
```bash
# 1. Sinh/load CA (thư mục ca/)
python -c "from ca_manager import CA; print(CA().cert_pem()[:80])"

# 2. Sinh mobileconfig thử
PUBLIC_HOST=proxy.example.com PUBLIC_IP=1.2.3.4 \
python -c "from mobileconfig_gen import gen_dns_profile, gen_enroll_profile; \
print(gen_dns_profile('proxy.example.com','1.2.3.4')[:50]); \
print(gen_enroll_profile('proxy.example.com')[:50])"

# 3. Chạy unit test modules
python -m pytest -q   # nếu có
```

## Triển khai miễn phí (không VPS, không VPN)

Bạn có thể chạy server này trên máy local (có kết nối internet) và dùng dịch vụ tunnel để công khai với TLS.

### Dùng Cloudflare Tunnel (Cloudflared) — **có TLS, miễn phí**
1. Đăng ký Cloudflare, mua domain giá rẻ (hoặc dùng subdomain free của Cloudflare).
2. Cài đặt `cloudflared` trên VPS/local:
   ```bash
   # Ubuntu/Debian
   sudo apt install wget && wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O cloudflared && chmod +x cloudflared
   ```
3. Chạy tunnel:
   ```bash
   ./cloudflared tunnel --url http://localhost:8000
   ```
   Cloudflare cấp URL như `https://proxy-your-name.trycloudflare.com`.
4. Sửa `config.py`:
   ```python
   PUBLIC_HOST = "proxy-your-name.trycloudflare.com"  # URL tunnel
   PUBLIC_IP = "YOUR_LOCAL_PUBLIC_IP"  # hoặc để mặc định "127.0.0.1" (Cloudflare sẽ chuyển)
   ```
   (Nếu muốn các domain bị pin trỏ thẳng về máy bạn, đặt `PUBLIC_IP` là IP public của bạn. Nếu chỉ dùng Cloudflare Tunnel, đặt `127.0.0.1` là đủ — Cloudflare tự chuyển tiếp.)

### Dùng Ngrok (Ops: phí, hạn chế free)
```bash
ngrok http 8000
```
Lấy URL `https://xxx.ngrok.io`, sửa `PUBLIC_HOST = "xxx.ngrok.io"`.

### Dùng serveo / localtunnel
```bash
ssh -R 80:localhost:8000 serveo.net
```
Sau đó lấy URL `https://xxx.serveo.net`.

### DNS & Domain riêng
DoH trong profile mobileconfig cần HTTPS. Nhờ Cloudflare HTTPS & Tunnel miễn phí, bạn có thể dùng domain riêng tạo tunnel và dẫn tới local. iOS sẽ gửi DNS query tới URL đó (có TLS), từ đó traffic Locket bị pin về tunnel IP → đến local bạn.

## Lưu ý khi không có VPS
- Chạy app phải ở local 24/7 nếu không tunnel mất.
- Nên thiết lập `ALLOWED_TOKENS` để giới hạn người dùng.
- iPhone cài profile DNS có lúc mất kết nối nếu local IP thay đổi (VPN, WiFi khác). Do đó hãy thử các dịch vụ như **twilio ngrok** (free tier) hoặc **cloudflared** độ ổn định cao hơn.
- Tại **Settings → General → VPN & Device Management** nhớ bật “Trust” cho Root CA.

## Bảo mật & lưu ý
- CA/key tự tạo mỗi khi xóa `ca/` → **bắt buộc** cài lại profile CA trên mọi thiết bị.
- Không chia sẻ `ca/ca.key` ra ngoài; ai có nó có thể MITM toàn bộ traffic của người cài CA.
- API endpoint MITM nên bảo vệ bằng token (`ALLOWED_TOKENS`) nếu public server.
- Đây là công cụ phục vụ mục đích học tập/nghiên cứu. Tuân thủ ToS & pháp luật khi sử dụng.
