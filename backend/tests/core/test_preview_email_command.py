"""Tests for the ``preview_email`` management command."""

from io import StringIO

import pytest
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.management.commands.preview_email import SAMPLES
from tests.factories import OrganizationFactory


pytestmark = pytest.mark.django_db


def test_list_lists_every_sample_template():
    out = StringIO()
    call_command("preview_email", list=True, stdout=out)

    output = out.getvalue()
    for name in SAMPLES:
        assert name in output


def test_unknown_template_raises_command_error():
    with pytest.raises(CommandError):
        call_command("preview_email", "nope_not_a_template", to="x@example.com")


def test_missing_template_raises_command_error():
    with pytest.raises(CommandError):
        call_command("preview_email", to="x@example.com")


@pytest.mark.parametrize("template", sorted(SAMPLES))
def test_each_sample_renders_and_sends(template: str):
    """Every sample context must render both .html and .txt without error
    and produce an email with both bodies."""
    call_command("preview_email", template, to="preview@example.com")

    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == ["preview@example.com"]
    assert msg.subject.startswith("[PREVIEW] ")
    assert msg.body  # plain text alternative
    assert msg.alternatives, "missing HTML alternative"
    body, mimetype = msg.alternatives[0]
    assert mimetype == "text/html"
    assert body.startswith("<!DOCTYPE html>")


def test_org_flag_applies_org_branding():
    org = OrganizationFactory(
        slug="acme-preview",
        email_from_name="Acme Support",
        primary_color="#FF00AA",
    )

    call_command(
        "preview_email", "ticket_reply", to="preview@example.com", org=org.slug
    )

    msg = mail.outbox[0]
    assert "Acme Support" in msg.from_email
    html = msg.alternatives[0][0]
    assert "#FF00AA" in html or "#ff00aa" in html.lower()


def test_org_flag_with_unknown_slug_raises_command_error():
    with pytest.raises(CommandError):
        call_command(
            "preview_email",
            "otp_code",
            to="preview@example.com",
            org="does-not-exist",
        )
