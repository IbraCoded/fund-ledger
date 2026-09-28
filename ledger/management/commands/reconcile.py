import argparse
from datetime import UTC, datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from ledger.reconciliation import total_imbalance, unbalanced_transfers


def _as_of(value: str) -> datetime:
    parsed = parse_datetime(value)
    if parsed is None:
        raise argparse.ArgumentTypeError(f"not an ISO-8601 datetime: {value!r}")
    return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed, UTC)


class Command(BaseCommand):
    help = "Verify the ledger balances. Exits non-zero on any imbalance."

    def add_arguments(self, parser):
        parser.add_argument(
            "--as-of", type=_as_of, default=None, help="ISO-8601 timestamp (UTC if naive)"
        )

    def handle(self, *args, as_of=None, **options):
        imbalance = total_imbalance(as_of=as_of)
        broken = unbalanced_transfers()
        for transfer_id, amount in broken:
            self.stderr.write(f"  transfer {transfer_id} is off by {amount}")
        if imbalance != 0 or broken:
            raise CommandError(
                f"LEDGER OUT OF BALANCE: system imbalance {imbalance}, "
                f"{len(broken)} unbalanced transfer(s)"
            )
        when = as_of.isoformat() if as_of else "now"
        self.stdout.write(
            self.style.SUCCESS(f"Ledger balanced as of {when} (imbalance {imbalance})")
        )
