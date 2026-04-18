from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import structlog
from django.db import transaction as db_transaction
from django.utils import timezone

logger = structlog.get_logger()

from chains.adapters import AdapterFactory
from chains.models import AddressUsage
from chains.models import ChainType
from chains.models import OnchainTransfer
from chains.models import TransferType
from common.utils.math import format_decimal_stripped
from deposits.exceptions import DepositStatusError
from deposits.models import Deposit
from deposits.models import DepositAddress
from deposits.models import DepositCollection
from deposits.models import DepositStatus
from deposits.models import GasRecharge
from projects.models import RecipientAddressUsage
from projects.models import RecipientAddress
from common.internal_callback import send_internal_callback
from webhooks.service import WebhookService


class DepositService:
    """High level orchestration around deposit lifecycle and collection."""

    @staticmethod
    def build_webhook_payload(
        deposit: Deposit, *, confirmed: bool | None = None
    ) -> dict:
        """统一构造 deposit webhook payload，避免业务层各自拼装。"""
        if confirmed is None:
            confirmed = deposit.status == DepositStatus.COMPLETED

        customer = getattr(deposit, "customer", None)
        return {
            "type": "deposit",
            "data": {
                "sys_no": deposit.sys_no,
                "uid": customer.uid if customer else None,
                "chain": deposit.transfer.chain.code,
                "block": deposit.transfer.block,
                "hash": deposit.transfer.hash,
                "crypto": deposit.transfer.crypto.symbol,
                "amount": format_decimal_stripped(deposit.transfer.amount),
                "confirmed": confirmed,
            },
        }

    @staticmethod
    def refresh_worth(deposit: Deposit) -> None:
        """显式计算 Deposit worth，避免继续依赖 post_save signal。"""
        try:
            worth = deposit.transfer.crypto.usd_amount(deposit.transfer.amount)
        except Exception:
            logger.exception(
                "calculate_worth 失败，worth 保持默认值 0", deposit_id=deposit.pk
            )
            return

        Deposit.objects.filter(pk=deposit.pk).update(
            worth=worth,
            updated_at=timezone.now(),
        )
        deposit.worth = worth

    @classmethod
    def _notify(cls, deposit: Deposit, status: str) -> None:
        """发送 deposit webhook 通知，统一经 service builder 生成 payload。"""
        payload = cls.build_webhook_payload(
            deposit, confirmed=status == DepositStatus.COMPLETED
        )
        try:
            WebhookService.create_event(
                project=deposit.customer.project, payload=payload
            )
        except Exception:
            logger.exception("发送充币 webhook 通知失败", deposit_id=deposit.pk)

    @classmethod
    def _pre_notify(cls, deposit: Deposit) -> None:
        # 预通知：链上刚出块，尚未达到确认数。
        if deposit.customer.project.pre_notify:
            cls._notify(deposit, DepositStatus.CONFIRMING)

    @classmethod
    def notify_completed(cls, deposit: Deposit) -> None:
        cls._notify(deposit, DepositStatus.COMPLETED)

    @classmethod
    def initialize_deposit(cls, deposit: Deposit) -> Deposit:
        """显式执行 Deposit 创建后的初始化。"""
        cls.refresh_worth(deposit)
        cls._pre_notify(deposit)
        return deposit

    @classmethod
    def try_create_deposit(cls, transfer: OnchainTransfer) -> bool:
        # inactive 占位币允许生成 OnchainTransfer 以便统计余额，但不能继续进入商户充值业务流。
        if not transfer.crypto.active:
            return False

        try:
            customer = DepositAddress.objects.get(
                chain_type=transfer.chain.type,
                address__address=transfer.to_address,
            ).customer
        except DepositAddress.DoesNotExist:
            return False

        transfer.type = TransferType.Deposit
        transfer.save(update_fields=["type"])

        deposit = Deposit.objects.create(
            customer=customer,
            transfer=transfer,
            status=DepositStatus.CONFIRMING,
        )
        cls.initialize_deposit(deposit)
        return True

    @classmethod
    @db_transaction.atomic
    def _transition_status(cls, deposit: Deposit, target: str) -> bool:
        """
        加行锁执行状态转换：CONFIRMING -> target。

        并发安全：select_for_update 防止重复确认。
        幂等：已处于目标状态则返回 False（跳过），非 CONFIRMING 则抛异常。
        """
        Deposit.objects.select_for_update().filter(pk=deposit.pk).first()
        deposit.refresh_from_db()

        if deposit.status == target:
            return False
        if deposit.status != DepositStatus.CONFIRMING:
            raise DepositStatusError("Deposit status must be CONFIRMING")

        deposit.status = target
        deposit.save(update_fields=["status", "updated_at"])
        return True

    @classmethod
    def confirm_deposit(cls, deposit: Deposit) -> None:
        if cls._transition_status(deposit, DepositStatus.COMPLETED):
            cls.notify_completed(deposit)
            send_internal_callback(
                event="deposit.confirmed",
                appid=deposit.customer.project.appid,
                sys_no=deposit.sys_no,
                worth=str(deposit.worth),
                currency=deposit.transfer.crypto.symbol,
            )

    @classmethod
    @db_transaction.atomic
    def drop_deposit(cls, deposit: Deposit) -> None:
        """删除 CONFIRMING 状态的充值记录，释放数据以便 reorg 后扫描器自然重建。"""
        if not Deposit.objects.select_for_update().filter(pk=deposit.pk).exists():
            return  # 已删除，幂等跳过
        deposit.refresh_from_db()
        if deposit.status != DepositStatus.CONFIRMING:
            raise DepositStatusError("Deposit status must be CONFIRMING")
        deposit.delete()

    @classmethod
    def prepare_collection(cls, deposit: Deposit) -> dict | None:  # noqa: PLR0911
        """
        归集准备阶段（必须在事务内调用）：加锁、校验、计算金额，
        为后续同事务创建 DepositCollection + BroadcastTask 准备参数。

        返回 dict 包含归集任务创建所需参数，返回 None 表示无需归集。
        """
        grouped_deposits, deposit = cls._resolve_collection_group(deposit)
        if deposit is None:
            return None

        chain = deposit.transfer.chain
        crypto = deposit.transfer.crypto
        project = deposit.customer.project

        recipient = cls._select_recipient(project_id=project.id, chain_type=chain.type)
        if recipient is None:
            return None

        deposit_addr = DepositAddress.objects.get(
            customer=deposit.customer,
            chain_type=chain.type,
        ).address
        adapter = AdapterFactory.get_adapter(chain.type)

        # 快速退出：链上余额为 0 不可能归集
        balance_raw = adapter.get_balance(deposit_addr.address, chain, crypto)
        if balance_raw <= 0:
            return None

        # 归集金额 = 充值金额之和（非余额），保证对账一致
        amount = cls._calculate_collection_amount(grouped_deposits)

        if not cls._should_collect(deposit, amount):
            return None

        # Gas 充足性检查：不足时自动补充并跳过本轮，等下一轮 gas 到账后重试
        if not cls._ensure_gas_and_check(
            deposit=deposit,
            deposit_address=deposit_addr,
            adapter=adapter,
            collection_amount=amount,
        ):
            return None

        return {
            "group_ids": [item.pk for item in grouped_deposits],
            "address": deposit_addr,
            "crypto": crypto,
            "chain": chain,
            "recipient_address": recipient.address,
            "amount": amount,
            "deposit_id": deposit.id,
        }

    @classmethod
    @db_transaction.atomic
    def execute_collection(cls, params: dict) -> bool:
        """
        在同一事务内同时创建 BroadcastTask、DepositCollection 以及两者关系。

        事务成功提交后，Deposit -> Collection 与 Collection -> BroadcastTask
        两条关系同时成立；若任一步失败，则整个事务回滚，不留下半成品状态。
        """
        from evm.models import EvmBroadcastTask

        decimals = params["crypto"].get_decimals(params["chain"])
        value_raw = int(params["amount"] * Decimal(10**decimals))
        task = EvmBroadcastTask.schedule_transfer(
            address=params["address"],
            crypto=params["crypto"],
            chain=params["chain"],
            to=params["recipient_address"],
            value_raw=value_raw,
            transfer_type=TransferType.DepositCollection,
        )
        collection = DepositCollection.objects.create(
            collection_hash=None,
            broadcast_task=task.base_task,
        )
        Deposit.objects.filter(pk__in=params["group_ids"]).update(
            collection=collection,
            updated_at=timezone.now(),
        )
        return True

    @classmethod
    def collect_deposit(cls, deposit: Deposit) -> bool:
        """归集便捷封装：在单个事务内完成 prepare + create，保证关系原子建立。"""
        try:
            with db_transaction.atomic():
                params = cls.prepare_collection(deposit)
                if params is None:
                    return False
                return cls.execute_collection(params)
        except Exception:  # noqa: BLE001
            logger.exception(
                "归集任务创建失败，事务已回滚",
                deposit_id=getattr(deposit, "id", None) or getattr(deposit, "pk", None),
            )
            return False

    @classmethod
    def _resolve_collection_group(
        cls, deposit: Deposit
    ) -> tuple[list[Deposit], Deposit | None]:
        """
        解析同客户同链同币的待归集分组，返回 (grouped_deposits, representative_deposit)。
        representative_deposit 为 None 表示无需归集。
        """
        if not deposit.pk:
            logger.warning("_resolve_collection_group 收到未持久化实例，跳过")
            return [], None

        grouped = cls._lock_collectible_group(deposit)
        if not grouped:
            return [], None
        return grouped, grouped[0]

    @staticmethod
    def _calculate_collection_amount(grouped_deposits: list[Deposit]) -> Decimal:
        """归集金额 = 分组内所有充值金额之和，保证对账一致：充多少归多少。"""
        return sum((d.transfer.amount for d in grouped_deposits), Decimal("0"))

    @staticmethod
    def try_match_gas_recharge(
        transfer: OnchainTransfer, broadcast_task: "BroadcastTask"
    ) -> bool:
        """通过 BroadcastTask 识别 Vault → 充币地址的 Gas 补充转账，并关联到 GasRecharge 记录。"""
        transfer.type = TransferType.GasRecharge
        transfer.save(update_fields=["type"])

        # 将链上转账关联到 GasRecharge 审计记录
        GasRecharge.objects.filter(
            broadcast_task=broadcast_task,
            transfer__isnull=True,
        ).update(transfer=transfer, updated_at=timezone.now())
        return True

    @classmethod
    @db_transaction.atomic
    def try_match_collection(
        cls,
        transfer: OnchainTransfer,
        broadcast_task: "BroadcastTask",
    ) -> bool:
        """通过 BroadcastTask 将链上归集转账与 DepositCollection 记录关联。"""
        collection = (
            DepositCollection.objects.select_for_update()
            .filter(broadcast_task=broadcast_task)
            .first()
        )
        if collection is None:
            return False

        transfer.type = TransferType.DepositCollection
        transfer.save(update_fields=["type"])

        collection.collection_hash = transfer.hash
        collection.transfer = transfer
        collection.save(update_fields=["collection_hash", "transfer", "updated_at"])
        return True

    @staticmethod
    @db_transaction.atomic
    def confirm_collection(collection: DepositCollection) -> None:
        """归集交易确认：标记整组充币已归集完成。"""
        # 加行锁后重新读取，防止并发重复确认。
        collection = DepositCollection.objects.select_for_update().get(pk=collection.pk)
        # 幂等：已确认则跳过
        if collection.collected_at:
            return
        collection.collected_at = timezone.now()
        collection.save(update_fields=["collected_at", "updated_at"])

    @staticmethod
    @db_transaction.atomic
    def drop_collection(collection: DepositCollection) -> None:
        """
        归集链上观测失效：保留固定关系，仅清空链上观测字段以等待同一任务重试/重播。
        """
        collection = DepositCollection.objects.select_for_update().get(pk=collection.pk)
        if (
            collection.collection_hash is None
            and collection.transfer_id is None
            and collection.collected_at is None
        ):
            return
        collection.collection_hash = None
        collection.transfer = None
        collection.collected_at = None
        collection.save(
            update_fields=["collection_hash", "transfer", "collected_at", "updated_at"]
        )

    @staticmethod
    def _select_recipient(*, project_id: int, chain_type: ChainType | str):
        return (
            RecipientAddress.objects.filter(
                project_id=project_id,
                chain_type=chain_type,
                usage=RecipientAddressUsage.DEPOSIT_COLLECTION,
            )
            .order_by("id")
            .first()
        )

    @staticmethod
    def _to_amount(raw_value: int, decimals: int) -> Decimal:
        return Decimal(raw_value).scaleb(-decimals)

    @classmethod
    def _should_collect(cls, deposit: Deposit, collection_amount: Decimal) -> bool:
        crypto = deposit.transfer.crypto
        project = deposit.customer.project

        try:
            worth = collection_amount * crypto.price("USD")
        except KeyError:
            logger.warning(
                "缺少代币价格，直接触发归集",
                crypto=crypto.symbol,
            )
            worth = project.gather_worth

        if worth >= project.gather_worth:
            return True

        deadline = deposit.created_at + timedelta(days=project.gather_period)
        return timezone.now() >= deadline

    @classmethod
    def _ensure_gas_and_check(
        cls,
        *,
        deposit: Deposit,
        deposit_address,
        adapter,
        collection_amount: Decimal,
    ) -> bool:
        """
        检查归集 gas 是否充足，不足时自动补充并跳过本轮归集。

        原生币：余额 >= 归集金额 + 2 次原生币转账 gas。
        代币：原生币余额 >= 1 次 ERC-20 转账 gas。
        Gas 补充金额 = min(5 次 ERC-20 转账, 10 次原生币转账)。

        返回 True 表示 gas 充足可立即归集，False 表示已发起补充、本轮跳过。
        """
        chain = deposit.transfer.chain
        crypto = deposit.transfer.crypto

        gas_price = cls._get_gas_price(chain)
        if gas_price <= 0:
            # 非 EVM 或 RPC 异常，直接放行由后续交易自行校验
            return True

        native_gas_cost = gas_price * chain.base_transfer_gas
        erc20_gas_cost = gas_price * chain.erc20_transfer_gas

        # --- 判断 gas 是否充足 ---
        if crypto == chain.native_coin or crypto.is_native:
            # 原生币归集：余额需覆盖归集金额 + 2 次原生币转账 gas
            crypto_decimals = crypto.get_decimals(chain)
            collection_raw = int(collection_amount * Decimal(10**crypto_decimals))
            required_gas_raw = 2 * native_gas_cost
            current_balance = adapter.get_balance(
                deposit_address.address, chain, crypto
            )
            if current_balance >= collection_raw + required_gas_raw:
                return True
        else:
            # 代币归集：需要足够原生币支付 ERC-20 转账 gas
            current_native = adapter.get_balance(
                deposit_address.address, chain, chain.native_coin
            )
            if current_native >= erc20_gas_cost:
                return True

        # --- Gas 不足，发起补充 ---

        # 防重复：如果该充值地址已有尚未广播的 Gas 补充任务（stage=queued 且无 tx_hash），
        # 跳过本轮等待广播即可。已广播或已终结的 GasRecharge 不阻塞新请求。
        deposit_addr_record = DepositAddress.objects.get(
            customer=deposit.customer,
            chain_type=chain.type,
        )
        has_pending_recharge = GasRecharge.objects.filter(
            deposit_address=deposit_addr_record,
            recharged_at__isnull=True,
            broadcast_task__stage="queued",
            broadcast_task__tx_hash="",
        ).exists()
        if has_pending_recharge:
            return False

        recharge_raw = min(5 * erc20_gas_cost, 10 * native_gas_cost)
        if recharge_raw <= 0:
            return False

        vault_addr = deposit.customer.project.wallet.get_address(
            chain_type=chain.type,
            usage=AddressUsage.Vault,
        )
        try:
            from evm.models import EvmBroadcastTask

            task = EvmBroadcastTask.schedule_transfer(
                address=vault_addr,
                chain=chain,
                crypto=chain.native_coin,
                to=deposit_address.address,
                value_raw=recharge_raw,
                transfer_type=TransferType.GasRecharge,
            )
            GasRecharge.objects.create(
                deposit_address=deposit_addr_record,
                broadcast_task=task.base_task,
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Gas 补充交易失败，跳过本轮归集",
                deposit_id=deposit.id,
                chain=chain.code,
            )
        # 无论补充成功与否，本轮均跳过，等下一轮 gas 到账后重试
        return False

    @staticmethod
    def _get_gas_price(chain) -> int:
        """获取 EVM 链当前 gas price（wei），非 EVM 返回 0。"""
        if chain.type != ChainType.EVM:
            return 0
        try:
            return chain.w3.eth.gas_price
        except Exception:  # noqa: BLE001
            logger.warning("获取 gas_price 失败", chain=chain.code)
            return 0

    @staticmethod
    def _lock_collectible_group(deposit: Deposit) -> list[Deposit]:
        """锁定同一客户在同链同币下仍待归集的全部完成充币记录。
        使用 skip_locked 与 tasks.py 保持一致，避免并发时阻塞等待或死锁。"""
        return list(
            Deposit.objects.select_for_update(skip_locked=True)
            .select_related(
                "customer", "customer__project", "transfer__crypto", "transfer__chain"
            )
            .filter(
                customer_id=deposit.customer_id,
                transfer__chain_id=deposit.transfer.chain_id,
                transfer__crypto_id=deposit.transfer.crypto_id,
                status=DepositStatus.COMPLETED,
                collection__isnull=True,
            )
            .order_by("created_at", "pk")
        )
