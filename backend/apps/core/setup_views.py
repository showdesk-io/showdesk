"""Instance setup views for first-time initialization.

These endpoints are public and only work until a real account exists. End users
don't count, as the public widget can create them. Neither do unfinished setup
attempts: an unverified superuser in no organization, which a retry replaces.
"""

import logging

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.email import send_branded_email
from apps.core.throttling import OTP_REQUEST_THROTTLES
from apps.organizations.models import OTPCode, User

logger = logging.getLogger(__name__)


def _unfinished_setup_attempts():
    return User.objects.filter(
        is_superuser=True, is_verified=False, organization__isnull=True
    )


def is_instance_initialized() -> bool:
    """Check if anyone other than an end user or a setup attempt has an account.

    Not based on is_verified or is_staff alone: an email change clears the first
    and a demotion the second, and neither may reopen setup.
    """
    return (
        User.objects.filter(
            Q(role__in=[User.Role.ADMIN, User.Role.AGENT])
            | Q(is_staff=True)
            | Q(is_superuser=True)
        )
        .exclude(pk__in=_unfinished_setup_attempts().values("pk"))
        .exists()
    )


class SetupStatusView(APIView):
    """Check whether the instance has been initialized."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request: Request) -> Response:
        return Response({"initialized": is_instance_initialized()})


class InitializeSerializer(serializers.Serializer):
    """Serializer for instance initialization."""

    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150, required=False, default="")


class SetupInitializeView(APIView):
    """Create the first platform admin and send an OTP for login.

    This endpoint only works when no users exist in the database.
    It creates a superuser (is_staff=True, is_superuser=True) with
    no organization, then sends an OTP to the provided email.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = OTP_REQUEST_THROTTLES

    def post(self, request: Request) -> Response:
        if is_instance_initialized():
            return Response(
                {"detail": "Instance is already initialized."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = InitializeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"].lower()
        first_name = serializer.validated_data["first_name"]
        last_name = serializer.validated_data["last_name"]

        try:
            with transaction.atomic():
                _unfinished_setup_attempts().delete()

                # Create the platform admin
                user = User.objects.create_superuser(
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                )

                # Generate and send OTP — if email fails, rollback user creation
                otp = OTPCode.generate(email)
                self._send_otp_email(email, otp.code)

            logger.info("Platform admin created and OTP sent: %s", user.email)
        except Exception:
            logger.exception("Setup failed for %s", email)
            return Response(
                {
                    "detail": "Failed to send verification email. Please check your email configuration and try again."
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {"detail": "Admin account created. Check your email for the login code."},
            status=status.HTTP_201_CREATED,
        )

    def _send_otp_email(self, email: str, code: str) -> None:
        """Send the OTP code via email."""
        expiry_minutes = getattr(settings, "OTP_EXPIRY_SECONDS", 600) // 60

        send_branded_email(
            template="otp_code",
            subject=f"Showdesk setup code: {code}",
            to=[email],
            context={
                "kicker": "Welcome",
                "heading": "Welcome to Showdesk",
                "intro": "You're almost done. Use the code below to finish setting up your instance.",
                "code": code,
                "expiry_minutes": expiry_minutes,
            },
        )
