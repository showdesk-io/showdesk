"""Celery tasks of the contacts app."""

import logging

from celery import shared_task

from apps.core.email import send_branded_email

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def export_contact_data(self, contact_id: str, requested_by_id: str) -> None:
    """Email a contact's data to who asked for it, as an attachment.

    Never on a storage, where a URL could outlive the request or reach someone else.
    """
    from apps.contacts import gdpr
    from apps.contacts.models import Contact
    from apps.organizations.models import User

    contact = (
        Contact.objects.select_related("organization", "company")
        .filter(id=contact_id)
        .first()
    )
    user = User.objects.filter(id=requested_by_id).first()
    if contact is None or user is None:
        logger.warning(
            "Skipping the export of contact %s for user %s: one no longer exists.",
            contact_id,
            requested_by_id,
        )
        return

    export = gdpr.build_contact_export(contact)
    message: dict = {
        "template": "contact_export_ready",
        "subject": "Contact export ready",
        "attachments": [(f"contact-{contact.id}.zip", export, "application/zip")],
    }
    if len(export) > gdpr.MAX_EXPORT_ATTACHMENT_BYTES:
        logger.warning(
            "The export of contact %s is too large to email: %d bytes.",
            contact.id,
            len(export),
        )
        message = {
            "template": "contact_export_too_large",
            "subject": "Contact export too large",
        }
    try:
        send_branded_email(
            to=[user.email],
            organization=contact.organization,
            context={"contact_name": contact.display_name, "contact_id": contact.id},
            **message,
        )
    except Exception as exc:
        logger.exception("Failed to email the export of contact %s", contact.id)
        raise self.retry(exc=exc)
