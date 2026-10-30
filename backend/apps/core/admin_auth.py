"""OTP-based authentication for Django admin.

Replaces the default username/password login with the same OTP flow
used by the frontend: enter email -> receive code -> verify code.
"""

import logging

from django.conf import settings
from django.contrib import auth
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from apps.core.email import send_branded_email
from apps.core.throttling import OTP_REQUEST_THROTTLES, OTP_VERIFY_THROTTLES
from apps.organizations.models import OTPCode, User

logger = logging.getLogger(__name__)

TOO_MANY_ATTEMPTS = "Too many attempts. Please try again later."


def _throttled(request: HttpRequest, throttles: list) -> bool:
    """Apply the API's OTP throttles to this form: every counter gets the hit."""
    allowed = [throttle().allow_request(request, None) for throttle in throttles]
    return not all(allowed)


def _admin_user(email: str) -> User | None:
    """Return who may sign in here. End users don't, even with a stale is_staff."""
    return (
        User.objects.filter(email=email, is_active=True, is_staff=True)
        .exclude(role=User.Role.END_USER, is_superuser=False)
        .first()
    )


def _redirect_after_login(request: HttpRequest) -> HttpResponse:
    next_url = request.GET.get("next", "")
    if url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(next_url)
    return redirect("admin:index")


def admin_otp_login(request: HttpRequest) -> HttpResponse:
    """Handle the two-step OTP login for Django admin."""
    if request.user.is_authenticated and request.user.is_staff:
        return redirect("admin:index")

    step = request.POST.get("step", "email")
    context: dict = {"step": "email", "email": ""}

    if request.method == "POST":
        if step == "email":
            email = request.POST.get("email", "").strip().lower()
            context["email"] = email

            if _throttled(request, OTP_REQUEST_THROTTLES):
                context["error"] = TOO_MANY_ATTEMPTS
                return render(request, "admin/otp_login.html", context, status=429)

            user = _admin_user(email)
            if user:
                otp = OTPCode.generate(email)
                expiry_minutes = getattr(settings, "OTP_EXPIRY_SECONDS", 600) // 60
                send_branded_email(
                    template="otp_code",
                    subject=f"Showdesk admin login code: {otp.code}",
                    to=[email],
                    context={
                        "kicker": "Admin sign-in",
                        "heading": "Your Showdesk admin code",
                        "intro": "Use the code below to access the Showdesk admin.",
                        "code": otp.code,
                        "expiry_minutes": expiry_minutes,
                    },
                )
                logger.info("Admin OTP sent to %s", email)

            # Always advance to code step (prevent email enumeration)
            context["step"] = "code"
            context["email"] = email

        elif step == "code":
            email = request.POST.get("email", "").strip().lower()
            code = request.POST.get("code", "").strip()
            context["email"] = email
            context["step"] = "code"

            if _throttled(request, OTP_VERIFY_THROTTLES):
                context["error"] = TOO_MANY_ATTEMPTS
                return render(request, "admin/otp_login.html", context, status=429)

            otp = OTPCode.redeem(email, code)
            user = _admin_user(email)

            if otp and user:
                if not user.is_verified:
                    user.is_verified = True
                    user.save(update_fields=["is_verified"])
                auth.login(request, user)
                logger.info("Admin OTP verified for %s", email)
                return _redirect_after_login(request)

            context["error"] = "Invalid or expired code."

    return render(request, "admin/otp_login.html", context)
