from django.apps import AppConfig


class CurrenciesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "currencies"
    verbose_name = "货币"

    def ready(self):
        import currencies.signals  # noqa
