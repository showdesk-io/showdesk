"""Views for knowledge base models."""

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import Article, Category
from .serializers import ArticleSerializer, CategorySerializer


class CategoryViewSet(viewsets.ModelViewSet):
    """ViewSet for managing knowledge base categories."""

    serializer_class = CategorySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):  # noqa: ANN201
        """Filter categories by user's organization."""
        user = self.request.user
        if user.is_superuser:
            return Category.objects.all()
        if user.organization:
            return Category.objects.filter(organization=user.organization)
        return Category.objects.none()


class ArticleViewSet(viewsets.ModelViewSet):
    """ViewSet for managing knowledge base articles."""

    serializer_class = ArticleSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["category", "status"]
    search_fields = ["title", "body"]

    def get_queryset(self):  # noqa: ANN201
        """Filter articles by user's organization."""
        user = self.request.user
        if user.is_superuser:
            return Article.objects.all()
        if user.organization:
            return Article.objects.filter(organization=user.organization)
        return Article.objects.none()

    @action(detail=True, methods=["post"], permission_classes=[AllowAny])
    def helpful(self, request, pk=None):  # noqa: ANN001, ANN201
        """Mark an article as helpful."""
        article = self.get_object()
        article.helpful_count += 1
        article.save(update_fields=["helpful_count"])
        return Response({"helpful_count": article.helpful_count})

    @action(detail=True, methods=["post"], permission_classes=[AllowAny])
    def not_helpful(self, request, pk=None):  # noqa: ANN001, ANN201
        """Mark an article as not helpful."""
        article = self.get_object()
        article.not_helpful_count += 1
        article.save(update_fields=["not_helpful_count"])
        return Response({"not_helpful_count": article.not_helpful_count})
