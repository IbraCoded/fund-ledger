import threading
import time
from datetime import date
from decimal import Decimal as D

import pytest
from django.db import IntegrityError, transaction

from funds.models import Period
from ledger.errors import ClosedPeriod
from ledger.models import AccountType, Entry, Transfer
from ledger.services import post_transfer, reverse_transfer
from operations.chart import get_account
from operations.errors import PeriodNotClosable
from operations.periods import close_period
from operations.services import create_capital_call
from tests.concurrency import run_concurrently
from tests.factories import two_legs

pytestmark = pytest.mark.django_db


def _close(pe, period):
    return close_period(fund_id=pe.fund.id, period_id=period.id)


def _call(pe, key="call-1", notice=date(2026, 3, 1)):
    return create_capital_call(
        fund_id=pe.fund.id,
        idempotency_key=key,
        total_amount=D("1000.00"),
        notice_date=notice,
        due_date=notice,
    )


def test_close_sets_status_and_timestamp(pe):
    period, changed = _close(pe, pe.h1)
    assert changed and period.status == "CLOSED" and period.closed_at is not None


def test_closing_twice_is_a_no_op(pe):
    _close(pe, pe.h1)
    _, changed = _close(pe, pe.h1)
    assert not changed


def test_periods_close_in_order(pe):
    with pytest.raises(PeriodNotClosable, match="earlier"):
        _close(pe, pe.h2)


def test_service_rejects_posting_into_closed_period(pe):
    _close(pe, pe.h1)
    with pytest.raises(ClosedPeriod):
        _call(pe)


def test_database_rejects_entries_into_closed_period_even_bypassing_python(pe):
    _close(pe, pe.h1)
    cash = get_account(pe.fund, AccountType.CASH)
    sneaky = Transfer.objects.create(
        idempotency_key="sneaky", transfer_type="ADJUSTMENT", period=pe.h1
    )
    with pytest.raises(IntegrityError, match="not open"), transaction.atomic():
        Entry.objects.create(
            transfer=sneaky,
            account=cash,
            direction="DEBIT",
            amount=D("1"),
            currency="GBP",
            base_amount=D("1"),
        )


def test_closed_periods_cannot_be_reopened(pe):
    _close(pe, pe.h1)
    with pytest.raises(IntegrityError, match="final"), transaction.atomic():
        Period.objects.filter(id=pe.h1.id).update(status="OPEN", closed_at=None)


def test_corrections_after_close_go_forward_into_the_open_period(pe):
    call, _ = _call(pe)
    _close(pe, pe.h1)
    reversal, _ = reverse_transfer(
        transfer_id=call.transfer_id, idempotency_key="fix", period=pe.h2
    )
    assert reversal.period_id == pe.h2.id
    assert Transfer.objects.get(id=call.transfer_id).period_id == pe.h1.id  # untouched


@pytest.mark.django_db(transaction=True)
def test_close_waits_for_in_flight_postings(pe):
    cash = get_account(pe.fund, AccountType.CASH)
    gp = get_account(pe.fund, AccountType.GP_CAPITAL)
    inserted = threading.Event()
    timeline: dict[str, float] = {}

    def poster() -> None:
        with transaction.atomic():
            post_transfer(
                idempotency_key="in-flight",
                legs=two_legs(gp, cash, D("5")),
                period=pe.h1,
                transfer_type="ADJUSTMENT",
            )
            inserted.set()
            time.sleep(0.5)  # keep the transaction (and its FOR SHARE lock) open
            timeline["poster_committing"] = time.monotonic()

    def closer() -> None:
        assert inserted.wait(timeout=5)
        _close(pe, pe.h1)
        timeline["closer_done"] = time.monotonic()

    run_concurrently(lambda task: task(), [poster, closer], workers=2)

    assert timeline["closer_done"] > timeline["poster_committing"]
    assert Transfer.objects.filter(idempotency_key="in-flight").exists()
