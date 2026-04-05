from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class BitcoinConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "bitcoin"
    verbose_name = _("Bitcoin")
