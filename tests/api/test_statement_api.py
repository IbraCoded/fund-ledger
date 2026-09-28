from datetime import date
from decimal import Decimal as D

import pytest

from operations.services import create_capital_call

pytestmark = pytest.mark.django_db


def test_statement_as_json_and_csv(pe, api_for):
    create_capital_call(
        fund_id=pe.fund.id,
        idempotency_key="c",
        total_amount=D("1000.00"),
        notice_date=date(2026, 2, 1),
        due_date=date(2026, 2, 1),
    )
    api = api_for(pe.fund, "VIEWER")
    url = f"/api/v1/funds/{pe.fund.id}/lps/{pe.lps[0].id}/statement/?period={pe.h1.id}"

    body = api.get(url).json()
    assert body["opening_balance"] == "0"
    assert body["currency"] == "GBP"

    csv_response = api.get(url + "&format=csv")
    assert csv_response["Content-Type"].startswith("text/csv")
    assert "closing_balance," in csv_response.content.decode()


def test_statement_requires_a_period(pe, api_for):
    url = f"/api/v1/funds/{pe.fund.id}/lps/{pe.lps[0].id}/statement/"
    assert api_for(pe.fund, "VIEWER").get(url).status_code == 400
