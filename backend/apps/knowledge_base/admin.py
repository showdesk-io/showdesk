"""Knowledge base admin configuration."""

from django.contrib import admin

from .models import Article, Category


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """Admin for knowledge base categories."""

    list_display = ["name", "organization", "sort_order", "is_published"]
    list_filter = ["organization", "is_published"]
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    """Admin for knowledge base articles."""

    list_display = [
        "title",
        "category",
        "status",
        "author",
        "view_count",
        "published_at",
    ]
    list_filter = ["status", "category", "organization"]
    search_fields = ["title", "body"]
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ["view_count", "helpful_count", "not_helpful_count"]
