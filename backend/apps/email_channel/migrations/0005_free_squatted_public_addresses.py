from django.db import migrations


def free_squatted_public_addresses(apps, schema_editor):
    """Clear public addresses on a domain another organization has verified.

    Set before a public address needed its domain verified by the mailbox's
    organization: the domain's owner gets them back, as a verification now
    does.
    """
    Mailbox = apps.get_model("email_channel", "Mailbox")
    OrganizationDomain = apps.get_model("organizations", "OrganizationDomain")
    owners = dict(
        OrganizationDomain.objects.filter(status="verified").values_list(
            "domain", "organization_id"
        )
    )
    squatted = [
        mailbox.pk
        for mailbox in Mailbox.objects.exclude(public_address="").only(
            "pk", "organization_id", "public_address"
        )
        if owners.get(mailbox.public_address.rpartition("@")[2].lower())
        not in (None, mailbox.organization_id)
    ]
    Mailbox.objects.filter(pk__in=squatted).update(public_address="")


class Migration(migrations.Migration):
    dependencies = [
        ("email_channel", "0004_sending_removal"),
        ("organizations", "0017_organizationdomain_sending"),
    ]

    operations = [
        migrations.RunPython(free_squatted_public_addresses, migrations.RunPython.noop),
    ]
