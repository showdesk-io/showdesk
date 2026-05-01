"""Serializers for organization-related models."""

import re

from rest_framework import serializers

from .models import (
    Organization,
    OrganizationDomain,
    OrgJoinRequest,
    Team,
    User,
)


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
            "widget_secret",
            "is_active",
            "widget_color",
            "widget_position",
            "widget_greeting",
            "video_expiration_days",
            "video_max_duration_seconds",
            "agent_count",
            "email_domain",
            "onboarding_completed_at",
            "onboarding_step",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "api_token",
            "widget_secret",
            "email_domain",
            "created_at",
            "updated_at",
        ]

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
            "is_superuser",
            "date_joined",
        ]
        read_only_fields = ["id", "is_superuser", "date_joined"]


class InviteAgentSerializer(serializers.Serializer):
    """Serializer for inviting a new agent via email.

    Note: email-already-exists is *not* validated here. The view returns
    HTTP 409 with a structured error in that case (see UserViewSet.invite),
    matching the signup endpoint's contract.
    """

    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150, required=False, default="")
    last_name = serializers.CharField(max_length=150, required=False, default="")
    role = serializers.ChoiceField(
        choices=[("admin", "Admin"), ("agent", "Agent")],
        default="agent",
    )

    def validate_email(self, value: str) -> str:
        return value.lower().strip()


class PlatformOrganizationListSerializer(serializers.ModelSerializer):
    """Serializer for listing organizations in the platform admin console."""

    agent_count = serializers.SerializerMethodField()
    ticket_count = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = [
            "id",
            "name",
            "slug",
            "domain",
            "is_active",
            "agent_count",
            "ticket_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_agent_count(self, obj: Organization) -> int:
        return obj.users.filter(role__in=["admin", "agent"], is_active=True).count()

    def get_ticket_count(self, obj: Organization) -> int:
        return obj.tickets.count()


class PlatformOrganizationDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for a single organization in the platform admin."""

    agent_count = serializers.SerializerMethodField()
    ticket_count = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = [
            "id",
            "name",
            "slug",
            "domain",
            "logo",
            "api_token",
            "widget_secret",
            "is_active",
            "widget_color",
            "widget_position",
            "widget_greeting",
            "video_expiration_days",
            "video_max_duration_seconds",
            "agent_count",
            "ticket_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "api_token",
            "widget_secret",
            "created_at",
            "updated_at",
        ]

    def get_agent_count(self, obj: Organization) -> int:
        return obj.users.filter(role__in=["admin", "agent"], is_active=True).count()

    def get_ticket_count(self, obj: Organization) -> int:
        return obj.tickets.count()


class PlatformOrganizationCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating an organization via platform admin."""

    class Meta:
        model = Organization
        fields = [
            "name",
            "slug",
            "domain",
        ]


_DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,253}[a-z0-9])?\.[a-z]{2,}$")


class OrganizationDomainSerializer(serializers.ModelSerializer):
    """Serializer for OrganizationDomain (org-scoped, admin-only writes).

    `domain` is write-once: settable on create but immutable afterwards.
    Status, verification_method, token, and verified_at are entirely
    server-managed (set by the verify endpoint, not the client).
    """

    txt_record_name = serializers.CharField(read_only=True)
    txt_record_value = serializers.CharField(read_only=True)

    class Meta:
        model = OrganizationDomain
        fields = [
            "id",
            "domain",
            "is_branding",
            "is_email_routing",
            "status",
            "verification_method",
            "verification_token",
            "verified_at",
            "last_check_at",
            "txt_record_name",
            "txt_record_value",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "verification_method",
            "verification_token",
            "verified_at",
            "last_check_at",
            "txt_record_name",
            "txt_record_value",
            "created_at",
            "updated_at",
        ]

    def validate_domain(self, value: str) -> str:
        normalized = (value or "").strip().lower()
        if self.instance is not None and normalized != self.instance.domain:
            raise serializers.ValidationError(
                "domain is immutable; create a new entry instead."
            )
        if not _DOMAIN_RE.match(normalized):
            raise serializers.ValidationError(
                "Enter a valid domain (e.g. acme.com)."
            )
        return normalized

    def validate(self, attrs: dict) -> dict:
        is_branding = attrs.get(
            "is_branding",
            getattr(self.instance, "is_branding", False),
        )
        is_email_routing = attrs.get(
            "is_email_routing",
            getattr(self.instance, "is_email_routing", False),
        )
        if not (is_branding or is_email_routing):
            raise serializers.ValidationError(
                {"is_branding": "Choose at least one purpose."}
            )
        return attrs


class OrgJoinRequestSerializer(serializers.ModelSerializer):
    """Serializer for OrgJoinRequest (admin-side approval UI)."""

    decided_by_email = serializers.SerializerMethodField()

    class Meta:
        model = OrgJoinRequest
        fields = [
            "id",
            "email",
            "full_name",
            "status",
            "created_at",
            "decided_at",
            "decided_by",
            "decided_by_email",
        ]
        read_only_fields = fields

    def get_decided_by_email(self, obj: OrgJoinRequest) -> str | None:
        return obj.decided_by.email if obj.decided_by else None


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
