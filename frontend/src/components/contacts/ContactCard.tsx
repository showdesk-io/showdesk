/**
 * Who a ticket is from, on its sidebar: the contact it's linked to, and whether the
 * sender proved being that contact.
 *
 * The badges are about the contact's own addresses. The sender hint and the requester are
 * about this ticket: a forged ticket can link to a verified contact.
 */

import { Link } from "react-router";
import { TIMELINE_TICKETS_LIMIT } from "@/api/contacts";
import { useContactTickets } from "@/hooks/useContacts";
import type { ContactSummary, Ticket } from "@/types";
import { ANONYMIZED_CONTACT } from "./anonymized";
import { Fact, SectionHeading } from "./DetailParts";
import { NO_VALUE } from "./format";
import { Avatar } from "./ListParts";
import { UnverifiedBadge } from "./UnverifiedBadge";

const isSame = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase();

/** What the ticket says of its sender and the contact doesn't, each empty if nothing. */
function otherRequester(ticket: Ticket, contact: ContactSummary) {
  const account = ticket.requester_detail;
  const name =
    ticket.requester_name.trim() ||
    (account ? `${account.first_name} ${account.last_name}`.trim() : "");
  const email = ticket.requester_email.trim() || account?.email || "";
  return {
    name: isSame(name, contact.name) || isSame(name, contact.display_name) ? "" : name,
    email: isSame(email, contact.email) || isSame(email, contact.declared_email) ? "" : email,
  };
}

function OtherTickets({ contactId, ticketId }: { contactId: string; ticketId: string }) {
  const { data: tickets } = useContactTickets(contactId);
  let count = NO_VALUE;
  if (tickets) {
    const others = tickets.filter((ticket) => ticket.id !== ticketId).length;
    // The API returns the latest ones only.
    count = tickets.length >= TIMELINE_TICKETS_LIMIT ? `${others}+` : String(others);
  }
  return <p className="text-gray-500">Other tickets: {count}</p>;
}

function ContactLink({ contactId, children }: { contactId: string; children: string }) {
  return (
    <Link
      to={`/contacts/${contactId}`}
      className="break-words font-medium text-gray-900 hover:text-primary-700"
    >
      {children}
    </Link>
  );
}

export function ContactCard({
  contact,
  ticket,
}: {
  contact: ContactSummary;
  ticket: Ticket;
}) {
  // An anonymized ticket lost its session, so its sender reads as unverified whoever it
  // was, and what it says of its requester went with the contact's data.
  if (contact.is_anonymized) {
    return (
      <section aria-label="Contact" className="mb-6 text-sm">
        <SectionHeading>Contact</SectionHeading>
        <div className="space-y-1">
          <ContactLink contactId={contact.id}>{ANONYMIZED_CONTACT}</ContactLink>
          <OtherTickets contactId={contact.id} ticketId={ticket.id} />
        </div>
      </section>
    );
  }

  const company = contact.company_detail;
  const requester = otherRequester(ticket, contact);

  return (
    <section aria-label="Contact" className="mb-6 text-sm">
      <SectionHeading>Contact</SectionHeading>
      <div className="space-y-2">
        <ContactLink contactId={contact.id}>{contact.display_name}</ContactLink>

        {contact.email && (
          <p className="flex flex-wrap items-center gap-2 text-gray-500">
            <span className="break-all">{contact.email}</span>
            {!contact.email_verified && <UnverifiedBadge />}
          </p>
        )}
        {contact.declared_email && contact.declared_email !== contact.email && (
          <Fact label="Declared (unverified)">
            <span className="flex flex-wrap items-center gap-2">
              <span className="break-all">{contact.declared_email}</span>
              <UnverifiedBadge />
            </span>
          </Fact>
        )}

        {company && (
          <div className="flex items-center gap-2">
            <Avatar url={company.logo_url} name={company.name} square />
            <div className="min-w-0">
              <Link
                to={`/companies/${company.id}`}
                className="break-words text-primary-700 hover:underline"
              >
                {company.name}
              </Link>
              {company.plan && <p className="text-xs text-gray-500">{company.plan}</p>}
            </div>
          </div>
        )}

        <OtherTickets contactId={contact.id} ticketId={ticket.id} />

        {ticket.sender_verified === false && (
          <div className="rounded-lg bg-yellow-50 px-3 py-2 text-xs text-yellow-800">
            <p className="font-medium">Unverified sender</p>
            <p className="mt-0.5">
              Nothing proves this contact wrote this ticket. Check before sharing account
              details.
            </p>
          </div>
        )}

        {(requester.name || requester.email) && (
          <Fact label="Requester on this ticket">
            {requester.name && <p>{requester.name}</p>}
            {requester.email && <p className="break-all text-gray-500">{requester.email}</p>}
          </Fact>
        )}
      </div>
    </section>
  );
}
