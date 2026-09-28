from decimal import Decimal as D
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from ledger.services import post_transfer
from tests.factories import two_legs

pytestmark = pytest.mark.django_db


def test_reconcile_passes_on_a_healthy_ledger(world):
    post_transfer(
        idempotency_key="t",
        legs=two_legs(world.equity, world.cash, D("5")),
        period=world.period,
        transfer_type="ADJUSTMENT",
    )
    out = StringIO()
    call_command("reconcile", "--as-of", "2100-01-01T00:00:00Z", stdout=out)
    assert "Ledger balanced" in out.getvalue()


def test_reconcile_fails_loudly_on_imbalance(monkeypatch):
    # We have to fake the imbalance: the database won't let us create a real one.
    # That's the whole point of the project.
    monkeypatch.setattr(
        "ledger.management.commands.reconcile.total_imbalance", lambda **_: D("0.01")
    )
    with pytest.raises(CommandError, match="OUT OF BALANCE"):
        call_command("reconcile")


def test_reconcile_rejects_a_bad_timestamp():
    with pytest.raises(CommandError):
        call_command("reconcile", "--as-of", "last tuesday")


def test_reconciliation_endpoint(world, api_for):
    body = (
        api_for(world.fund, "VIEWER").get(f"/api/v1/funds/{world.fund.id}/reconciliation/").json()
    )
    assert body == {
        "fund": str(world.fund.id),
        "balanced": True,
        "imbalance": "0",
        "unbalanced_transfers": [],
    }
