/**
 * Tests for how the settings page reaches the custom attributes tabs.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/api/client";
import { SettingsPage } from "../SettingsPage";

const auth = vi.hoisted(() => ({ role: "admin" }));

vi.mock("@/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("@/hooks/useAuth", () => ({
  useCurrentUser: () => ({ data: { id: "u1", role: auth.role } }),
}));
vi.mock("@/api/users", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/users")>()),
  fetchAgents: vi.fn().mockResolvedValue([]),
  fetchOrganization: vi.fn().mockResolvedValue({ id: "o1", enabled_features: [] }),
}));

const client = vi.mocked(apiClient);

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <SettingsPage />
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

beforeEach(() => {
  vi.clearAllMocks();
  auth.role = "admin";
  client.get.mockResolvedValue({ data: [] });
});

describe("SettingsPage attribute tabs", () => {
  it("opens each entity's attributes, without what was typed in the other", async () => {
    const user = renderPage();

    await user.click(screen.getByRole("button", { name: "Contact attributes" }));
    await user.click(await screen.findByRole("button", { name: /New attribute/ }));
    await user.type(screen.getByLabelText("Label"), "Plan");
    expect(client.get).toHaveBeenCalledWith("/contact-attributes/");

    await user.click(screen.getByRole("button", { name: "Company attributes" }));
    await screen.findByRole("heading", { name: "Company attributes" });
    expect(client.get).toHaveBeenCalledWith("/company-attributes/");
    expect(screen.queryByLabelText("Label")).not.toBeInTheDocument();
  });

  it("gives an agent the read-only tab", async () => {
    auth.role = "agent";
    const user = renderPage();

    await user.click(screen.getByRole("button", { name: "Contact attributes" }));

    await screen.findByRole("heading", { name: "Contact attributes" });
    expect(screen.queryByRole("button", { name: /New attribute/ })).not.toBeInTheDocument();
  });
});
