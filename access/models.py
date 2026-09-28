import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Now


class Role(models.TextChoices):
    LP = "LP", "Limited partner: own statement only"
    VIEWER = "VIEWER", "Viewer: read the whole fund"
    OPERATOR = "OPERATOR", "Operator: also post calls, distributions, reversals"
    CONTROLLER = "CONTROLLER", "Controller: also close periods"


ROLE_RANK: dict[str, int] = {Role.LP: 0, Role.VIEWER: 1, Role.OPERATOR: 2, Role.CONTROLLER: 3}


class FundMembership(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="fund_memberships"
    )
    fund = models.ForeignKey("funds.Fund", on_delete=models.PROTECT, related_name="memberships")
    role = models.CharField(max_length=16, choices=Role.choices)
    lp = models.ForeignKey(
        "funds.LimitedPartner",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="memberships",
    )
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "fund"], name="membership_one_per_user_fund"),
            models.CheckConstraint(
                condition=(Q(role="LP") & Q(lp__isnull=False))
                | (~Q(role="LP") & Q(lp__isnull=True)),
                name="membership_lp_iff_lp_role",
            ),
        ]


class ApiKey(models.Model):
    """A hashed API key. The raw key is shown once at creation and never stored."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_keys"
    )
    name = models.CharField(max_length=100)
    prefix = models.CharField(max_length=12)
    key_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(db_default=Now())
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["prefix"], name="apikey_prefix_unique"),
            models.CheckConstraint(
                condition=Q(key_hash__regex=r"^[0-9a-f]{64}$"), name="apikey_hash_is_sha256"
            ),
        ]
