"""Serializers of the email channel: its settings, and its public routes."""

import copy

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.core.permissions import is_org_admin
from apps.core.serializers import OrgScopedPrimaryKeyRelatedField
from apps.email_channel.models import InboundEmail, Mailbox
from apps.organizations.models import OrganizationDomain, Team
from apps.tickets.models import TicketMessage
from apps.tickets.serializers import WidgetMessageSerializer

PUBLIC_ADDRESS_TAKEN = "Another mailbox already uses this address."
DOMAIN_NOT_VERIFIED = "Verify {domain} for your organization first."


class MailboxSerializer(serializers.ModelSerializer):
    """A mailbox, in the organization given by ``context["organization"]``.

    Validated by the model's ``full_clean()`` too: the rules on the public address
    and the default team are in ``Mailbox.clean()``. The Gmail forwarding
    confirmation is for admins, who set the forwarding up.
    """

    default_team = OrgScopedPrimaryKeyRelatedField(
        queryset=Team.objects.all(), required=False, allow_null=True
    )
    inbound_address = serializers.SerializerMethodField()

    class Meta:
        model = Mailbox
        fields = [
            "id",
            "name",
            "local_part",
            "inbound_address",
            "public_address",
            "default_team",
            "is_active",
            "forwarding_confirmation",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "local_part",
            "forwarding_confirmation",
            "created_at",
            "updated_at",
        ]
        # Checked in ``validate``, on the lowercased address, with a clearer answer.
        validators: list = []

    def get_inbound_address(self, mailbox: Mailbox) -> str:
        return mailbox.inbound_address if settings.INBOUND_EMAIL_DOMAIN else ""

    def validate(self, attrs: dict) -> dict:
        if self.instance is not None:
            candidate = copy.copy(self.instance)
        else:
            candidate = Mailbox(organization=self.context["organization"])
        for field, value in attrs.items():
            setattr(candidate, field, value)
        try:
            # The unique constraint is checked below, with a clearer message.
            candidate.full_clean(exclude=["local_part"], validate_constraints=False)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc
        if "public_address" in attrs:
            attrs["public_address"] = candidate.public_address
            self._check_domain_owned(candidate)
            if candidate.public_address and (
                Mailbox.objects.filter(public_address=candidate.public_address)
                .exclude(pk=candidate.pk)
                .exists()
            ):
                raise serializers.ValidationError(
                    {"public_address": [PUBLIC_ADDRESS_TAKEN]}
                )
        return attrs

    def _check_domain_owned(self, candidate: Mailbox) -> None:
        """A new public address needs its domain verified by the organization.

        Nobody may reserve an address on a domain they haven't proven theirs.
        An address set before this rule, left unchanged, stays.
        """
        address = candidate.public_address
        if not address or (
            self.instance is not None and address == self.instance.public_address
        ):
            return
        domain = address.rpartition("@")[2]
        if not OrganizationDomain.objects.filter(
            organization_id=candidate.organization_id,
            domain=domain,
            status=OrganizationDomain.Status.VERIFIED,
        ).exists():
            raise serializers.ValidationError(
                {"public_address": [DOMAIN_NOT_VERIFIED.format(domain=domain)]}
            )

    def to_representation(self, instance: Mailbox) -> dict:
        data = super().to_representation(instance)
        request = self.context.get("request")
        if not (request and is_org_admin(request.user)):
            data.pop("forwarding_confirmation", None)
        return data


class InboundLogSerializer(serializers.ModelSerializer):
    """A received mail, as a mailbox's log lists it. Never its raw mail."""

    class Meta:
        model = InboundEmail
        fields = [
            "id",
            "sender",
            "subject",
            "status",
            "reason",
            "received_at",
            "processed_at",
        ]
        read_only_fields = fields


class ConversationReplySerializer(serializers.Serializer):
    """A message written on the conversation page."""

    body = serializers.CharField(max_length=10000)


class ConversationAttachmentSerializer(serializers.Serializer):
    """A file sent from the conversation page, with an optional message.

    The file itself is checked by ``TicketAttachmentSerializer``, as the widget's.
    """

    file = serializers.FileField()
    body = serializers.CharField(
        max_length=10000, required=False, allow_blank=True, default=""
    )


class ConversationMessageSerializer(WidgetMessageSerializer):
    """A message as the conversation page shows it.

    No name on the requester's side: the ticket's session, or a mail's sender, may
    be someone other than the person the link was mailed to.
    """

    sender_name = serializers.SerializerMethodField()

    class Meta(WidgetMessageSerializer.Meta):
        fields = [f for f in WidgetMessageSerializer.Meta.fields if f != "deletable"]
        read_only_fields = fields

    def get_sender_name(self, message: TicketMessage) -> str:
        if message.sender_type == TicketMessage.SenderType.USER:
            return ""
        return message.sender_name
