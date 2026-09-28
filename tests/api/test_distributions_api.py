import pytest
from rest_framework.test import APIClient

from operations.models import Distribution

pytestmark = pytest.mark.django_db

CALL = {"total_amount": "1000000.00", "notice_date": "2026-02-01", "due_date": "2026-02-15"}
BODY = {"total_amount": "250000.00", "payment_date": "2026-08-01", "classification": "GAIN"}


@pytest.fixture
def api():
    return APIClient()


def _url(pe, resource):
    return f"/api/v1/funds/{pe.fund.id}/{resource}/"


def test_call_then_distribute_over_http(api, pe):
    called = api.post(_url(pe, "capital-calls"), CALL, format="json", HTTP_IDEMPOTENCY_KEY="call-1")
    assert called.status_code == 201

    first = api.post(_url(pe, "distributions"), BODY, format="json", HTTP_IDEMPOTENCY_KEY="dist-1")
    again = api.post(_url(pe, "distributions"), BODY, format="json", HTTP_IDEMPOTENCY_KEY="dist-1")
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json() == first.json()
    assert Distribution.objects.count() == 1

    # 750,000 of cash is left; asking for more than that must not touch the ledger.
    too_big = {**BODY, "total_amount": "750000.01"}
    response = api.post(
        _url(pe, "distributions"), too_big, format="json", HTTP_IDEMPOTENCY_KEY="dist-2"
    )
    assert response.status_code == 409
    assert response.json()["error"] == "insufficient_funds"
    assert Distribution.objects.count() == 1
