"""Contacts admin configuration."""

from django.contrib import admin

from .models import (
    Company,
    CompanyAttributeDef,
    Contact,
    ContactAttributeDef,
    ContactNote,
)


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    """Admin for contacts."""

    list_display = ["name", "email", "organization", "last_seen_at"]
    search_fields = ["email", "name", "external_id"]
    autocomplete_fields = ["company"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    """Admin for companies."""

    list_display = ["name", "domain", "organization"]
    search_fields = ["name", "domain", "external_id"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(ContactAttributeDef, CompanyAttributeDef)
class CustomAttributeDefAdmin(admin.ModelAdmin):
    """Admin for contact and company attribute definitions."""

    list_display = ["label", "key", "type", "organization", "position", "is_archived"]
    list_filter = ["type", "is_archived"]
    search_fields = ["key", "label"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(ContactNote)
class ContactNoteAdmin(admin.ModelAdmin):
    """Admin for contact notes."""

    list_display = ["contact", "author", "created_at"]
    search_fields = ["body", "contact__email", "contact__name"]
    autocomplete_fields = ["contact", "author"]
    readonly_fields = ["id", "created_at", "updated_at"]
