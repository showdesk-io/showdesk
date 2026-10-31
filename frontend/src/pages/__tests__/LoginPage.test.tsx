/**
 * Tests for the errors LoginPage shows: a rate limit isn't a wrong code.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { AxiosError, type AxiosResponse } from "axios";
import toast from "react-hot-toast";

vi.mock("@/api/auth");
vi.mock("react-hot-toast", () => ({
  default: { success: vi.fn(), error: vi.fn() },
}));

import * as authApi from "@/api/auth";
import { LoginPage } from "../LoginPage";

const RATE_LIMITED = "Too many attempts. Please wait a while and try again.";

function httpError(status: number) {
  return new AxiosError("error", "ERR_BAD_REQUEST", undefined, undefined, {
    status,
    data: {},
  } as AxiosResponse);
}

function renderLogin() {
  return render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>,
  );
}

async function submitEmail(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/email/i), "agent@acme.com");
  await user.click(screen.getByRole("button", { name: /send login code/i }));
}

async function submitCode(user: ReturnType<typeof userEvent.setup>) {
  const input = await screen.findByLabelText(/login code/i);
  await user.type(input, "123456");
  await user.click(screen.getByRole("button", { name: /sign in/i }));
  return input;
}

beforeEach(() => {
  vi.mocked(toast.error).mockClear();
  vi.mocked(authApi.requestOTP).mockReset();
  vi.mocked(authApi.verifyOTP).mockReset();
  vi.mocked(authApi.requestOTP).mockResolvedValue();
});

describe("LoginPage — requesting a code", () => {
  it("explains a 429", async () => {
    vi.mocked(authApi.requestOTP).mockRejectedValueOnce(httpError(429));
    const user = userEvent.setup();
    renderLogin();
    await submitEmail(user);
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(RATE_LIMITED));
  });

  it("stays generic on other errors", async () => {
    vi.mocked(authApi.requestOTP).mockRejectedValueOnce(httpError(500));
    const user = userEvent.setup();
    renderLogin();
    await submitEmail(user);
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Something went wrong. Please try again.",
      ),
    );
  });
});

describe("LoginPage — verifying a code", () => {
  it("explains a 429 and keeps the code", async () => {
    vi.mocked(authApi.verifyOTP).mockRejectedValueOnce(httpError(429));
    const user = userEvent.setup();
    renderLogin();
    await submitEmail(user);
    const input = await submitCode(user);
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(RATE_LIMITED));
    expect(input).toHaveValue("123456");
  });

  it("calls a 401 an invalid code and clears it", async () => {
    vi.mocked(authApi.verifyOTP).mockRejectedValueOnce(httpError(401));
    const user = userEvent.setup();
    renderLogin();
    await submitEmail(user);
    const input = await submitCode(user);
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Invalid or expired code."),
    );
    expect(input).toHaveValue("");
  });
});
