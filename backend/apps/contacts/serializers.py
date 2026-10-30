"""Serializers of the contacts API."""

from rest_framework import serializers

from apps.tickets.serializers import TicketListSerializer

from .attributes import clean_attributes
from .models import Company, Contact, ContactAttributeDef, ContactNote
from .summary import CompanySummarySerializer

EMAIL_TAKEN = "Another contact already uses this value."


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
        if not isinstance(value, dict):
            raise serializers.ValidationError("Expected an object.")
        defs = ContactAttributeDef.objects.filter(
            organization=self.context["organization"]
        )
        return clean_attributes(defs, value)

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
        """Apply a PATCH to ``instance``, the row the view locked.

        Not ``ModelSerializer.update``: its full ``save()`` would write back every
        other field as read. Only what really changes is written, and nothing at
        all if nothing does.
        """
        if "attributes" in validated_data:
            stored = instance.attributes
            validated_data["attributes"] = {
                **(stored if isinstance(stored, dict) else {}),
                **validated_data["attributes"],
            }
        if "email" in validated_data and validated_data["email"] != instance.email:
            validated_data["email_verified_at"] = None  # The proof was of the old one.
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
