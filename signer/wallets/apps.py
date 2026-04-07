from django.apps import AppConfig


class WalletsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "wallets"
    verbose_name = "Signer Wallets"

    def ready(self):
        from bitcoin_support.network import get_active_bitcoin_network
        from bitcoinutils.setup import setup

        network = get_active_bitcoin_network()
        setup(network.bitcoinutils_network)
