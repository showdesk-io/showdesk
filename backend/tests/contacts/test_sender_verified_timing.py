"""A session's proof only speaks for what it wrote after giving it."""

import hashlib
import hmac
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.tickets.models import Ticket, WidgetSession
from tests.factories import ContactFactory, OrganizationFactory, TicketFactory

pytestmark = pytest.mark.django_db
SESSION_URL = "/api/v1/tickets/widget_session/"
MESSAGE_URL = "/api/v1/tickets/widget_message/"
EMAIL = "alice@x.io"


def _sign(value: str) -> str:
    return hmac.new(b"s3cret", value.encode(), hashlib.sha256).hexdigest()


EMAIL_HASH = _sign(f"email:{EMAIL}")


@pytest.fixture
def org():
    return OrganizationFactory(widget_secret="s3cret")


def _init(api_client, org, **body):
    return api_client.post(
        SESSION_URL, body, format="json", HTTP_X_WIDGET_TOKEN=str(org.api_token)
    )


def _write(api_client, org, session_id) -> Ticket:
    res = api_client.post(
        MESSAGE_URL,
        {"body": "Hello"},
        format="json",
        HTTP_X_WIDGET_TOKEN=str(org.api_token),
        HTTP_X_WIDGET_SESSION=str(session_id),
    )
    assert res.status_code == 201
    return Ticket.objects.get(pk=res.data["ticket_id"])


def _verified(ticket) -> bool | None:
    return Ticket.objects.get(pk=ticket.pk).sender_verified


def _proven_session(api_client, org) -> WidgetSession:
    res = _init(api_client, org, email=EMAIL, email_hash=EMAIL_HASH)
    return WidgetSession.objects.get(pk=res.data["session_id"])


class TestEmailProof:
    def test_ticket_written_before_the_proof_stays_unverified(self, api_client, org):
        res = _init(api_client, org, email=EMAIL)
        session_id = res.data["session_id"]
        earlier = _write(api_client, org, session_id)
        assert _verified(earlier) is False

        res = _init(
            api_client, org, session_id=session_id, email=EMAIL, email_hash=EMAIL_HASH
        )

        assert res.data["session_id"] == session_id
        assert _verified(earlier) is False
        assert _verified(_write(api_client, org, session_id)) is True

    @pytest.mark.parametrize(
        ("offset", "expected"), [(-1, False), (0, True), (1, True)]
    )
    def test_compares_the_ticket_with_the_date_of_the_proof(
        self, org, offset, expected
    ):
        now = timezone.now()
        contact = ContactFactory(organization=org, email=EMAIL)
        session = WidgetSession.objects.create(
            organization=org, contact=contact, email=EMAIL, email_verified_at=now
        )
        ticket = TicketFactory(
            organization=org, contact=contact, widget_session=session, requester=None
        )
        Ticket.objects.filter(pk=ticket.pk).update(
            created_at=now + timedelta(seconds=offset)
        )
        assert _verified(ticket) is expected

    def test_another_init_doesnt_move_the_date_of_the_proof(self, api_client, org):
        session = _proven_session(api_client, org)
        ticket = _write(api_client, org, session.id)
        proven_at = session.email_verified_at

        _init(
            api_client,
            org,
            session_id=str(session.id),
            email=EMAIL,
            email_hash=EMAIL_HASH,
        )

        session.refresh_from_db()
        assert session.email_verified_at == proven_at
        assert _verified(ticket) is True


