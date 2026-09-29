from rest_framework.permissions import SAFE_METHODS
from rest_framework.throttling import UserRateThrottle


class MutationThrottle(UserRateThrottle):
    """A tighter per-user budget for requests that move money."""

    scope = "mutations"

    def allow_request(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return super().allow_request(request, view)
