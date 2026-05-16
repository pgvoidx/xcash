from __future__ import annotations

from typing import Protocol

from chains.models import BroadcastTask, Chain, TransferType
from evm.internal_tx.facts import MatchedTransferFact


class ReceiptMatcher(Protocol):
    """从 receipt 中提取与 BroadcastTask 预期吻合的真实资产移动事实。"""

    def __call__(
        self,
        *,
        chain: Chain,
        broadcast_task: BroadcastTask,
        receipt: dict,
    ) -> MatchedTransferFact | None: ...


MATCHERS: dict[TransferType, ReceiptMatcher] = {}


def get_matcher(transfer_type: TransferType) -> ReceiptMatcher:
    return MATCHERS[transfer_type]


from evm.internal_tx.deposit_collection import deposit_collection_matcher  # noqa: E402
from evm.internal_tx.create2 import create2_matcher  # noqa: E402
from evm.internal_tx.gas_recharge import gas_recharge_matcher  # noqa: E402
from evm.internal_tx.withdrawal import withdrawal_matcher  # noqa: E402
from evm.internal_tx.x402 import x402_matcher  # noqa: E402

MATCHERS[TransferType.Withdrawal] = withdrawal_matcher
MATCHERS[TransferType.GasRecharge] = gas_recharge_matcher
MATCHERS[TransferType.DepositCollection] = deposit_collection_matcher
MATCHERS[TransferType.X402Facilitate] = x402_matcher
MATCHERS[TransferType.ContractDeployCollect] = create2_matcher
