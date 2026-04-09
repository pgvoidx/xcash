from django.apps import AppConfig
from django.db.models.signals import post_migrate
from django.utils.translation import gettext_lazy as _


class EvmConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "evm"
    verbose_name = _("EVM")

    def ready(self):
        post_migrate.connect(
            _install_db_triggers_after_migrate,
            dispatch_uid="evm.install_db_triggers",
        )


_installed_aliases: set[str] = set()


def _install_db_triggers_after_migrate(sender, **kwargs) -> None:
    using = kwargs.get("using", "default")
    if using in _installed_aliases:
        return
    from django.db import connections

    existing_tables = set(connections[using].introspection.table_names())
    if "evm_evmbroadcasttask" not in existing_tables:
        return
    from evm.db_triggers import install_triggers

    install_triggers(using=using)
    _installed_aliases.add(using)
