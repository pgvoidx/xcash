from __future__ import annotations

import hashlib
from decimal import ROUND_DOWN
from decimal import Decimal
from typing import TYPE_CHECKING

from bip_utils import Base58Encoder  # type: ignore[import]

from bitcoin.constants import BTC_DEFAULT_FEE_RATE_SAT_PER_BYTE
from bitcoin.constants import BTC_P2PKH_INPUT_VBYTES
from bitcoin.constants import BTC_P2PKH_OUTPUT_VBYTES
from bitcoin.constants import BTC_P2PKH_TX_OVERHEAD_VBYTES
from bitcoin.constants import SATOSHI_PER_BTC
from bitcoin.network import get_active_bitcoin_network

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bitcoin.rpc import BitcoinUtxo
    from chains.models import Chain
    from currencies.models import Crypto


def ensure_bitcoin_native_currency(*, chain: Chain, crypto: Crypto) -> None:
    """强约束 Bitcoin 链只能处理该链的原生 BTC。"""
    if chain.type != "btc":
        msg = f"链类型不是 Bitcoin: {chain.code}"
        raise ValueError(msg)

    if crypto.pk != chain.native_coin_id:
        msg = (
            f"Bitcoin 暂仅支持链原生币 {chain.native_coin.symbol}，"
            f"当前收到 {crypto.symbol}"
        )
        raise NotImplementedError(msg)


def btc_to_satoshi(amount: Decimal | float | str) -> int:
    normalized = Decimal(str(amount))
    return int(
        (normalized * SATOSHI_PER_BTC).quantize(Decimal("1"), rounding=ROUND_DOWN)
    )


def sat_per_byte_from_btc_per_kb(fee_rate_btc_per_kb: Decimal) -> int:
    return max(
        int(fee_rate_btc_per_kb * SATOSHI_PER_BTC / 1000),
        BTC_DEFAULT_FEE_RATE_SAT_PER_BYTE,
    )


def estimate_p2pkh_tx_vbytes(*, input_count: int, output_count: int = 2) -> int:
    """估算 legacy P2PKH 交易大小。

    采用保守估算：
    - 10 bytes 固定开销（version/locktime/varint 等）
    - 每个输入约 148 bytes
    - 每个输出约 34 bytes
    当前项目钱包派生的是 P2PKH（1...）地址，此估算成立。
    """
    return (
        BTC_P2PKH_TX_OVERHEAD_VBYTES
        + input_count * BTC_P2PKH_INPUT_VBYTES
        + output_count * BTC_P2PKH_OUTPUT_VBYTES
    )


def select_utxos_for_amount(
    *,
    utxos: Sequence[BitcoinUtxo],
    amount_satoshi: int,
    fee_rate_sat_per_byte: int,
) -> tuple[list[BitcoinUtxo], int]:
    """为支付金额选择一组 UTXO，并返回保守估算的矿工费。

    这里始终按“2 输出（收款 + 找零）”估算，宁可略高估，也不接受低估费率后广播失败。
    选取策略为按金额从大到小挑选，目标是尽量减少输入数，从而减少矿工费和失败概率。
    """
    selected: list[BitcoinUtxo] = []
    total_satoshi = 0

    for utxo in sorted(
        utxos, key=lambda item: btc_to_satoshi(item["amount"]), reverse=True
    ):
        selected.append(utxo)
        total_satoshi += btc_to_satoshi(utxo["amount"])

        fee_satoshi = (
            estimate_p2pkh_tx_vbytes(
                input_count=len(selected),
                output_count=2,
            )
            * fee_rate_sat_per_byte
        )

        if total_satoshi >= amount_satoshi + fee_satoshi:
            return selected, fee_satoshi

    msg = "Bitcoin UTXO 余额不足以覆盖转账金额与矿工费"
    raise ValueError(msg)


