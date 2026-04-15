from rest_framework import serializers

from chains.serializers import TransferSerializer
from deposits.models import DepositCollection
from deposits.models import GasRecharge
from withdrawals.models import VaultFunding


class DepositCollectionSerializer(serializers.ModelSerializer):
    tx = TransferSerializer(source="transfer", read_only=True)

    class Meta:
        model = DepositCollection
        fields = [
            "id",
            "collection_hash",
            "tx",
            "collected_at",
            "created_at",
            "updated_at",
        ]


class GasRechargeSerializer(serializers.ModelSerializer):
    tx = TransferSerializer(source="transfer", read_only=True)
    deposit_address = serializers.CharField(
        source="deposit_address.address.address", read_only=True
    )

    class Meta:
        model = GasRecharge
        fields = [
            "id",
            "deposit_address",
            "tx",
            "recharged_at",
            "created_at",
            "updated_at",
        ]


class VaultFundingSerializer(serializers.ModelSerializer):
    tx = TransferSerializer(source="transfer", read_only=True)

    class Meta:
        model = VaultFunding
        fields = [
            "id",
            "tx",
        ]
