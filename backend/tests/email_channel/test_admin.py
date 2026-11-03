"""The admin of the email channel."""

import pytest
from django.urls import reverse

from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_inbound_emails_cannot_be_added_by_hand(client):
    # They are what a provider delivered: one made up would pass for a real mail.
    client.force_login(UserFactory(is_staff=True, is_superuser=True))

    response = client.get(reverse("admin:email_channel_inboundemail_add"))

    assert response.status_code == 403
