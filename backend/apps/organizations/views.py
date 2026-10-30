"""Views for organization-related models."""

import logging
import uuid

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.email import send_branded_email
from apps.core.permissions import (
    IsOrgAdmin,
    IsOrgAdminOrReadOnly,
    IsOrgStaff,
    IsPlatformAdmin,
    get_active_org,
    is_org_admin,
    require_active_org,
)

from . import services
from .models import (
    Organization,
    OrganizationDomain,
    OrgJoinRequest,
    OTPCode,
    Team,
    User,
)
from .serializers import (
    InviteAgentSerializer,
    OrganizationDomainSerializer,
    OrganizationSerializer,
    OrgJoinRequestSerializer,
    PlatformOrganizationCreateSerializer,
    PlatformOrganizationDetailSerializer,
    PlatformOrganizationListSerializer,
    TeamSerializer,
    UserSerializer,
)

logger = logging.getLogger(__name__)


class OrganizationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """The active organization. Creating and deleting are platform routes."""

    serializer_class = OrganizationSerializer
    permission_classes = [IsAuthenticated, IsOrgStaff]

    # All that agents may write: the wizard's progress, not the settings.
    AGENT_WRITABLE_FIELDS = frozenset({"onboarding_step", "onboarding_completed_at"})

    # Fields that require the ``custom_branding`` feature flag to mutate.
    # Read-only orgs (free plan) keep the defaults (Showdesk brand) but
    # cannot edit them; the API returns 403 the moment they try.
    BRANDING_WRITABLE_FIELDS = ("logo", "primary_color", "email_from_name")

    def get_queryset(self):
        """Filter organizations by the active organization."""
        org = get_active_org(self.request)
        if org:
            return Organization.objects.filter(id=org.id)
        return Organization.objects.none()

    def update(self, request, *args, **kwargs):
        self._reject_writes_by_agents(request)
        self._reject_branding_writes_without_flag(request)
        return super().update(request, *args, **kwargs)

    def _reject_writes_by_agents(self, request) -> None:
        if is_org_admin(request.user):
            return
        fields = set(request.data)
        if not fields or fields - self.AGENT_WRITABLE_FIELDS:
            raise PermissionDenied("Only admins can change the organization.")

    def _reject_branding_writes_without_flag(self, request) -> None:
        org = get_active_org(request)
        if org is None or org.has_feature("custom_branding"):
            return
        # Touched any branding field? -- raise a clean 403.
        touched = [f for f in self.BRANDING_WRITABLE_FIELDS if f in request.data]
        if touched:
            raise PermissionDenied(
                "Custom branding is not included in your plan. "
                f"Fields requiring it: {', '.join(touched)}."
            )

    @action(detail=True, methods=["post"])
    def regenerate_token(self, request, pk=None):
        """Regenerate the organization's widget API token."""
        org = self.get_object()
        if request.user.role != User.Role.ADMIN and not request.user.is_superuser:
            return Response(
                {"error": "Only admins can regenerate the API token."},
                status=status.HTTP_403_FORBIDDEN,
            )
        org.api_token = uuid.uuid4()
        org.save(update_fields=["api_token"])
        return Response(self.get_serializer(org).data)

    @action(detail=True, methods=["post"])
    def revoke_credentials(self, request, pk=None):
        """Revoke and regenerate both API token and widget secret.

        This is an irreversible action: the old token and secret stop
        working immediately. The client must update their integration code.
        """
        org = self.get_object()
        if request.user.role != User.Role.ADMIN and not request.user.is_superuser:
            return Response(
                {"error": "Only admins can revoke credentials."},
                status=status.HTTP_403_FORBIDDEN,
            )
        org.api_token = uuid.uuid4()
        org.widget_secret = Organization.generate_widget_secret()
        org.save(update_fields=["api_token", "widget_secret"])
        return Response(self.get_serializer(org).data)


# What anybody may change on their own row.
SELF_EDITABLE_USER_FIELDS = frozenset(
    {"first_name", "last_name", "avatar", "phone", "timezone", "is_available"}
)
# What nobody may change on their own row, admins and superusers included.
NEVER_SELF_EDITABLE_USER_FIELDS = frozenset({"role", "is_active"})


