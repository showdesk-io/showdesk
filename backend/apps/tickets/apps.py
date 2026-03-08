"""Tickets app configuration."""

from django.apps import AppConfig


class TicketsConfig(AppConfig):
    """Configuration for the tickets application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tickets"
    verbose_name = "Tickets"

    def ready(self) -> None:
        """Register signal handlers."""
        from django.db.models.signals import post_save

        from apps.organizations.models import Organization

        from .models import PriorityLevel

        post_save.connect(
            _seed_priorities_on_org_create,
            sender=Organization,
            dispatch_uid="seed_default_priorities",
        )


def _seed_priorities_on_org_create(sender, instance, created, **kwargs) -> None:  # noqa: ANN001
    """Seed default priority levels when a new organization is created."""
    if created:
        from .models import PriorityLevel

        PriorityLevel.create_defaults(instance)
