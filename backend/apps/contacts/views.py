"""Views of the contacts API."""

import logging
import math
import re
import uuid
from datetime import UTC

from django.db import IntegrityError, transaction
from django.db.models import Count, F, Q
from django.db.models.fields.json import KeyTransform
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import get_active_org
from apps.tickets.models import Ticket

from .attributes import is_storable
from .models import Contact
from .permissions import IsOrganizationStaff, require_org_admin
from .serializers import (
    EMAIL_TAKEN,
    ContactNoteSerializer,
    ContactSerializer,
    ContactTicketSerializer,
)

logger = logging.getLogger(__name__)

OPEN_STATUSES = [Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS, Ticket.Status.WAITING]
TIMELINE_LIMIT = 100

_ATTRIBUTE_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_NUMBER = re.compile(r"-?[0-9]+(\.[0-9]+)?")


class ContactAnonymized(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This contact has been anonymized."
    default_code = "contact_anonymized"


class DirectoryPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


def _parse_dt(value: str | None):
    """Return ``value`` as an aware UTC datetime, or None if it can't be used.

    In UTC, as Postgres refuses the offsets beyond ±15:59 that Python accepts.
    """
    try:
        parsed = parse_datetime(value or "")
        if parsed is None:
            return None
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed)
        return parsed.astimezone(UTC)
    except (ValueError, OverflowError):
        return None


class NullsLastOrderingFilter(OrderingFilter):
    """``?ordering=`` in either direction, with NULLs last (Postgres puts them
    first on DESC, which would list never-seen contacts on top of the list).
    """

    def filter_queryset(self, request, queryset, view):
        ordering = self.get_ordering(request, queryset, view)
        if not ordering:
            return queryset
        return queryset.order_by(
            *(
                F(field[1:]).desc(nulls_last=True)
                if field.startswith("-")
                else F(field).asc(nulls_last=True)
                for field in ordering
            ),
            "id",
        )


def filter_by_attributes(queryset, params):
    """Apply the ``attr.<key>=<value>`` query params, by exact match on the top key.

    A key is matched by ``KeyTransform``, never spliced into a lookup, where
    ``attributes__has_key`` or ``attributes__a__gt`` would be a lookup or a JSON path.
    Keys that aren't identifiers without a double underscore are ignored. Query strings
    only hold text and attributes are typed, so a value also matches its typed reading.
    """
    for index, (param, value) in enumerate(params.items()):
        key = param.removeprefix("attr.")
        if key == param or "__" in key or not _ATTRIBUTE_KEY.fullmatch(key):
            continue
        if not is_storable(value):
            return queryset.none()  # Postgres can't even read it as a JSON value.
        alias = f"_attr_{index}"
        match = Q(**{alias: value})
        if value in ("true", "false"):
            match |= Q(**{alias: value == "true"})
        elif _NUMBER.fullmatch(value) and math.isfinite(float(value)):
            match |= Q(**{alias: float(value)})
        queryset = queryset.alias(**{alias: KeyTransform(key, "attributes")}).filter(
            match
        )
    return queryset


def timeline_tickets(tickets):
    """Return the rows ``ContactTicketSerializer`` shows, without an N+1."""
    return (
        tickets.select_related("requester", "assigned_agent")
        .prefetch_related("tags")
        .annotate(message_count=Count("messages"))
        .order_by("-updated_at", "-id")[:TIMELINE_LIMIT]
    )


def _lock_writable_contact(pk) -> Contact:
    """Return the contact's committed row, locked, unless it can't be written to.

    Same row lock as the identity service and the anonymization, so nothing read
    before an anonymization can write personal data back over it. Plain manager: the
    aggregates of ``get_queryset()`` can't be locked. For a transaction.
    """
    contact = Contact.objects.select_for_update(no_key=True).filter(pk=pk).first()
    if contact is None:
        raise NotFound
    if contact.is_anonymized:
        raise ContactAnonymized
    return contact


def _as_validation_error(exc: IntegrityError) -> ValidationError:
    """Turn a conflict the serializer's checks couldn't see coming into a 400."""
    if "unique_contact_email_per_org" in str(exc):
        return ValidationError({"email": [EMAIL_TAKEN]})
    # What's left is a company deleted since it was validated.
    logger.warning("Contact write refused by the database: %s", type(exc).__name__)
    return ValidationError({"non_field_errors": ["This contact could not be saved."]})


