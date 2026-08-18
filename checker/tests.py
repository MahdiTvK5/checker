import base64
import json
import time
from types import SimpleNamespace
from unittest import mock

import requests
from django.test import TestCase, override_settings

from . import views, xui
from .models import Panel, decrypt_password


class ParseTests(TestCase):
    def test_parse_vless_basic(self):
        link = "vless://11111111-2222-3333-4444-555555555555@1.2.3.4:443?type=tcp#name"
        self.assertEqual(xui.parse_vless(link), "11111111-2222-3333-4444-555555555555")

    def test_parse_vless_invalid(self):
        self.assertIsNone(xui.parse_vless("https://example.com"))
        self.assertIsNone(xui.parse_vless(""))
        self.assertIsNone(xui.parse_vless(None))

    def test_normalize_query(self):
        self.assertEqual(
            xui.normalize_query("vless://abc-uuid@1.2.3.4:443#x"), "abc-uuid"
        )
        self.assertEqual(xui.normalize_query("  user@mail  "), "user@mail")
        self.assertIsNone(xui.normalize_query("   "))

    def test_parse_trojan(self):
        self.assertEqual(
            xui.normalize_query("trojan://secretpass@1.2.3.4:443#n"), "secretpass"
        )

    def test_parse_vmess(self):
        payload = base64.b64encode(
            json.dumps({"id": "vmess-uuid", "ps": "name"}).encode()
        ).decode()
        self.assertEqual(xui.normalize_query("vmess://" + payload), "vmess-uuid")

    def test_parse_ss(self):
        head = base64.b64encode(b"aes-256-gcm:sspass").decode()
        self.assertEqual(xui.normalize_query(f"ss://{head}@1.2.3.4:443#n"), "sspass")

    def test_parse_ss_legacy(self):
        payload = base64.b64encode(b"aes-256-gcm:realpass@1.2.3.4:443").decode()
        self.assertEqual(xui.normalize_query("ss://" + payload), "realpass")

    def test_unknown_scheme(self):
        self.assertIsNone(xui.normalize_query("ftp://something"))

    def test_format_bytes(self):
        self.assertEqual(xui.format_bytes(1024 ** 3), 1.0)
        self.assertEqual(xui.format_bytes("bad"), 0)
        self.assertEqual(xui.format_bytes(None), 0)


class ExpiryTests(TestCase):
    def test_unlimited(self):
        text, kind = xui.describe_expiry(0)
        self.assertEqual(text, "نامحدود")
        self.assertEqual(kind, "unlimited")

    def test_negative_is_pending(self):
        text, kind = xui.describe_expiry(-30 * 86400 * 1000)
        self.assertEqual(kind, "pending")
        self.assertIn("اولین اتصال", text)
        self.assertNotEqual(text, "منقضی شده")

    def test_less_than_a_day(self):
        ms = int(time.time() * 1000) + 5 * 3600 * 1000
        text, kind = xui.describe_expiry(ms)
        self.assertEqual(kind, "warn")
        self.assertIn("ساعت", text)
        self.assertNotIn("0 روز", text)

    def test_expired(self):
        text, kind = xui.describe_expiry(1000)
        self.assertEqual(kind, "expired")


def _make_inbounds(uuid, email, total=0, up=0, down=0, expiry=0, enable=True):
    return [{
        "enable": True,
        "clientStats": [{"email": email, "total": total, "up": up, "down": down}],
        "settings": json.dumps({
            "clients": [{"id": uuid, "email": email, "expiryTime": expiry, "enable": enable}],
        }),
    }]


