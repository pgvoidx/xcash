from __future__ import annotations

from decimal import Decimal

from django.db import transaction as db_transaction
from django.utils import timezone

from bitcoin.models import BitcoinBroadcastTask
from bitcoin.rpc import BitcoinRpcClient
from bitcoin.rpc import BitcoinRpcError
from bitcoin.utils import btc_to_satoshi
from bitcoin.utils import estimate_p2pkh_tx_vbytes
from chains.models import AddressChainState
from chains.models import BroadcastTaskResult
from chains.models import BroadcastTaskStage
from chains.models import TransferType
from chains.signer import get_signer_backend
from users.otp import validate_admin_sensitive_action_context
from withdrawals.models import Withdrawal
from withdrawals.models import WithdrawalStatus


class BitcoinFeeBumpService:
    """只为 BTC 提现提供人工 RBF 提费重发。"""

    AMBIGUOUS_BROADCAST_ERROR_MARKERS = (
        "txn-mempool-conflict",
        "missingorspent",
    )
    MIN_INCREMENTAL_RELAY_FEE_SAT_PER_VBYTE = 1

    @classmethod
    @db_transaction.atomic
    def bump_withdrawal(
        cls,
        *,
        withdrawal_id: int,
        approval_context: dict[str, object] | None,
    ) -> BitcoinBroadcastTask:
        validate_admin_sensitive_action_context(context=approval_context)
        Withdrawal.objects.select_for_update().get(pk=withdrawal_id)
        withdrawal = Withdrawal.objects.select_related(
            "chain",
            "crypto",
            "transfer",
            "broadcast_task__chain",
            "broadcast_task__address",
            "broadcast_task__bitcoin_task",
        ).get(pk=withdrawal_id)
        cls._validate_withdrawal(withdrawal=withdrawal)

        base_task = withdrawal.broadcast_task
        bitcoin_task = base_task.bitcoin_task
        AddressChainState.acquire_for_update(
            address=bitcoin_task.address,
            chain=bitcoin_task.chain,
        )

        client = BitcoinRpcClient(bitcoin_task.chain.rpc)
        cls._assert_not_confirmed(client=client, task=bitcoin_task)
        if not bitcoin_task.is_replaceable:
            raise ValueError("当前 BTC 提现不是 replaceable 交易，无法执行 RBF 提费重发")

        reserved_utxos = bitcoin_task.load_reserved_utxos(client=client)
        if not reserved_utxos:
            raise ValueError("当前 BTC 提现缺少已预留 UTXO，无法执行提费重发")

        new_fee_satoshi = cls._estimate_replacement_fee(
            input_count=len(reserved_utxos),
            old_fee_satoshi=bitcoin_task.fee_satoshi,
            fee_rate_btc_per_kb=client.estimate_smart_fee(),
        )
        amount_satoshi = btc_to_satoshi(withdrawal.amount)
        total_input_satoshi = sum(
            btc_to_satoshi(utxo["amount"]) for utxo in reserved_utxos
        )
        if total_input_satoshi < amount_satoshi + new_fee_satoshi:
            raise ValueError("当前预留 UTXO 余额不足以支撑更高手续费的 RBF 替换")

        signer_result = get_signer_backend().sign_bitcoin_transaction(
            address=bitcoin_task.address,
            chain=bitcoin_task.chain,
            source_address=bitcoin_task.address.address,
            to=str(base_task.recipient),
            amount_satoshi=amount_satoshi,
            fee_satoshi=new_fee_satoshi,
            replaceable=True,
            utxos=reserved_utxos,
        )
        current_hash = str(base_task.tx_hash or "").lower()
        new_hash = str(signer_result.txid).lower()
        if not new_hash:
            raise ValueError("Bitcoin signer 未返回新的交易哈希")
        if new_hash == current_hash:
            raise ValueError("Bitcoin 提费重签未生成新的交易哈希，拒绝继续广播")

        attempted_at = timezone.now()
        try:
            returned_txid = client.send_raw_transaction(signer_result.signed_payload)
        except BitcoinRpcError as exc:
            BitcoinBroadcastTask.objects.filter(pk=bitcoin_task.pk).update(
                last_attempt_at=attempted_at
            )
            error_message = str(exc)
            if any(
                marker in error_message.lower()
                for marker in cls.AMBIGUOUS_BROADCAST_ERROR_MARKERS
            ):
                raise ValueError(
                    "Bitcoin 提费重发返回不确定结果，请先检查节点/mempool 状态后再决定是否重试: "
                    f"{error_message}"
                ) from exc
            raise

        if str(returned_txid).lower() != new_hash:
            raise RuntimeError(
                "Bitcoin 提费重发返回 txid 不一致: "
                f"expected={new_hash}, got={returned_txid}"
            )

        base_task.create_initial_tx_hash()
        base_task.append_tx_hash(new_hash)
        BitcoinBroadcastTask.objects.filter(pk=bitcoin_task.pk).update(
            signed_payload=signer_result.signed_payload,
            fee_satoshi=new_fee_satoshi,
            last_attempt_at=attempted_at,
        )
        bitcoin_task.signed_payload = signer_result.signed_payload
        bitcoin_task.fee_satoshi = new_fee_satoshi
        bitcoin_task.last_attempt_at = attempted_at
        return bitcoin_task

    @staticmethod
    def _validate_withdrawal(*, withdrawal: Withdrawal) -> None:
        if withdrawal.chain_id is None or withdrawal.chain.type != "btc":
            raise ValueError("仅支持对 BTC 提现执行人工提费重发")
        if withdrawal.status != WithdrawalStatus.PENDING:
            raise ValueError("仅待执行状态的 BTC 提现允许人工提费重发")
        if withdrawal.transfer_id is not None:
            raise ValueError("当前 BTC 提现已命中链上转账，禁止继续提费重发")
        if withdrawal.broadcast_task_id is None:
            raise ValueError("当前 BTC 提现缺少链上任务，无法执行提费重发")

        base_task = withdrawal.broadcast_task
        if base_task.transfer_type != TransferType.Withdrawal:
            raise ValueError("当前链上任务不是提现任务，拒绝执行 BTC 提费重发")
        if base_task.stage != BroadcastTaskStage.PENDING_CHAIN:
            raise ValueError("仅待上链阶段的 BTC 提现允许人工提费重发")
        if base_task.result != BroadcastTaskResult.UNKNOWN:
            raise ValueError("仅未终局的 BTC 提现允许人工提费重发")
        if not hasattr(base_task, "bitcoin_task"):
            raise ValueError("当前链上任务不是 BTC 任务，拒绝执行提费重发")

    @classmethod
    def _estimate_replacement_fee(
        cls,
        *,
        input_count: int,
        old_fee_satoshi: int,
        fee_rate_btc_per_kb: Decimal,
    ) -> int:
        from bitcoin.utils import sat_per_byte_from_btc_per_kb

        tx_vbytes = estimate_p2pkh_tx_vbytes(input_count=input_count, output_count=2)
        current_target_fee = (
            tx_vbytes * sat_per_byte_from_btc_per_kb(fee_rate_btc_per_kb)
        )
        minimum_replacement_fee = (
            old_fee_satoshi
            + tx_vbytes * cls.MIN_INCREMENTAL_RELAY_FEE_SAT_PER_VBYTE
        )
        return max(current_target_fee, minimum_replacement_fee)

    @staticmethod
    def _assert_not_confirmed(
        *,
        client: BitcoinRpcClient,
        task: BitcoinBroadcastTask,
    ) -> None:
        known_hashes = list(
            task.base_task.tx_hashes.order_by("version").values_list("hash", flat=True)
        )
        if task.base_task.tx_hash and task.base_task.tx_hash not in known_hashes:
            known_hashes.append(task.base_task.tx_hash)

        for tx_hash in known_hashes:
            tx_info = client.get_raw_transaction(str(tx_hash))
            if tx_info is None:
                continue
            if tx_info.get("blockhash") or int(tx_info.get("confirmations", 0) or 0) > 0:
                raise ValueError("当前 BTC 提现已进入区块确认流程，不能再执行人工提费重发")
