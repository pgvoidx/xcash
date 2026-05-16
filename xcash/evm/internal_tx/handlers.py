from __future__ import annotations

from typing import Protocol

from chains.models import (
    BroadcastTask,
    BroadcastTaskFailureReason,
    OnchainTransfer,
    TransferType,
)


class InternalTransferHandler(Protocol):
    """按 TransferType 推进系统内交易的业务生命周期。"""

    def match(self, transfer: OnchainTransfer, broadcast_task: BroadcastTask) -> bool: ...

    def confirm(self, transfer: OnchainTransfer) -> None: ...

    def drop(self, transfer: OnchainTransfer) -> None: ...

    def finalize_failed(
        self,
        broadcast_task: BroadcastTask,
        reason: BroadcastTaskFailureReason,
    ) -> None: ...


HANDLERS: dict[TransferType, InternalTransferHandler] = {}


def get_handler(transfer_type: TransferType) -> InternalTransferHandler:
    return HANDLERS[transfer_type]


from evm.internal_tx.deposit_collection import deposit_collection_handler  # noqa: E402
from evm.internal_tx.create2 import contract_deploy_collection_handler  # noqa: E402
from evm.internal_tx.gas_recharge import gas_recharge_handler  # noqa: E402
from evm.internal_tx.withdrawal import withdrawal_handler  # noqa: E402
from evm.internal_tx.x402 import x402_handler  # noqa: E402

HANDLERS[TransferType.Withdrawal] = withdrawal_handler
HANDLERS[TransferType.GasRecharge] = gas_recharge_handler
HANDLERS[TransferType.DepositCollection] = deposit_collection_handler
HANDLERS[TransferType.X402Facilitate] = x402_handler
HANDLERS[TransferType.ContractDeployCollect] = contract_deploy_collection_handler
