"""Factory classes for generating test data.

Uses factory_boy to create model instances with sensible defaults.
All factories are self-contained and can be used independently.
"""

import factory
from django.utils import timezone

from apps.organizations.models import Organization, Team, User
from apps.tickets.models import (
    CannedResponse,
    PriorityLevel,
    SavedView,
    SLAPolicy,
    Tag,
    Ticket,
    TicketAttachment,
    TicketMessage,
)
from apps.videos.models import VideoRecording


class OrganizationFactory(factory.django.DjangoModelFactory):
    """Factory for creating Organization instances."""

    class Meta:
        model = Organization

    name = factory.Sequence(lambda n: f"Test Org {n}")
    slug = factory.Sequence(lambda n: f"test-org-{n}")
    is_active = True
    widget_color = "#6366F1"
    widget_position = "bottom-right"
    widget_greeting = "How can we help?"
    video_expiration_days = 90
    video_max_duration_seconds = 600


class UserFactory(factory.django.DjangoModelFactory):
    """Factory for creating User instances."""

    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@test.example")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    organization = factory.SubFactory(OrganizationFactory)
    role = User.Role.AGENT
    is_active = True
    is_available = True
    password = factory.PostGenerationMethodCall("set_password", "testpass123")


class AdminFactory(UserFactory):
    """Factory for creating admin User instances."""

    role = User.Role.ADMIN
    is_staff = True


class EndUserFactory(UserFactory):
    """Factory for creating end-user instances."""

    role = User.Role.END_USER


class TeamFactory(factory.django.DjangoModelFactory):
    """Factory for creating Team instances."""

    class Meta:
        model = Team

    organization = factory.SubFactory(OrganizationFactory)
    name = factory.Sequence(lambda n: f"Team {n}")
    description = "A test team."


class TagFactory(factory.django.DjangoModelFactory):
    """Factory for creating Tag instances."""

    class Meta:
        model = Tag

    organization = factory.SubFactory(OrganizationFactory)
    name = factory.Sequence(lambda n: f"tag-{n}")
    color = "#EF4444"


class PriorityLevelFactory(factory.django.DjangoModelFactory):
    """Factory for creating PriorityLevel instances."""

    class Meta:
        model = PriorityLevel

    organization = factory.SubFactory(OrganizationFactory)
    name = factory.Sequence(lambda n: f"Priority {n}")
    slug = factory.Sequence(lambda n: f"priority-{n}")
    color = "#6B7280"
    position = factory.Sequence(lambda n: n)
    is_default = False


class SavedViewFactory(factory.django.DjangoModelFactory):
    """Factory for creating SavedView instances."""

    class Meta:
        model = SavedView

    organization = factory.SubFactory(OrganizationFactory)
    created_by = factory.SubFactory(UserFactory)
    name = factory.Sequence(lambda n: f"View {n}")
    filters = factory.LazyFunction(lambda: {"status": "open"})
    is_shared = False
    position = factory.Sequence(lambda n: n)


class CannedResponseFactory(factory.django.DjangoModelFactory):
    """Factory for creating CannedResponse instances."""

    class Meta:
        model = CannedResponse

    organization = factory.SubFactory(OrganizationFactory)
    created_by = factory.SubFactory(UserFactory)
    name = factory.Sequence(lambda n: f"Template {n}")
    shortcut = factory.Sequence(lambda n: f"tpl{n}")
    body = factory.Faker("paragraph")
    is_shared = False
    position = factory.Sequence(lambda n: n)


class SLAPolicyFactory(factory.django.DjangoModelFactory):
    """Factory for creating SLAPolicy instances."""

    class Meta:
        model = SLAPolicy

    organization = factory.SubFactory(OrganizationFactory)
    name = "Standard SLA"
    priority = SLAPolicy.Priority.MEDIUM
    first_response_minutes = 240
    resolution_minutes = 1440
    is_active = True


class TicketFactory(factory.django.DjangoModelFactory):
    """Factory for creating Ticket instances."""

    class Meta:
        model = Ticket

    organization = factory.SubFactory(OrganizationFactory)
    reference = factory.Sequence(lambda n: f"SD-{n:04d}")
    title = factory.Faker("sentence", nb_words=6)
    description = factory.Faker("paragraph")
    status = Ticket.Status.OPEN
    priority = Ticket.Priority.MEDIUM
    source = Ticket.Source.WIDGET
    requester = factory.SubFactory(EndUserFactory)
    requester_email = factory.LazyAttribute(
        lambda o: o.requester.email if o.requester else "test@example.com"
    )
    context_url = "https://app.example.com/page"
    context_browser = "Chrome"
    context_os = "macOS"
    context_screen_resolution = "1920x1080"


class TicketMessageFactory(factory.django.DjangoModelFactory):
    """Factory for creating TicketMessage instances."""

    class Meta:
        model = TicketMessage

    ticket = factory.SubFactory(TicketFactory)
    author = factory.SubFactory(UserFactory)
    body = factory.Faker("paragraph")
    message_type = TicketMessage.MessageType.REPLY


class TicketAttachmentFactory(factory.django.DjangoModelFactory):
    """Factory for creating TicketAttachment instances."""

    class Meta:
        model = TicketAttachment

    ticket = factory.SubFactory(TicketFactory)
    uploaded_by = factory.SubFactory(UserFactory)
    filename = "test-file.pdf"
    content_type = "application/pdf"
    file_size = 1024


class VideoRecordingFactory(factory.django.DjangoModelFactory):
    """Factory for creating VideoRecording instances."""

    class Meta:
        model = VideoRecording

    ticket = factory.SubFactory(TicketFactory)
    status = VideoRecording.Status.READY
    recording_type = VideoRecording.RecordingType.SCREEN
    duration_seconds = 30.0
    file_size = 5_000_000
    width = 1920
    height = 1080
    mime_type = "video/webm"
    has_audio = True
    has_camera = False
    expires_at = factory.LazyFunction(
        lambda: timezone.now() + timezone.timedelta(days=90)
    )
