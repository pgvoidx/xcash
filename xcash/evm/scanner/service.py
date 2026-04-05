from __future__ import annotations

from dataclasses import dataclass

from chains.models import Chain
from chains.models import ChainType
from evm.models import EvmScanCursor
from evm.models import EvmScanCursorType
from evm.scanner.erc20 import EvmErc20ScanResult
from evm.scanner.erc20 import EvmErc20TransferScanner
from evm.scanner.native import EvmNativeDirectScanner
from evm.scanner.native import EvmNativeScanResult


@dataclass(frozen=True)
class EvmScanSummary:
    """汇总单条链一次自扫描任务的结果。"""

    native: EvmNativeScanResult
    erc20: EvmErc20ScanResult


class EvmChainScannerService:
    """统一编排一条 EVM 链上的自扫描流程。"""

    @staticmethod
    def _is_enabled(*, chain: Chain, scanner_type: EvmScanCursorType) -> bool:
        enabled = (
            EvmScanCursor.objects.filter(
                chain=chain,
                scanner_type=scanner_type,
            )
            .values_list("enabled", flat=True)
            .first()
        )
        return True if enabled is None else bool(enabled)

    @staticmethod
    def _empty_native_result(*, chain: Chain) -> EvmNativeScanResult:
        return EvmNativeScanResult(
            from_block=0,
            to_block=0,
            latest_block=chain.latest_block_number,
            observed_transfers=0,
            created_transfers=0,
        )

    @staticmethod
    def _empty_erc20_result(*, chain: Chain) -> EvmErc20ScanResult:
        return EvmErc20ScanResult(
            from_block=0,
            to_block=0,
            latest_block=chain.latest_block_number,
            observed_logs=0,
            created_transfers=0,
        )

    @staticmethod
    def scan_chain(*, chain: Chain) -> EvmScanSummary:
        if chain.type != ChainType.EVM:
            raise ValueError(f"仅支持扫描 EVM 链，当前链为 {chain.code}")

        return EvmScanSummary(
            native=(
                EvmNativeDirectScanner.scan_chain(chain=chain)
                if EvmChainScannerService._is_enabled(
                    chain=chain,
                    scanner_type=EvmScanCursorType.NATIVE_DIRECT,
                )
                else EvmChainScannerService._empty_native_result(chain=chain)
            ),
            erc20=(
                EvmErc20TransferScanner.scan_chain(chain=chain)
                if EvmChainScannerService._is_enabled(
                    chain=chain,
                    scanner_type=EvmScanCursorType.ERC20_TRANSFER,
                )
                else EvmChainScannerService._empty_erc20_result(chain=chain)
            ),
        )
