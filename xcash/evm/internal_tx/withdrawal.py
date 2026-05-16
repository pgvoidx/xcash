from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from chains.models import (
    BroadcastTask,
    BroadcastTaskFailureReason,
    Chain,
    OnchainTransfer,
)
from evm.internal_tx._log_utils import matches_transfer_log, normalize_log_index
from evm.internal_tx.facts import MatchedTransferFact
from web3 import Web3


def withdrawal_matcher(
    *,
    chain: Chain,
    broadcast_task: BroadcastTask,
    receipt: dict,
) -> MatchedTransferFact | None:
    """提取 Withdrawal 预期的资产移动事实。"""
    return _task_transfer_fact(chain=chain, task=broadcast_task, receipt=receipt)


def _task_transfer_fact(
    *,
    chain: Chain,
    task: BroadcastTask,
    receipt: dict,
) -> MatchedTransferFact | None:
    if task.crypto == chain.native_coin:
        return _native_task_fact(chain=chain, task=task)
    return _erc20_task_fact(chain=chain, task=task, receipt=receipt)


def _native_task_fact(*, chain: Chain, task: BroadcastTask) -> MatchedTransferFact:
    decimals = chain.native_coin.get_decimals(chain)
    expected_value = Decimal(task.amount).scaleb(decimals)
    return MatchedTransferFact(
        event_id="native:tx",
        from_address=Web3.to_checksum_address(task.address.address),
        to_address=Web3.to_checksum_address(task.recipient),
        crypto=chain.native_coin,
        value=expected_value,
        amount=task.amount,
    )


def _erc20_task_fact(
    *,
    chain: Chain,
    task: BroadcastTask,
    receipt: dict,
) -> MatchedTransferFact | None:
    decimals = task.crypto.get_decimals(chain)
    expected_value = Decimal(task.amount).scaleb(decimals)
    token_addr = task.crypto.address(chain)
    if not token_addr:
        return None

    matches = [
        log
        for log in receipt.get("logs") or []
        if matches_transfer_log(
            log,
            token=token_addr,
            from_address=task.address.address,
            to_address=task.recipient,
            value=expected_value,
        )
    ]
    if len(matches) != 1:
        return None

    log = matches[0]
    return MatchedTransferFact(
        event_id=f"erc20:{normalize_log_index(log.get('logIndex'))}",
        from_address=Web3.to_checksum_address(task.address.address),
        to_address=Web3.to_checksum_address(task.recipient),
        crypto=task.crypto,
        value=expected_value,
        amount=task.amount,
    )


@dataclass
class WithdrawalHandler:
    def match(self, transfer: OnchainTransfer, broadcast_task: BroadcastTask) -> bool:
        from withdrawals.service import WithdrawalService

        return WithdrawalService.try_match_withdrawal(transfer, broadcast_task)

    def confirm(self, transfer: OnchainTransfer) -> None:
        from withdrawals.service import WithdrawalService

        WithdrawalService.confirm_withdrawal(transfer)

    def drop(self, transfer: OnchainTransfer) -> None:
        from withdrawals.service import WithdrawalService

        WithdrawalService.drop_withdrawal(transfer)

    def finalize_failed(
        self,
        broadcast_task: BroadcastTask,
        reason: BroadcastTaskFailureReason,
    ) -> None:
        from withdrawals.service import WithdrawalService

        WithdrawalService.fail_withdrawal(broadcast_task=broadcast_task)


withdrawal_handler = WithdrawalHandler()

