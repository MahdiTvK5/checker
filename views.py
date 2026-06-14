from types import SimpleNamespace

from django.shortcuts import render
from decouple import config

from .models import Panel
from .xui import PanelError, lookup, normalize_query


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


def check_config(request):
    if request.method != "POST":
        return render(request, "index.html")

    raw_input = request.POST.get("vless_link", "")
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

    errors = []
    for panel in panels:
        try:
            result = lookup(panel, query)
        except PanelError as exc:
            errors.append(f"{panel.name}: {exc}")
            continue
        if result:
            result["panel"] = panel.name
            return render(request, "index.html", {"result": result})

    # Not found on any reachable panel.
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
