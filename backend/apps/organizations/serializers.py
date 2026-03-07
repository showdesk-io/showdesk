"""Serializers for organization-related models."""

from rest_framework import serializers

from .models import Organization, Team, User


class OrganizationSerializer(serializers.ModelSerializer):
    """Serializer for the Organization model."""

    agent_count = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = [
            "id",
            "name",
            "slug",
            "domain",
            "logo",
            "api_token",
            "is_active",
            "widget_color",
            "widget_position",
            "widget_greeting",
            "video_expiration_days",
            "video_max_duration_seconds",
            "agent_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "api_token", "created_at", "updated_at"]

    def get_agent_count(self, obj: Organization) -> int:
        return obj.users.filter(role__in=["admin", "agent"], is_active=True).count()


class OrganizationPublicSerializer(serializers.ModelSerializer):
    """Public serializer for widget configuration (no sensitive data)."""

    class Meta:
        model = Organization
        fields = [
            "id",
            "name",
            "logo",
            "widget_color",
            "widget_position",
            "widget_greeting",
            "video_max_duration_seconds",
        ]


class UserSerializer(serializers.ModelSerializer):
    """Serializer for the User model."""

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "organization",
            "role",
            "avatar",
            "phone",
            "timezone",
            "is_available",
            "is_active",
            "date_joined",
        ]
        read_only_fields = ["id", "date_joined"]


class InviteAgentSerializer(serializers.Serializer):
    """Serializer for inviting a new agent via email."""

    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150, required=False, default="")
    last_name = serializers.CharField(max_length=150, required=False, default="")
    role = serializers.ChoiceField(
        choices=[("admin", "Admin"), ("agent", "Agent")],
        default="agent",
    )

    def validate_email(self, value: str) -> str:
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value


class TeamSerializer(serializers.ModelSerializer):
    """Serializer for the Team model."""

    members = UserSerializer(many=True, read_only=True)
    member_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=User.objects.all(),
        source="members",
        write_only=True,
        required=False,
    )

    class Meta:
        model = Team
        fields = [
            "id",
            "organization",
            "name",
            "description",
            "members",
            "member_ids",
            "lead",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
