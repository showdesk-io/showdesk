import logging

from django.db import migrations

from apps.organizations.models import is_public_email_domain

logger = logging.getLogger(__name__)


def free_squatted_public_addresses(apps, schema_editor):
    """Clear public addresses on a domain another organization has verified.

    Set before a public address needed its domain verified by the mailbox's
    organization: the domain's owner gets them back, as a verification now
    does. A webmail domain verified before that was refused is nobody's.
    """
    Mailbox = apps.get_model("email_channel", "Mailbox")
    OrganizationDomain = apps.get_model("organizations", "OrganizationDomain")
    owners = {
        domain: organization_id
        for domain, organization_id in OrganizationDomain.objects.filter(
            status="verified"
        ).values_list("domain", "organization_id")
        if not is_public_email_domain(domain)
    }
    squatted = [
        mailbox
        for mailbox in Mailbox.objects.exclude(public_address="").only(
            "pk", "organization_id", "public_address"
        )
        if owners.get(mailbox.public_address.rpartition("@")[2].lower())
        not in (None, mailbox.organization_id)
    ]
    for mailbox in squatted:
        logger.warning(
            "Clearing public address %s of mailbox %s: its domain is another "
            "organization's.",
            mailbox.public_address,
            mailbox.pk,
        )
    Mailbox.objects.filter(pk__in=[m.pk for m in squatted]).update(public_address="")


class Migration(migrations.Migration):
    dependencies = [
        ("email_channel", "0004_sending_removal"),
        ("organizations", "0017_organizationdomain_sending"),
    ]

    operations = [
        migrations.RunPython(free_squatted_public_addresses, migrations.RunPython.noop),
    ]
