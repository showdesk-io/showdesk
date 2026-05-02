/**
 * Tests for SignupPage state machine. The signup flow has 5 internal
 * steps (email, otp, join_confirm, join_done, wizard) driven entirely by
 * client state and API responses; these tests exercise the transitions
 * and the API calls behind them. Live-checks (checkDomain / checkSlug)
 * are stubbed so no debouncing-timing tricks are required.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/api/signup");
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

import * as signupApi from "@/api/signup";
import { useAuthStore } from "@/store/authStore";
import { SignupPage } from "../SignupPage";


function renderSignup() {
  return render(
    <MemoryRouter>
      <SignupPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  navigateMock.mockReset();
  useAuthStore.setState({
    accessToken: null,
    refreshToken: null,
    isAuthenticated: false,
  });
  vi.mocked(signupApi.checkDomain).mockResolvedValue({ matches_org: false });
  vi.mocked(signupApi.checkSlug).mockResolvedValue({ available: true });
  vi.mocked(signupApi.signupRequestOTP).mockResolvedValue();
  // After OTP verify, isAuthenticated flips and the resume useEffect
  // re-fires fetchSignupState. Reject so the SignupPage catch swallows
  // it silently and the test stays on the step it just navigated to.
  vi.mocked(signupApi.fetchSignupState).mockRejectedValue(new Error("test-noop"));
});


describe("SignupPage — email step", () => {
  it("renders the email step initially when unauthenticated", async () => {
    renderSignup();
    expect(
      await screen.findByRole("heading", { name: /create your showdesk account/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/full name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/work email/i)).toBeInTheDocument();
  });

  it("submitting the email form advances to the OTP step", async () => {
    const user = userEvent.setup();
    renderSignup();

    await user.type(await screen.findByLabelText(/full name/i), "Jane Doe");
    await user.type(screen.getByLabelText(/work email/i), "jane@acme.com");
    await user.click(
      screen.getByRole("button", { name: /send verification code/i }),
    );

    await waitFor(() => {
      expect(signupApi.signupRequestOTP).toHaveBeenCalledWith({
        email: "jane@acme.com",
        full_name: "Jane Doe",
      });
    });
    expect(
      await screen.findByLabelText(/verification code/i),
    ).toBeInTheDocument();
  });

  it("shows the domain-match hint when an existing org matches the email", async () => {
    vi.mocked(signupApi.checkDomain).mockResolvedValue({
      matches_org: true,
      org_name: "Acme Inc",
      domain: "acme.com",
    });

    const user = userEvent.setup();
    renderSignup();

    await user.type(
      await screen.findByLabelText(/work email/i),
      "jane@acme.com",
    );

    expect(
      await screen.findByText(/already uses\s*Showdesk/i, undefined, {
        timeout: 2000,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Acme Inc")).toBeInTheDocument();
  });
});


describe("SignupPage — OTP step routes by next_step", () => {
  async function reachOTPStep() {
    const user = userEvent.setup();
    renderSignup();
    await user.type(await screen.findByLabelText(/full name/i), "Jane");
    await user.type(screen.getByLabelText(/work email/i), "jane@acme.com");
    await user.click(
      screen.getByRole("button", { name: /send verification code/i }),
    );
    await screen.findByLabelText(/verification code/i);
    return user;
  }

  it("create_org → wizard step is shown after verifying the code", async () => {
    vi.mocked(signupApi.signupVerifyOTP).mockResolvedValue({
      access: "a", refresh: "r",
      user: { id: "u1", email: "jane@acme.com" } as never,
      next_step: "create_org",
      domain: "acme.com",
    });

    const user = await reachOTPStep();
    await user.type(screen.getByLabelText(/verification code/i), "123456");
    await user.click(screen.getByRole("button", { name: /verify and continue/i }));

    expect(
      await screen.findByRole("heading", { name: /set up your workspace/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/organization name/i)).toBeInTheDocument();
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
  });

  it("join_request → join_confirm step is shown after verifying the code", async () => {
    vi.mocked(signupApi.signupVerifyOTP).mockResolvedValue({
      access: "a", refresh: "r",
      user: { id: "u1", email: "jane@acme.com" } as never,
      next_step: "join_request",
      org_name: "Acme Inc",
    });

    const user = await reachOTPStep();
    await user.type(screen.getByLabelText(/verification code/i), "123456");
    await user.click(screen.getByRole("button", { name: /verify and continue/i }));

    expect(
      await screen.findByRole("heading", { name: /join acme inc/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /request to join acme inc/i }),
    ).toBeInTheDocument();
  });
});


describe("SignupPage — wizard step submits and navigates", () => {
  it("submitting the wizard calls signupCreateOrg and navigates to /onboarding", async () => {
    vi.mocked(signupApi.signupVerifyOTP).mockResolvedValue({
      access: "a", refresh: "r",
      user: { id: "u1", email: "jane@acme.com" } as never,
      next_step: "create_org",
      domain: "acme.com",
    });
    vi.mocked(signupApi.signupCreateOrg).mockResolvedValue({
      user: { id: "u1", email: "jane@acme.com" } as never,
      organization: { id: "o1", slug: "acme", name: "Acme" },
      email_domain: "acme.com",
      email_domain_status: "verified",
    });

    const user = userEvent.setup();
    renderSignup();
    await user.type(await screen.findByLabelText(/full name/i), "Jane");
    await user.type(screen.getByLabelText(/work email/i), "jane@acme.com");
    await user.click(
      screen.getByRole("button", { name: /send verification code/i }),
    );
    await user.type(
      await screen.findByLabelText(/verification code/i),
      "123456",
    );
    await user.click(screen.getByRole("button", { name: /verify and continue/i }));

    await user.type(
      await screen.findByLabelText(/organization name/i),
      "Acme",
    );
    // Wait for the slug live-check to settle so the submit button enables.
    await waitFor(() =>
      expect(signupApi.checkSlug).toHaveBeenCalled(),
    );
    await user.click(
      screen.getByRole("button", { name: /create my workspace/i }),
    );

    await waitFor(() => {
      expect(signupApi.signupCreateOrg).toHaveBeenCalledWith(
        expect.objectContaining({ org_name: "Acme", org_slug: "acme" }),
      );
    });
    expect(navigateMock).toHaveBeenCalledWith("/onboarding");
  });
});
