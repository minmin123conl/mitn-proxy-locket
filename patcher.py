"""Lõi patch payload.

Quan trọng: KHÔNG bơm fixture cứng. Thay vào đó:
  1. Đọc payload GỐC thật từ upstream (Locket/Firebase/RevenueCat qua httpx).
  2. Với remote config (Firebase): giữ nguyên toàn bộ key gốc, rồi MERGE các
     khóa photobooth/filter/friends_v2 mới vào đúng nơi — mô phỏng cách
     uplocket.io.vn tự cập nhật theo từng phiên bản app, không làm vỡ cấu trúc.
  3. Với RevenueCat: giữ app_user_id thật, chèn subscriptions/entitlements
     cho các gói Locket Gold/photobooth/filter.
  4. Với profile (api.locketcamera.com): chèn badge (gold/photobooth/filters).

  => App nhận đúng cấu trúc mới nhất + đủ quyền => render được photobooth/filter.
"""
import copy
import datetime
import json
import random
import re

import httpx

import config

# ============================================================
# Tiện ích
# ============================================================
def _expires() -> str:
    return f"{config.SUB_EXPIRY_YEAR}-12-31T23:59:59Z"


def _purchase() -> str:
    return config.SUB_PURCHASE_DATE


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tx_id() -> str:
    return "200000" + "".join(random.choice("0123456789") for _ in range(10))


# ============================================================
# RevenueCat: subscriptions + entitlements
# ============================================================
_ENTITLEMENT_IDS = [
    "Gold", "pro", "vip", "gold", "plus", "plus_gold", "premium", "mega",
    "unlimited", "unlimited_gold", "locket_gold", "photos_booth", "photo_booth",
    "photobooth", "ai_filters", "ai_filter", "filters", "filters_v2",
    "camera_effects", "camera_effects_v2", "ar_filters", "face_filters",
    "lenses", "boomerang", "burst", "all_features", "full_access",
    "locket_plus", "locket_premium", "camera_roll", "live_photos",
    "widget_customization", "no_ads",
]
_PRODUCT_IDS = [
    "locket_1600_1y", "locket_plus_1y", "locket_premium_1y", "locket_unlimited_1y",
    "locket_photos_booth_1y", "locket_ai_filters_1y", "locket_camera_effects_1y",
    "locket_boost_1y",
]
_ENT_TO_PROD = {
    "Gold": "locket_1600_1y", "gold": "locket_1600_1y", "pro": "locket_1600_1y",
    "vip": "locket_1600_1y", "no_ads": "locket_1600_1y",
    "plus": "locket_plus_1y", "plus_gold": "locket_plus_1y", "camera_roll": "locket_plus_1y",
    "live_photos": "locket_plus_1y", "widget_customization": "locket_plus_1y",
    "premium": "locket_premium_1y", "locket_premium": "locket_premium_1y",
    "unlimited": "locket_unlimited_1y", "unlimited_gold": "locket_unlimited_1y",
    "mega": "locket_unlimited_1y", "all_features": "locket_unlimited_1y",
    "full_access": "locket_unlimited_1y",
    "photos_booth": "locket_photos_booth_1y", "photo_booth": "locket_photos_booth_1y",
    "photobooth": "locket_photos_booth_1y", "boomerang": "locket_photos_booth_1y",
    "burst": "locket_photos_booth_1y",
    "ai_filters": "locket_ai_filters_1y", "ai_filter": "locket_ai_filters_1y",
    "filters": "locket_ai_filters_1y", "filters_v2": "locket_ai_filters_1y",
    "camera_effects": "locket_camera_effects_1y", "camera_effects_v2": "locket_camera_effects_1y",
    "ar_filters": "locket_camera_effects_1y", "face_filters": "locket_camera_effects_1y",
    "lenses": "locket_camera_effects_1y",
    "boost": "locket_boost_1y", "boosted": "locket_boost_1y",
}


def _subcription(product_id: str, tx: str) -> dict:
    return {
        "auto_resume_date": None,
        "display_name": product_id,
        "is_sandbox": False,
        "ownership_type": "PURCHASED",
        "billing_issues_detected_at": None,
        "management_url": "https://apps.apple.com/account/subscriptions",
        "period_type": "normal",
        "price": {"amount": 399000, "currency": "VND"},
        "expires_date": _expires(),
        "grace_period_expires_date": None,
        "refunded_at": None,
        "unsubscribe_detected_at": None,
        "original_purchase_date": _purchase(),
        "purchase_date": _purchase(),
        "store": "app_store",
        "store_transaction_id": tx,
    }


def _entitlement(product_id: str) -> dict:
    return {
        "grace_period_expires_date": None,
        "purchase_date": _purchase(),
        "original_purchase_date": _purchase(),
        "product_identifier": product_id,
        "expires_date": _expires(),
        "ownership_type": "PURCHASED",
        "store": "app_store",
    }