class FindClientTests(TestCase):
    def test_find_by_uuid(self):
        inbounds = _make_inbounds("u-1", "ali", total=2 * 1024 ** 3, up=1024 ** 3, down=0)
        res = xui.find_client(inbounds, "u-1")
        self.assertEqual(res["username"], "ali")
        self.assertEqual(res["total"], 2.0)
        self.assertEqual(res["used"], 1.0)
        self.assertEqual(res["remaining_volume"], 1.0)
        self.assertEqual(res["percent"], 50)
        self.assertEqual(res["status"], "active")

    def test_find_by_password(self):
        inbounds = [{
            "clientStats": [{"email": "ali", "total": 0, "up": 0, "down": 0}],
            "settings": json.dumps({"clients": [{"password": "pw-1", "email": "ali"}]}),
        }]
        res = xui.find_client(inbounds, "pw-1")
        self.assertIsNotNone(res)
        self.assertEqual(res["username"], "ali")

    def test_find_by_email_case_insensitive(self):
        inbounds = _make_inbounds("u-1", "Ali")
        self.assertIsNotNone(xui.find_client(inbounds, "ali"))

    def test_unlimited_total(self):
        inbounds = _make_inbounds("u-1", "ali", total=0)
        res = xui.find_client(inbounds, "u-1")
        self.assertEqual(res["total"], "نامحدود")
        self.assertEqual(res["remaining_volume"], "نامحدود")
        self.assertIsNone(res["percent"])

    def test_not_found(self):
        inbounds = _make_inbounds("u-1", "ali")
        self.assertIsNone(xui.find_client(inbounds, "nope"))

    def test_malformed_settings_ignored(self):
        inbounds = [{"clientStats": [], "settings": "not-json"}]
        self.assertIsNone(xui.find_client(inbounds, "u-1"))

    def test_obj_none_does_not_crash(self):
        self.assertIsNone(xui.find_client(None, "u-1"))

    def test_aggregates_multiple_inbounds(self):
        gb = 1024 ** 3
        inbounds = (
            _make_inbounds("u-1", "ali", total=10 * gb, up=1 * gb, down=0)
            + _make_inbounds("u-1", "ali", total=10 * gb, up=4 * gb, down=0)
        )
        res = xui.find_client(inbounds, "u-1")
        self.assertEqual(res["used"], 5.0)
        self.assertEqual(res["total"], 10.0)
        self.assertEqual(res["remaining_volume"], 5.0)

    def test_disabled_client(self):
        inbounds = _make_inbounds("u-1", "ali", enable=False)
        res = xui.find_client(inbounds, "u-1")
        self.assertEqual(res["status"], "disabled")
        self.assertEqual(res["status_label"], "غیرفعال")


class MultiPanelViewTests(TestCase):
    def setUp(self):
        self.p1 = Panel.objects.create(name="P1", url="http://p1", username="a", password="b", order=1)
        self.p2 = Panel.objects.create(name="P2", url="http://p2", username="a", password="b", order=2)

    def _post(self, value="vless://u-2@1.2.3.4:443#x"):
        return self.client.post("/", {"vless_link": value})

    def test_found_on_second_panel(self):
        def fake_lookup(panel, query, timeout=8):
            if panel.name == "P2":
                return {
                    "username": "ali",
                    "total": "نامحدود",
                    "used": 0,
                    "remaining_time": "۱۰ روز",
                    "remaining_volume": "نامحدود",
                    "percent": None,
                    "status": "active",
                    "status_label": "فعال",
                    "time_kind": "ok",
                    "volume_kind": "ok",
                }
            return None

        with mock.patch.object(views, "lookup", side_effect=fake_lookup):
            res = self._post()
        self.assertContains(res, "ali")
        self.assertContains(res, "P2")
        self.assertContains(res, "فعال")
        self.assertContains(res, 'value="vless://u-2@1.2.3.4:443#x"')

    def test_prefers_lower_order_panel(self):
        def fake_lookup(panel, query, timeout=8):
            return {
                "username": panel.name,
                "total": "نامحدود",
                "used": 0,
                "remaining_time": "نامحدود",
                "remaining_volume": "نامحدود",
                "percent": None,
                "status": "active",
                "status_label": "فعال",
                "time_kind": "unlimited",
                "volume_kind": "ok",
            }

        with mock.patch.object(views, "lookup", side_effect=fake_lookup):
            res = self._post()
        self.assertContains(res, "P1")
        self.assertNotContains(res, "P2")

    def test_not_found_anywhere(self):
        with mock.patch.object(views, "lookup", return_value=None):
            res = self._post()
        self.assertContains(res, "یافت نشد")

    def test_all_panels_error(self):
        with mock.patch.object(views, "lookup", side_effect=views.PanelError("down")):
            res = self._post()
        self.assertContains(res, "خطا در ارتباط")

    def test_empty_input_rejected(self):
        res = self.client.post("/", {"vless_link": "   "})
        self.assertContains(res, "ورودی نامعتبر")

    def test_unexpected_exception_is_not_500(self):
        with mock.patch.object(views, "lookup", side_effect=TypeError("boom")):
            res = self._post()
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "خطا")

    @override_settings(LOOKUP_RATE_LIMIT=2, LOOKUP_RATE_WINDOW=60)
    def test_rate_limit(self):
        views._rate_hits.clear()
        with mock.patch.object(views, "lookup", return_value=None):
            self.assertEqual(self._post().status_code, 200)
            self.assertEqual(self._post().status_code, 200)
            third = self._post()
        self.assertEqual(third.status_code, 429)

    def test_healthz(self):
        self.assertContains(self.client.get("/healthz"), "ok")

    def test_password_is_encrypted_at_rest(self):
        self.assertTrue(self.p1.password.startswith("enc:"))
        self.assertEqual(decrypt_password(self.p1.password), "b")
        self.assertEqual(self.p1.plain_password, "b")


