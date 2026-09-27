from datetime import date
from decimal import Decimal
from itertools import count
from types import SimpleNamespace

from django.utils import timezone

from funds.models import Commitment, Fund, LimitedPartner, Period
from ledger.legs import Leg
from ledger.models import Account, AccountType
from ledger.services import post_transfer
from operations.chart import open_fund_accounts

# A simple counter to generate unique names for test objects.
_seq = count(1)


def make_fund(*, base_currency: str = "GBP") -> Fund:
    n = next(_seq)
    return Fund.objects.create(
        name=f"Test Fund {n}",
        base_currency=base_currency,
        vintage_year=2026,
        inception_date=date(2026, 1, 1),
    )


def make_period(
    fund: Fund,
    *,
    start: date = date(2026, 1, 1),
    end: date = date(2026, 12, 31),
    status: str = "OPEN",
) -> Period:
    return Period.objects.create(
        fund=fund,
        start_date=start,
        end_date=end,
        status=status,
        closed_at=timezone.now() if status == "CLOSED" else None,
    )


def make_lp(name: str | None = None) -> LimitedPartner:
    return LimitedPartner.objects.create(name=name or f"LP {next(_seq)}", investor_type="PENSION")


def make_account(
    fund: Fund,
    *,
    account_type: str = AccountType.CASH,
    currency: str | None = None,
    lp: LimitedPartner | None = None,
    code: str | None = None,
) -> Account:
    return Account.objects.create(
        fund=fund,
        account_type=account_type,
        currency=currency or fund.base_currency,
        owner_lp=lp,
        code=code or f"{account_type}-{next(_seq)}",
    )


def two_legs(src: Account, dst: Account, amount: Decimal) -> list[Leg]:
    """Move `amount` from src to dst: credit the source, debit the destination."""
    return [Leg(src.id, "CREDIT", amount), Leg(dst.id, "DEBIT", amount)]


def fund_accounts(
    period: Period, source: Account, accounts: list[Account], amount: Decimal
) -> None:
    for account in accounts:
        post_transfer(
            idempotency_key=f"fund-{account.id}",
            legs=two_legs(source, account, amount),
            period=period,
            transfer_type="ADJUSTMENT",
        )


AWKWARD_COMMITMENTS = [
    Decimal(x)
    for x in (
        "47300000",
        "12125000",
        "33333333.33",
        "5000000",
        "8750000",
        "21000000",
        "1000000",
        "15500000",
        "9999999.99",
        "2750000",
    )
]


def build_pe_fund(commitments: list[Decimal] = AWKWARD_COMMITMENTS) -> SimpleNamespace:
    """A fund with LPs, commitments, two half-year periods and a full chart of accounts."""
    fund = make_fund()
    lps = []
    for amount in commitments:
        lp = make_lp()
        Commitment.objects.create(
            fund=fund, lp=lp, committed_amount=amount, signed_date=date(2025, 12, 1)
        )
        lps.append(lp)
    h1 = make_period(fund, start=date(2026, 1, 1), end=date(2026, 6, 30))
    h2 = make_period(fund, start=date(2026, 7, 1), end=date(2026, 12, 31))
    open_fund_accounts(fund)
    return SimpleNamespace(fund=fund, lps=lps, h1=h1, h2=h2)
