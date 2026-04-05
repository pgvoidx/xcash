from django.apps import AppConfig
from django.db.models.signals import post_migrate


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        from core.signals import bootstrap_reference_data_after_migrate

        post_migrate.connect(
            bootstrap_reference_data_after_migrate,
            dispatch_uid="core.default_data_after_migrate",
        )
