from __future__ import annotations

from dataclasses import dataclass

from chains.models import ChainType


@dataclass(frozen=True)
class BitcoinWatchSet:
    """描述 Bitcoin 扫描器当前需要关注的地址集合。"""

    watched_addresses: frozenset[str]
    recipient_addresses: frozenset[str]


def load_watch_set() -> BitcoinWatchSet:
    """加载 Bitcoin 收款扫描需要关注的系统地址集合。"""
    from deposits.models import DepositAddress
    from projects.models import RecipientAddress

    # BTC 内部扫描只盯“真正会收币”的地址集合。
    # 先覆盖客户充币地址和项目收币地址，不把金库地址纳入监听，避免误把找零识别成入账。
    deposit_addresses = set(
        DepositAddress.objects.filter(chain_type=ChainType.BITCOIN).values_list(
            "address__address",
            flat=True,
        )
    )
    recipient_addresses = set(
        RecipientAddress.objects.filter(chain_type=ChainType.BITCOIN).values_list(
            "address",
            flat=True,
        )
    )
    return BitcoinWatchSet(
        watched_addresses=frozenset(deposit_addresses | recipient_addresses),
        recipient_addresses=frozenset(recipient_addresses),
    )
