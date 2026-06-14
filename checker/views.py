import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from types import SimpleNamespace

from django.shortcuts import render
from decouple import config

from .models import Panel
from .xui import PanelError, lookup, normalize_query

logger = logging.getLogger("checker")

# Cap on parallel panel requests so a huge panel list can't exhaust threads.
MAX_WORKERS = 12

# Hard limit on user input length to avoid abuse.
MAX_QUERY_LEN = 512


def _env_panel():
    """Backward-compatible single panel built from environment variables.

    Used only when no :class:`Panel` rows exist, so existing deployments keep
    working without a database migration step.
    """
    url = config("XUI_URL", default="")
    if not url:
        return None
    return SimpleNamespace(
        name="پنل پیش‌فرض",
        base_url=url.rstrip("/"),
        username=config("XUI_USERNAME", default=""),
        password=config("XUI_PASSWORD", default=""),
        verify_ssl=config("XUI_VERIFY_SSL", default=False, cast=bool),
    )


def _get_panels():
    panels = list(Panel.objects.filter(is_active=True))
    if panels:
        return panels
    env_panel = _env_panel()
    return [env_panel] if env_panel else []


def _query_panels(panels, query):
    """Query every panel concurrently and return ``(result, errors)``.

    Returns as soon as the first panel reports a match (remaining requests are
    cancelled). ``errors`` only matters when nothing is found.
    """
    if len(panels) == 1:
        # No need to spin up a thread pool for a single panel.
        try:
            result = lookup(panels[0], query)
        except PanelError as exc:
            logger.warning("panel lookup failed: %s: %s", panels[0].name, exc)
            return None, [f"{panels[0].name}: {exc}"]
        if result:
            result["panel"] = panels[0].name
            return result, []
        return None, []

    errors = []
    executor = ThreadPoolExecutor(max_workers=min(len(panels), MAX_WORKERS))
    try:
        futures = {executor.submit(lookup, p, query): p for p in panels}
        for future in as_completed(futures):
            panel = futures[future]
            try:
                result = future.result()
            except PanelError as exc:
                logger.warning("panel lookup failed: %s: %s", panel.name, exc)
                errors.append(f"{panel.name}: {exc}")
                continue
            if result:
                result["panel"] = panel.name
                return result, errors
        return None, errors
    finally:
        # Don't block on slow/cancelled panels once we're done.
        executor.shutdown(wait=False, cancel_futures=True)


def check_config(request):
    if request.method != "POST":
        return render(request, "index.html")

    raw_input = request.POST.get("vless_link", "")[:MAX_QUERY_LEN]
    query = normalize_query(raw_input)
    if not query:
        return render(request, "index.html", {
            "error": "ورودی نامعتبر است. لینک vless، UUID یا ایمیل کانفیگ را وارد کنید.",
            "vless_link": raw_input,
        })

    panels = _get_panels()
    if not panels:
        return render(request, "index.html", {
            "error": "هیچ پنلی تنظیم نشده است. لطفاً از بخش مدیریت یک پنل اضافه کنید.",
            "vless_link": raw_input,
        })

    result, errors = _query_panels(panels, query)
    if result:
        return render(request, "index.html", {"result": result})

    if errors and len(errors) == len(panels):
        # Every panel failed to respond – surface the connection problems.
        return render(request, "index.html", {
            "error": "خطا در ارتباط با پنل‌ها:",
            "panel_errors": errors,
            "vless_link": raw_input,
        })

    return render(request, "index.html", {
        "error": "این کانفیگ در هیچ‌کدام از پنل‌ها یافت نشد.",
        "panel_errors": errors or None,
        "vless_link": raw_input,
    })
