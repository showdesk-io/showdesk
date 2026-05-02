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


# Email domains where multiple unrelated companies share inboxes. Signups
# from these domains never trigger the auto-join flow — each user creates
# their own organization. Extend by setting SHOWDESK_PUBLIC_EMAIL_DOMAINS
# in the environment.
PUBLIC_EMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "hotmail.com",
        "hotmail.fr",
        "outlook.com",
        "outlook.fr",
        "live.com",
        "msn.com",
        "yahoo.com",
        "yahoo.fr",
        "ymail.com",
        "icloud.com",
        "me.com",
        "mac.com",
        "protonmail.com",
        "proton.me",
        "pm.me",
        "aol.com",
        "gmx.com",
        "gmx.de",
        "mail.com",
        "mail.ru",
        "yandex.com",
        "yandex.ru",
        "qq.com",
        "163.com",
        "126.com",
        "free.fr",
        "orange.fr",
        "wanadoo.fr",
        "laposte.net",
        "sfr.fr",
    }
)


def extract_email_domain(email: str) -> str:
    """Return the lowercased domain of an email, or '' if invalid."""
    if not email or "@" not in email:
        return ""
    return email.rsplit("@", 1)[-1].strip().lower()


def is_public_email_domain(domain: str) -> bool:
    """Return True if the domain is a shared/public webmail provider."""
    return domain.lower() in PUBLIC_EMAIL_DOMAINS


class Organization(TimestampedModel):
    """A company or entity that uses Showdesk to manage support tickets.

    Each organization has its own set of agents, teams, tickets, and
    configuration. The widget is scoped to a single organization via
    its API token.
    """

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
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

    # Branding (agent dashboard + transactional emails). Distinct from
    # ``widget_color`` so the embedded widget can have its own accent
    # without dragging the dashboard along.
    primary_color = models.CharField(
        max_length=7,
        blank=True,
        default="",
        help_text=(
            "Primary brand color (hex, e.g. #6366F1). Used in the dashboard "
            "and in branded emails. Falls back to the Showdesk default when empty."
        ),
    )
    email_from_name = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text=(
            "Display name shown in the From: header of transactional emails "
            "(e.g. \"Acme Support\"). Falls back to the Showdesk brand name "
            "when empty."
        ),
    )

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

    # Self-service signup
    onboarding_completed_at = models.DateTimeField(null=True, blank=True)
    onboarding_step = models.PositiveSmallIntegerField(
        default=0,
        help_text="Last completed step of the post-signup onboarding wizard.",
    )
    widget_first_seen_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Timestamp of the first widget request authenticated with this "
            "org's api_token. Powers the install-detection step in onboarding."
        ),
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


class OrganizationDomain(TimestampedModel):
    """A domain claimed by an organization for branding and/or email routing.

    Two independent purposes:
      - is_branding:      shown publicly (replaces the legacy `domain` field).
      - is_email_routing: drives the signup auto-join flow (replaces the
                          legacy `email_domain` field).

    A row may serve one or both. At least one must be set (DB-checked).

    Verification:
      - admin_email: an admin in the org has a verified email on this domain.
                     Only valid for is_email_routing rows. Set automatically
                     at signup; refused later if the domain is already
                     verified by another org.
      - dns_txt:     the org has placed `showdesk-verification=<token>` as
                     a TXT record on `_showdesk.<domain>`. Required for
                     branding domains and for any email_routing domain that
                     does not match the admin's email.

    Ownership transfer: at most one verified row per `domain` exists
    globally (partial unique index). When org B's DNS challenge succeeds
    on a domain org A holds, A flips to `failed` and B becomes `verified`.
    Once verified, a row stays verified forever unless transferred.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        VERIFIED = "verified", "Verified"
        FAILED = "failed", "Failed"

    class VerificationMethod(models.TextChoices):
        ADMIN_EMAIL = "admin_email", "Admin email"
        DNS_TXT = "dns_txt", "DNS TXT"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="domains",
    )
    domain = models.CharField(max_length=255, db_index=True)
    is_branding = models.BooleanField(default=False)
    is_email_routing = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    verification_method = models.CharField(
        max_length=20,
        choices=VerificationMethod.choices,
        blank=True,
        null=True,
    )
    verification_token = models.CharField(
        max_length=64,
        blank=True,
        help_text="Random token the admin embeds in the DNS TXT record.",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    last_check_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "domain"],
                name="unique_org_domain",
            ),
            models.UniqueConstraint(
                fields=["domain"],
                condition=models.Q(status="verified"),
                name="unique_verified_domain_globally",
            ),
            models.CheckConstraint(
                condition=models.Q(is_branding=True)
                | models.Q(is_email_routing=True),
                name="domain_has_at_least_one_purpose",
            ),
        ]
        indexes = [
            models.Index(fields=["domain", "status"]),
        ]

    def __str__(self) -> str:
        purposes = []
        if self.is_email_routing:
            purposes.append("routing")
        if self.is_branding:
            purposes.append("branding")
        return f"{self.domain} [{','.join(purposes)}] ({self.status})"

    @staticmethod
    def generate_token() -> str:
        """Return a random 32-char hex token for DNS TXT verification."""
        return secrets.token_hex(16)

    @property
    def txt_record_name(self) -> str:
        """The hostname where the admin must place the TXT record."""
        return f"_showdesk.{self.domain}"

    @property
    def txt_record_value(self) -> str:
        """The full TXT record value the admin must publish."""
        return f"showdesk-verification={self.verification_token}"


class OrgJoinRequest(TimestampedModel):
    """A pending request to join an existing organization.

    Created when someone signs up with an email whose domain matches an
    existing org's `email_domain`. An admin of the target org must
    approve or reject the request before a User row is provisioned.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="join_requests",
    )
    email = models.EmailField(db_index=True)
    full_name = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="decided_join_requests",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "email"],
                condition=models.Q(status="pending"),
                name="unique_pending_join_request_per_email",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.email} -> {self.organization.name} ({self.status})"
