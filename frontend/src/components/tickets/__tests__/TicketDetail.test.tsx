/**
 * Tests for what the ticket sidebar shows about who a ticket is from.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/api/client";
import type { ContactSummary, Ticket } from "@/types";
import { TicketDetail } from "../TicketDetail";

vi.mock("@/api/client", () => ({
  apiClient: { get: vi.fn() },
}));
vi.mock("@/hooks/useAuth", () => ({
  useCurrentUser: () => ({ data: { id: "u1", role: "agent" } }),
}));
vi.mock("@/api/users", () => ({
  fetchAgents: vi.fn().mockResolvedValue([]),
  fetchTeams: vi.fn().mockResolvedValue([]),
}));

const client = vi.mocked(apiClient);

const contact: ContactSummary = {
  id: "c1",
  display_name: "Ada Lovelace",
  name: "Ada Lovelace",
  email: "ada@example.com",
  email_verified: true,
  declared_email: "",
  avatar_url: "",
  company_detail: null,
};

function makeTicket(overrides: Partial<Ticket> = {}): Ticket {
  return {
    id: "t1",
    reference: "SD-1",
    title: "Cannot log in",
    description: "",
    status: "open",
    priority: "medium",
    source: "widget",
    issue_type: "other",
    requester: null,
    requester_detail: null,
    requester_name: "Bob Requester",
    requester_email: "bob@example.com",
    contact: null,
    contact_detail: null,
    sender_verified: null,
    assigned_agent: null,
    assigned_agent_detail: null,
    assigned_team: null,
    tags_detail: [],
    context_url: "",
    context_metadata: {},
    messages: [],
    videos: [],
    created_at: "2026-02-01T00:00:00Z",
    updated_at: "2026-02-01T00:00:00Z",
    ...overrides,
  } as unknown as Ticket;
}

function renderDetail(ticket: Ticket) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <TicketDetail ticket={ticket} onSendMessage={vi.fn()} isSending={false} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const contactTicketsCalls = () =>
  client.get.mock.calls.filter(([url]) => String(url).startsWith("/contacts/"));

beforeEach(() => {
  vi.clearAllMocks();
  client.get.mockResolvedValue({ data: [] });
});

describe("TicketDetail sidebar", () => {
  it("shows the contact card instead of the requester when there's a contact", async () => {
    renderDetail(makeTicket({ contact: "c1", contact_detail: contact }));

    expect(screen.getByRole("heading", { name: "Contact" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Requester" })).not.toBeInTheDocument();
    expect(await screen.findByText("Other tickets: 0")).toBeInTheDocument();
    expect(client.get).toHaveBeenCalledWith("/contacts/c1/tickets/");
  });

  it("keeps the requester, and fetches nothing about contacts, without one", () => {
    renderDetail(makeTicket());

    expect(screen.getByRole("heading", { name: "Requester" })).toBeInTheDocument();
    expect(screen.getByText("Bob Requester")).toBeInTheDocument();
    expect(screen.getByText("bob@example.com")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Contact" })).not.toBeInTheDocument();
    expect(contactTicketsCalls()).toHaveLength(0);
  });
});
