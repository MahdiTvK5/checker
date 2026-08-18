"""Client helpers for talking to a 3x-ui / X-UI panel.

Encapsulates login + inbound lookup so the view layer stays thin and the
multi-panel logic can reuse a single, well-tested code path.

Design notes (the app runs on a server inside Iran):
- No external/CDN dependency is needed here; only HTTP calls to the panels.
- Login cookies are cached per panel (with a TTL) so we don't re-login on
  every request. The cache stores plain cookie dicts, not ``Session``
  objects, so it is safe to use from multiple threads concurrently.
"""

import base64
import binascii
import hashlib
import json
import logging
import threading
import time
from urllib.parse import urlparse, unquote

import requests
import urllib3

logger = logging.getLogger("checker")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SESSION_TTL = 3600

_session_cache = {}
_cache_lock = threading.Lock()


class PanelError(Exception):
    """Raised when a panel cannot be reached or returns an error."""


class PanelAuthError(PanelError):
    """Raised when the panel response looks like an expired/failed login."""


def _b64decode(data):
    """Forgiving base64 decode (handles missing padding and url-safe)."""
    data = data.strip()
    data += "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(data).decode("utf-8", "ignore")
    except (binascii.Error, ValueError):
        return ""


def _userinfo(link):
    """Return the userinfo part (before @) of a URL-style link."""
    try:
        parsed = urlparse(link)
        if parsed.username:
            return unquote(parsed.username).strip()
    except (ValueError, IndexError):
        pass
    try:
        return link.split("://", 1)[1].split("@", 1)[0].split("?", 1)[0].strip() or None
    except IndexError:
        return None


def parse_vless(link):
    if not link or not link.strip().startswith("vless://"):
        return None
    return _userinfo(link.strip())


def _parse_vmess(link):
    payload = link.strip()[len("vmess://"):]
    decoded = _b64decode(payload)
    if not decoded:
        return None
    try:
        obj = json.loads(decoded)
    except (ValueError, json.JSONDecodeError):
        return None
    return (obj.get("id") or "").strip() or None


def _parse_ss(link):
    """Extract the password from SIP002 or legacy ss:// links."""
    body = link.strip()[len("ss://"):].split("#", 1)[0]
    if "@" in body:
        userinfo = body.split("@", 1)[0]
        decoded = _b64decode(userinfo) or unquote(userinfo)
    else:
        decoded = _b64decode(body) or body
        if "@" in decoded:
            decoded = decoded.split("@", 1)[0]
    decoded = unquote(decoded)
    if ":" in decoded:
        return decoded.split(":", 1)[1].strip() or None
    return decoded.strip() or None


def parse_link(link):
    link = link.strip()
    scheme = link.split("://", 1)[0].lower()
    if scheme == "vless":
        return parse_vless(link)
    if scheme == "vmess":
        return _parse_vmess(link)
    if scheme == "trojan":
        return _userinfo(link)
    if scheme == "ss":
        return _parse_ss(link)
    return None


def normalize_query(raw):
    if not raw:
        return None
    raw = raw.strip()
    if "://" in raw:
        return parse_link(raw)
    return raw or None


def format_bytes(size):
    try:
        return round(int(size) / (1024 ** 3), 2)
    except (TypeError, ValueError):
        return 0


