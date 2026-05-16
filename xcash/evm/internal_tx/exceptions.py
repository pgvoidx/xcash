from __future__ import annotations


class UnknownInternalBroadcastError(RuntimeError):
    """系统内地址发出交易但无法解析到对应 BroadcastTask。"""

    def __init__(self, *, chain_code: str, tx_hash: str, from_address: str):
        super().__init__(
            f"system address {from_address} sent tx {tx_hash} on {chain_code} "
            f"without a resolvable BroadcastTask"
        )
        self.chain_code = chain_code
        self.tx_hash = tx_hash
        self.from_address = from_address

