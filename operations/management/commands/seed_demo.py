import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from funds.models import Commitment, Fund, FxRate, LimitedPartner, Period
from operations.chart import open_fund_accounts
from operations.services import (
    charge_fee,
    create_capital_call,
    create_distribution,
    record_investment,
    record_valuation,
)

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
        open_fund_accounts(fund)
        self.history(fund)
        self.stdout.write(self.style.SUCCESS(f"Demo fund ready: {fund.name} ({fund.id})"))

    def history(self, fund: Fund) -> None:
        """A year of fund activity. Fixed idempotency keys make re-runs replay, not duplicate."""
        f = fund.id
        create_capital_call(
            fund_id=f,
            idempotency_key="demo:call:1",
            total_amount=Decimal("25000000.00"),
            notice_date=date(2026, 1, 15),
            due_date=date(2026, 1, 29),
        )
        record_investment(
            fund_id=f,
            idempotency_key="demo:invest:1",
            amount=Decimal("15000000.00"),
            currency="USD",
            on_date=date(2026, 2, 10),
        )
        charge_fee(
            fund_id=f,
            idempotency_key="demo:fee:q1",
            amount=Decimal("412500.00"),
            on_date=date(2026, 3, 31),
        )
        create_capital_call(
            fund_id=f,
            idempotency_key="demo:call:2",
            total_amount=Decimal("10000000.00"),
            notice_date=date(2026, 4, 15),
            due_date=date(2026, 4, 29),
        )
        record_valuation(
            fund_id=f,
            idempotency_key="demo:valuation:q2",
            change=Decimal("1850000.00"),
            on_date=date(2026, 6, 30),
        )
        create_distribution(
            fund_id=f,
            idempotency_key="demo:dist:1",
            total_amount=Decimal("3000000.00"),
            payment_date=date(2026, 7, 20),
            classification="GAIN",
        )

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
