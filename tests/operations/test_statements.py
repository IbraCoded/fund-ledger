from datetime import date
from decimal import Decimal as D

import pytest

from operations.services import (
    charge_fee,
    create_capital_call,
    create_distribution,
    record_investment,
    record_valuation,
)
from operations.statements import lp_statement, nav, snapshot_nav

pytestmark = pytest.mark.django_db


@pytest.fixture
def scenario(pe):
    """H1: call 1m, invest 600k, fee 20k. H2: +150k valuation, distribute 300k."""
    f = pe.fund.id
    create_capital_call(fund_id=f, idempotency_key="call", total_amount=D("1000000.00"),
                        notice_date=date(2026, 2, 1), due_date=date(2026, 2, 15))
    record_investment(fund_id=f, idempotency_key="inv", amount=D("600000.00"),
                      currency="GBP", on_date=date(2026, 3, 1))
    charge_fee(fund_id=f, idempotency_key="fee", amount=D("20000.00"), on_date=date(2026, 6, 30))
    record_valuation(fund_id=f, idempotency_key="val", change=D("150000.00"), on_date=date(2026, 9, 30))
    create_distribution(fund_id=f, idempotency_key="dist", total_amount=D("300000.00"),
                        payment_date=date(2026, 10, 15), classification="GAIN")
    return pe


def _statements(pe, period):
    return [lp_statement(fund=pe.fund, lp=lp, period=period) for lp in pe.lps]


def test_each_statement_is_internally_consistent_and_chains(scenario):
    for s1, s2 in zip(_statements(scenario, scenario.h1), _statements(scenario, scenario.h2), strict=True):
        assert s1.opening_balance == 0
        assert s2.opening_balance == s1.closing_balance
        for s in (s1, s2):
            assert s.closing_balance == (
                s.opening_balance + s.contributions - s.distributions
                + s.other_adjustments + s.allocated_gains - s.allocated_fees
            )
        assert s2.unfunded_commitment == s2.commitment - s2.contributed_to_date


def test_per_lp_lines_add_up_to_fund_totals(scenario):
    h1, h2 = _statements(scenario, scenario.h1), _statements(scenario, scenario.h2)
    assert sum(s.contributions for s in h1) == D("1000000.00")
    assert sum(s.allocated_fees for s in h1) == D("20000.00")
    assert sum(s.allocated_gains for s in h2) == D("150000.00")
    assert sum(s.distributions for s in h2) == D("300000.00")


def test_partners_capital_equals_nav(scenario):
    """The accounting equation, end to end: Σ LP capital == assets."""
    assert sum(s.closing_balance for s in _statements(scenario, scenario.h1)) == nav(
        scenario.fund, through_period=scenario.h1
    ) == D("980000.00")
    assert sum(s.closing_balance for s in _statements(scenario, scenario.h2)) == nav(
        scenario.fund, through_period=scenario.h2
    ) == D("830000.00")


def test_nav_snapshot_is_upserted(scenario):
    first = snapshot_nav(scenario.fund, scenario.h2)
    again = snapshot_nav(scenario.fund, scenario.h2)
    assert first.id == again.id and again.total_nav == D("830000.00")


def test_zero_valuation_is_rejected(pe):
    from ledger.errors import InvalidTransfer

    with pytest.raises(InvalidTransfer):
        record_valuation(fund_id=pe.fund.id, idempotency_key="z", change=D("0"), on_date=date(2026, 3, 1))
