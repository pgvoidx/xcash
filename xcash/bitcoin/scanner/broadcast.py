from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from django.utils import timezone

from bitcoin.models import BitcoinBroadcastTask
from bitcoin.rpc import BitcoinRpcClient
from bitcoin.rpc import BitcoinRpcError
from bitcoin.rpc import BitcoinTxInfo
from bitcoin.rpc import BitcoinTxVout
from bitcoin.utils import btc_to_satoshi
from chains.models import BroadcastTaskResult
from chains.models import BroadcastTaskStage
from chains.models import Chain
from chains.service import ObservedTransferPayload
from chains.service import TransferService


class BitcoinBroadcastTransferObserver:
    """为已知的内部 BTC 链上任务补录出账 OnchainTransfer。"""

    @classmethod
    def observe_chain(cls, *, chain: Chain) -> int:
        client = BitcoinRpcClient(chain.rpc)
        block_cache: dict[str, dict] = {}
        created_count = 0

        queryset = BitcoinBroadcastTask.objects.select_related(
            "address",
            "base_task",
        ).prefetch_related("base_task__tx_hashes").filter(
            chain=chain,
            base_task__result=BroadcastTaskResult.UNKNOWN,
            base_task__stage__in=(
                BroadcastTaskStage.PENDING_CHAIN,
                BroadcastTaskStage.PENDING_CONFIRM,
            ),
            base_task__recipient__isnull=False,
            base_task__amount__isnull=False,
        )

        for task in queryset:
            block = None
            tx = None
            for tx_hash in cls._candidate_tx_hashes(task=task):
                block, tx = cls._load_mined_transaction(
                    client=client,
                    tx_hash=tx_hash,
                    block_cache=block_cache,
                )
                if block is not None and tx is not None:
                    break
            if block is None or tx is None:
                continue

            matched_output = cls._find_matching_output(
                tx=tx,
                recipient=str(task.base_task.recipient),
                amount=Decimal(task.base_task.amount),
            )
            if matched_output is None:
                continue

            occurred_ts = int(tx.get("blocktime") or block.get("time") or 0)
            occurred_at = datetime.fromtimestamp(
                occurred_ts,
                tz=timezone.get_current_timezone(),
            )
            result = TransferService.create_observed_transfer(
                observed=ObservedTransferPayload(
                    chain=chain,
                    block=int(block.get("height", 0)),
                    tx_hash=str(tx.get("txid", "") or task.base_task.tx_hash).lower(),
                    event_id=f"vout:{int(matched_output.get('n', 0))}",
                    from_address=task.address.address,
                    to_address=str(task.base_task.recipient),
                    crypto=task.base_task.crypto or chain.native_coin,
                    value=Decimal(btc_to_satoshi(task.base_task.amount)),
                    amount=Decimal(task.base_task.amount),
                    timestamp=occurred_ts,
                    occurred_at=occurred_at,
                    source="bitcoin-broadcast-observer",
                )
            )
            if result.created:
                created_count += 1

        return created_count

    @staticmethod
    def _candidate_tx_hashes(*, task: BitcoinBroadcastTask) -> list[str]:
        hashes = list(task.base_task.tx_hashes.order_by("version").values_list("hash", flat=True))
        current_hash = str(task.base_task.tx_hash or "")
        if current_hash and current_hash not in hashes:
            hashes.append(current_hash)
        return [str(tx_hash).lower() for tx_hash in hashes if tx_hash]

    @classmethod
    def _load_mined_transaction(
        cls,
        *,
        client: BitcoinRpcClient,
        tx_hash: str,
        block_cache: dict[str, dict],
    ) -> tuple[dict | None, BitcoinTxInfo | None]:
        if not tx_hash:
            return None, None

        try:
            wallet_tx = client.get_transaction(tx_hash)
        except BitcoinRpcError:
            wallet_tx = None
        block_hash = wallet_tx.get("blockhash") if wallet_tx else None
        if block_hash:
            block = cls._get_block(
                client=client,
                block_hash=str(block_hash),
                block_cache=block_cache,
            )
            if block is not None:
                for block_tx in block.get("tx", []) or []:
                    if str(block_tx.get("txid", "")).lower() == str(tx_hash).lower():
                        return block, block_tx

        raw_tx = client.get_raw_transaction(tx_hash)
        if raw_tx is None:
            return None, None

        block_hash = raw_tx.get("blockhash")
        if not block_hash:
            return None, None
        block = cls._get_block(
            client=client,
            block_hash=str(block_hash),
            block_cache=block_cache,
        )
        return block, raw_tx

    @staticmethod
    def _get_block(
        *,
        client: BitcoinRpcClient,
        block_hash: str,
        block_cache: dict[str, dict],
    ) -> dict | None:
        cached = block_cache.get(block_hash)
        if cached is not None:
            return cached
        block = client.get_block(block_hash)
        block_cache[block_hash] = block
        return block

    @classmethod
    def _find_matching_output(
        cls,
        *,
        tx: BitcoinTxInfo,
        recipient: str,
        amount: Decimal,
    ) -> BitcoinTxVout | None:
        for output in tx.get("vout", []) or []:
            if cls._extract_output_address(output) != recipient:
                continue
            if Decimal(str(output.get("value", "0"))) != amount:
                continue
            return output
        return None

    @staticmethod
    def _extract_output_address(output: BitcoinTxVout) -> str | None:
        script_pub_key = output.get("scriptPubKey", {}) or {}
        address = script_pub_key.get("address")
        if address:
            return str(address)

        addresses = script_pub_key.get("addresses") or []
        if addresses:
            return str(addresses[0])

        return None
