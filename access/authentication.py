import structlog
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from access.keys import record_use, verify_key


class ApiKeyAuthentication(BaseAuthentication):
    """Authorization: Bearer fl_<prefix>.<secret>"""

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts or parts[0].lower() != b"bearer":
            return None  # not our scheme: request stays anonymous → 401 from IsAuthenticated
        if len(parts) != 2:
            raise AuthenticationFailed("Malformed Authorization header.")
        try:
            raw = parts[1].decode("ascii")
        except UnicodeDecodeError:
            raise AuthenticationFailed("Malformed API key.") from None
        api_key = verify_key(raw)
        if api_key is None:
            # One message for every failure: don't tell an attacker which part was wrong.
            raise AuthenticationFailed("Invalid, expired or revoked API key.")
        record_use(api_key)
        structlog.contextvars.bind_contextvars(
            user=api_key.user.get_username(), api_key=api_key.prefix
        )
        return api_key.user, api_key

    def authenticate_header(self, request):
        # Makes DRF answer 401 (with WWW-Authenticate) rather than 403 when credentials are missing.
        return 'Bearer realm="fund-ledger"'
