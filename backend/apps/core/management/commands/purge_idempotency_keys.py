"""Management command to purge old idempotency records."""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.models import IdempotencyRecord


class Command(BaseCommand):
    """
    Purge old idempotency records.

    This command deletes IdempotencyRecord entries older than N days.
    Default is 30 days.

    IMPORTANT: Business tables (invoices, purchases, receipts, credit notes, payouts)
    also carry their own unique idempotency_key column which is NEVER purged.
    This table (IdempotencyRecord) is only the first line of defence against
    duplicate requests and can be safely purged after a reasonable retention period.
    """

    help = "Delete idempotency records older than N days (default 30)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Delete records older than this many days (default: 30). Use 0 to delete all.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        cutoff = timezone.now() - timedelta(days=days)

        if days == 0:
            queryset = IdempotencyRecord.objects.all()
            count = queryset.count()
            queryset.delete()
            self.stdout.write(
                self.style.SUCCESS(f"Deleted {count} idempotency record(s) (all records)")
            )
        else:
            queryset = IdempotencyRecord.objects.filter(created_at__lt=cutoff)
            count = queryset.count()
            queryset.delete()
            self.stdout.write(
                self.style.SUCCESS(f"Deleted {count} idempotency record(s) older than {days} days")
            )
