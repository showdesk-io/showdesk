"""Change ticket reference from globally unique to unique per organization."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0004_organization_widget_secret"),
        ("tickets", "0005_add_issue_type_and_external_user_id"),
    ]

    operations = [
        # Drop the global unique constraint
        migrations.AlterField(
            model_name="ticket",
            name="reference",
            field=models.CharField(
                db_index=True,
                help_text="Human-readable ticket reference (e.g., SD-1234).",
                max_length=20,
            ),
        ),
        # Add unique_together for (organization, reference)
        migrations.AlterUniqueTogether(
            name="ticket",
            unique_together={("organization", "reference")},
        ),
    ]
