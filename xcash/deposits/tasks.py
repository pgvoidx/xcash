import structlog
from celery import shared_task

logger = structlog.get_logger()

from common.decorators import singleton_task
from deposits.models import Deposit
from deposits.models import DepositStatus
from deposits.service import DepositService


@shared_task(ignore_result=True)
@singleton_task(timeout=64)
def gather_deposits() -> None:
    # 外层不开事务：仅读取候选集 ID 列表，避免长事务持有行锁期间执行 RPC 调用。
    # 逐条在 service 内开独立事务处理，防止一次性锁住全批记录直至所有 RPC 结束，阻塞其他并发操作。
    candidate_ids = list(
        Deposit.objects.filter(
            status=DepositStatus.COMPLETED,
            collection__isnull=True,
        )
        .order_by("created_at")
        .values_list("pk", flat=True)[:16]
    )

    for deposit_id in candidate_ids:
        try:
            deposit = (
                Deposit.objects.select_related(
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
                continue
            collected = DepositService.collect_deposit(deposit)
            if not collected:
                logger.debug("归集任务本轮跳过", deposit_id=deposit_id)
        except Exception:  # noqa: BLE001
            logger.exception("归集充币任务失败", deposit_id=deposit_id)
