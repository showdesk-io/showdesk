/**
 * How a ticket shows a requester whose personal data was removed.
 */

import type { TicketListItem } from "@/types";

export const ANONYMIZED_CONTACT = "Anonymized contact";

/** Of the addresses anonymization gives a contact, and copies on their tickets. */
const ANONYMIZED_EMAIL_SUFFIX = "@example.invalid";

type Requester = Pick<
  TicketListItem,
  "contact_detail" | "requester_detail" | "requester_email"
>;

/**
 * The contact says so, whatever its address: a visitor can declare one at that domain. A
 * ticket with no contact, scrubbed that way or left by a deleted contact, only has the
 * address to tell.
 */
export function isRequesterAnonymized(ticket: Requester): boolean {
  if (ticket.contact_detail) return ticket.contact_detail.is_anonymized;
  return ticket.requester_email.toLowerCase().endsWith(ANONYMIZED_EMAIL_SUFFIX);
}

/** The requester's address, as a ticket line shows it. */
export function requesterAddress(ticket: Requester): string {
  return isRequesterAnonymized(ticket)
    ? ANONYMIZED_CONTACT
    : (ticket.requester_detail?.email ?? ticket.requester_email);
}
