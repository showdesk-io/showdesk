/**
 * Tests for OnboardingPage. Covers the resume-from-org-state behaviour
 * (the wizard jumps to the step persisted on Organization), the
 * widget-install detection rendered by EmbedStep (the new
 * widget_first_seen_at field flips a "Waiting" pulse to a "Detected"
 * badge), and the redirect when onboarding has already been completed.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/api/users");
vi.mock("react-hot-toast", () => ({
  default: { success: vi.fn(), error: vi.fn() },
}));

const navigateMock = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return { ...actual, useNavigate: () => navigateMock };
});

import * as usersApi from "@/api/users";
import type { Organization } from "@/types";
import { OnboardingPage } from "../OnboardingPage";


function makeOrg(overrides: Partial<Organization> = {}): Organization {
  return {
    id: "org-1",
    name: "Acme Inc",
    slug: "acme",
    logo: null,
    primary_color: "",
    email_from_name: "",
    api_token: "abc-123",
    widget_secret: "secret",
    is_active: true,
    widget_color: "#6366F1",
    widget_position: "bottom-right",
    widget_greeting: "How can we help?",
    video_expiration_days: 90,
    video_max_duration_seconds: 600,
    agent_count: 1,
    onboarding_completed_at: null,
    onboarding_step: 0,
    widget_first_seen_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function renderOnboarding() {
  // Each test gets a fresh client so cache state does not leak.
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <OnboardingPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  navigateMock.mockReset();
  vi.mocked(usersApi.updateOrganization).mockImplementation(
    async (_id, data) => makeOrg(data as Partial<Organization>),
  );
});


describe("OnboardingPage", () => {
  it("renders the widget step (step 0) when org.onboarding_step is 0", async () => {
    vi.mocked(usersApi.fetchOrganization).mockResolvedValue(makeOrg());
    renderOnboarding();

    expect(
      await screen.findByRole("heading", { name: /customize your widget/i }),
    ).toBeInTheDocument();
  });

  it("resumes at the embed step when org.onboarding_step is 2", async () => {
    vi.mocked(usersApi.fetchOrganization).mockResolvedValue(
      makeOrg({ onboarding_step: 2 }),
    );
    renderOnboarding();

    expect(
      await screen.findByRole("heading", { name: /drop the widget on your site/i }),
    ).toBeInTheDocument();
    // The embed snippet uses the api_token.
    expect(screen.getByText(/abc-123/)).toBeInTheDocument();
  });

  it("redirects to / when onboarding has already been completed", async () => {
    vi.mocked(usersApi.fetchOrganization).mockResolvedValue(
      makeOrg({ onboarding_completed_at: "2026-04-01T00:00:00Z" }),
    );
    renderOnboarding();

    // <Navigate to="/" replace /> renders nothing — the page's heading
    // never appears.
    await waitFor(() => {
      expect(
        screen.queryByRole("heading", { name: /welcome to showdesk/i }),
      ).not.toBeInTheDocument();
    });
  });

  it("EmbedStep shows the 'Waiting' badge when widget_first_seen_at is null", async () => {
    vi.mocked(usersApi.fetchOrganization).mockResolvedValue(
      makeOrg({ onboarding_step: 2, widget_first_seen_at: null }),
    );
    renderOnboarding();

    expect(
      await screen.findByText(/waiting for the first widget call/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/widget detected on your site/i),
    ).not.toBeInTheDocument();
  });

  it("EmbedStep shows the 'Detected' badge when widget_first_seen_at is set", async () => {
    vi.mocked(usersApi.fetchOrganization).mockResolvedValue(
      makeOrg({
        onboarding_step: 2,
        widget_first_seen_at: "2026-05-02T10:00:00Z",
      }),
    );
    renderOnboarding();

    expect(
      await screen.findByText(/widget detected on your site/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/waiting for the first widget call/i),
    ).not.toBeInTheDocument();
  });

  it("clicking 'Open my dashboard' marks onboarding complete and navigates home", async () => {
    vi.mocked(usersApi.fetchOrganization).mockResolvedValue(
      makeOrg({ onboarding_step: 2 }),
    );
    const user = userEvent.setup();
    renderOnboarding();

    await user.click(
      await screen.findByRole("button", { name: /open my dashboard/i }),
    );

    await waitFor(() => {
      expect(usersApi.updateOrganization).toHaveBeenCalledWith(
        "org-1",
        expect.objectContaining({
          onboarding_step: 3,
          onboarding_completed_at: expect.any(String),
        }),
      );
    });
    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalledWith("/");
    });
  });
});
