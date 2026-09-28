from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from access.models import FundMembership, Role
from funds.models import Commitment, Fund


class Command(BaseCommand):
    help = "Give a user a role on a fund, creating the (API-only) user if needed."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--fund", required=True, type=UUID)
        parser.add_argument("--role", required=True, choices=Role.values)
        parser.add_argument("--lp", type=UUID, help="Required for, and only for, the LP role")

    def handle(self, *args, **options):
        role, lp_id = options["role"], options["lp"]
        if (role == Role.LP) != (lp_id is not None):
            raise CommandError("--lp is required for the LP role, and only for it")
        fund = Fund.objects.filter(id=options["fund"]).first()
        if fund is None:
            raise CommandError("no such fund")
        if lp_id is not None and not Commitment.objects.filter(fund=fund, lp_id=lp_id).exists():
            raise CommandError("that LP has no commitment to this fund")

        user, created = get_user_model().objects.get_or_create(username=options["username"])
        if created:
            user.set_unusable_password()  # API keys only: no password login exists
            user.save(update_fields=["password"])
        FundMembership.objects.update_or_create(
            user=user, fund=fund, defaults={"role": role, "lp_id": lp_id}
        )
        self.stdout.write(self.style.SUCCESS(f"{user.get_username()} is {role} on {fund.name}"))
