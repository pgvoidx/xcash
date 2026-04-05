from rest_framework import serializers

from common.utils.math import format_decimal_stripped


class StrippedDecimalField(serializers.DecimalField):
    """
    一个自定义的DecimalField，用于在序列化输出时移除末尾多余的零。
    例如：Decimal('12.500') -> "12.5"
          Decimal('100.00') -> "100"
    """

    def to_representation(self, value):
        if value is None:
            return None

        # 统一复用公共格式化逻辑，确保 API/admin/webhook 输出一致。
        return format_decimal_stripped(value)
