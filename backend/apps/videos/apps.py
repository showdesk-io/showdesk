"""Videos app configuration."""

from django.apps import AppConfig


class VideosConfig(AppConfig):
    """Configuration for the videos application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.videos"
    verbose_name = "Videos"
