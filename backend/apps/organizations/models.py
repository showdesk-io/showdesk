"""Organization, Team, User, and OTP models."""

import hashlib
import hmac
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone

from apps.core.models import TimestampedModel

# Slug of the internal organization used for dogfooding — tickets submitted
# by Showdesk staff via the in-app widget are scoped here.
SHOWDESK_INTERNAL_ORG_SLUG = "showdesk-internal"


class Organization(TimestampedModel):
    """A company or entity that uses Showdesk to manage support tickets.

    Each organization has its own set of agents, teams, tickets, and
    configuration. The widget is scoped to a single organization via
    its API token.
    """

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    domain = models.CharField(
        max_length=255,
        blank=True,
        help_text="Primary domain for this organization.",
    )
    logo = models.ImageField(upload_to="organizations/logos/", blank=True)
    api_token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        help_text="Public token used by the widget to authenticate requests.",
    )
    widget_secret = models.CharField(
        max_length=64,
        default=secrets.token_hex,
        help_text="Secret key for HMAC identity verification. Never expose client-side.",
    )
    is_active = models.BooleanField(default=True)

    # Widget configuration
    widget_color = models.CharField(
        max_length=7,
        default="#6366F1",
        help_text="Primary color for the widget (hex).",
    )
    widget_position = models.CharField(
        max_length=20,
        default="bottom-right",
        choices=[
            ("bottom-right", "Bottom Right"),
            ("bottom-left", "Bottom Left"),
        ],
    )
    widget_greeting = models.CharField(
        max_length=255,
        default="How can we help you?",
    )

    # Video settings
    video_expiration_days = models.PositiveIntegerField(
        default=90,
        help_text="Number of days before recorded videos are automatically deleted.",
    )
    video_max_duration_seconds = models.PositiveIntegerField(
        default=600,
        help_text="Maximum recording duration in seconds.",
    )

    # Ticket reference counter (atomic increment)
    ticket_counter = models.PositiveIntegerField(
        default=0,
        help_text="Auto-incremented counter for generating ticket references.",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @staticmethod
    def generate_widget_secret() -> str:
        """Generate a 64-char hex secret for HMAC identity verification."""
        return secrets.token_hex(32)

    def verify_user_hash(self, external_user_id: str, user_hash: str) -> bool:
        """Verify an HMAC-SHA256 user hash against the widget secret."""
        if not self.widget_secret:
            return False
        expected = hmac.new(
            self.widget_secret.encode(),
            external_user_id.encode(),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, user_hash)

    def next_ticket_reference(self) -> str:
        """Generate the next ticket reference atomically.

        Uses F() expressions and select_for_update to guarantee
        uniqueness even under concurrent requests.
        """
        from django.db.models import F

        Organization.objects.filter(pk=self.pk).update(
            ticket_counter=F("ticket_counter") + 1
        )
        self.refresh_from_db(fields=["ticket_counter"])
        return f"SD-{self.ticket_counter:04d}"


class UserManager(BaseUserManager):
    """Custom user manager that uses email as the unique identifier."""

    def create_user(
        self,
        email: str,
        password: str | None = None,
        **extra_fields,  # noqa: ANN003
    ) -> "User":
        """Create and return a regular user."""
        if not email:
            raise ValueError("Users must have an email address.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(
        self,
        email: str,
        password: str | None = None,
        **extra_fields,  # noqa: ANN003
    ) -> "User":
        """Create and return a superuser."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMIN)
        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Custom user model for Showdesk.

    Users can be either agents (who handle tickets) or end-users
    (customers who submit tickets). The role field determines their
    permissions and UI experience.
    """

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        AGENT = "agent", "Agent"
        END_USER = "end_user", "End User"

    # Remove username field, use email instead
    username = None
    email = models.EmailField(unique=True)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="users",
        null=True,
        blank=True,
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.END_USER,
    )
    avatar = models.ImageField(upload_to="users/avatars/", blank=True)
    phone = models.CharField(max_length=30, blank=True)
    timezone = models.CharField(max_length=50, default="UTC")
    is_available = models.BooleanField(
        default=True,
        help_text="Whether this agent is currently available for ticket assignment.",
    )
    is_verified = models.BooleanField(
        default=False,
        help_text="Whether this user has verified their email via OTP at least once.",
    )

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ["email"]

    def __str__(self) -> str:
        return self.email

    @property
    def is_agent(self) -> bool:
        """Check if user is an agent or admin."""
        return self.role in (self.Role.AGENT, self.Role.ADMIN)


class Team(TimestampedModel):
    """A group of agents within an organization.

    Teams allow organizing agents by specialty, department, or any
    other grouping. Tickets can be assigned to a team rather than
    a specific agent.
    """

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="teams",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    members = models.ManyToManyField(
        User,
        related_name="teams",
        blank=True,
    )
    lead = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="led_teams",
    )

    class Meta:
        ordering = ["name"]
        unique_together = ["organization", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.organization})"


class OTPCode(models.Model):
    """One-time password for passwordless email authentication.

    A new code is generated for each login attempt. Codes expire after
    OTP_EXPIRY_SECONDS (default 10 minutes) and can only be used once.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(db_index=True)
    code = models.CharField(max_length=8)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["email", "code", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"OTP for {self.email} ({self.code})"

    @property
    def is_expired(self) -> bool:
        """Check if this OTP has expired."""
        expiry = getattr(settings, "OTP_EXPIRY_SECONDS", 600)
        return timezone.now() > self.created_at + timedelta(seconds=expiry)

    @property
    def is_valid(self) -> bool:
        """Check if this OTP can still be used."""
        return self.used_at is None and not self.is_expired

    def mark_used(self) -> None:
        """Mark this OTP as used."""
        self.used_at = timezone.now()
        self.save(update_fields=["used_at"])

    @classmethod
    def generate(cls, email: str) -> "OTPCode":
        """Generate a new OTP code for the given email.

        Invalidates any existing unused codes for this email.
        """
        # Invalidate previous unused codes
        cls.objects.filter(email=email, used_at__isnull=True).update(
            used_at=timezone.now()
        )

        length = getattr(settings, "OTP_LENGTH", 6)
        code = "".join(secrets.choice("0123456789") for _ in range(length))
        return cls.objects.create(email=email, code=code)
