"""Root URL configuration for Showdesk."""

from django.conf import settings
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path

from apps.core.admin_auth import admin_otp_login

admin.site.login = admin_otp_login

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("config.api_urls")),
]

# In DEBUG, serve files from STATICFILES_DIRS (e.g. backend/static/brand/logo.png
# referenced from outgoing emails). In production the web server serves
# STATIC_ROOT directly after collectstatic.
if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
