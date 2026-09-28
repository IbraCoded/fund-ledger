from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.test import APIClient

from access.keys import issue_key
from access.models import ApiKey
from access.permissions import FundRolePermission
from api import urls as api_urls
from funds.models import Period
from ledger.models import AccountType
from operations.chart import get_account
from operations.models import CapitalCall
from operations.services import create_capital_call
from tests.factories import build_pe_fund

pytestmark = pytest.mark.django_db

CALL = {"total_amount": "1000.00", "notice_date": "2026-03-01", "due_date": "2026-03-15"}
CALL_TOTAL = Decimal("1000.00")


def _post_call(client, fund, key="k1"):
    return client.post(
        f"/api/v1/funds/{fund.id}/capital-calls/", CALL, format="json", HTTP_IDEMPOTENCY_KEY=key
    )


def _statement_url(pe, lp):
    return f"/api/v1/funds/{pe.fund.id}/lps/{lp.id}/statement/?period={pe.h1.id}"


# --- Authentication ---------------------------------------------------------------------


def test_missing_credentials_are_401_with_a_challenge(pe):
    response = APIClient().get(f"/api/v1/funds/{pe.fund.id}/accounts/")
    assert response.status_code == 401
    assert response["WWW-Authenticate"].startswith("Bearer")


@pytest.mark.parametrize(
    "header",
    [
        "Bearer nonsense",
        "Bearer fl_abc",
        "Bearer fl_000000000000.wrong",
        "Basic dXNlcjpwdw==",
        "Bearer a b",
    ],
)
def test_bad_credentials_are_401(pe, header):
    response = APIClient().get(f"/api/v1/funds/{pe.fund.id}/accounts/", HTTP_AUTHORIZATION=header)
    assert response.status_code == 401


def test_revoked_and_expired_keys_stop_working_immediately(pe, api_for):
    client = api_for(pe.fund, "VIEWER")
    url = f"/api/v1/funds/{pe.fund.id}/accounts/"
    assert client.get(url).status_code == 200
    ApiKey.objects.filter(user=client.user).update(revoked_at=timezone.now())
    assert client.get(url).status_code == 401

    _, expired = issue_key(
        client.user, name="old", expires_at=timezone.now() - timedelta(seconds=1)
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {expired}")
    assert client.get(url).status_code == 401


def test_last_used_is_recorded(pe, api_for):
    client = api_for(pe.fund, "VIEWER")
    client.get(f"/api/v1/funds/{pe.fund.id}/accounts/")
    assert ApiKey.objects.get(user=client.user).last_used_at is not None


# --- Authorization: roles -----------------------------------------------------------------


def test_viewer_can_read_but_not_write(pe, api_for):
    viewer = api_for(pe.fund, "VIEWER")
    assert viewer.get(f"/api/v1/funds/{pe.fund.id}/accounts/").status_code == 200
    assert _post_call(viewer, pe.fund).status_code == 403
    assert not CapitalCall.objects.exists()


def test_operator_writes_are_attributed_to_the_authenticated_user(pe, api_for):
    operator = api_for(pe.fund, "OPERATOR")
    assert _post_call(operator, pe.fund).status_code == 201
    assert CapitalCall.objects.get().transfer.created_by == operator.user.username


def test_only_controllers_close_periods(pe, api_for):
    url = f"/api/v1/funds/{pe.fund.id}/periods/{pe.h1.id}/close/"
    assert api_for(pe.fund, "OPERATOR").post(url).status_code == 403
    controller = api_for(pe.fund, "CONTROLLER")
    assert controller.post(url).status_code == 200
    period = Period.objects.get(id=pe.h1.id)
    assert (period.status, period.closed_by) == ("CLOSED", controller.user.username)


def test_lp_sees_only_their_own_statement(pe, api_for):
    lp_client = api_for(pe.fund, "LP", lp=pe.lps[0])
    assert lp_client.get(_statement_url(pe, pe.lps[0])).status_code == 200
    assert lp_client.get(_statement_url(pe, pe.lps[1])).status_code == 404
    assert lp_client.get(f"/api/v1/funds/{pe.fund.id}/accounts/").status_code == 403


# --- Authorization: object level (IDOR) ------------------------------------------------------


def test_non_members_get_404_everywhere(pe, api_for):
    outsider = api_for(build_pe_fund().fund, "CONTROLLER")  # powerful, but on a different fund
    cash = get_account(pe.fund, AccountType.CASH)
    call, _ = create_capital_call(
        fund_id=pe.fund.id,
        idempotency_key="c",
        total_amount=CALL_TOTAL,
        notice_date=pe.h1.start_date,
        due_date=pe.h1.start_date,
    )
    urls = [
        ("get", f"/api/v1/funds/{pe.fund.id}/accounts/"),
        ("get", f"/api/v1/funds/{pe.fund.id}/reconciliation/"),
        ("get", f"/api/v1/accounts/{cash.id}/balance/"),
        ("get", f"/api/v1/accounts/{cash.id}/entries/"),
        ("get", _statement_url(pe, pe.lps[0])),
        ("post", f"/api/v1/funds/{pe.fund.id}/periods/{pe.h1.id}/close/"),
        ("post", f"/api/v1/transfers/{call.transfer_id}/reverse/"),
    ]
    for method, url in urls:
        response = getattr(outsider, method)(url, {}, format="json", HTTP_IDEMPOTENCY_KEY="x")
        assert response.status_code == 404, url


def test_me_lists_only_my_memberships(pe, api_for):
    client = api_for(pe.fund, "VIEWER")
    body = client.get("/api/v1/me/").json()
    assert body["username"] == client.user.username
    assert body["memberships"] == [
        {"fund": str(pe.fund.id), "fund_name": pe.fund.name, "role": "VIEWER", "lp": None}
    ]


# --- Deny by default ----------------------------------------------------------------------

PUBLIC_TO_ANY_AUTHENTICATED_USER = {"MeView"}


def test_every_api_endpoint_requires_a_fund_role():
    """Fails the build if someone adds an endpoint and forgets authorization."""
    for pattern in api_urls.urlpatterns:
        view = pattern.callback.view_class  # type: ignore[attr-defined]  # set by as_view()
        if view.__name__ in PUBLIC_TO_ANY_AUTHENTICATED_USER:
            assert list(view.permission_classes) == [IsAuthenticated]
        else:
            assert FundRolePermission in view.permission_classes, (
                f"{view.__name__} is not fund-scoped"
            )
            assert hasattr(view, "required_role"), view.__name__
