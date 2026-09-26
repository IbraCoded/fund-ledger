from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor

from django.db import connection


def run_concurrently[A, R](fn: Callable[[A], R], args: Iterable[A], *, workers: int) -> list[R]:
    """Run fn over args on a thread pool; each worker thread closes its DB connection."""

    def wrapped(arg: A) -> R:
        try:
            return fn(arg)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(wrapped, args))
