from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from chains.models import Chain


class EvmScannerRpcError(RuntimeError):
    """统一包装 EVM 自扫描涉及的 RPC 异常。"""


class EvmScannerRpcClient:
    """对扫描器暴露最小 RPC 面，隔离 Web3 原始异常细节。"""

    def __init__(self, *, chain: Chain):
        self.chain = chain

    def get_latest_block_number(self) -> int:
        try:
            return int(self.chain.get_latest_block_number)
        except Exception as exc:  # noqa: BLE001
            raise EvmScannerRpcError(
                f"获取最新区块失败: chain={self.chain.code}"
            ) from exc

    def get_transfer_logs(
        self,
        *,
        from_block: int,
        to_block: int,
        token_addresses: list[str],
        topic0: str,
    ) -> list[dict[str, Any]]:
        if from_block > to_block or not token_addresses:
            return []

        max_block_range = max(1, int(getattr(self.chain, "evm_log_max_block_range", 10)))
        logs: list[dict[str, Any]] = []
        chunk_from = from_block

        while chunk_from <= to_block:
            chunk_to = min(to_block, chunk_from + max_block_range - 1)
            logs.extend(
                self._get_transfer_logs_chunk(
                    from_block=chunk_from,
                    to_block=chunk_to,
                    token_addresses=token_addresses,
                    topic0=topic0,
                )
            )
            chunk_from = chunk_to + 1

        return logs

    def _get_transfer_logs_chunk(
        self,
        *,
        from_block: int,
        to_block: int,
        token_addresses: list[str],
        topic0: str,
    ) -> list[dict[str, Any]]:
        try:
            return list(
                self.chain.w3.eth.get_logs(  # noqa: SLF001
                    {
                        "fromBlock": from_block,
                        "toBlock": to_block,
                        "address": token_addresses,
                        "topics": [topic0],
                    }
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise EvmScannerRpcError(
                f"获取 ERC20 日志失败: chain={self.chain.code} from={from_block} to={to_block}"
            ) from exc

    def get_block_timestamp(self, *, block_number: int) -> int:
        try:
            block = self.chain.w3.eth.get_block(
                block_number, full_transactions=False
            )  # noqa: SLF001
            return int(block["timestamp"])
        except Exception as exc:  # noqa: BLE001
            raise EvmScannerRpcError(
                f"获取区块时间失败: chain={self.chain.code} block={block_number}"
            ) from exc

    def get_full_block(self, *, block_number: int) -> dict[str, Any]:
        try:
            return dict(
                self.chain.w3.eth.get_block(
                    block_number, full_transactions=True
                )  # noqa: SLF001
            )
        except Exception as exc:  # noqa: BLE001
            raise EvmScannerRpcError(
                f"获取完整区块失败: chain={self.chain.code} block={block_number}"
            ) from exc

    def get_transaction_receipt_status(self, *, tx_hash: str) -> int | None:
        try:
            receipt = self.chain.w3.eth.get_transaction_receipt(tx_hash)  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001
            raise EvmScannerRpcError(
                f"获取交易回执失败: chain={self.chain.code} tx_hash={tx_hash}"
            ) from exc

        if receipt is None:
            return None
        status = receipt.get("status")
        return int(status) if status in (0, 1) else None
