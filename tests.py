import json
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase

from . import views, xui
from .models import Panel


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

    def test_format_bytes(self):
        self.assertEqual(xui.format_bytes(1024 ** 3), 1.0)
        self.assertEqual(xui.format_bytes("bad"), 0)
        self.assertEqual(xui.format_bytes(None), 0)


def _make_inbounds(uuid, email, total=0, up=0, down=0, expiry=0):
    return [{
        "clientStats": [{"email": email, "total": total, "up": up, "down": down}],
        "settings": json.dumps({"clients": [{"id": uuid, "email": email, "expiryTime": expiry}]}),
    }]


class FindClientTests(TestCase):
    def test_find_by_uuid(self):
        inbounds = _make_inbounds("u-1", "ali", total=2 * 1024 ** 3, up=1024 ** 3, down=0)
        res = xui.find_client(inbounds, "u-1")
        self.assertEqual(res["username"], "ali")
        self.assertEqual(res["total"], 2.0)
        self.assertEqual(res["used"], 1.0)

    def test_find_by_email_case_insensitive(self):
        inbounds = _make_inbounds("u-1", "Ali")
        self.assertIsNotNone(xui.find_client(inbounds, "ali"))

    def test_unlimited_total(self):
        inbounds = _make_inbounds("u-1", "ali", total=0)
        self.assertEqual(xui.find_client(inbounds, "u-1")["total"], "نامحدود")

    def test_not_found(self):
        inbounds = _make_inbounds("u-1", "ali")
        self.assertIsNone(xui.find_client(inbounds, "nope"))

    def test_malformed_settings_ignored(self):
        inbounds = [{"clientStats": [], "settings": "not-json"}]
        self.assertIsNone(xui.find_client(inbounds, "u-1"))


class MultiPanelViewTests(TestCase):
    def setUp(self):
        self.p1 = Panel.objects.create(name="P1", url="http://p1", username="a", password="b", order=1)
        self.p2 = Panel.objects.create(name="P2", url="http://p2", username="a", password="b", order=2)

    def _post(self, value="vless://u-2@1.2.3.4:443#x"):
        return self.client.post("/", {"vless_link": value})

    def test_found_on_second_panel(self):
        def fake_lookup(panel, query, timeout=8):
            if panel.name == "P2":
                return {"username": "ali", "total": "نامحدود", "used": 0, "remaining_time": "۱۰ روز"}
            return None

        with mock.patch.object(views, "lookup", side_effect=fake_lookup):
            res = self._post()
        self.assertContains(res, "ali")
        self.assertContains(res, "P2")

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
