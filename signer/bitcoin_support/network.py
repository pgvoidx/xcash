from __future__ import annotations

from dataclasses import dataclass

from bip_utils import Bip44Coins
from bip_utils import Bip84Coins
from django.conf import settings


@dataclass(frozen=True)
class BitcoinNetworkConfig:
    """描述 signer 当前运行所使用的 Bitcoin 网络参数。"""

    name: str
    wif_prefix: bytes
    bip44_coin: Bip44Coins
    bip84_coin: Bip84Coins
    bit_private_key_class_name: str


BITCOIN_NETWORKS: dict[str, BitcoinNetworkConfig] = {
    "mainnet": BitcoinNetworkConfig(
        name="mainnet",
        wif_prefix=b"\x80",
        bip44_coin=Bip44Coins.BITCOIN,
        bip84_coin=Bip84Coins.BITCOIN,
        bit_private_key_class_name="PrivateKey",
    ),
    # regtest / signet 继续沿用 testnet 的 WIF 与 BIP44 coin 语义。
    "testnet": BitcoinNetworkConfig(
        name="testnet",
        wif_prefix=b"\xef",
        bip44_coin=Bip44Coins.BITCOIN_TESTNET,
        bip84_coin=Bip84Coins.BITCOIN_TESTNET,
        bit_private_key_class_name="PrivateKeyTestnet",
    ),
    "signet": BitcoinNetworkConfig(
        name="signet",
        wif_prefix=b"\xef",
        bip44_coin=Bip44Coins.BITCOIN_TESTNET,
        bip84_coin=Bip84Coins.BITCOIN_TESTNET,
        bit_private_key_class_name="PrivateKeyTestnet",
    ),
    "regtest": BitcoinNetworkConfig(
        name="regtest",
        wif_prefix=b"\xef",
        bip44_coin=Bip44Coins.BITCOIN_TESTNET,
        bip84_coin=Bip84Coins.BITCOIN_REGTEST,
        bit_private_key_class_name="PrivateKeyTestnet",
    ),
}


def get_active_bitcoin_network() -> BitcoinNetworkConfig:
    network_name = settings.BITCOIN_NETWORK.strip().lower()
    try:
        return BITCOIN_NETWORKS[network_name]
    except KeyError as exc:
        supported = ", ".join(sorted(BITCOIN_NETWORKS))
        msg = f"Unsupported BITCOIN_NETWORK={network_name}. Supported: {supported}"
        raise ValueError(msg) from exc
