"""Serializers for ticket-related models."""

from rest_framework import serializers

from apps.organizations.serializers import UserSerializer

from .models import PriorityLevel, SavedView, SLAPolicy, Tag, Ticket, TicketAttachment, TicketMessage


class PriorityLevelSerializer(serializers.ModelSerializer):
    """Serializer for the PriorityLevel model."""

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
        read_only_fields = ["id", "organization", "created_at", "updated_at"]


class TagSerializer(serializers.ModelSerializer):
    """Serializer for the Tag model."""

    class Meta:
        model = Tag
        fields = ["id", "organization", "name", "color", "created_at"]
        read_only_fields = ["id", "organization", "created_at"]


class SLAPolicySerializer(serializers.ModelSerializer):
    """Serializer for the SLAPolicy model."""

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
        read_only_fields = ["id", "created_at", "updated_at"]


class TicketAttachmentSerializer(serializers.ModelSerializer):
    """Serializer for ticket attachments with file validation."""

    # Max 20 MB per file
    MAX_FILE_SIZE = 20 * 1024 * 1024

    # Blocked extensions (executable, dangerous)
    BLOCKED_EXTENSIONS = {
        ".exe", ".bat", ".cmd", ".com", ".msi", ".scr",
        ".pif", ".vbs", ".vbe", ".js", ".jse", ".wsf",
        ".wsh", ".ps1", ".sh", ".csh", ".dll", ".sys",
    }

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
        read_only_fields = ["id", "created_at"]

    def validate_file(self, value):  # noqa: ANN001, ANN201
        """Validate file size and type."""
        if value.size > self.MAX_FILE_SIZE:
            max_mb = self.MAX_FILE_SIZE // (1024 * 1024)
            raise serializers.ValidationError(
                f"File size exceeds the {max_mb} MB limit."
            )

        import os

        _, ext = os.path.splitext(value.name)
        if ext.lower() in self.BLOCKED_EXTENSIONS:
            raise serializers.ValidationError(
                f"File type '{ext}' is not allowed."
            )

        return value


class TicketMessageSerializer(serializers.ModelSerializer):
    """Serializer for ticket messages."""

    author_detail = UserSerializer(source="author", read_only=True)
    attachments = TicketAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = TicketMessage
        fields = [
            "id",
            "ticket",
            "author",
            "author_detail",
            "body",
            "message_type",
            "attachments",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class TicketSerializer(serializers.ModelSerializer):
    """Serializer for the Ticket model."""

    from apps.videos.serializers import VideoRecordingSerializer

    messages = TicketMessageSerializer(many=True, read_only=True)
    videos = VideoRecordingSerializer(many=True, read_only=True)
    tags_detail = TagSerializer(source="tags", many=True, read_only=True)
    tag_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Tag.objects.all(),
        source="tags",
        write_only=True,
        required=False,
    )
    requester_detail = UserSerializer(source="requester", read_only=True)
    assigned_agent_detail = UserSerializer(source="assigned_agent", read_only=True)

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
            "assigned_agent",
            "assigned_agent_detail",
            "assigned_team",
            "tags_detail",
            "tag_ids",
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
            "reference",
            "first_response_at",
            "resolved_at",
            "closed_at",
            "created_at",
            "updated_at",
        ]


class TicketListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for ticket list views."""

    requester_detail = UserSerializer(source="requester", read_only=True)
    assigned_agent_detail = UserSerializer(source="assigned_agent", read_only=True)
    tags_detail = TagSerializer(source="tags", many=True, read_only=True)
    message_count = serializers.SerializerMethodField()

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
            "requester_detail",
            "requester_name",
            "requester_email",
            "assigned_agent_detail",
            "assigned_team",
            "tags_detail",
            "message_count",
            "created_at",
            "updated_at",
        ]

    def get_message_count(self, obj: Ticket) -> int:
        """Return the number of messages on this ticket."""
        return obj.messages.count()


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
            "context_url",
            "context_user_agent",
            "context_os",
            "context_browser",
            "context_screen_resolution",
            "context_metadata",
        ]


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
        read_only_fields = ["id", "organization", "created_by", "created_at", "updated_at"]

    def validate_name(self, value):  # noqa: ANN001, ANN201
        """Ensure the name is unique within the organization."""
        request = self.context.get("request")
        if not request or not request.user.organization:
            return value
        qs = SavedView.objects.filter(
            organization=request.user.organization,
            name=value,
        )
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A view with this name already exists.")
        return value
