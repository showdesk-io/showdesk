/**
 * API functions for the email channel's mailboxes and their log of received mail.
 * Agents read them, admins write them and replay failed mails.
 */

import { apiClient } from "./client";
import type { InboundLogEntry, Mailbox, PaginatedResponse } from "@/types";

export type MailboxCreate = Pick<Mailbox, "name"> &
  Partial<Pick<Mailbox, "public_address" | "default_team">>;

export type MailboxUpdate = Partial<
  Pick<Mailbox, "name" | "public_address" | "default_team" | "is_active">
>;

export async function fetchMailboxes(): Promise<Mailbox[]> {
  const response = await apiClient.get<Mailbox[]>("/mailboxes/");
  return response.data;
}

export async function createMailbox(data: MailboxCreate): Promise<Mailbox> {
  const response = await apiClient.post<Mailbox>("/mailboxes/", data);
  return response.data;
}

export async function updateMailbox(id: string, data: MailboxUpdate): Promise<Mailbox> {
  const response = await apiClient.patch<Mailbox>(`/mailboxes/${id}/`, data);
  return response.data;
}

/** Mail forwarded to the previous address is refused from then on. */
export async function regenerateMailboxAddress(id: string): Promise<Mailbox> {
  const response = await apiClient.post<Mailbox>(`/mailboxes/${id}/regenerate-address/`);
  return response.data;
}

/** Forgets the proof of forwarding: customers reply to a reply address again. */
export async function resetMailboxForwarding(id: string): Promise<Mailbox> {
  const response = await apiClient.post<Mailbox>(`/mailboxes/${id}/reset-forwarding/`);
  return response.data;
}

/** The mailbox's ignored and failed mails, newest first. */
export async function fetchMailboxInbound(
  id: string,
  page: number,
): Promise<PaginatedResponse<InboundLogEntry>> {
  const response = await apiClient.get<PaginatedResponse<InboundLogEntry>>(
    `/mailboxes/${id}/inbound/`,
    { params: { page } },
  );
  return response.data;
}

/** Runs a failed mail through the pipeline again. */
export async function replayInboundEmail(id: string): Promise<void> {
  await apiClient.post(`/inbound-emails/${id}/replay/`);
}
