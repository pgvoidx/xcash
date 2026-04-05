from django.conf import settings
from rest_framework.routers import DefaultRouter
from rest_framework.routers import SimpleRouter

from deposits.viewsets import DepositViewSet
from invoices.viewsets import InvoiceViewSet
from withdrawals.viewsets import WithdrawalViewSet

router = (
    DefaultRouter(trailing_slash=False)
    if settings.DEBUG
    else SimpleRouter(trailing_slash=False)
)

router.register("invoice", InvoiceViewSet)
router.register("deposit", DepositViewSet, basename="deposit")
router.register("withdrawal", WithdrawalViewSet)

app_name = "api_v1"
urlpatterns = [
    *router.urls,
]
