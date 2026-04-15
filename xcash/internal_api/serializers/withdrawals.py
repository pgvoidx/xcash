from rest_framework import serializers

from chains.serializers import TransferSerializer
from withdrawals.models import Withdrawal


class InternalWithdrawalCreateSerializer(serializers.Serializer):
    """内网提币创建序列化器。

    复用现有 WithdrawalViewSet.create 中的校验逻辑思路，
    但 project 由 URL 的 appid 注入而非 HMAC header。
    字段定义与商户 API 的 CreateWithdrawalSerializer 保持一致。
    """

    out_no = serializers.CharField(max_length=64)
    to = serializers.CharField(max_length=256)
    uid = serializers.CharField(max_length=128, required=False, default="")
    crypto = serializers.CharField(max_length=32)
    chain = serializers.CharField(max_length=64)
    amount = serializers.DecimalField(max_digits=36, decimal_places=18)


class InternalWithdrawalDetailSerializer(serializers.ModelSerializer):
    tx = TransferSerializer(source="transfer", read_only=True)
    crypto = serializers.SlugRelatedField(slug_field="symbol", read_only=True)
    chain = serializers.SlugRelatedField(slug_field="code", read_only=True)
    uid = serializers.CharField(source="customer.uid", read_only=True, default="")
    reviewed_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Withdrawal
        fields = [
            "sys_no",
            "out_no",
            "uid",
            "crypto",
            "chain",
            "to",
            "amount",
            "worth",
            "hash",
            "status",
            "tx",
            "reviewed_by",
            "reviewed_at",
            "created_at",
            "updated_at",
        ]


class WithdrawalRejectSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)
