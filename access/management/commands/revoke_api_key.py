from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from access.models import ApiKey


class Command(BaseCommand):
    help = "Revoke an API key by its public prefix. Takes effect on the next request."

    def add_arguments(self, parser):
        parser.add_argument("prefix")

    def handle(self, *args, **options):
        revoked = ApiKey.objects.filter(prefix=options["prefix"], revoked_at__isnull=True).update(
            revoked_at=timezone.now()
        )
        if not revoked:
            raise CommandError("no active key with that prefix")
        self.stdout.write(self.style.SUCCESS(f"Revoked {options['prefix']}"))
