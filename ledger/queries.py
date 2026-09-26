from datetime import datetime
from decimal import Decimal
from uuid import UUID

from django.db.models import QuerySet, Sum

from ledger.models import Entry

ZERO = Decimal("0")


def _entries(account_id: UUID, as_of: datetime | None) -> QuerySet[Entry]:
    qs = Entry.objects.filter(account_id=account_id)
    if as_of is not None:
        qs = qs.filter(created_at__lte=as_of)
    return qs


def native_balance(account_id: UUID, *, as_of: datetime | None = None) -> Decimal:
    """Balance in the account's own currency, debit-positive.

    "How many dollars are in the USD account?" This is what overdraft checks use.
    """
    return _entries(account_id, as_of).aggregate(t=Sum("signed_amount"))["t"] or ZERO


def base_balance(account_id: UUID, *, as_of: datetime | None = None) -> Decimal:
    """Balance in the fund's base currency, at the rates captured when each entry was booked."""
    return _entries(account_id, as_of).aggregate(t=Sum("signed_base_amount"))["t"] or ZERO
