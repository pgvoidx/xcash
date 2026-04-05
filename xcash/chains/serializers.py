from rest_framework import serializers

from chains.models import OnchainTransfer
from common.serializers import StrippedDecimalField


class TransferSerializer(serializers.ModelSerializer):
    chain = serializers.CharField(read_only=True, source="chain.code")
    crypto = serializers.CharField(read_only=True, source="crypto.symbol")
    hash = serializers.CharField(read_only=True)
    amount = StrippedDecimalField(read_only=True, max_digits=32, decimal_places=8)

    class Meta:
        model = OnchainTransfer
        fields = (
            "chain",
            "block",
            "hash",
            "from_address",
            "to_address",
            "crypto",
            "amount",
            "datetime",
            "status",
            "confirm_progress",
        )
