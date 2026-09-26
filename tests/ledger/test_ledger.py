from decimal import Decimal as D

import pytest
from django.db import IntegrityError, transaction

from ledger.models import AccountType, Entry, Transfer
from tests.factories import make_account, make_lp

pytestmark = pytest.mark.django_db


def _transfer(world, key="t-1", **kwargs):
    return Transfer.objects.create(
        idempotency_key=key, transfer_type="ADJUSTMENT", period=world.period, **kwargs
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"amount": D("0"), "base_amount": D("0")},
        {"amount": D("-5"), "base_amount": D("5")},
        {"base_amount": D("0")},
        {"direction": "SIDE"},
    ],
)
def test_entry_row_checks(world, overrides):
    fields = {"direction": "DEBIT", "amount": D("5"), "base_amount": D("5"), "currency": "GBP"}
    fields.update(overrides)
    with pytest.raises(IntegrityError), transaction.atomic():
        Entry.objects.create(transfer=_transfer(world), account=world.cash, **fields)


def test_signed_columns_are_generated_by_the_database(world):
    t = _transfer(world)
    Entry.objects.create(
        transfer=t, account=world.cash, direction="DEBIT",
        amount=D("7"), currency="GBP", base_amount=D("7"),
    )
    Entry.objects.create(
        transfer=t, account=world.equity, direction="CREDIT",
        amount=D("7"), currency="GBP", base_amount=D("7"),
    )
    signed = dict(t.entries.values_list("direction", "signed_amount"))
    assert signed == {"DEBIT": D("7"), "CREDIT": D("-7")}


def test_only_lp_capital_accounts_have_an_owner(world):
    lp = make_lp()
    with pytest.raises(IntegrityError), transaction.atomic():
        make_account(world.fund, account_type=AccountType.CASH, lp=lp)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_account(world.fund, account_type=AccountType.LP_CAPITAL)
    make_account(world.fund, account_type=AccountType.LP_CAPITAL, lp=lp)


def test_one_lp_capital_account_per_lp_and_currency(world):
    lp = make_lp()
    make_account(world.fund, account_type=AccountType.LP_CAPITAL, lp=lp)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_account(world.fund, account_type=AccountType.LP_CAPITAL, lp=lp)


def test_idempotency_key_is_unique_and_required(world):
    _transfer(world, key="same")
    with pytest.raises(IntegrityError), transaction.atomic():
        _transfer(world, key="same")
    with pytest.raises(IntegrityError), transaction.atomic():
        _transfer(world, key="")


def test_reverses_only_allowed_on_reversals(world):
    original = _transfer(world)
    with pytest.raises(IntegrityError), transaction.atomic():
        _transfer(world, key="bad", reverses=original)  # type ADJUSTMENT with a target
