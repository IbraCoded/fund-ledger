import threading
from decimal import Decimal as D

import pytest

from ledger.errors import IdempotencyConflict, InsufficientFunds
from ledger.models import Entry, Transfer
from ledger.queries import native_balance
from ledger.services import post_transfer_idempotent
from tests.concurrency import run_concurrently
from tests.factories import fund_accounts, make_account, two_legs

pytestmark = pytest.mark.django_db


def _send(world, key, legs):
    return post_transfer_idempotent(
        idempotency_key=key, legs=legs, period=world.period, transfer_type="ADJUSTMENT"
    )


def test_replay_returns_the_original(world):
    first, created1 = _send(world, "k1", two_legs(world.equity, world.cash, D("10")))
    again, created2 = _send(world, "k1", two_legs(world.equity, world.cash, D("10.00")))
    assert (created1, created2) == (True, False)
    assert again.id == first.id
    assert Entry.objects.count() == 2
    assert native_balance(world.cash.id) == D("10")


def test_same_key_different_request_is_a_conflict(world):
    _send(world, "k1", two_legs(world.equity, world.cash, D("10")))
    with pytest.raises(IdempotencyConflict):
        _send(world, "k1", two_legs(world.equity, world.cash, D("11")))


def test_rejected_request_does_not_burn_its_key(world):
    other = make_account(world.fund)
    with pytest.raises(InsufficientFunds):
        _send(world, "k1", two_legs(world.cash, other, D("5")))
    _send(world, "fund", two_legs(world.equity, world.cash, D("5")))
    _, created = _send(world, "k1", two_legs(world.cash, other, D("5")))
    assert created is True


@pytest.mark.django_db(transaction=True)
def test_concurrent_duplicates_create_exactly_one_transfer(world):
    src, dst = make_account(world.fund), make_account(world.fund)
    fund_accounts(world.period, world.equity, [src], D("100"))
    start = threading.Barrier(20)  # release all 20 requests at the same instant

    def fire(_: int):
        start.wait()
        transfer, created = _send(world, "dup-1", two_legs(src, dst, D("10")))
        return transfer.id, created

    results = run_concurrently(fire, range(20), workers=20)

    assert sum(created for _, created in results) == 1
    assert len({transfer_id for transfer_id, _ in results}) == 1
    assert Transfer.objects.filter(idempotency_key="dup-1").count() == 1
    assert Entry.objects.filter(transfer__idempotency_key="dup-1").count() == 2
    assert native_balance(src.id) == D("90")
