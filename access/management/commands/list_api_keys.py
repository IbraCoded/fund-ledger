from django.core.management.base import BaseCommand

from access.models import ApiKey


class Command(BaseCommand):
    help = "List API keys (prefixes only; secrets are never stored)."

    def handle(self, *args, **options):
        for key in ApiKey.objects.select_related("user").order_by("user__username", "created_at"):
            state = "revoked" if key.revoked_at else f"expires {key.expires_at or 'never'}"
            self.stdout.write(
                f"{key.prefix}  {key.user.get_username():<20} {key.name:<20} {state}  "
                f"last used {key.last_used_at or 'never'}"
            )
