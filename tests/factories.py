from datetime import date
from itertools import count

from django.utils import timezone

from funds.models import Fund, LimitedPartner, Period
from ledger.models import Account, AccountType

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