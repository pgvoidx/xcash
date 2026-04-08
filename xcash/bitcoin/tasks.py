import structlog
from celery import shared_task

from bitcoin.models import BitcoinScanCursor
from bitcoin.scanner import BitcoinChainScannerService
from bitcoin.watch_sync import BitcoinWatchSyncService
from chains.models import Chain
from chains.models import ChainType
from common.decorators import singleton_task

logger = structlog.get_logger()


@shared_task(ignore_result=True)
@singleton_task(timeout=64)
def sync_bitcoin_watch_addresses() -> None:
    """将系统内已知 BTC 地址同步到活跃 Bitcoin 节点的钱包视图。"""
    for chain in Chain.objects.filter(active=True, type=ChainType.BITCOIN):
        try:
            imported_count = BitcoinWatchSyncService.sync_chain(chain)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Bitcoin watch-only 地址同步失败",
                chain=chain.code,
                error=str(exc),
            )
            continue

        if imported_count:
            logger.info(
                "Bitcoin watch-only 地址同步完成",
                chain=chain.code,
                imported_count=imported_count,
            )


@shared_task(ignore_result=True)
@singleton_task(timeout=64)
def scan_bitcoin_receipts() -> None:
    """基于 Bitcoin Core 定时扫描 BTC 收款（仅 Invoice 入账）。"""
    for chain in Chain.objects.filter(active=True, type=ChainType.BITCOIN):
        cursor = (
            BitcoinScanCursor.objects.filter(chain=chain)
            .only("enabled")
            .first()
        )
        if cursor is not None and not cursor.enabled:
            continue

        summary = BitcoinChainScannerService.scan_chain(chain=chain)
        if summary.created_receipts:
            logger.info(
                "Bitcoin 区块扫描发现新的标准收款",
                chain=chain.code,
                created_count=summary.created_receipts,
            )
