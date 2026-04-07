from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import IntegrityError
from django.db import models
from django.db import transaction as db_transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from bitcoin.rpc import BitcoinRpcClient
from bitcoin.rpc import BitcoinRpcError
from bitcoin.utils import btc_to_satoshi
from bitcoin.utils import ensure_bitcoin_native_currency
from bitcoin.utils import is_replaceable_signed_transaction
from bitcoin.utils import sat_per_byte_from_btc_per_kb
from bitcoin.utils import select_utxos_for_amount
from bitcoin.utils import select_utxos_for_sweep
from chains.models import AddressChainState
from chains.models import BroadcastTask
from chains.models import BroadcastTaskFailureReason
from chains.models import BroadcastTaskResult
from chains.models import BroadcastTaskStage
from chains.models import TransferType
from chains.signer import get_signer_backend
from common.models import UndeletableModel
from common.utils.bitcoin import classify_bitcoin_address

if TYPE_CHECKING:
    from collections.abc import Callable
    from decimal import Decimal

    from bitcoin.rpc import BitcoinUtxo
    from chains.models import Address
    from chains.models import Chain
    from currencies.models import Crypto


class BitcoinScanCursor(models.Model):
    """记录 Bitcoin 链扫描推进位置与最近错误。

    设计原则：
    - 每条 Bitcoin 链只保留一个收款扫描游标，直接按链维度持久化。
    - last_scanned_block 记录主扫描面已经推进到的最高块高。
    - last_safe_block 记录当前安全块高，便于后台观察追平程度。
    """

    chain = models.OneToOneField(
        "chains.Chain",
        on_delete=models.CASCADE,
        related_name="bitcoin_scan_cursor",
        verbose_name=_("链"),
    )
    last_scanned_block = models.PositiveIntegerField(_("已扫描到的区块"), default=0)
    last_safe_block = models.PositiveIntegerField(_("安全区块"), default=0)
    enabled = models.BooleanField(_("启用"), default=True)
    last_error = models.CharField(_("最近错误"), max_length=255, blank=True, default="")
    last_error_at = models.DateTimeField(_("最近错误时间"), blank=True, null=True)
    updated_at = models.DateTimeField(_("更新时间"), auto_now=True)
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)

    class Meta:
        ordering = ("chain_id",)
        verbose_name = _("Bitcoin 扫描游标")
        verbose_name_plural = verbose_name

    def __str__(self) -> str:
        return self.chain.code


