"""Views for ticket-related models."""

import logging

from django.core.exceptions import ValidationError
from django.db import DatabaseError, models, transaction
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.contacts.services import (
    resolve_contact_for_email,
    resolve_contact_for_widget_session,
)
from apps.core.permissions import get_active_org, has_feature
from apps.core.throttling import (
    WidgetMessageThrottle,
    WidgetSessionThrottle,
    WidgetSubmitThrottle,
    WidgetUploadThrottle,
)
from apps.notifications.signals import (
    notify_message_deleted,
    notify_new_message,
    notify_new_ticket,
    notify_ticket_update,
)
from apps.organizations.models import RESERVED_EXTERNAL_ID_PREFIXES, Organization

from .models import (
    CannedResponse,
    PriorityLevel,
    SavedView,
    Tag,
    Ticket,
    TicketAttachment,
    TicketMessage,
    WidgetSession,
)
from .serializers import (
    CannedResponseSerializer,
    PriorityLevelSerializer,
    SavedViewSerializer,
    SLAPolicySerializer,
    TagSerializer,
    TicketAttachmentSerializer,
    TicketCreateFromWidgetSerializer,
    TicketListSerializer,
    TicketMessageSerializer,
    TicketSerializer,
    WidgetConversationListSerializer,
    WidgetIdentitySerializer,
    WidgetMessageCreateSerializer,
    WidgetMessageSerializer,
    WidgetSessionSerializer,
)
from .tasks import (
    send_ticket_assigned_email,
    send_ticket_created_email,
    send_ticket_reply_email,
    send_ticket_resolved_email,
)

logger = logging.getLogger(__name__)

# In ``Ticket.context_metadata``: written anonymously, then moved to the session of
# a login. Its sender never counts as verified.
PRE_LOGIN_ANONYMOUS_KEY = "pre_login_anonymous"


