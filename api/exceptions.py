import structlog
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, OperationalError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from ledger.errors import LedgerError
from ledger.idempotency import constraint_name

log = structlog.get_logger("api")

# Constraints a well-formed request can hit when it loses a race. Fixed messages only:
# raw database error text never leaves the server.
CONSTRAINT_ERRORS = {
    "period_open": ("period_closed", status.HTTP_409_CONFLICT, "The accounting period is closed."),
    "transfer_reverses_unique": (
        "already_reversed",
        status.HTTP_409_CONFLICT,
        "This transfer has already been reversed.",
    ),
}

# lock_timeout / statement_timeout from the app role's settings (Step 16.1).
BUSY_SQLSTATES = frozenset({"55P03", "57014"})


def _error(code: str, detail: str, http_status: int, **extra) -> Response:
    return Response({"error": code, "detail": detail, **extra}, status=http_status)


def exception_handler(exc, context):
    if isinstance(exc, LedgerError):
        return _error(exc.code, str(exc), exc.http_status)
    if isinstance(exc, ObjectDoesNotExist):
        return _error("not_found", "Not found.", status.HTTP_404_NOT_FOUND)
    if isinstance(exc, IntegrityError):
        mapped = CONSTRAINT_ERRORS.get(constraint_name(exc) or "")
        if mapped:
            code, http_status, message = mapped
            return _error(code, message, http_status)
    if isinstance(exc, OperationalError):
        sqlstate = getattr(exc.__cause__, "sqlstate", None)
        if sqlstate in BUSY_SQLSTATES:
            log.warning("db.busy", sqlstate=sqlstate)
            busy = _error(
                "busy", "The ledger is busy; retry shortly.", status.HTTP_503_SERVICE_UNAVAILABLE
            )
            busy["Retry-After"] = "1"
            return busy

    response = drf_exception_handler(exc, context)  # DRF's own: validation, auth, throttling...
    if response is not None:
        return response

    # Anything else is a bug. Log everything; tell the client nothing except how to report it.
    request = context.get("request")
    request_id = request.META.get("REQUEST_ID") if request is not None else None
    log.error("request.unhandled_exception", exc_info=exc)
    return _error(
        "internal_error",
        "An unexpected error occurred.",
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        request_id=request_id,
    )
