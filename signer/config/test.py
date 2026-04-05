import os
import warnings

os.environ.setdefault("SIGNER_DEBUG", "1")
os.environ.setdefault("SIGNER_SECRET_KEY", "signer-test-secret-key")
os.environ.setdefault("SIGNER_SHARED_SECRET", "signer-test-shared-secret")

from .settings import *  # noqa: F403

# signer 子项目测试默认走内存/本地文件依赖，保证在 signer/ 目录内直接 uv run pytest 可用。
DEBUG = True
SECRET_KEY = "signer-test-secret-key"
SIGNER_SHARED_SECRET = "signer-test-shared-secret"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "test.sqlite3",  # noqa: F405
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "signer-pytest-cache",
    }
}

# web3 仍会经由 websockets.legacy 触发上游弃用告警；signer 测试先静默这类第三方噪音。
warnings.filterwarnings(
    "ignore",
    message=r"websockets\.legacy is deprecated;.*",
    category=DeprecationWarning,
)
