/**
 * Tests for the Contacts and Companies lists: what they ask the API for and what they
 * show of the answer. Only the API client is mocked, so hooks and params are the real ones.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, type AxiosResponse } from "axios";
import toast from "react-hot-toast";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/api/client";
import type { AttributeDef, Company, Contact } from "@/types";
import { ContactsPage } from "../ContactsPage";

vi.mock("@/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("react-hot-toast", () => ({
  default: { success: vi.fn(), error: vi.fn() },
}));

const client = vi.mocked(apiClient);

function contact(overrides: Partial<Contact> = {}): Contact {
  return {
    id: "c1",
    display_name: "Ada Lovelace",
    name: "Ada Lovelace",
    email: "ada@example.com",
    email_verified: true,
    declared_email: "",
    avatar_url: "",
    company_detail: null,
    company: null,
    last_seen_at: null,
    open_tickets_count: 0,
    is_anonymized: false,
    ...overrides,
  } as Contact;
}

function company(overrides: Partial<Company> = {}): Company {
  return {
    id: "co1",
    name: "Acme",
    domain: "acme.io",
    logo_url: "",
    plan: "pro",
    contacts_count: 3,
    open_tickets_count: 2,
    ...overrides,
  } as Company;
}

function attribute(overrides: Partial<AttributeDef>): AttributeDef {
  return {
    id: overrides.key ?? "a",
    key: "a",
    label: "A",
    type: "enum",
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

let contacts: Contact[];
let companies: Company[];
let attributeDefs: AttributeDef[];
let contactCount: number | undefined;
let companyCount: number | undefined;
let refuseContacts: ((params: Record<string, unknown>) => AxiosError | null) | null;

function requests(url: string): Record<string, unknown>[] {
  return client.get.mock.calls
    .filter(([called]) => called === url)
    .map(([, config]) => (config?.params ?? {}) as Record<string, unknown>);
}

function lastRequest(url: string): Record<string, unknown> {
  const all = requests(url);
  return all[all.length - 1] ?? {};
}

function CurrentLocation() {
  const { pathname } = useLocation();
  return <div data-testid="location">{pathname}</div>;
}

function renderPage(path = "/contacts") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <CurrentLocation />
        <Routes>
          <Route path="contacts" element={<ContactsPage />} />
          <Route path="companies" element={<ContactsPage />} />
          <Route path="contacts/:id" element={null} />
          <Route path="companies/:id" element={null} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const location = () => screen.getByTestId("location").textContent;

beforeEach(() => {
  vi.resetAllMocks();
  contacts = [contact()];
  companies = [company()];
  attributeDefs = [];
  contactCount = undefined;
  companyCount = undefined;
  refuseContacts = null;
  client.get.mockImplementation(async (url: string, config) => {
    if (url === "/contacts/") {
      const refused = refuseContacts?.((config?.params ?? {}) as Record<string, unknown>);
      if (refused) throw refused;
      return { data: { count: contactCount ?? contacts.length, results: contacts } };
    }
    if (url === "/companies/") {
      return { data: { count: companyCount ?? companies.length, results: companies } };
    }
    if (url === "/contact-attributes/") return { data: attributeDefs };
    throw new Error(`Unexpected request: ${url}`);
  });
});

describe("contacts table", () => {
  it("shows a row's fields", async () => {
    contacts = [
      contact({
        company_detail: company(),
        open_tickets_count: 4,
        last_seen_at: new Date(Date.now() - 3 * 86400000).toISOString(),
      }),
    ];
    renderPage();

    const row = (await screen.findByText("Ada Lovelace")).closest("tr")!;
    expect(within(row).getByText("ada@example.com")).toBeInTheDocument();
    expect(within(row).getByText("Acme")).toBeInTheDocument();
    expect(within(row).getByText("3 days ago")).toBeInTheDocument();
    expect(within(row).getByText("4")).toBeInTheDocument();
    expect(within(row).getByText("AL")).toBeInTheDocument();
    expect(within(row).queryByText("Unverified")).not.toBeInTheDocument();
  });

  it("shows the avatar when there is one", async () => {
    contacts = [contact({ avatar_url: "https://cdn.test/a.png" })];
    const { container } = renderPage();

    await screen.findByText("Ada Lovelace");
    expect(container.querySelector("img")).toHaveAttribute(
      "src",
      "https://cdn.test/a.png",
    );
    expect(screen.queryByText("AL")).not.toBeInTheDocument();
  });

  it("badges an email that is set but not verified", async () => {
    contacts = [contact({ email_verified: false })];
    renderPage();

    const email = await screen.findByText("ada@example.com");
    expect(within(email.parentElement!).getByText("Unverified")).toBeInTheDocument();
  });

  it("shows the declared email with a badge when there is no email", async () => {
    contacts = [contact({ email: "", declared_email: "said@example.com" })];
    renderPage();

    const email = await screen.findByText("said@example.com");
    expect(within(email.parentElement!).getByText("Unverified")).toBeInTheDocument();
  });

  it("shows both when neither email is proven, a badge on each", async () => {
    contacts = [
      contact({ email_verified: false, declared_email: "said@example.com" }),
    ];
    renderPage();

    await screen.findByText("said@example.com");
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    expect(screen.getAllByText("Unverified")).toHaveLength(2);
  });

  it("leaves the declared email out when the email is proven", async () => {
    contacts = [contact({ declared_email: "said@example.com" })];
    renderPage();

    await screen.findByText("ada@example.com");
    expect(screen.queryByText("said@example.com")).not.toBeInTheDocument();
    expect(screen.queryByText("Unverified")).not.toBeInTheDocument();
  });

  it("opens a contact on a row click", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByText("ada@example.com"));
    expect(location()).toBe("/contacts/c1");
  });

  it("gives a keyboard user a link to the contact", async () => {
    renderPage();

    expect(await screen.findByRole("link", { name: "Ada Lovelace" })).toHaveAttribute(
      "href",
      "/contacts/c1",
    );
  });

  it("marks an anonymized contact and doesn't open it", async () => {
    const user = userEvent.setup();
    contacts = [
      contact({
        name: "",
        email: "",
        display_name: "Anonymous contact",
        is_anonymized: true,
      }),
    ];
    renderPage();

    const name = await screen.findByText("Anonymous contact");
    const row = name.closest("tr")!;
    expect(within(row).getByText("Anonymized")).toBeInTheDocument();
    expect(row).toHaveAttribute("aria-disabled", "true");
    expect(within(row).queryByRole("link")).not.toBeInTheDocument();

    await user.click(name);
    expect(location()).toBe("/contacts");
  });
});

describe("contacts states", () => {
  it("shows a loading state", async () => {
    client.get.mockImplementation(() => new Promise(() => {}));
    renderPage();

    expect(await screen.findByRole("status", { name: "Loading contacts" })).toBeVisible();
  });

  it("shows an empty state", async () => {
    contacts = [];
    renderPage();

    expect(await screen.findByText("No contacts found.")).toBeInTheDocument();
  });

  it("shows an error, and tries again on demand", async () => {
    const user = userEvent.setup();
    refuseContacts = () => refusal(500, {});
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load contacts.");
    expect(screen.queryByText("No contacts found.")).not.toBeInTheDocument();

    refuseContacts = null;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
  });

  it("goes back to the first page when the page asked for no longer exists", async () => {
    const user = userEvent.setup();
    contactCount = 60;
    renderPage();
    await screen.findByText("Ada Lovelace");

    refuseContacts = (params) =>
      params.page === 2 ? refusal(404, { detail: "Invalid page." }) : null;
    await user.click(screen.getByRole("button", { name: "Next page" }));

    await waitFor(() => expect(lastRequest("/contacts/").page).toBe(1));
    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("contacts filters", () => {
  it("searches once typing stops", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Ada Lovelace");

    await user.type(screen.getByRole("searchbox", { name: "Search contacts" }), "ada");

    await waitFor(() => expect(lastRequest("/contacts/").search).toBe("ada"));
    const searched = requests("/contacts/")
      .map((params) => params.search)
      .filter(Boolean);
    expect(searched).toEqual(["ada"]);
  });

  it("filters by company", async () => {
    const user = userEvent.setup();
    renderPage();

    const select = screen.getByRole("combobox", { name: "Company" });
    await within(select).findByRole("option", { name: "Acme" });
    expect(requests("/companies/")[0]).toMatchObject({ page_size: 100 });
    await user.selectOptions(select, "Acme");

    await waitFor(() => expect(lastRequest("/contacts/").company).toBe("co1"));
  });

  it("filters on verified emails only", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Ada Lovelace");
    expect(lastRequest("/contacts/")).not.toHaveProperty("email_verified");

    await user.click(screen.getByRole("checkbox", { name: "Verified email only" }));
    await waitFor(() => expect(lastRequest("/contacts/").email_verified).toBe(true));

    await user.click(screen.getByRole("checkbox", { name: "Verified email only" }));
    await waitFor(() =>
      expect(lastRequest("/contacts/")).not.toHaveProperty("email_verified"),
    );
  });

  it("has a select per live enum or boolean attribute", async () => {
    const user = userEvent.setup();
    attributeDefs = [
      attribute({ key: "tier", label: "Tier", options: ["gold", "silver"] }),
      attribute({ key: "beta", label: "Beta", type: "boolean" }),
      attribute({ key: "old", label: "Old", is_archived: true }),
      attribute({ key: "note", label: "Note", type: "string" }),
    ];
    renderPage();

    const tier = await screen.findByRole("combobox", { name: "Tier" });
    expect(screen.queryByRole("combobox", { name: "Old" })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Note" })).not.toBeInTheDocument();

    await user.selectOptions(tier, "gold");
    await waitFor(() => expect(lastRequest("/contacts/")["attr.tier"]).toBe("gold"));

    await user.selectOptions(screen.getByRole("combobox", { name: "Beta" }), "No");
    await waitFor(() => expect(lastRequest("/contacts/")["attr.beta"]).toBe("false"));
    expect(lastRequest("/contacts/")["attr.tier"]).toBe("gold");

    await user.selectOptions(tier, "Any Tier");
    await waitFor(() =>
      expect(lastRequest("/contacts/")).not.toHaveProperty("attr.tier"),
    );
  });
});

describe("contacts pagination", () => {
  async function onSecondPage(user: ReturnType<typeof userEvent.setup>) {
    contactCount = 60;
    renderPage();
    await screen.findByText("Ada Lovelace");
    expect(lastRequest("/contacts/")).toMatchObject({ page: 1, page_size: 25 });
    await user.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(lastRequest("/contacts/").page).toBe(2));
    await screen.findByText("Page 2 of 3");
  }

  it("moves between pages, within the count", async () => {
    const user = userEvent.setup();
    contactCount = 60;
    renderPage();
    await screen.findByText("Page 1 of 3");
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Next page" }));
    await screen.findByText("Page 2 of 3");
    await user.click(screen.getByRole("button", { name: "Next page" }));
    await screen.findByText("Page 3 of 3");
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Previous page" }));
    await screen.findByText("Page 2 of 3");
    expect(lastRequest("/contacts/").page).toBe(2);
  });

  it("changes the page size, and goes back to page 1", async () => {
    const user = userEvent.setup();
    await onSecondPage(user);

    await user.selectOptions(screen.getByRole("combobox", { name: "Rows per page" }), "50");

    await waitFor(() =>
      expect(lastRequest("/contacts/")).toMatchObject({ page: 1, page_size: 50 }),
    );
    expect(await screen.findByText("Page 1 of 2")).toBeInTheDocument();
  });

  it("goes back to page 1 when a search changes", async () => {
    const user = userEvent.setup();
    await onSecondPage(user);

    await user.type(screen.getByRole("searchbox", { name: "Search contacts" }), "a");

    await waitFor(() =>
      expect(lastRequest("/contacts/")).toMatchObject({ page: 1, search: "a" }),
    );
    expect(requests("/contacts/")).not.toContainEqual(
      expect.objectContaining({ page: 2, search: "a" }),
    );
  });

  it("goes back to page 1 when a filter changes", async () => {
    const user = userEvent.setup();
    await onSecondPage(user);

    await user.click(screen.getByRole("checkbox", { name: "Verified email only" }));

    await waitFor(() =>
      expect(lastRequest("/contacts/")).toMatchObject({ page: 1, email_verified: true }),
    );
    expect(requests("/contacts/")).not.toContainEqual(
      expect.objectContaining({ page: 2, email_verified: true }),
    );
  });
});

describe("add contact", () => {
  const open = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(screen.getByRole("button", { name: "Add contact" }));
    return screen.findByRole("dialog", { name: "Add contact" });
  };

  it("creates a contact, says so and closes", async () => {
    const user = userEvent.setup();
    client.post.mockResolvedValue({ data: contact({ id: "new" }) });
    renderPage();
    await screen.findByText("Ada Lovelace");
    const before = requests("/contacts/").length;

    const dialog = await open(user);
    await user.type(within(dialog).getByLabelText("Name"), "  Grace  ");
    await user.type(within(dialog).getByLabelText("Phone"), "+33123456789");
    await user.click(within(dialog).getByRole("button", { name: "Add contact" }));

    await waitFor(() =>
      expect(client.post).toHaveBeenCalledWith("/contacts/", {
        name: "Grace",
        phone: "+33123456789",
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(toast.success).toHaveBeenCalledWith("Contact added.");
    await waitFor(() => expect(requests("/contacts/").length).toBeGreaterThan(before));
  });

  it("asks for a name, an email or a phone, without calling the API", async () => {
    const user = userEvent.setup();
    renderPage();

    const dialog = await open(user);
    await user.type(within(dialog).getByLabelText("Name"), "   ");
    await user.click(within(dialog).getByRole("button", { name: "Add contact" }));

    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      "A contact needs a name, an email or a phone number.",
    );
    expect(client.post).not.toHaveBeenCalled();
  });

  it("shows the API's field errors on their fields", async () => {
    const user = userEvent.setup();
    client.post.mockRejectedValue(
      refusal(400, { email: ["A contact with this email already exists."] }),
    );
    renderPage();

    const dialog = await open(user);
    const email = within(dialog).getByLabelText("Email");
    await user.type(email, "ada@example.com");
    await user.click(within(dialog).getByRole("button", { name: "Add contact" }));

    expect(
      await within(dialog).findByText("A contact with this email already exists."),
    ).toBeInTheDocument();
    expect(email).toHaveAttribute("aria-invalid", "true");
    expect(email).toHaveAccessibleDescription("A contact with this email already exists.");
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("shows the API's error about no field, and any on a field not in the form", async () => {
    const user = userEvent.setup();
    client.post.mockRejectedValue(
      refusal(400, {
        non_field_errors: ["A contact needs a name, an email or a phone number."],
        locale: ["Too long."],
      }),
    );
    renderPage();

    const dialog = await open(user);
    await user.type(within(dialog).getByLabelText("Name"), "Grace");
    await user.click(within(dialog).getByRole("button", { name: "Add contact" }));

    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent("A contact needs a name, an email or a phone number.");
    expect(alert).toHaveTextContent("Too long.");
  });

  it("falls back to a toast when the API says nothing usable", async () => {
    const user = userEvent.setup();
    client.post.mockRejectedValue(new AxiosError("Network Error"));
    renderPage();

    const dialog = await open(user);
    await user.type(within(dialog).getByLabelText("Name"), "Grace");
    await user.click(within(dialog).getByRole("button", { name: "Add contact" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Failed to add contact."),
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it.each([
    ["Close", (user: ReturnType<typeof userEvent.setup>, dialog: HTMLElement) =>
      user.click(within(dialog).getByRole("button", { name: "Close" }))],
    ["Cancel", (user: ReturnType<typeof userEvent.setup>, dialog: HTMLElement) =>
      user.click(within(dialog).getByRole("button", { name: "Cancel" }))],
    ["Escape", (user: ReturnType<typeof userEvent.setup>) => user.keyboard("{Escape}")],
  ])("clears values and errors when closed with %s", async (_label, close) => {
    const user = userEvent.setup();
    client.post.mockRejectedValue(refusal(400, { email: ["Enter a valid email address."] }));
    renderPage();

    let dialog = await open(user);
    await user.type(within(dialog).getByLabelText("Email"), "nope");
    await user.click(within(dialog).getByRole("button", { name: "Add contact" }));
    await within(dialog).findByText("Enter a valid email address.");

    await close(user, dialog);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    dialog = await open(user);
    expect(within(dialog).getByLabelText("Email")).toHaveValue("");
    expect(
      within(dialog).queryByText("Enter a valid email address."),
    ).not.toBeInTheDocument();
  });
});

describe("tabs", () => {
  it("are driven by the route", async () => {
    const user = userEvent.setup();
    renderPage();

    const tab = (name: string) =>
      within(screen.getByRole("navigation", { name: "Contacts and companies" })).getByRole(
        "link",
        { name },
      );
    expect(tab("Contacts")).toHaveAttribute("aria-current", "page");
    await screen.findByText("Ada Lovelace");

    await user.click(tab("Companies"));

    expect(location()).toBe("/companies");
    expect(tab("Companies")).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(await screen.findByRole("link", { name: "Acme" })).toBeInTheDocument();
    expect(screen.queryByText("Ada Lovelace")).not.toBeInTheDocument();
  });
});

describe("companies table", () => {
  it("shows a row's fields, and opens the company on a click", async () => {
    const user = userEvent.setup();
    renderPage("/companies");

    const name = await screen.findByRole("link", { name: "Acme" });
    expect(name).toHaveAttribute("href", "/companies/co1");
    const row = name.closest("tr")!;
    expect(within(row).getByText("acme.io")).toBeInTheDocument();
    expect(within(row).getByText("3")).toBeInTheDocument();
    expect(within(row).getByText("2")).toBeInTheDocument();
    expect(within(row).getByText("pro")).toBeInTheDocument();

    await user.click(within(row).getByText("acme.io"));
    expect(location()).toBe("/companies/co1");
  });

  it("shows the logo when there is one", async () => {
    companies = [company({ logo_url: "https://cdn.test/l.png" })];
    const { container } = renderPage("/companies");

    await screen.findByRole("link", { name: "Acme" });
    expect(container.querySelector("img")).toHaveAttribute(
      "src",
      "https://cdn.test/l.png",
    );
  });

  it("shows a loading state", async () => {
    client.get.mockImplementation(() => new Promise(() => {}));
    renderPage("/companies");

    expect(await screen.findByRole("status", { name: "Loading companies" })).toBeVisible();
  });

  it("shows an empty state", async () => {
    companies = [];
    renderPage("/companies");

    expect(await screen.findByText("No companies found.")).toBeInTheDocument();
  });

  it("shows an error, and tries again on demand", async () => {
    const user = userEvent.setup();
    let failing = true;
    client.get.mockImplementation(async () => {
      if (failing) throw refusal(500, {});
      return { data: { count: 1, results: companies } };
    });
    renderPage("/companies");

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load companies.");

    failing = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("link", { name: "Acme" })).toBeInTheDocument();
  });

  it("searches once typing stops, and goes back to page 1", async () => {
    const user = userEvent.setup();
    companyCount = 60;
    renderPage("/companies");
    await screen.findByRole("link", { name: "Acme" });
    await user.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(lastRequest("/companies/").page).toBe(2));

    await user.type(screen.getByRole("searchbox", { name: "Search companies" }), "acm");

    await waitFor(() =>
      expect(lastRequest("/companies/")).toMatchObject({ page: 1, search: "acm" }),
    );
    expect(
      requests("/companies/")
        .map((params) => params.search)
        .filter(Boolean),
    ).toEqual(["acm"]);
  });
});

describe("add company", () => {
  const open = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(screen.getByRole("button", { name: "Add company" }));
    return screen.findByRole("dialog", { name: "Add company" });
  };

  it("creates a company, says so and closes", async () => {
    const user = userEvent.setup();
    client.post.mockResolvedValue({ data: company({ id: "new" }) });
    renderPage("/companies");

    const dialog = await open(user);
    await user.type(within(dialog).getByLabelText("Name"), "Initech");
    await user.type(within(dialog).getByLabelText("Domain"), "initech.com");
    await user.click(within(dialog).getByRole("button", { name: "Add company" }));

    await waitFor(() =>
      expect(client.post).toHaveBeenCalledWith("/companies/", {
        name: "Initech",
        domain: "initech.com",
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(toast.success).toHaveBeenCalledWith("Company added.");
  });

  it("asks for a name, without calling the API", async () => {
    const user = userEvent.setup();
    renderPage("/companies");

    const dialog = await open(user);
    await user.click(within(dialog).getByRole("button", { name: "Add company" }));

    expect(within(dialog).getByRole("alert")).toHaveTextContent("A company needs a name.");
    expect(client.post).not.toHaveBeenCalled();
  });

  it("shows the API's field errors, and clears them when closed", async () => {
    const user = userEvent.setup();
    client.post.mockRejectedValue(refusal(400, { domain: ["This domain is taken."] }));
    renderPage("/companies");

    let dialog = await open(user);
    await user.type(within(dialog).getByLabelText("Name"), "Initech");
    await user.type(within(dialog).getByLabelText("Domain"), "acme.io");
    await user.click(within(dialog).getByRole("button", { name: "Add company" }));
    expect(await within(dialog).findByText("This domain is taken.")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Domain")).toHaveAttribute("aria-invalid", "true");

    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    dialog = await open(user);
    expect(within(dialog).getByLabelText("Name")).toHaveValue("");
    expect(within(dialog).queryByText("This domain is taken.")).not.toBeInTheDocument();
  });
});
