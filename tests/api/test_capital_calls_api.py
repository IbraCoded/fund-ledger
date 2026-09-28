from decimal import Decimal as D

import pytest
from rest_framework.test import APIClient

from ledger.models import AccountType
from operations.chart import get_account
from operations.models import CapitalCall

pytestmark = pytest.mark.django_db

BODY = {"total_amount": "250000.00", "notice_date": "2026-03-01", "due_date": "2026-03-15"}


@pytest.fixture
def api():
    return APIClient()


def _url(pe):
    return f"/api/v1/funds/{pe.fund.id}/capital-calls/"


def test_idempotency_key_is_required(api, pe):
    response = api.post(_url(pe), BODY, format="json")
    assert response.status_code == 400
    assert "Idempotency-Key" in response.json()


def test_create_then_replay(api, pe):
    first = api.post(_url(pe), BODY, format="json", HTTP_IDEMPOTENCY_KEY="call-1")
    again = api.post(_url(pe), BODY, format="json", HTTP_IDEMPOTENCY_KEY="call-1")
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json() == first.json()
    assert CapitalCall.objects.count() == 1


def test_key_reuse_with_different_body_is_422(api, pe):
    api.post(_url(pe), BODY, format="json", HTTP_IDEMPOTENCY_KEY="call-1")
    other = {**BODY, "total_amount": "1.00"}
    response = api.post(_url(pe), other, format="json", HTTP_IDEMPOTENCY_KEY="call-1")
    assert response.status_code == 422
    assert response.json()["error"] == "idempotency_conflict"


def test_json_numbers_are_parsed_as_decimal(api, pe):
    body = {**BODY, "total_amount": 1000000.01}  # a JSON number, not a string
    api.post(_url(pe), body, format="json", HTTP_IDEMPOTENCY_KEY="call-1")
    assert CapitalCall.objects.get().total_amount == D("1000000.01")


def test_domain_errors_map_to_http(api, pe):
    too_big = {**BODY, "total_amount": "900000000.00"}
    response = api.post(_url(pe), too_big, format="json", HTTP_IDEMPOTENCY_KEY="k1")
    assert response.status_code == 409
    assert response.json()["error"] == "commitment_exceeded"

    backwards = {**BODY, "due_date": "2026-01-01"}
    assert (
        api.post(_url(pe), backwards, format="json", HTTP_IDEMPOTENCY_KEY="k2").status_code == 400
    )


def test_unknown_fund_is_404(api):
    url = "/api/v1/funds/00000000-0000-0000-0000-000000000000/capital-calls/"
    assert api.post(url, BODY, format="json", HTTP_IDEMPOTENCY_KEY="k").status_code == 404


def test_balance_and_entries_endpoints(api, pe):
    api.post(_url(pe), BODY, format="json", HTTP_IDEMPOTENCY_KEY="call-1")
    cash = get_account(pe.fund, AccountType.CASH)

    balance = api.get(f"/api/v1/accounts/{cash.id}/balance/").json()
    assert balance["balance"] == "250000.0000"

    page = api.get(f"/api/v1/accounts/{cash.id}/entries/").json()
    assert len(page["results"]) == len(pe.lps)
    assert page["next"] is None

    accounts = api.get(f"/api/v1/funds/{pe.fund.id}/accounts/").json()
    assert {a["code"] for a in accounts} >= {"CASH-GBP", "GP_CAPITAL"}


def test_bad_as_of_is_400(api, pe):
    cash = get_account(pe.fund, AccountType.CASH)
    assert api.get(f"/api/v1/accounts/{cash.id}/balance/?as_of=yesterday").status_code == 400
