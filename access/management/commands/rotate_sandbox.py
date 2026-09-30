"""Point the public sandbox key at today's fresh sandbox fund. Run daily from cron."""

from datetime import date

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from access.models import FundMembership, Role
from operations.sandbox import open_sandbox_fund


class Command(BaseCommand):
    help = "Open today's sandbox fund and move the sandbox user's CONTROLLER membership onto it."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="sandbox")
        parser.add_argument("--date", type=date.fromisoformat, help="Default: today")

    def handle(self, *args, **options):
        day = options["date"] or timezone.localdate()
        with transaction.atomic():
            fund = open_sandbox_fund(day)
            user, created = get_user_model().objects.get_or_create(username=options["username"])
            if created:
                user.set_unusable_password()
                user.save(update_fields=["password"])
            # The key never changes; what it can reach does. Yesterday's fund stays in the
            # ledger (nothing is ever deleted), it just stops being reachable with this key.
            FundMembership.objects.filter(user=user).exclude(fund=fund).delete()
            FundMembership.objects.update_or_create(
                user=user, fund=fund, defaults={"role": Role.CONTROLLER, "lp": None}
            )
        self.stdout.write(
            self.style.SUCCESS(f"{user.get_username()} is CONTROLLER on {fund.name} ({fund.id})")
        )
