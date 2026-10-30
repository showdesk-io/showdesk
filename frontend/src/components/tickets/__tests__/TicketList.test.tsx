/**
 * Tests for what a ticket row says of its requester. Only the API client is mocked.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/api/client";
import type { ContactSummary, TicketListItem } from "@/types";
import { TicketList } from "../TicketList";

vi.mock("@/api/client", () => ({
  apiClient: { get: vi.fn() },
}));

function makeTicket(overrides: Partial<TicketListItem> = {}): TicketListItem {
  return {
    id: "t1",
    reference: "SD-1",
    title: "Cannot log in",
    status: "open",
    priority: "medium",
    requester_detail: null,
    requester_email: "bob@example.com",
    contact_detail: null,
    tags_detail: [],
    message_count: 1,
    ...overrides,
  } as unknown as TicketListItem;
}

const contact = (overrides: Partial<ContactSummary>) =>
  ({ id: "c1", is_anonymized: false, ...overrides }) as ContactSummary;

function renderList(ticket: TicketListItem, viewMode: "compact" | "expanded") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <TicketList tickets={[ticket]} isLoading={false} viewMode={viewMode} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(apiClient.get).mockResolvedValue({ data: [] });
});

describe.each(["compact", "expanded"] as const)("a %s row", (viewMode) => {
  it("shows the requester's address", () => {
    renderList(makeTicket(), viewMode);

    expect(screen.getByText("bob@example.com")).toBeInTheDocument();
  });

  it("says anonymized rather than show the placeholder, whatever the contact's address", () => {
    renderList(
      makeTicket({
        requester_email: "anonymized-abc@example.invalid",
        contact_detail: contact({ is_anonymized: true }),
      }),
      viewMode,
    );

    expect(screen.getByText("Anonymized contact")).toBeInTheDocument();
    expect(screen.queryByText(/example\.invalid/)).not.toBeInTheDocument();
  });

  it("says anonymized for a ticket scrubbed with no contact", () => {
    renderList(makeTicket({ requester_email: "anonymized-abc@EXAMPLE.invalid" }), viewMode);

    expect(screen.getByText("Anonymized contact")).toBeInTheDocument();
  });

  it("shows the address of a visitor at that domain, with a regular contact", () => {
    renderList(
      makeTicket({
        requester_email: "visitor@example.invalid",
        contact_detail: contact({ is_anonymized: false }),
      }),
      viewMode,
    );

    expect(screen.getByText("visitor@example.invalid")).toBeInTheDocument();
    expect(screen.queryByText("Anonymized contact")).not.toBeInTheDocument();
  });
});
