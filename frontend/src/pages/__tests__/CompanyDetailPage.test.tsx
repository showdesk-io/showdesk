/**
 * Tests for the company detail page. Only the API client and the current user are mocked,
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
import type { AttributeDef, Company, Contact, TicketListItem } from "@/types";
import { CompanyDetailPage } from "../CompanyDetailPage";

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

function makeCompany(overrides: Partial<Company> = {}): Company {
  return {
    id: "co1",
    external_id: "ext-co",
    name: "Acme",
    domain: "acme.io",
    logo_url: "",
    industry: "",
    size: "",
    website: "https://acme.io/",
    plan: "pro",
    mrr_cents: 123450,
    health_score: 80,
    signed_up_at: null,
    churned_at: null,
    attributes: {},
    contacts_count: 2,
    open_tickets_count: 1,
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

function makePerson(overrides: Partial<Contact> = {}): Contact {
  return {
    id: "c1",
    display_name: "Ada Lovelace",
    name: "Ada Lovelace",
    email: "ada@example.com",
    email_verified: true,
    declared_email: "",
    avatar_url: "",
    last_seen_at: null,
    open_tickets_count: 4,
    is_anonymized: false,
    ...overrides,
  } as Contact;
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

let company: Company;
let tickets: TicketListItem[];
let people: Contact[];
let attributeDefs: AttributeDef[];
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
      <MemoryRouter initialEntries={["/companies/co1"]}>
        <CurrentLocation />
        <Routes>
          <Route path="companies" element={null} />
          <Route path="companies/:id" element={<CompanyDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const loaded = () => screen.findByRole("heading", { name: "Acme" });

function patchLikeTheApi() {
  client.patch.mockImplementation(async (_url: string, data: unknown) => {
    const { attributes, ...fields } = data as Partial<Company>;
    company = { ...company, ...fields, attributes: { ...company.attributes, ...attributes } };
    return { data: company };
  });
}

beforeEach(() => {
  vi.resetAllMocks();
  auth.role = "admin";
  company = makeCompany();
  tickets = [makeTicket()];
  people = [makePerson()];
  attributeDefs = [];
  refused = {};
  client.get.mockImplementation(async (url: string) => {
    if (refused[url]) throw refused[url];
    if (url === "/companies/co1/") return { data: company };
    if (url === "/companies/co1/tickets/") return { data: tickets };
    if (url === "/companies/co1/contacts/") return { data: people };
    if (url === "/company-attributes/") return { data: attributeDefs };
    throw new Error(`Unexpected request: ${url}`);
  });
});

describe("page states", () => {
  it("shows a loading state", async () => {
    client.get.mockImplementation(() => new Promise(() => {}));
    renderPage();

    expect(await screen.findByRole("status", { name: "Loading company" })).toBeVisible();
  });

  it("shows a not-found state with a link back on a 404", async () => {
    refused["/companies/co1/"] = refusal(404, { detail: "Not found." });
    renderPage();

    expect(await screen.findByText("Company not found.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to companies" })).toHaveAttribute(
      "href",
      "/companies",
    );
  });

  it("shows an error on anything else, and tries again on demand", async () => {
    const user = userEvent.setup();
    refused["/companies/co1/"] = refusal(500, {});
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load this company.");

    delete refused["/companies/co1/"];
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await loaded()).toBeInTheDocument();
  });
});

describe("profile", () => {
  it("shows the company", async () => {
    renderPage();

    await loaded();
    expect(screen.getByText("acme.io")).toBeInTheDocument();
    expect(screen.getByText("pro")).toBeInTheDocument();
    expect(screen.getByText("MRR").nextElementSibling).toHaveTextContent(/^1234\.50$/);
    expect(screen.getByText("Health score").nextElementSibling).toHaveTextContent("80");
    expect(screen.getByText("Contacts").nextElementSibling).toHaveTextContent("2");
    expect(screen.getByText("Open tickets").nextElementSibling).toHaveTextContent("1");
    expect(screen.getByRole("link", { name: "Back to companies" })).toBeInTheDocument();
  });

  it("shows a dash when there is no MRR or health score", async () => {
    company = makeCompany({ mrr_cents: null, health_score: null });
    renderPage();

    await loaded();
    expect(screen.getByText("MRR").nextElementSibling).toHaveTextContent("—");
    expect(screen.getByText("Health score").nextElementSibling).toHaveTextContent("—");
  });

  it("shows the MRR of a company on 0 as 0", async () => {
    company = makeCompany({ mrr_cents: 0 });
    renderPage();

    await loaded();
    expect(screen.getByText("MRR").nextElementSibling).toHaveTextContent("0.00");
  });

  it("shows the external id read-only", async () => {
    renderPage();

    await loaded();
    expect(screen.getByText("ext-co").tagName).toBe("CODE");
    expect(
      screen.queryByRole("button", { name: "Edit external id" }),
    ).not.toBeInTheDocument();
  });

  it("links an http(s) website", async () => {
    renderPage();

    await loaded();
    const link = screen.getByRole("link", { name: "https://acme.io/" });
    expect(link).toHaveAttribute("href", "https://acme.io/");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("doesn't link a javascript: website, or show a javascript: logo", async () => {
    company = makeCompany({
      website: "javascript:alert(1)",
      logo_url: "javascript:alert(2)",
    });
    const { container } = renderPage();

    await loaded();
    expect(screen.getByText("javascript:alert(1)").closest("a")).toBeNull();
    expect(container.querySelector('a[href^="javascript"]')).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("shows an http(s) logo", async () => {
    company = makeCompany({ logo_url: "https://cdn.test/l.png" });
    const { container } = renderPage();

    await loaded();
    expect(container.querySelector("img")).toHaveAttribute("src", "https://cdn.test/l.png");
  });
});

describe("inline edit", () => {
  it.each([
    ["Name", "name", "Initech"],
    ["Domain", "domain", "initech.com"],
    ["Website", "website", "https://initech.com/"],
    ["Plan", "plan", "enterprise"],
  ])("saves the %s", async (label, field, value) => {
    const user = userEvent.setup();
    patchLikeTheApi();
    renderPage();
    await loaded();

    await user.click(screen.getByRole("button", { name: `Edit ${label.toLowerCase()}` }));
    const input = screen.getByRole("textbox", { name: label });
    await user.clear(input);
    await user.type(input, value);
    await user.tab();

    await waitFor(() =>
      expect(client.patch).toHaveBeenCalledWith("/companies/co1/", { [field]: value }),
    );
    expect(await screen.findByText(value)).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: label })).not.toBeInTheDocument();
  });

  it("shows a 400 on the field and keeps the input", async () => {
    const user = userEvent.setup();
    client.patch.mockRejectedValue(
      refusal(400, { domain: ["Another company already uses this domain."] }),
    );
    renderPage();
    await loaded();

    await user.click(screen.getByRole("button", { name: "Edit domain" }));
    const input = screen.getByRole("textbox", { name: "Domain" });
    await user.clear(input);
    await user.type(input, "taken.io{Enter}");

    expect(
      await screen.findByText("Another company already uses this domain."),
    ).toBeInTheDocument();
    expect(input).toHaveValue("taken.io");
    expect(input).toHaveAttribute("aria-invalid", "true");
  });

  it("shows the API's refusal of an empty name", async () => {
    const user = userEvent.setup();
    client.patch.mockRejectedValue(refusal(400, { name: ["This field may not be blank."] }));
    renderPage();
    await loaded();

    await user.click(screen.getByRole("button", { name: "Edit name" }));
    await user.clear(screen.getByRole("textbox", { name: "Name" }));
    await user.tab();

    expect(await screen.findByText("This field may not be blank.")).toBeInTheDocument();
    expect(client.patch).toHaveBeenCalledWith("/companies/co1/", { name: "" });
  });
});

describe("attributes", () => {
  it("edits the company's definitions with the attribute payload", async () => {
    const user = userEvent.setup();
    attributeDefs = [
      attribute({ key: "region", label: "Region" }),
      attribute({ key: "old", label: "Old", is_archived: true }),
    ];
    company = makeCompany({ attributes: { old: "kept" } });
    patchLikeTheApi();
    renderPage();

    await user.type(await screen.findByRole("textbox", { name: "Region" }), "EMEA");
    await user.tab();

    await waitFor(() =>
      expect(client.patch).toHaveBeenCalledWith("/companies/co1/", {
        attributes: { region: "EMEA" },
      }),
    );
    expect(screen.getByText("old").nextElementSibling).toHaveTextContent("kept");
  });

  it("shows a 400 next to the attribute", async () => {
    const user = userEvent.setup();
    attributeDefs = [attribute({ key: "region", label: "Region" })];
    client.patch.mockRejectedValue(
      refusal(400, { attributes: { region: ["Not a valid string value."] } }),
    );
    renderPage();

    const input = await screen.findByRole("textbox", { name: "Region" });
    await user.type(input, "x");
    await user.tab();

    expect(await screen.findByText("Not a valid string value.")).toBeInTheDocument();
    expect(input).toHaveValue("x");
  });
});

describe("tabs", () => {
  const tab = (name: string) => screen.getByRole("tab", { name });

  it("shows the tickets first", async () => {
    renderPage();

    await loaded();
    expect(tab("Tickets")).toHaveAttribute("aria-selected", "true");
    const panel = screen.getByRole("tabpanel", { name: "Tickets" });
    const link = await within(panel).findByRole("link", { name: "SD-1 Cannot log in" });
    expect(link).toHaveAttribute("href", "/tickets/t1");
    expect(within(panel).getByText("open")).toBeInTheDocument();
    expect(gets("/companies/co1/tickets/")).toHaveLength(1);
  });

  it("shows the people, whose rows link to contacts", async () => {
    const user = userEvent.setup();
    renderPage();
    await loaded();

    await user.click(tab("People"));

    expect(tab("People")).toHaveAttribute("aria-selected", "true");
    const panel = screen.getByRole("tabpanel", { name: "People" });
    const link = await within(panel).findByRole("link", { name: "Ada Lovelace" });
    expect(link).toHaveAttribute("href", "/contacts/c1");
    const row = link.closest("tr")!;
    expect(within(row).getByText("ada@example.com")).toBeInTheDocument();
    expect(within(row).getByText("4")).toBeInTheDocument();
    expect(within(row).queryByText("Unverified")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "SD-1 Cannot log in" })).not.toBeInTheDocument();
  });

  it("badges a person's unverified email", async () => {
    const user = userEvent.setup();
    people = [makePerson({ email_verified: false })];
    renderPage();
    await loaded();

    await user.click(tab("People"));

    expect(await screen.findByText("Unverified")).toBeInTheDocument();
  });

  it("says when the tickets may be cut off, at exactly the cap", async () => {
    tickets = Array.from({ length: 100 }, (_, i) =>
      makeTicket({ id: `t${i}`, reference: `SD-${i}` }),
    );
    renderPage();

    expect(await screen.findByText("Showing the latest 100")).toBeInTheDocument();
  });

  it("doesn't below the cap", async () => {
    tickets = Array.from({ length: 99 }, (_, i) =>
      makeTicket({ id: `t${i}`, reference: `SD-${i}` }),
    );
    renderPage();

    await screen.findByRole("link", { name: "SD-98 Cannot log in" });
    expect(screen.queryByText("Showing the latest 100")).not.toBeInTheDocument();
  });

  it("says when the people may be cut off, at exactly the cap", async () => {
    const user = userEvent.setup();
    people = Array.from({ length: 200 }, (_, i) =>
      makePerson({ id: `c${i}`, display_name: `Person ${i}` }),
    );
    renderPage();
    await loaded();

    await user.click(tab("People"));

    expect(await screen.findByText("Showing the first 200")).toBeInTheDocument();
  });

  it("doesn't below the cap", async () => {
    const user = userEvent.setup();
    people = Array.from({ length: 199 }, (_, i) =>
      makePerson({ id: `c${i}`, display_name: `Person ${i}` }),
    );
    renderPage();
    await loaded();

    await user.click(tab("People"));

    await screen.findByText("Person 198");
    expect(screen.queryByText("Showing the first 200")).not.toBeInTheDocument();
  });

  it("shows loading states", async () => {
    const user = userEvent.setup();
    const get = client.get.getMockImplementation()!;
    client.get.mockImplementation((url: string, config) =>
      url === "/companies/co1/" || url === "/company-attributes/"
        ? get(url, config)
        : new Promise(() => {}),
    );
    renderPage();

    expect(await screen.findByRole("status", { name: "Loading tickets" })).toBeVisible();
    await user.click(tab("People"));
    expect(screen.getByRole("status", { name: "Loading people" })).toBeVisible();
  });

  it("shows errors, and tries again on demand", async () => {
    const user = userEvent.setup();
    refused["/companies/co1/tickets/"] = refusal(500, {});
    refused["/companies/co1/contacts/"] = refusal(500, {});
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load tickets.");
    delete refused["/companies/co1/tickets/"];
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("link", { name: "SD-1 Cannot log in" })).toBeInTheDocument();

    await user.click(tab("People"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load people.");
  });

  it("shows empty states", async () => {
    const user = userEvent.setup();
    tickets = [];
    people = [];
    renderPage();

    expect(await screen.findByText("No tickets yet.")).toBeInTheDocument();
    await user.click(tab("People"));
    expect(await screen.findByText("No people yet.")).toBeInTheDocument();
  });
});

describe("delete", () => {
  const open = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(screen.getByRole("button", { name: "Delete" }));
    return screen.findByRole("dialog", { name: "Delete company" });
  };

  it("is hidden from agents, who can still edit", async () => {
    auth.role = "agent";
    renderPage();

    await loaded();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit name" })).toBeInTheDocument();
  });

  it("says the contacts stay, and cancelling does nothing", async () => {
    const user = userEvent.setup();
    renderPage();
    await loaded();

    const dialog = await open(user);
    expect(dialog).toHaveTextContent("Its 2 contacts stay, without a company.");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(client.delete).not.toHaveBeenCalled();
  });

  it("gets the count right for one contact", async () => {
    const user = userEvent.setup();
    company = makeCompany({ contacts_count: 1 });
    renderPage();
    await loaded();

    expect(await open(user)).toHaveTextContent("Its 1 contact stays, without a company.");
  });

  it("deletes and goes back to the list", async () => {
    const user = userEvent.setup();
    client.delete.mockResolvedValue({ data: undefined });
    renderPage();
    await loaded();

    const dialog = await open(user);
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent(/^\/companies$/));
    expect(client.delete).toHaveBeenCalledWith("/companies/co1/");
    expect(toast.success).toHaveBeenCalledWith("Company deleted.");
  });

  it("is disabled while pending", async () => {
    const user = userEvent.setup();
    client.delete.mockImplementation(() => new Promise(() => {}));
    renderPage();
    await loaded();

    const dialog = await open(user);
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Delete" })).toBeDisabled(),
    );
  });

  it("on a 409, shows a toast, refreshes and stays", async () => {
    const user = userEvent.setup();
    client.delete.mockRejectedValue(
      refusal(409, { detail: "This company just got a new contact. Try again." }),
    );
    renderPage();
    await loaded();
    const before = gets("/companies/co1/").length;

    const dialog = await open(user);
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "This company just got a new contact. Try again.",
      ),
    );
    await waitFor(() => expect(gets("/companies/co1/").length).toBeGreaterThan(before));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent("/companies/co1");
  });

  it("stays on a failure and says so", async () => {
    const user = userEvent.setup();
    client.delete.mockRejectedValue(refusal(500, {}));
    renderPage();
    await loaded();

    const dialog = await open(user);
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Failed to delete company."));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
