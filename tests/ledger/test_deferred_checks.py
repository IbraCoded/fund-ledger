from decimal import Decimal as D

import pytest
from django.db import IntegrityError, connection, transaction

from ledger.models import Entry, Transfer

# NOTE: plain django_db. This test runs inside a transaction that is ROLLED BACK,
# never committed.
pytestmark = pytest.mark.django_db


def _unbalanced(world):
    t = Transfer.objects.create(idempotency_key="u", transfer_type="ADJUSTMENT", period=world.period)
    Entry.objects.create(
        transfer=t, account=world.cash, direction="DEBIT",
        amount=D("5"), currency="GBP", base_amount=D("5"),
    )


def test_deferred_check_does_not_fire_at_insert_time(world):
    """Inserting an unbalanced transfer raises nothing: the balance trigger runs at COMMIT.

    Django forces deferred checks at teardown, so without the savepoint rollback this
    test would PASS and then ERROR at teardown. Delete the last line and watch that happen.
    """
    sid = transaction.savepoint()
    _unbalanced(world)  # no exception, even though the transfer doesn't balance
    transaction.savepoint_rollback(sid)  # discards the row *and* its pending check


def test_set_constraints_immediate_forces_the_check(world):
    with pytest.raises(IntegrityError, match="does not balance"), transaction.atomic():
        _unbalanced(world)
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS entry_balance_check IMMEDIATE")