class TestResumingAProvenSession:
    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"email": EMAIL},
            {"email": EMAIL, "email_hash": "forged"},
            {"email": "other@x.io", "email_hash": EMAIL_HASH},
        ],
        ids=["nothing", "unsigned", "forged", "signature-of-another-email"],
    )
    def test_without_a_valid_signature_is_a_logout(self, api_client, org, payload):
        session = _proven_session(api_client, org)
        proven_at = session.email_verified_at
        contact_id = session.contact_id
        ticket = _write(api_client, org, session.id)

        res = _init(api_client, org, session_id=str(session.id), **payload)

        assert res.status_code == 201
        assert res.data["session_id"] != str(session.id)
        new_session = WidgetSession.objects.get(pk=res.data["session_id"])
        assert new_session.email_verified_at is None
        assert not new_session.tickets.exists()
        # The stored one isn't touched: what it proved stays true of what it wrote.
        session.refresh_from_db()
        assert session.email == EMAIL
        assert session.email_verified_at == proven_at
        assert session.contact_id == contact_id
        assert _verified(ticket) is True

    def test_what_is_written_after_the_logout_isnt_verified(self, api_client, org):
        session = _proven_session(api_client, org)
        res = _init(api_client, org, session_id=str(session.id), email=EMAIL)
        assert _verified(_write(api_client, org, res.data["session_id"])) is False

    @pytest.mark.parametrize(
        "payload",
        [
            {"email": EMAIL, "email_hash": EMAIL_HASH},
            {"email": "ALICE@x.io", "email_hash": EMAIL_HASH},
            {"email_hash": EMAIL_HASH},
        ],
        ids=["signed", "other-case", "email-left-out"],
    )
    def test_signing_on_every_init_keeps_the_session(self, api_client, org, payload):
        session = _proven_session(api_client, org)
        ticket = _write(api_client, org, session.id)
        for _ in range(2):
            res = _init(api_client, org, session_id=str(session.id), **payload)
            assert res.status_code == 200
            assert res.data["session_id"] == str(session.id)
        assert _verified(ticket) is True
        assert _verified(_write(api_client, org, session.id)) is True

    def test_a_signed_other_email_keeps_the_session_on_a_new_proof(
        self, api_client, org
    ):
        session = _proven_session(api_client, org)
        ticket = _write(api_client, org, session.id)
        res = _init(
            api_client,
            org,
            session_id=str(session.id),
            email="new@x.io",
            email_hash=_sign("email:new@x.io"),
        )
        assert res.data["session_id"] == str(session.id)
        assert _verified(ticket) is False  # It was written by the previous email.
        assert _verified(_write(api_client, org, session.id)) is True

    def test_an_unproven_session_still_resumes_unsigned(self, api_client, org):
        res = _init(api_client, org, email=EMAIL)
        again = _init(api_client, org, session_id=res.data["session_id"], email=EMAIL)
        assert again.status_code == 200
        assert again.data["session_id"] == res.data["session_id"]

    def test_a_wrong_user_hash_is_refused(self, api_client, org):
        """Nothing else proves anything: same answer as on an identified session."""
        session = _proven_session(api_client, org)
        res = _init(
            api_client,
            org,
            session_id=str(session.id),
            external_user_id="u1",
            user_hash="wrong",
        )
        assert res.status_code == 403

    def test_a_valid_user_hash_is_a_login(self, api_client, org):
        session = _proven_session(api_client, org)
        ticket = _write(api_client, org, session.id)
        res = _init(
            api_client,
            org,
            session_id=str(session.id),
            external_user_id="u1",
            user_hash=_sign("u1"),
        )
        assert res.status_code == 201
        ticket.refresh_from_db()
        assert str(ticket.widget_session_id) == res.data["session_id"]
        assert ticket.sender_verified is False


class TestIdentifiedSession:
    def test_ticket_written_after_identification_is_verified(self, api_client, org):
        res = _init(api_client, org, external_user_id="u1", user_hash=_sign("u1"))
        ticket = _write(api_client, org, res.data["session_id"])
        assert _verified(ticket) is True

    def test_ticket_written_before_the_login_stays_unverified(self, api_client, org):
        anonymous = _init(api_client, org, email=EMAIL).data["session_id"]
        earlier = _write(api_client, org, anonymous)

        res = _init(
            api_client,
            org,
            session_id=anonymous,
            external_user_id="u1",
            user_hash=_sign("u1"),
        )

        earlier.refresh_from_db()
        assert str(earlier.widget_session_id) == res.data["session_id"]
        assert earlier.sender_verified is False
        assert _verified(_write(api_client, org, res.data["session_id"])) is True
