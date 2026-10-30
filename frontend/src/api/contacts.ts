/**
 * API functions for contact operations.
 *
 * A refused write is a 400 by field, and by key for `attributes`, or a 409 for an
 * anonymized contact: read them with `parseApiError`.
 */

import { apiClient } from "./client";
import type { Contact, ContactNote, PaginatedResponse, TicketListItem } from "@/types";

/** The API's cap on a timeline's tickets, the latest ones. A full list may be cut off. */
export const TIMELINE_TICKETS_LIMIT = 100;

export interface ContactFilters {
  search?: string;
  company?: string;
  email_verified?: boolean;
  last_seen_after?: string;
  last_seen_before?: string;
  ordering?: string;
  page?: number;
  page_size?: number;
  /** Exact match on custom attributes, by key. */
  attrs?: Record<string, string>;
}

/** The fields an agent can write. `external_id` and `declared_email` aren't. */
export type ContactWrite = Partial<
  Pick<
    Contact,
    | "name"
    | "email"
    | "phone"
    | "avatar_url"
    | "job_title"
    | "locale"
    | "timezone"
    | "company"
    | "is_unsubscribed"
    | "attributes"
  >
>;

/** Query params of a directory list: `attrs` as `attr.<key>`, without what isn't set. */
export function toListParams({
  attrs = {},
  ...filters
}: { attrs?: Record<string, string> } & Record<string, unknown>): Record<
  string,
  unknown
> {
  const entries = [
    ...Object.entries(attrs).map(([key, value]) => [`attr.${key}`, value] as const),
    ...Object.entries(filters),
  ];
  return Object.fromEntries(
    entries.filter(([, value]) => value !== undefined && value !== ""),
  );
}

export async function fetchContacts(
  filters: ContactFilters = {},
): Promise<PaginatedResponse<Contact>> {
  const response = await apiClient.get<PaginatedResponse<Contact>>("/contacts/", {
    params: toListParams({ ...filters }),
  });
  return response.data;
}

export async function fetchContact(id: string): Promise<Contact> {
  const response = await apiClient.get<Contact>(`/contacts/${id}/`);
  return response.data;
}

export async function createContact(data: ContactWrite): Promise<Contact> {
  const response = await apiClient.post<Contact>("/contacts/", data);
  return response.data;
}

export async function updateContact(id: string, data: ContactWrite): Promise<Contact> {
  const response = await apiClient.patch<Contact>(`/contacts/${id}/`, data);
  return response.data;
}

export async function deleteContact(id: string): Promise<void> {
  await apiClient.delete(`/contacts/${id}/`);
}

export async function fetchContactTickets(id: string): Promise<TicketListItem[]> {
  const response = await apiClient.get<TicketListItem[]>(`/contacts/${id}/tickets/`);
  return response.data;
}

export async function fetchContactNotes(id: string): Promise<ContactNote[]> {
  const response = await apiClient.get<ContactNote[]>(`/contacts/${id}/notes/`);
  return response.data;
}

export async function createContactNote(
  id: string,
  body: string,
): Promise<ContactNote> {
  const response = await apiClient.post<ContactNote>(`/contacts/${id}/notes/`, {
    body,
  });
  return response.data;
}

/** Admin only. Queued: the requester gets the archive by email. */
export async function exportContact(id: string): Promise<{ status: string }> {
  const response = await apiClient.post<{ status: string }>(
    `/contacts/${id}/export/`,
  );
  return response.data;
}

/** Admin only, and irreversible. */
export async function anonymizeContact(id: string): Promise<Contact> {
  const response = await apiClient.post<Contact>(`/contacts/${id}/anonymize/`);
  return response.data;
}
