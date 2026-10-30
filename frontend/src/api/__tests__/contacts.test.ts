/**
 * Tests for the requests the contacts, companies and attribute definition API modules
 * make, and for reading what the API answers when it refuses a write.
 */

import { AxiosError, type AxiosResponse } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  fetchAttributeDefs,
  createAttributeDef,
  updateAttributeDef,
} from "../attributeDefs";
import { apiClient } from "../client";
import {
  createCompany,
  deleteCompany,
  fetchCompanies,
  fetchCompany,
  fetchCompanyContacts,
  fetchCompanyTickets,
  updateCompany,
} from "../companies";
import {
  anonymizeContact,
  createContact,
  createContactNote,
  deleteContact,
  exportContact,
  fetchContact,
  fetchContactNotes,
  fetchContacts,
  fetchContactTickets,
  updateContact,
} from "../contacts";
import { parseApiError } from "../errors";

vi.mock("../client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

const client = vi.mocked(apiClient);

beforeEach(() => {
  vi.resetAllMocks();
});

describe("fetchContacts", () => {
  it("maps attrs to attr.<key>", async () => {
    client.get.mockResolvedValue({ data: { results: [] } });

    await fetchContacts({ attrs: { plan: "pro" }, search: "a" });

    expect(client.get).toHaveBeenCalledWith("/contacts/", {
      params: { "attr.plan": "pro", search: "a" },
    });
  });

  it("keeps a false filter and leaves out what isn't set", async () => {
    client.get.mockResolvedValue({ data: { results: [] } });

    await fetchContacts({
      email_verified: false,
      company: undefined,
      search: "",
      attrs: { plan: "" },
      page: 2,
      page_size: 50,
    });

    expect(client.get).toHaveBeenCalledWith("/contacts/", {
      params: { email_verified: false, page: 2, page_size: 50 },
    });
  });

  it("returns the page as the API sent it", async () => {
    const page = { count: 1, next: null, previous: null, results: [{ id: "c1" }] };
    client.get.mockResolvedValue({ data: page });

    await expect(fetchContacts()).resolves.toEqual(page);
  });
});

describe("contact requests", () => {
  it("reads a contact, its tickets and its notes", async () => {
    client.get.mockResolvedValue({ data: [{ id: "x" }] });

    await expect(fetchContactTickets("c1")).resolves.toEqual([{ id: "x" }]);
    await expect(fetchContactNotes("c1")).resolves.toEqual([{ id: "x" }]);
    await fetchContact("c1");

    expect(client.get.mock.calls.map(([url]) => url)).toEqual([
      "/contacts/c1/tickets/",
      "/contacts/c1/notes/",
      "/contacts/c1/",
    ]);
  });

  it("writes to the matching endpoints", async () => {
    client.post.mockResolvedValue({ data: { id: "c1" } });
    client.patch.mockResolvedValue({ data: { id: "c1" } });
    client.delete.mockResolvedValue({ data: undefined });

    await createContact({ email: "a@x.io" });
    await updateContact("c1", { attributes: { plan: null } });
    await createContactNote("c1", "Called them");
    await deleteContact("c1");

    expect(client.post).toHaveBeenCalledWith("/contacts/", { email: "a@x.io" });
    expect(client.patch).toHaveBeenCalledWith("/contacts/c1/", {
      attributes: { plan: null },
    });
    expect(client.post).toHaveBeenCalledWith("/contacts/c1/notes/", {
      body: "Called them",
    });
    expect(client.delete).toHaveBeenCalledWith("/contacts/c1/");
  });

  it("exports and anonymizes with a POST and no body", async () => {
    client.post.mockResolvedValueOnce({ data: { status: "queued" } });
    await expect(exportContact("c1")).resolves.toEqual({ status: "queued" });

    client.post.mockResolvedValueOnce({ data: { id: "c1", is_anonymized: true } });
    await expect(anonymizeContact("c1")).resolves.toEqual({
      id: "c1",
      is_anonymized: true,
    });

    expect(client.post.mock.calls).toEqual([
      ["/contacts/c1/export/"],
      ["/contacts/c1/anonymize/"],
    ]);
  });
});

describe("company requests", () => {
  it("maps attrs to attr.<key> on the list", async () => {
    client.get.mockResolvedValue({ data: { results: [] } });

    await fetchCompanies({ attrs: { tier: "gold" }, ordering: "-mrr_cents" });

    expect(client.get).toHaveBeenCalledWith("/companies/", {
      params: { "attr.tier": "gold", ordering: "-mrr_cents" },
    });
  });

  it("reads a company, its contacts and its tickets", async () => {
    client.get.mockResolvedValue({ data: [{ id: "x" }] });

    await fetchCompany("co1");
    await expect(fetchCompanyContacts("co1")).resolves.toEqual([{ id: "x" }]);
    await expect(fetchCompanyTickets("co1")).resolves.toEqual([{ id: "x" }]);

    expect(client.get.mock.calls.map(([url]) => url)).toEqual([
      "/companies/co1/",
      "/companies/co1/contacts/",
      "/companies/co1/tickets/",
    ]);
  });

  it("writes to the matching endpoints", async () => {
    client.post.mockResolvedValue({ data: { id: "co1" } });
    client.patch.mockResolvedValue({ data: { id: "co1" } });
    client.delete.mockResolvedValue({ data: undefined });

    await createCompany({ name: "Acme" });
    await updateCompany("co1", { domain: "acme.io" });
    await deleteCompany("co1");

    expect(client.post).toHaveBeenCalledWith("/companies/", { name: "Acme" });
    expect(client.patch).toHaveBeenCalledWith("/companies/co1/", {
      domain: "acme.io",
    });
    expect(client.delete).toHaveBeenCalledWith("/companies/co1/");
  });
});

describe("attribute definition requests", () => {
  it("picks the endpoint of the entity", async () => {
    const defs = [{ id: "d1" }];
    client.get.mockResolvedValue({ data: defs });

    await expect(fetchAttributeDefs("contact")).resolves.toEqual(defs);
    await expect(fetchAttributeDefs("company")).resolves.toEqual(defs);

    expect(client.get.mock.calls.map(([url]) => url)).toEqual([
      "/contact-attributes/",
      "/company-attributes/",
    ]);
  });

  it("creates and updates under that endpoint", async () => {
    client.post.mockResolvedValue({ data: { id: "d1" } });
    client.patch.mockResolvedValue({ data: { id: "d1" } });
    const data = { key: "plan", label: "Plan", type: "string" } as const;

    await createAttributeDef("company", data);
    await updateAttributeDef("contact", "d1", { is_archived: true });

    expect(client.post).toHaveBeenCalledWith("/company-attributes/", data);
    expect(client.patch).toHaveBeenCalledWith("/contact-attributes/d1/", {
      is_archived: true,
    });
  });
});

function responseError(status: number, data: unknown): AxiosError {
  return new AxiosError("Request failed", "ERR_BAD_REQUEST", undefined, undefined, {
    status,
    data,
  } as AxiosResponse);
}

describe("parseApiError", () => {
  it("reads the 409 of an anonymized contact", () => {
    expect(
      parseApiError(responseError(409, { detail: "This contact has been anonymized." })),
    ).toEqual({
      status: 409,
      message: "This contact has been anonymized.",
      fields: {},
      attributes: {},
    });
  });

  it("gives the 400 of an attribute by its key", () => {
    const parsed = parseApiError(
      responseError(400, {
        attributes: {
          plan: ["Not a valid enum value."],
          nope: ["Unknown attribute."],
        },
      }),
    );

    expect(parsed.attributes).toEqual({
      plan: ["Not a valid enum value."],
      nope: ["Unknown attribute."],
    });
    expect(parsed.fields).toEqual({});
    expect(parsed.message).toBeNull();
  });

  it("gives the 400 of a field by its name, attributes included", () => {
    const parsed = parseApiError(
      responseError(400, {
        email: ["Another contact already uses this value."],
        attributes: ["Expected an object."],
      }),
    );

    expect(parsed.fields).toEqual({
      email: ["Another contact already uses this value."],
      attributes: ["Expected an object."],
    });
    expect(parsed.attributes).toEqual({});
  });

  it("gives an error about no field as the message", () => {
    const parsed = parseApiError(
      responseError(400, {
        non_field_errors: ["A contact needs a name, an email or a phone number."],
      }),
    );

    expect(parsed.message).toBe("A contact needs a name, an email or a phone number.");
    expect(parsed.fields).toEqual({});
  });

  it("copes with a body that isn't JSON", () => {
    expect(parseApiError(responseError(502, "<html>Bad gateway</html>"))).toEqual({
      status: 502,
      message: null,
      fields: {},
      attributes: {},
    });
  });

  it("has no status without a response", () => {
    const empty = { status: null, message: null, fields: {}, attributes: {} };

    expect(parseApiError(new AxiosError("Network Error"))).toEqual(empty);
    expect(parseApiError(new Error("Boom"))).toEqual(empty);
  });
});