def describe_expiry(expiry_time):
    """Return ``(text, kind)`` for a 3x-ui ``expiryTime`` value.

    ``kind`` is one of: unlimited, pending, expired, ok, warn.
    Negative expiryTime means "duration after first connection".
    """
    if not expiry_time:
        return "نامحدود", "unlimited"
    try:
        expiry_time = int(expiry_time)
    except (TypeError, ValueError):
        return "نامحدود", "unlimited"

    if expiry_time < 0:
        ms = abs(expiry_time)
        days = ms // 86_400_000
        if days:
            return f"از اولین اتصال: {days} روز", "pending"
        hours = max(ms // 3_600_000, 1)
        return f"از اولین اتصال: {hours} ساعت", "pending"

    remain = expiry_time - int(time.time() * 1000)
    if remain <= 0:
        return "منقضی شده", "expired"

    days = remain // 86_400_000
    hours = (remain % 86_400_000) // 3_600_000
    minutes = (remain % 3_600_000) // 60_000
    if days >= 1:
        kind = "ok" if days > 3 else "warn"
        if days < 7 and hours:
            return f"{days} روز و {hours} ساعت", kind
        return f"{days} روز", kind
    if hours >= 1:
        return f"{hours} ساعت", "warn"
    return f"{max(minutes, 1)} دقیقه", "warn"


def _panel_secret(panel):
    return getattr(panel, "plain_password", None) or panel.password


def _cache_key(panel):
    raw = f"{panel.base_url}|{panel.username}|{_panel_secret(panel)}".encode()
    return hashlib.sha256(raw).hexdigest()


def _login_cookies(panel, timeout):
    login_url = f"{panel.base_url}/login"
    try:
        res = requests.post(
            login_url,
            data={"username": panel.username, "password": _panel_secret(panel)},
            timeout=timeout,
            verify=panel.verify_ssl,
        )
    except requests.exceptions.RequestException as exc:
        logger.warning("login failed for %s: %s", panel.base_url, exc)
        raise PanelError("عدم دسترسی به پنل") from exc

    try:
        ok = res.json().get("success")
    except (ValueError, json.JSONDecodeError):
        raise PanelError("پاسخ نامعتبر از پنل (احتمالاً آدرس/مسیر اشتباه است)")

    if not ok:
        raise PanelError("نام کاربری یا رمز عبور پنل نادرست است")

    return requests.utils.dict_from_cookiejar(res.cookies)


def get_cookies(panel, timeout, force=False):
    key = _cache_key(panel)
    now = time.time()

    with _cache_lock:
        stale = [k for k, entry in _session_cache.items() if entry[1] <= now]
        for k in stale:
            del _session_cache[k]
        if not force:
            entry = _session_cache.get(key)
            if entry and entry[1] > now:
                return entry[0]

    cookies = _login_cookies(panel, timeout)
    with _cache_lock:
        _session_cache[key] = (cookies, now + SESSION_TTL)
    return cookies


def clear_session_cache():
    with _cache_lock:
        _session_cache.clear()


def _looks_like_login_page(res):
    ctype = str((getattr(res, "headers", None) or {}).get("Content-Type") or "").lower()
    if res.status_code in (401, 403):
        return True
    if "text/html" in ctype:
        return True
    return False


def _fetch_inbounds(panel, cookies, timeout):
    stats_url = f"{panel.base_url}/panel/api/inbounds/list"
    try:
        res = requests.get(
            stats_url,
            cookies=cookies,
            timeout=timeout,
            verify=panel.verify_ssl,
        )
    except requests.exceptions.RequestException as exc:
        logger.warning("inbound fetch failed for %s: %s", panel.base_url, exc)
        raise PanelError("خطا در دریافت اطلاعات از پنل") from exc

    if _looks_like_login_page(res):
        raise PanelAuthError("نشست منقضی شده است")

    try:
        data = res.json()
    except (ValueError, json.JSONDecodeError):
        raise PanelAuthError("نشست منقضی شده است")

    if not data.get("success"):
        raise PanelError("سرور در دریافت اطلاعات خطا داد")

    obj = data.get("obj")
    if obj is None:
        return []
    if not isinstance(obj, list):
        raise PanelError("پاسخ نامعتبر از پنل")
    return obj


def _client_matches(client, query, query_lower):
    cid = client.get("id") or ""
    email = client.get("email") or ""
    password = client.get("password") or ""
    return cid == query or password == query or email.lower() == query_lower


def _build_result(username, total, used, expiry_time, enabled):
    time_text, time_kind = describe_expiry(expiry_time)
    expired = time_kind == "expired"
    pending = time_kind == "pending"
    depleted = False

    if total and total > 0:
        remaining_bytes = max(total - used, 0)
        percent = min(int(used * 100 / total), 100)
        volume = {
            "total": format_bytes(total),
            "remaining_volume": format_bytes(remaining_bytes),
            "percent": percent,
        }
        depleted = remaining_bytes == 0 or percent >= 100
    else:
        volume = {
            "total": "نامحدود",
            "remaining_volume": "نامحدود",
            "percent": None,
        }

    if not enabled:
        status, status_label = "disabled", "غیرفعال"
    elif expired:
        status, status_label = "expired", "منقضی شده"
    elif depleted:
        status, status_label = "depleted", "حجم تمام شده"
    elif pending:
        status, status_label = "pending", "منتظر اولین اتصال"
    else:
        status, status_label = "active", "فعال"

    volume_kind = "ok"
    if volume["percent"] is not None:
        if volume["percent"] >= 100:
            volume_kind = "bad"
        elif volume["percent"] >= 80:
            volume_kind = "warn"

    result = {
        "username": username,
        "used": format_bytes(used),
        "remaining_time": time_text,
        "time_kind": time_kind,
        "status": status,
        "status_label": status_label,
        "enabled": enabled,
        "volume_kind": volume_kind,
    }
    result.update(volume)
    return result


def find_client(inbounds, query):
    """Search a panel's inbounds for a client matching ``query``.

    Traffic from the same client across multiple inbounds is aggregated.
    """
    if not query or not isinstance(inbounds, list):
        return None
    query_lower = query.lower()

    total = 0
    used = 0
    expiry_time = 0
    enabled = False
    username = ""
    matched = False

    for inbound in inbounds:
        if not isinstance(inbound, dict):
            continue
        inbound_on = inbound.get("enable", True)
        client_stats = inbound.get("clientStats") or []
        if not isinstance(client_stats, list):
            client_stats = []
        try:
            settings = json.loads(inbound.get("settings") or "{}")
        except (ValueError, json.JSONDecodeError, TypeError):
            settings = {}
        if not isinstance(settings, dict):
            settings = {}
        clients = settings.get("clients") or []
        if not isinstance(clients, list):
            continue

        for client in clients:
            if not isinstance(client, dict):
                continue
            if not _client_matches(client, query, query_lower):
                continue
            matched = True
            cid = client.get("id") or ""
            email = client.get("email") or ""
            username = username or email or cid
            expiry_time = client.get("expiryTime") or expiry_time
            client_on = client.get("enable", True)
            if inbound_on and client_on:
                enabled = True

            stat = next(
                (s for s in client_stats if isinstance(s, dict) and (s.get("email") or "") == email),
                {},
            )
            quota = stat.get("total") or 0
            if quota > total:
                total = quota
            used += (stat.get("up") or 0) + (stat.get("down") or 0)

    if not matched:
        return None
    return _build_result(username, total, used, expiry_time, enabled)


def lookup(panel, query, timeout=8):
    cookies = get_cookies(panel, timeout)
    try:
        inbounds = _fetch_inbounds(panel, cookies, timeout)
    except PanelAuthError:
        cookies = get_cookies(panel, timeout, force=True)
        inbounds = _fetch_inbounds(panel, cookies, timeout)
    return find_client(inbounds, query)
