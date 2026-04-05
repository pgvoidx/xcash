from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from bitcoin.rpc import BitcoinRpcClient
from bitcoin.rpc import BitcoinRpcError
from bitcoin.utils import btc_to_satoshi
from bitcoin.utils import ensure_bitcoin_native_currency
from chains.adapters import AdapterInterface
from chains.adapters import TxCheckStatus
from common.utils.bitcoin import is_valid_bitcoin_address

if TYPE_CHECKING:
    from chains.models import Chain
    from chains.types import AddressStr
    from currencies.models import Crypto


class BitcoinAdapter(AdapterInterface):
    """Bitcoin 链适配器：负责地址验证、余额查询和交易状态查询。"""

    @classmethod
    def validate_address(cls, address: AddressStr) -> bool:
        # 统一复用公共 checksum 校验，避免模型层与适配器层出现两套 BTC 规则。
        return is_valid_bitcoin_address(str(address))

    @classmethod
    def is_address(cls, chain: Chain, address: AddressStr) -> bool:
        return cls.validate_address(address)

    @classmethod
    def is_contract(cls, chain: Chain, address: AddressStr) -> bool:
        return False

    @classmethod
    def get_balance(cls, address: AddressStr, chain: Chain, crypto: Crypto) -> int:
        """查询地址 BTC 余额，返回 satoshi 整数。"""
        ensure_bitcoin_native_currency(chain=chain, crypto=crypto)

        client = BitcoinRpcClient(chain.rpc)
        # 钱包未导入 watch-only 地址时，余额查询也要能回退到 UTXO 集扫描。
        utxos = client.list_unspent(str(address), min_conf=1)
        if not utxos:
            utxos = client.scan_unspent(str(address), min_conf=1)
        total_btc = sum(Decimal(str(utxo["amount"])) for utxo in utxos)
        return btc_to_satoshi(total_btc)

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
