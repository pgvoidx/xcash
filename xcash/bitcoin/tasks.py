import structlog
from celery import shared_task
from django.db.models import Q

from bitcoin.models import BitcoinBroadcastTask
from bitcoin.scanner import BitcoinChainScannerService
from chains.models import BroadcastTaskResult
from chains.models import BroadcastTaskStage
from chains.models import Chain
from chains.models import ChainType
from common.decorators import singleton_task
from common.time import ago

logger = structlog.get_logger()


@shared_task(ignore_result=True)
def broadcast_bitcoin_broadcast_task(pk: int) -> None:
    """广播单条 BitcoinBroadcastTask。

    Bitcoin P2PKH 交易无过期时间，
    可无限期重试直到广播成功或被手动取消。
    """
    task = BitcoinBroadcastTask.objects.get(pk=pk)

    if task.base_task_id:
        # 已进入待确认/已结束的任务不应继续重复广播。
        if (
            task.base_task.result != BroadcastTaskResult.UNKNOWN
            or task.base_task.stage
            not in (BroadcastTaskStage.QUEUED, BroadcastTaskStage.PENDING_CHAIN)
        ):
            return

    task.broadcast()


@shared_task(ignore_result=True)
@singleton_task(timeout=64)
def process_bitcoin_queues() -> None:
    """定时扫描待上链的 BitcoinBroadcastTask，对符合条件的任务触发重试广播。

    条件：
    - 统一父任务仍处于待执行/待上链
    - 距上次尝试超过 5 分钟（Bitcoin 节点重试间隔较长）
    - 创建时间超过 5 秒（给 broadcast_bitcoin_broadcast_task 初次执行留出时间）
    """
    queryset = BitcoinBroadcastTask.objects.filter(
        Q(last_attempt_at__isnull=True) | Q(last_attempt_at__lt=ago(minutes=5)),
        base_task__stage__in=(
            BroadcastTaskStage.QUEUED,
            BroadcastTaskStage.PENDING_CHAIN,
        ),
        base_task__result=BroadcastTaskResult.UNKNOWN,
        created_at__lt=ago(seconds=5),
    ).order_by("created_at")[:10]

    for task in queryset:
        broadcast_bitcoin_broadcast_task.delay(task.pk)


@shared_task(ignore_result=True)
@singleton_task(timeout=64)
def scan_bitcoin_receipts() -> None:
    """基于 Bitcoin Core 定时扫描标准 BTC 收款。

    BTC 不再依赖外部流服务商，首版直接使用 Bitcoin Core 区块扫描。
    只处理标准收款输出，避免把复杂脚本、金库找零和非收款流量混进 Transfer。
    """
    for chain in Chain.objects.filter(active=True, type=ChainType.BITCOIN):
        summary = BitcoinChainScannerService.scan_chain(chain=chain)
        if summary.created_receipts:
            logger.info(
                "Bitcoin 区块扫描发现新的标准收款",
                chain=chain.code,
                created_count=summary.created_receipts,
            )
