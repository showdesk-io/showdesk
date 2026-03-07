"""Serializers for organization-related models."""

from rest_framework import serializers

from .models import Organization, Team, User


class OrganizationSerializer(serializers.ModelSerializer):
    """Serializer for the Organization model."""

    class Meta:
        model = Organization
        fields = [
            "id",
            "name",
            "slug",
            "domain",
            "logo",
            "is_active",
            "widget_color",
            "widget_position",
            "widget_greeting",
            "video_expiration_days",
            "video_max_duration_seconds",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


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
        extra_kwargs = {
            "password": {"write_only": True, "required": False},
        }


class UserCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating new users."""

    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "password",
            "first_name",
            "last_name",
            "organization",
            "role",
        ]
        read_only_fields = ["id"]

    def create(self, validated_data: dict) -> User:
        """Create a user with a hashed password."""
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


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
