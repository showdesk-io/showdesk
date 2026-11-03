"""Proving a widget session's email by a code (email channel design §6.2).

The code route answers the same whatever is behind the address (Decision A), and
mails a code only when proving it would open conversations the session can't see.
"""

import hashlib
import hmac
from unittest import mock

import pytest
from django.core import mail
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.contacts.services import resolve_contact_for_widget_session
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
        session.email_verified_for = "a@x.io"
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
        code = OTPCode.generate(
            "a@x.io",
            purpose=OTPCode.Purpose.WIDGET_EMAIL,
            organization=org,
            widget_session=session,
        )

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


def _asking(org, email="a@x.io", **fields):
    """A session whose address holds a ticket it can't see, having asked for a code."""
    holder = Contact.objects.filter(organization=org, email=email).first()
    if holder is None:
        holder = ContactFactory(organization=org, email=email)
        _email_ticket(org, holder)
    session = WidgetSession.objects.create(organization=org, email=email, **fields)
    _post(org, CODE_URL, session)
    return session


class TestBoundCodes:
    def test_a_code_works_only_for_the_organization_and_session_that_asked(self, org):
        """Evil Inc. relays a code its own widget had mailed to the victim."""
        evil = OrganizationFactory()
        asking = _asking(evil)
        code = _code()
        _email_ticket(org, ContactFactory(organization=org, email="a@x.io"))
        attacker = WidgetSession.objects.create(organization=org, email="a@x.io")
        sibling = WidgetSession.objects.create(organization=evil, email="a@x.io")

        assert _post(org, VERIFY_URL, attacker, code=code).status_code == 400
        assert _post(evil, VERIFY_URL, sibling, code=code).status_code == 400
        assert _post(evil, VERIFY_URL, asking, code=code).data == {"verified": True}
        attacker.refresh_from_db()
        assert attacker.email_verified_at is None

    def test_another_session_asking_does_not_cancel_a_pending_code(self, org):
        asking = _asking(org)
        code = OTPCode.objects.get(widget_session=asking).code
        _asking(org)

        assert _post(org, VERIFY_URL, asking, code=code).data == {"verified": True}

    def test_a_verified_session_is_refused_the_same_way(self, org):
        session = _asking(org)
        code = _code()
        WidgetSession.objects.filter(pk=session.pk).update(
            email_verified_at=session.created_at, email_verified_for="a@x.io"
        )

        res = _post(org, VERIFY_URL, session, code=code)

        assert (res.status_code, res.data) == (
            400,
            {"error": "Invalid or expired code."},
        )


class TestRacingAnEmailChange:
    def test_a_code_proves_nothing_once_the_email_changed(self, org):
        session = _asking(org)
        real_redeem = OTPCode.redeem

        def redeem_then_patch(*args, **kwargs):
            otp = real_redeem(*args, **kwargs)
            WidgetSession.objects.filter(pk=session.pk).update(email="b@x.io")
            return otp

        with mock.patch.object(OTPCode, "redeem", side_effect=redeem_then_patch):
            res = _post(org, VERIFY_URL, session, code=_code())

        assert res.data == {"verified": False}
        session.refresh_from_db()
        assert (session.email, session.email_verified_at) == ("b@x.io", None)
        assert session.email_verified_for == ""

    def test_a_signature_proves_nothing_once_the_email_changed(self, org):
        ContactFactory(organization=org, email="a@x.io")
        session = WidgetSession.objects.create(organization=org, email="a@x.io")
        WidgetSession.objects.filter(pk=session.pk).update(email="b@x.io")

        resolve_contact_for_widget_session(session, email_verified=True)

        session.refresh_from_db()
        assert (session.email_verified_at, session.email_verified_for) == (None, "")


class TestCodeRouteTiming:
    def test_always_queues_one_task_and_decides_nothing_itself(self, org):
        holder = ContactFactory(organization=org, email="a@x.io")
        _email_ticket(org, holder)
        sessions = [
            WidgetSession.objects.create(organization=org, email=email)
            for email in ("a@x.io", "b@x.io", "unknown@x.io")
        ]
        with mock.patch("apps.tickets.views.send_widget_email_code") as task:
            for session in sessions:
                assert _post(org, CODE_URL, session).status_code == 202

        assert [c.args for c in task.delay.call_args_list] == [
            (str(s.pk), s.email) for s in sessions
        ]
        assert not OTPCode.objects.exists()

    def test_no_code_for_an_external_id_the_service_rejects(self, org):
        holder = ContactFactory(organization=org, email="a@x.io")
        _email_ticket(org, holder)
        session = WidgetSession.objects.create(
            organization=org, email="a@x.io", external_user_id="email:a@x.io"
        )

        _post(org, CODE_URL, session)

        assert mail.outbox == []


