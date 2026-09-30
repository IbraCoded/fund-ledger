from collections.abc import Iterable
from decimal import Decimal
from uuid import UUID

from django.db.models import Sum

from ledger.models import Account, Entry, TransferType
from ledger.queries import EFFECTIVE_TYPE, ZERO


def contributed_by_account(lp_accounts: Iterable[Account]) -> dict[UUID, Decimal]:
    """Net capital each LP has paid in, keyed by account id, in one grouped query.

    Capital calls run this under the fund lock, so one query rather than one per LP keeps
    the lock short. Accounts with no contributions map to zero.
    """
    ids = [a.id for a in lp_accounts]
    totals = dict(
        Entry.objects.filter(account_id__in=ids)
        .annotate(effective_type=EFFECTIVE_TYPE)
        .filter(effective_type=TransferType.CAPITAL_CALL)
        .values("account_id")
        .annotate(t=Sum("signed_base_amount"))
        .values_list("account_id", "t")
    )
    return {i: -(totals.get(i) or ZERO) for i in ids}  # LP capital is credit-normal


def contributed(lp_account: Account) -> Decimal:
    """Net capital an LP has paid in, including the effect of reversed calls."""
    return contributed_by_account([lp_account])[lp_account.id]
