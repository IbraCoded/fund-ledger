from datetime import date
from decimal import Decimal as D

import pytest

from ledger.errors import IdempotencyConflict
from ledger.models import AccountType
from ledger.queries import native_balance
from ledger.reconciliation import total_imbalance
from ledger.services import reverse_transfer
from operations.chart import get_account, lp_capital_accounts
from operations.errors import CommitmentExceeded, NoPeriod
from operations.models import CapitalCall
from operations.queries import contributed
from operations.services import create_capital_call
from tests.concurrency import run_concurrently

pytestmark = pytest.mark.django_db


def _call(pe, key="call-1", amount="1000000.01", notice=date(2026, 3, 1)):
    return create_capital_call(
        fund_id=pe.fund.id,
        idempotency_key=key,
        total_amount=D(amount),
        notice_date=notice,
        due_date=notice,
    )


def test_call_books_2n_entries_that_sum_exactly(pe):
    call, created = _call(pe)
    assert created
    entries = call.transfer.entries.all()
    assert entries.count() == 2 * len(pe.lps)

    lp_accounts = lp_capital_accounts(pe.fund)
    credited = sum(-native_balance(a.id) for a in lp_accounts.values())
    assert credited == D("1000000.01")
    assert native_balance(get_account(pe.fund, AccountType.CASH).id) == D("1000000.01")
    assert total_imbalance() == 0


def test_call_numbers_increment(pe):
    first, _ = _call(pe, key="c1")
    second, _ = _call(pe, key="c2")
    assert (first.call_number, second.call_number) == (1, 2)


def test_cannot_call_more_than_is_unfunded(pe):
    # Total commitments are ~£156.8m, so £200m must exceed every LP's unfunded amount.
    with pytest.raises(CommitmentExceeded):
        _call(pe, amount="200000000.00")
    assert not CapitalCall.objects.exists()


def test_replay_returns_the_original_call(pe):
    first, _ = _call(pe)
    again, created = _call(pe)
    assert not created and again.id == first.id
    assert CapitalCall.objects.count() == 1


def test_reusing_a_key_for_a_different_call_conflicts(pe):
    _call(pe)
    with pytest.raises(IdempotencyConflict):
        _call(pe, amount="5.00")


def test_call_outside_any_period_is_rejected(pe):
    with pytest.raises(NoPeriod):
        _call(pe, notice=date(2030, 1, 1))


@pytest.mark.django_db(transaction=True)
def test_concurrent_calls_get_distinct_numbers(pe):
    run_concurrently(lambda i: _call(pe, key=f"cc-{i}", amount="1000.00"), range(8), workers=8)
    numbers = sorted(CapitalCall.objects.values_list("call_number", flat=True))
    assert numbers == list(range(1, 9))


def test_reversed_call_no_longer_counts_as_contributed(pe):
    call, _ = _call(pe, amount="1000.00")
    reverse_transfer(transfer_id=call.transfer_id, idempotency_key="rev", period=pe.h1)
    assert all(contributed(a) == 0 for a in lp_capital_accounts(pe.fund).values())
