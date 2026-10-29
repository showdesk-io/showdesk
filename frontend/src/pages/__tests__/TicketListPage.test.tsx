/**
 * Tests for the TicketListPage state that reacts to changing data:
 *   - bulk selection is trimmed to the visible tickets when results change;
 *   - the active saved view is deselected once filters stop matching it;
 *   - keyboard focus resets when the visible list changes size.
 * The ticket list itself is stubbed; only the page's state logic is under test.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { SavedView, TicketListItem } from "@/types";

let ticketResults: TicketListItem[] = [];
let savedViews: SavedView[] = [];

vi.mock("@/hooks/useTickets", () => ({
  useTickets: () => ({
    data: { results: ticketResults, count: ticketResults.length },
    isLoading: false,
  }),
  useCreateTicket: () => ({ mutate: vi.fn(), isPending: false }),
  useBulkUpdateTickets: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/hooks/useTags", () => ({ useTags: () => ({ data: [] }) }));
vi.mock("@/hooks/useSavedViews", () => ({
  useSavedViews: () => ({ data: savedViews }),
  useCreateSavedView: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteSavedView: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/hooks/useAuth", () => ({
  useCurrentUser: () => ({ data: { id: "u1" } }),
}));
vi.mock("@/api/users", () => ({
  fetchAgents: vi.fn().mockResolvedValue([]),
  fetchTeams: vi.fn().mockResolvedValue([]),
  fetchOrganization: vi
    .fn()
    .mockResolvedValue({ id: "o1", enabled_features: ["bulk_actions"] }),
}));
vi.mock("@/components/tickets/TicketList", () => ({
  TicketList: ({
    tickets,
    selectedIds,
    onToggleSelect,
    focusedId,
  }: {
    tickets: TicketListItem[];
    selectedIds?: Set<string>;
    onToggleSelect?: (id: string, next: boolean) => void;
    focusedId?: string | null;
  }) => (
    <ul>
      {tickets.map((t) => (
        <li key={t.id} data-testid={`row-${t.id}`} data-focused={focusedId === t.id}>
          {onToggleSelect && (
            <input
              type="checkbox"
              aria-label={`Select ${t.id}`}
              checked={!!selectedIds?.has(t.id)}
              onChange={(e) => onToggleSelect(t.id, e.target.checked)}
            />
          )}
        </li>
      ))}
    </ul>
  ),
}));

import { TicketListPage } from "../TicketListPage";

function ticket(id: string): TicketListItem {
  return { id, reference: id.toUpperCase() } as TicketListItem;
}

function view(id: string, name: string, priority: string): SavedView {
  return {
    id,
    organization: "o1",
    created_by: "u1",
    created_by_detail: null,
    name,
    filters: { priority },
    is_shared: false,
    position: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const tree = () => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <TicketListPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
  const utils = render(tree());
  return { ...utils, rerenderPage: () => utils.rerender(tree()) };
}

beforeEach(() => {
  ticketResults = [ticket("t1"), ticket("t2")];
  savedViews = [];
});

describe("TicketListPage — bulk selection", () => {
  it("drops selected tickets that are no longer visible after results change", async () => {
    const user = userEvent.setup();
    const { rerenderPage } = renderPage();

    await user.click(await screen.findByLabelText("Select t1"));
    await user.click(screen.getByLabelText("Select t2"));
    expect(screen.getByText("2 selected")).toBeInTheDocument();

    ticketResults = [ticket("t2"), ticket("t3")];
    rerenderPage();

    expect(screen.getByText("1 selected")).toBeInTheDocument();
    expect(screen.getByLabelText("Select t2")).toBeChecked();
    expect(screen.getByLabelText("Select t3")).not.toBeChecked();
  });
});

describe("TicketListPage — saved views", () => {
  it("deselects the active view when filters stop matching, and keeps it off", async () => {
    savedViews = [view("v1", "Urgent only", "urgent")];
    const user = userEvent.setup();
    renderPage();

    const chip = screen.getByRole("button", { name: "Urgent only" });
    const prioritySelect = screen.getByDisplayValue("All Priorities");

    await user.click(chip);
    expect(prioritySelect).toHaveValue("urgent");
    expect(chip.className).toContain("bg-primary-500");

    await user.selectOptions(prioritySelect, "high");
    expect(chip.className).not.toContain("bg-primary-500");

    // Matching the view's filters again by hand does not re-activate it.
    await user.selectOptions(prioritySelect, "urgent");
    expect(chip.className).not.toContain("bg-primary-500");
  });
});

describe("TicketListPage — keyboard focus", () => {
  it("resets the focused row when the number of visible tickets changes", async () => {
    const user = userEvent.setup();
    const { rerenderPage } = renderPage();

    await user.keyboard("j");
    expect(screen.getByTestId("row-t1")).toHaveAttribute("data-focused", "true");

    // Same length: focus is kept.
    ticketResults = [ticket("t1"), ticket("t2")];
    rerenderPage();
    expect(screen.getByTestId("row-t1")).toHaveAttribute("data-focused", "true");

    ticketResults = [ticket("t1"), ticket("t2"), ticket("t3")];
    rerenderPage();
    await waitFor(() =>
      expect(screen.getByTestId("row-t1")).toHaveAttribute("data-focused", "false"),
    );
  });
});
