"""Branded transactional email helper.

All outgoing emails should go through ``send_branded_email`` so they share
the same HTML shell (header, footer, CTA buttons) and ship a plain-text
fallback alongside the HTML body.
"""

from __future__ import annotations

import logging
from email.utils import formataddr, parseaddr
from typing import Any, Iterable

from django.conf import settings
from django.template.loader import render_to_string

from django.core.mail import EmailMultiAlternatives

logger = logging.getLogger(__name__)


def _default_logo_url() -> str:
    """URL of the default Showdesk logo, served by Django from backend/static/."""
    return (
        settings.BRAND_LOGO_URL
        or f"{settings.SITE_URL.rstrip('/')}/static/brand/logo.png"
    )


def _showdesk_brand() -> dict[str, Any]:
    """Build the default Showdesk brand dict from Django settings.

    Read at call time (not import time) so tests and runtime overrides of
    settings take effect without re-importing this module.
    """
    return {
        "name": settings.BRAND_NAME,
        "primary_color": settings.BRAND_PRIMARY_COLOR,
        "primary_color_dark": settings.BRAND_PRIMARY_COLOR_DARK,
        "text_color": settings.BRAND_TEXT_COLOR,
        "muted_color": settings.BRAND_MUTED_COLOR,
        "background": settings.BRAND_BACKGROUND_COLOR,
        "card_background": settings.BRAND_CARD_BACKGROUND_COLOR,
        "border_color": settings.BRAND_BORDER_COLOR,
        "logo_url": _default_logo_url(),
    }


def _brand_for(organization: Any | None) -> dict[str, Any]:
    """Resolve brand context, allowing per-org overrides when available."""
    brand = _showdesk_brand()
    if organization is None:
        return brand

    primary = getattr(organization, "primary_color", None)
    if primary:
        brand["primary_color"] = primary

    # Per-org logo: Organization.logo is an ImageField; .url goes through the
    # storage backend (S3 or local). Falls back silently to the default
    # Showdesk logo if the file is missing or storage can't yield a URL.
    org_logo = getattr(organization, "logo", None)
    if org_logo and getattr(org_logo, "name", ""):
        try:
            brand["logo_url"] = org_logo.url
        except Exception:  # noqa: BLE001 — keep default rather than crash
            logger.exception("org logo URL unavailable; using default")

    org_name = getattr(organization, "name", None)
    if org_name:
        brand["org_name"] = org_name
    return brand


def send_branded_email(
    *,
    template: str,
    context: dict[str, Any],
    subject: str,
    to: Iterable[str],
    organization: Any | None = None,
    reply_to: Iterable[str] | None = None,
    from_email: str | None = None,
    fail_silently: bool = False,
) -> int:
    """Render and send a branded HTML + plain-text email.

    ``template`` is the base name under ``templates/emails/`` (e.g.
    ``"ticket_created"``); the helper loads ``<template>.html`` and
    ``<template>.txt``.
    """
    recipients = [addr for addr in to if addr]
    if not recipients:
        logger.info("send_branded_email: no recipients for %s, skipping", template)
        return 0

    full_context = {
        **context,
        "brand": _brand_for(organization),
        "site_url": getattr(settings, "SITE_URL", ""),
        "subject": subject,
    }

    html_body = render_to_string(f"emails/{template}.html", full_context)
    text_body = render_to_string(f"emails/{template}.txt", full_context)

    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=_format_from_email(from_email, organization),
        to=list(recipients),
        reply_to=list(reply_to) if reply_to else None,
    )
    message.attach_alternative(html_body, "text/html")
    return message.send(fail_silently=fail_silently)


def _format_from_email(
    from_email: str | None, organization: Any | None
) -> str:
    """Build the From: header, honouring per-org ``email_from_name`` overrides.

    The address part stays whatever was passed (or ``DEFAULT_FROM_EMAIL``).
    The display name comes from ``Organization.email_from_name`` if set,
    otherwise from ``BRAND_NAME`` -- matching what end-users see in the
    rendered HTML.
    """
    raw = from_email or settings.DEFAULT_FROM_EMAIL
    name, address = parseaddr(raw)
    if not address:
        return raw  # Couldn't parse; let Django reject it downstream.

    org_name = (
        getattr(organization, "email_from_name", "") if organization else ""
    )
    display = org_name or name or settings.BRAND_NAME
    return formataddr((display, address))