class BitcoinBroadcastTask(UndeletableModel):
    """Bitcoin 链上任务：先签名入库，再异步广播。

    设计思路：
    - Bitcoin 使用 UTXO 模型：签名时必须先选出一组输入 UTXO。
    - AddressChainState 行锁防止并发签名消耗相同 UTXO（double-spend）。
    - 签名后 txid 即确定，可先写库，再在事务提交后异步广播。
    - signed_payload 保存已签名链上载荷，广播失败时可无限重试。
    """

    # base_task 是跨链统一锚点；Bitcoin 子表继续保存 UTXO 交易构造所需的链特有字段。
    base_task = models.OneToOneField(
        "chains.BroadcastTask",
        on_delete=models.CASCADE,
        related_name="bitcoin_task",
        verbose_name=_("通用链上任务"),
        blank=True,
        null=True,
    )
    address = models.ForeignKey(
        "chains.Address",
        on_delete=models.PROTECT,
        verbose_name=_("地址"),
    )
    chain = models.ForeignKey(
        "chains.Chain",
        on_delete=models.PROTECT,
        verbose_name=_("网络"),
    )
    # 统一按"已签名链上载荷"建模，避免把广播载荷误写成任务对象。
    signed_payload = models.TextField(_("已签名链上载荷"))
    fee_satoshi = models.PositiveIntegerField(_("矿工费（satoshi）"), default=0)
    last_attempt_at = models.DateTimeField(_("上次尝试时间"), blank=True, null=True)
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)

    class Meta:
        ordering = ("created_at",)
        verbose_name = _("Bitcoin 链上任务")
        verbose_name_plural = verbose_name

    def __str__(self) -> str:
        return self.base_task.tx_hash if self.base_task_id else str(self.pk)

    @property
    def status(self) -> str:
        if self.base_task_id:
            return self.base_task.display_status
        return "待执行"

    def broadcast(self) -> None:
        """向 Bitcoin 节点广播已签名链上载荷。

        Bitcoin 广播幂等：同一笔签名载荷重复广播时，节点可能返回
        already-in-mempool / already-known / already in block chain，均视为成功。
        """
        client = BitcoinRpcClient(self.chain.rpc)

        self.last_attempt_at = timezone.now()
        self.save(update_fields=["last_attempt_at"])

        try:
            returned_txid = client.send_raw_transaction(self.signed_payload)
        except BitcoinRpcError as exc:
            msg = str(exc).lower()
            if (
                "already in block chain" in msg
                or "already-in-mempool" in msg
                or "txn-already-known" in msg
            ):
                returned_txid = self.base_task.tx_hash
            elif "txn-mempool-conflict" in msg or "missingorspent" in msg:
                if self._should_ignore_conflict_failure():
                    return
                # UTXO 已被其他交易占用时，任务应明确失败并释放预留，避免进入无限重试。
                self._finalize_failure(BroadcastTaskFailureReason.DOUBLE_SPEND)
                return
            else:
                raise

        if returned_txid != self.base_task.tx_hash:
            msg = (
                "Bitcoin 广播 txid 不一致: "
                f"expected={self.base_task.tx_hash}, got={returned_txid}"
            )
            raise RuntimeError(msg)
        if self.base_task_id:
            # Bitcoin 广播成功后，统一父任务进入"待上链"等待节点真正出块。
            BroadcastTask.objects.filter(
                pk=self.base_task_id,
                stage=BroadcastTaskStage.QUEUED,
                result=BroadcastTaskResult.UNKNOWN,
            ).update(
                stage=BroadcastTaskStage.PENDING_CHAIN,
                updated_at=timezone.now(),
            )

    def _finalize_failure(self, reason: BroadcastTaskFailureReason | str) -> None:
        """把任务收口为失败终局，并释放该任务占用的 UTXO 预留。"""
        if not self.base_task_id:
            return

        BroadcastTask.objects.filter(pk=self.base_task_id).update(
            stage=BroadcastTaskStage.FINALIZED,
            result=BroadcastTaskResult.FAILED,
            failure_reason=reason,
            updated_at=timezone.now(),
        )
        BitcoinReservedUtxo.release_for_broadcast_task(self.base_task_id)

        if self.base_task.transfer_type == TransferType.Withdrawal:
            from withdrawals.service import WithdrawalService

            WithdrawalService.fail_withdrawal(broadcast_task=self.base_task)
        elif self.base_task.transfer_type == TransferType.DepositCollection:
            from deposits.models import DepositCollection
            from deposits.service import DepositService

            collection = DepositCollection.objects.filter(
                broadcast_task=self.base_task
            ).first()
            if collection is None and self.base_task.tx_hash:
                collection = DepositCollection.objects.filter(
                    collection_hash=self.base_task.tx_hash
                ).first()
            if collection is not None:
                DepositService.drop_collection(collection)

    @staticmethod
    def _raise_invalid_transfer(message: str) -> None:
        raise ValueError(message)

    def _should_ignore_conflict_failure(self) -> bool:
        """并发提费后，旧 worker 再广播旧 payload 不应把当前任务误判成失败。"""
        fresh_task = (
            type(self)
            .objects.select_related("base_task")
            .filter(pk=self.pk)
            .first()
        )
        if fresh_task is None:
            return True
        if fresh_task.signed_payload != self.signed_payload:
            return True
        if (
            fresh_task.base_task_id
            and self.base_task_id
            and fresh_task.base_task.tx_hash != self.base_task.tx_hash
        ):
            return True
        if (
            fresh_task.base_task_id
            and fresh_task.base_task.result != BroadcastTaskResult.UNKNOWN
        ):
            return True
        return False

    @property
    def is_replaceable(self) -> bool:
        return is_replaceable_signed_transaction(self.signed_payload)

    def load_reserved_utxos(self, *, client: BitcoinRpcClient) -> list[BitcoinUtxo]:
        """根据数据库里的预留输入重建 signer 需要的 UTXO 明细。"""
        if not self.base_task_id:
            return []

        reservations = list(
            BitcoinReservedUtxo.objects.filter(
                broadcast_task_id=self.base_task_id,
                released_at__isnull=True,
            ).order_by("created_at", "pk")
        )
        utxos: list[BitcoinUtxo] = []
        for reservation in reservations:
            raw_tx = client.get_raw_transaction(reservation.txid)
            if raw_tx is None:
                raise ValueError(f"无法加载预留 UTXO 的前序交易: {reservation.txid}")

            matched_output = None
            for output in raw_tx.get("vout", []) or []:
                if int(output.get("n", -1)) == reservation.vout:
                    matched_output = output
                    break
            if matched_output is None:
                raise ValueError(
                    f"预留 UTXO 在前序交易中不存在: {reservation.txid}:{reservation.vout}"
                )

            script_pub_key = matched_output.get("scriptPubKey", {}) or {}
            script_hex = (
                script_pub_key.get("hex")
                if isinstance(script_pub_key, dict)
                else None
            )
            if not script_hex:
                raise ValueError(
                    f"预留 UTXO 缺少 scriptPubKey.hex: {reservation.txid}:{reservation.vout}"
                )

            utxos.append(
                {
                    "txid": reservation.txid,
                    "vout": reservation.vout,
                    "amount": matched_output.get("value", "0"),
                    "confirmations": int(raw_tx.get("confirmations", 0) or 0),
                    "scriptPubKey": str(script_hex),
                }
            )
        return utxos

    @classmethod
    def schedule_transfer(
        cls,
        *,
        address: Address,
        chain: Chain,
        crypto: Crypto,
        to: str,
        amount: Decimal,
        transfer_type: TransferType,
        verify_fn: Callable[[], None] | None = None,
        sweep: bool = False,
    ) -> BitcoinBroadcastTask:
        """构建并签名 Bitcoin SegWit (P2WPKH) 交易，原子写入 DB。

        内部地址统一为 Native SegWit，外部目标地址可为任意类型 (P2PKH/P2SH/P2WPKH)。
        估费时根据目标地址类型动态计算输出体积，避免广播时因 fee 不足失败。
        """
        ensure_bitcoin_native_currency(chain=chain, crypto=crypto)

        with db_transaction.atomic():
            AddressChainState.acquire_for_update(address=address, chain=chain)

            if verify_fn is not None:
                verify_fn()

            client = BitcoinRpcClient(chain.rpc)

            # 先尝试钱包视角的 listunspent；descriptor 私钥钱包不支持 watch-only 时，
            # 再回退到全节点 UTXO 集扫描，避免本地联调和外部节点因钱包能力差异而失效。
            raw_utxos = client.list_unspent(str(address.address))
            if not raw_utxos:
                raw_utxos = client.scan_unspent(str(address.address))
            raw_utxos = BitcoinReservedUtxo.exclude_reserved(
                chain=chain,
                raw_utxos=raw_utxos,
            )
            if not raw_utxos:
                msg = (
                    f"Bitcoin 地址 {address.address} 无可用未预留 UTXO，"
                    "请检查该地址是否已收到确认资金或稍后重试"
                )
                cls._raise_invalid_transfer(msg)

            fee_rate_sat_per_byte = sat_per_byte_from_btc_per_kb(
                client.estimate_smart_fee()
            )
            if sweep:
                # sweep 直接基于当前全部可用 UTXO 计算净额，避免归集时先猜金额再被实际手续费打回。
                target_address_type = classify_bitcoin_address(to)
                selected_utxos, amount_satoshi, fee_satoshi = select_utxos_for_sweep(
                    utxos=raw_utxos,
                    fee_rate_sat_per_byte=fee_rate_sat_per_byte,
                    target_address_type=target_address_type,
                )
                amount = Decimal(amount_satoshi).scaleb(-8)
            else:
                amount_satoshi = btc_to_satoshi(amount)
                if amount_satoshi <= 0:
                    msg = "Bitcoin 转账金额必须大于 0"
                    cls._raise_invalid_transfer(msg)

                # 核心业务逻辑：
                # 1. 先从节点返回的 UTXO 中挑出一组输入；
                # 2. 按输入数保守估算 2 输出（收款 + 找零）的手续费；
                # 3. 再把同一组输入交给 bit 构建交易，避免"估费与选币不一致"。
                target_address_type = classify_bitcoin_address(to)
                selected_utxos, fee_satoshi = select_utxos_for_amount(
                    utxos=raw_utxos,
                    amount_satoshi=amount_satoshi,
                    fee_rate_sat_per_byte=fee_rate_sat_per_byte,
                    target_address_type=target_address_type,
                )

            signer_result = get_signer_backend().sign_bitcoin_transaction(
                address=address,
                chain=chain,
                source_address=address.address,
                to=to,
                amount_satoshi=amount_satoshi,
                fee_satoshi=fee_satoshi,
                replaceable=transfer_type == TransferType.Withdrawal,
                utxos=selected_utxos,
            )

            base_task = BroadcastTask.objects.create(
                chain=chain,
                address=address,
                transfer_type=transfer_type,
                crypto=crypto,
                recipient=to,
                amount=amount,
                tx_hash=signer_result.txid,
                stage=BroadcastTaskStage.QUEUED,
                result=BroadcastTaskResult.UNKNOWN,
            )
            task = cls.objects.create(
                base_task=base_task,
                address=address,
                chain=chain,
                signed_payload=signer_result.signed_payload,
                fee_satoshi=fee_satoshi,
            )
            BitcoinReservedUtxo.reserve_many(
                chain=chain,
                address=address,
                broadcast_task=base_task,
                raw_utxos=selected_utxos,
            )
            return task


