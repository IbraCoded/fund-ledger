from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from access.keys import issue_key


class Command(BaseCommand):
    help = "Issue an API key for a user. The key is printed once and cannot be recovered."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--name", required=True, help="What this key is for, e.g. 'laptop'")
        parser.add_argument("--expires-in-days", type=int, default=365, help="0 = never")

    def handle(self, *args, **options):
        user = get_user_model().objects.filter(username=options["username"]).first()
        if user is None:
            raise CommandError("no such user (create one with grant_access)")
        days = options["expires_in_days"]
        expires_at = timezone.now() + timedelta(days=days) if days > 0 else None
        api_key, raw = issue_key(user, name=options["name"], expires_at=expires_at)
        self.stdout.write(
            f"Key {api_key.prefix} for {user.get_username()}, expires {expires_at or 'never'}:"
        )
        self.stdout.write(raw)
        self.stderr.write("Store it now. It is not stored anywhere and cannot be shown again.")
