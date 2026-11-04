"""Email channel app configuration."""

from django.apps import AppConfig


class EmailChannelConfig(AppConfig):
    """Configuration for the email channel: mailboxes and inbound mail."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.email_channel"
    verbose_name = "Email channel"

    def ready(self) -> None:
        from anymail.signals import inbound
        from django.db.models.signals import post_delete, pre_delete

        from apps.email_channel.models import InboundEmail
        from apps.email_channel.signals import (
            delete_raw_mail,
            record_sending_removal,
            store_inbound_event,
        )
        from apps.organizations.models import OrganizationDomain

        inbound.connect(store_inbound_event, dispatch_uid="email_channel_store")
        post_delete.connect(
            delete_raw_mail, sender=InboundEmail, dispatch_uid="email_channel_raw"
        )
        pre_delete.connect(
            record_sending_removal,
            sender=OrganizationDomain,
            dispatch_uid="email_channel_sending_removal",
        )
