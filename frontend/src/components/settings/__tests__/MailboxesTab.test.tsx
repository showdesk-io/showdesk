/**
 * Tests for the email settings tab. Only the API client is mocked, so hooks and payloads
 * are the real ones.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, type AxiosResponse } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/api/client";
import type { InboundLogEntry, Mailbox } from "@/types";
import { MailboxesTab } from "../MailboxesTab";
import { safeConfirmationUrl } from "../forwarding";

vi.mock("@/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}));
vi.mock("react-hot-toast", () => ({
  default: { success: vi.fn(), error: vi.fn() },
}));

const client = vi.mocked(apiClient);

function mailbox(overrides: Partial<Mailbox> = {}): Mailbox {
  return {
    id: "m1",
    name: "Support",
    local_part: "acme-x7k2m9abcd",
    inbound_address: "acme-x7k2m9abcd@in.example.com",
    public_address: "support@acme.com",
    sends_from_public_address: false,
    forwarding_verified_at: null,
    default_team: null,
    is_active: true,
    created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-01T00:00:00Z",
    ...overrides,
  };
}

function logEntry(overrides: Partial<InboundLogEntry> = {}): InboundLogEntry {
  return {
    id: "i1",
    sender: "robot@example.org",
    subject: "Out of office",
    status: "ignored",
    reason: "auto_reply",
    received_at: "2026-11-02T10:00:00Z",
    processed_at: "2026-11-02T10:00:01Z",
    ...overrides,
  };
}

function refusal(data: unknown, status = 400): AxiosError {
  return new AxiosError("Request failed", "ERR_BAD_REQUEST", undefined, undefined, {
    status,
    data,
  } as AxiosResponse);
}

let mailboxes: Mailbox[];
let sendingDomainsEnabled: boolean;
let log: InboundLogEntry[];
type LogPage = { next: string | null; previous: string | null; results: InboundLogEntry[] };
/** Pages of the log by number, when a test pages it; a missing one is a 404. */
let pages: Record<number, LogPage | undefined> | null;

async function renderTab({ isAdmin = true }: { isAdmin?: boolean } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MailboxesTab isAdmin={isAdmin} />
    </QueryClientProvider>,
  );
  await screen.findByRole("heading", { name: "Email" });
  return userEvent.setup();
}

beforeEach(() => {
  vi.clearAllMocks();
  mailboxes = [mailbox()];
  sendingDomainsEnabled = false;
  log = [];
  pages = null;
  client.get.mockImplementation((url: string, config?: unknown) => {
    if (url === "/mailboxes/") return Promise.resolve({ data: mailboxes });
    if (url === "/organizations/")
      return Promise.resolve({
        data: { results: [{ id: "o1", sending_domains_enabled: sendingDomainsEnabled }] },
      });
    if (url === "/organization-domains/") return Promise.resolve({ data: { results: [] } });
    if (url === "/teams/")
      return Promise.resolve({ data: { results: [{ id: "team1", name: "Billing" }] } });
    if (url.endsWith("/inbound/")) {
      if (pages) {
        const page = pages[(config as { params: { page: number } }).params.page];
        return page
          ? Promise.resolve({ data: { count: 2, ...page } })
          : Promise.reject(refusal({ detail: "Invalid page." }, 404));
      }
      return Promise.resolve({ data: { count: log.length, next: null, previous: null, results: log } });
    }
    return Promise.reject(new Error(`unexpected ${url}`));
  });
  client.post.mockResolvedValue({ data: mailbox() });
  client.patch.mockResolvedValue({ data: mailbox() });
});

describe("safeConfirmationUrl", () => {
  it("keeps an https link to one of Google's two confirmation hosts", () => {
    expect(safeConfirmationUrl("https://mail.google.com/mail/vf-abc")).toBe(
      "https://mail.google.com/mail/vf-abc",
    );
    expect(safeConfirmationUrl("https://mail-settings.google.com/mail/vf-x")).not.toBeNull();
  });

  it("refuses anything else", () => {
    for (const url of [
      "http://mail.google.com/x",
      "https://mail.google.com.evil.example/x",
      "https://evil.example@mail.google.com/x",
      "https://mail.google.com:8443/x",
      "javascript:alert(1)",
      "not a url",
      "",
    ]) {
      expect(safeConfirmationUrl(url)).toBeNull();
    }
  });
});

