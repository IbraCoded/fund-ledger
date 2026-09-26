import uuid

from django.db import models
from django.db.models import F, Q

MONEY = {"max_digits": 20, "decimal_places": 4}
ISO_4217 = r"^[A-Z]{3}$"


class Fund(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, unique=True)
    base_currency = models.CharField(max_length=3)
    vintage_year = models.PositiveSmallIntegerField()
    inception_date = models.DateField()

    class Meta:
        # Constraints to ensure that the base_currency is a valid ISO 4217 currency code.
        constraints = [
            models.CheckConstraint(
                condition=Q(base_currency__regex=ISO_4217), name="fund_base_currency_iso4217"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class InvestorType(models.TextChoices):
    PENSION = "PENSION"
    ENDOWMENT = "ENDOWMENT"
    SOVEREIGN_WEALTH = "SOVEREIGN_WEALTH"
    FAMILY_OFFICE = "FAMILY_OFFICE"
    FUND_OF_FUNDS = "FUND_OF_FUNDS"
    INSURANCE = "INSURANCE"


class LimitedPartner(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    investor_type = models.CharField(max_length=32, choices=InvestorType.choices)

    def __str__(self) -> str:
        return self.name


class Commitment(models.Model):
    """An LP's legal promise to provide up to `committed_amount` when called."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fund = models.ForeignKey(Fund, on_delete=models.PROTECT, related_name="commitments")
    lp = models.ForeignKey(LimitedPartner, on_delete=models.PROTECT, related_name="commitments")
    committed_amount = models.DecimalField(**MONEY)
    signed_date = models.DateField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["fund", "lp"], name="commitment_one_per_lp_per_fund"),
            # Constraint to make sure that the committed_amount is positive.
            models.CheckConstraint(
                condition=Q(committed_amount__gt=0), name="commitment_amount_positive"
            ),
        ]


class PeriodStatus(models.TextChoices):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class Period(models.Model):
    """An accounting period. Once CLOSED, nothing may be posted into it."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fund = models.ForeignKey(Fund, on_delete=models.PROTECT, related_name="periods")
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=6, choices=PeriodStatus.choices, default=PeriodStatus.OPEN)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["fund", "start_date"]
        constraints = [
            models.UniqueConstraint(fields=["fund", "start_date"], name="period_unique_start"),
            models.CheckConstraint(
                condition=Q(end_date__gte=F("start_date")), name="period_end_not_before_start"
            ),
            # Constraint to ensure that the closed_at field is only set when the period is CLOSED, and is null when the period is OPEN.
            models.CheckConstraint(
                condition=(
                    Q(status="OPEN", closed_at__isnull=True)
                    | Q(status="CLOSED", closed_at__isnull=False)
                ),
                name="period_closed_at_matches_status",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.start_date}..{self.end_date} ({self.status})"


class FxRate(models.Model):
    """Rate to convert 1 unit of from_currency into to_currency, valid from as_of_date."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    from_currency = models.CharField(max_length=3)
    to_currency = models.CharField(max_length=3)
    rate = models.DecimalField(max_digits=20, decimal_places=10)
    as_of_date = models.DateField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["from_currency", "to_currency", "as_of_date"], name="fxrate_unique_per_day"
            ),
            models.CheckConstraint(condition=Q(rate__gt=0), name="fxrate_positive"),
            models.CheckConstraint(
                condition=~Q(from_currency=F("to_currency")), name="fxrate_distinct_currencies"
            ),
        ]


# Net Asset Value (NAV) snapshot for a fund on a given date. This is used for reporting and performance calculations.
class NavSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fund = models.ForeignKey(Fund, on_delete=models.PROTECT, related_name="nav_snapshots")
    as_of_date = models.DateField()
    total_nav = models.DecimalField(**MONEY)
    computed_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["fund", "as_of_date"], name="nav_one_per_fund_per_day"),
        ]
