"""SaaS 模式下，对锁定操作（deposit/withdrawal）做权限校验。

设计参考：xcash-saas spec §5.3
- INTERNAL_API_TOKEN 为空视为未对接 SaaS（自托管），直接放行
- 缓存正常结果 60 秒，stale 副本 300 秒兜底
- SaaS 不可达且无 stale 缓存时 fail-closed
"""

from __future__ import annotations

import httpx
import structlog
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied

logger = structlog.get_logger()

# SaaS 侧 endpoint 路径；SAAS_CALLBACK_URL 只配 scheme+host
_SAAS_PERMISSION_PATH = "/callbacks/xcash/permission"

CACHE_TTL = 60          # 正常缓存 1 分钟
STALE_TTL = 300         # SaaS 不可达时兜底用的过期缓存 5 分钟

_TIMEOUT = httpx.Timeout(connect=2.0, read=3.0, write=3.0, pool=5.0)


def check_saas_permission(*, appid: str, action: str) -> None:
    """对锁定操作做权限校验。

    Args:
        appid: xcash Project appid
        action: 'deposit' / 'withdrawal' 等，对应 SaaS 返回的 enable_<action>

    Raises:
        PermissionDenied: 该 tier 未开放该功能 / 用户已 frozen / SaaS 不可达且无缓存

    Returns:
        None — 不抛异常即放行
    """
    # 自托管模式：未对接 SaaS，所有功能默认开放
    if not settings.INTERNAL_API_TOKEN:
        return

    cache_key = f"saas_permission:{appid}"
    perm = cache.get(cache_key)

    if perm is None:
        try:
            perm = _fetch_from_saas(appid)
            cache.set(cache_key, perm, CACHE_TTL)
            cache.set(f"{cache_key}:stale", perm, STALE_TTL)
        except httpx.HTTPError as exc:
            # SaaS 不可达 → 用 stale 缓存兜底
            perm = cache.get(f"{cache_key}:stale")
            if perm is None:
                logger.warning(
                    "saas_permission_unavailable",
                    appid=appid, action=action, error=str(exc),
                )
                raise PermissionDenied("permission service unavailable")
            logger.info("saas_permission_stale_used", appid=appid)

    if perm.get("frozen"):
        raise PermissionDenied("project is frozen")

    feature_key = f"enable_{action}"
    if not perm.get(feature_key, False):
        raise PermissionDenied(
            f"{action} is not enabled for current tier",
        )


def _fetch_from_saas(appid: str) -> dict:
    url = f"{settings.SAAS_CALLBACK_URL.rstrip('/')}{_SAAS_PERMISSION_PATH}"
    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.post(
            url,
            json={"appid": appid},
            headers={
                "Authorization": f"Bearer {settings.INTERNAL_API_TOKEN}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        return resp.json()
