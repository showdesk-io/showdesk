"""Provision the Showdesk internal organization (dogfooding).

Creates a singleton org identified by its slug. Tickets from the in-app
widget — used by Showdesk staff to report bugs and feature requests —
are scoped to this organization.
"""

from django.db import migrations

INTERNAL_SLUG = "showdesk-internal"


def create_internal_org(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    Organization.objects.get_or_create(
        slug=INTERNAL_SLUG,
        defaults={
            "name": "Showdesk Internal",
            "domain": "showdesk.local",
            "widget_color": "#6366F1",
            "widget_position": "bottom-right",
            "widget_greeting": "Found a bug? Got an idea? Tell us.",
            "video_expiration_days": 90,
            "video_max_duration_seconds": 600,
        },
    )


def remove_internal_org(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    Organization.objects.filter(slug=INTERNAL_SLUG).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0005_widget_session_and_messaging"),
    ]

    operations = [
        migrations.RunPython(create_internal_org, remove_internal_org),
    ]
