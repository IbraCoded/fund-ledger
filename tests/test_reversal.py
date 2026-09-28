from decimal import Decimal as D

import pytest

from ledger.errors import AlreadyReversed, InsufficientFunds, InvalidTransfer
from ledger.models import Entry, Transfer
from ledger.queries import native_balance
from ledger.reconciliation import total_imbalance
from ledger.services import post_transfer, reverse_transfer
from tests.concurrency import run_concurrently
from tests.factories import make_account, two_legs

pytestmark = pytest.mark.django_db


def _post(world, legs, key):
    return post_transfer(
        idempotency_key=key, legs=legs, period=world.period, transfer_type="ADJUSTMENT"
    )


def _reverse(world, transfer, key="rev-1"):
    return reverse_transfer(transfer_id=transfer.id, idempotency_key=key, period=world.period)


def test_reversal_cancels_the_original_without_touching_it(world):
    original = _post(world, two_legs(world.equity, world.cash, D("100")), "t-1")
    before = list(original.entries.values_list("id", "direction", "amount"))

    reversal, created = _reverse(world, original)

    assert created and reversal.reverses_id == original.id
    assert reversal.transfer_type == "REVERSAL"
    assert (
        list(Entry.objects.filter(transfer=original).values_list("id", "direction", "amount"))
        == before
    )
    assert native_balance(world.cash.id) == 0
    assert native_balance(world.equity.id) == 0
    assert total_imbalance() == 0


def test_replay_returns_the_same_reversal(world):
    original = _post(world, two_legs(world.equity, world.cash, D("100")), "t-1")
    first, _ = _reverse(world, original)
    again, created = _reverse(world, original)
    assert not created and again.id == first.id


def test_second_reversal_is_rejected(world):
    original = _post(world, two_legs(world.equity, world.cash, D("100")), "t-1")
    _reverse(world, original, key="rev-1")
    with pytest.raises(AlreadyReversed):
        _reverse(world, original, key="rev-2")


def test_reversals_cannot_be_reversed(world):
    original = _post(world, two_legs(world.equity, world.cash, D("100")), "t-1")
    reversal, _ = _reverse(world, original)
    with pytest.raises(InvalidTransfer):
        _reverse(world, reversal, key="rev-2")


def test_reversal_respects_the_overdraft_guard(world):
    funding = _post(world, two_legs(world.equity, world.cash, D("100")), "fund")
    _post(world, two_legs(world.cash, make_account(world.fund), D("60")), "spend")
    with pytest.raises(InsufficientFunds):
        _reverse(world, funding)  # would take cash to -60


@pytest.mark.django_db(transaction=True)
def test_concurrent_reversals_with_different_keys_produce_one(world):
    _post(world, two_legs(world.equity, world.cash, D("100")), "fund")
    # The original takes cash OUT, so reversing it puts cash back: no overdraft interference.
    original = _post(world, two_legs(world.cash, world.equity, D("40")), "spend")

    def attempt(i: int) -> str:
        try:
            _reverse(world, original, key=f"rev-{i}")
            return "reversed"
        except AlreadyReversed:
            return "already"

    outcomes = run_concurrently(attempt, range(6), workers=6)
    assert sorted(outcomes).count("reversed") == 1
    assert Transfer.objects.filter(reverses=original).count() == 1
    assert native_balance(world.cash.id) == D("100")
