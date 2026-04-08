"""Root URL configuration for Showdesk."""

from django.contrib import admin
from django.urls import include, path

from apps.core.admin_auth import admin_otp_login

admin.site.login = admin_otp_login

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("config.api_urls")),
]
