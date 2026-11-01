"""Serializers for ticket-related models."""

from django.db.models import Count, Q
from rest_framework import serializers
from rest_framework.fields import empty

from apps.contacts.attributes import is_storable
from apps.contacts.models import Contact
from apps.contacts.summary import ContactSummarySerializer
from apps.core.permissions import get_active_org
from apps.core.serializers import (
    OrgScopedPrimaryKeyRelatedField,
    read_only_organization_field,
)
from apps.organizations.models import RESERVED_EXTERNAL_ID_PREFIXES, Team, User
from apps.organizations.serializers import UserSerializer

from .models import (
    CannedResponse,
    PriorityLevel,
    SavedView,
    SLAPolicy,
    Tag,
    Ticket,
    TicketAttachment,
    TicketMessage,
    WidgetSession,
)


class PriorityLevelSerializer(serializers.ModelSerializer):
    """Serializer for the PriorityLevel model."""

    organization = read_only_organization_field()

    class Meta:
        model = PriorityLevel
        fields = [
            "id",
            "organization",
            "name",
            "slug",
            "color",
            "position",
            "is_default",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class TagSerializer(serializers.ModelSerializer):
    """Serializer for the Tag model."""

    organization = read_only_organization_field()

    class Meta:
        model = Tag
        fields = ["id", "organization", "name", "color", "created_at"]
        read_only_fields = ["id", "created_at"]


class SLAPolicySerializer(serializers.ModelSerializer):
    """Serializer for the SLAPolicy model.

    ``organization`` is set server-side from the active org in the
    viewset's ``perform_create`` -- exposing it as writable would let a
    caller forge cross-org rows. The ``unique_together`` (org, priority)
    is enforced explicitly here so duplicates surface as a clean 400
    instead of an unhandled IntegrityError.
    """

    class Meta:
        model = SLAPolicy
        fields = [
            "id",
            "organization",
            "name",
            "priority",
            "first_response_minutes",
            "resolution_minutes",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "organization", "created_at", "updated_at"]

    def validate_priority(self, value: str) -> str:
        request = self.context.get("request")
        if request is None:
            return value
        org = get_active_org(request)
        if org is None:
            return value
        qs = SLAPolicy.objects.filter(organization=org, priority=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                f"A policy for priority '{value}' already exists in this organization."
            )
        return value


class TicketAttachmentSerializer(serializers.ModelSerializer):
    """Serializer for ticket attachments with file validation."""

    ticket = OrgScopedPrimaryKeyRelatedField(queryset=Ticket.objects.all())
    message = OrgScopedPrimaryKeyRelatedField(
        queryset=TicketMessage.objects.all(),
        org_field="ticket__organization",
        required=False,
        allow_null=True,
    )

    # Max 20 MB per file
    MAX_FILE_SIZE = 20 * 1024 * 1024

    # Blocked extensions (executable, dangerous)
    BLOCKED_EXTENSIONS = frozenset(
        {
            ".exe",
            ".bat",
            ".cmd",
            ".com",
            ".msi",
            ".scr",
            ".pif",
            ".vbs",
            ".vbe",
            ".js",
            ".jse",
            ".wsf",
            ".wsh",
            ".ps1",
            ".sh",
            ".csh",
            ".dll",
            ".sys",
        }
    )

    class Meta:
        model = TicketAttachment
        fields = [
            "id",
            "ticket",
            "message",
            "uploaded_by",
            "file",
            "filename",
            "content_type",
            "file_size",
            "created_at",
        ]
        read_only_fields = ["id", "uploaded_by", "created_at"]

    def validate_file(self, value):
        """Validate file size and type."""
        if value.size > self.MAX_FILE_SIZE:
            max_mb = self.MAX_FILE_SIZE // (1024 * 1024)
            raise serializers.ValidationError(
                f"File size exceeds the {max_mb} MB limit."
            )

        import os

        _, ext = os.path.splitext(value.name)
        if ext.lower() in self.BLOCKED_EXTENSIONS:
            raise serializers.ValidationError(f"File type '{ext}' is not allowed.")

        return value


class TicketMessageSerializer(serializers.ModelSerializer):
    """Serializer for ticket messages."""

    ticket = OrgScopedPrimaryKeyRelatedField(queryset=Ticket.objects.all())
    author_detail = UserSerializer(source="author", read_only=True)
    attachments = TicketAttachmentSerializer(many=True, read_only=True)
    sender_name = serializers.CharField(read_only=True)

    class Meta:
        model = TicketMessage
        fields = [
            "id",
            "ticket",
            "author",
            "author_detail",
            "body",
            "message_type",
            "sender_type",
            "body_type",
            "sender_name",
            "attachments",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "author", "created_at", "updated_at"]


# Who a ticket can be assigned to, as in the bulk_update action.
ASSIGNABLE_AGENTS = User.objects.filter(
    role__in=[User.Role.AGENT, User.Role.ADMIN], is_active=True
)


class TicketContactField(OrgScopedPrimaryKeyRelatedField):
    """A contact of the active organization that a ticket can take.

    An anonymized contact takes no more tickets, but a ticket can keep the one it has.
    """

    def get_queryset(self):
        taken = Q(is_anonymized=False)
        ticket = self.parent.instance
        if ticket is not None:
            taken |= Q(pk=ticket.contact_id)
        return super().get_queryset().filter(taken)


class TicketSerializer(serializers.ModelSerializer):
    """Serializer for the Ticket model."""

    from apps.videos.serializers import VideoRecordingSerializer

    messages = TicketMessageSerializer(many=True, read_only=True)
    videos = VideoRecordingSerializer(many=True, read_only=True)
    tags_detail = TagSerializer(source="tags", many=True, read_only=True)
    tag_ids = OrgScopedPrimaryKeyRelatedField(
        many=True,
        queryset=Tag.objects.all(),
        source="tags",
        write_only=True,
        required=False,
    )
    requester = OrgScopedPrimaryKeyRelatedField(
        queryset=User.objects.all(), required=False, allow_null=True
    )
    requester_detail = UserSerializer(source="requester", read_only=True)
    assigned_agent = OrgScopedPrimaryKeyRelatedField(
        queryset=ASSIGNABLE_AGENTS, required=False, allow_null=True
    )
    assigned_agent_detail = UserSerializer(source="assigned_agent", read_only=True)
    assigned_team = OrgScopedPrimaryKeyRelatedField(
        queryset=Team.objects.all(), required=False, allow_null=True
    )
    sla_policy = OrgScopedPrimaryKeyRelatedField(
        queryset=SLAPolicy.objects.all(), required=False, allow_null=True
    )
    contact = TicketContactField(
        queryset=Contact.objects.all(), required=False, allow_null=True
    )
    contact_detail = ContactSummarySerializer(source="contact", read_only=True)
    sender_verified = serializers.BooleanField(read_only=True, allow_null=True)

    class Meta:
        model = Ticket
        fields = [
            "id",
            "organization",
            "reference",
            "title",
            "description",
            "status",
            "priority",
            "source",
            "requester",
            "requester_detail",
            "requester_name",
            "requester_email",
            "contact",
            "contact_detail",
            "sender_verified",
            "assigned_agent",
            "assigned_agent_detail",
            "assigned_team",
            "tags_detail",
            "tag_ids",
            "issue_type",
            "external_user_id",
            "context_url",
            "context_user_agent",
            "context_os",
            "context_browser",
            "context_screen_resolution",
            "context_metadata",
            "sla_policy",
            "first_response_at",
            "resolved_at",
            "closed_at",
            "messages",
            "videos",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "organization",
            "reference",
            "first_response_at",
            "resolved_at",
            "closed_at",
            "created_at",
            "updated_at",
        ]

    def update(self, instance, validated_data):
        """Save only what the request sent, not what the view read before.

        Saving the whole row could restore what an anonymization just removed.
        """
        tags = validated_data.pop("tags", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save(update_fields=[*validated_data, "updated_at"])
        if tags is not None:
            instance.tags.set(tags)
        return instance


class WidgetSubmitResponseSerializer(serializers.ModelSerializer):
    """What a widget gets back from a submission: what it reads, and nothing else.

    The widget's token is public, and anyone can name an address to find out about the
    contact holding it.
    """

    class Meta:
        model = Ticket
        fields = ["id", "reference"]


class TicketAssignSerializer(serializers.Serializer):
    """Validates the body of the ticket ``assign`` action."""

    agent_id = OrgScopedPrimaryKeyRelatedField(
        queryset=ASSIGNABLE_AGENTS, required=False, allow_null=True
    )
    team_id = OrgScopedPrimaryKeyRelatedField(
        queryset=Team.objects.all(), required=False, allow_null=True
    )


class TicketSetTagsSerializer(serializers.Serializer):
    """Validates the body of the ticket ``set_tags`` action."""

    tag_ids = OrgScopedPrimaryKeyRelatedField(
        many=True, queryset=Tag.objects.all(), required=False
    )


class TicketListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for ticket list views."""

    requester_detail = UserSerializer(source="requester", read_only=True)
    assigned_agent_detail = UserSerializer(source="assigned_agent", read_only=True)
    tags_detail = TagSerializer(source="tags", many=True, read_only=True)
    message_count = serializers.IntegerField(read_only=True)
    contact_detail = ContactSummarySerializer(source="contact", read_only=True)
    sender_verified = serializers.BooleanField(read_only=True, allow_null=True)

    class Meta:
        model = Ticket
        fields = [
            "id",
            "reference",
            "title",
            "description",
            "status",
            "priority",
            "source",
            "issue_type",
            "requester_detail",
            "requester_name",
            "requester_email",
            "contact",
            "contact_detail",
            "sender_verified",
            "assigned_agent_detail",
            "assigned_team",
            "tags_detail",
            "message_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


def ticket_list_rows(tickets):
    """Return the rows ``TicketListSerializer`` shows, without an N+1.

    Distinct: filtering on several tags joins them, one row per tag matched. Ordered
    here, as Django drops ``Meta.ordering`` from a query with a GROUP BY.
    """
    return (
        tickets.select_related(
            "requester", "assigned_agent", "contact__company", "widget_session"
        )
        .prefetch_related("tags")
        .annotate(message_count=Count("messages", distinct=True))
        .order_by("-created_at", "-id")
    )


class TicketCreateFromWidgetSerializer(serializers.ModelSerializer):
    """Serializer for creating tickets from the widget.

    This serializer handles unauthenticated submissions where the
    requester provides their name and email instead of being logged in.
    The organization is determined by the widget API token.
    """

    class Meta:
        model = Ticket
        fields = [
            "title",
            "description",
            "requester_name",
            "requester_email",
            "priority",
            "issue_type",
            "external_user_id",
            "context_url",
            "context_user_agent",
            "context_os",
            "context_browser",
            "context_screen_resolution",
            "context_metadata",
        ]


class WidgetTicketListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing tickets in the widget."""

    last_agent_reply = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = [
            "id",
            "reference",
            "title",
            "status",
            "created_at",
            "updated_at",
            "last_agent_reply",
        ]

    def get_last_agent_reply(self, obj: Ticket) -> str | None:
        last_reply = (
            obj.messages.filter(
                message_type="reply",
                author__role__in=["admin", "agent"],
            )
            .order_by("-created_at")
            .values_list("body", flat=True)
            .first()
        )
        return last_reply


class SavedViewSerializer(serializers.ModelSerializer):
    """Serializer for saved ticket filter views."""

    created_by_detail = UserSerializer(source="created_by", read_only=True)

    class Meta:
        model = SavedView
        fields = [
            "id",
            "organization",
            "created_by",
            "created_by_detail",
            "name",
            "filters",
            "is_shared",
            "position",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "organization",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def validate_name(self, value):
        """Ensure the name is unique within the organization."""
        request = self.context.get("request")
        org = get_active_org(request) if request else None
        if not org:
            return value
        qs = SavedView.objects.filter(organization=org, name=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A view with this name already exists.")
        return value


class CannedResponseSerializer(serializers.ModelSerializer):
    """Serializer for reusable reply templates."""

    created_by_detail = UserSerializer(source="created_by", read_only=True)

    class Meta:
        model = CannedResponse
        fields = [
            "id",
            "organization",
            "created_by",
            "created_by_detail",
            "name",
            "shortcut",
            "body",
            "is_shared",
            "position",
            "usage_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "organization",
            "created_by",
            "usage_count",
            "created_at",
            "updated_at",
        ]

    def validate_name(self, value):
        request = self.context.get("request")
        if not request:
            return value
        org = get_active_org(request)
        if not org:
            return value
        qs = CannedResponse.objects.filter(organization=org, name=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "A canned response with this name already exists.",
            )
        return value


# ---------------------------------------------------------------------------
# Widget messaging serializers
# ---------------------------------------------------------------------------


class StrictCharField(serializers.CharField):
    """A CharField that refuses non-strings instead of coercing numbers."""

    def run_validation(self, data=empty):
        # Before the parent's str(data), a RecursionError on a deeply nested list.
        if data is not empty and data is not None and not isinstance(data, str):
            self.fail("invalid")
        return super().run_validation(data)


class WidgetHashField(serializers.Field):
    """A hash signed by the host app. An invalid one is ignored, never a 400.

    A hash of a shape no signature has reads as ``bad_shape``.
    """

    def __init__(self, *, bad_shape: str = "", **kwargs):
        self.bad_shape = bad_shape
        super().__init__(required=False, allow_null=True, **kwargs)

    def to_internal_value(self, data):
        if isinstance(data, str) and len(data) <= 128 and data.isascii():
            return data
        return self.bad_shape


class WidgetNameField(serializers.Field):
    """A display name. Whatever can't be one is ignored, so it reads as absent."""

    def __init__(self, **kwargs):
        super().__init__(required=False, allow_null=True, **kwargs)

    def to_internal_value(self, data):
        # A boolean isn't one: it would stick, a resume only fills a blank name.
        if isinstance(data, (int, float)) and not isinstance(data, bool):
            data = str(data)
        if not isinstance(data, str) or not is_storable(data):
            return None
        return data.strip()[: WidgetSession._meta.get_field("name").max_length]


class WidgetEmailField(serializers.Field):
    """An email, only checked as text. A cut one would be somebody else's address."""

    def __init__(self, **kwargs):
        super().__init__(required=False, allow_null=True, **kwargs)

    def to_internal_value(self, data):
        if not isinstance(data, str) or not is_storable(data):
            return None
        email = data.strip()
        if len(email) > WidgetSession._meta.get_field("email").max_length:
            return None
        return email


class WidgetObjectField(serializers.Field):
    """A JSON object, for the service to look into. Anything else reads as absent."""

    def __init__(self, **kwargs):
        super().__init__(required=False, allow_null=True, **kwargs)

    def to_internal_value(self, data):
        return data if isinstance(data, dict) else None


class WidgetExternalIdField(StrictCharField):
    """A user id, as a string. A plain JavaScript host may pass an integer."""

    def __init__(self, **kwargs):
        super().__init__(
            required=False,
            allow_null=True,
            allow_blank=True,
            max_length=255,
            trim_whitespace=False,  # The HMAC covers its exact value.
            **kwargs,
        )

    def run_validation(self, data=empty):
        if type(data) is int and abs(data) < 2**63:
            data = str(data)
        return super().run_validation(data)


# A value no signature can equal: a digest is hexadecimal. A ``user_hash`` of a
# bad shape must stay a wrong hash, not read as an id sent without one.
BAD_SHAPE_USER_HASH = "invalid"


class WidgetIdentitySerializer(serializers.Serializer):
    """Read the identity fields of a widget session payload.

    Null means absent. Only ``external_user_id`` is ever refused: everything else
    is display data or a signature, and a host page that gets it wrong must not
    stop the widget. ``email`` is only checked as text, since the widget's contact
    form lets anything with an "@" through. Stored as is, it shows agents what was
    typed, and the identity service ignores what isn't valid.
    """

    name = WidgetNameField()
    email = WidgetEmailField()
    external_user_id = WidgetExternalIdField()
    user_hash = WidgetHashField(bad_shape=BAD_SHAPE_USER_HASH)
    email_hash = WidgetHashField()
    company_hash = WidgetHashField()
    traits = WidgetObjectField()
    company = WidgetObjectField()

    def validate_external_user_id(self, value: str | None) -> str | None:
        if value and value.startswith(RESERVED_EXTERNAL_ID_PREFIXES):
            raise serializers.ValidationError("This prefix is reserved.")
        return value


class WidgetSessionSerializer(serializers.ModelSerializer):
    """Serializer for widget session creation and display."""

    session_id = serializers.UUIDField(source="id", read_only=True)

    class Meta:
        model = WidgetSession
        fields = [
            "session_id",
            "name",
            "email",
            "external_user_id",
        ]
        read_only_fields = ["session_id"]


class WidgetMessageCreateSerializer(serializers.Serializer):
    """Validates incoming widget chat messages."""

    ticket_id = serializers.UUIDField(required=False, allow_null=True)
    body = serializers.CharField(required=False, allow_blank=True, max_length=10000)
    body_type = serializers.ChoiceField(
        choices=TicketMessage.BodyType.choices,
        default=TicketMessage.BodyType.TEXT,
    )
    context = serializers.JSONField(required=False, default=dict)

    def validate(self, attrs):
        body = attrs.get("body", "")
        body_type = attrs.get("body_type", "text")
        if body_type == "text" and not body.strip():
            raise serializers.ValidationError(
                {"body": "Text messages must have a body."}
            )
        return attrs


class WidgetMessageSerializer(serializers.ModelSerializer):
    """Serializer for displaying messages in widget conversations."""

    attachments = TicketAttachmentSerializer(many=True, read_only=True)
    sender_name = serializers.CharField(read_only=True)

    class Meta:
        model = TicketMessage
        fields = [
            "id",
            "ticket",
            "body",
            "body_type",
            "sender_type",
            "sender_name",
            "attachments",
            "created_at",
        ]
        read_only_fields = fields


class WidgetConversationListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing conversations in the widget history tab."""

    last_message_preview = serializers.SerializerMethodField()
    last_message_at = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = [
            "id",
            "reference",
            "title",
            "status",
            "last_message_preview",
            "last_message_at",
            "unread_count",
            "created_at",
        ]

    def get_last_message_preview(self, obj: Ticket) -> str:
        last_msg = (
            obj.messages.filter(message_type="reply")
            .order_by("-created_at")
            .values_list("body", flat=True)
            .first()
        )
        if not last_msg:
            return ""
        return last_msg[:120]

    def get_last_message_at(self, obj: Ticket) -> str | None:
        last_msg = (
            obj.messages.filter(message_type="reply")
            .order_by("-created_at")
            .values_list("created_at", flat=True)
            .first()
        )
        return last_msg.isoformat() if last_msg else None

    def get_unread_count(self, obj: Ticket) -> int:
        """Count agent replies the end-user hasn't seen yet.

        Prefers the explicit `widget_last_read_at` marker (set when the user
        opens the conversation in the widget). Falls back to "replies after
        the last user message" so history stays sensible for tickets that
        pre-date the marker.
        """
        if obj.widget_last_read_at:
            return obj.messages.filter(
                sender_type="agent",
                created_at__gt=obj.widget_last_read_at,
            ).count()
        last_user_msg = (
            obj.messages.filter(sender_type="user")
            .order_by("-created_at")
            .values_list("created_at", flat=True)
            .first()
        )
        if not last_user_msg:
            return obj.messages.filter(sender_type="agent").count()
        return obj.messages.filter(
            sender_type="agent",
            created_at__gt=last_user_msg,
        ).count()
