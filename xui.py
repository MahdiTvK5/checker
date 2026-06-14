"""Client helpers for talking to a 3x-ui / X-UI panel.

Encapsulates login + inbound lookup so the view layer stays thin and the
multi-panel logic can reuse a single, well-tested code path.
"""

import json
import time
from urllib.parse import urlparse

import requests
import urllib3

# Panels almost always run with self-signed certificates. When a panel opts
# out of verification we silence the noisy per-request warning once.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class PanelError(Exception):
    """Raised when a panel cannot be reached or returns an error."""


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


def login(session, base_url, username, password, verify_ssl, timeout):
    login_url = f"{base_url}/login"
    try:
        res = session.post(
            login_url,
            data={"username": username, "password": password},
            timeout=timeout,
            verify=verify_ssl,
        )
    except requests.exceptions.RequestException as exc:
        raise PanelError(f"عدم دسترسی به پنل: {exc}") from exc

    try:
        ok = res.json().get("success")
    except (ValueError, json.JSONDecodeError):
        raise PanelError("پاسخ نامعتبر از پنل (احتمالاً آدرس/مسیر اشتباه است)")

    if not ok:
        raise PanelError("نام کاربری یا رمز عبور پنل نادرست است")


def fetch_inbounds(session, base_url, verify_ssl, timeout):
    stats_url = f"{base_url}/panel/api/inbounds/list"
    try:
        res = session.get(stats_url, timeout=timeout, verify=verify_ssl)
        data = res.json()
    except requests.exceptions.RequestException as exc:
        raise PanelError(f"خطا در دریافت اطلاعات: {exc}") from exc
    except (ValueError, json.JSONDecodeError):
        raise PanelError("پاسخ نامعتبر هنگام دریافت لیست inbound ها")

    if not data.get("success"):
        raise PanelError("سرور در دریافت اطلاعات خطا داد")
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
    simple namespace both work). Raises :class:`PanelError` on failure.
    """
    session = requests.Session()
    login(session, panel.base_url, panel.username, panel.password, panel.verify_ssl, timeout)
    inbounds = fetch_inbounds(session, panel.base_url, panel.verify_ssl, timeout)
    return find_client(inbounds, query)
