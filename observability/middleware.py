import re
import time
import uuid

import structlog
from django.http import HttpRequest, HttpResponse

log = structlog.get_logger("http")

# Accept a caller's request id only if it's short and boring: prevents log injection.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestIDMiddleware:
    header = "X-Request-ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming = request.headers.get(self.header, "")
        request_id = incoming if _SAFE_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()  # worker threads are reused
        structlog.contextvars.bind_contextvars(
            request_id=request_id, method=request.method, path=request.path
        )
        started = time.perf_counter()
        response = self.get_response(request)
        response[self.header] = request_id
        log.info(
            "request.finished",
            status=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return response
