from types import SimpleNamespace

import pytest

from ledger.models import AccountType
from tests.factories import make_account, make_fund, make_period


@pytest.fixture
def world():
    """A fund with one open 2026 period, a cash account and an equity account.

    The equity (GP_CAPITAL) account is credit-normal and unguarded, so tests use it
    as the source of money when funding cash accounts.
    """
    fund = make_fund()
    return SimpleNamespace(
        fund=fund,
        period=make_period(fund),
        cash=make_account(fund),
        equity=make_account(fund, account_type=AccountType.GP_CAPITAL),
    )