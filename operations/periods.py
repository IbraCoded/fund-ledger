from datetime import date
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from funds.models import Fund, Period, PeriodStatus
from ledger.reconciliation import period_imbalance
from operations.errors import NoPeriod, PeriodNotClosable

def period_for(fund: Fund, on_date: date) -> Period:
    period = Period.objects.filter(
        fund=fund, start_date__lte=on_date, end_date__gte=on_date
    ).first()
    if period is None:
        raise NoPeriod(f"no accounting period covers {on_date}")
    return period


def close_period(*, fund_id: UUID, period_id: UUID) -> tuple[Period, bool]:
    """Close a period. Returns (period, changed). Closing a closed period is a no-op."""
    with transaction.atomic():
        # FOR UPDATE waits for every in-flight posting holding FOR SHARE on this row.
        period = Period.objects.select_for_update().get(id=period_id, fund_id=fund_id)
        if period.status == PeriodStatus.CLOSED:
            return period, False
        if Period.objects.filter(
            fund_id=fund_id, start_date__lt=period.start_date, status=PeriodStatus.OPEN
        ).exists():
            raise PeriodNotClosable("close earlier periods first")
        imbalance = period_imbalance(period.id)
        if imbalance != 0:
            raise PeriodNotClosable(f"period does not reconcile (imbalance {imbalance})")
        period.status = PeriodStatus.CLOSED
        period.closed_at = timezone.now()
        period.save(update_fields=["status", "closed_at"])
    return period, True
