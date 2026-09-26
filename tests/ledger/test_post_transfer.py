from datetime import date
from decimal import Decimal as D

import pytest

from ledger.errors import (
    ClosedPeriod,
    InsufficientFunds,
    InvalidTransfer,
    UnbalancedTransfer,
    UnknownAccount,
)
from ledger.legs import Leg
from ledger.models import Entry, Transfer
from ledger.queries import native_balance
from ledger.reconciliation import total_imbalance, unbalanced_transfers
from ledger.services import post_transfer
from tests.factories import make_account, make_fund, make_period, two_legs

pytestmark = pytest.mark.django_db


def _post(world, legs, key="t-1", period=None):
    return post_transfer(
        idempotency_key=key,
        legs=legs,
        period=period or world.period,
        transfer_type="ADJUSTMENT",
    )


def test_posts_a_balanced_transfer_and_balances_are_derived(world):
    transfer = _post(world, two_legs(world.equity, world.cash, D("250.00")))
    assert transfer.entries.count() == 2
    assert native_balance(world.cash.id) == D("250.00")
    assert native_balance(world.equity.id) == D("-250.00")  # credit-normal: negative when signed
    assert total_imbalance() == 0
    assert unbalanced_transfers() == []


@pytest.mark.parametrize(
    ("amount", "message"),
    [
        (10.0, "Decimal"),
        (D("0"), "positive"),
        (D("-1"), "positive"),
        (D("NaN"), "positive"),
        (D("1.00001"), "4 decimal places"),
    ],
)
def test_rejects_bad_amounts(world, amount, message):
    legs = [Leg(world.equity.id, "CREDIT", amount), Leg(world.cash.id, "DEBIT", amount)]
    with pytest.raises(InvalidTransfer, match=message):
        _post(world, legs)
    assert not Entry.objects.exists()


def test_rejects_single_leg_and_one_sided_transfers(world):
    with pytest.raises(InvalidTransfer, match="two legs"):
        _post(world, [Leg(world.cash.id, "DEBIT", D("1"))])
    with pytest.raises(InvalidTransfer, match="one debit and one credit"):
        _post(world, [Leg(world.cash.id, "DEBIT", D("1")), Leg(world.equity.id, "DEBIT", D("1"))])


def test_rejects_unbalanced_legs_and_writes_nothing(world):
    legs = [Leg(world.equity.id, "CREDIT", D("100")), Leg(world.cash.id, "DEBIT", D("99"))]
    with pytest.raises(UnbalancedTransfer):
        _post(world, legs)
    assert not Transfer.objects.exists()


def test_rejects_overdrawing_cash(world):
    _post(world, two_legs(world.equity, world.cash, D("50")))
    other = make_account(world.fund)
    with pytest.raises(InsufficientFunds):
        _post(world, two_legs(world.cash, other, D("50.01")), key="t-2")
    assert native_balance(world.cash.id) == D("50")


def test_credit_normal_accounts_are_not_guarded(world):
    # GP_CAPITAL starts at zero and goes "negative" in signed terms: that's normal.
    _post(world, two_legs(world.equity, world.cash, D("1000")))


def test_rejects_closed_period(world):
    closed = make_period(
        world.fund, start=date(2025, 1, 1), end=date(2025, 12, 31), status="CLOSED"
    )
    with pytest.raises(ClosedPeriod):
        _post(world, two_legs(world.equity, world.cash, D("1")), period=closed)


def test_rejects_accounts_from_another_fund(world):
    stranger = make_account(make_fund())
    with pytest.raises(InvalidTransfer, match="do not belong"):
        _post(world, two_legs(world.equity, stranger, D("1")))


def test_rejects_unknown_account(world):
    ghost = make_account(make_fund())
    legs = two_legs(world.equity, ghost, D("1"))
    ghost.delete()  # accounts are deletable while they have no entries
    with pytest.raises(UnknownAccount):
        _post(world, legs)


def test_point_in_time_balance(world):
    first = _post(world, two_legs(world.equity, world.cash, D("100")), key="t-1")
    cutoff = Entry.objects.filter(transfer=first).values_list("created_at", flat=True)[0]
    _post(world, two_legs(world.equity, world.cash, D("40")), key="t-2")
    assert native_balance(world.cash.id, as_of=cutoff) == D("100")
    assert native_balance(world.cash.id) == D("140")
