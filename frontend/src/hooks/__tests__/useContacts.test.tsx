/**
 * Tests for the contacts, companies and attribute definition hooks: what they ask the
 * API for and which cached queries a mutation leaves stale, on a real QueryClient.
 */

import { QueryClient, QueryClientProvider, type QueryKey } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { AxiosError, type AxiosResponse } from "axios";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/api/client";
import { parseApiError } from "@/api/errors";
import {
  useAttributeDefs,
  useCreateAttributeDef,
  useUpdateAttributeDef,
} from "../useAttributeDefs";
import {
  useCompanies,
  useCompany,
  useCompanyContacts,
  useCompanyTickets,
  useCreateCompany,
  useDeleteCompany,
  useUpdateCompany,
} from "../useCompanies";
import {
  useAnonymizeContact,
  useContact,
  useContactNotes,
  useContacts,
  useContactTickets,
  useCreateContact,
  useCreateContactNote,
  useDeleteContact,
  useExportContact,
  useUpdateContact,
} from "../useContacts";

vi.mock("@/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

const client = vi.mocked(apiClient);

const CACHED: QueryKey[] = [
  ["contacts", {}],
  ["contact", "c1"],
  ["contact", "c1", "tickets"],
  ["contact", "c1", "notes"],
  ["contact", "c2"],
  ["companies", {}],
  ["company", "co1"],
  ["company", "co1", "contacts"],
  ["company", "co1", "tickets"],
  ["attributeDefs", "contact"],
  ["attributeDefs", "company"],
  ["tickets", {}],
  ["ticket", "t1"],
  ["tags"],
];

function setup() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  for (const key of CACHED) {
    queryClient.setQueryData(key, { cached: true });
  }
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const stale = () =>
    CACHED.filter((key) => queryClient.getQueryState(key)?.isInvalidated).map((key) =>
      key.filter((part) => typeof part === "string").join("/"),
    );
  return { queryClient, wrapper, stale };
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("queries", () => {
  it("useContacts asks for the filters given and caches under them", async () => {
    const { queryClient, wrapper } = setup();
    const page = { count: 0, next: null, previous: null, results: [] };
    client.get.mockResolvedValue({ data: page });
    const params = { attrs: { plan: "pro" }, page: 2 };

    const { result } = renderHook(() => useContacts(params), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(client.get).toHaveBeenCalledWith("/contacts/", {
      params: { "attr.plan": "pro", page: 2 },
    });
    expect(queryClient.getQueryData(["contacts", params])).toEqual(page);
  });

  it.each<[string, () => { fetchStatus: string }]>([
    ["useContact", () => useContact("")],
    ["useContactTickets", () => useContactTickets("")],
    ["useContactNotes", () => useContactNotes("")],
    ["useCompany", () => useCompany("")],
    ["useCompanyContacts", () => useCompanyContacts("")],
    ["useCompanyTickets", () => useCompanyTickets("")],
  ])("%s waits for an id", (_name, useHook) => {
    const { wrapper } = setup();

    const { result } = renderHook(useHook, { wrapper });

    expect(result.current.fetchStatus).toBe("idle");
    expect(client.get).not.toHaveBeenCalled();
  });

  it.each<[string, () => { data: unknown; isSuccess: boolean }, string, QueryKey]>([
    ["useContact", () => useContact("n1"), "/contacts/n1/", ["contact", "n1"]],
    [
      "useContactTickets",
      () => useContactTickets("n1"),
      "/contacts/n1/tickets/",
      ["contact", "n1", "tickets"],
    ],
    [
      "useContactNotes",
      () => useContactNotes("n1"),
      "/contacts/n1/notes/",
      ["contact", "n1", "notes"],
    ],
    ["useCompanies", () => useCompanies(), "/companies/", ["companies", {}]],
    ["useCompany", () => useCompany("n1"), "/companies/n1/", ["company", "n1"]],
    [
      "useCompanyContacts",
      () => useCompanyContacts("n1"),
      "/companies/n1/contacts/",
      ["company", "n1", "contacts"],
    ],
    [
      "useCompanyTickets",
      () => useCompanyTickets("n1"),
      "/companies/n1/tickets/",
      ["company", "n1", "tickets"],
    ],
    [
      "useAttributeDefs",
      () => useAttributeDefs("company"),
      "/company-attributes/",
      ["attributeDefs", "company"],
    ],
  ])("%s reads its endpoint and caches under its key", async (_name, useHook, url, key) => {
    const { queryClient, wrapper } = setup();
    queryClient.removeQueries({ queryKey: key, exact: true });
    client.get.mockResolvedValue({ data: [{ id: "x" }] });

    const { result } = renderHook(useHook, { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(client.get.mock.calls[0]?.[0]).toBe(url);
    expect(queryClient.getQueryData(key)).toEqual([{ id: "x" }]);
  });
});

describe("contact mutations", () => {
  it("creating a contact refreshes the lists and the companies' counts", async () => {
    const { wrapper, stale } = setup();
    client.post.mockResolvedValue({ data: { id: "c9" } });

    const { result } = renderHook(() => useCreateContact(), { wrapper });
    await result.current.mutateAsync({ email: "a@x.io" });

    expect(client.post).toHaveBeenCalledWith("/contacts/", { email: "a@x.io" });
    expect(stale()).toEqual([
      "contacts",
      "companies",
      "company/co1",
      "company/co1/contacts",
      "company/co1/tickets",
    ]);
  });

  it("updating a contact also refreshes the tickets showing it, not other contacts", async () => {
    const { wrapper, stale } = setup();
    client.patch.mockResolvedValue({ data: { id: "c1" } });

    const { result } = renderHook(() => useUpdateContact(), { wrapper });
    await result.current.mutateAsync({ id: "c1", name: "Ann" });

    expect(client.patch).toHaveBeenCalledWith("/contacts/c1/", { name: "Ann" });
    const invalidated = stale();
    expect(invalidated).toContain("contact/c1");
    expect(invalidated).toContain("contact/c1/notes");
    expect(invalidated).toContain("ticket/t1");
    expect(invalidated).toContain("tickets");
    expect(invalidated).toContain("company/co1");
    expect(invalidated).not.toContain("contact/c2");
    expect(invalidated).not.toContain("attributeDefs/contact");
    expect(invalidated).not.toContain("tags");
  });

  it("a refused update leaves the cache alone and its error usable", async () => {
    const { wrapper, stale } = setup();
    client.patch.mockRejectedValue(
      new AxiosError("Request failed", "ERR_BAD_REQUEST", undefined, undefined, {
        status: 409,
        data: { detail: "This contact has been anonymized." },
      } as AxiosResponse),
    );

    const { result } = renderHook(() => useUpdateContact(), { wrapper });
    const error = await result.current
      .mutateAsync({ id: "c1", name: "Ann" })
      .catch((err: unknown) => err);

    expect(parseApiError(error).status).toBe(409);
    expect(parseApiError(error).message).toBe("This contact has been anonymized.");
    expect(stale()).toEqual([]);
  });

  it("deleting a contact drops it and refreshes what showed it", async () => {
    const { queryClient, wrapper, stale } = setup();
    client.delete.mockResolvedValue({ data: undefined });

    const { result } = renderHook(() => useDeleteContact(), { wrapper });
    await result.current.mutateAsync("c1");

    expect(client.delete).toHaveBeenCalledWith("/contacts/c1/");
    expect(queryClient.getQueryState(["contact", "c1"])).toBeUndefined();
    expect(queryClient.getQueryState(["contact", "c1", "notes"])).toBeUndefined();
    expect(queryClient.getQueryState(["contact", "c2"])).toBeDefined();
    const invalidated = stale();
    expect(invalidated).toContain("contacts");
    expect(invalidated).toContain("tickets");
    expect(invalidated).toContain("companies");
  });

  it("adding a note only refreshes the notes of that contact", async () => {
    const { wrapper, stale } = setup();
    client.post.mockResolvedValue({ data: { id: "n1" } });

    const { result } = renderHook(() => useCreateContactNote("c1"), { wrapper });
    await result.current.mutateAsync("Called them");

    expect(client.post).toHaveBeenCalledWith("/contacts/c1/notes/", {
      body: "Called them",
    });
    expect(stale()).toEqual(["contact/c1/notes"]);
  });

  it("anonymizing also refreshes the tickets", async () => {
    const { wrapper, stale } = setup();
    client.post.mockResolvedValue({ data: { id: "c1", is_anonymized: true } });

    const { result } = renderHook(() => useAnonymizeContact(), { wrapper });
    await result.current.mutateAsync("c1");

    expect(client.post).toHaveBeenCalledWith("/contacts/c1/anonymize/");
    const invalidated = stale();
    expect(invalidated).toEqual(
      expect.arrayContaining([
        "contacts",
        "contact/c1",
        "contact/c1/tickets",
        "contact/c1/notes",
        "companies",
        "company/co1",
        "tickets",
        "ticket/t1",
      ]),
    );
    expect(invalidated).not.toContain("contact/c2");
  });

  it("exporting changes nothing cached", async () => {
    const { wrapper, stale } = setup();
    client.post.mockResolvedValue({ data: { status: "queued" } });

    const { result } = renderHook(() => useExportContact(), { wrapper });
    await expect(result.current.mutateAsync("c1")).resolves.toEqual({
      status: "queued",
    });

    expect(client.post).toHaveBeenCalledWith("/contacts/c1/export/");
    expect(stale()).toEqual([]);
  });
});

describe("company mutations", () => {
  it("creating a company refreshes the list only", async () => {
    const { wrapper, stale } = setup();
    client.post.mockResolvedValue({ data: { id: "co9" } });

    const { result } = renderHook(() => useCreateCompany(), { wrapper });
    await result.current.mutateAsync({ name: "Acme" });

    expect(stale()).toEqual(["companies"]);
  });

  it("updating a company refreshes it and the contacts and tickets showing it", async () => {
    const { wrapper, stale } = setup();
    client.patch.mockResolvedValue({ data: { id: "co1" } });

    const { result } = renderHook(() => useUpdateCompany(), { wrapper });
    await result.current.mutateAsync({ id: "co1", name: "Acme" });

    expect(client.patch).toHaveBeenCalledWith("/companies/co1/", { name: "Acme" });
    expect(stale()).toEqual(
      expect.arrayContaining([
        "companies",
        "company/co1",
        "company/co1/contacts",
        "contacts",
        "contact/c1",
        "contact/c2",
        "tickets",
        "ticket/t1",
      ]),
    );
    expect(stale()).not.toContain("attributeDefs/company");
  });

  it("deleting a company drops it and refreshes its former contacts", async () => {
    const { queryClient, wrapper, stale } = setup();
    client.delete.mockResolvedValue({ data: undefined });

    const { result } = renderHook(() => useDeleteCompany(), { wrapper });
    await result.current.mutateAsync("co1");

    expect(queryClient.getQueryState(["company", "co1"])).toBeUndefined();
    expect(queryClient.getQueryState(["company", "co1", "contacts"])).toBeUndefined();
    expect(stale()).toEqual(
      expect.arrayContaining([
        "companies",
        "contacts",
        "contact/c1",
        "tickets",
      ]),
    );
  });
});

describe("attribute definition mutations", () => {
  it("creating refreshes the definitions of that entity only", async () => {
    const { wrapper, stale } = setup();
    client.post.mockResolvedValue({ data: { id: "d1" } });

    const { result } = renderHook(() => useCreateAttributeDef("contact"), { wrapper });
    await result.current.mutateAsync({ key: "plan", label: "Plan", type: "string" });

    expect(client.post).toHaveBeenCalledWith("/contact-attributes/", {
      key: "plan",
      label: "Plan",
      type: "string",
    });
    expect(stale()).toEqual(["attributeDefs/contact"]);
  });

  it("updating refreshes the definitions of that entity only", async () => {
    const { wrapper, stale } = setup();
    client.patch.mockResolvedValue({ data: { id: "d1" } });

    const { result } = renderHook(() => useUpdateAttributeDef("company"), { wrapper });
    await result.current.mutateAsync({ id: "d1", is_archived: true });

    expect(client.patch).toHaveBeenCalledWith("/company-attributes/d1/", {
      is_archived: true,
    });
    expect(stale()).toEqual(["attributeDefs/company"]);
  });
});
