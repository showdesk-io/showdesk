"""Email channel app configuration."""

from django.apps import AppConfig


class EmailChannelConfig(AppConfig):
    """Configuration for the email channel: mailboxes and inbound mail."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.email_channel"
    verbose_name = "Email channel"

    def ready(self) -> None:
        from anymail.signals import inbound

        from apps.email_channel.signals import store_inbound_event

        inbound.connect(store_inbound_event, dispatch_uid="email_channel_store")
