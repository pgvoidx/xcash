import structlog
from celery import shared_task
from django.db.models import Exists
from django.db.models import F
from django.db.models import OuterRef

logger = structlog.get_logger()

from common.decorators import singleton_task
from deposits.models import Deposit
from deposits.models import DepositStatus
from deposits.service import DepositService
from projects.models import RecipientAddress
from projects.models import RecipientAddressUsage


# ── gather_deposits 调度参数（防 DoS / 队头阻塞 / 多 project 公平） ──
# 单 project 单轮最多挑 K 笔：避免单一 project 用大量 deposit 独占整轮调度，
# 让其他项目的归集也能拿到名额。
PER_PROJECT_QUOTA = 4
# 单轮总归集名额：与原实现 16 保持一致，不变更上层吞吐预期。
TOTAL_BATCH_SIZE = 16
# 候选池：在 Python 层做 round-robin 之前预读的候选 ID 数。
# 取得足够大让多项目场景下能凑齐 quota，但又不至于让一次 query 过大。
CANDIDATE_POOL = 200
# 单笔 deposit 累计失败这么多次后，gather 永久跳过、写 warning 留待人工介入。
# 防御来源：恶意 / 错误配置（recipient 是会 revert 的合约）等场景下，
# 反复 collect 不会成功；不能让这类"毒丸"持续占用队头。
MAX_FAILED_ATTEMPTS = 5


@shared_task(ignore_result=True)
@singleton_task(timeout=64)
def gather_deposits() -> None:
    """定时归集任务：扫描已完成、尚未归集的 Deposit，逐条触发 collect_deposit。

    四层防御：
    1. 仅扫描 project 已配置 DEPOSIT_COLLECTION recipient 的 deposit（Exists 子查询）。
       project 漏配 recipient 时这些 deposit 不会被反复尝试，等待运营补配后自然进入。
    2. 跳过 failed_collection_attempts 已达上限的 deposit；这些 deposit 已被
       collect_deposit 反复返回 False，再尝试也只是浪费调度名额，必须人工介入。
    3. 候选池预读 CANDIDATE_POOL 条 + Python 层 per-project 配额，防止单个 project
       用大量 deposit 独占整轮。
    4. 每笔失败时累计 failed_collection_attempts，达到阈值时打 warning。

    外层不开事务：仅读取候选集 ID 列表，避免长事务持有行锁期间执行 RPC 调用。
    每条 deposit 交给 DepositService.collect_deposit 处理：prepare 阶段事务外做
    链上 RPC（余额 / gas 价格 / gas 补充），execute 阶段事务内做 DB 原子三步写入，
    把行锁持有时间压到最短，避免阻塞其他并发操作。
    """
    # L1：只考虑 project 已配 DEPOSIT_COLLECTION recipient（且链类型匹配）的 deposit。
    # OuterRef 走 join 字符串：deposit.customer.project_id 与 deposit.transfer.chain.type。
    has_recipient = RecipientAddress.objects.filter(
        project_id=OuterRef("customer__project_id"),
        chain_type=OuterRef("transfer__chain__type"),
        usage=RecipientAddressUsage.DEPOSIT_COLLECTION,
    )

    # L3：失败计数已达上限的不再调度。values_list 同时取 project_id 用于公平调度。
    candidates = list(
        Deposit.objects.filter(
            status=DepositStatus.COMPLETED,
            collection__isnull=True,
            failed_collection_attempts__lt=MAX_FAILED_ATTEMPTS,
        )
        .annotate(_has_recipient=Exists(has_recipient))
        .filter(_has_recipient=True)
        .order_by("created_at")
        .values_list("pk", "customer__project_id")[:CANDIDATE_POOL]
    )

    # 公平调度：在 Python 层按 project 做 round-robin，每个 project 单轮最多 K 笔。
    # 选择 Python 而非 SQL window function 的理由：
    # - 实现简单、易读、易调试；
    # - CANDIDATE_POOL 量级（200）下性能开销可忽略；
    # - 后续 tune 参数（quota / batch / pool）只在常量上调整即可。
    seen_per_project: dict[int, int] = {}
    candidate_ids: list[int] = []
    for pk, project_id in candidates:
        if seen_per_project.get(project_id, 0) >= PER_PROJECT_QUOTA:
            continue
        candidate_ids.append(pk)
        seen_per_project[project_id] = seen_per_project.get(project_id, 0) + 1
        if len(candidate_ids) >= TOTAL_BATCH_SIZE:
            break

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
                # 失败计数 +1：用 F 表达式避免读-改-写的 race condition。
                # 单条 deposit 即便被并发任务同时观察到，也能保证计数原子单调递增。
                Deposit.objects.filter(pk=deposit_id).update(
                    failed_collection_attempts=F("failed_collection_attempts") + 1
                )
                # 重新读取一次最新计数，决定是否打告警。这里多一次 DB 读，但只
                # 在归集失败路径上发生，对正常路径没有性能影响。
                latest_attempts = (
                    Deposit.objects.filter(pk=deposit_id)
                    .values_list("failed_collection_attempts", flat=True)
                    .first()
                )
                if (
                    latest_attempts is not None
                    and latest_attempts >= MAX_FAILED_ATTEMPTS
                ):
                    logger.warning(
                        "归集失败次数达上限，进入人工 review",
                        deposit_id=deposit_id,
                        failed_attempts=latest_attempts,
                    )
                else:
                    logger.debug(
                        "归集任务本轮跳过",
                        deposit_id=deposit_id,
                        failed_attempts=latest_attempts,
                    )
        except Exception:  # noqa: BLE001
            logger.exception("归集充币任务失败", deposit_id=deposit_id)
