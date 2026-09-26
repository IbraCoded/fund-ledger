from decimal import Decimal as D

import pytest
from django.db import IntegrityError, transaction

from ledger.models import Entry, Transfer

# transaction=True: each test really COMMITs, so deferred triggers really fire.
pytestmark = pytest.mark.django_db(transaction=True)


def _transfer(world, key="t-1"):
    return Transfer.objects.create(
        idempotency_key=key, transfer_type="ADJUSTMENT", period=world.period
    )


def _entry(transfer, account, direction, amount, currency=None):
    return Entry.objects.create(
        transfer=transfer,
        account=account,
        direction=direction,
        amount=amount,
        currency=currency or account.currency,
        base_amount=amount,
    )


def test_balanced_transfer_commits(world):
    with transaction.atomic():
        t = _transfer(world)
        _entry(t, world.cash, "DEBIT", D("100"))  # unbalanced for a moment: that's allowed
        _entry(t, world.equity, "CREDIT", D("100"))
    assert Entry.objects.filter(transfer=t).count() == 2


def test_unbalanced_transfer_is_rejected_at_commit(world):
    with pytest.raises(IntegrityError, match="does not balance"), transaction.atomic():
        t = _transfer(world)
        _entry(t, world.cash, "DEBIT", D("100"))
        _entry(t, world.equity, "CREDIT", D("99.99"))
    assert not Transfer.objects.exists()  # the whole transaction rolled back


def test_imbalance_error_names_the_constraint(world):
    with pytest.raises(IntegrityError) as caught, transaction.atomic():
        _entry(_transfer(world), world.cash, "DEBIT", D("1"))
    assert caught.value.__cause__.diag.constraint_name == "transfer_balanced"


@pytest.fixture
def posted(world):
    with transaction.atomic():
        t = _transfer(world)
        _entry(t, world.cash, "DEBIT", D("100"))
        _entry(t, world.equity, "CREDIT", D("100"))
    return t


def test_entries_cannot_be_updated(posted):
    with pytest.raises(IntegrityError, match="append-only"):
        Entry.objects.filter(transfer=posted).update(amount=D("1"))


def test_entries_cannot_be_deleted(posted):
    with pytest.raises(IntegrityError, match="append-only"):
        Entry.objects.filter(transfer=posted).delete()


def test_transfers_cannot_be_updated(posted):
    with pytest.raises(IntegrityError, match="append-only"):
        Transfer.objects.filter(pk=posted.pk).update(description="edited")


def test_entry_currency_must_match_account(world):
    with pytest.raises(IntegrityError, match="entry_currency_matches_account"):
        _entry(_transfer(world), world.cash, "DEBIT", D("1"), currency="USD")
