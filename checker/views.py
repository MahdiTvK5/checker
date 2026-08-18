import logging
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from types import SimpleNamespace

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from decouple import config

from .models import Panel
from .xui import PanelError, lookup, normalize_query

logger = logging.getLogger("checker")

MAX_WORKERS = 12
MAX_QUERY_LEN = 512

_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="panel")

_rate_lock = threading.Lock()
_rate_hits = defaultdict(deque)


def _env_panel():
    url = config("XUI_URL", default="")
    if not url:
        return None
    return SimpleNamespace(
        name="پنل پیش‌فرض",
        base_url=url.rstrip("/"),
        username=config("XUI_USERNAME", default=""),
        password=config("XUI_PASSWORD", default=""),
        verify_ssl=config("XUI_VERIFY_SSL", default=False, cast=bool),
        order=0,
        id=0,
        plain_password=config("XUI_PASSWORD", default=""),
    )


def _get_panels():
    panels = list(Panel.objects.filter(is_active=True))
    if panels:
        return panels
    env_panel = _env_panel()
    return [env_panel] if env_panel else []


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR") or "unknown"


def _rate_limited(ip):
    limit = getattr(settings, "LOOKUP_RATE_LIMIT", 30)
    window = getattr(settings, "LOOKUP_RATE_WINDOW", 60)
    now = time.time()
    with _rate_lock:
        hits = _rate_hits[ip]
        while hits and hits[0] <= now - window:
            hits.popleft()
        if len(hits) >= limit:
            return True
        hits.append(now)
        return False


def _panel_rank(panel):
    return (getattr(panel, "order", 0) or 0, getattr(panel, "id", 0) or 0)


def _safe_lookup(panel, query):
    try:
        return lookup(panel, query)
    except PanelError:
        raise
    except Exception as exc:
        logger.exception("unexpected panel error: %s", getattr(panel, "name", "?"))
        raise PanelError("خطای غیرمنتظره در ارتباط با پنل") from exc


def _query_panels(panels, query):
    """Query panels in parallel; prefer the match with the lowest ``order``."""
    if len(panels) == 1:
        try:
            result = _safe_lookup(panels[0], query)
        except PanelError as exc:
            logger.warning("panel lookup failed: %s: %s", panels[0].name, exc)
            return None, True
        if result:
            result["panel"] = panels[0].name
            return result, False
        return None, False

    errors = 0
    best = None
    completed = set()
    futures = {_executor.submit(_safe_lookup, p, query): p for p in panels}

    for future in as_completed(futures):
        panel = futures[future]
        completed.add(id(panel))
        try:
            result = future.result()
        except PanelError as exc:
            logger.warning("panel lookup failed: %s: %s", panel.name, exc)
            errors += 1
            result = None
        if result:
            result["panel"] = panel.name
            cand = (_panel_rank(panel), result)
            if best is None or cand[0] < best[0]:
                best = cand

        if best:
            better_pending = any(
                id(p) not in completed and _panel_rank(p) < best[0]
                for p in panels
            )
            if not better_pending:
                return best[1], False

    if best:
        return best[1], False
    return None, errors == len(panels)


def healthz(request):
    return HttpResponse("ok", content_type="text/plain")


def check_config(request):
    if request.method != "POST":
        return render(request, "index.html")

    raw_input = request.POST.get("vless_link", "")[:MAX_QUERY_LEN]
    context = {"vless_link": raw_input}

    if _rate_limited(_client_ip(request)):
        context["error"] = "تعداد درخواست‌ها زیاد است. کمی صبر کنید و دوباره تلاش کنید."
        return render(request, "index.html", context, status=429)

    query = normalize_query(raw_input)
    if not query:
        context["error"] = "ورودی نامعتبر است. لینک کانفیگ، UUID یا ایمیل را وارد کنید."
        return render(request, "index.html", context)

    panels = _get_panels()
    if not panels:
        context["error"] = "در حال حاضر سرویسی برای استعلام تنظیم نشده است."
        return render(request, "index.html", context)

    try:
        result, all_down = _query_panels(panels, query)
    except Exception:
        logger.exception("lookup crashed")
        context["error"] = "خطای غیرمنتظره‌ای رخ داد. کمی بعد دوباره تلاش کنید."
        return render(request, "index.html", context)

    if result:
        context["result"] = result
        return render(request, "index.html", context)

    if all_down:
        context["error"] = "خطا در ارتباط با سرورها. کمی بعد دوباره تلاش کنید."
    else:
        context["error"] = "این کانفیگ یافت نشد. لینک را بررسی کنید یا با پشتیبانی تماس بگیرید."
    return render(request, "index.html", context)
