"""Organizations admin configuration."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Organization, Team, User


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    """Admin for organizations."""

    list_display = ["name", "slug", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["name", "slug", "domain"]
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ["id", "api_token", "created_at", "updated_at"]


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin for custom user model."""

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
        (None, {"fields": ("email", "password")}),
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
                "fields": ("email", "password1", "password2", "role", "organization"),
            },
        ),
    )


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    """Admin for teams."""

    list_display = ["name", "organization", "lead"]
    list_filter = ["organization"]
    search_fields = ["name"]
    filter_horizontal = ["members"]
