"""The ledger engine. post_transfer is the only code path that writes Entry rows."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from uuid import UUID

from django.db import IntegrityError, connection, transaction

from funds.models import Period, PeriodStatus
from ledger.errors import (
    AlreadyReversed,
    ClosedPeriod,
    InsufficientFunds,
    InvalidTransfer,
    UnbalancedTransfer,
    UnknownAccount,
)
from ledger.idempotency import constraint_name, money_str, request_fingerprint, run_idempotent
from ledger.legs import Leg, PricedLeg
from ledger.models import NON_NEGATIVE_TYPES, Account, Direction, Entry, Transfer, TransferType
from ledger.pricing import price_legs
from ledger.queries import native_balance

FOUR_DP = Decimal("0.0001")
VALID_DIRECTIONS = frozenset(Direction.values)


def post_transfer(
    *,
    idempotency_key: str,
    legs: Sequence[Leg],
    period: Period,
    transfer_type: str,
    description: str = "",
    reverses: Transfer | None = None,
    request_hash: str = "",
    created_by: str = "",
    fx_date: date | None = None,
) -> Transfer:
    # Step 1: validate the caller's request, before we do any database work.
    validate_legs(legs)
    with transaction.atomic():
        accounts = _lock_accounts(legs)
        _validate_context(period, accounts)
        priced = price_legs(
            legs,
            accounts,
            base_currency=period.fund.base_currency,
            fx_date=fx_date or date.today(),
        )
        # Step 8: check that the transfer balances and that all accounts have sufficient funds.
        _check_balanced(priced)
        _check_sufficient_funds(priced)
        transfer = Transfer.objects.create(
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            transfer_type=transfer_type,
            reverses=reverses,
            period=period,
            description=description,
            created_by=created_by,
        )
        # Step 9: insert the Entry rows. The database will run the deferred balance trigger at COMMIT.
        Entry.objects.bulk_create(
            [
                Entry(
                    transfer=transfer,
                    account=p.account,
                    direction=p.direction,
                    amount=p.amount,
                    currency=p.currency,
                    fx_rate=p.fx_rate,
                    base_amount=p.base_amount,
                )
                for p in priced
            ]
        )
        _fire_deferred_balance_check()
    return transfer


def validate_legs(legs: Sequence[Leg]) -> None:
    if len(legs) < 2:
        raise InvalidTransfer("a transfer needs at least two legs")
    directions = {str(leg.direction) for leg in legs}
    if not directions <= VALID_DIRECTIONS:
        raise InvalidTransfer(f"unknown direction(s): {sorted(directions - VALID_DIRECTIONS)}")
    if directions != VALID_DIRECTIONS:
        raise InvalidTransfer("a transfer needs at least one debit and one credit")
    for leg in legs:
        if not isinstance(leg.amount, Decimal):
            raise InvalidTransfer(f"amounts must be Decimal, got {type(leg.amount).__name__}")
        if not leg.amount.is_finite() or leg.amount <= 0:
            raise InvalidTransfer(f"amounts must be positive, got {leg.amount}")
        if leg.amount != leg.amount.quantize(FOUR_DP):
            raise InvalidTransfer(f"amounts allow at most 4 decimal places, got {leg.amount}")


def _lock_accounts(legs: Sequence[Leg]) -> dict[UUID, Account]:
    """Lock every account the transfer touches, in ascending primary-key order.

    The lock is a mutex over "the entries of this account": we never update the row.
    Holding it while we read balances and insert entries makes the overdraft check and
    the write atomic with respect to every other transfer touching the same account.

    ORDER BY id gives every transaction in the system the same global lock order,
    which makes a deadlock cycle impossible. list() forces the query to run, which is
    when the locks are actually taken.
    """
    ids = {leg.account_id for leg in legs}
    locked = list(Account.objects.select_for_update().filter(id__in=ids).order_by("id"))
    if len(locked) != len(ids):
        missing = sorted(str(i) for i in ids - {a.id for a in locked})
        raise UnknownAccount(f"unknown account(s): {missing}")
    return {a.id: a for a in locked}


def _validate_context(period: Period, accounts: dict[UUID, Account]) -> None:
    # A friendly early error. The guarantee is the period trigger (Step 9).
    if period.status != PeriodStatus.OPEN:
        raise ClosedPeriod(f"period {period} is closed")
    foreign = sorted(a.code for a in accounts.values() if a.fund_id != period.fund_id)
    if foreign:
        raise InvalidTransfer(f"accounts {foreign} do not belong to this period's fund")


def _check_balanced(priced: Sequence[PricedLeg]) -> None:
    # A friendly early error. The guarantee is the deferred balance trigger.
    debits = sum((p.base_amount for p in priced if p.direction == Direction.DEBIT), Decimal(0))
    credits = sum((p.base_amount for p in priced if p.direction == Direction.CREDIT), Decimal(0))
    if debits != credits:
        raise UnbalancedTransfer(f"debits {debits} != credits {credits}")


def _check_sufficient_funds(priced: Sequence[PricedLeg]) -> None:
    deltas: dict[UUID, Decimal] = defaultdict(Decimal)
    for p in priced:
        if p.account.account_type in NON_NEGATIVE_TYPES:
            deltas[p.account.id] += p.amount if p.direction == Direction.DEBIT else -p.amount
    for account_id, delta in deltas.items():
        if delta >= 0:
            continue
        available = native_balance(account_id)
        if available + delta < 0:
            raise InsufficientFunds(f"account {account_id} holds {available}, needs {-delta}")


def _fire_deferred_balance_check() -> None:
    """Run the deferred balance trigger now, instead of at the eventual COMMIT.

    Why: if post_transfer runs inside a caller's transaction (idempotency savepoint in
    Step 6, a capital call in Step 7, a rolled-back test), the deferred check would
    otherwise fire far away, at the outermost COMMIT or at test teardown. Switching to IMMEDIATE
    runs all pending checks for this constraint right here; switching back to DEFERRED
    restores normal behaviour for anything the caller does next.
    """
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS entry_balance_check IMMEDIATE")
        cursor.execute("SET CONSTRAINTS entry_balance_check DEFERRED")


def post_transfer_idempotent(
    *,
    idempotency_key: str,
    legs: Sequence[Leg],
    period: Period,
    transfer_type: str,
    description: str = "",
    created_by: str = "",
    fx_date: date | None = None,
) -> tuple[Transfer, bool]:
    validate_legs(legs)  # before fingerprinting: money_str needs real Decimals
    request_hash = request_fingerprint(
        kind="transfer",
        transfer_type=str(transfer_type),
        period=str(period.id),
        legs=sorted(
            [str(leg.account_id), str(leg.direction), money_str(leg.amount)] for leg in legs
        ),
    )
    return run_idempotent(
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        transfer_type=str(transfer_type),
        create=lambda: post_transfer(
            idempotency_key=idempotency_key,
            legs=legs,
            period=period,
            transfer_type=transfer_type,
            description=description,
            request_hash=request_hash,
            created_by=created_by,
            fx_date=fx_date,
        ),
        replay=lambda existing: existing,
    )


REVERSES_CONSTRAINT = "transfer_reverses_unique"


def reverse_transfer(
    *,
    transfer_id: UUID,
    idempotency_key: str,
    period: Period,
    created_by: str = "",
) -> tuple[Transfer, bool]:
    """Post a new transfer that exactly cancels `transfer_id`. Never touches the original."""
    original = Transfer.objects.get(id=transfer_id)
    if original.transfer_type == TransferType.REVERSAL:
        raise InvalidTransfer("a reversal cannot itself be reversed; post a new transfer instead")

    existing = original.reversals.first()
    if existing is not None and existing.idempotency_key != idempotency_key:
        raise AlreadyReversed(f"transfer {original.id} was already reversed by {existing.id}")

    # Flip each leg, keeping the ORIGINAL fx_rate and base_amount so the reversal
    # cancels the original exactly in base currency, whatever rates have done since.
    legs = [
        Leg(
            e.account_id, _flip(e.direction), e.amount, fx_rate=e.fx_rate, base_amount=e.base_amount
        )
        for e in original.entries.order_by("id")
    ]
    request_hash = request_fingerprint(
        kind="reversal", reverses=str(original.id), period=str(period.id)
    )
    try:
        return run_idempotent(
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            transfer_type=TransferType.REVERSAL,
            create=lambda: post_transfer(
                idempotency_key=idempotency_key,
                legs=legs,
                period=period,
                transfer_type=TransferType.REVERSAL,
                reverses=original,
                description=f"Reversal of {original.id}",
                request_hash=request_hash,
                created_by=created_by,
            ),
            replay=lambda transfer: transfer,
        )
    except IntegrityError as exc:
        # Lost a race with a concurrent reversal using a different key.
        if constraint_name(exc) == REVERSES_CONSTRAINT:
            raise AlreadyReversed(f"transfer {original.id} was already reversed") from exc
        raise


def _flip(direction: str) -> str:
    return Direction.CREDIT if direction == Direction.DEBIT else Direction.DEBIT