class TestCodeProofAndAnotherEmail:
    def test_an_init_declaring_another_email_is_a_logout(self, org):
        session = _asking(org)
        _post(org, VERIFY_URL, session, code=_code())

        same = _post(org, SESSION_URL, session_id=str(session.pk), email="A@x.io")
        other = _post(org, SESSION_URL, session_id=str(session.pk), email="b@x.io")

        assert same.data["session_id"] == str(session.pk)
        assert other.data["session_id"] != str(session.pk)
        session.refresh_from_db()
        assert session.email == "a@x.io"


@pytest.mark.django_db(transaction=True)
def test_the_migration_keeps_only_proofs_of_the_address_the_contact_holds():
    before = ("tickets", "0016_widgetsession_email_proof_source")
    executor = MigrationExecutor(connection)
    executor.migrate([before])
    state = executor.loader.project_state(before).apps
    Session = state.get_model("tickets", "WidgetSession")
    OldContact = state.get_model("contacts", "Contact")
    org = OrganizationFactory()
    holding = OldContact.objects.create(organization_id=org.pk, email="a@x.io")
    elsewhere = OldContact.objects.create(organization_id=org.pk, email="c@x.io")
    now = timezone.now()
    kept = Session.objects.create(
        organization_id=org.pk,
        contact_id=holding.pk,
        email=" A@x.io",
        email_verified_at=now,
        email_proof_source="signed",
    )
    dropped = Session.objects.create(
        organization_id=org.pk,
        contact_id=elsewhere.pk,
        email="b@x.io",
        email_verified_at=now,
        email_proof_source="signed",
    )
    unproven = Session.objects.create(organization_id=org.pk, email="d@x.io")
    try:
        executor = MigrationExecutor(connection)
        executor.migrate([("tickets", "0017_widgetsession_email_verified_for")])
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    rows = {
        row[0]: row[1:]
        for row in WidgetSession.objects.filter(organization=org).values_list(
            "pk", "email_verified_for", "email_proof_source", "email_verified_at"
        )
    }
    assert rows[kept.pk][:2] == ("a@x.io", "signed")
    assert rows[kept.pk][2] is not None
    assert rows[dropped.pk] == ("", "", None)
    assert rows[unproven.pk] == ("", "", None)


def _stale(org, **fields):
    """A session holding a date, but for an address it no longer has."""
    holder = Contact.objects.filter(organization=org, email="a@x.io").first()
    if holder is None:
        holder = ContactFactory(organization=org, email="a@x.io")
        _email_ticket(org, holder)
    return WidgetSession.objects.create(
        organization=org,
        email="a@x.io",
        email_verified_at=timezone.now(),
        email_verified_for="old@x.io",
        **fields,
    )


class TestAProofThatDoesNotHold:
    def test_can_still_ask_for_a_code_and_verify(self, org):
        session = _stale(org)

        _post(org, CODE_URL, session)
        res = _post(org, VERIFY_URL, session, code=_code())

        assert [m.to for m in mail.outbox] == [["a@x.io"]]
        assert res.data == {"verified": True}

    def test_a_patch_clears_it_even_with_the_same_email(self, org):
        session = _stale(org, email_proof_source=WidgetSession.ProofSource.CODE)

        APIClient().patch(
            SESSION_URL,
            {"email": "a@x.io"},
            format="json",
            HTTP_X_WIDGET_TOKEN=org.api_token,
            HTTP_X_WIDGET_SESSION=str(session.pk),
        )

        session.refresh_from_db()
        assert (session.email_verified_at, session.email_verified_for) == (None, "")
        assert session.email_proof_source == ""

    def test_a_resume_clears_it_even_with_the_same_email(self, org):
        session = _stale(org, email_proof_source=WidgetSession.ProofSource.CODE)

        res = _post(org, SESSION_URL, session_id=str(session.pk), email="a@x.io")

        assert res.data["session_id"] == str(session.pk)
        session.refresh_from_db()
        assert (session.email_verified_at, session.email_verified_for) == (None, "")


def test_a_late_code_does_not_relabel_a_signed_proof(org):
    """A verify that passed its guard before a signed proof landed."""
    from apps.tickets.views import _link_session_contact

    ContactFactory(organization=org, email="a@x.io")
    session = WidgetSession.objects.create(
        organization=org,
        email="a@x.io",
        email_verified_at=timezone.now(),
        email_verified_for="a@x.io",
        email_proof_source=WidgetSession.ProofSource.SIGNED,
    )

    _link_session_contact(org, session, code_proof=True)

    session.refresh_from_db()
    assert session.email_proof_source == WidgetSession.ProofSource.SIGNED


def test_a_failed_send_is_retried_with_the_same_code(org):
    holder = ContactFactory(organization=org, email="a@x.io")
    _email_ticket(org, holder)
    session = WidgetSession.objects.create(organization=org, email="a@x.io")

    with mock.patch(
        "apps.tickets.tasks.send_branded_email", side_effect=OSError
    ) as send:
        _post(org, CODE_URL, session)

    assert OTPCode.objects.filter(widget_session=session).count() == 1
    codes = {call.kwargs["context"]["code"] for call in send.call_args_list}
    assert send.call_count > 1
    assert len(codes) == 1
