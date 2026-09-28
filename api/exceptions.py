from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from ledger.errors import LedgerError
from ledger.idempotency import constraint_name

# Database constraints a well-formed request can hit when it loses a race the service
# layer's early checks couldn't see. Anything not listed here is a bug → 500.
CONSTRAINT_ERRORS = {
    "period_open": ("period_closed", status.HTTP_409_CONFLICT),
    "transfer_reverses_unique": ("already_reversed", status.HTTP_409_CONFLICT),
}


def exception_handler(exc, context):
    if isinstance(exc, LedgerError):
        return Response({"error": exc.code, "detail": str(exc)}, status=exc.http_status)
    if isinstance(exc, ObjectDoesNotExist):
        return Response({"error": "not_found", "detail": str(exc)}, status=404)
    if isinstance(exc, IntegrityError):
        mapped = CONSTRAINT_ERRORS.get(constraint_name(exc) or "")
        if mapped:
            code, http_status = mapped
            return Response({"error": code, "detail": str(exc.__cause__)}, status=http_status)
    return drf_exception_handler(exc, context)
