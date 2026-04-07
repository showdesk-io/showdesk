"""Management command to send a test email."""

from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send a test email to verify SMTP configuration."

    def add_arguments(self, parser):
        parser.add_argument("recipient", help="Email address to send the test to.")

    def handle(self, *args, **options):
        recipient = options["recipient"]
        try:
            result = send_mail(
                subject="Showdesk test email",
                message="If you receive this, your email configuration is working.",
                from_email=None,  # uses DEFAULT_FROM_EMAIL
                recipient_list=[recipient],
                fail_silently=False,
            )
            self.stdout.write(self.style.SUCCESS(f"Email sent (result={result})."))
        except Exception as e:
            raise CommandError(f"Failed to send email: {e}")
