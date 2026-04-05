from django.contrib import admin
from unfold.decorators import display

from bitcoin.models import BitcoinBroadcastTask
from bitcoin.models import BitcoinScanCursor
from common.admin import ReadOnlyModelAdmin
from common.admin_scan_cursor import SyncScanCursorToLatestActionMixin
from common.utils.math import format_decimal_stripped


@admin.register(BitcoinBroadcastTask)
class BitcoinBroadcastTaskAdmin(ReadOnlyModelAdmin):
    ordering = ("-created_at",)
    list_display = (
        "display_address",
        "display_chain",
        "transfer_type",
        "display_recipient",
        "display_amount",
        "display_tx_hash",
        "fee_satoshi",
        "display_status",
        "created_at",
    )
    # 状态展示优先读取统一父任务，后台查询一并预加载，避免 N+1。
    list_select_related = ("base_task", "base_task__crypto", "address", "chain")
    search_fields = ("base_task__tx_hash", "address__address", "base_task__recipient")

    @display(
        description="状态",
        label={
            "待执行": "warning",
            "待上链": "warning",
            "待确认": "info",
            "成功": "success",
            "失败": "danger",
            "已结束": "info",
        },
    )
    def display_status(self, instance: BitcoinBroadcastTask) -> str:
        return instance.status

    @admin.display(description="地址", ordering="address__address")
    def display_address(self, obj: BitcoinBroadcastTask):  # pragma: no cover
        return obj.address

    @admin.display(description="网络", ordering="chain__name")
    def display_chain(self, obj: BitcoinBroadcastTask):  # pragma: no cover
        return obj.chain

    @admin.display(description="类型", ordering="base_task__transfer_type")
    def transfer_type(self, obj: BitcoinBroadcastTask):  # pragma: no cover
        return obj.base_task.get_transfer_type_display() if obj.base_task_id else "—"

    @admin.display(description="收款地址", ordering="base_task__recipient")
    def display_recipient(self, obj: BitcoinBroadcastTask):  # pragma: no cover
        return obj.base_task.recipient if obj.base_task_id else "—"

    @admin.display(description="数量")
    def display_amount(self, obj: BitcoinBroadcastTask):  # pragma: no cover
        if obj.base_task_id and obj.base_task.amount is not None:
            return format_decimal_stripped(obj.base_task.amount)
        return "—"

    @admin.display(description="交易 ID", ordering="base_task__tx_hash")
    def display_tx_hash(self, obj: BitcoinBroadcastTask):  # pragma: no cover
        return obj.base_task.tx_hash if obj.base_task_id else "—"


@admin.register(BitcoinScanCursor)
class BitcoinScanCursorAdmin(SyncScanCursorToLatestActionMixin, ReadOnlyModelAdmin):
    # Bitcoin 扫描游标只承担观测与排障职责，后台统一只读，避免人工改游标破坏扫描连续性。
    actions = ("sync_selected_to_latest",)
    ordering = ("chain__name",)
    list_display = (
        "display_chain",
        "display_enabled",
        "display_lag_state",
        "display_chain_latest_block",
        "last_scanned_block",
        "last_safe_block",
        "display_scan_gap",
        "display_error_state",
        "display_error_summary",
        "updated_at",
    )
    list_filter = ("enabled", "chain")
    search_fields = ("chain__name", "chain__code", "last_error")
    list_select_related = ("chain",)
    readonly_fields = (
        "chain",
        "display_enabled",
        "last_scanned_block",
        "last_safe_block",
        "display_chain_latest_block",
        "display_scan_gap",
        "display_lag_state",
        "last_error",
        "display_error_summary",
        "last_error_at",
        "updated_at",
        "created_at",
    )
    fields = readonly_fields

    @admin.display(ordering="chain__name", description="网络")
    def display_chain(self, obj: BitcoinScanCursor):  # pragma: no cover
        return obj.chain

    @display(
        description="启用",
        label={
            "是": "success",
            "否": "danger",
        },
    )
    def display_enabled(self, obj: BitcoinScanCursor) -> str:
        return "是" if obj.enabled else "否"

    @admin.display(description="链上最新块")
    def display_chain_latest_block(
        self, obj: BitcoinScanCursor
    ) -> int:  # pragma: no cover
        return obj.chain.latest_block_number

    @display(
        description="扫描状态",
        label={
            "正常": "success",
            "异常": "danger",
        },
    )
    def display_error_state(self, obj: BitcoinScanCursor) -> str:
        return "异常" if obj.last_error else "正常"

    @admin.display(description="落后区块")
    def display_scan_gap(self, obj: BitcoinScanCursor) -> int:
        # 以链上当前最新高度对比主扫描游标，便于快速判断该链是否积压。
        return max(obj.chain.latest_block_number - obj.last_scanned_block, 0)

    @display(
        description="积压",
        label={
            "正常": "success",
            "轻微": "warning",
            "严重": "danger",
        },
    )
    def display_lag_state(self, obj: BitcoinScanCursor) -> str:
        gap = self.display_scan_gap(obj)
        if gap >= 128:
            return "严重"
        if gap >= 16:
            return "轻微"
        return "正常"

    @admin.display(description="错误摘要")
    def display_error_summary(self, obj: BitcoinScanCursor) -> str:
        if not obj.last_error:
            return "—"
        # 列表页只展示摘要，详情页仍保留完整 last_error 原文。
        return obj.last_error[:60]
