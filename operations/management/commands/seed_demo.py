import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from funds.models import Commitment, Fund, FxRate, LimitedPartner, Period

DEMO_NS = uuid.UUID("6f1c6a8e-3b7d-4c55-9a0e-2f4f7b1d9c10")

# Deliberately awkward numbers: pro-rata splits of these never divide evenly.
DEMO_LPS = [
    ("Clydeside Pension Scheme", "PENSION", "47300000.00"),
    ("Forth Valley Endowment", "ENDOWMENT", "12125000.00"),
    ("Northern Lights Sovereign Fund", "SOVEREIGN_WEALTH", "33333333.33"),
    ("Kelvin Family Office", "FAMILY_OFFICE", "5000000.00"),
    ("Merchant City Fund of Funds", "FUND_OF_FUNDS", "8750000.00"),
    ("Caledonian Mutual", "INSURANCE", "21000000.00"),
    ("Strathclyde Alumni Trust", "ENDOWMENT", "1000000.00"),
    ("Tay Bridge Pension", "PENSION", "15500000.00"),
    ("Arran Capital Partners", "FUND_OF_FUNDS", "9999999.99"),
    ("Lomond Family Office", "FAMILY_OFFICE", "2750000.00"),
]


def demo_id(name: str) -> uuid.UUID:
    return uuid.uuid5(DEMO_NS, name)


def quarters(*years: int) -> Iterator[tuple[date, date]]:
    for year in years:
        for month in (1, 4, 7, 10):
            start = date(year, month, 1)
            next_start = date(year + 1, 1, 1) if month == 10 else date(year, month + 3, 1)
            yield start, next_start - timedelta(days=1)


class Command(BaseCommand):
    help = "Create a deterministic demo fund. Safe to run repeatedly."

    def handle(self, *args, **options):
        fund = self.reference_data()
        self.stdout.write(self.style.SUCCESS(f"Demo fund ready: {fund.name} ({fund.id})"))

    @transaction.atomic
    def reference_data(self) -> Fund:
        fund, _ = Fund.objects.get_or_create(
            id=demo_id("fund"),
            defaults={
                "name": "Glasgow Growth Partners I",
                "base_currency": "GBP",
                "vintage_year": 2026,
                "inception_date": date(2026, 1, 1),
            },
        )
        for name, investor_type, amount in DEMO_LPS:
            lp, _ = LimitedPartner.objects.get_or_create(
                id=demo_id(f"lp:{name}"), defaults={"name": name, "investor_type": investor_type}
            )
            Commitment.objects.get_or_create(
                fund=fund,
                lp=lp,
                defaults={"committed_amount": Decimal(amount), "signed_date": date(2025, 12, 1)},
            )
        for start, end in quarters(2026, 2027):
            Period.objects.get_or_create(fund=fund, start_date=start, defaults={"end_date": end})
        for ccy, rate in (("USD", "0.7900000000"), ("EUR", "0.8500000000")):
            FxRate.objects.get_or_create(
                from_currency=ccy,
                to_currency="GBP",
                as_of_date=date(2026, 1, 1),
                defaults={"rate": Decimal(rate)},
            )
        return fund
