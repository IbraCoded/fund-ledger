from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.extra.django import TestCase

from ledger.errors import InsufficientFunds
from ledger.models import AccountType
from ledger.queries import native_balance
from ledger.reconciliation import total_imbalance, unbalanced_transfers
from ledger.services import post_transfer
from tests.factories import make_account, make_fund, make_period, two_legs

amounts = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("500"), places=2)
moves = st.lists(
    st.tuples(st.integers(0, 3), st.integers(0, 3), amounts).filter(lambda m: m[0] != m[1]),
    max_size=30,
)


class LedgerMatchesModel(TestCase):
    """Each Hypothesis example runs in its own transaction, rolled back afterwards.

    That's fine here because post_transfer forces the deferred balance check with
    SET CONSTRAINTS IMMEDIATE; without that, imbalances would go unnoticed.
    """

    @settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(initial=st.lists(amounts, min_size=4, max_size=4), ops=moves)
    def test_balances_match_model_and_books_balance(self, initial, ops):
        fund = make_fund()
        period = make_period(fund)
        source = make_account(fund, account_type=AccountType.GP_CAPITAL)
        cash = [make_account(fund) for _ in range(4)]

        expected: dict = {}
        for account, amount in zip(cash, initial, strict=True):
            post_transfer(
                idempotency_key=f"init-{account.id}",
                legs=two_legs(source, account, amount),
                period=period,
                transfer_type="ADJUSTMENT",
            )
            expected[account.id] = amount

        for i, (s, d, amount) in enumerate(ops):
            src, dst = cash[s], cash[d]
            try:
                post_transfer(
                    idempotency_key=f"op-{i}",
                    legs=two_legs(src, dst, amount),
                    period=period,
                    transfer_type="ADJUSTMENT",
                )
            except InsufficientFunds:
                self.assertLess(expected[src.id], amount)  # the model agrees it had to fail
                continue
            self.assertGreaterEqual(expected[src.id], amount)  # the model agrees it could succeed
            expected[src.id] -= amount
            expected[dst.id] += amount

        for account in cash:
            self.assertEqual(native_balance(account.id), expected[account.id])
        self.assertEqual(total_imbalance(), Decimal("0"))
        self.assertEqual(unbalanced_transfers(), [])