def select_utxos_for_sweep(
    *,
    utxos: Sequence[BitcoinUtxo],
    fee_rate_sat_per_byte: int,
) -> tuple[list[BitcoinUtxo], int, int]:
    """选择全部 UTXO 执行 sweep，并返回可转出净额与矿工费。

    sweep 语义用于归集：把地址上当前全部可用余额一次性打到目标地址，
    不再依赖调用方先用固定 fee 预扣一个"大概金额"。
    """
    selected = list(utxos)
    if not selected:
        raise ValueError("Bitcoin sweep 缺少可用 UTXO")

    total_satoshi = sum(btc_to_satoshi(utxo["amount"]) for utxo in selected)
    fee_satoshi = (
        estimate_p2pkh_tx_vbytes(
            input_count=len(selected),
            output_count=1,
        )
        * fee_rate_sat_per_byte
    )
    amount_satoshi = total_satoshi - fee_satoshi
    if amount_satoshi <= 0:
        raise ValueError("Bitcoin UTXO 余额不足以覆盖 sweep 矿工费")
    return selected, amount_satoshi, fee_satoshi


def privkey_bytes_to_wif(privkey_bytes: bytes) -> str:
    """将原始 32 字节 secp256k1 私钥转换为当前网络 WIF（压缩格式）。"""
    network = get_active_bitcoin_network()
    payload = network.wif_prefix + privkey_bytes + b"\x01"
    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return Base58Encoder.Encode(payload + checksum)


def compute_txid(signed_payload_hex: str) -> str:
    """从已签名 P2PKH 载荷 hex 计算 txid（double-SHA256 + 字节反转）。"""
    tx_bytes = bytes.fromhex(signed_payload_hex)
    txid_bytes = hashlib.sha256(hashlib.sha256(tx_bytes).digest()).digest()
    return txid_bytes[::-1].hex()


def _read_bitcoin_varint(raw: bytes, offset: int) -> tuple[int, int]:
    if offset >= len(raw):
        raise ValueError("Bitcoin 原始交易缺少 varint")

    prefix = raw[offset]
    if prefix < 0xFD:
        return prefix, offset + 1
    if prefix == 0xFD:
        end = offset + 3
        if end > len(raw):
            raise ValueError("Bitcoin 原始交易 varint(uint16) 不完整")
        return int.from_bytes(raw[offset + 1 : end], "little"), end
    if prefix == 0xFE:
        end = offset + 5
        if end > len(raw):
            raise ValueError("Bitcoin 原始交易 varint(uint32) 不完整")
        return int.from_bytes(raw[offset + 1 : end], "little"), end

    end = offset + 9
    if end > len(raw):
        raise ValueError("Bitcoin 原始交易 varint(uint64) 不完整")
    return int.from_bytes(raw[offset + 1 : end], "little"), end


def extract_input_sequences_from_raw_transaction(
    signed_payload_hex: str,
) -> list[int]:
    """从原始交易 hex 中提取每个输入的 nSequence，用于判断是否 opt-in RBF。"""
    raw = bytes.fromhex(signed_payload_hex)
    if len(raw) < 5:
        raise ValueError("Bitcoin 原始交易长度不足")

    offset = 4
    if len(raw) > offset + 1 and raw[offset] == 0 and raw[offset + 1] == 1:
        # segwit 交易在 version 后插入 marker/flag；当前项目主用 P2PKH，
        # 这里仍保留解析兼容，避免后续地址类型扩展时重复造轮子。
        offset += 2

    input_count, offset = _read_bitcoin_varint(raw, offset)
    sequences: list[int] = []
    for _ in range(input_count):
        if offset + 36 > len(raw):
            raise ValueError("Bitcoin 原始交易缺少完整输入前缀")
        offset += 36  # prevout txid(32) + vout(4)
        script_length, offset = _read_bitcoin_varint(raw, offset)
        if offset + script_length + 4 > len(raw):
            raise ValueError("Bitcoin 原始交易缺少完整 scriptSig 或 sequence")
        offset += script_length
        sequences.append(int.from_bytes(raw[offset : offset + 4], "little"))
        offset += 4
    return sequences


def is_replaceable_signed_transaction(signed_payload_hex: str) -> bool:
    """检查原始交易是否显式 opt-in RBF。"""
    try:
        sequences = extract_input_sequences_from_raw_transaction(signed_payload_hex)
    except ValueError:
        return False
    return any(sequence < 0xFFFFFFFE for sequence in sequences)
