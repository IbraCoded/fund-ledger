import random
import time
from collections.abc import Callable

import structlog
from django.db import OperationalError, connection

from observability.metrics import DB_RETRIES

log = structlog.get_logger(__name__)

# deadlock_detected, serialization_failure: both mean "rolled back, safe to retry".
RETRYABLE_SQLSTATES = frozenset({"40P01", "40001"})


def with_deadlock_retry[T](
    fn: Callable[[], T], *, attempts: int = 3, base_delay: float = 0.02
) -> T:
    """Retry fn on deadlock/serialization failure, with jittered exponential backoff.

    Only safe outside a transaction: inside one, the failure has already poisoned the
    outer transaction, so retrying the inner part cannot work.
    """
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except OperationalError as exc:
            sqlstate = getattr(exc.__cause__, "sqlstate", None)
            retryable = sqlstate in RETRYABLE_SQLSTATES and not connection.in_atomic_block
            if not retryable or attempt == attempts:
                raise
            DB_RETRIES.labels(sqlstate=sqlstate).inc()
            log.warning("db.retry", sqlstate=sqlstate, attempt=attempt)
            time.sleep(base_delay * (2**attempt) * random.random())
    raise AssertionError("unreachable")
