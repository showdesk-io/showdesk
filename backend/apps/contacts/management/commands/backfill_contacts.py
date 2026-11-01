"""Link the rows written since the back-fill migration by pods running the old code."""

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.contacts.backfill import backfill


class Command(BaseCommand):
    help = (
        "Create and link the contacts missing from widget sessions and tickets. "
        "Idempotent. Run it once after a deploy that includes the back-fill migration, "
        "when no old pod is left: later on, it would also link again a ticket whose "
        "contact an agent cleared."
    )

    def handle(self, *args, **options):
        with transaction.atomic():
            created = backfill(apps, None)
        self.stdout.write(f"Back-fill done: {created} contact(s) created.")
