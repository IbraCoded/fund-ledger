"""Capital account statements and NAV. Everything here is derived from entries."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from django.db.models import Sum
from django.utils import timezone

from funds.models import Commitment, Fund, LimitedPartner, NavSnapshot, Period
from ledger.models import Account, AccountType, Entry, TransferType
from ledger.queries import EFFECTIVE_TYPE, ZERO
from operations.allocation import allocate
from operations.chart import lp_capital_accounts

FOUR_DP = Decimal("0.0001")


@dataclass
class Movement:
    contributions: Decimal = ZERO
    distributions: Decimal = ZERO
    other: Decimal = ZERO
    allocated_gains: Decimal = ZERO
    allocated_fees: Decimal = ZERO

    @property
    def net(self) -> Decimal:
        return (
            self.contributions - self.distributions + self.other
            + self.allocated_gains - self.allocated_fees
        )


@dataclass(frozen=True)
class CapitalAccountStatement:
    fund_id: UUID
    lp_id: UUID
    lp_name: str
    period_start: date
    period_end: date
    currency: str
    opening_balance: Decimal
    contributions: Decimal
    distributions: Decimal
    other_adjustments: Decimal
    allocated_gains: Decimal
    allocated_fees: Decimal
    closing_balance: Decimal
    commitment: Decimal
    contributed_to_date: Decimal
    unfunded_commitment: Decimal

    def as_dict(self) -> dict[str, str]:
        """Strings throughout: Decimals must never be serialised as floats."""
        return {k: format(v, "f") if isinstance(v, Decimal) else str(v) for k, v in asdict(self).items()}


def _lp_ledger_movement(lp_account: Account, period: Period) -> Movement:
    rows = (
        Entry.objects.filter(account=lp_account, transfer__period=period)
        .annotate(effective_type=EFFECTIVE_TYPE)
        .values("effective_type")
        .annotate(total=Sum("signed_base_amount"))
    )
    movement = Movement()
    for row in rows:
        credit_positive = -row["total"]  # LP capital is credit-normal
        if row["effective_type"] == TransferType.CAPITAL_CALL:
            movement.contributions += credit_positive
        elif row["effective_type"] == TransferType.DISTRIBUTION:
            movement.distributions -= credit_positive
        else:
            movement.other += credit_positive
    return movement


def _fund_total(fund: Fund, period: Period, account_type: str) -> Decimal:
    return (
        Entry.objects.filter(
            account__fund=fund, account__account_type=account_type, transfer__period=period
        ).aggregate(t=Sum("signed_base_amount"))["t"]
        or ZERO
    )


def lp_statement(*, fund: Fund, lp: LimitedPartner, period: Period) -> CapitalAccountStatement:
    commitments = {c.lp_id: c.committed_amount for c in Commitment.objects.filter(fund=fund)}
    if lp.id not in commitments:
        raise Commitment.DoesNotExist(f"{lp} has no commitment to {fund}")
    lp_account = lp_capital_accounts(fund)[lp.id]

    opening = ZERO
    contributed_to_date = ZERO
    current = Movement()
    for p in Period.objects.filter(fund=fund, start_date__lte=period.start_date).order_by("start_date"):
        movement = _lp_ledger_movement(lp_account, p)
        gains = -_fund_total(fund, p, AccountType.GAIN_LOSS)  # credit-normal
        fees = _fund_total(fund, p, AccountType.FEE_EXPENSE)  # debit-normal
        movement.allocated_gains = allocate(gains, commitments, quantum=FOUR_DP)[lp.id]
        movement.allocated_fees = allocate(fees, commitments, quantum=FOUR_DP)[lp.id]
        contributed_to_date += movement.contributions
        if p.id == period.id:
            current = movement
        else:
            opening += movement.net

    commitment = commitments[lp.id]
    return CapitalAccountStatement(
        fund_id=fund.id,
        lp_id=lp.id,
        lp_name=lp.name,
        period_start=period.start_date,
        period_end=period.end_date,
        currency=fund.base_currency,
        opening_balance=opening,
        contributions=current.contributions,
        distributions=current.distributions,
        other_adjustments=current.other,
        allocated_gains=current.allocated_gains,
        allocated_fees=current.allocated_fees,
        closing_balance=opening + current.net,
        commitment=commitment,
        contributed_to_date=contributed_to_date,
        unfunded_commitment=commitment - contributed_to_date,
    )


def nav(fund: Fund, *, through_period: Period | None = None) -> Decimal:
    """Net asset value: cash plus investments, in base currency (no liabilities modelled)."""
    qs = Entry.objects.filter(
        account__fund=fund, account__account_type__in=[AccountType.CASH, AccountType.INVESTMENT]
    )
    if through_period is not None:
        qs = qs.filter(transfer__period__start_date__lte=through_period.start_date)
    return qs.aggregate(t=Sum("signed_base_amount"))["t"] or ZERO


def snapshot_nav(fund: Fund, period: Period) -> NavSnapshot:
    snapshot, _ = NavSnapshot.objects.update_or_create(
        fund=fund,
        as_of_date=period.end_date,
        defaults={"total_nav": nav(fund, through_period=period), "computed_at": timezone.now()},
    )
    return snapshot