describe("MailboxesTab", () => {
  it("shows the inbound address, with a copy button", async () => {
    const user = await renderTab();
    // userEvent's own clipboard, set up with it.
    const writeText = vi.spyOn(navigator.clipboard, "writeText");

    expect(
      screen.getByText("acme-x7k2m9abcd@in.example.com", { selector: "code" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Copy inbound address" }));
    expect(writeText).toHaveBeenCalledWith(
      "acme-x7k2m9abcd@in.example.com",
    );
  });

  it("creates a mailbox, and shows what the API refuses next to its field", async () => {
    const user = await renderTab();
    client.post.mockRejectedValueOnce(
      refusal({ public_address: ["Another mailbox already uses this address."] }),
    );

    await user.click(screen.getByRole("button", { name: /New mailbox/ }));
    const form = screen.getByRole("form", { name: "New mailbox" });
    await user.type(within(form).getByLabelText("Name"), "Billing");
    await user.type(within(form).getByLabelText("Public address"), "billing@acme.com");
    await user.selectOptions(within(form).getByLabelText("Default team"), "team1");
    await user.click(within(form).getByRole("button", { name: "Create" }));

    expect(client.post).toHaveBeenCalledWith("/mailboxes/", {
      name: "Billing",
      public_address: "billing@acme.com",
      default_team: "team1",
    });
    expect(
      await within(form).findByText("Another mailbox already uses this address."),
    ).toBeInTheDocument();
  });

  it("regenerates the address only once confirmed", async () => {
    const user = await renderTab();
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false);

    await user.click(screen.getByRole("button", { name: "New inbound address" }));
    expect(client.post).not.toHaveBeenCalled();

    confirm.mockReturnValueOnce(true);
    await user.click(screen.getByRole("button", { name: "New inbound address" }));
    expect(client.post).toHaveBeenCalledWith("/mailboxes/m1/regenerate-address/");
  });

  it("deactivates a mailbox", async () => {
    const user = await renderTab();

    await user.click(screen.getByRole("button", { name: "Deactivate" }));

    expect(client.patch).toHaveBeenCalledWith("/mailboxes/m1/", { is_active: false });
  });

  it("links a Gmail confirmation only to Google's hosts", async () => {
    mailboxes = [
      mailbox({
        forwarding_confirmation: {
          url: "https://mail.google.com/mail/vf-abc",
          code: "123456789",
          detected_at: "2026-11-02T10:00:00Z",
        },
      }),
      mailbox({
        id: "m2",
        name: "Billing",
        forwarding_confirmation: {
          url: "https://evil.example/mail/vf-abc",
          code: "987654321",
          detected_at: "2026-11-02T10:00:00Z",
        },
      }),
    ];
    await renderTab();

    expect(screen.getByText("123456789")).toBeInTheDocument();
    expect(screen.getByText("987654321")).toBeInTheDocument();
    const links = screen.getAllByRole("link", { name: /Confirm forwarding/ });
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "https://mail.google.com/mail/vf-abc",
    ]);
    expect(screen.queryByText(/evil\.example/)).not.toBeInTheDocument();
  });

  it("explains forwarding from Google Workspace and Microsoft 365", async () => {
    await renderTab();

    expect(screen.getByText(/Google Workspace/)).toBeInTheDocument();
    expect(screen.getByText(/anti-spam/)).toBeInTheDocument();
  });

  it("lists the ignored mails, and lets an admin replay a failed one", async () => {
    log = [
      logEntry(),
      logEntry({ id: "i2", subject: "Printer on fire", status: "failed", reason: "exception" }),
    ];
    const user = await renderTab();

    await user.click(screen.getByRole("button", { name: "Show received mail log" }));

    expect(await screen.findByText("Out of office", { selector: "td" })).toBeInTheDocument();
    expect(client.get).toHaveBeenCalledWith("/mailboxes/m1/inbound/", { params: { page: 1 } });
    const replays = screen.getAllByRole("button", { name: "Replay" });
    expect(replays).toHaveLength(1);
    await user.click(replays[0]!);
    await waitFor(() =>
      expect(client.post).toHaveBeenCalledWith("/inbound-emails/i2/replay/"),
    );
  });

  it("steps back a page when a replay empties the last one", async () => {
    pages = {
      1: { next: "page=2", previous: null, results: [logEntry()] },
      2: {
        next: null,
        previous: "page=1",
        results: [logEntry({ id: "i2", subject: "Printer on fire", status: "failed" })],
      },
    };
    const user = await renderTab();
    await user.click(screen.getByRole("button", { name: "Show received mail log" }));
    await user.click(await screen.findByRole("button", { name: "Older" }));
    await screen.findByText("Printer on fire", { selector: "td" });

    pages[2] = undefined;
    await user.click(screen.getByRole("button", { name: "Replay" }));

    await screen.findByText("Out of office", { selector: "td" });
    expect(client.get).toHaveBeenLastCalledWith("/mailboxes/m1/inbound/", {
      params: { page: 1 },
    });
  });

  it("keeps the pager on a page that can't be loaded", async () => {
    pages = {
      1: { next: "page=2", previous: null, results: [logEntry()] },
    };
    const user = await renderTab();
    await user.click(screen.getByRole("button", { name: "Show received mail log" }));
    await user.click(await screen.findByRole("button", { name: "Older" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Could not load/);
    await user.click(screen.getByRole("button", { name: "Newer" }));
    await screen.findByText("Out of office", { selector: "td" });
  });

  it("says which address replies are sent from", async () => {
    mailboxes = [
      mailbox(),
      mailbox({ id: "m2", name: "Billing", public_address: "billing@acme.com", sends_from_public_address: true }),
    ];
    await renderTab();

    expect(screen.getByRole("region", { name: "Support" })).toHaveTextContent(
      "Replies are sent from acme-x7k2m9abcd@in.example.com",
    );
    expect(screen.getByRole("region", { name: "Billing" })).toHaveTextContent(
      "Replies are sent from billing@acme.com",
    );
  });

  it("says where customers reply, and lets an admin reset it", async () => {
    mailboxes = [
      mailbox(),
      mailbox({ id: "m2", name: "Sales", public_address: "sales@acme.com", sends_from_public_address: true }),
      mailbox({
        id: "m3",
        name: "Billing",
        public_address: "billing@acme.com",
        sends_from_public_address: true,
        forwarding_verified_at: "2026-11-05T10:00:00Z",
      }),
    ];
    const user = await renderTab();
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false);

    expect(screen.getByRole("region", { name: "Support" })).not.toHaveTextContent("Customers reply");
    expect(screen.getByRole("region", { name: "Sales" })).toHaveTextContent(
      "Customers reply to a reply address of Showdesk (forward sales@acme.com here to have them reply to it)",
    );
    const billing = screen.getByRole("region", { name: "Billing" });
    expect(billing).toHaveTextContent("Customers reply to billing@acme.com");
    expect(within(screen.getByRole("region", { name: "Sales" })).queryByRole("button", { name: "Reset" })).toBeNull();

    await user.click(within(billing).getByRole("button", { name: "Reset" }));
    expect(client.post).not.toHaveBeenCalled();
    confirm.mockReturnValueOnce(true);
    await user.click(within(billing).getByRole("button", { name: "Reset" }));
    expect(client.post).toHaveBeenCalledWith("/mailboxes/m3/reset-forwarding/");
  });

  it("opens the send-from-your-domain wizard when the server can send from it", async () => {
    sendingDomainsEnabled = true;
    const user = await renderTab();

    await user.click(await screen.findByRole("button", { name: "Send from your domain" }));

    const toggle = screen.getByRole("button", { name: "Send from your domain" });
    expect(await screen.findByRole("region", { name: "Send from your domain" })).toHaveAttribute(
      "id",
      toggle.getAttribute("aria-controls"),
    );

    await user.click(screen.getByRole("button", { name: "Close send from your domain" }));
    expect(screen.queryByRole("region", { name: "Send from your domain" })).not.toBeInTheDocument();
    expect(toggle).toHaveFocus();
  });

  it("hides the wizard without a sending provider", async () => {
    await renderTab();
    await waitFor(() => expect(client.get).toHaveBeenCalledWith("/organizations/"));
    expect(screen.queryByRole("button", { name: "Send from your domain" })).not.toBeInTheDocument();
  });

  it("is read-only for agents", async () => {
    sendingDomainsEnabled = true;
    log = [logEntry({ status: "failed" })];
    const user = await renderTab({ isAdmin: false });

    expect(screen.queryByRole("button", { name: /New mailbox/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New inbound address" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Deactivate" })).not.toBeInTheDocument();
    await waitFor(() => expect(client.get).toHaveBeenCalledWith("/organizations/"));
    expect(screen.queryByRole("button", { name: "Send from your domain" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show received mail log" }));
    await screen.findByText("Out of office", { selector: "td" });
    expect(screen.queryByRole("button", { name: "Replay" })).not.toBeInTheDocument();
  });

  it("shows agents where customers reply, without a reset", async () => {
    mailboxes = [
      mailbox({ sends_from_public_address: true, forwarding_verified_at: "2026-11-05T10:00:00Z" }),
    ];
    await renderTab({ isAdmin: false });

    expect(screen.getByRole("region", { name: "Support" })).toHaveTextContent(
      "Customers reply to support@acme.com",
    );
    expect(screen.queryByRole("button", { name: "Reset" })).not.toBeInTheDocument();
  });
});
