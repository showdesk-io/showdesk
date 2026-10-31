/**
 * Tests for what the contacts, companies and attribute definition API modules work out
 * themselves, and for reading what the API answers when it refuses a write. The plain
 * requests are covered through the hooks.
 */

import { AxiosError, type AxiosResponse } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchAttributeDefs } from "../attributeDefs";
import { apiClient } from "../client";
import {
  createCompany,
  deleteCompany,
  fetchCompanies,
  updateCompany,
} from "../companies";
import { fetchContacts } from "../contacts";
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
});

describe("company requests", () => {
  it("maps attrs to attr.<key> on the list", async () => {
    client.get.mockResolvedValue({ data: { results: [] } });

    await fetchCompanies({ attrs: { tier: "gold" }, ordering: "-mrr_cents" });

    expect(client.get).toHaveBeenCalledWith("/companies/", {
      params: { "attr.tier": "gold", ordering: "-mrr_cents" },
    });
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
