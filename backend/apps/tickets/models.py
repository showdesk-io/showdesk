"""Ticket-related models: Ticket, TicketMessage, TicketAttachment, Tag, SLAPolicy."""

from django.conf import settings
from django.db import models

from apps.core.models import TimestampedModel


class PriorityLevel(TimestampedModel):
    """Custom priority level defined per organization.

    Organizations can define their own priorities with custom names, colors,
    and ordering. Default priorities (low, medium, high, urgent) are seeded
    automatically when an organization is created.
    """

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="priority_levels",
    )
    name = models.CharField(max_length=50)
    slug = models.SlugField(
        max_length=50,
        help_text="URL-friendly identifier used in ticket.priority field.",
    )
    color = models.CharField(
        max_length=7,
        default="#6B7280",
        help_text="Priority color in hex format.",
    )
    position = models.PositiveIntegerField(
        default=0,
        help_text="Sort order (lower = less urgent).",
    )
    is_default = models.BooleanField(
        default=False,
        help_text="If true, new tickets get this priority by default.",
    )

    class Meta:
        ordering = ["position"]
        unique_together = [
            ("organization", "slug"),
            ("organization", "name"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.organization})"

    @classmethod
    def create_defaults(cls, organization) -> None:  # noqa: ANN001
        """Create the four default priority levels for an organization."""
        defaults = [
            {"name": "Low", "slug": "low", "color": "#6B7280", "position": 0},
            {"name": "Medium", "slug": "medium", "color": "#3B82F6", "position": 1, "is_default": True},
            {"name": "High", "slug": "high", "color": "#F97316", "position": 2},
            {"name": "Urgent", "slug": "urgent", "color": "#EF4444", "position": 3},
        ]
        for d in defaults:
            cls.objects.get_or_create(
                organization=organization,
                slug=d["slug"],
                defaults=d,
            )


class Tag(TimestampedModel):
    """Labels that can be applied to tickets for categorization.

    Tags are scoped to an organization and can be used for filtering,
    automation rules, and reporting.
    """

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="tags",
    )
    name = models.CharField(max_length=100)
    color = models.CharField(
        max_length=7,
        default="#6B7280",
        help_text="Tag color in hex format.",
    )

    class Meta:
        ordering = ["name"]
        unique_together = ["organization", "name"]

    def __str__(self) -> str:
        return self.name


class SLAPolicy(TimestampedModel):
    """Service Level Agreement policy defining response and resolution times.

    SLA policies are applied to tickets based on priority level. They
    define the expected first response time and resolution time for
    each priority.
    """

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="sla_policies",
    )
    name = models.CharField(max_length=255)
    priority = models.CharField(max_length=10, choices=Priority.choices)
    first_response_minutes = models.PositiveIntegerField(
        help_text="Target first response time in minutes.",
    )
    resolution_minutes = models.PositiveIntegerField(
        help_text="Target resolution time in minutes.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "SLA Policy"
        verbose_name_plural = "SLA Policies"
        ordering = ["organization", "priority"]
        unique_together = ["organization", "priority"]

    def __str__(self) -> str:
        return f"{self.name} ({self.priority})"


class Ticket(TimestampedModel):
    """A support ticket submitted by an end-user or created by an agent.

    Tickets are the central entity of the helpdesk. They track the full
    lifecycle of a support request, from initial submission through
    resolution. Tickets can include video recordings, file attachments,
    and automatically captured technical context.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In Progress"
        WAITING = "waiting", "Waiting"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    class Source(models.TextChoices):
        WIDGET = "widget", "Widget"
        EMAIL = "email", "Email"
        API = "api", "API"
        AGENT = "agent", "Agent"

    # Core fields
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="tickets",
    )
    reference = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
        help_text="Human-readable ticket reference (e.g., SD-1234).",
    )
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )
    priority = models.CharField(
        max_length=50,
        default=Priority.MEDIUM,
        db_index=True,
    )
    source = models.CharField(
        max_length=10,
        choices=Source.choices,
        default=Source.WIDGET,
    )

    # People
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_tickets",
        help_text="The end-user who submitted this ticket.",
    )
    assigned_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tickets",
        help_text="The agent currently assigned to this ticket.",
    )
    assigned_team = models.ForeignKey(
        "organizations.Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tickets",
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="tickets")

    # Technical context (auto-captured from widget)
    context_url = models.URLField(
        max_length=2048,
        blank=True,
        help_text="URL where the ticket was submitted from.",
    )
    context_user_agent = models.TextField(blank=True)
    context_os = models.CharField(max_length=100, blank=True)
    context_browser = models.CharField(max_length=100, blank=True)
    context_screen_resolution = models.CharField(max_length=20, blank=True)
    context_metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional technical context captured by the widget.",
    )

    # Requester info for unauthenticated submissions
    requester_name = models.CharField(max_length=255, blank=True)
    requester_email = models.EmailField(blank=True)

    # SLA tracking
    sla_policy = models.ForeignKey(
        SLAPolicy,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["organization", "priority"]),
            models.Index(fields=["assigned_agent", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.reference}: {self.title}"


class TicketMessage(TimestampedModel):
    """A message within a ticket thread.

    Messages can be either public replies (visible to the requester)
    or internal notes (visible only to agents). This distinction is
    key for agent collaboration without exposing internal discussions.
    """

    class MessageType(models.TextChoices):
        REPLY = "reply", "Reply"
        INTERNAL_NOTE = "internal_note", "Internal Note"

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="ticket_messages",
    )
    body = models.TextField()
    message_type = models.CharField(
        max_length=20,
        choices=MessageType.choices,
        default=MessageType.REPLY,
    )

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"Message on {self.ticket.reference} by {self.author}"


class TicketAttachment(TimestampedModel):
    """A file attached to a ticket or message.

    Supports any file type. Video recordings are handled separately
    by the VideoRecording model, but can be linked here as well.
    """

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    message = models.ForeignKey(
        TicketMessage,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attachments",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
    )
    file = models.FileField(upload_to="attachments/%Y/%m/%d/")
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    file_size = models.PositiveBigIntegerField(help_text="File size in bytes.")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.filename} ({self.ticket.reference})"
