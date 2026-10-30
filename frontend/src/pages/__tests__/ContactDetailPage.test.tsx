/**
 * Tests for the contact detail page. Only the API client and the current user are mocked,
 * so hooks and payloads are the real ones.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, type AxiosResponse } from "axios";
import toast from "react-hot-toast";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/api/client";
import type {
  AttributeDef,
  Company,
  Contact,
  ContactNote,
  TicketListItem,
} from "@/types";
import { ContactDetailPage } from "../ContactDetailPage";

const auth = vi.hoisted(() => ({ role: "admin" }));

vi.mock("@/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("react-hot-toast", () => ({
  default: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("@/hooks/useAuth", () => ({
  useCurrentUser: () => ({ data: { id: "u1", role: auth.role } }),
}));

const client = vi.mocked(apiClient);

function makeContact(overrides: Partial<Contact> = {}): Contact {
  return {
    id: "c1",
    display_name: "Ada Lovelace",
    name: "Ada Lovelace",
    email: "ada@example.com",
    email_verified: true,
    email_verified_at: "2026-01-01T00:00:00Z",
    declared_email: "",
    external_id: "ext-42",
    phone: "+33123456789",
    avatar_url: "",
    job_title: "",
    locale: "",
    timezone: "",
    company: null,
    company_detail: null,
    first_seen_at: "2026-01-02T10:00:00Z",
    last_seen_at: "2026-03-04T10:00:00Z",
    last_contacted_at: null,
    is_unsubscribed: false,
    is_anonymized: false,
    attributes: {},
    tickets_count: 7,
    open_tickets_count: 3,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeTicket(overrides: Partial<TicketListItem> = {}): TicketListItem {
  return {
    id: "t1",
    reference: "SD-1",
    title: "Cannot log in",
    status: "open",
    created_at: "2026-02-01T00:00:00Z",
    updated_at: "2026-02-01T00:00:00Z",
    ...overrides,
  } as TicketListItem;
}

function makeNote(overrides: Partial<ContactNote> = {}): ContactNote {
  return {
    id: "n1",
    body: "Prefers email",
    author: "u2",
    author_name: "Grace Hopper",
    created_at: "2026-02-15T00:00:00Z",
    ...overrides,
  };
}

function attribute(overrides: Partial<AttributeDef>): AttributeDef {
  return {
    id: overrides.key ?? "a",
    key: "a",
    label: "A",
    type: "string",
    description: "",
    options: [],
    is_archived: false,
    position: 0,
    ...overrides,
  };
}

function refusal(status: number, data: unknown): AxiosError {
  return new AxiosError("Request failed", "ERR_BAD_REQUEST", undefined, undefined, {
    status,
    data,
  } as AxiosResponse);
}

let contact: Contact;
let tickets: TicketListItem[];
let notes: ContactNote[];
let attributeDefs: AttributeDef[];
let company: Partial<Company>;
let refused: Record<string, AxiosError>;

const gets = (url: string) => client.get.mock.calls.filter(([called]) => called === url);

function CurrentLocation() {
  const { pathname } = useLocation();
  return <div data-testid="location">{pathname}</div>;
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/contacts/c1"]}>
        <CurrentLocation />
        <Routes>
          <Route path="contacts" element={null} />
          <Route path="contacts/:id" element={<ContactDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const loaded = () => screen.findByRole("heading", { name: "Ada Lovelace" });

/** A PATCH answers like the API: attributes merged, what's sent applied. */
function patchLikeTheApi(extra: Partial<Contact> = {}) {
  client.patch.mockImplementation(async (_url: string, data: unknown) => {
    const { attributes, ...fields } = data as Partial<Contact>;
    contact = {
      ...contact,
      ...fields,
      ...extra,
      attributes: { ...contact.attributes, ...attributes },
    };
    return { data: contact };
  });
}

beforeEach(() => {
  vi.resetAllMocks();
  auth.role = "admin";
  contact = makeContact();
  tickets = [makeTicket()];
  notes = [makeNote()];
  attributeDefs = [];
  company = { id: "co1", mrr_cents: 123450, plan: "pro", name: "Acme" };
  refused = {};
  client.get.mockImplementation(async (url: string) => {
    if (refused[url]) throw refused[url];
    if (url === "/contacts/c1/") return { data: contact };
    if (url === "/contacts/c1/tickets/") return { data: tickets };
    if (url === "/contacts/c1/notes/") return { data: notes };
    if (url === "/contact-attributes/") return { data: attributeDefs };
    if (url === "/companies/co1/") return { data: company };
    throw new Error(`Unexpected request: ${url}`);
  });
});

describe("page states", () => {
  it("shows a loading state", async () => {
    client.get.mockImplementation(() => new Promise(() => {}));
    renderPage();

    expect(await screen.findByRole("status", { name: "Loading contact" })).toBeVisible();
  });

  it("shows a not-found state with a link back on a 404", async () => {
    refused["/contacts/c1/"] = refusal(404, { detail: "Not found." });
    renderPage();

    expect(await screen.findByText("Contact not found.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to contacts" })).toHaveAttribute(
      "href",
      "/contacts",
    );
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("shows an error on anything else, and tries again on demand", async () => {
    const user = userEvent.setup();
    refused["/contacts/c1/"] = refusal(500, {});
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load this contact.");
    expect(screen.queryByText("Contact not found.")).not.toBeInTheDocument();

    delete refused["/contacts/c1/"];
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await loaded()).toBeInTheDocument();
  });
});

