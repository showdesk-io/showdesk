"""Celery tasks of the contacts app."""

import logging

from celery import shared_task

from apps.core.email import send_branded_email

logger = logging.getLogger(__name__)

# ``reason`` of the ``contact_export_failed`` email.
EXPORT_TOO_LARGE = "too_large"
EXPORT_ERROR = "error"


def _tell_export_failed(contact, user, reason: str) -> None:
    """Tell who got a 202 that nothing is coming. There's nothing to do if this fails."""
    if contact is None or user is None:
        logger.error("Nobody to tell that a contact export failed.")
        return
    try:
        send_branded_email(
            template="contact_export_failed",
            subject="Contact export failed",
            to=[user.email],
            organization=contact.organization,
            context={
                "contact_name": contact.display_name,
                "contact_id": contact.id,
                "reason": reason,
            },
        )
    except Exception:
        logger.exception(
            "Couldn't tell who asked for the export of contact %s that it failed.",
            contact.id,
        )


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def export_contact_data(self, contact_id: str, requested_by_id: str) -> None:
    """Email a contact's data to who asked for it, as an attachment.

    Never on a storage, where a URL could outlive the request or reach someone else.

    Who asked only got a 202: any failure that won't be retried, the size or the last
    attempt, sends them one email saying so.
    """
    from apps.contacts import gdpr
    from apps.contacts.models import Contact
    from apps.organizations.models import User

    contact = user = None
    try:
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
        if not gdpr.export_fits_an_email(export):
            logger.warning(
                "The export of contact %s is too large to email: %d bytes.",
                contact.id,
                len(export),
            )
            _tell_export_failed(contact, user, EXPORT_TOO_LARGE)
            return
        send_branded_email(
            template="contact_export_ready",
            subject="Contact export ready",
            to=[user.email],
            organization=contact.organization,
            context={"contact_name": contact.display_name, "contact_id": contact.id},
            attachments=[(f"contact-{contact.id}.zip", export, "application/zip")],
        )
    except Exception as exc:
        logger.exception("Failed to export contact %s", contact_id)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        _tell_export_failed(contact, user, EXPORT_ERROR)