def _check_user_edit(actor: User, target: User, changed: set[str]) -> None:
    """Refuse an update of ``target`` that ``actor`` isn't entitled to."""
    if target.is_superuser and not actor.is_superuser:
        raise PermissionDenied("Only a superuser can change a superuser.")
    if actor.pk != target.pk:
        if not is_org_admin(actor):
            raise PermissionDenied("Only admins can change other users.")
        return
    if is_org_admin(actor):
        refused = changed & NEVER_SELF_EDITABLE_USER_FIELDS
    else:
        refused = changed - SELF_EDITABLE_USER_FIELDS
    if refused:
        raise PermissionDenied(
            f"You cannot change your own {', '.join(sorted(refused))}."
        )


def _check_keeps_an_admin(target: User) -> None:
    """Refuse to take away the last active admin of ``target``'s organization.

    Call it in a transaction, before the change: the row locks make concurrent
    removals of two admins wait for each other. A superuser that holds an admin
    role in the organization doesn't count: it isn't one of its own admins.
    """
    if (
        target.is_superuser
        or target.role != User.Role.ADMIN
        or not target.is_active
        or target.organization_id is None
    ):
        return
    admins = User.objects.select_for_update().filter(
        organization_id=target.organization_id,
        role=User.Role.ADMIN,
        is_active=True,
        is_superuser=False,
    )
    if not [admin for admin in admins if admin.pk != target.pk]:
        raise ValidationError(
            {"error": "An organization needs at least one active admin."}
        )


