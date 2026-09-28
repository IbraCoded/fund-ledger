import os

from django.db import DatabaseError, connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    generate_latest,
    multiprocess,
)
from prometheus_client.core import GaugeMetricFamily

from ledger.reconciliation import total_imbalance


def healthz(request: HttpRequest) -> JsonResponse:
    """Liveness + database check, used by Docker, Caddy, and uptime monitors."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse({"status": "error", "database": "unreachable"}, status=503)
    return JsonResponse({"status": "ok", "database": "ok"})


class ReconciliationCollector:
    """Computes the ledger imbalance at scrape time. Alert if it is ever non-zero."""

    def describe(self):
        return []  # don't query the database at registration (import) time

    def collect(self):
        yield GaugeMetricFamily(
            "ledger_reconciliation_imbalance",
            "System-wide sum of signed base amounts. Must always be 0.",
            value=float(total_imbalance()),
        )


_reconciliation_registry = CollectorRegistry()
_reconciliation_registry.register(ReconciliationCollector())


def metrics(request) -> HttpResponse:
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)  # aggregate across gunicorn workers
    else:
        registry = REGISTRY
    body = generate_latest(registry) + generate_latest(_reconciliation_registry)
    return HttpResponse(body, content_type=CONTENT_TYPE_LATEST)
