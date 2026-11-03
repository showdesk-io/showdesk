"""Proving a widget session's email by a code (email channel design §6.2).

The code route answers the same whatever is behind the address (Decision A), and
mails a code only when proving it would open conversations the session can't see.
"""

import hashlib
import hmac

import pytest
from django.core import mail
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.organizations.models import OTPCode
from apps.tickets.models import Ticket, WidgetSession
from tests.factories import (
    ContactFactory,
    OrganizationFactory,
    TicketFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db

CODE_URL = "/api/v1/tickets/widget_email_code/"
VERIFY_URL = "/api/v1/tickets/widget_email_verify/"
SESSION_URL = "/api/v1/tickets/widget_session/"


@pytest.fixture(autouse=True)
def _eager(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True


@pytest.fixture
def org():
    return OrganizationFactory()


def _post(org, url, session=None, **data):
    headers = {"HTTP_X_WIDGET_TOKEN": org.api_token}
    if session is not None:
        headers["HTTP_X_WIDGET_SESSION"] = str(session.pk)
    return APIClient().post(url, data, format="json", **headers)


def _email_ticket(org, contact):
    return TicketFactory(
        organization=org,
        contact=contact,
        source=Ticket.Source.EMAIL,
        requester=None,
        requester_email=contact.email,
        widget_session=None,
    )


def _code(email="a@x.io", purpose=OTPCode.Purpose.WIDGET_EMAIL) -> str:
    return (
        OTPCode.objects.filter(email=email, purpose=purpose, used_at__isnull=True)
        .latest("created_at")
        .code
    )


def _hash(secret: str, message: str) -> str:
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


class TestCodeRoute:
    def test_answers_the_same_whatever_is_behind_the_address(self, org):
        holder = ContactFactory(organization=org, email="a@x.io")
        _email_ticket(org, holder)
        ContactFactory(organization=org, email="b@x.io")
        answers = []
        for email in ("a@x.io", "b@x.io", "unknown@x.io"):
            session = WidgetSession.objects.create(organization=org, email=email)
            res = _post(org, CODE_URL, session)
            answers.append((res.status_code, res.data))

        assert answers == [answers[0]] * 3
        assert answers[0][0] == 202
        assert [message.to for message in mail.outbox] == [["a@x.io"]]
        assert _code() in mail.outbox[0].body

    def test_no_code_for_tickets_the_session_already_sees(self, org):
        holder = ContactFactory(organization=org, email="a@x.io")
        session = WidgetSession.objects.create(
            organization=org, email="a@x.io", contact=holder
        )
        TicketFactory(organization=org, contact=holder, widget_session=session)

        assert _post(org, CODE_URL, session).status_code == 202
        assert mail.outbox == []

    def test_no_code_for_a_proven_session(self, org):
        holder = ContactFactory(organization=org, email="a@x.io")
        _email_ticket(org, holder)
        session = WidgetSession.objects.create(
            organization=org, email="a@x.io", contact=holder
        )
        session.email_verified_at = session.created_at
        session.save()

        assert _post(org, CODE_URL, session).status_code == 202
        assert mail.outbox == []

    def test_more_than_the_limit_per_email_is_refused(self, org):
        statuses = [
            _post(
                org,
                CODE_URL,
                WidgetSession.objects.create(organization=org, email="a@x.io"),
            ).status_code
            for _ in range(6)
        ]
        assert statuses == [202] * 5 + [429]

    def test_does_not_cancel_a_pending_login_code(self, org):
        UserFactory(organization=org, email="a@x.io", role="agent")
        login = OTPCode.generate("a@x.io")
        holder = ContactFactory(organization=org, email="a@x.io")
        _email_ticket(org, holder)
        session = WidgetSession.objects.create(organization=org, email="a@x.io")

        _post(org, CODE_URL, session)

        assert OTPCode.redeem("a@x.io", login.code) is not None


class TestVerify:
    def _asked(self, org, **session_fields):
        holder = ContactFactory(organization=org, email="a@x.io")
        ticket = _email_ticket(org, holder)
        session = WidgetSession.objects.create(
            organization=org, email="a@x.io", **session_fields
        )
        _post(org, CODE_URL, session)
        return holder, ticket, session

    def test_a_right_code_proves_the_email(self, org):
        holder, _, session = self._asked(org)

        res = _post(org, VERIFY_URL, session, code=_code())

        assert (res.status_code, res.data) == (200, {"verified": True})
        session.refresh_from_db()
        assert session.contact_id == holder.pk
        assert session.email_verified_at is not None
        assert session.email_proof_source == WidgetSession.ProofSource.CODE

    def test_a_wrong_code_is_one_answer_whatever_the_cause(self, org):
        _, _, session = self._asked(org)
        unasked = WidgetSession.objects.create(organization=org, email="z@x.io")
        wrong = "000000" if _code() != "000000" else "111111"

        answers = {
            (res.status_code, str(res.data))
            for res in (
                _post(org, VERIFY_URL, session, code=wrong),
                _post(org, VERIFY_URL, unasked, code=wrong),
                _post(org, VERIFY_URL, session, code="not a code"),
            )
        }
        assert len(answers) == 1
        assert next(iter(answers))[0] == 400
        session.refresh_from_db()
        assert session.email_verified_at is None

    def test_a_login_code_does_not_verify_in_the_widget(self, org):
        _, _, session = self._asked(org)
        login = OTPCode.generate("a@x.io")

        res = _post(org, VERIFY_URL, session, code=login.code)

        assert res.status_code == 400
        session.refresh_from_db()
        assert session.email_verified_at is None

    def test_a_widget_code_does_not_log_in(self, org):
        UserFactory(organization=org, email="a@x.io", role="agent")
        self._asked(org)

        res = APIClient().post(
            "/api/v1/auth/verify-otp/",
            {"email": "a@x.io", "code": _code()},
            format="json",
        )

        assert res.status_code == 401

    def test_identified_session_takes_the_email_only_contacts_history(self, org):
        org.widget_secret = "s3cret"
        org.save()
        own = ContactFactory(organization=org, email="", external_id="u1")
        holder, ticket, session = self._asked(org, external_user_id="u1")

        res = _post(org, VERIFY_URL, session, code=_code())

        assert res.data == {"verified": True}
        assert not Contact.objects.filter(pk=holder.pk).exists()
        assert Ticket.objects.get(pk=ticket.pk).contact_id == own.pk

    def test_a_proof_that_does_not_stick_is_not_verified(self, org):
        """The identified session's contact holds another email: it proves nothing."""
        ContactFactory(organization=org, email="b@x.io", external_id="u1")
        holder = ContactFactory(organization=org, email="a@x.io")
        _email_ticket(org, holder)
        session = WidgetSession.objects.create(
            organization=org, email="a@x.io", external_user_id="u1"
        )
        code = OTPCode.generate("a@x.io", purpose=OTPCode.Purpose.WIDGET_EMAIL)

        res = _post(org, VERIFY_URL, session, code=code.code)

        assert res.data == {"verified": False}
        session.refresh_from_db()
        assert session.email_verified_at is None


class TestProofSource:
    @pytest.fixture
    def signing_org(self, org):
        org.widget_secret = "s3cret"
        org.save()
        return org

    def _resume(self, org, session, **body):
        return _post(org, SESSION_URL, session_id=str(session.pk), **body)

    def test_a_code_proof_survives_a_resume_with_no_hash(self, signing_org):
        org = signing_org
        holder = ContactFactory(organization=org, email="a@x.io")
        _email_ticket(org, holder)
        session = WidgetSession.objects.create(organization=org, email="a@x.io")
        _post(org, CODE_URL, session)
        _post(org, VERIFY_URL, session, code=_code())

        res = self._resume(org, session, email="a@x.io")

        assert res.data["session_id"] == str(session.pk)
        assert res.data["email_proof_offered"] is False

    def test_a_signed_proof_does_not(self, signing_org):
        org = signing_org
        res = _post(
            org,
            SESSION_URL,
            email="a@x.io",
            email_hash=_hash(org.widget_secret, "email:a@x.io"),
        )
        session = WidgetSession.objects.get(pk=res.data["session_id"])
        assert session.email_proof_source == WidgetSession.ProofSource.SIGNED

        res = self._resume(org, session, email="a@x.io")

        assert res.data["session_id"] != str(session.pk)

    def test_a_changed_email_drops_the_proof_and_its_source(self, org):
        holder = ContactFactory(organization=org, email="a@x.io")
        _email_ticket(org, holder)
        session = WidgetSession.objects.create(organization=org, email="a@x.io")
        _post(org, CODE_URL, session)
        _post(org, VERIFY_URL, session, code=_code())

        res = APIClient().patch(
            SESSION_URL,
            {"email": "b@x.io"},
            format="json",
            HTTP_X_WIDGET_TOKEN=org.api_token,
            HTTP_X_WIDGET_SESSION=str(session.pk),
        )

        assert res.data["email_proof_offered"] is True
        session.refresh_from_db()
        assert (session.email_verified_at, session.email_proof_source) == (None, "")

    def test_offered_for_any_unproven_email(self, org):
        res = _post(org, SESSION_URL, email="nobody@x.io")
        assert res.data["email_proof_offered"] is True
        res = _post(org, SESSION_URL)
        assert res.data["email_proof_offered"] is False
