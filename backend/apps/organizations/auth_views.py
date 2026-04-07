"""OTP-based authentication views.

Flow:
1. POST /api/v1/auth/request-otp/  { "email": "..." }
   → Sends a 6-digit OTP code via email, returns 200.
2. POST /api/v1/auth/verify-otp/   { "email": "...", "code": "..." }
   → Verifies the code, returns JWT access + refresh tokens.

No passwords involved. The email IS the authentication factor,
the OTP proves the user has access to that inbox.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import OTPCode, User

logger = logging.getLogger(__name__)


class RequestOTPSerializer(serializers.Serializer):
    """Serializer for OTP request."""

    email = serializers.EmailField()


class VerifyOTPSerializer(serializers.Serializer):
    """Serializer for OTP verification."""

    email = serializers.EmailField()
    code = serializers.CharField(max_length=8)


class RequestOTPView(APIView):
    """Send a one-time code to the user's email.

    Always returns 200 regardless of whether the email exists,
    to prevent email enumeration attacks.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "otp"

    def post(self, request: Request) -> Response:
        serializer = RequestOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].lower()

        # Only send OTP if the user exists and has dashboard access
        user = User.objects.filter(email=email, is_active=True).first()
        if user and (user.is_agent or user.is_staff):
            otp = OTPCode.generate(email)
            self._send_otp_email(email, otp.code)
            logger.info("OTP sent to %s", email)
        else:
            # Don't reveal whether the email exists
            logger.info("OTP requested for unknown/inactive email: %s", email)

        return Response(
            {"detail": "If this email is registered, you will receive a code shortly."},
            status=status.HTTP_200_OK,
        )

    def _send_otp_email(self, email: str, code: str) -> None:
        """Send the OTP code via email."""
        expiry_minutes = getattr(settings, "OTP_EXPIRY_SECONDS", 600) // 60

        subject = f"Showdesk login code: {code}"
        message = (
            f"Your Showdesk login code is: {code}\n\n"
            f"This code expires in {expiry_minutes} minutes.\n"
            f"If you didn't request this, you can safely ignore this email."
        )

        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )


class VerifyOTPView(APIView):
    """Verify an OTP code and return JWT tokens.

    On success, returns access and refresh tokens.
    On failure, returns 401.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "otp"

    def post(self, request: Request) -> Response:
        serializer = VerifyOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"].lower()
        code = serializer.validated_data["code"]

        # Find the most recent valid OTP for this email
        otp = (
            OTPCode.objects.filter(email=email, code=code, used_at__isnull=True)
            .order_by("-created_at")
            .first()
        )

        if not otp or not otp.is_valid:
            return Response(
                {"detail": "Invalid or expired code."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Find the user
        user = User.objects.filter(email=email, is_active=True).first()
        if not user or not (user.is_agent or user.is_staff):
            return Response(
                {"detail": "Invalid or expired code."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Mark OTP as used
        otp.mark_used()

        # Mark user as verified on first successful OTP
        if not user.is_verified:
            user.is_verified = True
            user.save(update_fields=["is_verified"])

        # Issue JWT tokens
        refresh = RefreshToken.for_user(user)

        logger.info("OTP verified for %s", email)

        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
            status=status.HTTP_200_OK,
        )
