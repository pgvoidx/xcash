from __future__ import annotations

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError


class Command(BaseCommand):
    help = "检查独立 signer 服务健康状态"

    def handle(self, *args, **options):
        if not settings.SIGNER_BASE_URL:
            raise CommandError("SIGNER_BASE_URL 未配置，无法检查 signer 服务")

        healthz_url = f"{settings.SIGNER_BASE_URL.rstrip('/')}/healthz"
        try:
            # 这里走独立健康探测，不带业务鉴权头，确保部署前能快速发现 signer 基础依赖是否就绪。
            response = httpx.get(
                healthz_url,
                timeout=settings.SIGNER_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise CommandError(f"signer 服务检查失败: {healthz_url}") from exc

        is_healthy = payload.get("ok")
        if is_healthy is None:
            is_healthy = payload.get("healthy", False)

        if not is_healthy:
            raise CommandError("signer 服务未就绪，请先检查数据库、缓存和共享密钥配置")

        self.stdout.write(self.style.SUCCESS(f"signer 服务检查通过: {healthz_url}"))
