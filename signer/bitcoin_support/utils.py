from __future__ import annotations

from decimal import ROUND_DOWN
from decimal import Decimal

from bip_utils import P2PKHAddrDecoder
from bip_utils import P2SHAddrDecoder
from bip_utils import SegwitBech32Decoder

from .network import get_active_bitcoin_network

SATOSHI_PER_BTC = Decimal("100000000")


def btc_to_satoshi(amount: Decimal | float | str) -> int:
    normalized = Decimal(str(amount))
    return int(
        (normalized * SATOSHI_PER_BTC).quantize(Decimal("1"), rounding=ROUND_DOWN)
    )


def privkey_bytes_to_wif(privkey_bytes: bytes) -> str:
    """将原始 32 字节 secp256k1 私钥转换为当前网络 WIF（压缩格式）。

    依赖 bitcoinutils.setup.setup() 已在 AppConfig.ready() 中按当前网络初始化。
    """
    from bitcoinutils.keys import PrivateKey

    secret_exponent = int.from_bytes(privkey_bytes, byteorder="big")
    return PrivateKey(secret_exponent=secret_exponent).to_wif()


def is_valid_bitcoin_address(address: str) -> bool:
    """对当前 Bitcoin 网络地址执行 checksum 校验（P2PKH / P2SH / SegWit）。"""
    network = get_active_bitcoin_network()

    # bip_utils 没有直接暴露 testnet/regtest 的版本字节常量，需要手动传入。
    # mainnet: P2PKH=0x00, P2SH=0x05; testnet/regtest: P2PKH=0x6f, P2SH=0xc4
    p2pkh_ver = b"\x00" if network.name == "mainnet" else b"\x6f"
    p2sh_ver = b"\x05" if network.name == "mainnet" else b"\xc4"
    bech32_hrp = "bc" if network.name == "mainnet" else "tb"
    if network.name == "regtest":
        bech32_hrp = "bcrt"

    for decoder, ver in [(P2PKHAddrDecoder, p2pkh_ver), (P2SHAddrDecoder, p2sh_ver)]:
        try:
            decoder.DecodeAddr(address, net_ver=ver)
        except Exception:  # noqa: BLE001, S110
            pass
        else:
            return True

    try:
        SegwitBech32Decoder.Decode(bech32_hrp, address)
    except Exception:  # noqa: BLE001
        return False
    else:
        return True


def compute_txid(signed_payload_hex: str) -> str:
    """从已签名原始交易 hex 计算 txid。

    SegWit 交易的 txid 基于去除 witness 数据后的序列化。
    """
    from bitcoinutils.transactions import Transaction

    return Transaction.from_raw(signed_payload_hex).get_txid()


def classify_bitcoin_address(address: str) -> str:
    """识别 Bitcoin 地址类型，返回 'p2pkh' / 'p2sh' / 'p2wpkh' / 'unknown'。"""
    if not address:
        return "unknown"
    lower = address.lower()
    if lower.startswith(("bc1q", "tb1q", "bcrt1q")):
        return "p2wpkh"
    if address[0] in ("3", "2"):
        return "p2sh"
    if address[0] in ("1", "m", "n"):
        return "p2pkh"
    return "unknown"
