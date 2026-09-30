"""A fresh, empty fund for public experiments: one per day, never deleted."""

from datetime import date
from decimal import Decimal

from funds.models import Commitment, Fund, LimitedPartner, Period
from operations.chart import open_fund_accounts
from operations.management.commands.seed_demo import demo_id, quarters

SANDBOX_LPS = [
    ("Sandbox Pension Scheme", "PENSION", "6000000.00"),
    ("Sandbox Endowment", "ENDOWMENT", "3333333.33"),
    ("Sandbox Family Office", "FAMILY_OFFICE", "1000000.00"),
]


def open_sandbox_fund(day: date) -> Fund:
    """Create (or fetch) the sandbox fund for `day`. Idempotent: same day, same fund."""
    fund, _ = Fund.objects.get_or_create(
        id=demo_id(f"sandbox:{day.isoformat()}"),
        defaults={
            "name": f"Sandbox {day.isoformat()}",
            "base_currency": "GBP",
            "vintage_year": day.year,
            "inception_date": date(day.year, 1, 1),
        },
    )
    for name, investor_type, amount in SANDBOX_LPS:
        lp, _ = LimitedPartner.objects.get_or_create(
            id=demo_id(f"sandbox-lp:{name}"),
            defaults={"name": name, "investor_type": investor_type},
        )
        Commitment.objects.get_or_create(
            fund=fund,
            lp=lp,
            defaults={"committed_amount": Decimal(amount), "signed_date": fund.inception_date},
        )
    for start, end in quarters(day.year, day.year + 1):
        Period.objects.get_or_create(fund=fund, start_date=start, defaults={"end_date": end})
    open_fund_accounts(fund)
    return fund
