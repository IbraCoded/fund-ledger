from dataclasses import fields

from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework import serializers

from operations.statements import CapitalAccountStatement


class ApiKeyAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "access.authentication.ApiKeyAuthentication"
    name = "ApiKey"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "fl_<prefix>.<secret>",
            "description": "API key issued with `manage.py create_api_key`.",
        }


class ErrorSerializer(serializers.Serializer):
    error = serializers.CharField()
    detail = serializers.CharField()


class BalanceSerializer(serializers.Serializer):
    account = serializers.UUIDField()
    currency = serializers.CharField()
    balance = serializers.CharField(
        help_text="Native currency, debit-positive, as a decimal string"
    )
    base_balance = serializers.CharField(help_text="Fund base currency at booking-time FX")
    as_of = serializers.DateTimeField(allow_null=True)


class UnbalancedTransferSerializer(serializers.Serializer):
    transfer = serializers.UUIDField()
    imbalance = serializers.CharField()


class ReconciliationSerializer(serializers.Serializer):
    fund = serializers.UUIDField()
    balanced = serializers.BooleanField()
    imbalance = serializers.CharField()
    unbalanced_transfers = UnbalancedTransferSerializer(many=True)


class MembershipSerializer(serializers.Serializer):
    fund = serializers.UUIDField()
    fund_name = serializers.CharField()
    role = serializers.CharField()
    lp = serializers.UUIDField(allow_null=True)


class MeSerializer(serializers.Serializer):
    username = serializers.CharField()
    memberships = MembershipSerializer(many=True)


# One string field per statement line, generated from the dataclass so they can't drift apart.
StatementSerializer = type(
    "CapitalAccountStatement",
    (serializers.Serializer,),
    {f.name: serializers.CharField() for f in fields(CapitalAccountStatement)},
)
