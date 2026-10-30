"""Contacts admin configuration."""

from django.contrib import admin

from .models import Company, Contact


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    """Admin for contacts."""

    list_display = ["name", "email", "organization", "last_seen_at"]
    search_fields = ["email", "name", "external_id"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    """Admin for companies."""

    list_display = ["name", "domain", "organization"]
    search_fields = ["name", "domain", "external_id"]
    readonly_fields = ["id", "created_at", "updated_at"]
