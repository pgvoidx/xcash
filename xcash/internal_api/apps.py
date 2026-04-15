from django.apps import AppConfig


class InternalApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "internal_api"
    verbose_name = "Internal API"
