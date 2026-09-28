"""Business operations. Each works out amounts, then calls the ledger engine."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from django.db.models import Max

from funds.models import Commitment, Fund
from ledger.errors import InvalidTransfer
from ledger.idempotency import money_str, request_fingerprint, run_idempotent
from ledger.legs import Leg
from ledger.models import AccountType, Direction, TransferType
from ledger.services import post_transfer
from operations.allocation import allocate
from operations.chart import get_account, lp_capital_accounts
from operations.errors import CommitmentExceeded
from operations.models import CapitalCall
from operations.periods import period_for
from operations.queries import contributed


def _pro_rata(fund: Fund, total: Decimal) -> tuple[list[Commitment], dict[UUID, Decimal]]:
    commitments = list(Commitment.objects.filter(fund=fund))
    if not commitments:
        raise InvalidTransfer(f"fund {fund} has no commitments")
    try:
        shares = allocate(total, {c.lp_id: c.committed_amount for c in commitments})
    except ValueError as exc:
        raise InvalidTransfer(str(exc)) from exc
    return commitments, shares


def create_capital_call(
    *,
    fund_id: UUID,
    idempotency_key: str,
    total_amount: Decimal,
    notice_date: date,
    due_date: date,
    created_by: str = "",
) -> tuple[CapitalCall, bool]:
    request_hash = request_fingerprint(
        kind="capital_call",
        fund=str(fund_id),
        total=money_str(total_amount),
        notice_date=notice_date.isoformat(),
        due_date=due_date.isoformat(),
    )

    def create() -> CapitalCall:
        # Lock order: fund first, then accounts (inside post_transfer). See Step 5.
        fund = Fund.objects.select_for_update().get(id=fund_id)
        period = period_for(fund, notice_date)
        commitments, shares = _pro_rata(fund, total_amount)
        lp_accounts = lp_capital_accounts(fund)

        for c in commitments:
            unfunded = c.committed_amount - contributed(lp_accounts[c.lp_id])
            if shares[c.lp_id] > unfunded:
                raise CommitmentExceeded(
                    f"LP {c.lp_id} would be called {shares[c.lp_id]}, unfunded is {unfunded}"
                )

        cash = get_account(fund, AccountType.CASH)
        legs: list[Leg] = []
        for lp_id, share in sorted(shares.items(), key=lambda item: str(item[0])):
            if share == 0:
                continue  # an LP whose share rounds to zero gets no entries
            legs.append(Leg(cash.id, Direction.DEBIT, share))
            legs.append(Leg(lp_accounts[lp_id].id, Direction.CREDIT, share))

        number = (
            CapitalCall.objects.filter(fund=fund).aggregate(n=Max("call_number"))["n"] or 0
        ) + 1
        transfer = post_transfer(
            idempotency_key=idempotency_key,
            legs=legs,
            period=period,
            transfer_type=TransferType.CAPITAL_CALL,
            description=f"Capital call #{number}",
            request_hash=request_hash,
            created_by=created_by,
        )
        return CapitalCall.objects.create(
            fund=fund,
            call_number=number,
            notice_date=notice_date,
            due_date=due_date,
            total_amount=total_amount,
            transfer=transfer,
        )

    return run_idempotent(
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        transfer_type=TransferType.CAPITAL_CALL,
        create=create,
        replay=lambda transfer: CapitalCall.objects.get(transfer=transfer),
    )
