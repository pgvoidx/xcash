from __future__ import annotations

from decimal import Decimal
from typing import Any
from typing import TypedDict
from typing import cast

import httpx

from bitcoin.constants import BTC_DEFAULT_FEE_RATE_SAT_PER_BYTE
from bitcoin.constants import BTC_FEE_TARGET_BLOCKS
from bitcoin.constants import SATOSHI_PER_BTC


class BitcoinRpcError(RuntimeError):
    """Bitcoin Core JSON-RPC 调用失败。"""


class BitcoinRpcErrorPayload(TypedDict, total=False):
    code: int
    message: str


class BitcoinUtxo(TypedDict, total=False):
    txid: str
    vout: int
    amount: float | str
    confirmations: int
    height: int
    scriptPubKey: str


class BitcoinScriptPubKey(TypedDict, total=False):
    address: str
    addresses: list[str]
    type: str


class BitcoinTxVout(TypedDict, total=False):
    n: int
    value: float | str
    scriptPubKey: BitcoinScriptPubKey


class BitcoinTxVin(TypedDict, total=False):
    txid: str
    vout: int
    coinbase: str


class BitcoinTxInfo(TypedDict, total=False):
    confirmations: int
    txid: str
    blockhash: str
    time: int
    blocktime: int
    vin: list[BitcoinTxVin]
    vout: list[BitcoinTxVout]


class BitcoinBlockInfo(TypedDict, total=False):
    hash: str
    height: int
    time: int
    tx: list[BitcoinTxInfo]


