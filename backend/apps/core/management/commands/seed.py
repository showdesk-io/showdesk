"""Management command to seed the database with demo data.

Creates a demo organization, agents, end-users, teams, tags,
SLA policies, and sample tickets with messages. Useful for
development and demonstration purposes.

Usage:
    python manage.py seed
    python manage.py seed --flush  # Clear existing data first
"""

import uuid
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.organizations.models import Organization, Team, User
from apps.tickets.models import SLAPolicy, Tag, Ticket, TicketAttachment, TicketMessage
from apps.knowledge_base.models import Article, Category


class Command(BaseCommand):
    """Seed the database with demo data for development."""

    help = "Seed the database with demo data (organization, agents, tickets, etc.)"

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        """Add command arguments."""
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete all existing data before seeding.",
        )

    def handle(self, *args, **options) -> None:  # noqa: ANN002, ANN003
        """Execute the seed command."""
        if options["flush"]:
            self.stdout.write("Flushing existing data...")
            self._flush()

        self.stdout.write("Seeding database...")

        org = self._create_organization()
        agents = self._create_agents(org)
        end_users = self._create_end_users(org)
        team = self._create_team(org, agents)
        tags = self._create_tags(org)
        self._create_sla_policies(org)
        tickets = self._create_tickets(org, agents, end_users, tags, team)
        self._create_messages(tickets, agents, end_users)
        self._create_knowledge_base(org, agents[0])

        self.stdout.write(self.style.SUCCESS(
            "\nSeed complete!\n"
            f"  Organization: {org.name} (token: {org.api_token})\n"
            f"  Agents: {', '.join(a.email for a in agents)}\n"
            f"  End users: {', '.join(u.email for u in end_users)}\n"
            f"  Team: {team.name}\n"
            f"  Tags: {', '.join(t.name for t in tags)}\n"
            f"  Tickets: {len(tickets)}\n"
            f"\n  Login with: admin@showdesk.local (OTP via email)\n"
            f"  Emails visible at: http://localhost/mailpit/\n"
        ))

    def _flush(self) -> None:
        """Delete all seeded data."""
        TicketMessage.objects.all().delete()
        TicketAttachment.objects.all().delete()
        Ticket.objects.all().delete()
        Tag.objects.all().delete()
        SLAPolicy.objects.all().delete()
        Article.objects.all().delete()
        Category.objects.all().delete()
        Team.objects.all().delete()
        User.objects.filter(is_superuser=False).delete()
        Organization.objects.all().delete()

    def _create_organization(self) -> Organization:
        """Create a demo organization."""
        org, created = Organization.objects.get_or_create(
            slug="acme-corp",
            defaults={
                "name": "Acme Corp",
                "domain": "acme.example.com",
                "widget_color": "#6366F1",
                "widget_position": "bottom-right",
                "widget_greeting": "Hi there! How can we help you today?",
                "video_expiration_days": 90,
                "video_max_duration_seconds": 300,
            },
        )
        if created:
            self.stdout.write(f"  Created organization: {org.name}")
        else:
            self.stdout.write(f"  Organization already exists: {org.name}")
        return org

    def _create_agents(self, org: Organization) -> list[User]:
        """Create demo agent accounts."""
        agents_data = [
            {
                "email": "admin@showdesk.local",
                "first_name": "Alice",
                "last_name": "Admin",
                "role": User.Role.ADMIN,
                "is_staff": True,
                "is_superuser": True,
            },
            {
                "email": "agent1@showdesk.local",
                "first_name": "Bob",
                "last_name": "Support",
                "role": User.Role.AGENT,
            },
            {
                "email": "agent2@showdesk.local",
                "first_name": "Carol",
                "last_name": "Support",
                "role": User.Role.AGENT,
            },
        ]

        agents = []
        for data in agents_data:
            user, created = User.objects.get_or_create(
                email=data["email"],
                defaults={
                    **data,
                    "organization": org,
                    "is_available": True,
                },
            )
            if created:
                user.set_unusable_password()
                user.save()
                self.stdout.write(f"  Created agent: {user.email}")
            agents.append(user)

        return agents

    def _create_end_users(self, org: Organization) -> list[User]:
        """Create demo end-user accounts."""
        users_data = [
            {
                "email": "jane@customer.example",
                "first_name": "Jane",
                "last_name": "Doe",
            },
            {
                "email": "john@customer.example",
                "first_name": "John",
                "last_name": "Smith",
            },
            {
                "email": "maria@customer.example",
                "first_name": "Maria",
                "last_name": "Garcia",
            },
        ]

        users = []
        for data in users_data:
            user, created = User.objects.get_or_create(
                email=data["email"],
                defaults={
                    **data,
                    "organization": org,
                    "role": User.Role.END_USER,
                },
            )
            if created:
                user.set_unusable_password()
                user.save()
                self.stdout.write(f"  Created end user: {user.email}")
            users.append(user)

        return users

    def _create_team(self, org: Organization, agents: list[User]) -> Team:
        """Create a demo team."""
        team, created = Team.objects.get_or_create(
            organization=org,
            name="General Support",
            defaults={
                "description": "First-line support team handling all incoming tickets.",
                "lead": agents[0],
            },
        )
        if created:
            team.members.set(agents)
            self.stdout.write(f"  Created team: {team.name}")
        return team

    def _create_tags(self, org: Organization) -> list[Tag]:
        """Create demo tags."""
        tags_data = [
            {"name": "bug", "color": "#EF4444"},
            {"name": "feature-request", "color": "#3B82F6"},
            {"name": "question", "color": "#8B5CF6"},
            {"name": "urgent", "color": "#F97316"},
            {"name": "billing", "color": "#10B981"},
            {"name": "onboarding", "color": "#EC4899"},
        ]

        tags = []
        for data in tags_data:
            tag, created = Tag.objects.get_or_create(
                organization=org,
                name=data["name"],
                defaults={"color": data["color"]},
            )
            if created:
                self.stdout.write(f"  Created tag: {tag.name}")
            tags.append(tag)

        return tags

    def _create_sla_policies(self, org: Organization) -> None:
        """Create demo SLA policies."""
        policies = [
            {
                "name": "Low Priority SLA",
                "priority": SLAPolicy.Priority.LOW,
                "first_response_minutes": 480,
                "resolution_minutes": 2880,
            },
            {
                "name": "Medium Priority SLA",
                "priority": SLAPolicy.Priority.MEDIUM,
                "first_response_minutes": 240,
                "resolution_minutes": 1440,
            },
            {
                "name": "High Priority SLA",
                "priority": SLAPolicy.Priority.HIGH,
                "first_response_minutes": 60,
                "resolution_minutes": 480,
            },
            {
                "name": "Urgent Priority SLA",
                "priority": SLAPolicy.Priority.URGENT,
                "first_response_minutes": 15,
                "resolution_minutes": 120,
            },
        ]

        for data in policies:
            _, created = SLAPolicy.objects.get_or_create(
                organization=org,
                priority=data["priority"],
                defaults=data,
            )
            if created:
                self.stdout.write(f"  Created SLA: {data['name']}")

    def _create_tickets(
        self,
        org: Organization,
        agents: list[User],
        end_users: list[User],
        tags: list[Tag],
        team: Team,
    ) -> list[Ticket]:
        """Create demo tickets with various statuses and priorities."""
        now = timezone.now()

        tickets_data = [
            {
                "reference": "SD-0001",
                "title": "Cannot upload files larger than 10MB",
                "description": (
                    "When I try to upload a PDF larger than 10MB, the upload "
                    "progress bar reaches 100% but then I get a generic error "
                    "message. This happens consistently in Chrome and Firefox."
                ),
                "status": Ticket.Status.OPEN,
                "priority": Ticket.Priority.HIGH,
                "source": Ticket.Source.WIDGET,
                "requester": end_users[0],
                "context_url": "https://app.acme.example/documents/upload",
                "context_browser": "Chrome",
                "context_os": "macOS",
                "context_screen_resolution": "2560x1440",
                "tags": [tags[0]],  # bug
            },
            {
                "reference": "SD-0002",
                "title": "Feature request: dark mode for the dashboard",
                "description": (
                    "Would love to see a dark mode option for the dashboard. "
                    "I work late at night and the bright UI is hard on my eyes."
                ),
                "status": Ticket.Status.OPEN,
                "priority": Ticket.Priority.LOW,
                "source": Ticket.Source.WIDGET,
                "requester": end_users[1],
                "context_url": "https://app.acme.example/dashboard",
                "context_browser": "Firefox",
                "context_os": "Windows",
                "context_screen_resolution": "1920x1080",
                "tags": [tags[1]],  # feature-request
            },
            {
                "reference": "SD-0003",
                "title": "How do I export my data?",
                "description": (
                    "I need to export all my project data as CSV for a report. "
                    "I looked in the settings but couldn't find the export option."
                ),
                "status": Ticket.Status.IN_PROGRESS,
                "priority": Ticket.Priority.MEDIUM,
                "source": Ticket.Source.WIDGET,
                "requester": end_users[2],
                "assigned_agent": agents[1],
                "assigned_team": team,
                "first_response_at": now - timedelta(hours=2),
                "context_url": "https://app.acme.example/settings",
                "context_browser": "Safari",
                "context_os": "macOS",
                "context_screen_resolution": "1440x900",
                "tags": [tags[2]],  # question
            },
            {
                "reference": "SD-0004",
                "title": "Payment failed but subscription is active",
                "description": (
                    "My last payment attempt failed according to my bank, "
                    "but my subscription still shows as active. I want to "
                    "make sure I won't lose access suddenly."
                ),
                "status": Ticket.Status.WAITING,
                "priority": Ticket.Priority.HIGH,
                "source": Ticket.Source.EMAIL,
                "requester": end_users[0],
                "assigned_agent": agents[2],
                "first_response_at": now - timedelta(hours=5),
                "context_browser": "Chrome",
                "context_os": "Windows",
                "tags": [tags[4]],  # billing
            },
            {
                "reference": "SD-0005",
                "title": "Login page returns 500 error intermittently",
                "description": (
                    "About 1 in 5 login attempts fails with a 500 error. "
                    "Refreshing the page and trying again usually works. "
                    "Started happening after the last update."
                ),
                "status": Ticket.Status.IN_PROGRESS,
                "priority": Ticket.Priority.URGENT,
                "source": Ticket.Source.WIDGET,
                "requester": end_users[1],
                "assigned_agent": agents[0],
                "assigned_team": team,
                "first_response_at": now - timedelta(minutes=10),
                "context_url": "https://app.acme.example/login",
                "context_browser": "Chrome",
                "context_os": "Linux",
                "context_screen_resolution": "1920x1080",
                "tags": [tags[0], tags[3]],  # bug, urgent
            },
            {
                "reference": "SD-0006",
                "title": "Need help setting up SSO",
                "description": (
                    "We just signed up for the enterprise plan and need help "
                    "configuring SAML SSO with our Okta instance."
                ),
                "status": Ticket.Status.RESOLVED,
                "priority": Ticket.Priority.MEDIUM,
                "source": Ticket.Source.EMAIL,
                "requester": end_users[2],
                "assigned_agent": agents[1],
                "first_response_at": now - timedelta(days=2),
                "resolved_at": now - timedelta(hours=12),
                "tags": [tags[5]],  # onboarding
            },
            {
                "reference": "SD-0007",
                "title": "API rate limit documentation is outdated",
                "description": (
                    "The API docs mention a rate limit of 100 req/min but "
                    "I'm getting throttled at 60 req/min. Can you update "
                    "the documentation?"
                ),
                "status": Ticket.Status.CLOSED,
                "priority": Ticket.Priority.LOW,
                "source": Ticket.Source.API,
                "requester": end_users[1],
                "assigned_agent": agents[2],
                "first_response_at": now - timedelta(days=5),
                "resolved_at": now - timedelta(days=4),
                "closed_at": now - timedelta(days=3),
                "tags": [tags[2]],  # question
            },
        ]

        tickets = []
        for data in tickets_data:
            tag_list = data.pop("tags", [])
            ticket, created = Ticket.objects.get_or_create(
                reference=data["reference"],
                defaults={**data, "organization": org},
            )
            if created:
                ticket.tags.set(tag_list)
                self.stdout.write(f"  Created ticket: {ticket.reference} - {ticket.title}")
            tickets.append(ticket)

        return tickets

    def _create_messages(
        self,
        tickets: list[Ticket],
        agents: list[User],
        end_users: list[User],
    ) -> None:
        """Create demo messages on tickets."""
        # Only add messages to tickets that already have some activity
        if len(tickets) < 5:
            return

        messages_data = [
            # Ticket SD-0003 (in_progress, assigned to agent1)
            {
                "ticket": tickets[2],
                "author": agents[1],
                "body": (
                    "Hi Maria, thanks for reaching out! You can export your data "
                    "by going to Settings > Data > Export. I'll send you a quick "
                    "screen recording showing the steps."
                ),
                "message_type": TicketMessage.MessageType.REPLY,
            },
            {
                "ticket": tickets[2],
                "author": agents[1],
                "body": (
                    "Note: the export feature was moved in v2.3. We should update "
                    "the onboarding guide to reflect this."
                ),
                "message_type": TicketMessage.MessageType.INTERNAL_NOTE,
            },
            # Ticket SD-0004 (waiting, billing)
            {
                "ticket": tickets[3],
                "author": agents[2],
                "body": (
                    "Hi Jane, I checked your account and the payment did fail, but "
                    "there's a 3-day grace period before the subscription is "
                    "deactivated. Could you please try the payment again? If it "
                    "fails, I can extend the grace period."
                ),
                "message_type": TicketMessage.MessageType.REPLY,
            },
            # Ticket SD-0005 (urgent, in_progress)
            {
                "ticket": tickets[4],
                "author": agents[0],
                "body": (
                    "I can reproduce this. Looking at the logs, it seems like a "
                    "database connection pool exhaustion issue. Investigating now."
                ),
                "message_type": TicketMessage.MessageType.INTERNAL_NOTE,
            },
            {
                "ticket": tickets[4],
                "author": agents[0],
                "body": (
                    "Hi John, we've identified the issue and are working on a fix. "
                    "As a workaround, you can try clearing your browser cache "
                    "before logging in. We'll update you as soon as the fix is "
                    "deployed."
                ),
                "message_type": TicketMessage.MessageType.REPLY,
            },
            # Ticket SD-0006 (resolved)
            {
                "ticket": tickets[5],
                "author": agents[1],
                "body": (
                    "Hi Maria, I've prepared a step-by-step guide for setting up "
                    "SAML SSO with Okta. Please follow these steps:\n\n"
                    "1. In Okta, create a new SAML 2.0 application\n"
                    "2. Set the Single Sign-On URL to: https://app.acme.example/sso/saml\n"
                    "3. Set the Audience URI to: https://app.acme.example\n"
                    "4. Copy the IdP metadata URL and paste it in Settings > SSO\n\n"
                    "Let me know if you run into any issues!"
                ),
                "message_type": TicketMessage.MessageType.REPLY,
            },
            {
                "ticket": tickets[5],
                "author": end_users[2],
                "body": "That worked perfectly, thank you so much!",
                "message_type": TicketMessage.MessageType.REPLY,
            },
        ]

        for data in messages_data:
            TicketMessage.objects.get_or_create(
                ticket=data["ticket"],
                author=data["author"],
                body=data["body"],
                defaults={"message_type": data["message_type"]},
            )

        self.stdout.write(f"  Created {len(messages_data)} messages")

    def _create_knowledge_base(self, org: Organization, author: User) -> None:
        """Create demo knowledge base content."""
        category, _ = Category.objects.get_or_create(
            organization=org,
            slug="getting-started",
            defaults={
                "name": "Getting Started",
                "description": "Everything you need to know to get up and running.",
                "icon": "book",
                "is_published": True,
            },
        )

        articles_data = [
            {
                "slug": "quick-start-guide",
                "title": "Quick Start Guide",
                "body": (
                    "# Quick Start Guide\n\n"
                    "Welcome to Acme Corp! This guide will help you get set up "
                    "in minutes.\n\n"
                    "## Step 1: Create your account\n\n"
                    "Visit our signup page and enter your email address.\n\n"
                    "## Step 2: Set up your workspace\n\n"
                    "Choose a name for your workspace and invite your team.\n\n"
                    "## Step 3: Start using the product\n\n"
                    "You're all set! Check out our other guides for more details."
                ),
                "status": Article.Status.PUBLISHED,
                "published_at": timezone.now() - timedelta(days=30),
                "view_count": 142,
            },
            {
                "slug": "how-to-export-data",
                "title": "How to Export Your Data",
                "body": (
                    "# How to Export Your Data\n\n"
                    "You can export your data at any time from the Settings page.\n\n"
                    "## CSV Export\n\n"
                    "1. Go to **Settings > Data > Export**\n"
                    "2. Select the data type you want to export\n"
                    "3. Choose the date range\n"
                    "4. Click **Export to CSV**\n\n"
                    "The download will start automatically."
                ),
                "status": Article.Status.PUBLISHED,
                "published_at": timezone.now() - timedelta(days=15),
                "view_count": 87,
            },
        ]

        for data in articles_data:
            Article.objects.get_or_create(
                organization=org,
                slug=data["slug"],
                defaults={
                    **data,
                    "category": category,
                    "author": author,
                },
            )

        self.stdout.write("  Created knowledge base articles")
