from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from ledger.models import Account


@dataclass(frozen=True)
class Leg:
    """One side of a transfer, as requested by a caller."""

    account_id: UUID
    direction: str  # "DEBIT" or "CREDIT"
    amount: Decimal  # in the account's own currency, > 0
    fx_rate: Decimal | None = None  # override; used by reversals
    base_amount: Decimal | None = None  # override; used by reversals


@dataclass(frozen=True)
class PricedLeg:
    """A leg once we know its account, currency and value in the fund's base currency."""

    account: Account
    direction: str
    amount: Decimal
    currency: str
    fx_rate: Decimal | None
    base_amount: Decimal
    adjustable: bool = False  # may absorb an FX rounding residual