def patch_revenuecat(body: dict) -> dict:
    """Merge subscriptions/entitlements vào response /v1/subscribers thật."""
    obj = copy.deepcopy(body) if isinstance(body, dict) else {}
    tx = _tx_id()

    # Giữ lại app_user_id / ngày gốc
    orig_app_user_id = obj.get("app_user_id") or (
        obj.get("subscriber") or {}).get("original_app_user_id")
    orig_mgmt = (obj.get("subscriber") or {}).get("management_url") or "https://apps.apple.com/account/subscriptions"

    obj["subscriber"] = obj.get("subscriber") or {}
    sub = obj["subscriber"]
    sub.setdefault("first_seen", _purchase())
    sub.setdefault("original_purchase_date", _purchase())
    sub["management_url"] = orig_mgmt
    sub["subscriptions"] = sub.get("subscriptions") or {}
    sub["entitlements"] = sub.get("entitlements") or {}
    sub["non_subscriptions"] = sub.get("non_subscriptions") or {}

    # Subscription chính Gold
    sub["subscriptions"]["locket_1600_1y"] = _subcription("locket_1600_1y", tx)
    for pid in _PRODUCT_IDS:
        if pid not in sub["subscriptions"]:
            sub["subscriptions"][pid] = _subcription(pid, tx)

    # Entitlements
    for ent in _ENTITLEMENT_IDS:
        prod = _ENT_TO_PROD.get(ent, "locket_1600_1y")
        if ent not in sub["entitlements"]:
            sub["entitlements"][ent] = _entitlement(prod)

    # Giữ id gốc
    if orig_app_user_id:
        obj.setdefault("app_user_id", orig_app_user_id)
        obj.setdefault("original_app_user_id", orig_app_user_id)
        sub.setdefault("original_app_user_id", orig_app_user_id)

    obj["request_date"] = _now_iso()
    obj["request_date_ms"] = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)

    # Offerings / products để app tìm gói Gold
    obj["offerings"] = {
        "current": {
            "identifier": "locket_gold",
            "server_description": "Locket Gold",
            "metadata": {},
            "availablePackages": [
                {"identifier": "$rc_monthly", "platform_product_identifier": "locket_1600_1y"},
                {"identifier": "$rc_annual", "platform_product_identifier": "locket_1600_1y"},
                {"identifier": "$rc_six_month", "platform_product_identifier": "locket_1600_1y"},
                {"identifier": "$rc_three_month", "platform_product_identifier": "locket_1600_1y"},
            ],
        },
        "all": [],
    }
    obj["products"] = [
        {
            "identifier": "locket_1600_1y",
            "description": "Locket Gold",
            "title": "Locket Gold",
            "price": 399000,
            "price_string": "399000 VND",
            "currency_code": "VND",
            "period": "P1Y",
            "period_unit": "YEAR",
            "period_number_of_units": 1,
        }
    ]
    return obj


# ============================================================
# Profile (api.locketcamera.com) — badge
# ============================================================
def patch_profile(body: dict) -> dict:
    """Chèn badge gold/photobooth/filters vào profile thật của người dùng."""
    obj = copy.deepcopy(body) if isinstance(body, dict) else {}
    obj["badge_level"] = "gold"
    obj["subscription_level"] = "locket_gold"
    obj["is_gold"] = True
    obj["is_photobooth_enabled"] = True
    obj["is_filters_enabled"] = True
    return obj


# ============================================================
# Firebase Remote Config — merge động photobooth/filter
# ============================================================
# Khóa remote config mà các phiên bản Locket thường đọc để gate photobooth/filter.
# Đây là "lí do cốt lõi" bản Shadowrocket cũ không hiện: key đã đổi. Ở đây ta
# MERGE một tập key phổ rộng (không thay payload gốc) để bám đúng cấu trúc mới.
_REMOTE_KEYS = {
    # ---- Photobooth ----
    "photobooth_enabled": True,
    "photobooth_v2_enabled": True,
    "photo_booth_enabled": True,
    "photos_booth_enabled": True,
    "boomerang_enabled": True,
    "burst_enabled": True,
    "photobooth_max_photos": 10,
    "photobooth_interval_seconds": 0.6,
    "photobooth_delay_seconds": 3.0,
    "photobooth_available_effects": [
        "silver", "gold", "vintage", "mono", "bloom", "studio",
        "candy", "neon", "hdr", "dramatic", "soft", "warm",
    ],
    "photobooth_effects_enabled": True,
    "photobooth_filters_enabled": True,
    "photobooth_countdown_enabled": True,
    "photobooth_sound_enabled": True,
    "photobooth_flash_enabled": True,
    "photobooth_camera_switch_enabled": True,
    "photobooth_gallery_enabled": True,
    "photobooth_share_enabled": True,
    "photobooth_ai_enhance_enabled": True,
    "photobooth_smart_frames_enabled": True,
    "photobooth_multi_shot_enabled": True,
    "photobooth_single_shot_enabled": True,

    # ---- Filters / AI ----
    "filters_enabled": True,
    "ai_filters_enabled": True,
    "ai_filter_enabled": True,
    "camera_effects_enabled": True,
    "ar_filters_enabled": True,
    "face_filters_enabled": True,
    "lenses_enabled": True,
    "style_transfer_enabled": True,
    "filter_categories": [
        {"id": "aesthetic", "name": "Aesthetic", "filters": ["noir", "dusk", "lumen", "glow"]},
        {"id": "beauty", "name": "Beauty", "filters": ["soft", "radiant", "dewy", "matt"]},
        {"id": "vintage", "name": "Vintage", "filters": ["retro", "analog", "kodak", "film"]},
    ],

    # ---- Subscription gate (dự phòng, hợp nhất với RevenueCat) ----
    "gold_enabled": True,
    "locket_gold_enabled": True,
    "premium_enabled": True,
    "plus_enabled": True,
    "unlimited_enabled": True,
    "no_ads_enabled": True,

    # ---- Các trường có thể app gọi ----
    "friends_v2_enabled": True,
    "widget_customization_enabled": True,
    "live_photos_enabled": True,
}