class BitcoinReservedUtxo(models.Model):
    """记录某笔 Bitcoin 链上任务已占用的 UTXO，防止并发双花签名。"""

    chain = models.ForeignKey(
        "chains.Chain",
        on_delete=models.CASCADE,
        related_name="reserved_bitcoin_utxos",
        verbose_name=_("链"),
    )
    address = models.ForeignKey(
        "chains.Address",
        on_delete=models.CASCADE,
        related_name="reserved_bitcoin_utxos",
        verbose_name=_("地址"),
    )
    broadcast_task = models.ForeignKey(
        "chains.BroadcastTask",
        on_delete=models.CASCADE,
        related_name="reserved_utxos",
        verbose_name=_("链上任务"),
    )
    txid = models.CharField(_("UTXO 交易哈希"), max_length=64)
    vout = models.PositiveIntegerField(_("UTXO 输出序号"))
    released_at = models.DateTimeField(_("释放时间"), blank=True, null=True)
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)

    class Meta:
        ordering = ("created_at", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("chain", "txid", "vout"),
                condition=models.Q(released_at__isnull=True),
                name="uniq_bitcoin_reserved_utxo_active",
            ),
        ]
        verbose_name = _("Bitcoin 预留 UTXO")
        verbose_name_plural = verbose_name

    def __str__(self) -> str:
        return f"{self.chain_id}:{self.txid}:{self.vout}"

    @classmethod
    def exclude_reserved(
        cls,
        *,
        chain,
        raw_utxos: list[BitcoinUtxo],
    ) -> list[BitcoinUtxo]:
        """从节点返回的 UTXO 集中剔除仍被进行中任务占用的输入。"""
        if not raw_utxos:
            return []

        candidate_keys = {
            (str(utxo["txid"]), int(utxo["vout"]))
            for utxo in raw_utxos
            if utxo.get("txid") is not None and utxo.get("vout") is not None
        }
        reserved_keys = set(
            cls.objects.filter(
                chain=chain,
                released_at__isnull=True,
                txid__in=[txid for txid, _ in candidate_keys],
                vout__in=[vout for _, vout in candidate_keys],
            ).values_list("txid", "vout")
        )
        return [
            utxo
            for utxo in raw_utxos
            if (str(utxo["txid"]), int(utxo["vout"])) not in reserved_keys
        ]

    @classmethod
    def reserve_many(
        cls,
        *,
        chain,
        address,
        broadcast_task,
        raw_utxos: list[BitcoinUtxo],
    ) -> None:
        """把已选中的输入立即预留到数据库，防止广播前再次被系统消费。"""
        reservations = [
            cls(
                chain=chain,
                address=address,
                broadcast_task=broadcast_task,
                txid=str(utxo["txid"]),
                vout=int(utxo["vout"]),
            )
            for utxo in raw_utxos
        ]
        try:
            cls.objects.bulk_create(reservations)
        except IntegrityError as exc:
            message = "Bitcoin UTXO 已被其他任务占用，请稍后重试"
            raise ValueError(message) from exc

    @classmethod
    def release_for_broadcast_task(cls, broadcast_task_id: int) -> None:
        """在任务进入终局后释放该任务占用的全部 UTXO 预留。"""
        cls.objects.filter(
            broadcast_task_id=broadcast_task_id,
            released_at__isnull=True,
        ).update(released_at=timezone.now())

    @classmethod
    def release_for_broadcast_task_id_by_hash(
        cls,
        *,
        chain_id: int,
        tx_hash: str,
    ) -> None:
        """通过统一链上任务哈希释放预留，供 Transfer.confirm 集中收口。"""
        broadcast_task_id = (
            BroadcastTask.objects.filter(chain_id=chain_id, tx_hash=tx_hash)
            .values_list("pk", flat=True)
            .first()
        )
        if broadcast_task_id is None:
            return
        cls.release_for_broadcast_task(broadcast_task_id)
