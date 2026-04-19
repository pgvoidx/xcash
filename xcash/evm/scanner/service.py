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
from evm.scanner.rpc import EvmScannerRpcClient
from evm.scanner.watchers import load_watch_set


@dataclass(frozen=True)
class EvmScanSummary:
    """汇总单条链一次自扫描任务的结果。"""

    native: EvmNativeScanResult
    erc20: EvmErc20ScanResult


@dataclass(frozen=True)
class EvmReconcileScanResult:
    """汇总一次兜底复扫的产出，供调用方观测命中情况。

    from_block / to_block 仅记录合并出的扫描区间，便于日志与断言；不会映射到任何游标。
    """

    from_block: int
    to_block: int
    observed_native: int
    observed_erc20: int
    created_native: int
    created_erc20: int


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

    @classmethod
    def scan_blocks_for_reconcile(
        cls,
        *,
        chain: Chain,
        block_numbers: set[int],
    ) -> EvmReconcileScanResult:
        """对指定块集合执行一次兜底复扫，不推进任何游标。

        - 合并为 [min..max] 连续区间，利用 native 逐块扫 / ERC20 logFilter 的原生能力，
          比按块分别调用更省 RPC 调用。
        - 复用 watch_set + OnchainTransfer 创建 + on_commit 派发 process 的既有管线，
          (chain, hash, event_id) 唯一约束天然保证复扫幂等。
        - 禁止读写 EvmScanCursor；主扫描负责游标管理，兜底只产生观测副作用。
        """
        if chain.type != ChainType.EVM:
            raise ValueError(f"仅支持扫描 EVM 链，当前链为 {chain.code}")
        if not block_numbers:
            return EvmReconcileScanResult(
                from_block=0,
                to_block=-1,
                observed_native=0,
                observed_erc20=0,
                created_native=0,
                created_erc20=0,
            )

        from_block = min(block_numbers)
        to_block = max(block_numbers)
        rpc_client = EvmScannerRpcClient(chain=chain)
        watch_set = load_watch_set(chain=chain)

        observed_native, created_native = 0, 0
        observed_erc20, created_erc20 = 0, 0

        if cls._is_enabled(
            chain=chain,
            scanner_type=EvmScanCursorType.NATIVE_DIRECT,
        ):
            observed_native, created_native = (
                EvmNativeDirectScanner.scan_range_without_cursor(
                    chain=chain,
                    rpc_client=rpc_client,
                    watch_set=watch_set,
                    from_block=from_block,
                    to_block=to_block,
                )
            )

        if cls._is_enabled(
            chain=chain,
            scanner_type=EvmScanCursorType.ERC20_TRANSFER,
        ):
            logs, created_erc20 = EvmErc20TransferScanner.scan_range_without_cursor(
                chain=chain,
                rpc_client=rpc_client,
                watch_set=watch_set,
                from_block=from_block,
                to_block=to_block,
            )
            observed_erc20 = len(logs)

        return EvmReconcileScanResult(
            from_block=from_block,
            to_block=to_block,
            observed_native=observed_native,
            observed_erc20=observed_erc20,
            created_native=created_native,
            created_erc20=created_erc20,
        )
