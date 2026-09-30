import os

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from ledger.db_roles import apply_grants, ensure_login_role


class Command(BaseCommand):
    help = "Create/update the least-privilege application role and re-apply its grants."

    def handle(self, *args, **options):
        role = os.environ.get("APP_DB_USER", "ledger_app")
        password = os.environ.get("APP_DB_PASSWORD", "")
        if not password:
            raise CommandError("APP_DB_PASSWORD must be set")
        if role == connection.settings_dict["USER"]:
            raise CommandError("run this as the owner role, not as the app role")
        with transaction.atomic():  # other sessions see the old or new ACL, never a half-state
            ensure_login_role(role, password)
            apply_grants(role)
        self.stdout.write(self.style.SUCCESS(f"Role {role} ready with least-privilege grants"))
