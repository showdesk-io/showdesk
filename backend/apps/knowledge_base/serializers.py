"""Serializers for knowledge base models."""

from rest_framework import serializers

from apps.core.serializers import (
    OrgScopedPrimaryKeyRelatedField,
    read_only_organization_field,
)

from .models import Article, Category


class CategorySerializer(serializers.ModelSerializer):
    """Serializer for the Category model."""

    organization = read_only_organization_field()
    article_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = [
            "id",
            "organization",
            "name",
            "slug",
            "description",
            "icon",
            "sort_order",
            "is_published",
            "article_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_article_count(self, obj: Category) -> int:
        """Return the number of published articles in this category."""
        return obj.articles.filter(status=Article.Status.PUBLISHED).count()


class ArticleSerializer(serializers.ModelSerializer):
    """Serializer for the Article model."""

    organization = read_only_organization_field()
    category = OrgScopedPrimaryKeyRelatedField(
        queryset=Category.objects.all(), required=False, allow_null=True
    )
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = Article
        fields = [
            "id",
            "organization",
            "category",
            "category_name",
            "title",
            "slug",
            "body",
            "status",
            "author",
            "view_count",
            "helpful_count",
            "not_helpful_count",
            "published_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "author",
            "view_count",
            "helpful_count",
            "not_helpful_count",
            "created_at",
            "updated_at",
        ]
