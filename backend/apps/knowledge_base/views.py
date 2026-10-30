"""Views for knowledge base models."""

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import IsOrgStaff, get_active_org, require_active_org

from .models import Article, Category
from .serializers import ArticleSerializer, CategorySerializer


class CategoryViewSet(viewsets.ModelViewSet):
    """ViewSet for managing knowledge base categories."""

    serializer_class = CategorySerializer
    permission_classes = [IsAuthenticated, IsOrgStaff]

    def get_queryset(self):
        """Filter categories by the active organization."""
        org = get_active_org(self.request)
        if org:
            return Category.objects.filter(organization=org)
        return Category.objects.none()

    def perform_create(self, serializer) -> None:
        """Set organization from the active org."""
        serializer.save(organization=require_active_org(self.request))


class ArticleViewSet(viewsets.ModelViewSet):
    """ViewSet for managing knowledge base articles."""

    serializer_class = ArticleSerializer
    permission_classes = [IsAuthenticated, IsOrgStaff]
    filterset_fields = ["category", "status"]
    search_fields = ["title", "body"]

    def get_queryset(self):
        """Filter articles by the active organization."""
        org = get_active_org(self.request)
        if org:
            return Article.objects.filter(organization=org)
        return Article.objects.none()

    def perform_create(self, serializer) -> None:
        """Set organization and author."""
        serializer.save(
            organization=require_active_org(self.request),
            author=self.request.user,
        )

    @action(detail=True, methods=["post"], permission_classes=[AllowAny])
    def helpful(self, request, pk=None):
        """Mark an article as helpful."""
        article = self.get_object()
        article.helpful_count += 1
        article.save(update_fields=["helpful_count"])
        return Response({"helpful_count": article.helpful_count})

    @action(detail=True, methods=["post"], permission_classes=[AllowAny])
    def not_helpful(self, request, pk=None):
        """Mark an article as not helpful."""
        article = self.get_object()
        article.not_helpful_count += 1
        article.save(update_fields=["not_helpful_count"])
        return Response({"not_helpful_count": article.not_helpful_count})
