import re
from decimal import Decimal as D

import pytest
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from ledger.errors import InsufficientFunds
from ledger.services import post_transfer_idempotent
from tests.factories import make_account, two_legs

pytestmark = pytest.mark.django_db


def _count(outcome: str) -> float:
    labels = {"transfer_type": "ADJUSTMENT", "outcome": outcome}
    return REGISTRY.get_sample_value("ledger_transfers_total", labels) or 0.0


def _send(world, key, legs):
    return post_transfer_idempotent(
        idempotency_key=key, legs=legs, period=world.period, transfer_type="ADJUSTMENT"
    )


def test_request_id_is_echoed_or_generated(client):
    assert client.get("/healthz", HTTP_X_REQUEST_ID="abc-123")["X-Request-ID"] == "abc-123"
    generated = client.get("/healthz", HTTP_X_REQUEST_ID="not valid!")["X-Request-ID"]
    assert re.fullmatch(r"[0-9a-f]{32}", generated)


def test_every_transfer_is_logged_with_its_replay_flag(world):
    legs = two_legs(world.equity, world.cash, D("1"))
    with capture_logs() as logs:
        _send(world, "log-1", legs)
        _send(world, "log-1", legs)
    posted = [event for event in logs if event["event"] == "transfer.posted"]
    assert [event["replay"] for event in posted] == [False, True]
    assert posted[0]["idempotency_key"] == "log-1"


def test_metrics_count_each_outcome(world):
    before = {o: _count(o) for o in ("created", "replayed", "rejected")}
    legs = two_legs(world.equity, world.cash, D("1"))
    _send(world, "m-1", legs)
    _send(world, "m-1", legs)
    with pytest.raises(InsufficientFunds):
        _send(world, "m-2", two_legs(world.cash, make_account(world.fund), D("99")))
    assert {o: _count(o) - before[o] for o in before} == {
        "created": 1,
        "replayed": 1,
        "rejected": 1,
    }


def test_metrics_endpoint(client, world):
    _send(world, "m-3", two_legs(world.equity, world.cash, D("1")))
    body = client.get("/metrics").content.decode()
    assert "ledger_transfers_total{" in body
    assert "ledger_reconciliation_imbalance 0.0" in body
