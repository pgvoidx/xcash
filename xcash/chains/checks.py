from __future__ import annotations

from django.conf import settings
from django.core.checks import Error
from django.core.checks import Warning as CheckWarning
from django.core.checks import register


@register()
def signer_settings_check(app_configs=None, **_kwargs):
    errors: list[Error | CheckWarning] = []
    signer_backend = settings.SIGNER_BACKEND.strip().lower()

    if signer_backend != "remote":
        errors.append(
            Error(
                "当前版本仅支持 remote signer，主应用不再提供本地持钥模式。",
                id="chains.E001",
            )
        )
        return errors

    if not settings.SIGNER_BASE_URL:
        errors.append(
            Error(
                "SIGNER_BACKEND=remote 时必须配置 SIGNER_BASE_URL。",
                id="chains.E002",
            )
        )

    if not settings.SIGNER_SHARED_SECRET:
        errors.append(
            Error(
                "SIGNER_BACKEND=remote 时必须配置 SIGNER_SHARED_SECRET。",
                id="chains.E003",
            )
        )

    if settings.SIGNER_TIMEOUT <= 0:
        errors.append(
            Error(
                "SIGNER_TIMEOUT 必须大于 0。",
                id="chains.E004",
            )
        )

    if settings.SIGNER_BASE_URL and not settings.SIGNER_BASE_URL.startswith(
        ("http://", "https://")
    ):
        errors.append(
            CheckWarning(
                "SIGNER_BASE_URL 建议使用完整的 http(s) 地址。",
                id="chains.W001",
            )
        )

    return errors