class UserViewSet(viewsets.ModelViewSet):
    """Users of the active organization.

    Agents read their colleagues and edit their own profile. The rest is for
    admins of the organization and superusers.
    """

    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated, IsOrgStaff]

    def get_permissions(self):
        if self.action in ("create", "destroy"):
            return [IsAuthenticated(), IsOrgAdmin()]
        return super().get_permissions()

    def get_queryset(self):
        """Filter users by the current user's organization.

        Superusers with an org see their org's users.
        Superusers without an org see no users (use platform admin endpoints).
        Supports ?role=agent|admin|end_user filtering.
        """
        org = get_active_org(self.request)
        if org:
            qs = User.objects.filter(organization=org)
        else:
            qs = User.objects.none()

        role = self.request.query_params.get("role")
        if role:
            if role == "agent":
                qs = qs.filter(role__in=[User.Role.AGENT, User.Role.ADMIN])
            else:
                qs = qs.filter(role=role)
        return qs

    def perform_create(self, serializer) -> None:
        """Create the user in the active organization."""
        serializer.save(organization=require_active_org(self.request))

    def perform_update(self, serializer) -> None:
        target = serializer.instance
        changed = {
            name
            for name, value in serializer.validated_data.items()
            if getattr(target, name) != value
        }
        _check_user_edit(self.request.user, target, changed)
        removes_admin = serializer.validated_data.get(
            "role", target.role
        ) != User.Role.ADMIN or not serializer.validated_data.get(
            "is_active", target.is_active
        )
        with transaction.atomic():
            if removes_admin:
                _check_keeps_an_admin(target)
            serializer.save()

    def perform_destroy(self, instance: User) -> None:
        if instance.is_superuser and not self.request.user.is_superuser:
            raise PermissionDenied("Only a superuser can delete a superuser.")
        with transaction.atomic():
            _check_keeps_an_admin(instance)
            instance.delete()

    # End users have no agents' routes, but they do have an account.
    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def me(self, request):
        """Return the currently authenticated user."""
        return Response(UserSerializer(request.user).data)

    @action(detail=False, methods=["post"])
    def invite(self, request):
        """Invite a new agent to the current organization.

        Creates the user with an unusable password. They log in via OTP.
        Sends an invitation email.

        Returns 409 if the email is already used by any user on the platform
        (one human = one org rule).
        """
        if request.user.role != User.Role.ADMIN and not request.user.is_superuser:
            return Response(
                {"error": "Only admins can invite agents."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = InviteAgentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        org = get_active_org(request)
        if not org:
            return Response(
                {"error": "No active organization."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        email = serializer.validated_data["email"]
        if User.objects.filter(email__iexact=email).exists():
            return Response(
                {
                    "detail": (
                        "This email is already used on Showdesk. "
                        "Ask your teammate to use a different address."
                    ),
                    "code": "email_taken",
                },
                status=status.HTTP_409_CONFLICT,
            )
        user = User.objects.create(
            email=email,
            first_name=serializer.validated_data.get("first_name", ""),
            last_name=serializer.validated_data.get("last_name", ""),
            role=serializer.validated_data.get("role", User.Role.AGENT),
            organization=org,
        )
        user.set_unusable_password()
        user.save()

        try:
            send_branded_email(
                template="agent_invitation",
                subject=f"You've been invited to {org.name} on Showdesk",
                to=[user.email],
                organization=org,
                context={
                    "first_name": user.first_name,
                    "email": user.email,
                    "org_name": org.name,
                    "login_url": f"{getattr(settings, 'SITE_URL', '')}/login",
                },
                fail_silently=True,
            )
        except Exception:
            logger.exception("Failed to send invitation email to %s", user.email)

        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def toggle_active(self, request, pk=None):
        """Activate or deactivate a user."""
        if request.user.role != User.Role.ADMIN and not request.user.is_superuser:
            return Response(
                {"error": "Only admins can change user status."},
                status=status.HTTP_403_FORBIDDEN,
            )

        user = self.get_object()
        if user.id == request.user.id:
            return Response(
                {"error": "You cannot deactivate yourself."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if user.is_superuser and not request.user.is_superuser:
            raise PermissionDenied("Only a superuser can change a superuser.")
        with transaction.atomic():
            _check_keeps_an_admin(user)
            user.is_active = not user.is_active
            user.save(update_fields=["is_active"])
        return Response(UserSerializer(user).data)


class OrganizationDomainViewSet(viewsets.ModelViewSet):
    """CRUD + verification actions for the active org's domains.

    Create routes through one of two verification paths based on the
    `verification_method` in the request body:
      - admin_email: synchronous auto-verify (an admin must already
        have a verified email on the domain). Refused if the domain is
        already verified by another org.
      - dns_txt: row created in `pending` state with a fresh token. The
        admin posts the TXT record and calls POST /verify/.
      - omitted: legacy "create as pending without method" — the admin
        can pick a method and trigger verify later.
    """

    serializer_class = OrganizationDomainSerializer
    permission_classes = [IsAuthenticated, IsOrgStaff]

    def get_queryset(self):
        org = get_active_org(self.request)
        if not org:
            return OrganizationDomain.objects.none()
        return OrganizationDomain.objects.filter(organization=org)

    def _check_admin(self) -> Response | None:
        user = self.request.user
        if user.role != User.Role.ADMIN and not user.is_superuser:
            return Response(
                {"error": "Only admins can manage organization domains."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    def create(self, request, *args, **kwargs):
        if (forbidden := self._check_admin()) is not None:
            return forbidden

        org = get_active_org(request)
        if not org:
            return Response(
                {"error": "No active organization."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Default to DNS challenge: it's available to every admin and gives
        # the row an actionable verification path. admin_email is a
        # shortcut for the common case where the requester's own email
        # already proves ownership.
        method = (request.data.get("verification_method") or "").strip()
        if method == OrganizationDomain.VerificationMethod.ADMIN_EMAIL:
            return self._create_with_admin_email(request, org)
        return self._create_with_dns_challenge(request, org)

    def _create_with_admin_email(self, request, org):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = services.try_admin_email_autoverify(
                organization=org,
                domain=serializer.validated_data["domain"],
                is_branding=serializer.validated_data.get("is_branding", False),
                is_email_routing=serializer.validated_data.get(
                    "is_email_routing", True
                ),
            )
        except services.DomainVerificationError as exc:
            return Response(
                {"detail": str(exc), "code": exc.code},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(self.get_serializer(row).data, status=status.HTTP_201_CREATED)

    def _create_with_dns_challenge(self, request, org):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        domain = serializer.validated_data["domain"]
        if OrganizationDomain.objects.filter(organization=org, domain=domain).exists():
            return Response(
                {"detail": "Domain already exists for this organization."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        row = services.start_dns_challenge(
            organization=org,
            domain=domain,
            is_branding=serializer.validated_data.get("is_branding", False),
            is_email_routing=serializer.validated_data.get("is_email_routing", False),
        )
        return Response(self.get_serializer(row).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        if (forbidden := self._check_admin()) is not None:
            return forbidden
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if (forbidden := self._check_admin()) is not None:
            return forbidden
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if (forbidden := self._check_admin()) is not None:
            return forbidden
        return super().destroy(request, *args, **kwargs)

    def perform_create(self, serializer) -> None:
        org = get_active_org(self.request)
        serializer.save(organization=org)

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        """Run a verification check on a pending row.

        For DNS rows, performs a synchronous TXT lookup and either
        promotes the row to verified (transferring ownership if needed)
        or returns the still-pending state with refreshed instructions.
        """
        if (forbidden := self._check_admin()) is not None:
            return forbidden

        row = self.get_object()
        if row.status == OrganizationDomain.Status.VERIFIED:
            return Response(self.get_serializer(row).data)

        if row.verification_method != OrganizationDomain.VerificationMethod.DNS_TXT:
            return Response(
                {
                    "detail": "Only DNS-challenge rows can be verified here.",
                    "code": "wrong_method",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if services.perform_dns_check(row):
            row.refresh_from_db()
            return Response(self.get_serializer(row).data)

        row.refresh_from_db()
        return Response(
            {
                "detail": "TXT record not found yet. DNS can take a few minutes "
                "to propagate.",
                "code": "still_pending",
                "domain": self.get_serializer(row).data,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=["post"], url_path="regenerate-token")
    def regenerate_token(self, request, pk=None):
        """Issue a fresh DNS verification token (invalidates the old one)."""
        if (forbidden := self._check_admin()) is not None:
            return forbidden
        row = self.get_object()
        if row.status == OrganizationDomain.Status.VERIFIED:
            return Response(
                {
                    "detail": "Cannot regenerate token on a verified row.",
                    "code": "already_verified",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        services.regenerate_dns_token(row)
        return Response(self.get_serializer(row).data)


class TeamViewSet(viewsets.ModelViewSet):
    """ViewSet for managing teams."""

    serializer_class = TeamSerializer
    permission_classes = [IsAuthenticated, IsOrgAdminOrReadOnly]

    def get_queryset(self):
        """Filter teams by the active organization."""
        org = get_active_org(self.request)
        if org:
            return Team.objects.filter(organization=org)
        return Team.objects.none()

    def perform_create(self, serializer) -> None:
        """Set organization on creation."""
        serializer.save(organization=require_active_org(self.request))


class PlatformOrganizationViewSet(viewsets.ModelViewSet):
    """ViewSet for platform admins to manage all organizations."""

    permission_classes = [IsAuthenticated, IsPlatformAdmin]
    queryset = Organization.objects.all()

    def get_serializer_class(self):
        if self.action == "list":
            return PlatformOrganizationListSerializer
        if self.action == "create":
            return PlatformOrganizationCreateSerializer
        return PlatformOrganizationDetailSerializer

    def get_queryset(self):
        qs = Organization.objects.annotate(
            _agent_count=Count(
                "users",
                filter=Q(users__role__in=["admin", "agent"], users__is_active=True),
            ),
            _ticket_count=Count("tickets"),
        )
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(slug__icontains=search)
                | Q(domains__domain__icontains=search)
            ).distinct()
        return qs.order_by("-created_at")

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        """Toggle the active status of an organization."""
        org = self.get_object()
        org.is_active = not org.is_active
        org.save(update_fields=["is_active"])
        return Response(PlatformOrganizationDetailSerializer(org).data)

    @action(detail=False, methods=["get"])
    def usage(self, request):
        """Platform-wide and per-org resource usage snapshot.

        Always live-computed from the source tables (no dependency on
        the unused UsageRecord roll-ups for now). Period filter
        (``?period=month`` for a 30-day window, otherwise all-time).
        Per-org rows: capped to the 20 heaviest tenants by ticket
        volume, since the platform admin is the only consumer.
        """
        from django.db.models import Sum

        from apps.tickets.models import Ticket, TicketAttachment
        from apps.videos.models import VideoRecording

        period = request.query_params.get("period", "all")
        since = (
            timezone.now() - timezone.timedelta(days=30) if period == "month" else None
        )

        org_qs = Organization.objects.all()
        ticket_qs = Ticket.objects.all()
        attachment_qs = TicketAttachment.objects.all()
        video_qs = VideoRecording.objects.all()
        if since is not None:
            ticket_qs = ticket_qs.filter(created_at__gte=since)
            attachment_qs = attachment_qs.filter(created_at__gte=since)
            video_qs = video_qs.filter(created_at__gte=since)

        agent_qs = User.objects.filter(
            role__in=[User.Role.AGENT, User.Role.ADMIN], is_active=True
        )

        platform_totals = {
            "organizations_total": org_qs.count(),
            "organizations_active": org_qs.filter(is_active=True).count(),
            "agents_active": agent_qs.count(),
            "tickets_total": ticket_qs.count(),
            "videos_total": video_qs.count(),
            "video_minutes": round(
                (video_qs.aggregate(s=Sum("duration_seconds"))["s"] or 0) / 60,
                1,
            ),
            "attachment_storage_bytes": (
                attachment_qs.aggregate(s=Sum("file_size"))["s"] or 0
            )
            + (video_qs.aggregate(s=Sum("file_size"))["s"] or 0),
        }

        # Per-org breakdown -- annotate then sort by ticket count.
        per_org_rows = []
        agent_counts = dict(
            agent_qs.values("organization")
            .annotate(c=Count("id"))
            .values_list("organization", "c")
        )
        ticket_counts = dict(
            ticket_qs.values("organization")
            .annotate(c=Count("id"))
            .values_list("organization", "c")
        )
        video_counts = dict(
            video_qs.values("ticket__organization")
            .annotate(c=Count("id"))
            .values_list("ticket__organization", "c")
        )
        video_minutes = {
            row["ticket__organization"]: round((row["s"] or 0) / 60, 1)
            for row in video_qs.values("ticket__organization").annotate(
                s=Sum("duration_seconds")
            )
        }
        attachment_bytes = dict(
            attachment_qs.values("ticket__organization")
            .annotate(s=Sum("file_size"))
            .values_list("ticket__organization", "s")
        )
        video_bytes = dict(
            video_qs.values("ticket__organization")
            .annotate(s=Sum("file_size"))
            .values_list("ticket__organization", "s")
        )

        for org in org_qs.order_by("name"):
            tickets = ticket_counts.get(org.id, 0)
            per_org_rows.append(
                {
                    "id": str(org.id),
                    "name": org.name,
                    "slug": org.slug,
                    "is_active": org.is_active,
                    "agents": agent_counts.get(org.id, 0),
                    "tickets": tickets,
                    "videos": video_counts.get(org.id, 0),
                    "video_minutes": video_minutes.get(org.id, 0.0),
                    "storage_bytes": (attachment_bytes.get(org.id) or 0)
                    + (video_bytes.get(org.id) or 0),
                }
            )

        # Sort heaviest tenants first; trim to top 20 to keep the
        # response size predictable.
        per_org_rows.sort(key=lambda r: r["tickets"], reverse=True)
        return Response(
            {
                "period": "month" if since else "all",
                "platform": platform_totals,
                "organizations": per_org_rows[:20],
            }
        )

    @action(detail=True, methods=["get"])
    def stats(self, request, pk=None):
        """Return usage statistics for an organization."""
        org = self.get_object()
        tickets = org.tickets.all()
        agents = org.users.filter(role__in=["admin", "agent"])

        ticket_stats = {
            "total": tickets.count(),
            "open": tickets.filter(status="open").count(),
            "in_progress": tickets.filter(status="in_progress").count(),
            "waiting": tickets.filter(status="waiting").count(),
            "resolved": tickets.filter(status="resolved").count(),
            "closed": tickets.filter(status="closed").count(),
        }

        agent_stats = {
            "total": agents.count(),
            "active": agents.filter(is_active=True).count(),
            "inactive": agents.filter(is_active=False).count(),
        }

        video_count = 0
        try:
            from apps.videos.models import VideoRecording

            video_count = VideoRecording.objects.filter(
                ticket__organization=org
            ).count()
        except ImportError:
            pass

        return Response(
            {
                "tickets": ticket_stats,
                "agents": agent_stats,
                "videos": {"total": video_count},
                "teams": org.teams.count(),
                "tags": org.tags.count(),
            }
        )


class JoinRequestViewSet(
    viewsets.ReadOnlyModelViewSet,
):
    """Admin-only management of pending join requests for the active org.

    Listed: GET /api/v1/join-requests/?status=pending
    Approve: POST /api/v1/join-requests/{id}/approve/
    Reject:  POST /api/v1/join-requests/{id}/reject/

    Approving creates a User row (role=AGENT, unusable password) and
    sends OTP + welcome emails. Rejecting just notifies the requester.
    """

    serializer_class = OrgJoinRequestSerializer
    permission_classes = [IsAuthenticated, IsOrgAdmin]

    def get_queryset(self):
        org = get_active_org(self.request)
        if not org:
            return OrgJoinRequest.objects.none()
        qs = OrgJoinRequest.objects.filter(organization=org)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        """Approve a pending join request: create the user and notify them."""
        join_request = self.get_object()
        if join_request.status != OrgJoinRequest.Status.PENDING:
            return Response(
                {"error": f"Join request is already {join_request.status}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        org = join_request.organization
        existing = User.objects.filter(email__iexact=join_request.email).first()

        if existing and (
            existing.is_superuser or existing.organization_id not in (None, org.id)
        ):
            # The requester created or joined another org between request and
            # decision, or runs the platform. Auto-reject; we cannot move them.
            join_request.status = OrgJoinRequest.Status.REJECTED
            join_request.decided_at = timezone.now()
            join_request.decided_by = request.user
            join_request.save(update_fields=["status", "decided_at", "decided_by"])
            return Response(
                {
                    "detail": (
                        "This email now belongs to another organization; the "
                        "request was auto-rejected."
                    ),
                    "code": "email_taken",
                },
                status=status.HTTP_409_CONFLICT,
            )

        if existing:
            user = existing
            user.organization = org
            user.role = User.Role.AGENT
            user.is_staff = True
            user.is_active = True
            if not user.first_name and not user.last_name and join_request.full_name:
                first_name, _, last_name = join_request.full_name.partition(" ")
                user.first_name = first_name
                user.last_name = last_name
            user.save()
        else:
            first_name, _, last_name = (join_request.full_name or "").partition(" ")
            user = User(
                email=join_request.email,
                first_name=first_name,
                last_name=last_name,
                role=User.Role.AGENT,
                organization=org,
                is_staff=True,
            )
            user.set_unusable_password()
            user.save()

        join_request.status = OrgJoinRequest.Status.APPROVED
        join_request.decided_at = timezone.now()
        join_request.decided_by = request.user
        join_request.save(update_fields=["status", "decided_at", "decided_by"])

        otp = OTPCode.generate(user.email)
        expiry_minutes = getattr(settings, "OTP_EXPIRY_SECONDS", 600) // 60
        send_branded_email(
            template="otp_code",
            subject=f"Showdesk login code: {otp.code}",
            to=[user.email],
            context={
                "kicker": "Sign in",
                "heading": "Your Showdesk login code",
                "intro": (
                    f"Your request to join {org.name} on Showdesk was approved. "
                    "Use the code below to finish signing in."
                ),
                "code": otp.code,
                "expiry_minutes": expiry_minutes,
            },
            fail_silently=True,
        )
        send_branded_email(
            template="join_request_approved",
            subject=f"You're in -- welcome to {org.name}",
            to=[user.email],
            organization=org,
            context={
                "first_name": user.first_name,
                "email": user.email,
                "org_name": org.name,
                "login_url": f"{getattr(settings, 'SITE_URL', '')}/login",
            },
            fail_silently=True,
        )
        return Response(OrgJoinRequestSerializer(join_request).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        """Reject a pending join request and notify the requester."""
        join_request = self.get_object()
        if join_request.status != OrgJoinRequest.Status.PENDING:
            return Response(
                {"error": f"Join request is already {join_request.status}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        join_request.status = OrgJoinRequest.Status.REJECTED
        join_request.decided_at = timezone.now()
        join_request.decided_by = request.user
        join_request.save(update_fields=["status", "decided_at", "decided_by"])

        send_branded_email(
            template="join_request_rejected",
            subject=f"Your request to join {join_request.organization.name}",
            to=[join_request.email],
            organization=join_request.organization,
            context={
                "requester_name": join_request.full_name,
                "org_name": join_request.organization.name,
            },
            fail_silently=True,
        )
        return Response(OrgJoinRequestSerializer(join_request).data)
