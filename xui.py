"""Client helpers for talking to a 3x-ui / X-UI panel.

Encapsulates login + inbound lookup so the view layer stays thin and the
multi-panel logic can reuse a single, well-tested code path.

Design notes (the app runs on a server inside Iran):
- No external/CDN dependency is needed here; only HTTP calls to the panels.
- Login cookies are cached per panel (with a TTL) so we don't re-login on
  every request. The cache stores plain cookie dicts, not ``Session``
  objects, so it is safe to use from multiple threads concurrently.
"""

import hashlib
import json
import threading
import time
from urllib.parse import urlparse

import requests
import urllib3

# Panels almost always run with self-signed certificates. When a panel opts
# out of verification we silence the noisy per-request warning once.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# How long a cached login cookie is trusted before we re-login (seconds).
SESSION_TTL = 3600

_session_cache = {}
_cache_lock = threading.Lock()


class PanelError(Exception):
    """Raised when a panel cannot be reached or returns an error."""


class PanelAuthError(PanelError):
    """Raised when the panel response looks like an expired/failed login.

    Used to trigger a single re-login + retry before giving up.
    """


def parse_vless(link):
    """Extract the client UUID from a vless:// link.

    Returns ``None`` if the input is not a recognisable vless link.
    """
    if not link:
        return None
    link = link.strip()
    if not link.startswith("vless://"):
        return None
    try:
        parsed = urlparse(link)
        uuid = parsed.username
        if uuid:
            return uuid.strip()
        # Fallback for links that urlparse can't fully decompose.
        return link.split("://", 1)[1].split("@", 1)[0].split("?", 1)[0].strip() or None
    except (ValueError, IndexError):
        return None


def normalize_query(raw):
    """Turn user input into a search term.

    Accepts a full vless link, a bare UUID, or an email/username and returns
    the value to match against ``client.id`` or ``client.email``.
    """
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("vless://"):
        return parse_vless(raw)
    return raw or None


def format_bytes(size):
    """Bytes -> gigabytes rounded to 2 decimals."""
    try:
        return round(int(size) / (1024 ** 3), 2)
    except (TypeError, ValueError):
        return 0


def _days_remaining(expiry_time):
    if not expiry_time:
        return "نامحدود"
    current_time_ms = int(time.time() * 1000)
    if expiry_time < current_time_ms:
        return "منقضی شده"
    days = int((expiry_time - current_time_ms) / (1000 * 60 * 60 * 24))
    return f"{days} روز"


# --------------------------------------------------------------------------
# Login session (cookie) cache
# --------------------------------------------------------------------------

def _cache_key(panel):
    """Stable key per (url, username, password).

    Password is hashed so a credential change invalidates the cache without
    keeping the secret around as a dict key.
    """
    raw = f"{panel.base_url}|{panel.username}|{panel.password}".encode()
    return hashlib.sha256(raw).hexdigest()


def _login_cookies(panel, timeout):
    """Perform a login and return the resulting cookie dict."""
    login_url = f"{panel.base_url}/login"
    try:
        res = requests.post(
            login_url,
            data={"username": panel.username, "password": panel.password},
            timeout=timeout,
            verify=panel.verify_ssl,
        )
    except requests.exceptions.RequestException as exc:
        raise PanelError(f"عدم دسترسی به پنل: {exc}") from exc

    try:
        ok = res.json().get("success")
    except (ValueError, json.JSONDecodeError):
        raise PanelError("پاسخ نامعتبر از پنل (احتمالاً آدرس/مسیر اشتباه است)")

    if not ok:
        raise PanelError("نام کاربری یا رمز عبور پنل نادرست است")

    return requests.utils.dict_from_cookiejar(res.cookies)


def get_cookies(panel, timeout, force=False):
    """Return valid login cookies for ``panel``, using the cache when possible."""
    key = _cache_key(panel)
    now = time.time()

    if not force:
        with _cache_lock:
            entry = _session_cache.get(key)
            if entry and entry[1] > now:
                return entry[0]

    cookies = _login_cookies(panel, timeout)
    with _cache_lock:
        _session_cache[key] = (cookies, now + SESSION_TTL)
    return cookies


def clear_session_cache():
    """Drop all cached login cookies (useful for tests / forced refresh)."""
    with _cache_lock:
        _session_cache.clear()


def _fetch_inbounds(panel, cookies, timeout):
    """Fetch the inbound list using cached cookies.

    Raises :class:`PanelAuthError` when the response looks like a login
    redirect / expired session so the caller can re-login and retry.
    """
    stats_url = f"{panel.base_url}/panel/api/inbounds/list"
    try:
        res = requests.get(
            stats_url,
            cookies=cookies,
            timeout=timeout,
            verify=panel.verify_ssl,
        )
    except requests.exceptions.RequestException as exc:
        raise PanelError(f"خطا در دریافت اطلاعات: {exc}") from exc

    try:
        data = res.json()
    except (ValueError, json.JSONDecodeError):
        # Most likely the panel returned the HTML login page -> session expired.
        raise PanelAuthError("نشست منقضی شده است")

    if not data.get("success"):
        raise PanelAuthError("سرور در دریافت اطلاعات خطا داد")
    return data.get("obj", [])


def find_client(inbounds, query):
    """Search a panel's inbounds for a client matching ``query``.

    ``query`` is matched (case-insensitively for email) against the client
    UUID or email. Returns a result dict or ``None``.
    """
    if not query:
        return None
    query_lower = query.lower()

    for inbound in inbounds:
        client_stats = inbound.get("clientStats", []) or []
        try:
            settings = json.loads(inbound.get("settings", "{}") or "{}")
        except (ValueError, json.JSONDecodeError):
            settings = {}
        clients = settings.get("clients", []) or []

        for client in clients:
            cid = (client.get("id") or "")
            email = client.get("email") or ""
            if cid == query or email.lower() == query_lower:
                expiry_time = client.get("expiryTime", 0)
                stat = next(
                    (s for s in client_stats if (s.get("email") or "") == email),
                    {},
                )
                total = stat.get("total", 0)
                used = stat.get("up", 0) + stat.get("down", 0)
                return {
                    "username": email or cid,
                    "total": format_bytes(total) if total and total > 0 else "نامحدود",
                    "used": format_bytes(used),
                    "remaining_time": _days_remaining(expiry_time),
                }
    return None


def lookup(panel, query, timeout=8):
    """Look up ``query`` on a single panel-like object.

    ``panel`` must expose ``base_url``, ``username``, ``password`` and
    ``verify_ssl`` attributes (the :class:`~checker.models.Panel` model or a
    simple namespace both work). Uses cached login cookies and re-logs in once
    if the session turns out to be expired. Raises :class:`PanelError` on
    failure.
    """
    cookies = get_cookies(panel, timeout)
    try:
        inbounds = _fetch_inbounds(panel, cookies, timeout)
    except PanelAuthError:
        # Cached cookies were stale -> force a fresh login and retry once.
        cookies = get_cookies(panel, timeout, force=True)
        inbounds = _fetch_inbounds(panel, cookies, timeout)
    return find_client(inbounds, query)
