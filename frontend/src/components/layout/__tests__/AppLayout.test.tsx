/**
 * Tests for the Contacts entry of the sidebar, through the app's real routes.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/api/client";
import { App } from "@/App";

vi.mock("@/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("@/components/common/AuthGuard", () => ({
  AuthGuard: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("@/hooks/useAuth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useAuth")>()),
  useCurrentUser: () => ({
    data: { id: "u1", first_name: "A", last_name: "B", organization: "o1" },
  }),
}));
vi.mock("@/hooks/useWebSocket", () => ({ useWebSocket: () => "connected" }));
vi.mock("@/hooks/useInternalWidget", () => ({ useInternalWidget: () => undefined }));

function renderAt(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const sidebar = screen.getAllByRole("navigation")[0]!;
  return within(sidebar).getByRole("link", { name: "Contacts" });
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ data: { count: 0, results: [] } });
});

describe("Contacts in the sidebar", () => {
  it("sits between Tickets and Team", () => {
    renderAt("/tickets");

    const labels = within(screen.getAllByRole("navigation")[0]!)
      .getAllByRole("link")
      .map((link) => link.textContent);
    expect(labels.slice(labels.indexOf("Tickets"), labels.indexOf("Team") + 1)).toEqual([
      "Tickets",
      "Contacts",
      "Team",
    ]);
  });

  it.each(["/contacts", "/companies"])("is active on %s, whose page shows", async (path) => {
    const link = renderAt(path);

    expect(link).toHaveClass("bg-primary-50");
    expect(await screen.findByRole("heading", { level: 1 })).toBeInTheDocument();
    expect(link).toHaveAttribute("href", "/contacts");
  });

  it("is active on /contacts/c1, whose page loads in the layout", () => {
    vi.mocked(apiClient.get).mockImplementation(() => new Promise(() => {}));

    expect(renderAt("/contacts/c1")).toHaveClass("bg-primary-50");
    expect(screen.getByRole("status", { name: "Loading contact" })).toBeInTheDocument();
  });

  it("is active on /companies/co1, in the layout", () => {
    expect(renderAt("/companies/co1")).toHaveClass("bg-primary-50");
    expect(screen.getByText("This page isn't available yet.")).toBeInTheDocument();
  });

  it("is not active elsewhere", () => {
    expect(renderAt("/tickets")).not.toHaveClass("bg-primary-50");
  });
});
