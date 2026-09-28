from datetime import UTC, datetime
from uuid import UUID

from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import CursorPagination
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from api.renderers import CSVRenderer
from api.serializers import (
    AccountSerializer,
    CapitalCallRequestSerializer,
    CapitalCallSerializer,
    DistributionRequestSerializer,
    DistributionSerializer,
    EntrySerializer,
    PeriodSerializer,
    ReverseRequestSerializer,
    TransferSerializer,
)
from funds.models import Fund, LimitedPartner, Period
from ledger.models import Account, Entry, Transfer
from ledger.queries import base_balance, native_balance
from ledger.retry import with_deadlock_retry
from ledger.services import reverse_transfer
from operations.periods import close_period, period_for
from operations.services import create_capital_call, create_distribution
from operations.statements import lp_statement

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


class DistributionsView(APIView):
    def post(self, request: Request, fund_id: UUID) -> Response:
        key = idempotency_key(request)
        get_object_or_404(Fund, id=fund_id)
        body = DistributionRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        distribution, created = with_deadlock_retry(
            lambda: create_distribution(fund_id=fund_id, idempotency_key=key, **body.validated_data)
        )
        return created_or_replayed(DistributionSerializer(distribution).data, created)


class ReverseTransferView(APIView):
    def post(self, request: Request, transfer_id: UUID) -> Response:
        key = idempotency_key(request)
        original = get_object_or_404(
            Transfer.objects.select_related("period__fund"), id=transfer_id
        )
        body = ReverseRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        on_date = body.validated_data.get("on_date") or timezone.localdate()
        period = period_for(original.period.fund, on_date)
        reversal, created = with_deadlock_retry(
            lambda: reverse_transfer(transfer_id=original.id, idempotency_key=key, period=period)
        )
        return created_or_replayed(TransferSerializer(reversal).data, created)


class ClosePeriodView(APIView):
    def post(self, request: Request, fund_id: UUID, period_id: UUID) -> Response:
        period, _ = close_period(fund_id=fund_id, period_id=period_id)
        return Response(PeriodSerializer(period).data)


class LPStatementView(APIView):
    renderer_classes = [JSONRenderer, CSVRenderer]

    def get(self, request: Request, fund_id: UUID, lp_id: UUID) -> Response:
        fund = get_object_or_404(Fund, id=fund_id)
        lp = get_object_or_404(LimitedPartner, id=lp_id)
        try:
            period_id = UUID(request.query_params.get("period", ""))
        except ValueError:
            raise ValidationError({"period": "A period id (UUID) is required."}) from None
        period = get_object_or_404(Period, id=period_id, fund=fund)
        statement = lp_statement(fund=fund, lp=lp, period=period)
        response = Response(statement.as_dict())
        if request.accepted_renderer.format == "csv":
            filename = f"statement-{lp.id}-{period.start_date}.csv"
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
