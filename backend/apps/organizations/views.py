"""Views for organization-related models."""

import uuid

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.email import send_branded_email
from apps.core.permissions import IsPlatformAdmin, get_active_org

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


class OrganizationViewSet(viewsets.ModelViewSet):
    """ViewSet for managing organizations (tenant-scoped)."""

    serializer_class = OrganizationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):  # noqa: ANN201
        """Filter organizations by the active organization."""
        org = get_active_org(self.request)
        if org:
            return Organization.objects.filter(id=org.id)
        return Organization.objects.none()

    @action(detail=True, methods=["post"])
    def regenerate_token(self, request, pk=None):  # noqa: ANN001, ANN201
        """Regenerate the organization's widget API token."""
        org = self.get_object()
        if request.user.role != User.Role.ADMIN and not request.user.is_superuser:
            return Response(
                {"error": "Only admins can regenerate the API token."},
                status=status.HTTP_403_FORBIDDEN,
            )
        org.api_token = uuid.uuid4()
        org.save(update_fields=["api_token"])
        return Response(OrganizationSerializer(org).data)

    @action(detail=True, methods=["post"])
    def revoke_credentials(self, request, pk=None):  # noqa: ANN001, ANN201
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
        return Response(OrganizationSerializer(org).data)


class UserViewSet(viewsets.ModelViewSet):
    """ViewSet for managing users."""

    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):  # noqa: ANN201
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

    @action(detail=False, methods=["get"])
    def me(self, request):  # noqa: ANN001, ANN201
        """Return the currently authenticated user."""
        return Response(UserSerializer(request.user).data)

    @action(detail=False, methods=["post"])
    def invite(self, request):  # noqa: ANN001, ANN201
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
        except Exception:  # noqa: BLE001
            pass

        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def toggle_active(self, request, pk=None):  # noqa: ANN001, ANN201
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
    permission_classes = [IsAuthenticated]

    def get_queryset(self):  # noqa: ANN201
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

    def create(self, request, *args, **kwargs):  # noqa: ANN001, ANN201
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

    def _create_with_admin_email(self, request, org):  # noqa: ANN001, ANN201
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
        return Response(
            self.get_serializer(row).data, status=status.HTTP_201_CREATED
        )

    def _create_with_dns_challenge(self, request, org):  # noqa: ANN001, ANN201
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        domain = serializer.validated_data["domain"]
        if OrganizationDomain.objects.filter(
            organization=org, domain=domain
        ).exists():
            return Response(
                {"detail": "Domain already exists for this organization."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        row = services.start_dns_challenge(
            organization=org,
            domain=domain,
            is_branding=serializer.validated_data.get("is_branding", False),
            is_email_routing=serializer.validated_data.get(
                "is_email_routing", False
            ),
        )
        return Response(
            self.get_serializer(row).data, status=status.HTTP_201_CREATED
        )

    def update(self, request, *args, **kwargs):  # noqa: ANN001, ANN201
        if (forbidden := self._check_admin()) is not None:
            return forbidden
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):  # noqa: ANN001, ANN201
        if (forbidden := self._check_admin()) is not None:
            return forbidden
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):  # noqa: ANN001, ANN201
        if (forbidden := self._check_admin()) is not None:
            return forbidden
        return super().destroy(request, *args, **kwargs)

    def perform_create(self, serializer) -> None:  # noqa: ANN001
        org = get_active_org(self.request)
        serializer.save(organization=org)

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):  # noqa: ANN001, ANN201
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
    def regenerate_token(self, request, pk=None):  # noqa: ANN001, ANN201
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
    permission_classes = [IsAuthenticated]

    def get_queryset(self):  # noqa: ANN201
        """Filter teams by the active organization."""
        org = get_active_org(self.request)
        if org:
            return Team.objects.filter(organization=org)
        return Team.objects.none()

    def perform_create(self, serializer) -> None:  # noqa: ANN001
        """Set organization on creation."""
        serializer.save(organization=get_active_org(self.request))


class PlatformOrganizationViewSet(viewsets.ModelViewSet):
    """ViewSet for platform admins to manage all organizations."""

    permission_classes = [IsAuthenticated, IsPlatformAdmin]
    queryset = Organization.objects.all()

    def get_serializer_class(self):  # noqa: ANN201
        if self.action == "list":
            return PlatformOrganizationListSerializer
        if self.action == "create":
            return PlatformOrganizationCreateSerializer
        return PlatformOrganizationDetailSerializer

    def get_queryset(self):  # noqa: ANN201
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
                | Q(domain__icontains=search)
            )
        return qs.order_by("-created_at")

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):  # noqa: ANN001, ANN201
        """Toggle the active status of an organization."""
        org = self.get_object()
        org.is_active = not org.is_active
        org.save(update_fields=["is_active"])
        return Response(PlatformOrganizationDetailSerializer(org).data)

    @action(detail=True, methods=["get"])
    def stats(self, request, pk=None):  # noqa: ANN001, ANN201
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
    permission_classes = [IsAuthenticated]

    def get_queryset(self):  # noqa: ANN201
        org = get_active_org(self.request)
        if not org:
            return OrgJoinRequest.objects.none()
        qs = OrgJoinRequest.objects.filter(organization=org)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def _check_admin(self, request) -> Response | None:  # noqa: ANN001
        if request.user.role != User.Role.ADMIN and not request.user.is_superuser:
            return Response(
                {"error": "Only admins can manage join requests."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):  # noqa: ANN001, ANN201
        """Approve a pending join request: create the user and notify them."""
        if (forbidden := self._check_admin(request)) is not None:
            return forbidden

        join_request = self.get_object()
        if join_request.status != OrgJoinRequest.Status.PENDING:
            return Response(
                {"error": f"Join request is already {join_request.status}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        org = join_request.organization
        existing = User.objects.filter(email__iexact=join_request.email).first()

        if existing and existing.organization_id not in (None, org.id):
            # The requester created or joined another org between request and
            # decision. Auto-reject; we cannot move them.
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
    def reject(self, request, pk=None):  # noqa: ANN001, ANN201
        """Reject a pending join request and notify the requester."""
        if (forbidden := self._check_admin(request)) is not None:
            return forbidden

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
