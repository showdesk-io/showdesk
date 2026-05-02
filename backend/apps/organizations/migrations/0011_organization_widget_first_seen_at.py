from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0010_remove_organization_domain_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="widget_first_seen_at",
            field=models.DateTimeField(
                blank=True,
                help_text=(
                    "Timestamp of the first widget request authenticated with "
                    "this org's api_token. Powers the install-detection step "
                    "in onboarding."
                ),
                null=True,
            ),
        ),
    ]
