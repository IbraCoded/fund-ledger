import pytest
from django.db import DatabaseError

pytestmark = pytest.mark.django_db


def test_healthz_ok(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_healthz_reports_database_failure(client, monkeypatch):
    def broken_cursor(*args, **kwargs):
        raise DatabaseError("connection refused")

    monkeypatch.setattr("observability.views.connection.cursor", broken_cursor)
    response = client.get("/healthz")
    assert response.status_code == 503