def _panel_ns():
    return SimpleNamespace(
        name="P", base_url="http://p", username="u", password="pw", verify_ssl=False
    )


def _login_resp():
    resp = mock.Mock()
    resp.json.return_value = {"success": True}
    resp.cookies = requests.cookies.cookiejar_from_dict({"session": "abc"})
    return resp


def _list_resp(uuid="u-1", email="ali"):
    resp = mock.Mock()
    resp.json.return_value = {"success": True, "obj": _make_inbounds(uuid, email)}
    resp.headers = {"Content-Type": "application/json"}
    resp.status_code = 200
    return resp


class SessionCacheTests(TestCase):
    def setUp(self):
        xui.clear_session_cache()
        self.addCleanup(xui.clear_session_cache)

    def test_login_cookies_are_cached(self):
        panel = _panel_ns()
        with mock.patch.object(xui.requests, "post", return_value=_login_resp()) as post, \
                mock.patch.object(xui.requests, "get", return_value=_list_resp()):
            self.assertIsNotNone(xui.lookup(panel, "u-1"))
            self.assertIsNotNone(xui.lookup(panel, "u-1"))
        self.assertEqual(post.call_count, 1)

    def test_relogin_on_expired_session(self):
        panel = _panel_ns()
        expired = mock.Mock()
        expired.json.side_effect = ValueError("html login page")
        expired.headers = {"Content-Type": "text/html"}
        expired.status_code = 200
        with mock.patch.object(xui.requests, "post", return_value=_login_resp()) as post, \
                mock.patch.object(xui.requests, "get", side_effect=[expired, _list_resp()]):
            result = xui.lookup(panel, "u-1")
        self.assertEqual(result["username"], "ali")
        self.assertEqual(post.call_count, 2)

    def test_success_false_does_not_relogin(self):
        panel = _panel_ns()
        fail = mock.Mock()
        fail.json.return_value = {"success": False}
        fail.headers = {"Content-Type": "application/json"}
        fail.status_code = 200
        with mock.patch.object(xui.requests, "post", return_value=_login_resp()) as post, \
                mock.patch.object(xui.requests, "get", return_value=fail) as get:
            with self.assertRaises(xui.PanelError):
                xui.lookup(panel, "u-1")
        self.assertEqual(post.call_count, 1)
        self.assertEqual(get.call_count, 1)
