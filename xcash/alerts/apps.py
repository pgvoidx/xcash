from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AlertsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "alerts"
    verbose_name = _("告警")
