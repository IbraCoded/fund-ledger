"""Issue and verify API keys of the form fl_<prefix>.<secret>."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.utils import timezone

from access.models import ApiKey

KEY_PREFIX = "fl_"
TOUCH_INTERVAL = timedelta(minutes=1)


def _digest(secret: str) -> str:
    # Fast hash is correct here: the secret is 256 random bits, so there is no
    # dictionary to attack. Slow hashes are for low-entropy human passwords.
    return hashlib.sha256(secret.encode()).hexdigest()


def issue_key(user: User, *, name: str, expires_at: datetime | None = None) -> tuple[ApiKey, str]:
    """Create a key. Returns (row, raw_key). The raw key cannot be recovered later."""
    prefix = secrets.token_hex(6)  # public lookup handle, 48 bits
    secret = secrets.token_urlsafe(32)  # 256 bits; alphabet never contains "."
    api_key = ApiKey.objects.create(
        user=user, name=name, prefix=prefix, key_hash=_digest(secret), expires_at=expires_at
    )
    return api_key, f"{KEY_PREFIX}{prefix}.{secret}"


def verify_key(raw: str) -> ApiKey | None:
    """The matching, live key for `raw`, or None. Never says *why* a key was rejected."""
    if not raw.startswith(KEY_PREFIX):
        return None
    prefix, dot, secret = raw.removeprefix(KEY_PREFIX).partition(".")
    if not (dot and prefix and secret):
        return None
    api_key = ApiKey.objects.select_related("user").filter(prefix=prefix).first()
    if api_key is None or not hmac.compare_digest(api_key.key_hash, _digest(secret)):
        return None
    now = timezone.now()
    if api_key.revoked_at is not None:
        return None
    if api_key.expires_at is not None and api_key.expires_at <= now:
        return None
    if not api_key.user.is_active:
        return None
    return api_key


def record_use(api_key: ApiKey) -> None:
    """Update last_used_at at most once a minute: a write on every read would be wasteful."""
    now = timezone.now()
    if api_key.last_used_at is None or now - api_key.last_used_at > TOUCH_INTERVAL:
        ApiKey.objects.filter(pk=api_key.pk).update(last_used_at=now)
