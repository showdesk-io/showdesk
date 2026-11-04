import logging

from django.db import migrations

logger = logging.getLogger(__name__)

# A frozen copy of `apps.organizations.models.PUBLIC_EMAIL_DOMAINS` as it was
# when this migration was written: a migration must not change with the code.
# Later additions to the list, or to the environment's
# SHOWDESK_PUBLIC_EMAIL_DOMAINS should it be read some day, don't apply here.
PUBLIC_EMAIL_DOMAINS = frozenset(
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
        if domain.lower() not in PUBLIC_EMAIL_DOMAINS
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
