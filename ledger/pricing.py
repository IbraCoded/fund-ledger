from collections.abc import Sequence
from datetime import date
from uuid import UUID

from ledger.errors import InvalidTransfer
from ledger.legs import Leg, PricedLeg
from ledger.models import Account


def price_legs(
    legs: Sequence[Leg],
    accounts: dict[UUID, Account],
    *,
    base_currency: str,
    fx_date: date,
) -> list[PricedLeg]:
    priced = []
    for leg in legs:
        account = accounts[leg.account_id]
        if account.currency != base_currency:
            raise InvalidTransfer(
                f"{account.currency} account on a {base_currency} fund; FX pricing not implemented yet"
            )
        priced.append(
            PricedLeg(
                account=account,
                direction=leg.direction,
                amount=leg.amount,
                currency=account.currency,
                fx_rate=None,
                base_amount=leg.amount if leg.base_amount is None else leg.base_amount,
            )
        )
    return priced