describe("profile", () => {
  it("shows the contact, with a link back to the list", async () => {
    renderPage();

    await loaded();
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    expect(screen.getByText("+33123456789")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to contacts" })).toHaveAttribute(
      "href",
      "/contacts",
    );
  });

  it("shows the external id read-only", async () => {
    renderPage();

    await loaded();
    expect(screen.getByText("ext-42")).toBeInTheDocument();
    expect(screen.getByText("ext-42").tagName).toBe("CODE");
    expect(
      screen.queryByRole("button", { name: "Edit external id" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "External ID" })).not.toBeInTheDocument();
  });

  it("shows the stats, and the company's plan and MRR with a link", async () => {
    contact = makeContact({
      company: "co1",
      company_detail: { id: "co1", name: "Acme", domain: "", logo_url: "", plan: "pro" },
    });
    renderPage();

    await loaded();
    expect(screen.getByText("Total tickets").nextElementSibling).toHaveTextContent("7");
    expect(screen.getByText("Open tickets").nextElementSibling).toHaveTextContent("3");
    expect(screen.getByText("First seen").nextElementSibling).toHaveTextContent("Jan 2, 2026");
    expect(screen.getByText("Last seen").nextElementSibling).toHaveTextContent("Mar 4, 2026");
    for (const name of ["Profile", "Overview"]) {
      expect(
        within(screen.getByRole("region", { name })).getByRole("link", { name: "Acme" }),
      ).toHaveAttribute("href", "/companies/co1");
    }
    expect(screen.getByText("Plan").nextElementSibling).toHaveTextContent("pro");
    expect(await screen.findByText("1234.50")).toBeInTheDocument();
  });

  it("doesn't ask for a company when there is none", async () => {
    renderPage();

    await loaded();
    expect(screen.queryByText("Plan")).not.toBeInTheDocument();
    expect(gets("/companies/co1/")).toHaveLength(0);
  });

  it("doesn't render a javascript: avatar", async () => {
    contact = makeContact({ avatar_url: "javascript:alert(1)" });
    const { container } = renderPage();

    await loaded();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("AL")).toBeInTheDocument();
  });
});

describe("email area", () => {
  it("marks a verified email", async () => {
    renderPage();

    const email = await screen.findByText("ada@example.com");
    expect(within(email.parentElement!).getByText("Verified")).toBeInTheDocument();
    expect(screen.queryByText("Unverified")).not.toBeInTheDocument();
  });

  it("badges an unverified email", async () => {
    contact = makeContact({ email_verified: false, email_verified_at: null });
    renderPage();

    const email = await screen.findByText("ada@example.com");
    expect(within(email.parentElement!).getByText("Unverified")).toBeInTheDocument();
    expect(screen.queryByText("Verified")).not.toBeInTheDocument();
  });

  it("shows the declared email as such, read-only", async () => {
    contact = makeContact({ declared_email: "said@example.com" });
    renderPage();

    await loaded();
    const label = screen.getByText("Declared (unverified)");
    expect(label.nextElementSibling).toHaveTextContent("said@example.com");
    expect(
      screen.queryByRole("button", { name: "Edit declared (unverified)" }),
    ).not.toBeInTheDocument();
  });

  it("leaves out a declared email that is the email", async () => {
    contact = makeContact({ declared_email: "ada@example.com" });
    renderPage();

    await loaded();
    expect(screen.queryByText("Declared (unverified)")).not.toBeInTheDocument();
  });

  it("reflects the response when a changed email loses its verification", async () => {
    const user = userEvent.setup();
    patchLikeTheApi({ email_verified: false, email_verified_at: null });
    renderPage();
    await loaded();

    await user.click(screen.getByRole("button", { name: "Edit email" }));
    const input = screen.getByRole("textbox", { name: "Email" });
    await user.clear(input);
    await user.type(input, "new@example.com{Enter}");

    await waitFor(() =>
      expect(client.patch).toHaveBeenCalledWith("/contacts/c1/", {
        email: "new@example.com",
      }),
    );
    const email = await screen.findByText("new@example.com");
    expect(within(email.parentElement!).getByText("Unverified")).toBeInTheDocument();
    expect(screen.queryByText("Verified")).not.toBeInTheDocument();
  });
});

