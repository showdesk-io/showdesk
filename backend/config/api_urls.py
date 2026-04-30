"""API v1 URL configuration."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from apps.organizations.auth_views import RequestOTPView, VerifyOTPView
from apps.organizations.signup_views import (
    CheckDomainView,
    CheckSlugView,
    SignupView,
)
from apps.organizations.views import (
    JoinRequestViewSet,
    OrganizationViewSet,
    PlatformOrganizationViewSet,
    TeamViewSet,
    UserViewSet,
)
from apps.tickets.views import (
    CannedResponseViewSet,
    PriorityLevelViewSet,
    SavedViewViewSet,
    TagViewSet,
    TicketAttachmentViewSet,
    TicketMessageViewSet,
    TicketViewSet,
)
from apps.tickets.widget_views import InternalWidgetIdentityView
from apps.videos.views import VideoRecordingViewSet
from apps.knowledge_base.views import ArticleViewSet, CategoryViewSet
from apps.core.views import HealthCheckView
from apps.core.setup_views import SetupStatusView, SetupInitializeView

router = DefaultRouter()

# Organizations
router.register(r"organizations", OrganizationViewSet, basename="organization")
router.register(r"teams", TeamViewSet, basename="team")
router.register(r"users", UserViewSet, basename="user")
router.register(r"join-requests", JoinRequestViewSet, basename="join-request")

# Tickets
router.register(r"tickets", TicketViewSet, basename="ticket")
router.register(r"messages", TicketMessageViewSet, basename="message")
router.register(r"attachments", TicketAttachmentViewSet, basename="attachment")
router.register(r"tags", TagViewSet, basename="tag")
router.register(r"priorities", PriorityLevelViewSet, basename="priority")
router.register(r"saved-views", SavedViewViewSet, basename="saved-view")
router.register(
    r"canned-responses",
    CannedResponseViewSet,
    basename="canned-response",
)

# Videos
router.register(r"videos", VideoRecordingViewSet, basename="video")

# Knowledge Base
router.register(r"kb/categories", CategoryViewSet, basename="kb-category")
router.register(r"kb/articles", ArticleViewSet, basename="kb-article")

# Platform Admin
router.register(
    r"platform/organizations",
    PlatformOrganizationViewSet,
    basename="platform-organization",
)

urlpatterns = [
    path("", include(router.urls)),
    # OTP authentication (passwordless)
    path("auth/request-otp/", RequestOTPView.as_view(), name="request-otp"),
    path("auth/verify-otp/", VerifyOTPView.as_view(), name="verify-otp"),
    # Self-service signup (public)
    path("auth/signup/", SignupView.as_view(), name="signup"),
    path("auth/check-slug/", CheckSlugView.as_view(), name="check-slug"),
    path("auth/check-domain/", CheckDomainView.as_view(), name="check-domain"),
    # JWT refresh (still needed for token rotation)
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("health/", HealthCheckView.as_view(), name="health-check"),
    # In-app widget bootstrap (dogfooding): returns the internal org token
    # and an HMAC hash for the authenticated user.
    path(
        "widget/identity-hash/",
        InternalWidgetIdentityView.as_view(),
        name="widget-identity-hash",
    ),
    # Instance setup (first-time initialization)
    path("setup/status/", SetupStatusView.as_view(), name="setup-status"),
    path("setup/initialize/", SetupInitializeView.as_view(), name="setup-initialize"),
]
