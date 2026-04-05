from django.conf import settings
from django.db import connections

from core.default_data import ensure_default_reference_data

_BOOTSTRAPPED_DATABASE_ALIASES: set[str] = set()


def _reference_tables_ready(*, using: str) -> bool:
    # post_migrate 会为每个 app 触发一次；只有主数据相关表都存在后才执行补齐。
    existing_tables = set(connections[using].introspection.table_names())
    return {
        "chains_chain",
        "currencies_crypto",
        "currencies_fiat",
        "currencies_chaintoken",
    }.issubset(existing_tables)


def bootstrap_reference_data_after_migrate(sender, **kwargs) -> None:
    if not getattr(settings, "AUTO_BOOTSTRAP_REFERENCE_DATA", True):
        return
    using = kwargs.get("using", "default")
    if not _reference_tables_ready(using=using):
        return
    if using in _BOOTSTRAPPED_DATABASE_ALIASES:
        return
    ensure_default_reference_data(using=using)
    _BOOTSTRAPPED_DATABASE_ALIASES.add(using)
