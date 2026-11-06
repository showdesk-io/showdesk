"""Root URL configuration for Showdesk."""

from django.conf import settings
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path

from apps.core.admin_auth import admin_otp_login
from apps.email_channel.webhooks import PostalInboundView, webhook_secrets

admin.site.login = admin_otp_login

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("config.api_urls")),
]

if settings.INBOUND_EMAIL_DOMAIN:
    # Only signed webhooks reach the inbound pipeline: a mail's From proves nothing,
    # and a webhook anyone can call would let anyone write into any mailbox.
    if settings.ANYMAIL.get("POSTAL_WEBHOOK_KEY"):
        urlpatterns.append(
            path(
                "anymail/postal/inbound/",
                PostalInboundView.as_view(),
                name="postal_inbound_webhook",
            )
        )
    # Without a shared secret, Anymail's views for basic-auth providers accept
    # anything. Mounted after Postal's view above, which takes precedence.
    if webhook_secrets(settings.ANYMAIL.get("WEBHOOK_SECRET")):
        urlpatterns.append(path("anymail/", include("anymail.urls")))

# In DEBUG, serve files from STATICFILES_DIRS (e.g. backend/static/brand/logo.png
# referenced from outgoing emails). In production the web server serves
# STATIC_ROOT directly after collectstatic.
if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
