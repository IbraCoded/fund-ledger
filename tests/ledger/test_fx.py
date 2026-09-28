from datetime import date
from decimal import Decimal as D

import pytest

from funds.models import FxRate
from ledger.errors import MissingFxRate, UnbalancedTransfer
from ledger.legs import Leg
from ledger.models import AccountType
from ledger.queries import base_balance, native_balance
from ledger.reconciliation import total_imbalance
from ledger.services import post_transfer, reverse_transfer
from tests.factories import fund_accounts, make_account

pytestmark = pytest.mark.django_db


@pytest.fixture
def usd(world):
    FxRate.objects.create(
        from_currency="USD", to_currency="GBP", rate=D("0.79"), as_of_date=date(2026, 1, 1)
    )
    fund_accounts(world.period, world.equity, [world.cash], D("100000"))
    return make_account(world.fund, account_type=AccountType.INVESTMENT, currency="USD")


def _buy(world, usd, fx_date=date(2026, 3, 1), usd_amount=D("100"), gbp_amount=D("79"), key="buy"):
    return post_transfer(
        idempotency_key=key,
        legs=[Leg(usd.id, "DEBIT", usd_amount), Leg(world.cash.id, "CREDIT", gbp_amount)],
        period=world.period,
        transfer_type="INVESTMENT",
        fx_date=fx_date,
    )


def test_cross_currency_transfer_captures_the_rate(world, usd):
    transfer = _buy(world, usd)
    entry = transfer.entries.get(account=usd)
    assert (entry.currency, entry.fx_rate, entry.base_amount) == ("USD", D("0.79"), D("79.0000"))
    assert native_balance(usd.id) == D("100")
    assert base_balance(usd.id) == D("79")
    assert total_imbalance() == 0


def test_later_rate_changes_never_rewrite_history(world, usd):
    _buy(world, usd)
    FxRate.objects.create(
        from_currency="USD", to_currency="GBP", rate=D("0.95"), as_of_date=date(2026, 6, 1)
    )
    FxRate.objects.filter(as_of_date=date(2026, 1, 1)).update(rate=D("0.50"))
    assert base_balance(usd.id) == D("79")


def test_uses_latest_rate_on_or_before_the_date(world, usd):
    FxRate.objects.create(
        from_currency="USD", to_currency="GBP", rate=D("0.85"), as_of_date=date(2026, 6, 1)
    )
    early = _buy(world, usd, fx_date=date(2026, 5, 31), key="early")
    late = _buy(world, usd, fx_date=date(2026, 7, 1), gbp_amount=D("85"), key="late")
    assert early.entries.get(account=usd).fx_rate == D("0.79")
    assert late.entries.get(account=usd).fx_rate == D("0.85")


def test_missing_rate_is_an_error(world, usd):
    with pytest.raises(MissingFxRate):
        _buy(world, usd, fx_date=date(2025, 12, 31))


def test_genuinely_unbalanced_fx_transfer_is_still_rejected(world, usd):
    with pytest.raises(UnbalancedTransfer):
        _buy(world, usd, gbp_amount=D("70"))


def test_rounding_residual_is_absorbed_by_the_largest_leg(world):
    FxRate.objects.create(
        from_currency="CHF", to_currency="GBP", rate=D("1.5"), as_of_date=date(2026, 1, 1)
    )
    holding = make_account(world.fund, account_type=AccountType.INVESTMENT, currency="CHF")
    source = make_account(world.fund, account_type=AccountType.GP_CAPITAL, currency="CHF")
    # 10.0003 CHF → 15.00045 → 15.0004 (half-even); each 0.0001 CHF → 0.00015 → 0.0002.
    # Credits total 15.0000 + 3 × 0.0002 = 15.0006: a 0.0002 residual to absorb.
    legs = [Leg(holding.id, "DEBIT", D("10.0003")), Leg(source.id, "CREDIT", D("10.0000"))]
    legs += [Leg(source.id, "CREDIT", D("0.0001")) for _ in range(3)]
    transfer = post_transfer(
        idempotency_key="rounding",
        legs=legs,
        period=world.period,
        transfer_type="ADJUSTMENT",
        fx_date=date(2026, 3, 1),
    )
    assert transfer.entries.get(direction="DEBIT").base_amount == D("15.0006")
    assert total_imbalance() == 0


def test_reversal_uses_the_original_rate_not_todays(world, usd):
    original = _buy(world, usd)
    FxRate.objects.create(
        from_currency="USD", to_currency="GBP", rate=D("0.95"), as_of_date=date(2026, 3, 2)
    )
    reverse_transfer(transfer_id=original.id, idempotency_key="undo", period=world.period)
    assert native_balance(usd.id) == 0
    assert base_balance(usd.id) == 0  # would be −16 if re-priced at 0.95
