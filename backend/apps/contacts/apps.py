"""Contacts app configuration."""

from django.apps import AppConfig


class ContactsConfig(AppConfig):
    """Configuration for the contacts application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.contacts"
    verbose_name = "Contacts"
