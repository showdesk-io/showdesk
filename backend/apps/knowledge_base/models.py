"""Knowledge base models: Category and Article."""

from django.conf import settings
from django.db import models

from apps.core.models import TimestampedModel


class Category(TimestampedModel):
    """A category for organizing knowledge base articles."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="kb_categories",
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    description = models.TextField(blank=True)
    icon = models.CharField(
        max_length=50,
        blank=True,
        help_text="Icon identifier for the category.",
    )
    sort_order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ["sort_order", "name"]
        unique_together = ["organization", "slug"]

    def __str__(self) -> str:
        return self.name


class Article(TimestampedModel):
    """A knowledge base article.

    Articles can be used for self-service support, reducing ticket
    volume through smart deflection.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="kb_articles",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="articles",
    )
    title = models.CharField(max_length=500)
    slug = models.SlugField(max_length=500)
    body = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="kb_articles",
    )
    view_count = models.PositiveIntegerField(default=0)
    helpful_count = models.PositiveIntegerField(default=0)
    not_helpful_count = models.PositiveIntegerField(default=0)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        unique_together = ["organization", "slug"]
        indexes = [
            models.Index(fields=["organization", "status"]),
        ]

    def __str__(self) -> str:
        return self.title
