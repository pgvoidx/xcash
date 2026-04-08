from __future__ import annotations

from decimal import ROUND_DOWN
from decimal import Decimal

from bitcoin.constants import SATOSHI_PER_BTC


def btc_to_satoshi(amount: Decimal | float | str) -> int:
    normalized = Decimal(str(amount))
    return int(
        (normalized * SATOSHI_PER_BTC).quantize(Decimal("1"), rounding=ROUND_DOWN)
    )