def _get_widget_org(request):
    """Validate X-Widget-Token header and return the Organization.

    Returns (organization, None) on success, or (None, Response) on failure.
    """
    token = request.headers.get("X-Widget-Token")
    if not token:
        return None, Response(
            {"error": "Missing X-Widget-Token header."},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    try:
        org = Organization.objects.get(api_token=token, is_active=True)
    except Organization.DoesNotExist:
        return None, Response(
            {"error": "Invalid or inactive organization token."},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    # Stamp the first widget call so the onboarding wizard can flip from
    # "Waiting for first ping" to "Widget detected". Single UPDATE keyed on
    # the still-null state to avoid a race with concurrent first calls.
    if org.widget_first_seen_at is None:
        now = timezone.now()
        updated = Organization.objects.filter(
            pk=org.pk, widget_first_seen_at__isnull=True
        ).update(widget_first_seen_at=now)
        if updated:
            org.widget_first_seen_at = now
    return org, None


def _get_widget_session(request, organization):
    """Validate X-Widget-Session header and return the WidgetSession.

    Returns (session, None) on success, or (None, Response) on failure.
    """
    session_id = request.headers.get("X-Widget-Session")
    if not session_id:
        return None, Response(
            {"error": "Missing X-Widget-Session header."},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    try:
        session = WidgetSession.objects.get(id=session_id, organization=organization)
    except (WidgetSession.DoesNotExist, ValidationError):
        return None, Response(
            {"error": "Invalid session."},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    return session, None


def _record_session_resume(
    org, session, name: str, email: str, email_hash: str | None
) -> None:
    """Fill the session's blank name, update its email, and record the visit.

    A different email replaces the session's on an identified session, where the
    latest declared value wins, or if the host app signed it. An anonymous session
    otherwise keeps its first email. The proof was about the previous email: the
    service proves the new one again, if it can.

    Writes only what changes: saving a value read before a concurrent
    anonymization would restore the personal data it just wiped.
    """
    fields = ["last_seen_at", "updated_at"]
    if name and not session.name:
        session.name = name
        fields.append("name")
    if (
        email
        and email.lower() != session.email.strip().lower()
        and (
            not session.email
            or session.external_user_id
            or org.verify_email_hash(email, email_hash)
        )
    ):
        session.email = email
        fields.append("email")
        if session.email_verified_at:
            session.email_verified_at = None
            fields.append("email_verified_at")
    session.save(update_fields=fields)


def _company_hash_is_valid(org, company, company_hash) -> bool:
    if not company_hash or not isinstance(company, dict):
        return False
    company_id = company.get("id")
    # Same values the service accepts as an id, without str() on a huge integer.
    if type(company_id) is int and abs(company_id) < 2**63:
        company_id = str(company_id)
    return org.verify_company_hash(
        company_id, company.get("name"), company.get("domain"), company_hash
    )


def _contact_claims(identity) -> dict:
    """Pick from the validated payload what ``_link_session_contact`` takes."""
    keys = ("email_hash", "company_hash", "traits", "company")
    return {key: identity.get(key) for key in keys}


def _link_session_contact(
    org, session, *, email_hash=None, company_hash=None, traits=None, company=None
) -> None:
    """Resolve the session's contact from the widget init payload.

    All of it is validated ``WidgetIdentitySerializer`` data. ``email_hash`` and
    ``company_hash`` are optional: an invalid one is ignored (the value stays
    unsigned) so a misconfigured host app never breaks the widget. For the same
    reason a database error (a conflict the service's retry couldn't settle, a
    deadlock, a lock timeout) is logged, and the session goes on without a contact
    until the next init.
    """
    email_verified = bool(
        session.email
        and email_hash
        and org.verify_email_hash(session.email, email_hash)
    )
    previous_contact_id = session.contact_id
    try:
        # Together: the tickets only get linked when the contact changes, so a
        # contact committed without them would leave them unlinked for good.
        with transaction.atomic():
            resolve_contact_for_widget_session(
                session,
                email_verified=email_verified,
                traits=traits,
                company=company,
                company_verified=_company_hash_is_valid(org, company, company_hash),
            )
            # The normal flow is first message, then contact nudge: tickets opened
            # before the session had a contact would otherwise never get one. Only
            # then: on any other visit, a ticket without a contact is one an agent
            # cleared.
            if session.contact_id and session.contact_id != previous_contact_id:
                Ticket.objects.filter(
                    organization=org, widget_session=session, contact__isnull=True
                ).update(contact_id=session.contact_id)
    except DatabaseError:
        session.contact_id = previous_contact_id
        logger.exception("Could not link widget session %s to a contact", session.pk)


def _update_session(request, org, identity) -> Response:
    """PATCH: update the contact info (name/email) of an existing session."""
    session, err = _get_widget_session(request, org)
    if err:
        return err
    name = identity.get("name")
    email = identity.get("email")
    fields = ["last_seen_at", "updated_at"]
    if name is not None:
        session.name = name
        fields.append("name")
    if email is not None:
        # The proof was about the previous email.
        if email.lower() != session.email.strip().lower():
            session.email_verified_at = None
            fields.append("email_verified_at")
        session.email = email
        fields.append("email")
    session.save(update_fields=fields)
    # Backfill on linked tickets with blank requester info
    if session.name or session.email:
        update_fields = {}
        if session.name:
            update_fields["requester_name"] = session.name
        if session.email:
            update_fields["requester_email"] = session.email
        Ticket.objects.filter(
            widget_session=session,
            requester_name="",
        ).update(**update_fields)
    _link_session_contact(org, session, **_contact_claims(identity))
    return Response(WidgetSessionSerializer(session).data)


def _stored_session(org, session_id):
    """Return the session the widget stored, or None if it isn't one of this org."""
    if not isinstance(session_id, str):
        return None  # str() on a deeply nested list overflows the stack.
    try:
        return WidgetSession.objects.get(id=session_id, organization=org)
    except (WidgetSession.DoesNotExist, ValidationError):
        return None


def _move_conversation_to_identified_session(org, anonymous, identified) -> None:
    """Continue an anonymous session's conversations on the session of a login.

    Those tickets were written before anyone proved who they are, so they're marked
    as such for ``sender_verified``. Moved, there's nothing left to do on a retry.

    Not caught, unlike a contact that can't be linked: the widget has to keep the
    anonymous session's id for its next init, the only way to retry this.
    """
    with transaction.atomic():
        WidgetSession.objects.select_for_update(no_key=True).get(pk=anonymous.pk)
        tickets = list(
            Ticket.objects.select_for_update(no_key=True).filter(
                organization=org, widget_session=anonymous
            )
        )
        for ticket in tickets:
            ticket.widget_session = identified
            ticket.external_user_id = identified.external_user_id
            ticket.contact_id = identified.contact_id or ticket.contact_id
            metadata = ticket.context_metadata
            ticket.context_metadata = {
                **(metadata if isinstance(metadata, dict) else {}),
                PRE_LOGIN_ANONYMOUS_KEY: True,
            }
        Ticket.objects.bulk_update(
            tickets,
            ["widget_session", "external_user_id", "contact", "context_metadata"],
            batch_size=500,
        )
        TicketMessage.objects.filter(
            widget_session=anonymous, ticket__organization=org
        ).update(widget_session=identified)


def _create_or_resume_session(request, org, identity) -> Response:
    """POST: create a new session or resume an existing one.

    Only a valid ``user_hash`` gives access to an identified session. The session
    the widget stored then decides what happens:

    - Anonymous, no valid hash: it goes on, whatever the id sent.
    - Anonymous, valid hash: a login. The identified session replaces it, and takes
      its conversations.
    - Identified, valid hash: the user's own session, or the session of whoever
      logged in since on that browser.
    - Identified, hash absent: a logout. A new anonymous session starts, and the
      stored one isn't touched, so neither is its contact.
    - Identified, wrong hash: refused, as without a stored session.
    """
    stored = _stored_session(org, request.data.get("session_id"))
    external_user_id = identity.get("external_user_id") or ""
    user_hash = identity.get("user_hash") or ""
    name = identity.get("name") or ""
    email = identity.get("email") or ""
    claims = _contact_claims(identity)

    is_login = False
    if stored is not None and not stored.external_user_id:
        is_login = bool(
            external_user_id
            and user_hash
            and org.verify_user_hash(external_user_id, user_hash)
        )
        if not is_login:
            _record_session_resume(org, stored, name, email, claims["email_hash"])
            _link_session_contact(org, stored, **claims)
            return Response(WidgetSessionSerializer(stored).data)

    # HMAC-identified user: find-or-create by external_user_id
    if external_user_id and user_hash:
        if not org.widget_secret:
            return Response(
                {"error": "Identity verification not configured."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not org.verify_user_hash(external_user_id, user_hash):
            return Response(
                {"error": "Invalid user_hash."},
                status=status.HTTP_403_FORBIDDEN,
            )
        session, created = WidgetSession.objects.get_or_create(
            organization=org,
            external_user_id=external_user_id,
            defaults={
                "name": name,
                "email": email,
                "user_agent": request.META.get("HTTP_USER_AGENT", ""),
            },
        )
        if not created:
            _record_session_resume(org, session, name, email, claims["email_hash"])
        _link_session_contact(org, session, **claims)
        if is_login:
            _move_conversation_to_identified_session(org, stored, session)
        resp_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(WidgetSessionSerializer(session).data, status=resp_status)

    # Anonymous session
    session = WidgetSession.objects.create(
        organization=org,
        name=name,
        email=email,
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )
    _link_session_contact(org, session, **claims)
    return Response(
        WidgetSessionSerializer(session).data,
        status=status.HTTP_201_CREATED,
    )


class TicketViewSet(viewsets.ModelViewSet):
    """ViewSet for managing tickets.

    Supports full CRUD operations, filtering by status/priority/assignee,
    and a special widget submission endpoint.
    """

    permission_classes = [IsAuthenticated]
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = [
        "status",
        "priority",
        "assigned_agent",
        "assigned_team",
        "source",
        "tags",
        "external_user_id",
    ]
    search_fields = ["title", "description", "reference", "requester_email"]
    ordering_fields = ["created_at", "updated_at", "priority", "status"]

    def get_serializer_class(self):
        """Use list serializer for list action."""
        if self.action == "list":
            return TicketListSerializer
        return TicketSerializer

    def get_queryset(self):
        """Filter tickets by the active organization."""
        org = get_active_org(self.request)
        if org:
            return Ticket.objects.filter(organization=org)
        return Ticket.objects.none()

    def perform_create(self, serializer) -> None:
        """Set organization and reference on creation."""
        org = get_active_org(self.request)
        ticket = serializer.save(
            organization=org,
            reference=org.next_ticket_reference(),
        )
        # Notify via WebSocket + email
        try:
            notify_new_ticket(ticket)
        except Exception:
            logger.exception("WebSocket notification failed for %s", ticket.reference)
        send_ticket_created_email.delay(str(ticket.id))

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Return aggregated statistics for the current filtered queryset.

        Accepts the same filter params as the list endpoint (status, priority,
        assigned_agent, assigned_team, tags, search). Returns breakdowns by
        status, priority, and agent workload.
        """
        qs = self.filter_queryset(self.get_queryset())
        total = qs.count()

        # Status breakdown
        status_counts = dict(
            qs.values_list("status")
            .annotate(count=models.Count("id"))
            .values_list("status", "count")
        )

        # Priority breakdown
        priority_counts = dict(
            qs.values_list("priority")
            .annotate(count=models.Count("id"))
            .values_list("priority", "count")
        )

        # Agent workload (top agents by ticket count)
        agent_rows = (
            qs.filter(assigned_agent__isnull=False)
            .values(
                "assigned_agent",
                "assigned_agent__first_name",
                "assigned_agent__last_name",
                "assigned_agent__email",
            )
            .annotate(count=models.Count("id"))
            .order_by("-count")[:10]
        )
        agent_workload = [
            {
                "agent_id": str(row["assigned_agent"]),
                "name": f"{row['assigned_agent__first_name']} {row['assigned_agent__last_name']}".strip()
                or row["assigned_agent__email"],
                "count": row["count"],
            }
            for row in agent_rows
        ]
        unassigned = qs.filter(assigned_agent__isnull=True).count()

        # Average age in hours
        from django.db.models import Avg
        from django.db.models.functions import Now

        avg_age = qs.aggregate(avg_age=Avg(Now() - models.F("created_at")))["avg_age"]
        avg_age_hours = round(avg_age.total_seconds() / 3600, 1) if avg_age else 0

        return Response(
            {
                "total": total,
                "by_status": status_counts,
                "by_priority": priority_counts,
                "agent_workload": agent_workload,
                "unassigned": unassigned,
                "avg_age_hours": avg_age_hours,
            }
        )

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[AllowAny],
        throttle_classes=[WidgetSubmitThrottle],
    )
    def widget_submit(self, request):
        """Submit a ticket from the embeddable widget.

        Authenticates via organization API token passed in the
        X-Widget-Token header.
        """
        token = request.headers.get("X-Widget-Token")
        if not token:
            return Response(
                {"error": "Missing X-Widget-Token header."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            organization = Organization.objects.get(api_token=token, is_active=True)
        except Organization.DoesNotExist:
            return Response(
                {"error": "Invalid or inactive organization token."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        serializer = TicketCreateFromWidgetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = serializer.save(
            organization=organization,
            reference=organization.next_ticket_reference(),
            source=Ticket.Source.WIDGET,
        )

        if ticket.requester_email:
            try:
                contact = resolve_contact_for_email(
                    organization, ticket.requester_email, name=ticket.requester_name
                )
                if contact is not None:
                    ticket.contact = contact
                    ticket.save(update_fields=["contact"])
            except DatabaseError:
                # The ticket exists: failing here would lose its notifications.
                logger.exception("Could not link ticket %s to a contact", ticket.pk)

        # Notify via WebSocket + email
        try:
            notify_new_ticket(ticket)
        except Exception:
            logger.exception("WebSocket notification failed for %s", ticket.reference)
        send_ticket_created_email.delay(str(ticket.id))

        return Response(
            TicketSerializer(ticket).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[AllowAny],
        throttle_classes=[WidgetUploadThrottle],
        parser_classes=[MultiPartParser, FormParser],
    )
    def widget_upload_attachment(self, request):
        """Upload a file attachment from the widget.

        Authenticates via X-Widget-Token header.
        Expects multipart form data with `ticket` (UUID) and `file`.
        """
        token = request.headers.get("X-Widget-Token")
        if not token:
            return Response(
                {"error": "Missing X-Widget-Token header."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            organization = Organization.objects.get(api_token=token, is_active=True)
        except Organization.DoesNotExist:
            return Response(
                {"error": "Invalid or inactive organization token."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        ticket_id = request.data.get("ticket")
        uploaded_file = request.FILES.get("file")

        if not ticket_id or not uploaded_file:
            return Response(
                {"error": "Both 'ticket' and 'file' fields are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            ticket = Ticket.objects.get(id=ticket_id, organization=organization)
        except Ticket.DoesNotExist:
            return Response(
                {"error": "Ticket not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = TicketAttachmentSerializer(
            data={
                "ticket": str(ticket.id),
                "file": uploaded_file,
                "filename": uploaded_file.name,
                "content_type": uploaded_file.content_type
                or "application/octet-stream",
                "file_size": uploaded_file.size,
            }
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(uploaded_by=None)

        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(
        detail=False,
        methods=["get"],
        permission_classes=[AllowAny],
    )
    def widget_tickets(self, request):
        """Fetch tickets for a user from the widget.

        Authenticates via X-Widget-Token header.
        Requires ?external_user_id=xxx and ?user_hash=xxx query parameters.
        The user_hash is verified via HMAC-SHA256(widget_secret, external_user_id)
        to prevent enumeration of other users' tickets.
        """
        token = request.headers.get("X-Widget-Token")
        if not token:
            return Response(
                {"error": "Missing X-Widget-Token header."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            organization = Organization.objects.get(api_token=token, is_active=True)
        except Organization.DoesNotExist:
            return Response(
                {"error": "Invalid or inactive organization token."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        external_user_id = request.query_params.get("external_user_id")
        if not external_user_id:
            return Response(
                {"error": "external_user_id query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if external_user_id.startswith(RESERVED_EXTERNAL_ID_PREFIXES):
            return Response(
                {"error": "This external_user_id prefix is reserved."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # HMAC identity verification: require user_hash when widget_secret is set
        user_hash = request.query_params.get("user_hash")
        if not organization.widget_secret:
            return Response(
                {
                    "error": "Identity verification not configured. Generate a widget secret in Settings."
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        if not user_hash:
            return Response(
                {"error": "user_hash query parameter is required for ticket history."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not organization.verify_user_hash(external_user_id, user_hash):
            return Response(
                {"error": "Invalid user_hash."},
                status=status.HTTP_403_FORBIDDEN,
            )

        tickets = Ticket.objects.filter(
            organization=organization,
            external_user_id=external_user_id,
        ).order_by("-created_at")[:20]

        from .serializers import WidgetTicketListSerializer

        serializer = WidgetTicketListSerializer(tickets, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        """Assign a ticket to an agent or team."""
        ticket = self.get_object()
        agent_id = request.data.get("agent_id")
        team_id = request.data.get("team_id")

        if agent_id:
            ticket.assigned_agent_id = agent_id
        if team_id:
            ticket.assigned_team_id = team_id
        if not ticket.first_response_at and agent_id:
            ticket.first_response_at = timezone.now()

        ticket.status = Ticket.Status.IN_PROGRESS
        ticket.save()

        # Notify
        try:
            notify_ticket_update(ticket)
        except Exception:
            logger.exception("WebSocket notification failed for %s", ticket.reference)
        if agent_id:
            send_ticket_assigned_email.delay(str(ticket.id))

        return Response(TicketSerializer(ticket).data)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        """Mark a ticket as resolved."""
        ticket = self.get_object()
        ticket.status = Ticket.Status.RESOLVED
        ticket.resolved_at = timezone.now()
        ticket.save()

        # Notify
        try:
            notify_ticket_update(ticket)
        except Exception:
            logger.exception("WebSocket notification failed for %s", ticket.reference)
        send_ticket_resolved_email.delay(str(ticket.id))

        return Response(TicketSerializer(ticket).data)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        """Close a ticket."""
        ticket = self.get_object()
        ticket.status = Ticket.Status.CLOSED
        ticket.closed_at = timezone.now()
        ticket.save()

        try:
            notify_ticket_update(ticket)
        except Exception:
            logger.exception("WebSocket notification failed for %s", ticket.reference)

        return Response(TicketSerializer(ticket).data)

    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):
        """Reopen a resolved or closed ticket."""
        ticket = self.get_object()
        ticket.status = Ticket.Status.OPEN
        ticket.resolved_at = None
        ticket.closed_at = None
        ticket.save()

        try:
            notify_ticket_update(ticket)
        except Exception:
            logger.exception("WebSocket notification failed for %s", ticket.reference)

        return Response(TicketSerializer(ticket).data)

    @action(detail=True, methods=["post"])
    def set_tags(self, request, pk=None):
        """Set tags on a ticket (replaces existing tags)."""
        ticket = self.get_object()
        tag_ids = request.data.get("tag_ids", [])

        # Validate that tags belong to the same org
        tags = Tag.objects.filter(
            id__in=tag_ids,
            organization=ticket.organization,
        )
        ticket.tags.set(tags)

        try:
            notify_ticket_update(ticket)
        except Exception:
            logger.exception("WebSocket notification failed for %s", ticket.reference)

        return Response(TicketSerializer(ticket).data)

    @action(
        detail=False,
        methods=["post"],
        url_path="bulk_update",
        permission_classes=[IsAuthenticated, has_feature("bulk_actions")],
    )
    def bulk_update(self, request):
        """Apply a single update to many tickets at once.

        Body: ``{"ids": [uuid, ...], "status"?, "priority"?,
        "assigned_agent_id"? (uuid|null)}``. Tickets outside the active
        organization are silently dropped (they are filtered out by the
        org-scoped queryset). Status transitions update the lifecycle
        timestamps the way the per-ticket actions do.
        """
        from django.db import transaction

        ids = request.data.get("ids") or []
        if not isinstance(ids, list) or not ids:
            return Response(
                {"error": "Provide a non-empty 'ids' array."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_status = request.data.get("status")
        new_priority = request.data.get("priority")
        # assigned_agent_id may be:
        #   - omitted     -> leave assignee untouched
        #   - a uuid str  -> set to that agent (must be in this org)
        #   - explicit None -> unassign
        agent_provided = "assigned_agent_id" in request.data
        new_agent_id = request.data.get("assigned_agent_id")

        if new_status is None and new_priority is None and not agent_provided:
            return Response(
                {
                    "error": "At least one of status / priority / assigned_agent_id is required."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if new_status is not None and new_status not in Ticket.Status.values:
            return Response(
                {"error": f"Invalid status '{new_status}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        org = get_active_org(request)
        if new_agent_id:
            from apps.organizations.models import User

            agent_in_org = User.objects.filter(
                id=new_agent_id,
                organization=org,
                role__in=[User.Role.AGENT, User.Role.ADMIN],
                is_active=True,
            ).exists()
            if not agent_in_org:
                return Response(
                    {"error": "Assigned agent must belong to the active organization."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Org-scoped queryset already filters out anything outside the
        # active org, so a hostile or stale id list is a no-op rather
        # than a leak.
        tickets = list(self.get_queryset().filter(id__in=ids))
        if not tickets:
            return Response({"updated": 0, "ids": []})

        now = timezone.now()
        with transaction.atomic():
            for ticket in tickets:
                if new_priority is not None:
                    ticket.priority = new_priority
                if agent_provided:
                    ticket.assigned_agent_id = new_agent_id or None
                    if new_agent_id and not ticket.first_response_at:
                        ticket.first_response_at = now
                if new_status is not None:
                    ticket.status = new_status
                    if new_status == Ticket.Status.RESOLVED:
                        ticket.resolved_at = ticket.resolved_at or now
                    elif new_status == Ticket.Status.CLOSED:
                        ticket.closed_at = ticket.closed_at or now
                    elif new_status == Ticket.Status.OPEN:
                        ticket.resolved_at = None
                        ticket.closed_at = None
                ticket.save()

        for ticket in tickets:
            try:
                notify_ticket_update(ticket)
            except Exception:
                logger.exception(
                    "WebSocket notification failed for %s", ticket.reference
                )

        return Response({"updated": len(tickets), "ids": [str(t.id) for t in tickets]})

    # ------------------------------------------------------------------
    # Widget messaging endpoints (chat-style)
    # ------------------------------------------------------------------

    @action(
        detail=False,
        methods=["post", "patch"],
        permission_classes=[AllowAny],
        throttle_classes=[WidgetSessionThrottle],
        url_path="widget_session",
    )
    def widget_session(self, request):
        """Create, resume, or update a widget session.

        POST: Create a new session or resume an existing one.
        PATCH: Update contact info (name/email) on an existing session.
        """
        org, err = _get_widget_org(request)
        if err:
            return err

        serializer = WidgetIdentitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identity = serializer.validated_data

        if request.method == "PATCH":
            return _update_session(request, org, identity)
        return _create_or_resume_session(request, org, identity)

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[AllowAny],
        throttle_classes=[WidgetMessageThrottle],
        url_path="widget_message",
    )
    def widget_message(self, request):
        """Send a chat message from the widget.

        Creates a ticket on the first message (when ticket_id is null).
        Subsequent messages are appended to the existing ticket.
        """
        org, err = _get_widget_org(request)
        if err:
            return err
        session, err = _get_widget_session(request, org)
        if err:
            return err

        serializer = WidgetMessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        ticket_id = data.get("ticket_id")
        body = data.get("body", "")
        body_type = data.get("body_type", "text")
        context_data = data.get("context", {})

        # Create or retrieve ticket
        if ticket_id:
            try:
                ticket = Ticket.objects.get(
                    id=ticket_id,
                    organization=org,
                    widget_session=session,
                )
            except Ticket.DoesNotExist:
                return Response(
                    {"error": "Ticket not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )
        else:
            # First message — create ticket
            title = body[:100] if body else f"[{body_type.capitalize()}]"
            ticket = Ticket.objects.create(
                organization=org,
                reference=org.next_ticket_reference(),
                title=title,
                description=body,
                source=Ticket.Source.WIDGET,
                widget_session=session,
                contact_id=session.contact_id,
                requester_name=session.name,
                requester_email=session.email,
                external_user_id=session.external_user_id,
                context_url=context_data.get("url", ""),
                context_user_agent=context_data.get("user_agent", ""),
                context_os=context_data.get("os", ""),
                context_browser=context_data.get("browser", ""),
                context_screen_resolution=context_data.get("screen_resolution", ""),
                context_metadata={
                    k: v
                    for k, v in context_data.items()
                    if k
                    not in (
                        "url",
                        "user_agent",
                        "os",
                        "browser",
                        "screen_resolution",
                    )
                },
            )
            try:
                notify_new_ticket(ticket)
            except Exception:
                logger.exception(
                    "WebSocket notification failed for %s", ticket.reference
                )
            send_ticket_created_email.delay(str(ticket.id))

        # Create message
        message = TicketMessage.objects.create(
            ticket=ticket,
            widget_session=session,
            sender_type=TicketMessage.SenderType.USER,
            body=body,
            body_type=body_type,
        )

        try:
            notify_new_message(message)
        except Exception:
            logger.exception("WebSocket notification failed for message %s", message.id)

        return Response(
            {
                "ticket_id": str(ticket.id),
                "message_id": str(message.id),
                "reference": ticket.reference,
                "created_at": message.created_at.isoformat(),
            },
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[AllowAny],
        throttle_classes=[WidgetUploadThrottle],
        parser_classes=[MultiPartParser, FormParser],
        url_path="widget_message_attachment",
    )
    def widget_message_attachment(self, request):
        """Upload a media attachment as a chat message from the widget.

        Supports screenshots, audio messages, images, and video recordings.
        Creates a ticket on the first message if ticket_id is not provided.
        """
        org, err = _get_widget_org(request)
        if err:
            return err
        session, err = _get_widget_session(request, org)
        if err:
            return err

        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return Response(
                {"error": "'file' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ticket_id = request.data.get("ticket_id")
        body_type = request.data.get("body_type", "image")
        body = request.data.get("body", "")

        # Create or retrieve ticket
        if ticket_id:
            try:
                ticket = Ticket.objects.get(
                    id=ticket_id,
                    organization=org,
                    widget_session=session,
                )
            except Ticket.DoesNotExist:
                return Response(
                    {"error": "Ticket not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )
        else:
            title = body[:100] if body else f"[{body_type.capitalize()}]"
            ticket = Ticket.objects.create(
                organization=org,
                reference=org.next_ticket_reference(),
                title=title,
                description=body,
                source=Ticket.Source.WIDGET,
                widget_session=session,
                contact_id=session.contact_id,
                requester_name=session.name,
                requester_email=session.email,
                external_user_id=session.external_user_id,
            )
            try:
                notify_new_ticket(ticket)
            except Exception:
                logger.exception(
                    "WebSocket notification failed for %s", ticket.reference
                )
            send_ticket_created_email.delay(str(ticket.id))

        # Create message
        message = TicketMessage.objects.create(
            ticket=ticket,
            widget_session=session,
            sender_type=TicketMessage.SenderType.USER,
            body=body,
            body_type=body_type,
        )

        # Validate and save attachment
        att_serializer = TicketAttachmentSerializer(
            data={
                "ticket": str(ticket.id),
                "message": str(message.id),
                "file": uploaded_file,
                "filename": uploaded_file.name,
                "content_type": uploaded_file.content_type
                or "application/octet-stream",
                "file_size": uploaded_file.size,
            }
        )
        att_serializer.is_valid(raise_exception=True)
        att_serializer.save(uploaded_by=None)

        # For video uploads, also create VideoRecording
        if body_type == "video":
            from apps.videos.models import VideoRecording

            video = VideoRecording.objects.create(
                ticket=ticket,
                original_file=uploaded_file,
                status=VideoRecording.Status.UPLOADING,
                recording_type=request.data.get("recording_type", "screen"),
                has_audio=request.data.get("has_audio", "false").lower() == "true",
                has_camera=request.data.get("has_camera", "false").lower() == "true",
                mime_type=uploaded_file.content_type or "video/webm",
                file_size=uploaded_file.size,
            )
            from apps.videos.tasks import process_video

            process_video.delay(str(video.id))

        try:
            notify_new_message(message)
        except Exception:
            logger.exception("WebSocket notification failed for message %s", message.id)

        return Response(
            {
                "ticket_id": str(ticket.id),
                "message_id": str(message.id),
                "reference": ticket.reference,
                "attachment": att_serializer.data,
                "created_at": message.created_at.isoformat(),
            },
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=False,
        methods=["get"],
        permission_classes=[AllowAny],
        url_path="widget_conversation",
    )
    def widget_conversation(self, request):
        """Fetch messages for a specific conversation from the widget."""
        org, err = _get_widget_org(request)
        if err:
            return err
        session, err = _get_widget_session(request, org)
        if err:
            return err

        ticket_id = request.query_params.get("ticket_id")
        if not ticket_id:
            return Response(
                {"error": "ticket_id query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            ticket = Ticket.objects.get(
                id=ticket_id,
                organization=org,
                widget_session=session,
            )
        except (Ticket.DoesNotExist, ValueError):
            return Response(
                {"error": "Ticket not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        messages = (
            ticket.messages.filter(message_type=TicketMessage.MessageType.REPLY)
            .select_related("author", "widget_session")
            .prefetch_related("attachments")
            .order_by("created_at")
        )

        serializer = WidgetMessageSerializer(messages, many=True)
        return Response(
            {
                "ticket_id": str(ticket.id),
                "reference": ticket.reference,
                "status": ticket.status,
                "messages": serializer.data,
            }
        )

    @action(
        detail=False,
        methods=["get"],
        permission_classes=[AllowAny],
        url_path="widget_history",
    )
    def widget_history(self, request):
        """Fetch conversation history for the current widget session."""
        org, err = _get_widget_org(request)
        if err:
            return err
        session, err = _get_widget_session(request, org)
        if err:
            return err

        # Find tickets by session, or by external_user_id for cross-session history
        q = models.Q(widget_session=session)
        if session.external_user_id:
            q |= models.Q(
                external_user_id=session.external_user_id,
                organization=org,
            )

        tickets = Ticket.objects.filter(q).order_by("-updated_at")[:30]
        serializer = WidgetConversationListSerializer(tickets, many=True)
        return Response(serializer.data)

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[AllowAny],
        url_path="widget_mark_read",
    )
    def widget_mark_read(self, request):
        """Mark a widget conversation as read up to `now`.

        The end-user has just opened this ticket in the widget, so agent
        replies up to this moment are no longer unread.
        """
        org, err = _get_widget_org(request)
        if err:
            return err
        session, err = _get_widget_session(request, org)
        if err:
            return err

        ticket_id = request.data.get("ticket_id")
        if not ticket_id:
            return Response(
                {"error": "ticket_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            ticket = Ticket.objects.get(
                id=ticket_id,
                organization=org,
                widget_session=session,
            )
        except (Ticket.DoesNotExist, ValueError):
            return Response(
                {"error": "Ticket not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        ticket.widget_last_read_at = timezone.now()
        ticket.save(update_fields=["widget_last_read_at"])
        return Response({"ticket_id": str(ticket.id), "status": "ok"})

    @action(
        detail=False,
        methods=["delete"],
        permission_classes=[AllowAny],
        url_path="widget_message_delete",
    )
    def widget_message_delete(self, request):
        """Delete a user message from the widget.

        Only the session that created the message can delete it.
        Only user-sent messages can be deleted (not agent replies).
        """
        org, err = _get_widget_org(request)
        if err:
            return err
        session, err = _get_widget_session(request, org)
        if err:
            return err

        message_id = request.query_params.get("message_id")
        if not message_id:
            return Response(
                {"error": "message_id query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            message = TicketMessage.objects.get(
                id=message_id,
                widget_session=session,
                ticket__organization=org,
            )
        except (TicketMessage.DoesNotExist, ValueError):
            return Response(
                {"error": "Message not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if message.sender_type != TicketMessage.SenderType.USER:
            return Response(
                {"error": "Only user messages can be deleted."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Keep references before deleting
        ticket = message.ticket
        deleted_message_id = str(message.id)

        # Delete associated attachments (files on storage) and the message
        message.attachments.all().delete()
        message.delete()

        try:
            notify_message_deleted(ticket, deleted_message_id)
        except Exception:
            logger.exception(
                "WebSocket notification failed for deleted message %s",
                deleted_message_id,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)


class TicketMessageViewSet(viewsets.ModelViewSet):
    """ViewSet for managing ticket messages."""

    serializer_class = TicketMessageSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter messages by the active organization's tickets."""
        org = get_active_org(self.request)
        if org:
            return TicketMessage.objects.filter(ticket__organization=org)
        return TicketMessage.objects.none()

    def perform_create(self, serializer) -> None:
        """Set author on creation and send notifications."""
        message = serializer.save(author=self.request.user)

        # WebSocket notification
        try:
            notify_new_message(message)
        except Exception:
            logger.exception("WebSocket notification failed for message %s", message.id)

        # Email notification (async via Celery)
        send_ticket_reply_email.delay(str(message.id))

    def perform_destroy(self, instance) -> None:
        """Delete message and send WebSocket notification."""
        ticket = instance.ticket
        message_id = str(instance.id)
        instance.delete()
        try:
            notify_message_deleted(ticket, message_id)
        except Exception:
            logger.exception(
                "WebSocket notification failed for deleted message %s", message_id
            )


class TicketAttachmentViewSet(viewsets.ModelViewSet):
    """ViewSet for managing ticket attachments."""

    serializer_class = TicketAttachmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter attachments by the active organization's tickets."""
        org = get_active_org(self.request)
        if org:
            return TicketAttachment.objects.filter(ticket__organization=org)
        return TicketAttachment.objects.none()

    def perform_create(self, serializer) -> None:
        """Set uploaded_by on creation."""
        serializer.save(uploaded_by=self.request.user)


class TagViewSet(viewsets.ModelViewSet):
    """ViewSet for managing tags."""

    serializer_class = TagSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter tags by the active organization."""
        org = get_active_org(self.request)
        if org:
            return Tag.objects.filter(organization=org)
        return Tag.objects.none()

    def perform_create(self, serializer) -> None:
        """Set organization from the active org."""
        serializer.save(organization=get_active_org(self.request))


class PriorityLevelViewSet(viewsets.ModelViewSet):
    """ViewSet for managing custom priority levels."""

    serializer_class = PriorityLevelSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter priority levels by the active organization."""
        org = get_active_org(self.request)
        if org:
            return PriorityLevel.objects.filter(organization=org)
        return PriorityLevel.objects.none()

    def perform_create(self, serializer) -> None:
        """Set organization from the active org."""
        serializer.save(organization=get_active_org(self.request))


class SLAPolicyViewSet(viewsets.ModelViewSet):
    """CRUD for ``SLAPolicy`` rows, scoped to the active organization.

    Admins can create/update/delete; agents can read only. Per-priority
    uniqueness is enforced at the model level (``unique_together``).

    Gated behind the ``sla_policies`` feature flag (Cloud Business+).
    """

    serializer_class = SLAPolicySerializer
    permission_classes = [IsAuthenticated, has_feature("sla_policies")]

    def get_queryset(self):
        org = get_active_org(self.request)
        if org:
            from .models import SLAPolicy

            return SLAPolicy.objects.filter(organization=org)
        from .models import SLAPolicy

        return SLAPolicy.objects.none()

    def _require_admin(self) -> None:
        from rest_framework.exceptions import PermissionDenied

        from apps.organizations.models import User

        user = self.request.user
        if user.role != User.Role.ADMIN and not user.is_superuser:
            raise PermissionDenied("Only admins can manage SLA policies.")

    def perform_create(self, serializer) -> None:
        self._require_admin()
        serializer.save(organization=get_active_org(self.request))

    def perform_update(self, serializer) -> None:
        self._require_admin()
        serializer.save()

    def perform_destroy(self, instance) -> None:
        self._require_admin()
        instance.delete()


class SavedViewViewSet(viewsets.ModelViewSet):
    """ViewSet for managing saved ticket filter views.

    Returns views owned by the current user plus shared views from the
    same organization. Only the creator can update or delete a view.
    """

    serializer_class = SavedViewSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Return personal views + shared views from the active org."""
        user = self.request.user
        org = get_active_org(self.request)
        if org:
            return SavedView.objects.filter(
                organization=org,
            ).filter(
                models.Q(created_by=user) | models.Q(is_shared=True),
            )
        return SavedView.objects.none()

    def perform_create(self, serializer) -> None:
        """Set organization and creator."""
        serializer.save(
            organization=get_active_org(self.request),
            created_by=self.request.user,
        )

    def perform_update(self, serializer) -> None:
        """Only the creator can update a saved view."""
        if serializer.instance.created_by != self.request.user:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You can only edit your own saved views.")
        serializer.save()

    def perform_destroy(self, instance) -> None:
        """Only the creator can delete a saved view."""
        if instance.created_by != self.request.user:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You can only delete your own saved views.")
        instance.delete()


class CannedResponseViewSet(viewsets.ModelViewSet):
    """ViewSet for managing reusable reply templates.

    Returns templates owned by the current user plus shared templates from
    the same organization. Only the creator can update or delete a template.
    """

    serializer_class = CannedResponseSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "shortcut", "body"]

    def get_queryset(self):
        """Return personal templates + shared templates from the active org."""
        user = self.request.user
        org = get_active_org(self.request)
        if org:
            return CannedResponse.objects.filter(
                organization=org,
            ).filter(
                models.Q(created_by=user) | models.Q(is_shared=True),
            )
        return CannedResponse.objects.none()

    def perform_create(self, serializer) -> None:
        """Set organization and creator."""
        serializer.save(
            organization=get_active_org(self.request),
            created_by=self.request.user,
        )

    def perform_update(self, serializer) -> None:
        """Only the creator can update a canned response."""
        if serializer.instance.created_by != self.request.user:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied(
                "You can only edit your own canned responses.",
            )
        serializer.save()

    def perform_destroy(self, instance) -> None:
        """Only the creator can delete a canned response."""
        if instance.created_by != self.request.user:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied(
                "You can only delete your own canned responses.",
            )
        instance.delete()

    @action(detail=True, methods=["post"], url_path="record-use")
    def record_use(self, request, pk=None):
        """Increment usage_count when a template is inserted."""
        instance = self.get_object()
        CannedResponse.objects.filter(pk=instance.pk).update(
            usage_count=models.F("usage_count") + 1,
        )
        instance.refresh_from_db()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)
