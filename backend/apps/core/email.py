"""Branded transactional email helper.

All outgoing emails should go through ``send_branded_email`` so they share
the same HTML shell (header, footer, CTA buttons) and ship a plain-text
fallback alongside the HTML body.
"""

from __future__ import annotations

import logging
import os
from email.mime.image import MIMEImage
from typing import Any, Iterable

from django.conf import settings
from django.template.loader import render_to_string

from django.core.mail import EmailMultiAlternatives

logger = logging.getLogger(__name__)

# Content-ID used to reference the embedded logo from the email HTML
# (`<img src="cid:showdesk-logo">`). Single ID is fine since each message
# carries at most one logo (Showdesk default OR per-org override).
LOGO_CID = "showdesk-logo"


def _showdesk_brand() -> dict[str, Any]:
    """Build the default Showdesk brand dict from Django settings.

    Read at call time (not import time) so tests and runtime overrides of
    settings take effect without re-importing this module. ``logo_url`` is
    a placeholder here — the real source is resolved by ``_resolve_logo``
    inside ``send_branded_email`` (which may attach the bytes as CID).
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
        "logo_url": "",
    }


def _brand_for(organization: Any | None) -> dict[str, Any]:
    """Resolve brand context, allowing per-org overrides when available."""
    brand = _showdesk_brand()
    if organization is None:
        return brand

    primary = getattr(organization, "primary_color", None)
    if primary:
        brand["primary_color"] = primary
    org_name = getattr(organization, "name", None)
    if org_name:
        brand["org_name"] = org_name
    return brand


def _resolve_logo(organization: Any | None) -> tuple[str, bytes | None]:
    """Decide what to put in the email's logo slot.

    Returns ``(src, bytes_or_None)``. When ``bytes`` is non-None the caller
    must attach those bytes as a CID-related part keyed on ``LOGO_CID``;
    ``src`` will be ``"cid:showdesk-logo"`` in that case. When ``bytes``
    is None, ``src`` is either an external URL or ``""`` (no logo —
    template falls back to text).
    """
    max_bytes = settings.BRAND_LOGO_MAX_BYTES

    # 1. Per-org logo (Organization.logo is an ImageField backed by
    #    Django storage — works for both S3 and local filesystem).
    if organization is not None:
        org_logo = getattr(organization, "logo", None)
        if org_logo and getattr(org_logo, "name", ""):
            try:
                with org_logo.open("rb") as f:
                    data = f.read(max_bytes + 1)
                if len(data) <= max_bytes:
                    return (f"cid:{LOGO_CID}", data)
                logger.warning(
                    "org logo %s exceeds %d bytes; falling back to URL",
                    org_logo.name, max_bytes,
                )
                try:
                    return (org_logo.url, None)
                except Exception:  # noqa: BLE001 — storage may not yield a URL
                    logger.exception("org logo URL unavailable; skipping")
                    return ("", None)
            except Exception:  # noqa: BLE001 — storage failures shouldn't break sends
                logger.exception("failed to read org logo; falling back to default")

    # 2. Explicitly-configured external URL (advanced override).
    if settings.BRAND_LOGO_URL:
        return (settings.BRAND_LOGO_URL, None)

    # 3. Default Showdesk logo from filesystem.
    logo_path = getattr(settings, "BRAND_LOGO_PATH", "")
    if logo_path and os.path.exists(logo_path):
        try:
            with open(logo_path, "rb") as f:
                data = f.read(max_bytes + 1)
            if len(data) <= max_bytes:
                return (f"cid:{LOGO_CID}", data)
            logger.warning(
                "BRAND_LOGO_PATH %s exceeds %d bytes; skipping logo",
                logo_path, max_bytes,
            )
        except Exception:  # noqa: BLE001
            logger.exception("failed to read BRAND_LOGO_PATH; skipping logo")

    # 4. Nothing usable — template will render the text fallback.
    return ("", None)


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

    brand = _brand_for(organization)
    logo_src, logo_bytes = _resolve_logo(organization)
    brand["logo_url"] = logo_src

    full_context = {
        **context,
        "brand": brand,
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

    if logo_bytes is not None:
        # Wrap the alternatives + image in a multipart/related so that mail
        # clients resolve `cid:showdesk-logo` to the embedded part instead
        # of trying to fetch it externally.
        img = MIMEImage(logo_bytes)
        img.add_header("Content-ID", f"<{LOGO_CID}>")
        img.add_header("Content-Disposition", "inline", filename="logo.png")
        message.attach(img)
        message.mixed_subtype = "related"

    return message.send(fail_silently=fail_silently)
