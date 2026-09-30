import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest
from django.db import OperationalError
from psycopg import errors

ROOT = Path(__file__).resolve().parent.parent
GOOD_KEY = secrets.token_urlsafe(50)  # Django warns on keys with too few unique characters


def _django(*args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "manage.py", *args],
        cwd=ROOT,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_production_refuses_to_start_without_a_secret_key():
    env = {k: v for k, v in os.environ.items() if k != "DJANGO_SECRET_KEY"}
    result = subprocess.run(
        [sys.executable, "manage.py", "check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**env, "DJANGO_ENV": "production"},
        timeout=60,
    )
    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY" in result.stderr


def test_production_refuses_a_weak_secret_key():
    result = _django("check", DJANGO_ENV="production", DJANGO_SECRET_KEY="dev-short")
    assert result.returncode != 0


def test_production_passes_django_deploy_checks():
    result = _django(
        "check",
        "--deploy",
        "--fail-level",
        "WARNING",
        DJANGO_ENV="production",
        DJANGO_SECRET_KEY=GOOD_KEY,
        DJANGO_ALLOWED_HOSTS="ledger.example.com",
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.django_db
def test_unexpected_errors_are_generic_json_with_a_request_id(pe, api_for, monkeypatch):
    def explode(**kwargs):
        raise RuntimeError("secret internals: SELECT * FROM somewhere")

    monkeypatch.setattr("api.views.create_capital_call", explode)
    response = api_for(pe.fund, "OPERATOR").post(
        f"/api/v1/funds/{pe.fund.id}/capital-calls/",
        {"total_amount": "1.00", "notice_date": "2026-03-01", "due_date": "2026-03-01"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="k",
        HTTP_X_REQUEST_ID="req-123",
    )
    assert response.status_code == 500
    assert response.json() == {
        "error": "internal_error",
        "detail": "An unexpected error occurred.",
        "request_id": "req-123",
    }
    assert "secret internals" not in response.content.decode()


@pytest.mark.django_db
def test_lock_timeouts_become_503_with_retry_after(pe, api_for, monkeypatch):
    def busy(**kwargs):
        exc = OperationalError("canceling statement due to lock timeout")
        exc.__cause__ = errors.LockNotAvailable("lock timeout")
        raise exc

    monkeypatch.setattr("api.views.create_capital_call", busy)
    response = api_for(pe.fund, "OPERATOR").post(
        f"/api/v1/funds/{pe.fund.id}/capital-calls/",
        {"total_amount": "1.00", "notice_date": "2026-03-01", "due_date": "2026-03-01"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="k",
    )
    assert response.status_code == 503
    assert response["Retry-After"] == "1"
