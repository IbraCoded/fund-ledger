"""Business operations. Each works out amounts, then calls the ledger engine."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from uuid import UUID

from django.db.models import Max

from funds.models import Commitment, Fund
from ledger.errors import InvalidTransfer
from ledger.idempotency import money_str, request_fingerprint, run_idempotent
from ledger.legs import Leg
from ledger.models import AccountType, Direction, Transfer, TransferType
from ledger.pricing import fx_rate_for
from ledger.services import post_transfer, post_transfer_idempotent
from operations.allocation import allocate
from operations.chart import ensure_account, get_account, lp_capital_accounts
from operations.errors import CommitmentExceeded
from operations.models import CapitalCall, Distribution
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


def create_distribution(
    *,
    fund_id: UUID,
    idempotency_key: str,
    total_amount: Decimal,
    payment_date: date,
    classification: str,
    created_by: str = "",
) -> tuple[Distribution, bool]:
    request_hash = request_fingerprint(
        kind="distribution",
        fund=str(fund_id),
        total=money_str(total_amount),
        payment_date=payment_date.isoformat(),
        classification=str(classification),
    )

    def create() -> Distribution:
        fund = Fund.objects.select_for_update().get(id=fund_id)
        period = period_for(fund, payment_date)
        _, shares = _pro_rata(fund, total_amount)
        lp_accounts = lp_capital_accounts(fund)
        cash = get_account(fund, AccountType.CASH)
        legs: list[Leg] = []
        for lp_id, share in sorted(shares.items(), key=lambda item: str(item[0])):
            if share == 0:
                continue
            legs.append(Leg(lp_accounts[lp_id].id, Direction.DEBIT, share))
            legs.append(Leg(cash.id, Direction.CREDIT, share))
        number = (
            Distribution.objects.filter(fund=fund).aggregate(n=Max("distribution_number"))["n"] or 0
        ) + 1
        transfer = post_transfer(
            idempotency_key=idempotency_key,
            legs=legs,
            period=period,
            transfer_type=TransferType.DISTRIBUTION,
            description=f"Distribution #{number} ({classification})",
            request_hash=request_hash,
            created_by=created_by,
        )
        return Distribution.objects.create(
            fund=fund,
            distribution_number=number,
            payment_date=payment_date,
            total_amount=total_amount,
            classification=classification,
            transfer=transfer,
        )

    return run_idempotent(
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        transfer_type=TransferType.DISTRIBUTION,
        create=create,
        replay=lambda transfer: Distribution.objects.get(transfer=transfer),
    )


PENNY = Decimal("0.01")


def record_investment(
    *,
    fund_id: UUID,
    idempotency_key: str,
    amount: Decimal,
    currency: str,
    on_date: date,
) -> tuple[Transfer, bool]:
    """Buy a holding in `currency`, paying from base-currency cash at the day's rate."""
    fund = Fund.objects.get(id=fund_id)
    period = period_for(fund, on_date)
    investment = ensure_account(fund, AccountType.INVESTMENT, currency)
    cash = get_account(fund, AccountType.CASH)
    if currency == fund.base_currency:
        legs = [Leg(investment.id, Direction.DEBIT, amount), Leg(cash.id, Direction.CREDIT, amount)]
    else:
        rate = fx_rate_for(currency, fund.base_currency, on_date)
        cost = (amount * rate).quantize(PENNY, rounding=ROUND_HALF_EVEN)  # cash moves in pennies
        legs = [
            Leg(investment.id, Direction.DEBIT, amount, fx_rate=rate, base_amount=cost),
            Leg(cash.id, Direction.CREDIT, cost),
        ]
    return post_transfer_idempotent(
        idempotency_key=idempotency_key,
        legs=legs,
        period=period,
        transfer_type=TransferType.INVESTMENT,
        description=f"Investment {amount} {currency}",
        fx_date=on_date,
    )
