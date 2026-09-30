from io import StringIO

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from access.keys import issue_key, verify_key
from access.models import FundMembership
from funds.models import Fund

pytestmark = pytest.mark.django_db


def _env(output: str) -> dict[str, str]:
    return dict(
        line.split("=", 1) for line in output.splitlines() if line and not line.startswith("#")
    )


def _client(raw_key: str) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_key}")
    return client


# --- demo_access ----------------------------------------------------------------------------


def test_demo_access_prints_a_working_key_for_every_role():
    out = StringIO()
    call_command("demo_access", stdout=out)
    env = _env(out.getvalue())

    roles = {}
    for variable in ("LP_KEY", "VIEWER_KEY", "OPERATOR_KEY", "CONTROLLER_KEY"):
        api_key = verify_key(env[variable])
        assert api_key is not None, variable
        roles[variable] = FundMembership.objects.get(user=api_key.user, fund_id=env["FUND_ID"]).role
    assert roles == {
        "LP_KEY": "LP",
        "VIEWER_KEY": "VIEWER",
        "OPERATOR_KEY": "OPERATOR",
        "CONTROLLER_KEY": "CONTROLLER",
    }
    assert env["WRITE_KEY"] == env["OPERATOR_KEY"]


def test_rerunning_demo_access_replaces_its_keys():
    first, second = StringIO(), StringIO()
    call_command("demo_access", stdout=first)
    call_command("demo_access", stdout=second)
    old, new = _env(first.getvalue())["VIEWER_KEY"], _env(second.getvalue())["VIEWER_KEY"]
    assert verify_key(old) is None
    assert verify_key(new) is not None


def test_production_mode_issues_only_read_only_keys():
    out = StringIO()
    call_command("demo_access", "--roles", "LP,VIEWER", "--days", "365", stdout=out)
    env = _env(out.getvalue())
    assert set(env) == {"API", "FUND_ID", "LP_KEY", "VIEWER_KEY"}  # nothing that can write


# --- rotate_sandbox --------------------------------------------------------------------------


def test_sandbox_key_follows_the_daily_fund():
    call_command("rotate_sandbox", "--date", "2026-09-28", stdout=StringIO())
    monday = Fund.objects.get(name="Sandbox 2026-09-28")
    user = FundMembership.objects.get(fund=monday).user
    _, raw = issue_key(user, name="readme")  # created once, published in the README
    sandbox = _client(raw)
    assert sandbox.get("/api/v1/me/").json()["memberships"][0]["role"] == "CONTROLLER"

    call_command("rotate_sandbox", "--date", "2026-09-29", stdout=StringIO())
    tuesday = Fund.objects.get(name="Sandbox 2026-09-29")

    memberships = sandbox.get("/api/v1/me/").json()["memberships"]
    assert [m["fund"] for m in memberships] == [str(tuesday.id)]  # same key, new fund
    assert sandbox.get(f"/api/v1/funds/{tuesday.id}/accounts/").status_code == 200
    assert sandbox.get(f"/api/v1/funds/{monday.id}/accounts/").status_code == 404
    assert Fund.objects.filter(id=monday.id).exists()  # nothing is ever deleted


def test_rotating_twice_on_the_same_day_is_a_no_op():
    for _ in range(2):
        call_command("rotate_sandbox", "--date", "2026-09-28", stdout=StringIO())
    assert Fund.objects.filter(name__startswith="Sandbox").count() == 1


def test_sandbox_fund_is_ready_for_a_capital_call():
    call_command("rotate_sandbox", "--date", "2026-09-28", stdout=StringIO())
    fund = Fund.objects.get(name="Sandbox 2026-09-28")
    _, raw = issue_key(FundMembership.objects.get(fund=fund).user, name="t")
    response = _client(raw).post(
        f"/api/v1/funds/{fund.id}/capital-calls/",
        {"total_amount": "100.00", "notice_date": "2026-09-28", "due_date": "2026-09-28"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="first-call",
    )
    assert response.status_code == 201


# --- periods endpoint and idempotency keys ---------------------------------------------------


def test_lp_can_list_periods(pe, api_for):
    periods = (
        api_for(pe.fund, "LP", lp=pe.lps[0]).get(f"/api/v1/funds/{pe.fund.id}/periods/").json()
    )
    assert [p["id"] for p in periods] == [str(pe.h1.id), str(pe.h2.id)]


@pytest.mark.parametrize("key", ["has spaces", "<script>", "é", "x" * 256])
def test_idempotency_keys_are_restricted_to_safe_characters(pe, api_for, key):
    response = api_for(pe.fund, "OPERATOR").post(
        f"/api/v1/funds/{pe.fund.id}/capital-calls/",
        {"total_amount": "1.00", "notice_date": "2026-03-01", "due_date": "2026-03-01"},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )
    assert response.status_code == 400
