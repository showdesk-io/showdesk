"""Serializers of the contacts API."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import DomainNameValidator
from rest_framework import serializers

from apps.tickets.serializers import TicketListSerializer

from .attributes import clean_attributes
from .models import (
    Company,
    CompanyAttributeDef,
    Contact,
    ContactAttributeDef,
    ContactNote,
)
from .summary import CompanySummarySerializer

EMAIL_TAKEN = "Another contact already uses this value."
DOMAIN_TAKEN = "Another company already uses this domain."

_domain_validator = DomainNameValidator()


def _clean_attributes(definitions, value):
    """Validate the ``attributes`` of a request, which have to be an object."""
    if not isinstance(value, dict):
        raise serializers.ValidationError("Expected an object.")
    return clean_attributes(definitions, value)


def _merged_attributes(instance, values) -> dict:
    """Return ``values`` on top of what ``instance`` stores, whatever its shape."""
    stored = instance.attributes
    return {**(stored if isinstance(stored, dict) else {}), **values}


def _write_changes(instance, validated_data):
    """Apply a PATCH to ``instance``, the row the view locked.

    Not ``ModelSerializer.update``: its full ``save()`` would write back every other
    field as read. Only what really changes is written, and nothing at all if nothing
    does.
    """
    changed = [
        field
        for field, value in validated_data.items()
        if getattr(instance, field) != value
    ]
    if changed:
        for field in changed:
            setattr(instance, field, validated_data[field])
        instance.save(update_fields=[*changed, "updated_at"])
    return instance


class ContactSerializer(serializers.ModelSerializer):
    """A contact, in the organization given by ``context["organization"]``.

    ``external_id`` is read-only: it's the identity a host app signs, and setting it
    would give the widget user of that id access to this contact's history.
    """

    company_detail = CompanySummarySerializer(source="company", read_only=True)
    email_verified = serializers.SerializerMethodField()
    display_name = serializers.CharField(read_only=True)
    tickets_count = serializers.IntegerField(read_only=True, default=0)
    open_tickets_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Contact
        fields = [
            "id",
            "display_name",
            "name",
            "email",
            "email_verified",
            "email_verified_at",
            "declared_email",
            "external_id",
            "phone",
            "avatar_url",
            "job_title",
            "locale",
            "timezone",
            "company",
            "company_detail",
            "first_seen_at",
            "last_seen_at",
            "last_contacted_at",
            "is_unsubscribed",
            "is_anonymized",
            "attributes",
            "tickets_count",
            "open_tickets_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "email_verified_at",
            "declared_email",
            "external_id",
            "first_seen_at",
            "last_seen_at",
            "last_contacted_at",
            "is_anonymized",
            "created_at",
            "updated_at",
        ]

    def get_fields(self):
        fields = super().get_fields()
        # Scoping the choices gives a company of another organization the very
        # answer of an unknown one, which doesn't tell which ids exist elsewhere.
        fields["company"].queryset = Company.objects.filter(
            organization=self.context.get("organization")
        )
        return fields

    def get_email_verified(self, obj) -> bool:
        return obj.email_verified_at is not None

    def validate_email(self, value: str) -> str:
        return (value or "").strip().lower()

    def validate_attributes(self, value):
        defs = ContactAttributeDef.objects.filter(
            organization=self.context["organization"]
        )
        return _clean_attributes(defs, value)

    def validate(self, attrs):
        # On creation only: a widget contact may have nothing but its external id,
        # and that mustn't stop an agent editing it.
        if self.instance is None and not any(
            attrs.get(field) for field in ("name", "email", "phone")
        ):
            raise serializers.ValidationError(
                "A contact needs a name, an email or a phone number."
            )
        if email := attrs.get("email"):
            taken = Contact.objects.filter(
                organization=self.context["organization"], email=email
            )
            if self.instance:
                taken = taken.exclude(pk=self.instance.pk)
            if taken.exists():
                raise serializers.ValidationError({"email": EMAIL_TAKEN})
        return attrs

    def update(self, instance, validated_data):
        if "attributes" in validated_data:
            validated_data["attributes"] = _merged_attributes(
                instance, validated_data["attributes"]
            )
        if "email" in validated_data and validated_data["email"] != instance.email:
            validated_data["email_verified_at"] = None  # The proof was of the old one.
        return _write_changes(instance, validated_data)


class CompanySerializer(serializers.ModelSerializer):
    """A company, in the organization given by ``context["organization"]``.

    ``external_id`` is read-only, as on a contact: signed widget payloads upsert a
    company on it and move their contacts there, and unsigned ones link to it.

    Editing ``domain`` doesn't relink existing contacts, neither those linked to this
    company nor those whose email matches the new domain. The domain only matters to
    the identity service, when it next resolves a contact without a company.
    """

    contacts_count = serializers.IntegerField(read_only=True, default=0)
    open_tickets_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Company
        fields = [
            "id",
            "external_id",
            "name",
            "domain",
            "logo_url",
            "industry",
            "size",
            "website",
            "plan",
            "mrr_cents",
            "health_score",
            "signed_up_at",
            "churned_at",
            "attributes",
            "contacts_count",
            "open_tickets_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "external_id", "created_at", "updated_at"]

    def validate_domain(self, value: str) -> str:
        domain = value.strip().lower()
        if not domain:
            return ""
        try:
            _domain_validator(domain)
        except DjangoValidationError as exc:
            raise serializers.ValidationError("Enter a valid domain name.") from exc
        # The validator allows one final dot, which is the same domain: left in, it
        # would get round the uniqueness.
        return domain.removesuffix(".")

    def validate_attributes(self, value):
        defs = CompanyAttributeDef.objects.filter(
            organization=self.context["organization"]
        )
        return _clean_attributes(defs, value)

    def validate(self, attrs):
        if domain := attrs.get("domain"):
            taken = Company.objects.filter(
                organization=self.context["organization"], domain=domain
            )
            if self.instance:
                taken = taken.exclude(pk=self.instance.pk)
            if taken.exists():
                raise serializers.ValidationError({"domain": DOMAIN_TAKEN})
        return attrs

    def update(self, instance, validated_data):
        if "attributes" in validated_data:
            validated_data["attributes"] = _merged_attributes(
                instance, validated_data["attributes"]
            )
        return _write_changes(instance, validated_data)


class ContactNoteSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = ContactNote
        fields = ["id", "body", "author", "author_name", "created_at"]
        read_only_fields = ["id", "author", "created_at"]

    def get_author_name(self, obj) -> str:
        if not obj.author:
            return ""
        return obj.author.get_full_name() or obj.author.email


class ContactTicketSerializer(TicketListSerializer):
    """Ticket rows shown on timelines, from ``views.timeline_tickets``.

    ``TicketListSerializer`` runs one COUNT per ticket for ``message_count``: here
    it comes from the annotation.
    """

    message_count = serializers.IntegerField(read_only=True)
