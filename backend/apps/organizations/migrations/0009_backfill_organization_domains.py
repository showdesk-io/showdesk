"""Backfill OrganizationDomain rows from the legacy scalar fields.

For each Organization:
  - non-empty `email_domain` → row(is_email_routing=True, status=verified,
    method=admin_email). The first admin's email vetted this at signup.
  - non-empty `domain` (branding) → row(is_branding=True, status=pending).
    Free-text field — admins must re-verify via DNS later.

If the same domain appears as both `email_domain` and `domain` on a single
org, we collapse onto the email_routing row and flip is_branding=True.

If two orgs share the same `email_domain` (unexpected but possible from
manual seeding), only the oldest stays verified; the rest are marked
failed to avoid violating the global "at most one verified per domain"
unique index.

`reverse_code` deletes all OrganizationDomain rows. The legacy scalar
fields are left untouched in this PR — their drop happens later, once
all reads have been migrated.
"""

import re

from django.db import migrations


# Mirrors apps.organizations.models.PUBLIC_EMAIL_DOMAINS at the time of
# this migration. Frozen here on purpose: data migrations must not import
# live model code (its shape may diverge).
_PUBLIC_EMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "hotmail.com",
        "hotmail.fr",
        "outlook.com",
        "outlook.fr",
        "live.com",
        "msn.com",
        "yahoo.com",
        "yahoo.fr",
        "ymail.com",
        "icloud.com",
        "me.com",
        "mac.com",
        "protonmail.com",
        "proton.me",
        "pm.me",
        "aol.com",
        "gmx.com",
        "gmx.de",
        "mail.com",
        "mail.ru",
        "yandex.com",
        "yandex.ru",
        "qq.com",
        "163.com",
        "126.com",
        "free.fr",
        "orange.fr",
        "wanadoo.fr",
        "laposte.net",
        "sfr.fr",
    }
)

# Loose syntactic check: lowercase letters, digits, dots, dashes, with a
# TLD-like suffix. Used to skip junk values in the legacy free-text
# `Organization.domain` field (e.g. "Acme HQ" or "https://acme.com/x").
_DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,253}[a-z0-9])?\.[a-z]{2,}$")


def _normalize(value: str) -> str:
    return (value or "").strip().lower()


def _looks_like_domain(value: str) -> bool:
    return bool(_DOMAIN_RE.match(value))


def backfill(apps, schema_editor):  # noqa: ANN001
    Organization = apps.get_model("organizations", "Organization")
    OrganizationDomain = apps.get_model("organizations", "OrganizationDomain")

    # Track which domain has been claimed (verified) globally so we can
    # avoid the "only one verified per domain" unique-index violation.
    claimed_verified: set[str] = set()

    for org in Organization.objects.order_by("created_at"):
        email_domain = _normalize(org.email_domain)
        branding_domain = _normalize(org.domain)

        # Skip empty / public-webmail email_domains for routing rows.
        routing_domain = (
            email_domain
            if email_domain and email_domain not in _PUBLIC_EMAIL_DOMAINS
            else ""
        )

        rows: list[dict] = []

        if routing_domain:
            if routing_domain in claimed_verified:
                # Another org already holds this domain verified. Mark this
                # one failed so the index stays consistent. Operators can
                # re-run DNS verification post-migration if needed.
                rows.append(
                    {
                        "domain": routing_domain,
                        "is_email_routing": True,
                        "is_branding": False,
                        "status": "failed",
                        "verification_method": "admin_email",
                        "verified_at": None,
                    }
                )
            else:
                rows.append(
                    {
                        "domain": routing_domain,
                        "is_email_routing": True,
                        "is_branding": False,
                        "status": "verified",
                        "verification_method": "admin_email",
                        "verified_at": org.created_at,
                    }
                )
                claimed_verified.add(routing_domain)

        if branding_domain and _looks_like_domain(branding_domain):
            existing = next(
                (r for r in rows if r["domain"] == branding_domain), None
            )
            if existing is not None:
                # Same domain serves both purposes — collapse onto the
                # routing row by flipping is_branding=True.
                existing["is_branding"] = True
            else:
                rows.append(
                    {
                        "domain": branding_domain,
                        "is_email_routing": False,
                        "is_branding": True,
                        "status": "pending",
                        "verification_method": None,
                        "verified_at": None,
                    }
                )

        for row in rows:
            OrganizationDomain.objects.create(organization=org, **row)


def unbackfill(apps, schema_editor):  # noqa: ANN001
    OrganizationDomain = apps.get_model("organizations", "OrganizationDomain")
    OrganizationDomain.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0008_organizationdomain"),
    ]

    operations = [
        migrations.RunPython(backfill, reverse_code=unbackfill),
    ]
