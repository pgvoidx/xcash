from unittest.mock import patch, Mock

import httpx
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings


@override_settings(
    INTERNAL_API_TOKEN="xcash-saas-token",
    SAAS_CALLBACK_URL="http://saas",
)
class CheckSaasPermissionTest(TestCase):
    def setUp(self):
        cache.clear()

    @patch("xcash.common.permission_check.httpx.Client")
    def test_caches_successful_response(self, mock_client_cls):
        from xcash.common.permission_check import check_saas_permission

        mock_resp = Mock()
        mock_resp.json.return_value = {
            "appid": "XC-a",
            "frozen": False,
            "enable_deposit": True,
            "enable_withdrawal": True,
        }
        mock_resp.raise_for_status.return_value = None
        mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

        check_saas_permission(appid="XC-a", action="deposit")  # 第一次调
        check_saas_permission(appid="XC-a", action="deposit")  # 第二次应命中缓存

        # 只调一次 SaaS
        self.assertEqual(
            mock_client_cls.return_value.__enter__.return_value.post.call_count, 1,
        )

    @patch("xcash.common.permission_check.httpx.Client")
    def test_denies_disabled_feature(self, mock_client_cls):
        from xcash.common.permission_check import check_saas_permission

        mock_resp = Mock()
        mock_resp.json.return_value = {
            "appid": "XC-a",
            "frozen": False,
            "enable_deposit": True,
            "enable_withdrawal": False,
        }
        mock_resp.raise_for_status.return_value = None
        mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

        check_saas_permission(appid="XC-a", action="deposit")  # OK

        with self.assertRaises(PermissionDenied):
            check_saas_permission(appid="XC-a", action="withdrawal")

    @patch("xcash.common.permission_check.httpx.Client")
    def test_denies_frozen_user(self, mock_client_cls):
        from xcash.common.permission_check import check_saas_permission

        mock_resp = Mock()
        mock_resp.json.return_value = {
            "appid": "XC-a",
            "frozen": True,
            "enable_deposit": True,
            "enable_withdrawal": True,
        }
        mock_resp.raise_for_status.return_value = None
        mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

        with self.assertRaises(PermissionDenied) as ctx:
            check_saas_permission(appid="XC-a", action="deposit")
        self.assertIn("frozen", str(ctx.exception).lower())

    @patch("xcash.common.permission_check.httpx.Client")
    def test_uses_stale_cache_on_saas_unavailable(self, mock_client_cls):
        """SaaS 第一次返回成功，第二次超时 → 用 stale 缓存。"""
        from xcash.common.permission_check import check_saas_permission

        ok_resp = Mock()
        ok_resp.json.return_value = {
            "appid": "XC-a",
            "frozen": False,
            "enable_deposit": True,
            "enable_withdrawal": False,
        }
        ok_resp.raise_for_status.return_value = None

        # 第一次成功，缓存写入
        mock_client_cls.return_value.__enter__.return_value.post.return_value = ok_resp
        check_saas_permission(appid="XC-a", action="deposit")

        # 模拟 60 秒后正常缓存过期，但 stale 仍在
        cache.delete("saas_permission:XC-a")

        # 第二次 SaaS 超时
        mock_client_cls.return_value.__enter__.return_value.post.side_effect = httpx.ConnectError("boom")
        # 应该用 stale 缓存判定
        check_saas_permission(appid="XC-a", action="deposit")  # 不抛异常

        with self.assertRaises(PermissionDenied):
            check_saas_permission(appid="XC-a", action="withdrawal")  # stale 也是 enable_withdrawal=False

    @patch("xcash.common.permission_check.httpx.Client")
    def test_fail_closed_on_cold_start_with_saas_unavailable(self, mock_client_cls):
        from xcash.common.permission_check import check_saas_permission

        mock_client_cls.return_value.__enter__.return_value.post.side_effect = httpx.ConnectError("boom")

        with self.assertRaises(PermissionDenied) as ctx:
            check_saas_permission(appid="XC-a", action="deposit")
        self.assertIn("unavailable", str(ctx.exception).lower())

    @override_settings(INTERNAL_API_TOKEN="")
    def test_no_token_means_self_hosted_pass_through(self):
        """INTERNAL_API_TOKEN 为空（自托管模式）：直接放行。"""
        from xcash.common.permission_check import check_saas_permission

        # 不应抛异常，不应调用 SaaS
        check_saas_permission(appid="XC-a", action="withdrawal")
