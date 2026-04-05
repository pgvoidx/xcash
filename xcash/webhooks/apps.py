from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class WebhooksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "webhooks"
    verbose_name = _("通知")
