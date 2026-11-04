/**
 * Tests for the organization domain API module: the sending actions' routes, and the
 * verify action's two answers.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OrganizationDomain } from "@/types";
import { apiClient } from "../client";
import {
  checkSending,
  createOrganizationDomain,
  disableSending,
  enableSending,
  verifyOrganizationDomain,
} from "../organizationDomains";

vi.mock("../client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

const client = vi.mocked(apiClient);
const row = { id: "d1", domain: "acme.com" } as OrganizationDomain;

beforeEach(() => {
  vi.resetAllMocks();
});

describe("sending actions", () => {
  it("enable, check and disable on the row's sending routes, answering the row", async () => {
    client.post.mockResolvedValue({ data: row });
    client.delete.mockResolvedValue({ data: row });

    expect(await enableSending("d1")).toBe(row);
    expect(await checkSending("d1")).toBe(row);
    expect(await disableSending("d1")).toBe(row);

    expect(client.post).toHaveBeenNthCalledWith(1, "/organization-domains/d1/sending/");
    expect(client.post).toHaveBeenNthCalledWith(2, "/organization-domains/d1/sending/check/");
    expect(client.delete).toHaveBeenCalledWith("/organization-domains/d1/sending/");
  });

  it("creates a domain only to send from it", async () => {
    client.post.mockResolvedValue({ data: row });

    await createOrganizationDomain({
      domain: "acme.com",
      is_sending: true,
      is_branding: false,
      is_email_routing: false,
      verification_method: "dns_txt",
    });

    expect(client.post).toHaveBeenCalledWith("/organization-domains/", {
      domain: "acme.com",
      is_sending: true,
      is_branding: false,
      is_email_routing: false,
      verification_method: "dns_txt",
    });
  });
});

describe("verifyOrganizationDomain", () => {
  it("reads a 202 as still pending, with the row inside", async () => {
    client.post.mockResolvedValueOnce({
      status: 202,
      data: { detail: "TXT record not found yet.", code: "still_pending", domain: row },
    });
    expect(await verifyOrganizationDomain("d1")).toEqual({ verified: false, domain: row });

    client.post.mockResolvedValueOnce({ status: 200, data: row });
    expect(await verifyOrganizationDomain("d1")).toEqual({ verified: true, domain: row });
  });
});
