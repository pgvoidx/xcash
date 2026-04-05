from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from evm.models import EvmScanCursor

# DEBUG 本地开发模式下，worker/beat 每次重启后第一次扫描都从当前链头开始。
# 这里用进程内集合记录“本进程已完成启动对齐”的游标，避免后续正常轮询被反复重置。
_DEBUG_BOOTSTRAPPED_CURSORS: set[tuple[int, str]] = set()


def _set_cursor_position_to_latest(
    *,
    cursor: EvmScanCursor,
    latest_block: int,
) -> EvmScanCursor:
    safe_block = max(0, latest_block - cursor.chain.confirm_block_count)
    EvmScanCursor.objects.filter(pk=cursor.pk).update(
        last_scanned_block=latest_block,
        last_safe_block=safe_block,
        last_error="",
        last_error_at=None,
        updated_at=timezone.now(),
    )
    cursor.last_scanned_block = latest_block
    cursor.last_safe_block = safe_block
    cursor.last_error = ""
    cursor.last_error_at = None
    return cursor


def bootstrap_cursor_to_latest_for_debug(
    *,
    cursor: EvmScanCursor,
    latest_block: int,
) -> EvmScanCursor:
    if latest_block <= 0 or cursor.chain_id is None:
        return cursor

    # 首次创建且尚未初始化的游标，不应从创世块补扫；直接对齐到当前链头。
    if cursor.last_scanned_block <= 0:
        return _set_cursor_position_to_latest(cursor=cursor, latest_block=latest_block)

    if not settings.DEBUG:
        return cursor

    cache_key = (cursor.chain_id, str(cursor.scanner_type))
    if cache_key in _DEBUG_BOOTSTRAPPED_CURSORS:
        return cursor

    cursor = _set_cursor_position_to_latest(cursor=cursor, latest_block=latest_block)
    _DEBUG_BOOTSTRAPPED_CURSORS.add(cache_key)
    return cursor
