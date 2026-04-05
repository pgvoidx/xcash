# ruff: noqa: E501, F405
import logging

from .base import *  # noqa
from .base import SENTRY_DSN
from .base import env
from .base import shared_processors

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env("DJANGO_SECRET_KEY")
DOMAIN = env("SITE_DOMAIN", default="").strip().lower()

# 改动原因：SITE_DOMAIN 允许为空且只提供主机名，生产配置需要分别适配 ALLOWED_HOSTS 与 CSRF_TRUSTED_ORIGINS 的格式要求。
ALLOWED_HOSTS = [host for host in ["127.0.0.1", "localhost", DOMAIN] if host]

# STATIC & MEDIA
# ------------------------
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# 基础 URL 设置
USE_X_FORWARDED_HOST = True
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "https"

# SECURITY
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-proxy-ssl-header
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Django 要求 CSRF_TRUSTED_ORIGINS 带 scheme；这里统一按 HTTPS 自托管入口生成。
CSRF_TRUSTED_ORIGINS = [f"https://{DOMAIN}"] if DOMAIN else []

# 生产环境严格限制跨域来源，仅允许自身域名。
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = [f"https://{DOMAIN}"] if DOMAIN else []

# LOGGING
# ------------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processors": [
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.dict_tracebacks,
                structlog.processors.JSONRenderer(),
            ],
            "foreign_pre_chain": shared_processors,
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
    },
    "root": {"level": "INFO", "handlers": ["console"]},
    "loggers": {
        "django.security.DisallowedHost": {"level": "ERROR", "handlers": ["console"]},
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}

# Sentry（可选）：设置 SENTRY_DSN 环境变量后自动启用
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
        traces_sample_rate=0.0,
        auto_session_tracking=False,
        send_default_pii=False,
        environment="production",
    )
