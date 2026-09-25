from django.db import DatabaseError, connection
from django.http import JsonResponse, HttpRequest


def healthz(request: HttpRequest) -> JsonResponse:
    """Liveness + database check, used by Docker, Caddy, and uptime monitors."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse({"status": "error", "database": "unreachable"}, status=503)
    return JsonResponse({"status": "ok", "database": "ok"})