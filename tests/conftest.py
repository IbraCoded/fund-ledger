from itertools import count
from types import SimpleNamespace

import pytest
import structlog
from django.contrib.auth.models import User
from django.core.cache import cache
from rest_framework.test import APIClient

from access.keys import issue_key
from access.models import FundMembership
from ledger.models import AccountType
from tests.factories import build_pe_fund, make_account, make_fund, make_period

structlog.configure(cache_logger_on_first_use=False)


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


@pytest.fixture
def pe():
    return build_pe_fund()


@pytest.fixture
def api_for(db):
    """Factory: an APIClient authenticated as a fresh user holding `role` on `fund`.

    The client carries the user as `client.user` so tests can assert attribution.
    """
    usernames = count(1)

    def make(fund, role, *, lp=None):
        user = User.objects.create_user(username=f"{role.lower()}-{next(usernames)}")
        FundMembership.objects.create(user=user, fund=fund, role=role, lp=lp)
        _, raw = issue_key(user, name="test")
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        client.user = user  # type: ignore[attr-defined]  # handle for assertions in tests
        return client

    return make


@pytest.fixture(autouse=True)
def _fresh_throttle_state():
    cache.clear()
