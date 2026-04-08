from __future__ import annotations

from typing import TYPE_CHECKING

from bitcoin.rpc import BitcoinRpcClient
from bitcoin.rpc import BitcoinRpcError
from chains.adapters import AdapterInterface
from chains.adapters import TxCheckStatus
from common.utils.bitcoin import is_valid_bitcoin_address

if TYPE_CHECKING:
    from chains.models import Chain
    from chains.types import AddressStr
    from currencies.models import Crypto


class BitcoinAdapter(AdapterInterface):
    """Bitcoin 链适配器：负责地址验证和交易状态查询。"""

    @classmethod
    def validate_address(cls, address: AddressStr) -> bool:
        return is_valid_bitcoin_address(str(address))

    @classmethod
    def is_address(cls, chain: Chain, address: AddressStr) -> bool:
        return cls.validate_address(address)

    @classmethod
    def is_contract(cls, chain: Chain, address: AddressStr) -> bool:
        return False

    @classmethod
    def get_balance(cls, address: AddressStr, chain: Chain, crypto: Crypto) -> int:
        raise NotImplementedError("BTC 仅支持 Invoice 支付，不支持余额查询")

    @classmethod
    def tx_result(cls, chain: Chain, tx_hash: str) -> TxCheckStatus | Exception:
        """查询比特币交易的链上确认状态。"""
        try:
            client = BitcoinRpcClient(chain.rpc)
            try:
                tx = client.get_transaction(tx_hash)
            except BitcoinRpcError as exc:
                if "Requested wallet does not exist or is not loaded" not in str(exc):
                    raise
                tx = None
            if tx is None:
                tx = client.get_raw_transaction(tx_hash)

            if tx is None:
                return TxCheckStatus.DROPPED

            confirmations = int(tx.get("confirmations", 0))
            if confirmations < 0:
                return TxCheckStatus.DROPPED

            if confirmations >= chain.confirm_block_count:
                return TxCheckStatus.CONFIRMED
        except Exception as exc:  # noqa: BLE001
            return exc
        else:
            return TxCheckStatus.CONFIRMING
