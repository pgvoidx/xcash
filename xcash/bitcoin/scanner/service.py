from __future__ import annotations

from dataclasses import dataclass

from bitcoin.scanner.receipt import BitcoinReceiptScanner
from chains.models import Chain
from chains.models import ChainType


@dataclass(frozen=True)
class BitcoinScanSummary:
    """汇总单条 Bitcoin 链一次自扫描任务的结果。"""

    created_receipts: int


class BitcoinChainScannerService:
    """统一编排一条 Bitcoin 链上的自扫描流程。"""

    @staticmethod
    def scan_chain(*, chain: Chain) -> BitcoinScanSummary:
        if chain.type != ChainType.BITCOIN:
            raise ValueError(f"仅支持扫描 Bitcoin 链，当前链为 {chain.code}")

        # Bitcoin 当前只接入标准 BTC 收款扫描；后续若扩展 UTXO 事件类型，统一收口在这里。
        return BitcoinScanSummary(
            created_receipts=BitcoinReceiptScanner.scan_recent_receipts(chain),
        )
