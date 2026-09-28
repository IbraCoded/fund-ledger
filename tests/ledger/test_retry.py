import pytest
from django.db import OperationalError
from psycopg import errors

from ledger.retry import with_deadlock_retry

pytestmark = pytest.mark.django_db(transaction=True)  # retry refuses to run inside a transaction


def _deadlock() -> OperationalError:
    exc = OperationalError("deadlock detected")
    exc.__cause__ = errors.DeadlockDetected("deadlock detected")
    return exc


def test_retries_deadlocks_then_succeeds():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise _deadlock()
        return "ok"

    assert with_deadlock_retry(flaky, base_delay=0) == "ok"
    assert len(calls) == 3


def test_gives_up_after_max_attempts():
    with pytest.raises(OperationalError):
        with_deadlock_retry(lambda: (_ for _ in ()).throw(_deadlock()), attempts=2, base_delay=0)


def test_does_not_retry_other_errors():
    calls = []

    def broken():
        calls.append(1)
        raise OperationalError("connection refused")

    with pytest.raises(OperationalError):
        with_deadlock_retry(broken, base_delay=0)
    assert len(calls) == 1
