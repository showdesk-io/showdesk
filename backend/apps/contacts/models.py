"""Contacts (end-users) and Companies of an Organization."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import TimestampedModel

from .attributes import validate_options


def _normalize(value: str) -> str:
    """Canonical form of an email or domain, as stored and compared."""
    return (value or "").strip().lower()


class Company(TimestampedModel):
    """The business a Contact belongs to (a customer of the Organization)."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="companies",
    )
    external_id = models.CharField(max_length=255, blank=True, default="")
    name = models.CharField(max_length=255)
    domain = models.CharField(max_length=255, blank=True, default="")
    logo_url = models.URLField(blank=True)
    industry = models.CharField(max_length=100, blank=True)
    size = models.CharField(max_length=50, blank=True)
    website = models.URLField(blank=True)
    plan = models.CharField(max_length=100, blank=True)
    mrr_cents = models.PositiveIntegerField(null=True, blank=True)
    health_score = models.PositiveSmallIntegerField(null=True, blank=True)
    signed_up_at = models.DateTimeField(null=True, blank=True)
    churned_at = models.DateTimeField(null=True, blank=True)
    attributes = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["name", "id"]
        verbose_name_plural = "companies"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "external_id"],
                condition=~Q(external_id=""),
                name="unique_company_external_id_per_org",
            ),
            models.UniqueConstraint(
                fields=["organization", "domain"],
                condition=~Q(domain=""),
                name="unique_company_domain_per_org",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        super().clean()
        self.domain = _normalize(self.domain)

    def save(self, *args, **kwargs) -> None:
        self.domain = _normalize(self.domain)
        super().save(*args, **kwargs)


class Contact(TimestampedModel):
    """An end-user talking to an Organization's support."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="contacts",
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contacts",
    )
    email = models.EmailField(blank=True, default="")
    email_verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set once the contact proved they own this email address.",
    )
    declared_email = models.EmailField(
        blank=True,
        default="",
        help_text="Unproven email given by an identified session. Grants nothing.",
    )
    external_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="User ID in the host application (HMAC-verified widget identity).",
    )
    phone = models.CharField(max_length=30, blank=True)
    name = models.CharField(max_length=255, blank=True)
    avatar_url = models.URLField(blank=True)
    job_title = models.CharField(max_length=255, blank=True)
    locale = models.CharField(max_length=10, blank=True)
    timezone = models.CharField(max_length=50, blank=True)
    first_seen_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_contacted_at = models.DateTimeField(null=True, blank=True)
    is_unsubscribed = models.BooleanField(default=False)
    is_anonymized = models.BooleanField(default=False)
    attributes = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = [models.F("last_seen_at").desc(nulls_last=True), "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "email"],
                condition=~Q(email=""),
                name="unique_contact_email_per_org",
            ),
            models.UniqueConstraint(
                fields=["organization", "external_id"],
                condition=~Q(external_id=""),
                name="unique_contact_external_id_per_org",
            ),
        ]
        indexes = [models.Index(fields=["organization", "company"])]

    def __str__(self) -> str:
        return self.display_name

    @property
    def display_name(self) -> str:
        return self.name or self.email or self.external_id or "Anonymous contact"

    def clean(self) -> None:
        super().clean()
        self.email = _normalize(self.email)
        self.declared_email = _normalize(self.declared_email)
        if (
            self.company_id
            and self.organization_id
            and Company.objects.filter(pk=self.company_id)
            .exclude(organization_id=self.organization_id)
            .exists()
        ):
            raise ValidationError(
                {"company": "This company belongs to another organization."}
            )

    def save(self, *args, **kwargs) -> None:
        self.email = _normalize(self.email)
        self.declared_email = _normalize(self.declared_email)
        super().save(*args, **kwargs)


class CustomAttributeDef(TimestampedModel):
    """Definition of a custom attribute an Organization adds to an entity."""

    MAX_PER_ORGANIZATION = 50

    class Type(models.TextChoices):
        STRING = "string", "Text"
        NUMBER = "number", "Number"
        BOOLEAN = "boolean", "Yes/No"
        DATE = "date", "Date"
        ENUM = "enum", "List"
        URL = "url", "URL"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="+"
    )
    key = models.SlugField(max_length=64, help_text="snake_case, immutable.")
    label = models.CharField(max_length=120)
    type = models.CharField(max_length=10, choices=Type.choices)
    description = models.TextField(blank=True)
    options = models.JSONField(default=list, blank=True)
    is_archived = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        abstract = True
        ordering = ["position", "label", "id"]

    def __str__(self) -> str:
        return f"{self.label} ({self.key})"

    def clean(self) -> None:
        super().clean()
        if self.options is None:  # An emptied field of the admin form.
            self.options = []
        try:
            validate_options(self.type, self.options)
        except ValidationError as exc:
            raise ValidationError({"options": exc.messages}) from exc


class ContactAttributeDef(CustomAttributeDef):
    """Custom attribute definition for an Organization's contacts."""

    class Meta(CustomAttributeDef.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "key"], name="unique_contact_attr_key"
            )
        ]


class CompanyAttributeDef(CustomAttributeDef):
    """Custom attribute definition for an Organization's companies."""

    class Meta(CustomAttributeDef.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "key"], name="unique_company_attr_key"
            )
        ]


class ContactNote(TimestampedModel):
    """Internal note written by an agent on a contact."""

    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    body = models.TextField()

    def __str__(self) -> str:
        return f"Note on {self.contact.display_name}"
