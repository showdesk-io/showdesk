"""Branded transactional email helper.

All outgoing emails should go through ``send_branded_email`` so they share
the same HTML shell (header, footer, CTA buttons) and ship a plain-text
fallback alongside the HTML body.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from django.conf import settings
from django.template.loader import render_to_string

from django.core.mail import EmailMultiAlternatives

logger = logging.getLogger(__name__)


SHOWDESK_BRAND = {
    "name": "Showdesk",
    "primary_color": "#5B5BD6",
    "primary_color_dark": "#4A4AC4",
    "text_color": "#0F172A",
    "muted_color": "#64748B",
    "background": "#F1F5F9",
    "card_background": "#FFFFFF",
    "border_color": "#E2E8F0",
    "logo_url": "",
}


def _brand_for(organization: Any | None) -> dict[str, Any]:
    """Resolve brand context, allowing per-org overrides when available."""
    brand = dict(SHOWDESK_BRAND)
    if organization is None:
        return brand

    primary = getattr(organization, "primary_color", None)
    if primary:
        brand["primary_color"] = primary
    logo = getattr(organization, "logo_url", None)
    if logo:
        brand["logo_url"] = logo
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
        from_email=from_email or settings.DEFAULT_FROM_EMAIL,
        to=list(recipients),
        reply_to=list(reply_to) if reply_to else None,
    )
    message.attach_alternative(html_body, "text/html")
    return message.send(fail_silently=fail_silently)
