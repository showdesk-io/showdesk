/**
 * Tests for the contact card of the ticket sidebar. Only the API client is mocked.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/api/client";
import type { ContactSummary, Ticket, TicketListItem } from "@/types";
import { ContactCard } from "../ContactCard";

vi.mock("@/api/client", () => ({
  apiClient: { get: vi.fn() },
}));

const client = vi.mocked(apiClient);

function makeContact(overrides: Partial<ContactSummary> = {}): ContactSummary {
  return {
    id: "c1",
    display_name: "Ada Lovelace",
    name: "Ada Lovelace",
    email: "ada@example.com",
    email_verified: true,
    declared_email: "",
    avatar_url: "",
    company_detail: null,
    is_anonymized: false,
    ...overrides,
  };
}

function makeTicket(overrides: Partial<Ticket> = {}): Ticket {
  return {
    id: "t1",
    requester_detail: null,
    requester_name: "Ada Lovelace",
    requester_email: "ada@example.com",
    sender_verified: true,
    ...overrides,
  } as Ticket;
}

const ticketsWithIds = (...ids: string[]) =>
  ids.map((id) => ({ id })) as TicketListItem[];

function renderCard(contact: ContactSummary, ticket: Ticket = makeTicket()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ContactCard contact={contact} ticket={ticket} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  client.get.mockResolvedValue({ data: ticketsWithIds("t1") });
});

describe("ContactCard", () => {
  it("links the contact's name to their page", () => {
    renderCard(makeContact());

    expect(screen.getByRole("heading", { name: "Contact" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ada Lovelace" })).toHaveAttribute(
      "href",
      "/contacts/c1",
    );
  });

  it("marks an unverified email, and not a verified one", () => {
    const { unmount } = renderCard(makeContact());
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    expect(screen.queryByText("Unverified")).not.toBeInTheDocument();
    unmount();

    renderCard(makeContact({ email_verified: false }));
    const line = screen.getByText("ada@example.com").parentElement as HTMLElement;
    expect(within(line).getByText("Unverified")).toBeInTheDocument();
  });

  it("labels a declared email and marks it unverified", () => {
    renderCard(makeContact({ email: "", email_verified: false, declared_email: "d@example.com" }));

    expect(screen.getByText("Declared (unverified)")).toBeInTheDocument();
    const line = screen.getByText("d@example.com").parentElement as HTMLElement;
    expect(within(line).getByText("Unverified")).toBeInTheDocument();
  });

  it("shows the company's logo, name and plan, linking to its page", () => {
    const { container } = renderCard(
      makeContact({
        company_detail: {
          id: "co1",
          name: "Analytical Engines",
          domain: "engines.example",
          logo_url: "https://cdn.example/logo.png",
          plan: "Enterprise",
        },
      }),
    );

    expect(screen.getByRole("link", { name: "Analytical Engines" })).toHaveAttribute(
      "href",
      "/companies/co1",
    );
    expect(screen.getByText("Enterprise")).toBeInTheDocument();
    expect(container.querySelector("img")).toHaveAttribute(
      "src",
      "https://cdn.example/logo.png",
    );
  });

  it("never loads a company logo that isn't http(s)", () => {
    const { container } = renderCard(
      makeContact({
        company_detail: {
          id: "co1",
          name: "Analytical Engines",
          domain: "",
          logo_url: "javascript:alert(1)",
          plan: "",
        },
      }),
    );

    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByRole("link", { name: /Analytical Engines/ })).toBeInTheDocument();
  });

  describe("other tickets", () => {
    it("counts the contact's tickets without the current one", async () => {
      client.get.mockResolvedValue({ data: ticketsWithIds("t1", "t2", "t3") });
      renderCard(makeContact());

      expect(await screen.findByText("Other tickets: 2")).toBeInTheDocument();
      expect(client.get).toHaveBeenCalledWith("/contacts/c1/tickets/");
    });

    it("counts them all when the current ticket isn't among them", async () => {
      client.get.mockResolvedValue({ data: ticketsWithIds("t2") });
      renderCard(makeContact());

      expect(await screen.findByText("Other tickets: 1")).toBeInTheDocument();
    });

    it("says nothing of a count it doesn't know yet", () => {
      client.get.mockReturnValue(new Promise(() => {}));
      renderCard(makeContact());

      expect(screen.getByText("Other tickets: —")).toBeInTheDocument();
    });

    it("doesn't take a failure for no ticket", async () => {
      client.get.mockRejectedValue(new Error("nope"));
      renderCard(makeContact());

      await waitFor(() => expect(client.get).toHaveBeenCalled());
      expect(await screen.findByText("Other tickets: —")).toBeInTheDocument();
      expect(screen.queryByText("Other tickets: 0")).not.toBeInTheDocument();
    });

    it("says when the API's limit makes the count a minimum", async () => {
      const ids = Array.from({ length: 100 }, (_, index) => `t${index + 1}`);
      client.get.mockResolvedValue({ data: ticketsWithIds(...ids) });
      renderCard(makeContact());

      expect(await screen.findByText("Other tickets: 99+")).toBeInTheDocument();
    });
  });

  describe("unverified sender hint", () => {
    it("shows for an unproven sender, even with a verified contact", () => {
      renderCard(makeContact(), makeTicket({ sender_verified: false }));

      expect(screen.getByText("Unverified sender")).toBeInTheDocument();
      expect(screen.getByText(/Nothing proves/)).toBeInTheDocument();
    });

    it.each([true, null])("doesn't show when sender_verified is %s", (value) => {
      renderCard(makeContact(), makeTicket({ sender_verified: value }));

      expect(screen.queryByText("Unverified sender")).not.toBeInTheDocument();
    });
  });

  describe("the ticket's requester", () => {
    it("shows who the ticket claims to be from when it isn't the contact", () => {
      renderCard(
        makeContact(),
        makeTicket({
          sender_verified: false,
          requester_name: "Mallory",
          requester_email: "mallory@example.com",
        }),
      );

      expect(screen.getByText("Requester on this ticket")).toBeInTheDocument();
      expect(screen.getByText("Mallory")).toBeInTheDocument();
      expect(screen.getByText("mallory@example.com")).toBeInTheDocument();
    });

    it("shows only what differs", () => {
      renderCard(makeContact(), makeTicket({ requester_name: "A. Lovelace" }));

      expect(screen.getByText("A. Lovelace")).toBeInTheDocument();
      expect(screen.getAllByText("ada@example.com")).toHaveLength(1);
    });

    it("shows nothing when it's the contact, whatever the case", () => {
      renderCard(
        makeContact(),
        makeTicket({ requester_name: "ada lovelace", requester_email: "ADA@Example.com" }),
      );

      expect(screen.queryByText("Requester on this ticket")).not.toBeInTheDocument();
    });

    it("shows nothing when the ticket names nobody", () => {
      renderCard(makeContact(), makeTicket({ requester_name: "", requester_email: "" }));

      expect(screen.queryByText("Requester on this ticket")).not.toBeInTheDocument();
    });

    it("doesn't take the contact's declared email for someone else", () => {
      renderCard(
        makeContact({ email: "", email_verified: false, declared_email: "d@example.com" }),
        makeTicket({ requester_email: "d@example.com" }),
      );

      expect(screen.queryByText("Requester on this ticket")).not.toBeInTheDocument();
    });

    it("falls back on the requester's account, as the sidebar did", () => {
      renderCard(
        makeContact(),
        makeTicket({
          requester_name: "",
          requester_email: "",
          requester_detail: {
            first_name: "Grace",
            last_name: "Hopper",
            email: "grace@agents.example",
          } as Ticket["requester_detail"],
        }),
      );

      expect(screen.getByText("Grace Hopper")).toBeInTheDocument();
      expect(screen.getByText("grace@agents.example")).toBeInTheDocument();
    });

    it("never marks the requester's address as the contact's unverified one", () => {
      renderCard(
        makeContact({ email_verified: false }),
        makeTicket({ requester_email: "mallory@example.com" }),
      );

      const line = screen.getByText("mallory@example.com").parentElement as HTMLElement;
      expect(within(line).queryByText("Unverified")).not.toBeInTheDocument();
    });
  });

  describe("a visitor who declares an address at the anonymization domain", () => {
    it("isn't taken for an anonymized contact", () => {
      renderCard(
        makeContact({
          display_name: "Mallory",
          name: "Mallory",
          email: "visitor@example.invalid",
          email_verified: false,
        }),
        makeTicket({
          sender_verified: false,
          requester_name: "Someone else",
          requester_email: "other@example.invalid",
        }),
      );

      expect(screen.getByRole("link", { name: "Mallory" })).toBeInTheDocument();
      expect(screen.getByText("visitor@example.invalid")).toBeInTheDocument();
      expect(screen.getByText("Unverified sender")).toBeInTheDocument();
      expect(screen.getByText("Requester on this ticket")).toBeInTheDocument();
      expect(screen.getByText("other@example.invalid")).toBeInTheDocument();
    });
  });

  describe("anonymized contact", () => {
    const anonymized = makeContact({
      display_name: "Anonymized contact",
      name: "Anonymized contact",
      email: "anonymized-abc@example.invalid",
      email_verified: false,
      is_anonymized: true,
    });

    it("links to the read-only page without the placeholder email", () => {
      renderCard(anonymized);

      expect(screen.getByRole("link", { name: "Anonymized contact" })).toHaveAttribute(
        "href",
        "/contacts/c1",
      );
      expect(screen.queryByText(/example\.invalid/)).not.toBeInTheDocument();
      expect(screen.queryByText("Unverified")).not.toBeInTheDocument();
    });

    it("goes by the flag, not the address", () => {
      renderCard({ ...anonymized, email: "ada@example.com" });

      expect(screen.getByRole("link", { name: "Anonymized contact" })).toBeInTheDocument();
      expect(screen.queryByText("ada@example.com")).not.toBeInTheDocument();
    });

    it("says it even if the contact was given another name since", () => {
      renderCard({ ...anonymized, display_name: "Someone", name: "Someone" });

      expect(screen.getByRole("link", { name: "Anonymized contact" })).toBeInTheDocument();
      expect(screen.queryByText("Someone")).not.toBeInTheDocument();
    });

    it("drops the requester and the hint, which no longer say anything", () => {
      renderCard(
        anonymized,
        makeTicket({
          sender_verified: false,
          requester_name: "Old name",
          requester_email: "old@example.com",
        }),
      );

      expect(screen.queryByText("Unverified sender")).not.toBeInTheDocument();
      expect(screen.queryByText("Requester on this ticket")).not.toBeInTheDocument();
      expect(screen.queryByText("old@example.com")).not.toBeInTheDocument();
    });
  });
});
