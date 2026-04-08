"""OTP-based authentication for Django admin.

Replaces the default username/password login with the same OTP flow
used by the frontend: enter email -> receive code -> verify code.
"""

import logging

from django.conf import settings
from django.contrib import auth
from django.core.mail import send_mail
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from apps.organizations.models import OTPCode, User

logger = logging.getLogger(__name__)


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

            user = User.objects.filter(
                email=email, is_active=True, is_staff=True
            ).first()
            if user:
                otp = OTPCode.generate(email)
                expiry_minutes = getattr(settings, "OTP_EXPIRY_SECONDS", 600) // 60
                send_mail(
                    subject=f"Showdesk admin login code: {otp.code}",
                    message=(
                        f"Your Showdesk admin login code is: {otp.code}\n\n"
                        f"This code expires in {expiry_minutes} minutes.\n"
                        f"If you didn't request this, you can safely ignore this email."
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[email],
                    fail_silently=False,
                )
                logger.info("Admin OTP sent to %s", email)

            # Always advance to code step (prevent email enumeration)
            context["step"] = "code"
            context["email"] = email

        elif step == "code":
            email = request.POST.get("email", "").strip().lower()
            code = request.POST.get("code", "").strip()
            context["email"] = email

            otp = (
                OTPCode.objects.filter(email=email, code=code, used_at__isnull=True)
                .order_by("-created_at")
                .first()
            )

            user = User.objects.filter(
                email=email, is_active=True, is_staff=True
            ).first()

            if otp and otp.is_valid and user:
                otp.mark_used()
                auth.login(request, user)
                logger.info("Admin OTP verified for %s", email)
                next_url = request.GET.get("next", "admin:index")
                return redirect(next_url)

            context["step"] = "code"
            context["error"] = "Invalid or expired code."

    return render(request, "admin/otp_login.html", context)
