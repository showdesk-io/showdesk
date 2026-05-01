"""Self-service signup endpoints.

Public, unauthenticated endpoints that let a prospect create an organization
and become its first admin without operator intervention.

Flow:
- POST /api/v1/auth/signup/      Create org + admin (path A) OR create
                                 a join request against an existing org with
                                 the same email domain (path B).
- GET  /api/v1/auth/check-slug/  Live slug-availability check for the form.
- GET  /api/v1/auth/check-domain/ Tells the form whether the email domain
                                 maps to an existing org so it can switch
                                 from "Create org" to "Request to join".

Authentication still happens via the existing OTP flow: signup creates the
user with an unusable password and immediately issues an OTP code. The
client should redirect to the OTP verification screen.
"""

from __future__ import annotations

import logging
import re

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils.text import slugify
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.email import send_branded_email
from apps.core.throttling import SignupCheckThrottle

from .models import (
    OrgJoinRequest,
    OTPCode,
    Organization,
    User,
    extract_email_domain,
    is_public_email_domain,
)

logger = logging.getLogger(__name__)

# Slug rules: lowercase ASCII, digits, dashes; 3-50 chars; cannot start/end
# with a dash. Validated client- and server-side.
_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,48}[a-z0-9])?$")
# Cap *successful* signups (org-created or join-requested) per IP per hour.
# Failed validation attempts (slug taken, email duplicate, malformed input)
# are intentionally not counted — they shouldn't penalize a user who is
# iterating on their form.
SIGNUP_SUCCESS_LIMIT = 5
SIGNUP_SUCCESS_WINDOW_SECONDS = 3600


_RESERVED_SLUGS = frozenset(
    {
        "admin",
        "api",
        "app",
        "auth",
        "cdn",
        "dashboard",
        "login",
        "logout",
        "platform",
        "settings",
        "setup",
        "showdesk",
        "showdesk-internal",
        "signup",
        "static",
        "support",
        "widget",
        "www",
    }
)


def _slug_available(slug: str) -> bool:
    return (
        bool(_SLUG_RE.match(slug))
        and slug not in _RESERVED_SLUGS
        and not Organization.objects.filter(slug=slug).exists()
    )


def _suggest_slug(base: str) -> str:
    """Return a slug derived from `base` that is not currently taken."""
    base = slugify(base)[:48] or "team"
    if _slug_available(base):
        return base
    for suffix in range(2, 100):
        candidate = f"{base}-{suffix}"[:50]
        if _slug_available(candidate):
            return candidate
    return ""


class SignupSerializer(serializers.Serializer):
    """Validate signup payload.

    `org_name` and `org_slug` are conditionally required: only when the
    email domain does not match an existing org. The view enforces that.
    """

    email = serializers.EmailField()
    full_name = serializers.CharField(max_length=255)
    org_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    org_slug = serializers.CharField(max_length=50, required=False, allow_blank=True)