class BitcoinRpcClient:
    """Bitcoin Core JSON-RPC 客户端。

    rpc_url 格式：http://rpcuser:rpcpassword@host:port/
    例如：http://bitcoin:secret@bitcoinnode:8332/
    """

    def __init__(self, rpc_url: str) -> None:
        if not rpc_url:
            msg = "Bitcoin RPC URL 未配置"
            raise ValueError(msg)
        self.rpc_url = rpc_url

    def _call(self, method: str, params: list[Any] | None = None) -> Any:
        """执行 Bitcoin Core JSON-RPC 调用，返回 result；错误时抛出 BitcoinRpcError。"""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or [],
        }
        try:
            resp = httpx.post(
                self.rpc_url,
                json=payload,
                timeout=30,
                trust_env=False,
            )
            data = resp.json()
        except ValueError as exc:
            msg = f"Bitcoin RPC 返回了非法 JSON（{method}）"
            raise BitcoinRpcError(msg) from exc
        except httpx.HTTPError as exc:
            msg = f"Bitcoin RPC 请求失败（{method}）: {exc}"
            raise BitcoinRpcError(msg) from exc

        error_payload = data.get("error")
        if error_payload:
            error = cast("BitcoinRpcErrorPayload", error_payload)
            error_msg = error.get("message", str(error_payload))
            msg = f"Bitcoin RPC error ({method}): {error_msg}"
            raise BitcoinRpcError(msg)

        if resp.is_error:
            # Bitcoin Core 的部分钱包 RPC（如 loadwallet 不存在）会返回 HTTP 500，
            # 但实际错误语义已在上面的 JSON error 中处理；走到这里说明服务端异常且无标准 error。
            try:
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                msg = f"Bitcoin RPC 请求失败（{method}）: {exc}"
                raise BitcoinRpcError(msg) from exc

        return data["result"]

    def get_block_count(self) -> int:
        return int(self._call("getblockcount"))

    def list_wallets(self) -> list[str]:
        result = self._call("listwallets")
        if not result:
            return []
        return cast("list[str]", result)

    def create_wallet(
        self,
        wallet_name: str,
        *,
        disable_private_keys: bool = False,
        blank: bool = False,
    ) -> dict[str, Any]:
        return cast(
            "dict[str, Any]",
            self._call("createwallet", [wallet_name, disable_private_keys, blank]),
        )

    def load_wallet(self, wallet_name: str) -> dict[str, Any]:
        return cast("dict[str, Any]", self._call("loadwallet", [wallet_name]))

    def get_new_address(self, label: str = "", address_type: str = "legacy") -> str:
        return cast("str", self._call("getnewaddress", [label, address_type]))

    def generate_to_address(self, block_count: int, address: str) -> list[str]:
        return cast(
            "list[str]", self._call("generatetoaddress", [block_count, address])
        )

    def import_address(
        self,
        address: str,
        *,
        label: str = "",
        rescan: bool = False,
    ) -> None:
        self._call("importaddress", [address, label, rescan])

    def import_descriptor(
        self,
        *,
        descriptor: str,
        label: str = "",
        timestamp: str | int = "now",
    ) -> list[dict[str, Any]]:
        # importdescriptors 要求带 checksum 的 descriptor；先走 getdescriptorinfo 统一规范化。
        descriptor_info = self.get_descriptor_info(descriptor)
        request = {
            "desc": descriptor_info["descriptor"],
            "timestamp": timestamp,
            "label": label,
        }
        result = cast(
            "list[dict[str, Any]]", self._call("importdescriptors", [[request]])
        )
        first_result = result[0] if result else {}
        if not first_result.get("success", False):
            error_payload = first_result.get("error", {})
            error_message = error_payload.get("message", "unknown error")
            msg = f"Bitcoin RPC error (importdescriptors): {error_message}"
            raise BitcoinRpcError(msg)
        return result

    def get_descriptor_info(self, descriptor: str) -> dict[str, Any]:
        return cast("dict[str, Any]", self._call("getdescriptorinfo", [descriptor]))

    def send_to_address(self, address: str, amount_btc: Decimal | float | str) -> str:
        # Bitcoin Core 接受字符串格式金额；避免 float() 导致精度丢失。
        return cast("str", self._call("sendtoaddress", [address, str(amount_btc)]))

    def get_block_hash(self, height: int) -> str:
        return cast("str", self._call("getblockhash", [height]))

    def get_block(self, block_hash: str, verbosity: int = 2) -> BitcoinBlockInfo:
        return cast("BitcoinBlockInfo", self._call("getblock", [block_hash, verbosity]))

    def list_unspent(self, address: str, min_conf: int = 1) -> list[BitcoinUtxo]:
        result = self._call("listunspent", [min_conf, 9_999_999, [address]])
        if not result:
            return []
        return cast("list[BitcoinUtxo]", result)

    def scan_unspent(self, address: str, min_conf: int = 1) -> list[BitcoinUtxo]:
        # descriptor 私钥钱包无法直接 import watch-only 时，回退到全节点 UTXO 集扫描。
        result = cast(
            "dict[str, Any]",
            self._call("scantxoutset", ["start", [f"addr({address})"]]),
        )
        if not result.get("success"):
            return []

        best_height = int(result.get("height", 0))
        raw_unspents = cast("list[dict[str, Any]]", result.get("unspents", []))
        scanned_unspents: list[BitcoinUtxo] = []
        for utxo in raw_unspents:
            utxo_height = int(utxo.get("height", 0))
            confirmations = max(best_height - utxo_height + 1, 0) if utxo_height else 0
            if confirmations < min_conf:
                continue
            scanned_unspents.append(
                {
                    "txid": utxo["txid"],
                    "vout": int(utxo["vout"]),
                    "amount": utxo["amount"],
                    "confirmations": confirmations,
                    "height": utxo_height,
                    "scriptPubKey": utxo["scriptPubKey"],
                }
            )
        return scanned_unspents

    def get_transaction(self, txid: str) -> BitcoinTxInfo | None:
        try:
            return cast("BitcoinTxInfo", self._call("gettransaction", [txid, True]))
        except BitcoinRpcError as exc:
            error_message = str(exc)
            if (
                "Invalid or non-wallet transaction id" in error_message
                or "Requested wallet does not exist or is not loaded" in error_message
            ):
                return None
            raise

    def get_raw_transaction(self, txid: str) -> BitcoinTxInfo | None:
        try:
            return cast("BitcoinTxInfo", self._call("getrawtransaction", [txid, True]))
        except BitcoinRpcError as exc:
            if "No such mempool or blockchain transaction" in str(exc):
                return None
            raise

    def send_raw_transaction(self, hex_string: str) -> str:
        return cast("str", self._call("sendrawtransaction", [hex_string]))

    def estimate_smart_fee(self, conf_target: int = BTC_FEE_TARGET_BLOCKS) -> Decimal:
        """估算矿工费率（BTC/kB），若节点无法估算则返回默认值。"""
        try:
            result = self._call("estimatesmartfee", [conf_target])
        except BitcoinRpcError:
            result = None

        if isinstance(result, dict):
            fee_rate = result.get("feerate")
            if fee_rate:
                return Decimal(str(fee_rate))

        # 回退到默认费率（satoshi/byte → BTC/kB 转换）
        return Decimal(BTC_DEFAULT_FEE_RATE_SAT_PER_BYTE * 1000) / Decimal(
            SATOSHI_PER_BTC
        )
