import structlog
from celery import shared_task
from django.db import transaction as db_transaction

logger = structlog.get_logger()

from common.decorators import singleton_task
from deposits.models import Deposit
from deposits.models import DepositStatus
from deposits.service import DepositService


@shared_task(ignore_result=True)
@singleton_task(timeout=64)
def gather_deposits() -> None:
    # 外层不开事务：仅读取候选集 ID 列表，避免长事务持有行锁期间执行 RPC 调用。
    # 逐条开独立事务处理，防止一次性锁住全批记录直至所有 RPC 结束，阻塞其他并发操作。
    candidate_ids = list(
        Deposit.objects.filter(
            status=DepositStatus.COMPLETED,
            collection__isnull=True,
        )
        .order_by("created_at")
        .values_list("pk", flat=True)[:16]
    )

    for deposit_id in candidate_ids:
        # 两阶段归集：阶段1（事务内）加锁+校验+预占位，阶段2（事务外）广播链上交易。
        # 分离事务与 RPC，避免长事务持有行锁期间执行链上调用。
        try:
            # 阶段1：事务内加锁、校验、计算金额、预创建 collection 占位
            params = None
            with db_transaction.atomic():
                deposit = (
                    Deposit.objects.select_for_update(skip_locked=True, of=("self",))
                    .select_related(
                        "customer",
                        "customer__project",
                        "transfer__crypto",
                        "transfer__chain",
                    )
                    .filter(
                        pk=deposit_id,
                        status=DepositStatus.COMPLETED,
                        collection__isnull=True,
                    )
                    .first()
                )
                if deposit is None:
                    # 已被其他归集流程处理或状态已变更，跳过
                    continue

                params = DepositService.prepare_collection(deposit)

            # 阶段2：事务外广播链上交易（不持有行锁）
            if params is not None:
                collected = DepositService.execute_collection(params)
                if not collected:
                    logger.debug("归集广播失败", deposit_id=deposit_id)
        except Exception:  # noqa: BLE001
            logger.exception("归集充币任务失败", deposit_id=deposit_id)
