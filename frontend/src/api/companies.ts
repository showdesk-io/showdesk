/**
 * API functions for company operations.
 *
 * A refused write is a 400 by field, and by key for `attributes`, and deleting a company
 * can be a 409: read them with `parseApiError`.
 */

import { apiClient } from "./client";
import { toListParams } from "./contacts";
import type { Company, Contact, PaginatedResponse, TicketListItem } from "@/types";

export interface CompanyFilters {
  search?: string;
  ordering?: string;
  page?: number;
  page_size?: number;
  /** Exact match on custom attributes, by key. */
  attrs?: Record<string, string>;
}

/** The fields an agent can write. `external_id` isn't. */
export type CompanyWrite = Partial<
  Pick<
    Company,
    | "name"
    | "domain"
    | "logo_url"
    | "industry"
    | "size"
    | "website"
    | "plan"
    | "mrr_cents"
    | "health_score"
    | "signed_up_at"
    | "churned_at"
    | "attributes"
  >
>;

export async function fetchCompanies(
  filters: CompanyFilters = {},
): Promise<PaginatedResponse<Company>> {
  const response = await apiClient.get<PaginatedResponse<Company>>("/companies/", {
    params: toListParams({ ...filters }),
  });
  return response.data;
}

export async function fetchCompany(id: string): Promise<Company> {
  const response = await apiClient.get<Company>(`/companies/${id}/`);
  return response.data;
}

export async function createCompany(
  data: CompanyWrite & Pick<Company, "name">,
): Promise<Company> {
  const response = await apiClient.post<Company>("/companies/", data);
  return response.data;
}

export async function updateCompany(id: string, data: CompanyWrite): Promise<Company> {
  const response = await apiClient.patch<Company>(`/companies/${id}/`, data);
  return response.data;
}

/** Admin only. Its contacts stay, without a company. */
export async function deleteCompany(id: string): Promise<void> {
  await apiClient.delete(`/companies/${id}/`);
}

export async function fetchCompanyContacts(id: string): Promise<Contact[]> {
  const response = await apiClient.get<Contact[]>(`/companies/${id}/contacts/`);
  return response.data;
}

export async function fetchCompanyTickets(id: string): Promise<TicketListItem[]> {
  const response = await apiClient.get<TicketListItem[]>(`/companies/${id}/tickets/`);
  return response.data;
}
