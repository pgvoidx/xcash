from django.urls import path
from wallets.views import CreateWalletView
from wallets.views import DeriveAddressView
from wallets.views import InternalAdminSummaryView
from wallets.views import SignBitcoinView
from wallets.views import SignEvmView
from wallets.views import healthz

urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path(
        "internal/admin-summary",
        InternalAdminSummaryView.as_view(),
        name="internal-admin-summary",
    ),
    path("v1/wallets/create", CreateWalletView.as_view(), name="wallet-create"),
    path(
        "v1/wallets/derive-address",
        DeriveAddressView.as_view(),
        name="wallet-derive-address",
    ),
    path("v1/sign/evm", SignEvmView.as_view(), name="sign-evm"),
    path("v1/sign/bitcoin", SignBitcoinView.as_view(), name="sign-bitcoin"),
]
