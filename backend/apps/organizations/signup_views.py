"""Self-service signup endpoints (OTP-first flow).

Public, unauthenticated endpoints that walk a prospect through:
  1. Enter email → receive OTP (POST /auth/signup/request-otp/)
  2. Verify OTP → JWT issued + routing decision (POST /auth/signup/verify-otp/)
  3. Either create org via wizard (POST /auth/signup/create-org/) or
     request to join an existing org (POST /auth/signup/request-join/).

The routing decision (`next_step`) is computed from the verified user's
state and email domain:
  - "has_org": user is already attached to an org → log in to dashboard.
  - "join_request": user has no org but their email domain matches an
    existing org → propose join request.
  - "create_org": user has no org and no domain match → propose wizard.

A User row is created at OTP verify time (role=ADMIN, is_staff=True,
organization=None) — this keeps the auth model uniform: signup-pending
users can log in via either /auth/request-otp/ or /auth/signup/request-otp/
and resume the wizard. Public webmail email_domain is never persisted.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils.text import slugify
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

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
from .serializers import UserSerializer

logger = logging.getLogger(__name__)

# Slug rules: lowercase ASCII, digits, dashes; 3-50 chars; cannot start/end
# with a dash. Validated client- and server-side.
_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,48}[a-z0-9])?$")
# Cap *successful* org-creations / join-requests per IP per hour. Failed
# validation attempts do not count — they shouldn't penalize a user who
# is iterating on their form.
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


def _client_ip(request: Request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _success_cache_key(request: Request) -> str:
    return f"signup_success:{_client_ip(request)}"


def _check_success_quota(request: Request) -> Response | None:
    count = cache.get(_success_cache_key(request), 0)
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


def _record_signup_success(request: Request) -> None:
    key = _success_cache_key(request)
    current = cache.get(key, 0)
    cache.set(key, current + 1, SIGNUP_SUCCESS_WINDOW_SECONDS)


def _send_otp_email(email: str, code: str, intro: str | None = None) -> None:
    expiry_minutes = getattr(settings, "OTP_EXPIRY_SECONDS", 600) // 60
    send_branded_email(
        template="otp_code",
        subject=f"Showdesk login code: {code}",
        to=[email],
        context={
            "kicker": "Sign in",
            "heading": "Your Showdesk login code",
            "intro": intro
            or "Use the code below to finish creating your Showdesk account.",
            "code": code,
            "expiry_minutes": expiry_minutes,
        },
        fail_silently=True,
    )


def _send_welcome_email(user: User, org: Organization) -> None:
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
    org: Organization, join_request: OrgJoinRequest
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
            "review_url": f"{getattr(settings, 'SITE_URL', '')}/settings/team",
        },
        fail_silently=True,
    )


def _resolve_next_step(user: User) -> dict[str, Any]:
    """Decide what the signup UI should do next for this verified user.

    Returns one of three shapes:
      - {"next_step": "has_org", "org_id": ..., "org_slug": ...}
      - {"next_step": "join_request", "org_id": ..., "org_name": ...}
      - {"next_step": "create_org", "domain": "..."}
    """
    if user.organization_id is not None:
        org = user.organization
        return {
            "next_step": "has_org",
            "org_id": str(org.id),
            "org_slug": org.slug,
        }

    domain = extract_email_domain(user.email)
    if domain and not is_public_email_domain(domain):
        match = (
            Organization.objects.filter(email_domain=domain, is_active=True)
            .order_by("created_at")
            .first()
        )
        if match:
            return {
                "next_step": "join_request",
                "org_id": str(match.id),
                "org_name": match.name,
                "domain": domain,
            }
    return {"next_step": "create_org", "domain": domain or ""}


def _split_full_name(full_name: str) -> tuple[str, str]:
    first, _, last = full_name.strip().partition(" ")
    return first, last


# ---------------------------------------------------------------------------
# Step 1: request OTP
# ---------------------------------------------------------------------------


class SignupRequestOTPSerializer(serializers.Serializer):
    """Validate signup OTP-request payload."""

    email = serializers.EmailField()
    full_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )


class SignupRequestOTPView(APIView):
    """Send an OTP to an email entering the signup flow.

    Unlike /auth/request-otp/ (login), this endpoint sends an OTP to *any*
    valid email — login is enumeration-protected, but signup is an explicit
    intent so we can confirm receipt directly.

    Refuses (409) if the email belongs to an existing END_USER (a customer
    of some org). They cannot upgrade themselves to an admin via signup.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [SignupCheckThrottle]

    def post(self, request: Request) -> Response:
        serializer = SignupRequestOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].lower().strip()
        full_name = (serializer.validated_data.get("full_name") or "").strip()

        existing = User.objects.filter(email__iexact=email).first()
        if existing and (
            existing.role == User.Role.END_USER or not existing.is_active
        ):
            return Response(
                {
                    "detail": (
                        "This email cannot be used for signup. If you think "
                        "this is a mistake, contact your Showdesk admin."
                    ),
                    "code": "email_taken",
                },
                status=status.HTTP_409_CONFLICT,
            )

        # Stash the full_name in cache so we can apply it at verify-otp time
        # if the user is being created. Short TTL aligned with OTP expiry.
        if full_name:
            cache.set(
                f"signup_pending_name:{email}",
                full_name,
                getattr(settings, "OTP_EXPIRY_SECONDS", 600),
            )

        otp = OTPCode.generate(email)
        _send_otp_email(email, otp.code)
        logger.info("Signup OTP sent to %s", email)

        return Response(
            {"detail": "If this email is reachable, you will receive a code shortly."},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Step 2: verify OTP
# ---------------------------------------------------------------------------


class SignupVerifyOTPSerializer(serializers.Serializer):
    """Validate signup OTP-verify payload."""

    email = serializers.EmailField()
    code = serializers.CharField(max_length=8)


class SignupVerifyOTPView(APIView):
    """Verify the signup OTP and return JWT + the next routing step.

    On first verify for an unknown email, creates a User row with role=ADMIN,
    is_staff=True, is_verified=True, organization=None. This "lonely" user
    is benign (all org-scoped queries return empty) and lets the wizard
    resume after a browser refresh: the same flow handles re-entry.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [SignupCheckThrottle]

    @transaction.atomic
    def post(self, request: Request) -> Response:
        serializer = SignupVerifyOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].lower().strip()
        code = serializer.validated_data["code"]

        otp = (
            OTPCode.objects.filter(email=email, code=code, used_at__isnull=True)
            .order_by("-created_at")
            .first()
        )
        if not otp or not otp.is_valid:
            return Response(
                {"detail": "Invalid or expired code.", "code": "invalid_otp"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        user = User.objects.filter(email__iexact=email).first()
        if user and (user.role == User.Role.END_USER or not user.is_active):
            # Defense-in-depth: also blocked at request-otp.
            return Response(
                {"detail": "Invalid or expired code.", "code": "invalid_otp"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        otp.mark_used()

        if user is None:
            full_name = cache.get(f"signup_pending_name:{email}", "") or ""
            first_name, last_name = _split_full_name(full_name)
            user = User(
                email=email,
                first_name=first_name,
                last_name=last_name,
                role=User.Role.ADMIN,
                is_staff=True,
                is_verified=True,
                organization=None,
            )
            user.set_unusable_password()
            user.save()
            cache.delete(f"signup_pending_name:{email}")
            logger.info("Signup: created lonely user for %s", email)
        elif not user.is_verified:
            user.is_verified = True
            user.save(update_fields=["is_verified"])

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user).data,
                **_resolve_next_step(user),
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Step 3a: create org via wizard
# ---------------------------------------------------------------------------


class SignupStateView(APIView):
    """Return the next routing step for the authenticated user.

    Used by the frontend to resume the wizard after a refresh: when an
    authenticated user without an organization lands on /signup, we want
    to drop them straight into the wizard or the join-confirm screen.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(
            {
                "user": UserSerializer(request.user).data,
                **_resolve_next_step(request.user),
            }
        )


class CreateOrgSerializer(serializers.Serializer):
    """Validate the wizard create-org payload."""

    org_name = serializers.CharField(max_length=255)
    org_slug = serializers.CharField(max_length=50)


class SignupCreateOrgView(APIView):
    """Create the user's organization from the post-OTP wizard.

    Requires the authenticated user to have no organization yet (the
    "lonely user" state produced by /auth/signup/verify-otp/).
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request: Request) -> Response:
        if request.user.organization_id is not None:
            return Response(
                {
                    "detail": "You already belong to an organization.",
                    "code": "already_in_org",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if (over := _check_success_quota(request)) is not None:
            return over

        serializer = CreateOrgSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        org_name = serializer.validated_data["org_name"].strip()
        org_slug = serializer.validated_data["org_slug"].strip().lower()

        if not _slug_available(org_slug):
            return Response(
                {
                    "detail": "This slug is unavailable.",
                    "code": "slug_taken",
                    "suggestion": _suggest_slug(org_slug),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        domain = extract_email_domain(request.user.email)
        email_domain = (
            domain if domain and not is_public_email_domain(domain) else ""
        )

        org = Organization.objects.create(
            name=org_name,
            slug=org_slug,
            email_domain=email_domain,
        )

        user = request.user
        user.organization = org
        user.role = User.Role.ADMIN
        user.is_staff = True
        user.save(update_fields=["organization", "role", "is_staff"])

        _record_signup_success(request)
        _send_welcome_email(user, org)
        logger.info("Signup: created org %s for %s", org.slug, user.email)

        return Response(
            {
                "user": UserSerializer(user).data,
                "organization": {
                    "id": str(org.id),
                    "slug": org.slug,
                    "name": org.name,
                },
            },
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Step 3b: request to join an existing org
# ---------------------------------------------------------------------------


class RequestJoinSerializer(serializers.Serializer):
    """Validate the request-join payload (full_name is optional refinement)."""

    full_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )


class SignupRequestJoinView(APIView):
    """Submit a request to join the org that matches the user's email domain.

    Requires the authenticated user to have no organization yet. The match
    is recomputed server-side from the user's email — the client cannot
    pick a target org.
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request: Request) -> Response:
        user = request.user
        if user.organization_id is not None:
            return Response(
                {
                    "detail": "You already belong to an organization.",
                    "code": "already_in_org",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if (over := _check_success_quota(request)) is not None:
            return over

        domain = extract_email_domain(user.email)
        match = None
        if domain and not is_public_email_domain(domain):
            match = (
                Organization.objects.filter(email_domain=domain, is_active=True)
                .order_by("created_at")
                .first()
            )
        if not match:
            return Response(
                {
                    "detail": "No organization matches your email domain.",
                    "code": "no_match",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = RequestJoinSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        full_name = (serializer.validated_data.get("full_name") or "").strip()
        if full_name and not (user.first_name or user.last_name):
            user.first_name, user.last_name = _split_full_name(full_name)
            user.save(update_fields=["first_name", "last_name"])

        display_name = full_name or f"{user.first_name} {user.last_name}".strip()
        join_request, created = OrgJoinRequest.objects.get_or_create(
            organization=match,
            email=user.email,
            status=OrgJoinRequest.Status.PENDING,
            defaults={"full_name": display_name},
        )
        if created:
            _notify_admins_of_join_request(match, join_request)
            _record_signup_success(request)
            logger.info(
                "Signup: created join request for %s -> %s",
                user.email,
                match.slug,
            )
        else:
            logger.info(
                "Signup: duplicate pending join request for %s -> %s",
                user.email,
                match.slug,
            )

        return Response(
            {
                "status": "join_requested",
                "organization": {"id": str(match.id), "name": match.name},
            },
            status=status.HTTP_202_ACCEPTED,
        )


# ---------------------------------------------------------------------------
# Live form-helper endpoints (unchanged behavior)
# ---------------------------------------------------------------------------


class CheckSlugView(APIView):
    """Live slug-availability check used by the signup wizard."""

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

    Used during the email-entry step to preview the upcoming routing
    decision (so the CTA can read "Request to join {OrgName}").
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
