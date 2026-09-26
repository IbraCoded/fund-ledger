import uuid

from django.db import models
from django.db.models import Case, F, Q, Value, When
from django.db.models.functions import Now

MONEY = {"max_digits": 20, "decimal_places": 4}
ISO_4217 = r"^[A-Z]{3}$"


class AccountType(models.TextChoices):
    CASH = "CASH"
    INVESTMENT = "INVESTMENT"
    FEE_EXPENSE = "FEE_EXPENSE"
    GAIN_LOSS = "GAIN_LOSS"
    LP_CAPITAL = "LP_CAPITAL"
    GP_CAPITAL = "GP_CAPITAL"


# Account types whose native balance may never go below zero.
NON_NEGATIVE_TYPES = frozenset({AccountType.CASH.value})


class Direction(models.TextChoices):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class TransferType(models.TextChoices):
    CAPITAL_CALL = "CAPITAL_CALL"
    DISTRIBUTION = "DISTRIBUTION"
    FEE = "FEE"
    INVESTMENT = "INVESTMENT"
    REVERSAL = "REVERSAL"
    ADJUSTMENT = "ADJUSTMENT"


class Account(models.Model):
    """A bucket of value. Deliberately has no balance column: balance = SUM(entries)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fund = models.ForeignKey("funds.Fund", on_delete=models.PROTECT, related_name="accounts")
    code = models.CharField(max_length=64)
    account_type = models.CharField(max_length=32, choices=AccountType.choices)
    owner_lp = models.ForeignKey(
        "funds.LimitedPartner",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="accounts",
    )
    currency = models.CharField(max_length=3)
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(currency__regex=ISO_4217), name="account_currency_iso4217"
            ),
            # LP accounts must have an owner_lp, and non-LP accounts must not.
            models.CheckConstraint(
                condition=(
                    (Q(account_type="LP_CAPITAL") & Q(owner_lp__isnull=False))
                    | (~Q(account_type="LP_CAPITAL") & Q(owner_lp__isnull=True))
                ),
                name="account_owner_lp_iff_lp_capital",
            ),            
            models.UniqueConstraint(fields=["fund", "code"], name="account_code_unique_per_fund"),
                        models.UniqueConstraint(
                fields=["fund", "owner_lp", "currency"],
                condition=Q(account_type="LP_CAPITAL"),
                name="account_one_lp_capital_per_lp_currency",
            ),
            # Target of the composite FK from Entry (added in migration 0002).
            models.UniqueConstraint(fields=["id", "currency"], name="account_id_currency_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.code} ({self.currency})"


class Transfer(models.Model):
    """One unit of business intent. Produces >= 2 entries that sum to zero. Immutable."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idempotency_key = models.CharField(max_length=255)
    request_hash = models.CharField(max_length=64, blank=True, default="")
    transfer_type = models.CharField(max_length=32, choices=TransferType.choices)
    reverses = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversals"
    )
    period = models.ForeignKey("funds.Period", on_delete=models.PROTECT, related_name="transfers")
    description = models.TextField(blank=True, default="")
    created_by = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["idempotency_key"], name="transfer_idempotency_key_unique"
            ),
            models.UniqueConstraint(fields=["reverses"], name="transfer_reverses_unique"),
            models.CheckConstraint(
                condition=~Q(idempotency_key=""), name="transfer_idempotency_key_present"
            ),
            models.CheckConstraint(
                condition=Q(reverses__isnull=True) | Q(transfer_type="REVERSAL"),
                name="transfer_only_reversals_reverse",
            ),
            models.CheckConstraint(
                condition=~Q(transfer_type="REVERSAL") | Q(reverses__isnull=False),
                name="transfer_reversal_has_target",
            ),
        ]


def _signed(field: str) -> Case:
    """+field for DEBIT, -field for CREDIT. The one place the sign convention is defined."""
    return Case(
        When(direction="DEBIT", then=F(field)),
        default=F(field) * Value(-1),
        output_field=models.DecimalField(**MONEY),
    )


class Entry(models.Model):
    """One debit or credit line. Append-only: enforced by a trigger (migration 0002)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transfer = models.ForeignKey(Transfer, on_delete=models.PROTECT, related_name="entries")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="entries")
    direction = models.CharField(max_length=6, choices=Direction.choices)
    amount = models.DecimalField(**MONEY)
    currency = models.CharField(max_length=3)
    fx_rate = models.DecimalField(max_digits=20, decimal_places=10, null=True, blank=True)
    base_amount = models.DecimalField(**MONEY)
    signed_amount = models.GeneratedField(
        expression=_signed("amount"),
        output_field=models.DecimalField(**MONEY),
        db_persist=True,
    )
    signed_base_amount = models.GeneratedField(
        expression=_signed("base_amount"),
        output_field=models.DecimalField(**MONEY),
        db_persist=True,
    )
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="entry_amount_positive"),
            models.CheckConstraint(
                condition=Q(base_amount__gt=0), name="entry_base_amount_positive"
            ),
            models.CheckConstraint(
                condition=Q(currency__regex=ISO_4217), name="entry_currency_iso4217"
            ),
            models.CheckConstraint(
                condition=Q(direction__in=["DEBIT", "CREDIT"]), name="entry_direction_valid"
            ),
            models.CheckConstraint(
                condition=Q(fx_rate__isnull=True) | Q(fx_rate__gt=0), name="entry_fx_rate_positive"
            ),
        ]
        indexes = [
            models.Index(fields=["account", "created_at"], name="entry_account_created_idx"),
        ]