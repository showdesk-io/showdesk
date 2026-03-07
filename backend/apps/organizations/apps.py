"""Organizations app configuration."""

from django.apps import AppConfig


class OrganizationsConfig(AppConfig):
    """Configuration for the organizations application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.organizations"
    verbose_name = "Organizations"
