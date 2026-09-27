from datetime import date

from funds.models import Fund, Period
from operations.errors import NoPeriod


def period_for(fund: Fund, on_date: date) -> Period:
    period = Period.objects.filter(
        fund=fund, start_date__lte=on_date, end_date__gte=on_date
    ).first()
    if period is None:
        raise NoPeriod(f"no accounting period covers {on_date}")
    return period
