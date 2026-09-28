from datetime import UTC, datetime
from uuid import UUID

from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import generics
from rest_framework.exceptions import NotAuthenticated, NotFound, ValidationError
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from access.models import FundMembership, Role
from access.permissions import FundRolePermission, membership_of
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
from ledger.reconciliation import fund_imbalance, unbalanced_transfers
from ledger.retry import with_deadlock_retry
from ledger.services import reverse_transfer
from operations.periods import close_period, period_for
from operations.services import create_capital_call, create_distribution
from operations.statements import lp_statement


def actor(request: Request) -> str:
    """Who is doing this. Always from authentication, never from the request body."""
    return request.user.get_username()


class FundScoped(APIView):
    """Base view: the caller must hold at least `required_role` on the fund in the URL."""

    permission_classes = [FundRolePermission]
    required_role: str = Role.VIEWER

    def get_fund_id(self) -> UUID:
        return self.kwargs["fund_id"]


class AccountScoped(FundScoped):
    """For /accounts/{account_id}/...: authorise against the account's fund."""

    def get_fund_id(self) -> UUID:
        fund_id = (
            Account.objects.filter(id=self.kwargs["account_id"])
            .values_list("fund_id", flat=True)
            .first()
        )
        if fund_id is None:
            raise NotFound()
        return fund_id


class TransferScoped(FundScoped):
    """For /transfers/{transfer_id}/...: authorise against the transfer's fund."""

    def get_fund_id(self) -> UUID:
        fund_id = (
            Transfer.objects.filter(id=self.kwargs["transfer_id"])
            .values_list("period__fund_id", flat=True)
            .first()
        )
        if fund_id is None:
            raise NotFound()
        return fund_id


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


class FundAccountsView(FundScoped):
    required_role = Role.VIEWER

    def get(self, request: Request, fund_id: UUID) -> Response:
        fund = get_object_or_404(Fund, id=fund_id)
        return Response(AccountSerializer(fund.accounts.order_by("code"), many=True).data)


class CapitalCallsView(FundScoped):
    required_role = Role.OPERATOR

    def post(self, request: Request, fund_id: UUID) -> Response:
        key = idempotency_key(request)
        get_object_or_404(Fund, id=fund_id)
        body = CapitalCallRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        call, created = with_deadlock_retry(
            lambda: create_capital_call(
                fund_id=fund_id,
                idempotency_key=key,
                created_by=actor(request),
                **body.validated_data,
            )
        )
        return created_or_replayed(CapitalCallSerializer(call).data, created)


class AccountBalanceView(AccountScoped):
    required_role = Role.VIEWER

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


class AccountEntriesView(AccountScoped, generics.ListAPIView):
    required_role = Role.VIEWER
    serializer_class = EntrySerializer
    pagination_class = EntryCursorPagination

    def get_queryset(self):
        account = get_object_or_404(Account, id=self.kwargs["account_id"])
        return Entry.objects.filter(account=account)


class DistributionsView(FundScoped):
    required_role = Role.OPERATOR

    def post(self, request: Request, fund_id: UUID) -> Response:
        key = idempotency_key(request)
        get_object_or_404(Fund, id=fund_id)
        body = DistributionRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        distribution, created = with_deadlock_retry(
            lambda: create_distribution(
                fund_id=fund_id,
                idempotency_key=key,
                created_by=actor(request),
                **body.validated_data,
            )
        )
        return created_or_replayed(DistributionSerializer(distribution).data, created)


class ReverseTransferView(TransferScoped):
    required_role = Role.OPERATOR

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
            lambda: reverse_transfer(
                transfer_id=original.id,
                idempotency_key=key,
                period=period,
                created_by=actor(request),
            )
        )
        return created_or_replayed(TransferSerializer(reversal).data, created)


class ClosePeriodView(FundScoped):
    required_role = Role.CONTROLLER

    def post(self, request: Request, fund_id: UUID, period_id: UUID) -> Response:
        period, _ = close_period(fund_id=fund_id, period_id=period_id, closed_by=actor(request))
        return Response(PeriodSerializer(period).data)


class LPStatementView(FundScoped):
    required_role = Role.LP
    renderer_classes = [JSONRenderer, CSVRenderer]

    def get(self, request: Request, fund_id: UUID, lp_id: UUID) -> Response:
        fund = get_object_or_404(Fund, id=fund_id)
        lp = get_object_or_404(LimitedPartner, id=lp_id)
        membership = membership_of(request)
        if membership.role == Role.LP and membership.lp_id != lp.id:
            raise NotFound()  # same answer as a non-existent LP: don't confirm other LPs exist
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


class FundReconciliationView(FundScoped):
    required_role = Role.VIEWER

    def get(self, request: Request, fund_id: UUID) -> Response:
        fund = get_object_or_404(Fund, id=fund_id)
        imbalance = fund_imbalance(fund.id)
        broken = unbalanced_transfers(fund_id=fund.id)
        return Response(
            {
                "fund": str(fund.id),
                "balanced": imbalance == 0 and not broken,
                "imbalance": format(imbalance, "f"),
                "unbalanced_transfers": [
                    {"transfer": str(t), "imbalance": format(amount, "f")} for t, amount in broken
                ],
            }
        )


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        if not request.user.is_authenticated:  # IsAuthenticated guarantees this; narrows the type
            raise NotAuthenticated()
        memberships = FundMembership.objects.filter(user=request.user).select_related("fund")
        return Response(
            {
                "username": actor(request),
                "memberships": [
                    {
                        "fund": str(m.fund_id),
                        "fund_name": m.fund.name,
                        "role": m.role,
                        "lp": str(m.lp_id) if m.lp_id else None,
                    }
                    for m in memberships.order_by("fund__name")
                ],
            }
        )