class SignupView(APIView):
    """Create a new organization (path A) or a join request (path B)."""

    permission_classes = [AllowAny]
    authentication_classes = []
    # NOTE: not using a DRF throttle class — we count *successful* signups
    # only, so that slug typos and email-already-exists do not lock out
    # someone who is iterating on the form. See _check_success_quota.

    @transaction.atomic
    def post(self, request: Request) -> Response:
        if (over_quota := self._check_success_quota(request)) is not None:
            return over_quota

        serializer = SignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        email = data["email"].lower().strip()
        full_name = data["full_name"].strip()

        # 409 if the email already maps to a User anywhere on the platform.
        # Same rule as agent invitation: one human = one org.
        if User.objects.filter(email__iexact=email).exists():
            return Response(
                {
                    "detail": (
                        "This email is already used on Showdesk. Sign in instead, "
                        "or use a different address."
                    ),
                    "code": "email_taken",
                },
                status=status.HTTP_409_CONFLICT,
            )

        domain = extract_email_domain(email)
        matching_org = None
        if domain and not is_public_email_domain(domain):
            matching_org = (
                Organization.objects.filter(email_domain=domain, is_active=True)
                .order_by("created_at")
                .first()
            )

        if matching_org:
            response = self._create_join_request(matching_org, email, full_name)
        else:
            response = self._create_organization(email, full_name, data, domain)

        if response.status_code in (
            status.HTTP_201_CREATED,
            status.HTTP_202_ACCEPTED,
        ):
            self._record_signup_success(request)
        return response

    @staticmethod
    def _client_ip(request: Request) -> str:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "unknown")

    @classmethod
    def _success_cache_key(cls, request: Request) -> str:
        return f"signup_success:{cls._client_ip(request)}"

    @classmethod
    def _check_success_quota(cls, request: Request) -> Response | None:
        count = cache.get(cls._success_cache_key(request), 0)
        if count >= SIGNUP_SUCCESS_LIMIT:
            return Response(
                {
                    "detail": (
                        "Too many accounts created from this network recently. "
                        "Please try again later."
                    ),
                    "code": "signup_quota_exceeded",
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        return None

    @classmethod
    def _record_signup_success(cls, request: Request) -> None:
        key = cls._success_cache_key(request)
        # Re-read to avoid clobbering concurrent increments. We accept a small
        # race here — worst case the limit is exceeded by 1-2.
        current = cache.get(key, 0)
        cache.set(key, current + 1, SIGNUP_SUCCESS_WINDOW_SECONDS)

    def _create_organization(
        self,
        email: str,
        full_name: str,
        data: dict,
        domain: str,
    ) -> Response:
        org_name = (data.get("org_name") or "").strip()
        org_slug = (data.get("org_slug") or "").strip().lower()

        if not org_name or not org_slug:
            return Response(
                {
                    "detail": (
                        "Organization name and slug are required when no existing "
                        "organization matches your email domain."
                    ),
                    "code": "org_required",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not _slug_available(org_slug):
            return Response(
                {
                    "detail": "This slug is unavailable.",
                    "code": "slug_taken",
                    "suggestion": _suggest_slug(org_slug),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        org = Organization.objects.create(
            name=org_name,
            slug=org_slug,
            email_domain=domain if domain and not is_public_email_domain(domain) else "",
        )
        first_name, _, last_name = full_name.partition(" ")
        user = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            role=User.Role.ADMIN,
            organization=org,
            is_staff=True,
        )
        user.set_unusable_password()
        user.save()

        otp = OTPCode.generate(email)
        self._send_otp_email(email, otp.code)
        self._send_welcome_email(user, org)

        logger.info("Signup: created org %s for %s", org.slug, email)
        return Response(
            {
                "status": "created",
                "email": email,
                "organization": {"id": str(org.id), "slug": org.slug, "name": org.name},
            },
            status=status.HTTP_201_CREATED,
        )

    def _create_join_request(
        self,
        org: Organization,
        email: str,
        full_name: str,
    ) -> Response:
        # Coalesce duplicate pending requests for the same email/org.
        join_request, created = OrgJoinRequest.objects.get_or_create(
            organization=org,
            email=email,
            status=OrgJoinRequest.Status.PENDING,
            defaults={"full_name": full_name},
        )
        if created:
            self._notify_admins_of_join_request(org, join_request)
            logger.info(
                "Signup: created join request for %s -> %s", email, org.slug
            )
        else:
            logger.info(
                "Signup: duplicate pending join request for %s -> %s", email, org.slug
            )

        return Response(
            {
                "status": "join_requested",
                "email": email,
                "organization": {"name": org.name},
            },
            status=status.HTTP_202_ACCEPTED,
        )

    def _send_otp_email(self, email: str, code: str) -> None:
        expiry_minutes = getattr(settings, "OTP_EXPIRY_SECONDS", 600) // 60
        send_branded_email(
            template="otp_code",
            subject=f"Showdesk login code: {code}",
            to=[email],
            context={
                "kicker": "Sign in",
                "heading": "Your Showdesk login code",
                "intro": "Use the code below to finish creating your Showdesk account.",
                "code": code,
                "expiry_minutes": expiry_minutes,
            },
            fail_silently=True,
        )

    def _send_welcome_email(self, user: User, org: Organization) -> None:
        send_branded_email(
            template="signup_welcome",
            subject=f"Welcome to Showdesk, {org.name}",
            to=[user.email],
            organization=org,
            context={
                "first_name": user.first_name,
                "email": user.email,
                "org_name": org.name,
                "dashboard_url": f"{getattr(settings, 'SITE_URL', '')}/",
            },
            fail_silently=True,
        )

    def _notify_admins_of_join_request(
        self, org: Organization, join_request: OrgJoinRequest
    ) -> None:
        admin_emails = list(
            org.users.filter(role=User.Role.ADMIN, is_active=True).values_list(
                "email", flat=True
            )
        )
        if not admin_emails:
            return
        send_branded_email(
            template="join_request_submitted",
            subject=f"{join_request.email} wants to join {org.name}",
            to=admin_emails,
            organization=org,
            context={
                "requester_email": join_request.email,
                "requester_name": join_request.full_name,
                "org_name": org.name,
                "review_url": (
                    f"{getattr(settings, 'SITE_URL', '')}/settings/team"
                ),
            },
            fail_silently=True,
        )


class CheckSlugView(APIView):
    """Live slug-availability check used by the signup form."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [SignupCheckThrottle]

    def get(self, request: Request) -> Response:
        slug = request.query_params.get("slug", "").strip().lower()
        if not slug:
            return Response(
                {"available": False, "reason": "missing_slug"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not _SLUG_RE.match(slug):
            return Response(
                {
                    "available": False,
                    "reason": "invalid_format",
                    "suggestion": _suggest_slug(slug),
                }
            )
        if slug in _RESERVED_SLUGS:
            return Response(
                {
                    "available": False,
                    "reason": "reserved",
                    "suggestion": _suggest_slug(slug),
                }
            )
        if Organization.objects.filter(slug=slug).exists():
            return Response(
                {
                    "available": False,
                    "reason": "taken",
                    "suggestion": _suggest_slug(slug),
                }
            )
        return Response({"available": True})


class CheckDomainView(APIView):
    """Tell the signup form whether the email maps to an existing org.

    The frontend uses this to switch the UI from "Create organization" to
    "Request to join {OrgName}" before the user even submits the form.
    Returns `matches_org: false` for public webmail providers.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [SignupCheckThrottle]

    def get(self, request: Request) -> Response:
        email = request.query_params.get("email", "").strip().lower()
        domain = extract_email_domain(email)
        if not domain:
            return Response(
                {"matches_org": False, "reason": "invalid_email"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if is_public_email_domain(domain):
            return Response({"matches_org": False, "reason": "public_domain"})

        org = (
            Organization.objects.filter(email_domain=domain, is_active=True)
            .order_by("created_at")
            .first()
        )
        if org:
            return Response(
                {
                    "matches_org": True,
                    "org_name": org.name,
                    "domain": domain,
                }
            )
        return Response({"matches_org": False, "domain": domain})
