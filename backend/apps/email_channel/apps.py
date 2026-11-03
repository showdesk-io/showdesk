"""Email channel app configuration."""

from django.apps import AppConfig


class EmailChannelConfig(AppConfig):
    """Configuration for the email channel: mailboxes and inbound mail."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.email_channel"
    verbose_name = "Email channel"