class OrgScopedMixin:
    permission_classes = [IsAuthenticated, IsOrganizationStaff]

    def get_serializer_context(self):
        return {
            **super().get_serializer_context(),
            "organization": get_active_org(self.request),
        }

    def perform_create(self, serializer):
        serializer.save(organization=get_active_org(self.request))

    def perform_destroy(self, instance):
        require_org_admin(self.request.user)
        instance.delete()


class ContactViewSet(OrgScopedMixin, viewsets.ModelViewSet):
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    serializer_class = ContactSerializer
    pagination_class = DirectoryPagination
    filter_backends = [SearchFilter, NullsLastOrderingFilter]
    search_fields = ["name", "email", "declared_email", "external_id"]
    ordering_fields = ["name", "email", "last_seen_at", "created_at"]
    # Not left to Meta.ordering, which Django drops from a query with a GROUP BY.
    ordering = ["-last_seen_at", "-created_at"]

    def get_queryset(self):
        return (
            Contact.objects.filter(organization=get_active_org(self.request))
            .select_related("company")
            .annotate(
                tickets_count=Count("tickets", distinct=True),
                open_tickets_count=Count(
                    "tickets",
                    filter=Q(tickets__status__in=OPEN_STATUSES),
                    distinct=True,
                ),
            )
        )

    def filter_queryset(self, queryset):
        # For the list only: ``get_object()`` goes through here too, and a query
        # string has no say in which contact a detail request is about.
        if self.action != "list":
            return queryset
        qs = super().filter_queryset(queryset)
        params = self.request.query_params
        if company := params.get("company"):
            try:
                qs = qs.filter(company_id=uuid.UUID(company))
            except ValueError:
                pass
        if (verified := params.get("email_verified")) in ("true", "false"):
            qs = qs.filter(email_verified_at__isnull=verified == "false")
        if after := _parse_dt(params.get("last_seen_after")):
            qs = qs.filter(last_seen_at__gte=after)
        if before := _parse_dt(params.get("last_seen_before")):
            qs = qs.filter(last_seen_at__lte=before)
        return filter_by_attributes(qs, params)

    def perform_create(self, serializer):
        try:
            with transaction.atomic():
                super().perform_create(serializer)
        except IntegrityError as exc:
            raise _as_validation_error(exc) from exc

    def update(self, request, *args, **kwargs):
        """Handle a PATCH (no PUT here): validate and write on the locked row."""
        pk = self.get_object().pk
        try:
            with transaction.atomic():
                contact = _lock_writable_contact(pk)
                serializer = self.get_serializer(
                    contact, data=request.data, partial=True
                )
                serializer.is_valid(raise_exception=True)
                serializer.save()
                # The response needs the ticket counts.
                data = self.get_serializer(self.get_queryset().get(pk=pk)).data
        except IntegrityError as exc:
            raise _as_validation_error(exc) from exc
        return Response(data)

    def perform_destroy(self, instance):
        require_org_admin(self.request.user)
        # Lock order everywhere: contact, then sessions. The delete nulls the
        # sessions' FK before removing the row, so taking the contact's lock only
        # then could deadlock with a session being resolved.
        with transaction.atomic():
            contact = Contact.objects.select_for_update().filter(pk=instance.pk).first()
            if contact is not None:
                contact.delete()

    @action(detail=True, methods=["get"])
    def tickets(self, request, pk=None):
        contact = self.get_object()
        tickets = timeline_tickets(
            contact.tickets.filter(organization_id=contact.organization_id)
        )
        return Response(ContactTicketSerializer(tickets, many=True).data)

    @action(detail=True, methods=["get", "post"])
    def notes(self, request, pk=None):
        contact = self.get_object()
        if request.method == "POST":
            serializer = ContactNoteSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            with transaction.atomic():
                serializer.save(
                    contact=_lock_writable_contact(contact.pk), author=request.user
                )
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        notes = contact.notes.select_related("author").order_by("-created_at", "-id")
        return Response(ContactNoteSerializer(notes, many=True).data)
