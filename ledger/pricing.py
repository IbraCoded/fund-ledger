"""Turn requested legs into priced legs: currency, FX rate and base-currency amount."""

from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from uuid import UUID

from funds.models import FxRate
from ledger.errors import MissingFxRate
from ledger.legs import Leg, PricedLeg
from ledger.models import Account, Direction

FOUR_DP = Decimal("0.0001")


def fx_rate_for(from_currency: str, to_currency: str, on: date) -> Decimal:
    """Latest published rate on or before `on`."""
    rate = (
        FxRate.objects.filter(
            from_currency=from_currency, to_currency=to_currency, as_of_date__lte=on
        )
        .order_by("-as_of_date")
        .values_list("rate", flat=True)
        .first()
    )
    if rate is None:
        raise MissingFxRate(f"no {from_currency}->{to_currency} rate on or before {on}")
    return rate


def convert(amount: Decimal, rate: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 50  # no intermediate rounding before we quantize
        return (amount * rate).quantize(FOUR_DP, rounding=ROUND_HALF_EVEN)


def price_legs(
    legs: Sequence[Leg],
    accounts: dict[UUID, Account],
    *,
    base_currency: str,
    fx_date: date,
) -> list[PricedLeg]:
    rates: dict[str, Decimal] = {}
    priced: list[PricedLeg] = []
    for leg in legs:
        account = accounts[leg.account_id]
        currency = account.currency
        if currency == base_currency:
            fx_rate, base_amount, adjustable = None, leg.amount, False
        else:
            if leg.fx_rate is not None:
                fx_rate = leg.fx_rate
            else:
                if currency not in rates:
                    rates[currency] = fx_rate_for(currency, base_currency, fx_date)
                fx_rate = rates[currency]
            base_amount, adjustable = convert(leg.amount, fx_rate), True
        if leg.base_amount is not None:  # caller-supplied (reversals): use it verbatim
            base_amount, adjustable = leg.base_amount, False
        priced.append(
            PricedLeg(
                account=account,
                direction=leg.direction,
                amount=leg.amount,
                currency=currency,
                fx_rate=fx_rate,
                base_amount=base_amount,
                adjustable=adjustable,
            )
        )
    return _absorb_rounding_residual(priced)


def _absorb_rounding_residual(priced: list[PricedLeg]) -> list[PricedLeg]:
    debits = sum((p.base_amount for p in priced if p.direction == Direction.DEBIT), Decimal(0))
    credits = sum((p.base_amount for p in priced if p.direction == Direction.CREDIT), Decimal(0))
    residual = debits - credits
    if residual == 0:
        return priced
    candidates = [i for i, p in enumerate(priced) if p.adjustable]
    if not candidates or abs(residual) > FOUR_DP * len(candidates):
        return priced  # not a rounding artefact: let _check_balanced reject it
    i = max(candidates, key=lambda j: (priced[j].base_amount, j))
    leg = priced[i]
    adjustment = -residual if leg.direction == Direction.DEBIT else residual
    priced[i] = replace(leg, base_amount=leg.base_amount + adjustment)
    return priced
