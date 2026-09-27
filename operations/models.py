import uuid

from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Now

from funds.models import MONEY


class CapitalCall(models.Model):
    """The business document. The money lives in `transfer`."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fund = models.ForeignKey("funds.Fund", on_delete=models.PROTECT, related_name="capital_calls")
    call_number = models.PositiveIntegerField()
    notice_date = models.DateField()
    due_date = models.DateField()
    total_amount = models.DecimalField(**MONEY)
    transfer = models.OneToOneField(
        "ledger.Transfer", on_delete=models.PROTECT, related_name="capital_call"
    )
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["fund", "call_number"], name="capital_call_number_unique"
            ),
            models.CheckConstraint(condition=Q(total_amount__gt=0), name="capital_call_positive"),
            models.CheckConstraint(
                condition=Q(due_date__gte=F("notice_date")), name="capital_call_due_after_notice"
            ),
        ]
