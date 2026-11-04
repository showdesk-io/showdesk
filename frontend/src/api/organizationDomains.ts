/**
 * API client for the per-org OrganizationDomain endpoints.
 *
 * Verification is server-managed: status / token / verified_at are read-
 * only, set by the create endpoint (admin_email auto-verify), the verify
 * action (DNS challenge), or the regenerate-token action.
 *
 * Sending from a verified domain is turned on and off by its own actions, which
 * answer the row, or `{detail, code}` when they refuse. They are 404 when the
 * server has no sending provider.
 */

import { apiClient } from "./client";
import type {
  OrganizationDomain,
  PaginatedResponse,
  DomainVerificationMethod,
} from "@/types";

export interface CreateDomainPayload {
  domain: string;
  is_branding?: boolean;
  is_email_routing?: boolean;
  /** Only while the server has a sending provider. */
  is_sending?: boolean;
  verification_method?: DomainVerificationMethod;
}

export interface UpdateDomainPayload {
  is_branding?: boolean;
  is_email_routing?: boolean;
}

export async function fetchOrganizationDomains(): Promise<OrganizationDomain[]> {
  const response = await apiClient.get<PaginatedResponse<OrganizationDomain>>(
    "/organization-domains/",
  );
  return response.data.results;
}

export async function createOrganizationDomain(
  payload: CreateDomainPayload,
): Promise<OrganizationDomain> {
  const response = await apiClient.post<OrganizationDomain>(
    "/organization-domains/",
    payload,
  );
  return response.data;
}

export async function updateOrganizationDomain(
  id: string,
  payload: UpdateDomainPayload,
): Promise<OrganizationDomain> {
  const response = await apiClient.patch<OrganizationDomain>(
    `/organization-domains/${id}/`,
    payload,
  );
  return response.data;
}

export async function deleteOrganizationDomain(id: string): Promise<void> {
  await apiClient.delete(`/organization-domains/${id}/`);
}

export interface VerifyResponse {
  // 200: returns the updated OrganizationDomain (status=verified)
  // 202: returns { detail, code: "still_pending", domain: OrganizationDomain }
  detail?: string;
  code?: string;
  domain?: OrganizationDomain;
  // Spread of OrganizationDomain when status was 200:
  id?: string;
  status?: string;
}

export async function verifyOrganizationDomain(
  id: string,
): Promise<{ verified: boolean; domain: OrganizationDomain }> {
  const response = await apiClient.post<VerifyResponse | OrganizationDomain>(
    `/organization-domains/${id}/verify/`,
    {},
    { validateStatus: (s) => s === 200 || s === 202 },
  );
  if (response.status === 202) {
    const data = response.data as VerifyResponse;
    return { verified: false, domain: data.domain as OrganizationDomain };
  }
  return { verified: true, domain: response.data as OrganizationDomain };
}

export async function regenerateOrganizationDomainToken(
  id: string,
): Promise<OrganizationDomain> {
  const response = await apiClient.post<OrganizationDomain>(
    `/organization-domains/${id}/regenerate-token/`,
  );
  return response.data;
}

/** Registers the domain with the sending provider, and answers its DNS records. */
export async function enableSending(id: string): Promise<OrganizationDomain> {
  const response = await apiClient.post<OrganizationDomain>(
    `/organization-domains/${id}/sending/`,
  );
  return response.data;
}

/** Checks the domain's sending records now; refused (429) twice in 30 s. */
export async function checkSending(id: string): Promise<OrganizationDomain> {
  const response = await apiClient.post<OrganizationDomain>(
    `/organization-domains/${id}/sending/check/`,
  );
  return response.data;
}

/** Stops sending from the domain: replies go out from the inbound address again. */
export async function disableSending(id: string): Promise<OrganizationDomain> {
  const response = await apiClient.delete<OrganizationDomain>(
    `/organization-domains/${id}/sending/`,
  );
  return response.data;
}