def patch_remote_config(original: dict) -> dict:
    """Merge photoBooth/filter keys vào payload Firebase remote config GỐC.

    Firebase trả vài định dạng khác nhau tuỳ version:
      - { "entries": { "key": { "value": "..." } } }
      - { "key": "value" }
      - { "data": { ... } }  (flat cấu hình)
    Ta xử lý chung bằng cách hoạt động trên dict "flat" ngầm.
    """
    obj = copy.deepcopy(original) if isinstance(original, dict) else {}

    if not config.REMOTE_CONFIG_MERGE:
        # Chế độ thay thế: chỉ giữ cấu trúc ngoài, nội dung là key build của ta.
        obj = {"entries": {}}

    # Tìm chỗ chứa các cặp key-value
    if "entries" in obj and isinstance(obj["entries"], dict):
        container = obj["entries"]
        # Firebase entries: { "key": { "value": "..." } }
        target = dict((k, (v.get("value") if isinstance(v, dict) else v)) for k, v in container.items())
        target.update(_REMOTE_KEYS)
        new_entries = {}
        for k, v in target.items():
            # Giữ nguyên kiểu dữ liệu; value phải là string cho Firebase entries
            new_entries[k] = {"value": v if isinstance(v, str) else json.dumps(v)}
        obj["entries"] = new_entries
        return obj
    if "data" in obj and isinstance(obj["data"], dict):
        obj["data"].update(_REMOTE_KEYS)
        return obj
    if "configs" in obj and isinstance(obj["configs"], dict):
        # { "configs": { key: { weatherCd: .. } } }
        for name, cfg in obj["configs"].items():
            if isinstance(cfg, dict):
                cfg.update(_REMOTE_KEYS)
        return obj
    # Flat
    obj.update(_REMOTE_KEYS)
    return obj


def looks_like_remote_config(ct: str, path: str = "") -> bool:
    """Ước lượng nhanh: có phải endpoint Firebase remote config không."""
    if any(p in path for p in config.REMOTE_CONFIG_PATHS):
        return True
    return ct and "proto" in ct or "json" in ct and "firebase" in path


# ============================================================
# Điều phối chung
# ============================================================
def should_patch(host: str, path: str) -> str | None:
    """Trả về tên strategy patch cần áp dụng cho (host, path), hoặc None."""
    h = (host or "").rstrip(".")
    p = path or ""

    if config.ENABLE_REVENUECAT and "revenuecat.com" in h and any(
        p.startswith(x) for x in config.REVENUECAT_PATHS
    ):
        return "revenuecat"

    if config.ENABLE_REMOTE_CONFIG and (
        "firebaseremoteconfig" in h or "firebaseremoteconfigrealtime" in h
    ):
        return "remote_config"

    if config.ENABLE_PROFILE and (
        ("locketcamera.com" in h or "locket" in h) and any(x in p for x in config.PROFILE_PATHS)
    ):
        return "profile"

    return None


def apply_patch(strategy: str, body: bytes, headers: dict, host: str, path: str):
    """Nhận body upstream thật, áp patch theo strategy. Trả (new_body, new_headers)."""
    ct = (headers.get("content-type") or "").lower()

    if strategy == "revenuecat":
        try:
            obj = json.loads(body.decode("utf-8") or "{}")
        except Exception:
            obj = {}
        patched = patch_revenuecat(obj)
        return json.dumps(patched).encode("utf-8"), headers

    if strategy == "remote_config":
        # FB trả có thể proto (binary) hoặc json. Nếu json -> merge. Nếu proto -> bỏ qua
        # (không đụng vì client shadowrocket cũ không xử lý proto). Đây là nơi phát triển sau.
        text = body.decode("utf-8", "ignore") if body else ""
        if text.lstrip().startswith("{"):
            try:
                obj = json.loads(text)
            except Exception:
                obj = {}
            patched = patch_remote_config(obj)
            new_headers = dict(headers)
            if "content-length" in new_headers:
                del new_headers["content-length"]
            return json.dumps(patched).encode("utf-8"), new_headers
        return body, headers

    if strategy == "profile":
        try:
            obj = json.loads(body.decode("utf-8") or "{}")
        except Exception:
            obj = {}
        patched = patch_profile(obj)
        return json.dumps(patched).encode("utf-8"), headers

    return body, headers