/**
 * Choosing "Unassigned" has to send an explicit null: the API reads a missing
 * key as "leave it alone", which kept the ticket assigned with a success toast.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import type { ReactNode } from "react";
import type { Ticket, TicketListItem } from "@/types";

const assign = vi.fn();
const mutation = { mutate: vi.fn(), isPending: false };

vi.mock("@/hooks/useTickets", () => ({
  useAssignTicket: () => ({ mutate: assign, isPending: false }),
  useUpdateTicket: () => mutation,
  useResolveTicket: () => mutation,
  useCloseTicket: () => mutation,
  useReopenTicket: () => mutation,
  useDeleteMessage: () => mutation,
}));
vi.mock("@/hooks/useTags", () => ({
  useTags: () => ({ data: [] }),
  useCreateTag: () => mutation,
  useSetTicketTags: () => mutation,
}));
vi.mock("@/hooks/usePriorities", () => ({
  usePriorities: () => ({ data: [] }),
}));
vi.mock("@/hooks/useCannedResponses", () => ({
  useCannedResponses: () => ({ data: [] }),
  useRecordCannedResponseUse: () => mutation,
}));
vi.mock("@/hooks/useAuth", () => ({
  useCurrentUser: () => ({ data: undefined }),
}));
vi.mock("@/api/users", () => ({
  fetchAgents: async () => [
    { id: "a1", first_name: "Ann", last_name: "A", email: "ann@example.com" },
  ],
  fetchTeams: async () => [{ id: "t1", name: "Support" }],
}));

import { TicketSidebar } from "../TicketDetail";
import { AssignMenu } from "../TicketList";

function wrap(children: ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const ticket = {
  id: "ticket-1",
  status: "open",
  priority: "medium",
  assigned_agent: "a1",
  assigned_team: "t1",
  assigned_agent_detail: { id: "a1", first_name: "Ann", email: "ann@example.com" },
  requester_email: "",
  requester_detail: null,
  contact_detail: null,
  tags_detail: [],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
} as unknown as Ticket & TicketListItem;

function selectContaining(option: string): HTMLSelectElement {
  return screen.getByRole("option", { name: option }).closest("select")!;
}

describe("unassigning a ticket", () => {
  beforeEach(() => assign.mockClear());

  it("sends agent_id null from the ticket sidebar", async () => {
    wrap(<TicketSidebar ticket={ticket} />);
    await screen.findByRole("option", { name: /Ann/ });
    await userEvent.selectOptions(selectContaining("Unassigned"), "");
    expect(assign.mock.calls[0]?.[0]).toEqual({ ticketId: "ticket-1", agent_id: null });
  });

  it("sends team_id null from the ticket sidebar", async () => {
    wrap(<TicketSidebar ticket={ticket} />);
    await screen.findByRole("option", { name: "Support" });
    await userEvent.selectOptions(selectContaining("No team"), "");
    expect(assign.mock.calls[0]?.[0]).toEqual({ ticketId: "ticket-1", team_id: null });
  });

  it("still sends the id when choosing an agent", async () => {
    wrap(<TicketSidebar ticket={{ ...ticket, assigned_agent: null }} />);
    await screen.findByRole("option", { name: /Ann/ });
    await userEvent.selectOptions(selectContaining("Unassigned"), "a1");
    expect(assign.mock.calls[0]?.[0]).toEqual({ ticketId: "ticket-1", agent_id: "a1" });
  });

  it("sends agent_id null from the ticket list menu", async () => {
    wrap(<AssignMenu ticket={ticket} />);
    await userEvent.click(screen.getByTitle("Assign agent"));
    await userEvent.click(screen.getByRole("button", { name: "Unassigned" }));
    expect(assign.mock.calls[0]?.[0]).toEqual({ ticketId: "ticket-1", agent_id: null });
  });
});