describe("inline edit", () => {
  it("saves on blur", async () => {
    const user = userEvent.setup();
    patchLikeTheApi();
    renderPage();
    await loaded();

    await user.click(screen.getByRole("button", { name: "Edit phone" }));
    const input = screen.getByRole("textbox", { name: "Phone" });
    await user.clear(input);
    await user.type(input, "+33999");
    await user.tab();

    await waitFor(() =>
      expect(client.patch).toHaveBeenCalledWith("/contacts/c1/", { phone: "+33999" }),
    );
    expect(await screen.findByText("+33999")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Phone" })).not.toBeInTheDocument();
    expect(client.patch).toHaveBeenCalledTimes(1);
  });

  it("saves the name once on Enter", async () => {
    const user = userEvent.setup();
    patchLikeTheApi({ display_name: "Countess" });
    renderPage();
    await loaded();

    await user.click(screen.getByRole("button", { name: "Edit name" }));
    const input = screen.getByRole("textbox", { name: "Name" });
    await user.clear(input);
    await user.type(input, "Countess{Enter}");

    expect(await screen.findByRole("heading", { name: "Countess" })).toBeInTheDocument();
    expect(client.patch).toHaveBeenCalledTimes(1);
    expect(client.patch).toHaveBeenCalledWith("/contacts/c1/", { name: "Countess" });
  });

  it("doesn't save on Escape", async () => {
    const user = userEvent.setup();
    renderPage();
    await loaded();

    await user.click(screen.getByRole("button", { name: "Edit name" }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), " changed{Escape}");

    expect(screen.queryByRole("textbox", { name: "Name" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Ada Lovelace" })).toBeInTheDocument();
    expect(client.patch).not.toHaveBeenCalled();
  });

  it("doesn't save what didn't change", async () => {
    const user = userEvent.setup();
    renderPage();
    await loaded();

    await user.click(screen.getByRole("button", { name: "Edit name" }));
    await user.tab();

    expect(screen.queryByRole("textbox", { name: "Name" })).not.toBeInTheDocument();
    expect(client.patch).not.toHaveBeenCalled();
  });

  it("shows a 400 next to the field and keeps the input", async () => {
    const user = userEvent.setup();
    client.patch.mockRejectedValue(
      refusal(400, { email: ["Another contact already uses this value."] }),
    );
    renderPage();
    await loaded();

    await user.click(screen.getByRole("button", { name: "Edit email" }));
    const input = screen.getByRole("textbox", { name: "Email" });
    await user.clear(input);
    await user.type(input, "taken@example.com{Enter}");

    expect(
      await screen.findByText("Another contact already uses this value."),
    ).toBeInTheDocument();
    expect(input).toHaveValue("taken@example.com");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("Another contact already uses this value.");
  });

  it("says so when a save fails for no reason the API gives", async () => {
    const user = userEvent.setup();
    client.patch.mockRejectedValue(new AxiosError("Network Error"));
    renderPage();
    await loaded();

    await user.click(screen.getByRole("button", { name: "Edit phone" }));
    await user.type(screen.getByRole("textbox", { name: "Phone" }), "1{Enter}");

    expect(await screen.findByText("Could not save this change.")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Phone" })).toHaveValue("+331234567891");
  });

  it("on a 409, shows a toast and refreshes into the read-only state", async () => {
    const user = userEvent.setup();
    client.patch.mockImplementation(async () => {
      contact = makeContact({
        name: "Anonymized contact",
        display_name: "Anonymized contact",
        is_anonymized: true,
      });
      throw refusal(409, { detail: "This contact has been anonymized." });
    });
    renderPage();
    await loaded();

    await user.click(screen.getByRole("button", { name: "Edit name" }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), "x{Enter}");

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("This contact has been anonymized."),
    );
    expect(
      await screen.findByRole("heading", { name: "Anonymized contact" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Name" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit name" })).not.toBeInTheDocument();
  });
});

describe("attribute editor", () => {
  const allTypes = () => [
    attribute({ key: "nick", label: "Nickname", type: "string", position: 0 }),
    attribute({ key: "seats", label: "Seats", type: "number", position: 1 }),
    attribute({ key: "beta", label: "Beta", type: "boolean", position: 2 }),
    attribute({ key: "since", label: "Since", type: "date", position: 3 }),
    attribute({ key: "tier", label: "Tier", type: "enum", options: ["gold", "silver"], position: 4 }),
    attribute({ key: "site", label: "Site", type: "url", position: 5 }),
  ];

  it("has one typed input per live definition, filled in", async () => {
    attributeDefs = allTypes();
    contact = makeContact({
      attributes: {
        nick: "Ada",
        seats: 3,
        beta: true,
        since: "2026-01-15",
        tier: "gold",
        site: "https://ada.dev",
      },
    });
    renderPage();

    expect(await screen.findByRole("textbox", { name: "Nickname" })).toHaveValue("Ada");
    expect(screen.getByRole("spinbutton", { name: "Seats" })).toHaveValue(3);
    expect(screen.getByRole("checkbox", { name: "Beta" })).toBeChecked();
    expect(screen.getByLabelText("Since")).toHaveValue("2026-01-15");
    expect(screen.getByLabelText("Since")).toHaveAttribute("type", "date");
    expect(screen.getByRole("combobox", { name: "Tier" })).toHaveValue("gold");
    expect(screen.getByRole("textbox", { name: "Site" })).toHaveAttribute("type", "url");
  });

  it("saves text on blur with the attribute payload only", async () => {
    const user = userEvent.setup();
    attributeDefs = allTypes();
    patchLikeTheApi();
    renderPage();

    await user.type(await screen.findByRole("textbox", { name: "Nickname" }), "Ada");
    expect(client.patch).not.toHaveBeenCalled();
    await user.tab();

    await waitFor(() =>
      expect(client.patch).toHaveBeenCalledWith("/contacts/c1/", {
        attributes: { nick: "Ada" },
      }),
    );
    expect(client.patch).toHaveBeenCalledTimes(1);
  });

  it("sends a number as a number", async () => {
    const user = userEvent.setup();
    attributeDefs = allTypes();
    patchLikeTheApi();
    renderPage();

    await user.type(await screen.findByRole("spinbutton", { name: "Seats" }), "12{Enter}");

    await waitFor(() =>
      expect(client.patch).toHaveBeenCalledWith("/contacts/c1/", {
        attributes: { seats: 12 },
      }),
    );
  });

  it("sends a date", async () => {
    const user = userEvent.setup();
    attributeDefs = allTypes();
    patchLikeTheApi();
    renderPage();

    await screen.findByLabelText("Since");
    await user.type(screen.getByLabelText("Since"), "2026-02-03");
    await user.tab();

    await waitFor(() =>
      expect(client.patch).toHaveBeenCalledWith("/contacts/c1/", {
        attributes: { since: "2026-02-03" },
      }),
    );
  });

  it("saves an enum on change, and its empty choice clears it", async () => {
    const user = userEvent.setup();
    attributeDefs = allTypes();
    contact = makeContact({ attributes: { tier: "gold" } });
    patchLikeTheApi();
    renderPage();

    const select = await screen.findByRole("combobox", { name: "Tier" });
    expect(within(select).getByRole("option", { name: "Not set" })).toHaveValue("");

    await user.selectOptions(select, "silver");
    await waitFor(() =>
      expect(client.patch).toHaveBeenLastCalledWith("/contacts/c1/", {
        attributes: { tier: "silver" },
      }),
    );

    await user.selectOptions(select, "Not set");
    await waitFor(() =>
      expect(client.patch).toHaveBeenLastCalledWith("/contacts/c1/", {
        attributes: { tier: null },
      }),
    );
    await waitFor(() => expect(select).toHaveValue(""));
  });

  it("keeps an enum value whose option is gone on screen", async () => {
    attributeDefs = allTypes();
    contact = makeContact({ attributes: { tier: "bronze" } });
    renderPage();

    expect(await screen.findByRole("combobox", { name: "Tier" })).toHaveValue("bronze");
  });

  it("sends null when a field is cleared", async () => {
    const user = userEvent.setup();
    attributeDefs = allTypes();
    contact = makeContact({ attributes: { nick: "Ada", seats: 3 } });
    patchLikeTheApi();
    renderPage();

    await user.clear(await screen.findByRole("textbox", { name: "Nickname" }));
    await user.tab();
    await waitFor(() =>
      expect(client.patch).toHaveBeenLastCalledWith("/contacts/c1/", {
        attributes: { nick: null },
      }),
    );

    await user.clear(screen.getByRole("spinbutton", { name: "Seats" }));
    await user.tab();
    await waitFor(() =>
      expect(client.patch).toHaveBeenLastCalledWith("/contacts/c1/", {
        attributes: { seats: null },
      }),
    );
  });

  it("saves a boolean on change, unset until set, and can clear it", async () => {
    const user = userEvent.setup();
    attributeDefs = allTypes();
    patchLikeTheApi();
    renderPage();

    const box = await screen.findByRole("checkbox", { name: "Beta" });
    expect(box).toBePartiallyChecked();
    expect(screen.queryByRole("button", { name: "Clear Beta" })).not.toBeInTheDocument();

    await user.click(box);
    await waitFor(() =>
      expect(client.patch).toHaveBeenLastCalledWith("/contacts/c1/", {
        attributes: { beta: true },
      }),
    );
    await waitFor(() => expect(box).toBeChecked());

    await user.click(await screen.findByRole("button", { name: "Clear Beta" }));
    await waitFor(() =>
      expect(client.patch).toHaveBeenLastCalledWith("/contacts/c1/", {
        attributes: { beta: null },
      }),
    );
    await waitFor(() => expect(box).toBePartiallyChecked());
  });

  it("can set a boolean to false", async () => {
    const user = userEvent.setup();
    attributeDefs = allTypes();
    contact = makeContact({ attributes: { beta: true } });
    patchLikeTheApi();
    renderPage();

    await user.click(await screen.findByRole("checkbox", { name: "Beta" }));
    await waitFor(() =>
      expect(client.patch).toHaveBeenCalledWith("/contacts/c1/", {
        attributes: { beta: false },
      }),
    );
    await waitFor(() =>
      expect(screen.getByRole("checkbox", { name: "Beta" })).not.toBeChecked(),
    );
  });

  it("doesn't save what didn't change", async () => {
    const user = userEvent.setup();
    attributeDefs = allTypes();
    contact = makeContact({ attributes: { nick: "Ada" } });
    renderPage();

    await user.click(await screen.findByRole("textbox", { name: "Nickname" }));
    await user.tab();

    expect(client.patch).not.toHaveBeenCalled();
  });

  it("doesn't take what the browser can't read as a number for a cleared field", async () => {
    const user = userEvent.setup();
    attributeDefs = allTypes();
    contact = makeContact({ attributes: { seats: 3 } });
    renderPage();

    const seats = await screen.findByRole("spinbutton", { name: "Seats" });
    await user.click(seats);
    Object.defineProperty(seats, "validity", { value: { badInput: true } });
    await user.tab();

    expect(await screen.findByText("Not a valid number value.")).toBeInTheDocument();
    expect(client.patch).not.toHaveBeenCalled();
  });

  it("survives attributes that aren't an object", async () => {
    attributeDefs = allTypes();
    contact = makeContact({ attributes: "nope" as unknown as Record<string, unknown> });
    renderPage();

    expect(await screen.findByRole("textbox", { name: "Nickname" })).toHaveValue("");
  });

  it("shows a 400 next to that field and keeps the input, leaving the others alone", async () => {
    const user = userEvent.setup();
    attributeDefs = allTypes();
    client.patch.mockRejectedValue(
      refusal(400, { attributes: { site: ["Not a valid url value."] } }),
    );
    renderPage();

    const site = await screen.findByRole("textbox", { name: "Site" });
    await user.type(site, "nope");
    await user.tab();

    expect(await screen.findByText("Not a valid url value.")).toBeInTheDocument();
    expect(site).toHaveValue("nope");
    expect(site).toHaveAttribute("aria-invalid", "true");
    expect(site).toHaveAccessibleDescription("Not a valid url value.");
    expect(screen.getByRole("textbox", { name: "Nickname" })).not.toHaveAttribute(
      "aria-invalid",
    );

    client.patch.mockResolvedValue({ data: contact });
    await user.clear(site);
    await user.type(site, "https://ada.dev");
    await user.tab();
    await waitFor(() =>
      expect(screen.queryByText("Not a valid url value.")).not.toBeInTheDocument(),
    );
  });

  it("shows an archived definition's value read-only, under its raw key", async () => {
    attributeDefs = [
      attribute({ key: "old_plan", label: "Old plan", is_archived: true }),
      attribute({ key: "old_site", label: "Old site", type: "url", is_archived: true }),
      attribute({ key: "unused", label: "Unused", is_archived: true }),
    ];
    contact = makeContact({
      attributes: { old_plan: "legacy", old_site: "https://old.test/" },
    });
    renderPage();

    const key = await screen.findByText("old_plan");
    expect(key.nextElementSibling).toHaveTextContent("legacy");
    expect(screen.queryByText("Old plan")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /plan/i })).not.toBeInTheDocument();
    expect(screen.queryByText("unused")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "https://old.test/" })).toHaveAttribute(
      "href",
      "https://old.test/",
    );
  });

  it("links a url attribute only when it is http(s)", async () => {
    attributeDefs = [
      attribute({ key: "good", label: "Good", type: "url" }),
      attribute({ key: "bad", label: "Bad", type: "url" }),
      attribute({ key: "bad_old", label: "Bad old", type: "url", is_archived: true }),
    ];
    contact = makeContact({
      attributes: {
        good: "https://ada.dev/",
        bad: "javascript:alert(1)",
        bad_old: "javascript:alert(2)",
      },
    });
    const { container } = renderPage();

    expect(await screen.findByRole("link", { name: "Open Good" })).toHaveAttribute(
      "href",
      "https://ada.dev/",
    );
    expect(screen.queryByRole("link", { name: "Open Bad" })).not.toBeInTheDocument();
    expect(screen.getByText("javascript:alert(2)").tagName).not.toBe("A");
    expect(container.querySelector('a[href^="javascript"]')).toBeNull();
  });

  it("shows loading and error states for the definitions", async () => {
    const user = userEvent.setup();
    refused["/contact-attributes/"] = refusal(500, {});
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load attributes.");

    delete refused["/contact-attributes/"];
    attributeDefs = allTypes();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("textbox", { name: "Nickname" })).toBeInTheDocument();
  });

  it("shows a loading state while the definitions are on their way", async () => {
    const get = client.get.getMockImplementation()!;
    client.get.mockImplementation((url: string, config) =>
      url === "/contact-attributes/" ? new Promise(() => {}) : get(url, config),
    );
    renderPage();

    expect(await screen.findByRole("status", { name: "Loading attributes" })).toBeVisible();
  });
});

