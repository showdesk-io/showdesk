"""Organizations admin configuration."""

from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Organization, OrganizationDomain, Team, User


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    """Admin for organizations."""

    list_display = ["name", "slug", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["name", "slug", "domain"]
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ["id", "api_token", "created_at", "updated_at"]


class UserCreationForm(forms.ModelForm):
    """User creation form without password fields. Users authenticate via OTP."""

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name", "role", "organization")

    def save(self, commit=True):  # noqa: ANN001, ANN201, FBT002
        user = super().save(commit=False)
        user.set_unusable_password()
        if commit:
            user.save()
        return user


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin for custom user model."""

    add_form = UserCreationForm

    list_display = [
        "email",
        "first_name",
        "last_name",
        "role",
        "organization",
        "is_active",
    ]
    list_filter = ["role", "is_active", "organization"]
    search_fields = ["email", "first_name", "last_name"]
    ordering = ["email"]
    fieldsets = (
        (None, {"fields": ("email",)}),
        ("Personal info", {"fields": ("first_name", "last_name", "avatar", "phone")}),
        (
            "Organization",
            {"fields": ("organization", "role", "timezone", "is_available")},
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "first_name", "last_name", "role", "organization"),
            },
        ),
    )


@admin.register(OrganizationDomain)
class OrganizationDomainAdmin(admin.ModelAdmin):
    """Admin for verified/pending organization domains."""

    list_display = [
        "domain",
        "organization",
        "is_branding",
        "is_email_routing",
        "status",
        "verification_method",
        "verified_at",
    ]
    list_filter = ["status", "verification_method", "is_branding", "is_email_routing"]
    search_fields = ["domain", "organization__slug", "organization__name"]
    readonly_fields = [
        "id",
        "verification_token",
        "verified_at",
        "last_check_at",
        "created_at",
        "updated_at",
    ]


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    """Admin for teams."""

    list_display = ["name", "organization", "lead"]
    list_filter = ["organization"]
    search_fields = ["name"]
    filter_horizontal = ["members"]
