from decimal import Decimal
from typing import TypedDict

from rest_framework import serializers

from ledger.models import Account, Entry, Transfer
from operations.models import CapitalCall, Distribution, DistributionClassification


class MoneyInKwargs(TypedDict):
    max_digits: int
    decimal_places: int
    min_value: Decimal


# Typed for the same reason as MONEY in funds/models.py: so mypy can check **MONEY_IN.
MONEY_IN: MoneyInKwargs = {"max_digits": 18, "decimal_places": 2, "min_value": Decimal("0.01")}


class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        fields = ["id", "code", "account_type", "currency", "owner_lp"]


class EntrySerializer(serializers.ModelSerializer):
    # Generated columns aren't auto-mapped by DRF; declare them explicitly.
    signed_amount = serializers.DecimalField(max_digits=20, decimal_places=4, read_only=True)
    signed_base_amount = serializers.DecimalField(max_digits=20, decimal_places=4, read_only=True)

    class Meta:
        model = Entry
        fields = [
            "id",
            "transfer",
            "account",
            "direction",
            "amount",
            "currency",
            "fx_rate",
            "base_amount",
            "signed_amount",
            "signed_base_amount",
            "created_at",
        ]


class TransferSerializer(serializers.ModelSerializer):
    entries = EntrySerializer(many=True, read_only=True)

    class Meta:
        model = Transfer
        fields = [
            "id",
            "idempotency_key",
            "transfer_type",
            "reverses",
            "period",
            "description",
            "entries",
        ]


class CapitalCallRequestSerializer(serializers.Serializer):
    total_amount = serializers.DecimalField(**MONEY_IN)
    notice_date = serializers.DateField()
    due_date = serializers.DateField()

    def validate(self, attrs):
        if attrs["due_date"] < attrs["notice_date"]:
            raise serializers.ValidationError("due_date must not precede notice_date")
        return attrs


class CapitalCallSerializer(serializers.ModelSerializer):
    class Meta:
        model = CapitalCall
        fields = [
            "id",
            "fund",
            "call_number",
            "notice_date",
            "due_date",
            "total_amount",
            "transfer",
        ]


class DistributionRequestSerializer(serializers.Serializer):
    total_amount = serializers.DecimalField(**MONEY_IN)
    payment_date = serializers.DateField()
    classification = serializers.ChoiceField(choices=DistributionClassification.choices)


class DistributionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Distribution
        fields = [
            "id",
            "fund",
            "distribution_number",
            "payment_date",
            "total_amount",
            "classification",
            "transfer",
        ]
