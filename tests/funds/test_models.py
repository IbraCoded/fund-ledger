from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from funds.models import Commitment, Fund, FxRate, LimitedPartner, Period

pytestmark = pytest.mark.django_db


def _fund(name: str = "Fund I", currency: str = "GBP") -> Fund:
    return Fund.objects.create(
        name=name, base_currency=currency, vintage_year=2026, inception_date=date(2026, 1, 1)
    )


@pytest.mark.parametrize("currency", ["gbp", "GB", "G1P"])
def test_fund_currency_must_be_iso4217(currency):
    with pytest.raises(IntegrityError), transaction.atomic():
        _fund(currency=currency)


def test_commitment_must_be_positive():
    fund, lp = _fund(), LimitedPartner.objects.create(name="LP", investor_type="PENSION")
    with pytest.raises(IntegrityError), transaction.atomic():
        Commitment.objects.create(
            fund=fund, lp=lp, committed_amount=Decimal("0"), signed_date=date(2026, 1, 1)
        )


def test_one_commitment_per_lp_per_fund():
    fund, lp = _fund(), LimitedPartner.objects.create(name="LP", investor_type="PENSION")
    kwargs = {"fund": fund, "lp": lp, "signed_date": date(2026, 1, 1)}
    Commitment.objects.create(committed_amount=Decimal("100"), **kwargs)
    with pytest.raises(IntegrityError), transaction.atomic():
        Commitment.objects.create(committed_amount=Decimal("200"), **kwargs)


def test_period_end_cannot_precede_start():
    with pytest.raises(IntegrityError), transaction.atomic():
        Period.objects.create(fund=_fund(), start_date=date(2026, 6, 1), end_date=date(2026, 1, 1))


def test_closed_period_requires_closed_at():
    with pytest.raises(IntegrityError), transaction.atomic():
        Period.objects.create(
            fund=_fund(), start_date=date(2026, 1, 1), end_date=date(2026, 3, 31), status="CLOSED"
        )
    Period.objects.create(
        fund=_fund("Fund II"),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 3, 31),
        status="CLOSED",
        closed_at=timezone.now(),
    )


def test_fx_rate_needs_two_different_currencies():
    with pytest.raises(IntegrityError), transaction.atomic():
        FxRate.objects.create(
            from_currency="GBP", to_currency="GBP", rate=Decimal("1"), as_of_date=date(2026, 1, 1)
        )
