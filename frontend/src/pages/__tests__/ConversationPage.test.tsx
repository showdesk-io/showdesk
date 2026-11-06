/**
 * Tests for the public conversation page a mailed link opens, on its real fetch wrapper.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/store/authStore";
import { ConversationPage } from "../ConversationPage";

const TOKEN = "eyJ0Ijo:1abc:sig";
const PAGE_URL = `/api/v1/conversations/${encodeURIComponent(TOKEN)}/`;

const CONVERSATION = {
  organization: { name: "Acme", logo: "", color: "#123456" },
  reference: "SD-0042",
  title: "Export fails",
  status: "waiting",
  can_reply: true,
  messages: [
    {
      id: "m1",
      body: "My export fails <b>every time</b>",
      body_type: "text",
      sender_type: "user",
      sender_name: "Ann",
      attachments: [],
      created_at: "2026-11-01T10:00:00Z",
    },
    {
      id: "m2",
      body: "Have you tried X?",
      body_type: "text",
      sender_type: "agent",
      sender_name: "Alice Martin",
      attachments: [],
      created_at: "2026-11-01T11:00:00Z",
    },
  ],
};

type Answer = { status: number; body?: unknown };
type Route_ = (url: string, init: RequestInit) => Answer;

let fetchMock: ReturnType<typeof vi.fn>;

function serve(route: Route_) {
  fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const { status, body } = route(String(input), init);
    return new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
}

function pageReads(): number {
  return fetchMock.mock.calls.filter(
    ([url, init]) => String(url) === PAGE_URL && (init?.method ?? "GET") === "GET",
  ).length;
}

function renderPage() {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/c/${TOKEN}`]}>
        <Routes>
          <Route path="/c/:token" element={<ConversationPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function setVisibility(state: DocumentVisibilityState) {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
  document.dispatchEvent(new Event("visibilitychange"));
}

beforeEach(() => {
  setVisibility("visible");
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  useAuthStore.getState().logout();
});

describe("ConversationPage", () => {
  it("shows the thread, its bodies as text, and asks not to be indexed", async () => {
    serve(() => ({ status: 200, body: CONVERSATION }));
    renderPage();

    expect(await screen.findByText("Have you tried X?")).toBeInTheDocument();
    expect(screen.getByText("Acme")).toBeInTheDocument();
    expect(screen.getByText(/SD-0042/)).toBeInTheDocument();
    expect(screen.getByText("My export fails <b>every time</b>")).toBeInTheDocument();
    expect(document.querySelector("b")).toBeNull();
    expect(document.querySelector('meta[name="robots"]')).toHaveAttribute(
      "content",
      "noindex",
    );
  });

  it("polls every 15 s only while the page is visible", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    serve(() => ({ status: 200, body: CONVERSATION }));
    renderPage();
    await screen.findByText("Have you tried X?");
    expect(pageReads()).toBe(1);

    await act(() => vi.advanceTimersByTimeAsync(15_000));
    await waitFor(() => expect(pageReads()).toBe(2));

    act(() => setVisibility("hidden"));
    await act(() => vi.advanceTimersByTimeAsync(60_000));
    expect(pageReads()).toBe(2);
  });

  it("sends a reply", async () => {
    serve((_url, init) =>
      init.method === "POST"
        ? { status: 201, body: { id: "m3" } }
        : { status: 200, body: CONVERSATION },
    );
    const user = userEvent.setup();
    renderPage();

    await user.type(await screen.findByLabelText(/your reply/i), "Still broken");
    await user.click(screen.getByRole("button", { name: /^send$/i }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        `${PAGE_URL}messages/`,
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ body: "Still broken" }),
        }),
      ),
    );
    await waitFor(() => expect(pageReads()).toBe(2));
  });

  it("offers a new link when this one expired", async () => {
    serve((url) =>
      url.endsWith("/renew/")
        ? { status: 202 }
        : { status: 410, body: { renewable: true } },
    );
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText("This link has expired")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Send me a new link" }));

    expect(
      await screen.findByText(
        "If this address can receive our emails, a new link is on its way.",
      ),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/conversations/renew/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ token: TOKEN }) }),
    );
  });

  it("sends to support a link too old for a new one", async () => {
    serve(() => ({ status: 410, body: { renewable: false } }));
    renderPage();

    expect(await screen.findByText("This link has expired")).toBeInTheDocument();
    expect(screen.getByText(/contact support/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /new link/i })).toBeNull();
  });

  it("stops polling on a link that opens nothing or expired, not on a rate limit", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    for (const [status, body] of [
      [404, { error: "Conversation not found." }],
      [410, { renewable: true }],
    ] as const) {
      serve(() => ({ status, body }));
      const { unmount } = renderPage();
      await waitFor(() => expect(pageReads()).toBe(1));
      await act(() => vi.advanceTimersByTimeAsync(60_000));
      expect(pageReads()).toBe(1);
      unmount();
    }

    serve(() => ({ status: 429, body: {} }));
    renderPage();
    await waitFor(() => expect(pageReads()).toBe(1));
    await act(() => vi.advanceTimersByTimeAsync(15_000));
    await waitFor(() => expect(pageReads()).toBe(2));
  });

  it("says to write by email once the conversation can't take replies", async () => {
    serve(() => ({ status: 200, body: { ...CONVERSATION, can_reply: false } }));
    renderPage();

    expect(
      await screen.findByText(/reply by email to open a new request/i),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/your reply/i)).toBeNull();
  });

  it("says no more than not found for a link that opens nothing", async () => {
    serve(() => ({ status: 404, body: { error: "Conversation not found." } }));
    renderPage();

    expect(await screen.findByText("Conversation not found")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /new link/i })).toBeNull();
  });

  it("never sends the credentials of an agent logged in on this browser", async () => {
    useAuthStore.getState().setTokens("agent-access-jwt", "agent-refresh-jwt");
    serve((_url, init) =>
      init.method === "POST"
        ? { status: 201, body: { id: "m3" } }
        : { status: 200, body: CONVERSATION },
    );
    const user = userEvent.setup();
    renderPage();
    await user.type(await screen.findByLabelText(/your reply/i), "Hi");
    await user.click(screen.getByRole("button", { name: /^send$/i }));
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(1));

    for (const [, init] of fetchMock.mock.calls) {
      const headers = new Headers((init as RequestInit).headers);
      expect(headers.has("Authorization")).toBe(false);
      expect((init as RequestInit).credentials).toBe("omit");
    }
  });
});
