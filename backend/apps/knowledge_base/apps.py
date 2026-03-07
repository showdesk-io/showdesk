"""Knowledge base app configuration."""

from django.apps import AppConfig


class KnowledgeBaseConfig(AppConfig):
    """Configuration for the knowledge base application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.knowledge_base"
    verbose_name = "Knowledge Base"
