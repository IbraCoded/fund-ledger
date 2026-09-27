from decimal import Decimal

from django.db.models import Sum

from ledger.models import Account, Entry, TransferType
from ledger.queries import EFFECTIVE_TYPE, ZERO


def contributed(lp_account: Account) -> Decimal:
    """Net capital an LP has paid in, including the effect of reversed calls."""
    total = (
        Entry.objects.filter(account=lp_account)
        .annotate(effective_type=EFFECTIVE_TYPE)
        .filter(effective_type=TransferType.CAPITAL_CALL)
        .aggregate(t=Sum("signed_base_amount"))["t"]
    )
    return -(total or ZERO)  # LP capital is credit-normal
