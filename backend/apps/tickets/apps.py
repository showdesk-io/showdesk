"""Tickets app configuration."""

from django.apps import AppConfig


class TicketsConfig(AppConfig):
    """Configuration for the tickets application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tickets"
    verbose_name = "Tickets"
