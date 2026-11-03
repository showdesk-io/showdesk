"""Celery tasks of the email channel."""

from celery import shared_task


@shared_task
def process_inbound_email(inbound_id: str) -> None:
    """Run one stored mail through the pipeline. Safe to run again."""
