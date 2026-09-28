"""Exactly-once semantics for anything that creates a Transfer."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from decimal import Decimal

import structlog
from django.db import IntegrityError, transaction

from ledger.errors import IdempotencyConflict, LedgerError
from ledger.models import Transfer
from observability.metrics import TRANSFER_LATENCY, TRANSFERS

log = structlog.get_logger(__name__)


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
    transfer_type: str,
    create: Callable[[], T],
    replay: Callable[[Transfer], T],
) -> tuple[T, bool]:
    """Run create() at most once per key, with metrics and a log line for every outcome."""
    started = time.perf_counter()
    outcome = "error"
    try:
        result, created = _run_once(idempotency_key, request_hash, create, replay)
        outcome = "created" if created else "replayed"
    except LedgerError as exc:
        outcome = "rejected"
        log.info(
            "transfer.rejected",
            idempotency_key=idempotency_key,
            transfer_type=transfer_type,
            error=exc.code,
        )
        raise
    finally:
        TRANSFERS.labels(transfer_type=transfer_type, outcome=outcome).inc()
        TRANSFER_LATENCY.labels(transfer_type=transfer_type).observe(time.perf_counter() - started)
    log.info(
        "transfer.posted",
        transfer_id=str(_transfer_id(result)),
        idempotency_key=idempotency_key,
        transfer_type=transfer_type,
        replay=not created,
    )
    return result, created


def _run_once[T](
    idempotency_key: str,
    request_hash: str,
    create: Callable[[], T],
    replay: Callable[[Transfer], T],
) -> tuple[T, bool]:
    # Unchanged from Step 6: replay a known key; otherwise create, and replay if a
    # duplicate won the race (at the unique key, or before it via the locks).
    existing = Transfer.objects.filter(idempotency_key=idempotency_key).first()
    if existing is None:
        try:
            with transaction.atomic():
                return create(), True
        except IntegrityError as exc:
            if constraint_name(exc) != IDEMPOTENCY_CONSTRAINT:
                raise
            existing = Transfer.objects.get(idempotency_key=idempotency_key)
        except LedgerError:
            existing = Transfer.objects.filter(idempotency_key=idempotency_key).first()
            if existing is None:
                raise
    if existing.request_hash != request_hash:
        raise IdempotencyConflict(
            f"Idempotency-Key {idempotency_key!r} was already used for a different request"
        )
    return replay(existing), False


def _transfer_id(result: object) -> object:
    # A Transfer, or a document (CapitalCall, Distribution) that points at one.
    return getattr(result, "transfer_id", None) or getattr(result, "pk", None)
