from datetime import UTC, datetime
from uuid import UUID

from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from api.serializers import (
    AccountSerializer,
    CapitalCallRequestSerializer,
    CapitalCallSerializer,
    EntrySerializer,
)
from funds.models import Fund
from ledger.models import Account, Entry
from ledger.queries import base_balance, native_balance
from ledger.retry import with_deadlock_retry
from operations.services import create_capital_call

IDEMPOTENCY_HEADER = "Idempotency-Key"


def idempotency_key(request: Request) -> str:
    key = request.headers.get(IDEMPOTENCY_HEADER, "").strip()
    if not key:
        raise ValidationError({IDEMPOTENCY_HEADER: "This header is required on mutating requests."})
    if len(key) > 255:
        raise ValidationError({IDEMPOTENCY_HEADER: "Must be at most 255 characters."})
    return key


def created_or_replayed(data, created: bool) -> Response:
    return Response(data, status=201 if created else 200)


def parse_as_of(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    parsed = parse_datetime(raw)
    if parsed is None:
        raise ValidationError({"as_of": "Expected ISO-8601, e.g. 2026-06-30T23:59:59Z"})
    return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed, UTC)


class FundAccountsView(APIView):
    def get(self, request: Request, fund_id: UUID) -> Response:
        fund = get_object_or_404(Fund, id=fund_id)
        return Response(AccountSerializer(fund.accounts.order_by("code"), many=True).data)


class CapitalCallsView(APIView):
    def post(self, request: Request, fund_id: UUID) -> Response:
        key = idempotency_key(request)
        get_object_or_404(Fund, id=fund_id)
        body = CapitalCallRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        call, created = with_deadlock_retry(
            lambda: create_capital_call(fund_id=fund_id, idempotency_key=key, **body.validated_data)
        )
        return created_or_replayed(CapitalCallSerializer(call).data, created)


class AccountBalanceView(APIView):
    def get(self, request: Request, account_id: UUID) -> Response:
        account = get_object_or_404(Account, id=account_id)
        as_of = parse_as_of(request.query_params.get("as_of"))
        return Response(
            {
                "account": str(account.id),
                "currency": account.currency,
                "balance": str(native_balance(account.id, as_of=as_of)),
                "base_balance": str(base_balance(account.id, as_of=as_of)),
                "as_of": as_of.isoformat() if as_of else None,
            }
        )


class EntryCursorPagination(CursorPagination):
    page_size = 50
    ordering = "-created_at"


class AccountEntriesView(generics.ListAPIView):
    serializer_class = EntrySerializer
    pagination_class = EntryCursorPagination

    def get_queryset(self):
        account = get_object_or_404(Account, id=self.kwargs["account_id"])
        return Entry.objects.filter(account=account)
