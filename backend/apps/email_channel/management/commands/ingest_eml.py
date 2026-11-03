"""Feed a raw mail to the inbound pipeline, as a provider's webhook would."""

import sys

from anymail.inbound import AnymailInboundMessage
from django.core.management.base import BaseCommand

from apps.email_channel.inbound import store
from apps.email_channel.models import InboundEmail
from config.celery import app


class Command(BaseCommand):
    help = (
        "Store a raw mail (.eml) and run it through the inbound pipeline, as if a "
        "provider had delivered it. For testing, replaying, or a self-hosted setup "
        "without an inbound provider."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("file", help="Path of the .eml file, or - for stdin.")
        parser.add_argument(
            "--recipient",
            default=None,
            help="Envelope recipient, as a provider would give it (e.g. the "
            "mailbox's inbound address).",
        )

    def handle(self, *args, **options) -> None:
        if options["file"] == "-":
            raw = sys.stdin.buffer.read()
        else:
            with open(options["file"], "rb") as file:
                raw = file.read()
        message = AnymailInboundMessage.parse_raw_mime_bytes(raw)
        message.envelope_recipient = options["recipient"]

        inbound = store(message, raw=raw)
        if inbound is None:
            self.stdout.write("Duplicate: this mail was already stored.")
            return
        if inbound.status == InboundEmail.Status.PENDING and not (
            app.conf.task_always_eager
        ):
            self.stdout.write(f"{inbound.id} queued")
            return
        inbound.refresh_from_db()
        reason = f" ({inbound.reason})" if inbound.reason else ""
        self.stdout.write(f"{inbound.id} {inbound.status}{reason}")
