from __future__ import annotations

from collections import defaultdict

from django.contrib import admin
from django.contrib import messages
from django.db import transaction
from django.utils import timezone


class SyncScanCursorToLatestActionMixin:
    """为扫描游标后台提供“追平到最新区块”批量动作。"""

    @admin.action(description="追平到最新区块")
    def sync_selected_to_latest(self, request, queryset) -> None:
        selected_cursors = list(
            queryset.select_related("chain").order_by("chain_id", "pk")
        )
        if not selected_cursors:
            self.message_user(request, "未选中任何扫描游标", level=messages.WARNING)
            return

        cursor_ids_by_chain_id: dict[int, list[int]] = defaultdict(list)
        chains_by_id = {}
        for cursor in selected_cursors:
            cursor_ids_by_chain_id[cursor.chain_id].append(cursor.pk)
            chains_by_id[cursor.chain_id] = cursor.chain

        success_count = 0
        updated_at = timezone.now()

        for chain_id, cursor_ids in cursor_ids_by_chain_id.items():
            chain = chains_by_id[chain_id]
            try:
                latest_block = chain.get_latest_block_number
            except Exception as exc:  # noqa: BLE001
                self.message_user(
                    request,
                    f"{chain.code} 追平失败：{exc}",
                    level=messages.ERROR,
                )
                continue

            safe_block = max(0, latest_block - chain.confirm_block_count)
            with transaction.atomic():
                chain.__class__.objects.filter(pk=chain.pk).update(
                    latest_block_number=latest_block,
                )
                queryset.model.objects.filter(pk__in=cursor_ids).update(
                    last_scanned_block=latest_block,
                    last_safe_block=safe_block,
                    last_error="",
                    last_error_at=None,
                    updated_at=updated_at,
                )
            success_count += len(cursor_ids)

        if success_count:
            self.message_user(
                request,
                f"已将 {success_count} 个扫描游标追平到链上最新区块",
                level=messages.SUCCESS,
            )
