"""Mailboxes of an Organization and the emails they receive."""

import secrets
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import TimestampedModel

_LOCAL_PART_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"


def _generate_local_part(slug: str) -> str:
    """Return ``{slug}-{10 random characters}``: readable, but not guessable."""
    suffix = "".join(secrets.choice(_LOCAL_PART_ALPHABET) for _ in range(10))
    return f"{slug.lower()[:40]}-{suffix}"


def _raw_path(instance: "InboundEmail", filename: str) -> str:
    """Store a raw mail under a random name, which tells nothing of its content."""
    return f"inbound-emails/{uuid.uuid4().hex}.eml"


class Mailbox(TimestampedModel):
    """An address of an organization, receiving its forwarded support mail.

    Mail reaches it at ``{local_part}@{INBOUND_EMAIL_DOMAIN}``, usually forwarded
    from ``public_address`` (e.g. ``support@acme.com``) by the organization's own
    mail server.
    """

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="mailboxes",
    )
    name = models.CharField(max_length=100)
    local_part = models.CharField(max_length=64, unique=True, editable=False)
    public_address = models.EmailField(
        blank=True,
        help_text="The address customers write to, forwarded to the inbound address.",
    )
    default_team = models.ForeignKey(
        "organizations.Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mailboxes",
        help_text="Team assigned to the tickets this mailbox opens.",
    )
    is_active = models.BooleanField(default=True)
    forwarding_confirmation = models.JSONField(
        default=dict,
        blank=True,
        help_text="Link and code of a Gmail forwarding confirmation: {url, code, "
        "detected_at}. Taken from a mail whose sender can be forged.",
    )
    forwarding_verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When a mail last came in through the inbound address while "
        "naming the public address: forwarding from it works, so customers may "
        "reply to it. Cleared when the public address changes.",
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["public_address"],
                condition=~models.Q(public_address=""),
                name="unique_mailbox_public_address",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.organization})"

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        # What a change of the public address is told from, in ``save``.
        instance._stored_public_address = instance.__dict__.get("public_address")
        return instance

    @property
    def inbound_address(self) -> str:
        """The address the organization forwards its support mail to."""
        return f"{self.local_part}@{settings.INBOUND_EMAIL_DOMAIN}"

    def clean(self) -> None:
        super().clean()
        self.public_address = self.public_address.strip().lower()
        errors = {}
        if (
            self.default_team_id
            and self.organization_id
            and self.default_team.organization_id != self.organization_id
        ):
            errors["default_team"] = "This team belongs to another organization."
        domain = settings.INBOUND_EMAIL_DOMAIN.lower()
        if domain and self.public_address.rpartition("@")[2] == domain:
            errors["public_address"] = "Use an address outside the inbound domain."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs) -> None:
        self.public_address = self.public_address.strip().lower()
        stored = getattr(self, "_stored_public_address", None)
        if stored is not None and stored != self.public_address:
            # A proof of forwarding is about one address.
            self.forwarding_verified_at = None
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "forwarding_verified_at"}
        if not self.local_part:
            self.local_part = _generate_local_part(self.organization.slug)
        super().save(*args, **kwargs)
        self._stored_public_address = self.public_address

    def regenerate_address(self) -> None:
        """Give this mailbox a new inbound address.

        Mail the provider delivers to the previous one is then rejected, whatever
        its headers say: forwarding to it no longer counts as proven.
        """
        self.local_part = _generate_local_part(self.organization.slug)
        self.forwarding_verified_at = None
        self.save(update_fields=["local_part", "forwarding_verified_at", "updated_at"])


class InboundEmail(TimestampedModel):
    """One received email: a log, what a replay reads, and what makes delivery idempotent.

    A row without a mailbox is a mail no mailbox was found for.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSED = "processed", "Processed"
        IGNORED = "ignored", "Ignored"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"

    mailbox = models.ForeignKey(
        Mailbox,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="inbound_emails",
    )
    ticket = models.ForeignKey(
        "tickets.Ticket",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inbound_emails",
    )
    # Not ``message``: its ``message_id`` column would clash with the header's.
    ticket_message = models.ForeignKey(
        "tickets.TicketMessage",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inbound_emails",
    )
    message_id = models.CharField(
        max_length=255,
        help_text="The Message-ID header, or a hash standing for one.",
    )
    sender = models.EmailField(max_length=320, blank=True, db_index=True)
    recipients = models.JSONField(default=list, blank=True)
    # What the provider said, which the raw mail doesn't hold. The envelope
    # recipient is where the mail was delivered: its headers only say where the
    # sender claims it went.
    envelope_recipient = models.CharField(max_length=320, blank=True)
    envelope_sender = models.CharField(max_length=320, blank=True)
    spam_detected = models.BooleanField(
        null=True, blank=True, help_text="The provider's verdict, when it gives one."
    )
    spam_score = models.FloatField(null=True, blank=True)
    subject = models.CharField(max_length=998, blank=True)
    # Never exposed by URL: a mail holds personal data.
    raw = models.FileField(upload_to=_raw_path, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    reason = models.CharField(
        max_length=50,
        blank=True,
        help_text="Why it was ignored, rejected or failed (e.g. auto_reply).",
    )
    received_at = models.DateTimeField(default=timezone.now, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["message_id", "mailbox"],
                name="unique_inbound_per_mailbox",
            ),
            # NULLs are distinct in the constraint above. A mail rejected without
            # a mailbox (to an old reply address, say) leaves room for the same
            # one delivered where it belongs.
            models.UniqueConstraint(
                fields=["message_id"],
                condition=models.Q(mailbox__isnull=True) & ~models.Q(status="rejected"),
                name="unique_inbound_without_mailbox",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.message_id} ({self.status})"


class SendingRemoval(models.Model):
    """A sending registration still to remove at the provider (§7).

    Recorded in the transaction that takes the ref off its domain row, so a
    removal outlives the row (deleted, or registered again by its new owner)
    and its retries can be seen. While one exists for a domain, nobody may
    register that domain again.
    """

    domain = models.CharField(max_length=255, db_index=True)
    ref = models.CharField(max_length=255, unique=True)
    provider = models.CharField(
        max_length=32,
        blank=True,
        help_text=(
            "The provider that made the registration: only it removes it. "
            'Blank if unknown (recorded while the provider was "none").'
        ),
    )
    created_at = models.DateTimeField(default=timezone.now)
    attempts = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.domain} ({self.ref})"
