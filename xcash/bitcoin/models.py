from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


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
