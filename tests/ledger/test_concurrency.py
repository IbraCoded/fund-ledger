import contextlib
import random
from decimal import Decimal as D

import pytest
from django.db import OperationalError

from ledger.errors import InsufficientFunds
from ledger.queries import native_balance
from ledger.reconciliation import total_imbalance
from ledger.services import post_transfer
from tests.concurrency import run_concurrently
from tests.factories import fund_accounts, make_account, two_legs

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.xfail(reason="no locking yet: concurrent overdraft race (fixed in 5.2)", strict=False)
def test_no_account_goes_negative_under_concurrent_load(world):
    accounts = [make_account(world.fund) for _ in range(10)]
    # Low balances on purpose: accounts must hover near zero for the race to be observable.
    fund_accounts(world.period, world.equity, accounts, D("30"))

    rng = random.Random(1234)
    pairs = [rng.sample(accounts, 2) for _ in range(500)]

    def transfer(i: int) -> None:
        src, dst = pairs[i]
        with contextlib.suppress(InsufficientFunds):
            post_transfer(
                idempotency_key=f"load-{i}",
                legs=two_legs(src, dst, D("10")),
                period=world.period,
                transfer_type="ADJUSTMENT",
            )

    run_concurrently(transfer, range(500), workers=50)

    balances = {a.code: native_balance(a.id) for a in accounts}
    assert total_imbalance() == 0
    assert sum(balances.values()) == D("300")  # money is conserved between the ten accounts
    assert {code: b for code, b in balances.items() if b < 0} == {}


@pytest.mark.xfail(reason="locks taken in leg order deadlock (fixed in 5.3)", strict=False)
def test_opposing_transfers_do_not_deadlock(world):
    a, b = make_account(world.fund), make_account(world.fund)
    fund_accounts(world.period, world.equity, [a, b], D("1000000"))
    errors: list[OperationalError] = []

    def transfer(i: int) -> None:
        src, dst = (a, b) if i % 2 == 0 else (b, a)  # half go A→B, half go B→A
        try:
            post_transfer(
                idempotency_key=f"dl-{i}",
                legs=two_legs(src, dst, D("1")),
                period=world.period,
                transfer_type="ADJUSTMENT",
            )
        except OperationalError as exc:  # Postgres raises 40P01 "deadlock detected"
            errors.append(exc)

    run_concurrently(transfer, range(200), workers=20)

    assert errors == []
    assert total_imbalance() == 0
