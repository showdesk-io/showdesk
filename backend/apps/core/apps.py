"""Core app configuration."""

from corsheaders.signals import check_request_enabled
from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Configuration for the core application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    verbose_name = "Core"

    def ready(self) -> None:
        """Connect the signal opening the widget's routes to any origin."""
        from apps.core.cors import allow_widget_routes

        check_request_enabled.connect(allow_widget_routes)
