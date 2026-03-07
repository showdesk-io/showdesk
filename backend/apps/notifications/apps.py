"""Notifications app configuration."""

from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    """Configuration for the notifications application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.notifications"
    verbose_name = "Notifications"
