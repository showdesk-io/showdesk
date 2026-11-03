/**
 * Tests for what the ticket shows about who a ticket is from, and by which channel.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, type AxiosResponse } from "axios";
import toast from "react-hot-toast";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { uploadAttachment } from "@/api/attachments";
import { apiClient } from "@/api/client";
import type { ContactSummary, Ticket, TicketMessage } from "@/types";
import { TicketDetail } from "../TicketDetail";

vi.mock("@/api/client", () => ({
  apiClient: { get: vi.fn() },
}));
vi.mock("react-hot-toast", () => ({
  default: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("@/hooks/useAuth", () => ({
  useCurrentUser: () => ({ data: { id: "u1", role: "agent" } }),
}));
vi.mock("@/api/attachments", () => ({
  uploadAttachment: vi.fn(),
}));
vi.mock("@/api/users", () => ({
  fetchAgents: vi.fn().mockResolvedValue([]),
  fetchTeams: vi.fn().mockResolvedValue([]),
}));

const client = vi.mocked(apiClient);

const contact: ContactSummary = {
  id: "c1",
  display_name: "Ada Lovelace",
  name: "Ada Lovelace",
  email: "ada@example.com",
  email_verified: true,
  declared_email: "",
  avatar_url: "",
  company_detail: null,
  is_anonymized: false,
};

function makeTicket(overrides: Partial<Ticket> = {}): Ticket {
  return {
    id: "t1",
    reference: "SD-1",
    title: "Cannot log in",
    description: "",
    status: "open",
    priority: "medium",
    source: "widget",
    issue_type: "other",
    requester: null,
    requester_detail: null,
    requester_name: "Bob Requester",
    requester_email: "bob@example.com",
    contact: null,
    contact_detail: null,
    sender_verified: null,
    assigned_agent: null,
    assigned_agent_detail: null,
    assigned_team: null,
    tags_detail: [],
    context_url: "",
    context_metadata: {},
    messages: [],
    videos: [],
    created_at: "2026-02-01T00:00:00Z",
    updated_at: "2026-02-01T00:00:00Z",
    ...overrides,
  } as unknown as Ticket;
}

function renderDetail(ticket: Ticket, onSendMessage = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <TicketDetail ticket={ticket} onSendMessage={onSendMessage} isSending={false} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeMessage(overrides: Partial<TicketMessage> = {}): TicketMessage {
  return {
    id: "m1",
    ticket: "t1",
    author: null,
    author_detail: null,
    body: "Hello",
    message_type: "reply",
    sender_type: "user",
    body_type: "text",
    sender_name: "Ann",
    channel: "widget",
    external_sender: "",
    email_delivery_status: "",
    attachments: [],
    created_at: "2026-02-01T00:00:00Z",
    updated_at: "2026-02-01T00:00:00Z",
    ...overrides,
  };
}

const contactTicketsCalls = () =>
  client.get.mock.calls.filter(([url]) => String(url).startsWith("/contacts/"));

beforeEach(() => {
  vi.clearAllMocks();
  client.get.mockResolvedValue({ data: [] });
});

describe("TicketDetail sidebar", () => {
  it("shows the contact card instead of the requester when there's a contact", async () => {
    renderDetail(makeTicket({ contact: "c1", contact_detail: contact }));

    expect(screen.getByRole("heading", { name: "Contact" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Requester" })).not.toBeInTheDocument();
    expect(await screen.findByText("Other tickets: 0")).toBeInTheDocument();
    expect(client.get).toHaveBeenCalledWith("/contacts/c1/tickets/");
  });

  it("keeps the requester, and fetches nothing about contacts, without one", () => {
    renderDetail(makeTicket());

    expect(screen.getByRole("heading", { name: "Requester" })).toBeInTheDocument();
    expect(screen.getByText("Bob Requester")).toBeInTheDocument();
    expect(screen.getByText("bob@example.com")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Contact" })).not.toBeInTheDocument();
    expect(contactTicketsCalls()).toHaveLength(0);
  });

  it("doesn't show the placeholder of a ticket scrubbed with no contact", () => {
    renderDetail(
      makeTicket({
        requester_name: "Anonymized contact",
        requester_email: "anonymized-abc@example.invalid",
      }),
    );

    expect(screen.getByRole("heading", { name: "Requester" })).toBeInTheDocument();
    expect(screen.getByText("Anonymized contact")).toBeInTheDocument();
    expect(screen.queryByText(/example\.invalid/)).not.toBeInTheDocument();
  });
});

describe("TicketDetail messages", () => {
  const emailed = makeMessage({
    id: "0a1b2c3d-0000-0000-0000-000000000000",
    channel: "email",
    external_sender: '"Ann" <ann@example.org>',
    body: "From the mail",
  });

  it("badges each message with its channel, and shows a mail's sender", () => {
    renderDetail(
      makeTicket({
        messages: [emailed, makeMessage({ id: "m2", body: "From the widget" })],
      }),
    );

    const fromMail = screen.getByText("From the mail").closest("[data-message]") as HTMLElement;
    const fromWidget = screen.getByText("From the widget").closest("[data-message]") as HTMLElement;
    expect(within(fromMail).getByText("Email")).toBeInTheDocument();
    expect(within(fromMail).getByText('"Ann" <ann@example.org>')).toBeInTheDocument();
    expect(within(fromWidget).getByText("Widget")).toBeInTheDocument();
    expect(
      within(fromWidget).queryByRole("button", { name: "View original" }),
    ).not.toBeInTheDocument();
  });

  it("downloads the original mail through the authenticated client", async () => {
    // jsdom has no blob URLs: define them, so that they can be spied on and restored.
    Object.assign(URL, { createObjectURL: () => "", revokeObjectURL: () => {} });
    const create = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:original");
    const revoke = vi.spyOn(URL, "revokeObjectURL");
    const attached: boolean[] = [];
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        attached.push(this.isConnected);
      });
    client.get.mockImplementation((url: string) =>
      Promise.resolve({ data: url.endsWith("/original/") ? new Blob(["raw"]) : [] }),
    );
    renderDetail(makeTicket({ messages: [emailed] }));

    try {
      await userEvent.setup().click(screen.getByRole("button", { name: "View original" }));

      await waitFor(() => expect(click).toHaveBeenCalled());
      expect(client.get).toHaveBeenCalledWith(
        `/tickets/t1/messages/${emailed.id}/original/`,
        { responseType: "blob" },
      );
      expect(create).toHaveBeenCalled();
      // Clicked while in the document, then removed from it.
      expect(attached).toEqual([true]);
      expect(document.querySelector("a[download]")).toBeNull();
      // Revoked later, not right away: some browsers abort the download otherwise.
      expect(revoke).not.toHaveBeenCalled();
      await waitFor(() => expect(revoke).toHaveBeenCalledWith("blob:original"), {
        timeout: 2000,
      });
    } finally {
      create.mockRestore();
      revoke.mockRestore();
      click.mockRestore();
    }
  });

  it("says the original mail is gone only on a 404", async () => {
    const failWith = (status: number) =>
      client.get.mockImplementation((url: string) =>
        url.endsWith("/original/")
          ? Promise.reject(
              new AxiosError("Failed", "ERR_BAD_RESPONSE", undefined, undefined, {
                status,
              } as AxiosResponse),
            )
          : Promise.resolve({ data: [] }),
      );
    renderDetail(makeTicket({ messages: [emailed] }));
    const user = userEvent.setup();

    failWith(404);
    await user.click(screen.getByRole("button", { name: "View original" }));
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("The original mail is no longer available."),
    );

    failWith(500);
    await user.click(screen.getByRole("button", { name: "View original" }));
    await waitFor(() =>
      expect(toast.error).toHaveBeenLastCalledWith("Could not download the original mail."),
    );
  });

  it("says when a reply couldn't be delivered by email", () => {
    renderDetail(
      makeTicket({
        messages: [
          makeMessage({
            sender_type: "agent",
            channel: "agent",
            email_delivery_status: "failed",
          }),
        ],
      }),
    );

    expect(screen.getByText(/Not delivered by email/)).toBeInTheDocument();
  });
});

describe("TicketDetail reply with files", () => {
  it("uploads the files, then sends the reply naming them", async () => {
    const upload = vi.mocked(uploadAttachment);
    upload
      .mockResolvedValueOnce({ id: "a1" } as Awaited<ReturnType<typeof uploadAttachment>>)
      .mockResolvedValueOnce({ id: "a2" } as Awaited<ReturnType<typeof uploadAttachment>>);
    const onSendMessage = vi.fn();
    const user = userEvent.setup();
    const { container } = renderDetail(makeTicket(), onSendMessage);

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, [
      new File(["%PDF"], "invoice.pdf", { type: "application/pdf" }),
      new File(["png"], "shot.png", { type: "image/png" }),
    ]);
    await user.type(screen.getByPlaceholderText(/Write a reply/), "Here you go");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(onSendMessage).toHaveBeenCalled());
    // Uploaded to the ticket first: the reply links them before it's mailed.
    expect(upload.mock.calls.map(([data]) => [data.ticket, data.message])).toEqual([
      ["t1", undefined],
      ["t1", undefined],
    ]);
    expect(onSendMessage).toHaveBeenCalledWith("Here you go", "reply", ["a1", "a2"]);
    expect(upload.mock.invocationCallOrder[1]).toBeLessThan(
      onSendMessage.mock.invocationCallOrder[0] ?? 0,
    );
  });

  it("keeps the reply when an upload fails, and sends files alone", async () => {
    const upload = vi.mocked(uploadAttachment);
    upload.mockRejectedValueOnce(new Error("down"));
    const onSendMessage = vi.fn();
    const user = userEvent.setup();
    const { container } = renderDetail(makeTicket(), onSendMessage);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, new File(["x"], "a.txt", { type: "text/plain" }));

    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(onSendMessage).not.toHaveBeenCalled();
    expect(screen.getByText("a.txt")).toBeInTheDocument();

    upload.mockResolvedValueOnce({ id: "a9" } as Awaited<ReturnType<typeof uploadAttachment>>);
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(onSendMessage).toHaveBeenCalledWith("", "reply", ["a9"]));
  });

  it("keeps the reply and its uploaded files when sending it fails", async () => {
    const upload = vi.mocked(uploadAttachment);
    upload.mockResolvedValueOnce({ id: "a1" } as Awaited<ReturnType<typeof uploadAttachment>>);
    const onSendMessage = vi
      .fn()
      .mockRejectedValueOnce(new Error("down"))
      .mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    const { container } = renderDetail(makeTicket(), onSendMessage);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, new File(["x"], "a.txt", { type: "text/plain" }));
    await user.type(screen.getByPlaceholderText(/Write a reply/), "Hi");

    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(onSendMessage).toHaveBeenCalledTimes(1));
    expect(screen.getByText("a.txt")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Write a reply/)).toHaveValue("Hi");

    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(onSendMessage).toHaveBeenCalledTimes(2));
    expect(onSendMessage).toHaveBeenLastCalledWith("Hi", "reply", ["a1"]);
    expect(upload).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByText("a.txt")).not.toBeInTheDocument());
  });
});
