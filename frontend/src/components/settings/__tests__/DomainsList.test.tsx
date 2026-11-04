/**
 * Tests for the domains list of Settings → General. Only the API client is mocked.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/api/client";
import { useAuthStore } from "@/store/authStore";
import type { OrganizationDomain } from "@/types";
import { DomainsList } from "../DomainsList";

vi.mock("@/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("react-hot-toast", () => ({
  default: { success: vi.fn(), error: vi.fn() },
}));

const client = vi.mocked(apiClient);

const DOMAIN: OrganizationDomain = {
  id: "d1",
  domain: "acme.com",
  is_branding: true,
  is_email_routing: false,
  is_sending: true,
  status: "verified",
  verification_method: "dns_txt",
  verification_token: "tok",
  verified_at: "2026-11-02T00:00:00Z",
  last_check_at: "2026-11-02T00:00:00Z",
  txt_record_name: "_showdesk.acme.com",
  txt_record_value: "showdesk-verification=tok",
  sending_status: "verified",
  sending_dns_records: [],
  sending_requested_at: null,
  sending_last_checked_at: null,
  sending_last_error: "",
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
};

let sendingEnabled: boolean;

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ isAuthenticated: true });
  client.get.mockImplementation((url: string) => {
    if (url === "/organization-domains/") return Promise.resolve({ data: { results: [DOMAIN] } });
    if (url === "/organizations/")
      return Promise.resolve({
        data: { results: [{ id: "o1", sending_domains_enabled: sendingEnabled }] },
      });
    return Promise.reject(new Error(`unexpected ${url}`));
  });
});

async function renderList() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <DomainsList isAdmin />
    </QueryClientProvider>,
  );
  await screen.findByText("acme.com");
}

describe("DomainsList", () => {
  it("shows a domain's sending status while sending from domains is available", async () => {
    sendingEnabled = true;
    await renderList();
    expect(await screen.findByText(/Sending:/)).toBeInTheDocument();
  });

  it("says nothing about sending when the server can't send from domains", async () => {
    sendingEnabled = false;
    await renderList();
    expect(screen.getByText("Branding")).toBeInTheDocument();
    expect(screen.queryByText(/Sending/)).not.toBeInTheDocument();
  });
});
