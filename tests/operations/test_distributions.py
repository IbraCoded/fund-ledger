from datetime import date
from decimal import Decimal as D

import pytest

from ledger.errors import InsufficientFunds
from ledger.models import AccountType
from ledger.queries import native_balance
from ledger.reconciliation import total_imbalance
from operations.chart import get_account, lp_capital_accounts
from operations.models import Distribution
from operations.services import create_capital_call, create_distribution

pytestmark = pytest.mark.django_db


@pytest.fixture
def called(pe):
    create_capital_call(
        fund_id=pe.fund.id,
        idempotency_key="call-1",
        total_amount=D("1000000.00"),
        notice_date=date(2026, 2, 1),
        due_date=date(2026, 2, 15),
    )
    return pe


def _distribute(pe, amount, key="dist-1"):
    return create_distribution(
        fund_id=pe.fund.id,
        idempotency_key=key,
        total_amount=D(amount),
        payment_date=date(2026, 8, 1),
        classification="GAIN",
    )


def test_distribution_reduces_cash_and_lp_capital(called):
    distribution, _ = _distribute(called, "250000.00")
    assert distribution.classification == "GAIN"
    assert native_balance(get_account(called.fund, AccountType.CASH).id) == D("750000.00")
    lp_total = sum(-native_balance(a.id) for a in lp_capital_accounts(called.fund).values())
    assert lp_total == D("750000.00")
    assert total_imbalance() == 0


def test_cannot_distribute_more_cash_than_the_fund_holds(called):
    with pytest.raises(InsufficientFunds):
        _distribute(called, "1000000.01")
    assert not Distribution.objects.exists()


def test_distribution_numbers_increment(called):
    first, _ = _distribute(called, "1.00", key="d1")
    second, _ = _distribute(called, "1.00", key="d2")
    assert (first.distribution_number, second.distribution_number) == (1, 2)
