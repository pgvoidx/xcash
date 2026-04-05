from __future__ import annotations

import structlog
from django.db import transaction as db_transaction
from web3.exceptions import TransactionNotFound

from chains.adapters import TxCheckStatus
from chains.models import BroadcastTask
from chains.models import BroadcastTaskFailureReason
from chains.models import BroadcastTaskResult
from chains.models import BroadcastTaskStage
from chains.models import Chain
from chains.models import TransferType
from evm.models import EvmBroadcastTask

logger = structlog.get_logger()


class InternalEvmTaskCoordinator:
    """协调内部 EVM 任务的链上终局状态。

    语义边界：
    - 协调主体是内部 `EvmBroadcastTask(address, chain, nonce)`，而不是 Transfer。
    - `nonce` 是内部发送意图的稳定身份；当前 receipt 查询入口仍暂时依赖已保存的 tx_hash。
    - 这里只负责“明确失败”的终局收口；成功态继续由 Transfer 观测路径推进。
    """

    @classmethod
    def reconcile_chain(cls, *, chain: Chain) -> int:
        failed_count = 0
        queryset = (
            EvmBroadcastTask.objects.select_related("base_task", "address")
            .filter(
                chain=chain,
                completed=False,
                base_task__stage=BroadcastTaskStage.PENDING_CHAIN,
                base_task__result=BroadcastTaskResult.UNKNOWN,
            )
            .order_by("address_id", "nonce", "created_at")
        )

        for evm_task in queryset:
            if not evm_task.base_task_id:
                continue

            result = cls._current_attempt_result(evm_task=evm_task)
            if isinstance(result, Exception):
                logger.warning(
                    "内部 EVM 任务确认失败，跳过本轮收口",
                    chain=chain.code,
                    address_id=evm_task.address_id,
                    nonce=evm_task.nonce,
                    tx_hash=evm_task.base_task.tx_hash,
                    error=str(result),
                )
                continue
            if result != TxCheckStatus.FAILED:
                continue

            if cls._finalize_failed_task(evm_task=evm_task):
                failed_count += 1

        return failed_count

    @staticmethod
    @db_transaction.atomic
    def _finalize_failed_task(*, evm_task: EvmBroadcastTask) -> bool:
        from withdrawals.service import WithdrawalService

        locked_task = EvmBroadcastTask.objects.select_for_update().get(pk=evm_task.pk)
        if not locked_task.base_task_id:
            return False

        base_task = locked_task.base_task
        if (
            locked_task.completed
            or base_task.stage != BroadcastTaskStage.PENDING_CHAIN
            or base_task.result != BroadcastTaskResult.UNKNOWN
        ):
            return False

        updated = BroadcastTask.mark_finalized_failed(
            task_id=base_task.pk,
            reason=BroadcastTaskFailureReason.EXECUTION_REVERTED,
        )
        if not updated:
            return False

        EvmBroadcastTask.objects.filter(pk=locked_task.pk, completed=False).update(
            completed=True
        )
        if base_task.transfer_type == TransferType.Withdrawal:
            WithdrawalService.fail_withdrawal(broadcast_task=base_task)
        return True

    @staticmethod
    def _current_attempt_result(
        *, evm_task: EvmBroadcastTask
    ) -> TxCheckStatus | Exception:
        """查询当前这次广播尝试的 receipt 状态。

        协调器以 `(chain, address, nonce)` 为内部任务稳定身份，但查链上结果仍暂时通过
        当前保存的 tx_hash 入口读取 receipt。这里不产出 DROPPED 语义：
        - not found / receipt is None 只表示仍在确认中
        - status=0 表示当前尝试明确失败
        """
        tx_hash = evm_task.base_task.tx_hash
        try:
            receipt = evm_task.chain.w3.eth.get_transaction_receipt(
                tx_hash
            )  # noqa: SLF001
        except TransactionNotFound:
            return TxCheckStatus.CONFIRMING
        except Exception as exc:  # noqa: BLE001
            return exc

        if receipt is None:
            return TxCheckStatus.CONFIRMING

        status = receipt.get("status")
        if status == 1:
            return TxCheckStatus.CONFIRMED
        if status == 0:
            return TxCheckStatus.FAILED
        return RuntimeError("EVM receipt status missing or invalid")
