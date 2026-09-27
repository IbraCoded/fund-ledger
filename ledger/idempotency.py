"""Exactly-once semantics for anything that creates a Transfer."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from decimal import Decimal

from django.db import IntegrityError, transaction

from ledger.errors import IdempotencyConflict
from ledger.models import Transfer

IDEMPOTENCY_CONSTRAINT = "transfer_idempotency_key_unique"
FOUR_DP = Decimal("0.0001")


def money_str(amount: Decimal) -> str:
    """Canonical text for money in fingerprints: Decimal('10') and Decimal('10.00') match."""
    return format(amount.quantize(FOUR_DP), "f")


def request_fingerprint(**payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def constraint_name(exc: BaseException) -> str | None:
    """Name of the constraint behind a Django IntegrityError, via psycopg's diagnostics."""
    diag = getattr(exc.__cause__, "diag", None)
    return getattr(diag, "constraint_name", None)


def run_idempotent[T](
    *,
    idempotency_key: str,
    request_hash: str,
    transfer_type: str,  # used for metrics labels in Step 13
    create: Callable[[], T],
    replay: Callable[[Transfer], T],
) -> tuple[T, bool]:
    """Run create() at most once per key. Returns (result, created).

    create() runs in a SAVEPOINT. If it hits the unique idempotency constraint (a retry,
    possibly one that waited on the index while the original was in flight), we roll
    back to the savepoint, fetch the original transfer and replay it.
    """
    try:
        with transaction.atomic():
            return create(), True
    except IntegrityError as exc:
        if constraint_name(exc) != IDEMPOTENCY_CONSTRAINT:
            raise
    existing = Transfer.objects.get(idempotency_key=idempotency_key)
    if existing.request_hash != request_hash:
        raise IdempotencyConflict(
            f"Idempotency-Key {idempotency_key!r} was already used for a different request"
        )
    return replay(existing), False
