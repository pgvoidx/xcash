from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from chains.models import (
    BroadcastTask,
    BroadcastTaskFailureReason,
    Chain,
    OnchainTransfer,
)
from django.utils import timezone
from evm.internal_tx.facts import MatchedTransferFact
from web3 import Web3


def gas_recharge_matcher(
    *,
    chain: Chain,
    broadcast_task: BroadcastTask,
    receipt: dict,
) -> MatchedTransferFact | None:
    decimals = chain.native_coin.get_decimals(chain)
    expected_value = Decimal(broadcast_task.amount).scaleb(decimals)
    return MatchedTransferFact(
        event_id="native:tx",
        from_address=Web3.to_checksum_address(broadcast_task.address.address),
        to_address=Web3.to_checksum_address(broadcast_task.recipient),
        crypto=chain.native_coin,
        value=expected_value,
        amount=broadcast_task.amount,
    )


@dataclass
class GasRechargeHandler:
    def match(self, transfer: OnchainTransfer, broadcast_task: BroadcastTask) -> bool:
        from deposits.service import DepositService

        return DepositService.try_match_gas_recharge(transfer, broadcast_task)

    def confirm(self, transfer: OnchainTransfer) -> None:
        from deposits.models import GasRecharge

        GasRecharge.objects.filter(transfer=transfer).update(recharged_at=timezone.now())

    def drop(self, transfer: OnchainTransfer) -> None:
        return None

    def finalize_failed(
        self,
        broadcast_task: BroadcastTask,
        reason: BroadcastTaskFailureReason,
    ) -> None:
        return None


gas_recharge_handler = GasRechargeHandler()