describe("timeline", () => {
  const items = () =>
    within(screen.getByRole("list", { name: "Timeline" })).getAllByRole("listitem");

  beforeEach(() => {
    tickets = [
      makeTicket({ id: "t1", reference: "SD-1", title: "Old ticket", updated_at: "2026-01-10T00:00:00Z" }),
      makeTicket({ id: "t2", reference: "SD-2", title: "New ticket", status: "resolved", updated_at: "2026-03-10T00:00:00Z" }),
    ];
    notes = [makeNote({ id: "n1", body: "Middle note", created_at: "2026-02-10T00:00:00Z" })];
  });

  it("merges tickets and notes by date, newest first", async () => {
    renderPage();

    await screen.findByText("Middle note");
    const shown = items();
    expect(shown).toHaveLength(3);
    expect(shown[0]).toHaveTextContent("New ticket");
    expect(shown[1]).toHaveTextContent("Middle note");
    expect(shown[2]).toHaveTextContent("Old ticket");
  });

  it("shows a ticket's reference, title, status and link", async () => {
    renderPage();

    const link = await screen.findByRole("link", { name: "SD-2 New ticket" });
    expect(link).toHaveAttribute("href", "/tickets/t2");
    expect(within(link.closest("li")!).getByText("resolved")).toBeInTheDocument();
  });

  it("filters on tickets or notes", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Middle note");
    const group = screen.getByRole("group", { name: "Filter timeline" });
    expect(within(group).getByRole("button", { name: "All" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await user.click(within(group).getByRole("button", { name: "Tickets" }));
    expect(items()).toHaveLength(2);
    expect(screen.queryByText("Middle note")).not.toBeInTheDocument();
    expect(within(group).getByRole("button", { name: "Tickets" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await user.click(within(group).getByRole("button", { name: "Notes" }));
    expect(items()).toHaveLength(1);
    expect(screen.queryByText("New ticket")).not.toBeInTheDocument();
  });

  it("says when the tickets may be cut off, at exactly the cap", async () => {
    tickets = Array.from({ length: 100 }, (_, i) =>
      makeTicket({ id: `t${i}`, reference: `SD-${i}`, title: `Ticket ${i}` }),
    );
    renderPage();

    expect(await screen.findByText("Showing the latest 100")).toBeInTheDocument();
  });

  it("doesn't below the cap", async () => {
    tickets = Array.from({ length: 99 }, (_, i) =>
      makeTicket({ id: `t${i}`, reference: `SD-${i}`, title: `Ticket ${i}` }),
    );
    renderPage();

    await screen.findByText("Ticket 98");
    expect(screen.queryByText("Showing the latest 100")).not.toBeInTheDocument();
  });

  it("shows a note's author, with a fallback when empty", async () => {
    notes = [
      makeNote({ id: "n1", author_name: "Grace Hopper", body: "One" }),
      makeNote({ id: "n2", author: null, author_name: "", body: "Two" }),
    ];
    renderPage();

    const one = await screen.findByText("One");
    expect(within(one.closest("li")!).getByText("Grace Hopper")).toBeInTheDocument();
    expect(within(screen.getByText("Two").closest("li")!).getByText("Unknown author")).toBeInTheDocument();
  });

  it("renders a note as plain text, never as HTML", async () => {
    const html = '<img src=x onerror="alert(1)"><b>bold</b>';
    notes = [makeNote({ body: html })];
    const { container } = renderPage();

    expect(await screen.findByText(html)).toBeInTheDocument();
    expect(container.querySelector("[onerror]")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("adds a note, then clears the box", async () => {
    const user = userEvent.setup();
    client.post.mockImplementation(async (_url: string, data: unknown) => {
      const created = makeNote({ id: "n2", body: (data as { body: string }).body });
      notes = [created, ...notes];
      return { data: created };
    });
    renderPage();

    const box = await screen.findByRole("textbox", { name: "Add note" });
    const button = screen.getByRole("button", { name: "Add note" });
    expect(button).toBeDisabled();

    await user.type(box, "Called her");
    await user.click(button);

    await waitFor(() =>
      expect(client.post).toHaveBeenCalledWith("/contacts/c1/notes/", { body: "Called her" }),
    );
    expect(await screen.findByText("Called her")).toBeInTheDocument();
    expect(box).toHaveValue("");
  });

  it("shows a 400 on a note and keeps its text", async () => {
    const user = userEvent.setup();
    client.post.mockRejectedValue(refusal(400, { body: ["Too long."] }));
    renderPage();

    const box = await screen.findByRole("textbox", { name: "Add note" });
    await user.type(box, "Text");
    await user.click(screen.getByRole("button", { name: "Add note" }));

    expect(await screen.findByText("Too long.")).toBeInTheDocument();
    expect(box).toHaveValue("Text");
    expect(box).toHaveAccessibleDescription("Too long.");
  });

  it("falls back to a toast when a note fails for no reason the API gives", async () => {
    const user = userEvent.setup();
    client.post.mockRejectedValue(new AxiosError("Network Error"));
    renderPage();

    const box = await screen.findByRole("textbox", { name: "Add note" });
    await user.type(box, "Text");
    await user.click(screen.getByRole("button", { name: "Add note" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Failed to add note."));
    expect(box).toHaveValue("Text");
  });

  it("on a 409 on a note, shows a toast and refreshes", async () => {
    const user = userEvent.setup();
    client.post.mockImplementation(async () => {
      contact = makeContact({ is_anonymized: true });
      throw refusal(409, { detail: "This contact has been anonymized." });
    });
    renderPage();

    await user.type(await screen.findByRole("textbox", { name: "Add note" }), "Text");
    await user.click(screen.getByRole("button", { name: "Add note" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("This contact has been anonymized."),
    );
    await waitFor(() =>
      expect(screen.queryByRole("textbox", { name: "Add note" })).not.toBeInTheDocument(),
    );
  });

  it("shows a loading state", async () => {
    const get = client.get.getMockImplementation()!;
    client.get.mockImplementation((url: string, config) =>
      url === "/contacts/c1/tickets/" ? new Promise(() => {}) : get(url, config),
    );
    renderPage();

    expect(await screen.findByRole("status", { name: "Loading timeline" })).toBeVisible();
  });

  it("shows what loaded when the other half fails, and tries again on demand", async () => {
    const user = userEvent.setup();
    refused["/contacts/c1/tickets/"] = refusal(500, {});
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load tickets.");
    expect(await screen.findByText("Middle note")).toBeInTheDocument();

    delete refused["/contacts/c1/tickets/"];
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("New ticket")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows an empty state", async () => {
    tickets = [];
    notes = [];
    renderPage();

    expect(await screen.findByText("Nothing here yet.")).toBeInTheDocument();
  });
});

describe("admin controls", () => {
  it("are hidden from agents, who can still edit and add notes", async () => {
    auth.role = "agent";
    renderPage();

    await loaded();
    expect(screen.queryByRole("button", { name: "Export data" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Anonymize" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit name" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Add note" })).toBeInTheDocument();
  });

  it("are shown to admins", async () => {
    renderPage();

    await loaded();
    expect(screen.getByRole("button", { name: "Export data" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Anonymize" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });
});

describe("export", () => {
  it("queues the export and says so", async () => {
    const user = userEvent.setup();
    client.post.mockResolvedValue({ data: { status: "queued" } });
    renderPage();
    await loaded();

    await user.click(screen.getByRole("button", { name: "Export data" }));

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "Export queued — you will receive it by email",
      ),
    );
    expect(client.post).toHaveBeenCalledWith("/contacts/c1/export/");
  });

  it("is disabled while pending", async () => {
    const user = userEvent.setup();
    client.post.mockImplementation(() => new Promise(() => {}));
    renderPage();
    await loaded();

    await user.click(screen.getByRole("button", { name: "Export data" }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Export data" })).toBeDisabled(),
    );
  });

  it("says when it failed", async () => {
    const user = userEvent.setup();
    client.post.mockRejectedValue(refusal(500, {}));
    renderPage();
    await loaded();

    await user.click(screen.getByRole("button", { name: "Export data" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Failed to queue the export."));
  });
});

describe("a 409 on an admin action", () => {
  const conflict = () => refusal(409, { detail: "This contact has been anonymized." });

  it("on export, shows a toast and refreshes", async () => {
    const user = userEvent.setup();
    client.post.mockRejectedValue(conflict());
    renderPage();
    await loaded();
    const before = gets("/contacts/c1/").length;

    await user.click(screen.getByRole("button", { name: "Export data" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("This contact has been anonymized."),
    );
    await waitFor(() => expect(gets("/contacts/c1/").length).toBeGreaterThan(before));
  });

  it("on delete, shows a toast, refreshes and stays", async () => {
    const user = userEvent.setup();
    client.delete.mockRejectedValue(conflict());
    renderPage();
    await loaded();
    const before = gets("/contacts/c1/").length;

    await user.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("dialog", { name: "Delete contact" });
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("This contact has been anonymized."),
    );
    await waitFor(() => expect(gets("/contacts/c1/").length).toBeGreaterThan(before));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent("/contacts/c1");
  });

  it("on anonymize, shows a toast, refreshes and closes", async () => {
    const user = userEvent.setup();
    client.post.mockRejectedValue(conflict());
    renderPage();
    await loaded();

    await user.click(screen.getByRole("button", { name: "Anonymize" }));
    const dialog = await screen.findByRole("dialog", { name: "Anonymize contact" });
    await user.type(within(dialog).getByRole("textbox"), "ada@example.com");
    await user.click(within(dialog).getByRole("button", { name: "Anonymize" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("This contact has been anonymized."),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("anonymize", () => {
  const open = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(screen.getByRole("button", { name: "Anonymize" }));
    return screen.findByRole("dialog", { name: "Anonymize contact" });
  };

  it("says it's irreversible and what it deletes", async () => {
    const user = userEvent.setup();
    renderPage();
    await loaded();

    const dialog = await open(user);
    expect(dialog).toHaveTextContent(/irreversible/i);
    expect(dialog).toHaveTextContent(/notes, attachments and recordings/i);
  });

  it("requires the email typed before it can go", async () => {
    const user = userEvent.setup();
    renderPage();
    await loaded();

    const dialog = await open(user);
    const submit = within(dialog).getByRole("button", { name: "Anonymize" });
    const input = within(dialog).getByRole("textbox", { name: "Type the email to confirm" });
    expect(submit).toBeDisabled();

    await user.type(input, "wrong@example.com{Enter}");
    expect(submit).toBeDisabled();
    expect(client.post).not.toHaveBeenCalled();

    await user.clear(input);
    await user.type(input, "ada@example.com");
    expect(submit).toBeEnabled();
  });

  it("requires the display name when there is no email", async () => {
    const user = userEvent.setup();
    contact = makeContact({ email: "", email_verified: false });
    renderPage();
    await loaded();

    const dialog = await open(user);
    const submit = within(dialog).getByRole("button", { name: "Anonymize" });
    expect(submit).toBeDisabled();

    await user.type(
      within(dialog).getByRole("textbox", { name: "Type the name to confirm" }),
      "Ada Lovelace",
    );
    expect(submit).toBeEnabled();
  });

  it("anonymizes, and the page goes read-only", async () => {
    const user = userEvent.setup();
    client.post.mockImplementation(async () => {
      contact = makeContact({
        name: "Anonymized contact",
        display_name: "Anonymized contact",
        email: "anonymized-1@anonymized.invalid",
        email_verified: false,
        external_id: "",
        phone: "",
        is_anonymized: true,
      });
      notes = [];
      return { data: contact };
    });
    renderPage();
    await loaded();

    const dialog = await open(user);
    await user.type(within(dialog).getByRole("textbox"), "ada@example.com");
    await user.click(within(dialog).getByRole("button", { name: "Anonymize" }));

    await waitFor(() => expect(client.post).toHaveBeenCalledWith("/contacts/c1/anonymize/"));
    expect(
      await screen.findByRole("heading", { name: "Anonymized contact" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(toast.success).toHaveBeenCalledWith("Contact anonymized.");
  });

  it("is disabled while pending, and can't be closed then", async () => {
    const user = userEvent.setup();
    client.post.mockImplementation(() => new Promise(() => {}));
    renderPage();
    await loaded();

    const dialog = await open(user);
    await user.type(within(dialog).getByRole("textbox"), "ada@example.com");
    await user.click(within(dialog).getByRole("button", { name: "Anonymize" }));

    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Anonymize" })).toBeDisabled(),
    );
    await user.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(client.post).toHaveBeenCalledTimes(1);
  });

  it("shows what the API refuses in the modal, and the modal stays", async () => {
    const user = userEvent.setup();
    client.post.mockRejectedValue(refusal(403, { detail: "Admins only." }));
    renderPage();
    await loaded();

    const dialog = await open(user);
    await user.type(within(dialog).getByRole("textbox"), "ada@example.com");
    await user.click(within(dialog).getByRole("button", { name: "Anonymize" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Admins only.");
  });
});

describe("delete", () => {
  const open = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(screen.getByRole("button", { name: "Delete" }));
    return screen.findByRole("dialog", { name: "Delete contact" });
  };

  it("asks first, and cancelling does nothing", async () => {
    const user = userEvent.setup();
    renderPage();
    await loaded();

    const dialog = await open(user);
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(client.delete).not.toHaveBeenCalled();
  });

  it("deletes and goes back to the list", async () => {
    const user = userEvent.setup();
    client.delete.mockResolvedValue({ data: undefined });
    renderPage();
    await loaded();

    const dialog = await open(user);
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent(/^\/contacts$/));
    expect(client.delete).toHaveBeenCalledWith("/contacts/c1/");
    expect(toast.success).toHaveBeenCalledWith("Contact deleted.");
  });

  it("stays on a failure and says so", async () => {
    const user = userEvent.setup();
    client.delete.mockRejectedValue(refusal(500, {}));
    renderPage();
    await loaded();

    const dialog = await open(user);
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Failed to delete contact."));
    expect(screen.getByTestId("location")).toHaveTextContent("/contacts/c1");
  });
});

describe("anonymized contact", () => {
  beforeEach(() => {
    contact = makeContact({
      name: "Anonymized contact",
      display_name: "Anonymized contact",
      email: "anonymized-1@anonymized.invalid",
      email_verified: false,
      email_verified_at: null,
      external_id: "",
      phone: "",
      is_anonymized: true,
    });
    notes = [];
  });

  const shown = () => screen.findByRole("heading", { name: "Anonymized contact" });

  it("says so clearly, with its tickets visible", async () => {
    renderPage();

    await shown();
    expect(screen.getByText("Anonymized")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Anonymized" })).toHaveTextContent(/read-only/i);
    expect(await screen.findByRole("link", { name: "SD-1 Cannot log in" })).toBeInTheDocument();
  });

  it("doesn't show the placeholder email as if it were one", async () => {
    renderPage();

    await shown();
    expect(screen.queryByText(/anonymized-1@/)).not.toBeInTheDocument();
    expect(screen.queryByText("Unverified")).not.toBeInTheDocument();
  });

  it("has no edit, note, export, anonymize or delete controls, even for an admin", async () => {
    attributeDefs = [attribute({ key: "nick", label: "Nickname" })];
    renderPage();

    await shown();
    await screen.findByRole("link", { name: "SD-1 Cannot log in" });
    expect(screen.queryByRole("button", { name: /^Edit/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add note" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Export data" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Anonymize" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });
});
