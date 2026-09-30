"""From clone to a working API in one command: seed the demo fund, print a key per role."""

from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from access.keys import issue_key
from access.models import ApiKey, FundMembership, Role
from funds.models import Fund, LimitedPartner
from operations.management.commands.seed_demo import demo_id

KEY_NAME = "demo_access"
LP_NAME = "Kelvin Family Office"
ROLES = [
    (Role.LP, "demo-lp", "LP_KEY", f"{LP_NAME}'s statement only; every other LP is a 404"),
    (Role.VIEWER, "demo-viewer", "VIEWER_KEY", "reads the whole fund; any write is a 403"),
    (
        Role.OPERATOR,
        "demo-operator",
        "OPERATOR_KEY",
        "also posts capital calls, distributions, reversals",
    ),
    (Role.CONTROLLER, "demo-controller", "CONTROLLER_KEY", "also closes periods"),
]


class Command(BaseCommand):
    help = "Seed the demo fund and print one fresh API key per role, as KEY=value lines."

    def add_arguments(self, parser):
        parser.add_argument("--api", default="http://localhost:8000", help="Base URL to print")
        parser.add_argument("--days", type=int, default=30, help="Key lifetime")
        parser.add_argument(
            "--roles",
            default="LP,VIEWER,OPERATOR,CONTROLLER",
            help="Comma-separated. In production: LP,VIEWER (read-only keys for the README)",
        )

    def handle(self, *args, **options):
        call_command("seed_demo", stdout=StringIO())
        fund = Fund.objects.get(id=demo_id("fund"))
        lp = LimitedPartner.objects.get(id=demo_id(f"lp:{LP_NAME}"))
        expires_at = timezone.now() + timedelta(days=options["days"])
        api = options["api"].rstrip("/")
        wanted = {r.strip().upper() for r in options["roles"].split(",")}
        if not wanted <= set(Role.values):
            raise CommandError(f"unknown role(s): {sorted(wanted - set(Role.values))}")

        out = [
            f"# Fund Ledger demo access. Keys expire in {options['days']} days; re-run for fresh ones.",
            f"# Try them in the browser: {api}/api/docs/ -> Authorize. Or: make tour",
            f"API={api}",
            f"FUND_ID={fund.id}",
        ]
        keys: dict[str, str] = {}
        with transaction.atomic():
            for role, username, variable, blurb in ROLES:
                if role not in wanted:
                    continue
                user, created = get_user_model().objects.get_or_create(username=username)
                if created:
                    user.set_unusable_password()  # API keys only
                    user.save(update_fields=["password"])
                FundMembership.objects.update_or_create(
                    user=user,
                    fund=fund,
                    defaults={"role": role, "lp": lp if role == Role.LP else None},
                )
                # Re-running replaces this command's keys instead of piling up live ones.
                ApiKey.objects.filter(user=user, name=KEY_NAME, revoked_at__isnull=True).update(
                    revoked_at=timezone.now()
                )
                _, keys[variable] = issue_key(user, name=KEY_NAME, expires_at=expires_at)
                out += [f"# {role}: {blurb}", f"{variable}={keys[variable]}"]
        if "OPERATOR_KEY" in keys:
            out += [
                "# The security tour's write checks use this one:",
                f"WRITE_KEY={keys['OPERATOR_KEY']}",
            ]
        self.stdout.write("\n".join(out))
