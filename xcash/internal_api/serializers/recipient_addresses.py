from rest_framework import serializers

from projects.models import RecipientAddress


class RecipientAddressCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecipientAddress
        fields = ["name", "chain_type", "address", "usage"]


class RecipientAddressDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecipientAddress
        fields = ["id", "name", "chain_type", "address", "usage", "created_at"]
